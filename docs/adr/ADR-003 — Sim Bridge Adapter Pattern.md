# ADR-003 — Sim Bridge Adapter Pattern

**Status:** Accepted
**Date:** March 2026
**Deciders:** Engineering World Company
**Relates to:** ADR-001 (technology stack), ADR-002 (OpenUSD twin format),
               ADR-004 (ai_mode explicit field), ADR-006 (Flow360 integration)

---

## Context

EWC Compute dispatches simulation jobs across multiple solvers. The
platform's roadmap covers seven distinct physics domains — CFD, FEM,
thermal, electromagnetic, EDA, collision, and optical — and multiple
commercial and open-source solvers within each domain. The first active
solver is Flow360 (Flexcompute, Phase 2). The roadmap includes COMSOL,
Ansys Fluent, Ansys LS-DYNA, Lumerical (Tidy3D), OpenFOAM, and Cadence/
Synopsys EDA tools across Phase 2–3.

Every solver has a different API. Flow360 is REST over HTTPS, installed
via `pip install flow360`, authenticated with an API key. COMSOL uses a
REST API or LiveLink Python bridge and requires a local licence server.
Ansys Fluent uses a batch submission model or gRPC API and requires a
local installation. Lumerical exposes a Python scripting API. OpenFOAM
is a command-line tool called via subprocess.

Without an explicit architectural boundary, solver-specific code
proliferates throughout the codebase. Simulation dispatch logic touches
job queue routing, template validation, result parsing, status polling,
and audit logging. When a second solver is added, every one of these
concerns needs to handle both solvers. When a third is added, they
handle three. The combinatorial complexity compounds.

There is a second concern specific to engineering platforms: solver
lock-in is the primary commercial risk in this market. Siemens Xcelerator
and Dassault 3DEXPERIENCE succeeded partly by making it expensive to run
simulations outside their ecosystems. An EWC Compute architecture that
couples simulation logic tightly to specific solvers replicates that
lock-in at the platform level — engineers who adopt the platform become
dependent on whichever solvers EWC Compute has tightly integrated,
rather than on the platform itself.

The CUDA-X solver acceleration layer adds a further complexity: cuDSS
(direct sparse, optimal for FEM, structural, EDA, and collision) and
AmgX (algebraic multigrid, optimal for large-scale CFD and electromagnetics)
serve the same acceleration role but are optimal for different problem
types. The routing logic between them must live somewhere. It must be
consistent across all solvers, and it must not be replicated inside each
solver's integration code.

The requirements:

- A new solver can be added to the platform by writing one file, without
  touching job dispatch, template validation, result handling, or audit
  logging
- Solver-specific behaviour (authentication, job submission format, status
  polling, result parsing) is entirely contained within the solver's
  own module
- CUDA-X routing (cuDSS vs AmgX) is decided once, consistently, by a
  single module — never by individual solver adapters
- The platform can run with a subset of solvers available without
  degrading for the solvers that are present
- Solver adapters are independently testable without a running solver
  instance (via mocking the abstract interface)

---

## Decision

**We implement a Sim Bridge adapter pattern: an abstract `SolverAdapter`
base class defines the contract for all solver integrations; each solver
is implemented as a concrete subclass in its own module; a `cuda_x_router`
module owns all CUDA-X solver routing decisions; the `sim_templates`
service interacts only with the abstract interface.**

### The abstract interface

Located at `backend/app/sim_bridge/base.py`:

```python
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any
from pydantic import BaseModel

class SimDomain(str, Enum):
    CFD             = "cfd"
    FEM             = "fem"
    THERMAL         = "thermal"
    ELECTROMAGNETIC = "electromagnetic"
    EDA             = "eda"
    COLLISION       = "collision"
    OPTICAL         = "optical"

class CudaXSolver(str, Enum):
    CUDSS    = "cudss"    # Direct sparse — FEM, EDA, structural, collision
    AMGX     = "amgx"    # Algebraic multigrid — large-scale CFD, EM
    CUSPARSE = "cusparse" # General sparse — fallback / hybrid
    AUTO     = "auto"    # Route via cuda_x_router

class SimRunStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    CANCELLED = "cancelled"

class SolverAdapter(ABC):
    """
    Abstract base for all EWC Compute solver integrations.

    Every solver — Flow360, COMSOL, Ansys Fluent, Lumerical, OpenFOAM —
    implements these four async methods. The sim_templates service calls
    only these four methods. Solver-specific logic never leaks above
    this boundary.
    """

    @property
    @abstractmethod
    def domain(self) -> SimDomain:
        """Physics domain this adapter serves."""
        ...

    @property
    @abstractmethod
    def solver_name(self) -> str:
        """Human-readable solver name for audit logging."""
        ...

    @abstractmethod
    async def dispatch(
        self,
        parameters: dict[str, Any],
        usd_stage_path: str,
    ) -> str:
        """
        Submit a simulation job. Returns a solver-native job ID.

        parameters: validated SimTemplate parameters for this run.
        usd_stage_path: path to the OpenUSD stage for this twin.
        """
        ...

    @abstractmethod
    async def poll_status(self, job_id: str) -> SimRunStatus:
        """Poll the solver for job status. Maps solver-native status to SimRunStatus."""
        ...

    @abstractmethod
    async def fetch_results(self, job_id: str) -> dict[str, Any]:
        """
        Fetch completed job results. Returns a domain-normalised result dict.
        Result structure is defined per domain in the SimRun model.
        """
        ...

    @abstractmethod
    async def cancel(self, job_id: str) -> bool:
        """Cancel a running or pending job. Returns True if successful."""
        ...
```

### CUDA-X routing: a separate concern

`cuda_x_router.py` is the single source of truth for cuDSS vs AmgX
routing. No solver adapter is permitted to choose its own CUDA-X backend.
The routing logic is:

```python
# backend/app/sim_bridge/cuda_x_router.py

def select_cuda_x_solver(
    domain: SimDomain,
    mesh_cells: int,
    problem_type: str | None = None,
) -> CudaXSolver:
    """
    Route to the optimal CUDA-X sparse solver for a given domain and
    problem size. This function is called by sim_templates service,
    not by individual adapters.

    cuDSS  — direct sparse: optimal when the matrix fits in GPU memory.
             Best for FEM, EDA, structural, collision (< ~10M DOF).
    AmgX   — algebraic multigrid: optimal for large problems that do
             not fit in direct solver memory. Best for large-scale CFD
             (> 5M cells) and electromagnetics.
    """
    if domain in (SimDomain.EDA, SimDomain.COLLISION):
        return CudaXSolver.CUDSS

    if domain == SimDomain.FEM:
        # cuDSS is optimal for FEM below 10M degrees of freedom
        return CudaXSolver.CUDSS if mesh_cells < 10_000_000 else CudaXSolver.AMGX

    if domain == SimDomain.CFD:
        return CudaXSolver.AMGX if mesh_cells > 5_000_000 else CudaXSolver.CUDSS

    if domain == SimDomain.ELECTROMAGNETIC:
        return CudaXSolver.AMGX

    if domain == SimDomain.THERMAL:
        # Thermal is typically coupled to FEM or CFD; inherit their routing
        return CudaXSolver.CUDSS if mesh_cells < 5_000_000 else CudaXSolver.AMGX

    if domain == SimDomain.OPTICAL:
        # Optical domain (Tidy3D / Lumerical) uses its own FDTD GPU kernels
        # CUDA-X routing does not apply; return AUTO as a no-op signal
        return CudaXSolver.AUTO

    return CudaXSolver.CUDSS  # Conservative default
```

**Why routing lives outside the adapters:** if cuDSS/AmgX routing lived
inside each adapter, adding a new domain or changing routing thresholds
would require touching every adapter that serves overlapping domains.
Centralised routing means a single change propagates to all adapters
automatically. It also means the routing logic is independently testable
without instantiating any adapter.

### Adapter registry

The `sim_templates` service does not instantiate adapters directly. It
queries a registry that maps `(SimDomain, solver_name)` to an adapter
instance. Adapters are registered at application startup in `main.py`:

```python
# main.py — adapter registration at startup
from app.sim_bridge.flow360 import Flow360Adapter
from app.sim_bridge.comsol import Comsol Adapter
from app.services.sim_templates import register_adapter

register_adapter(Flow360Adapter())
register_adapter(ComsolfAdapter())
```

If an adapter is not registered (because the solver is not configured
in `.env`), the platform degrades gracefully: template dispatch for
that domain returns a `503 Solver Not Available` response rather than
a runtime error. Engineers on a Free tier with only Flow360 configured
see exactly the solvers available to them.

### Concrete adapter structure

Each adapter is one file. The Flow360 adapter illustrates the pattern:

```
backend/app/sim_bridge/
├── base.py             # Abstract SolverAdapter + enums — never modified
├── cuda_x_router.py    # CUDA-X routing — one source of truth
├── flow360.py          # Flow360 (Flexcompute) — Phase 2, active
├── lumerical.py        # Lumerical FDTD/MODE — Phase 2
├── comsol.py           # COMSOL Multiphysics — Phase 2
├── ansys_fluent.py     # Ansys Fluent — Phase 2+
├── ansys_lsdyna.py     # Ansys LS-DYNA — Phase 3+
├── openfoam.py         # OpenFOAM — Phase 2+
└── eda.py              # EDA stub (Cadence/Synopsys) — Phase 3+
```

Adding a Phase 4 solver (e.g. Simulia Abaqus for advanced FEM) requires:
1. Create `abaqus.py` implementing `SolverAdapter`
2. Register it in `main.py`
3. No other file changes

### Domain coverage

| Domain | Phase 2 adapter | Phase 3 adapter | CUDA-X |
| --- | --- | --- | --- |
| CFD | Flow360 (primary), OpenFOAM | Ansys Fluent | AmgX (large mesh), cuDSS (small mesh) |
| FEM / structural | COMSOL | Ansys Mechanical (future) | cuDSS |
| Thermal | Flow360 (conjugate HT), COMSOL | — | cuDSS / AmgX by mesh size |
| Electromagnetic | COMSOL | — | AmgX |
| Optical | Lumerical (FDTD/MODE), Tidy3D | — | FDTD native GPU (no CUDA-X routing) |
| EDA | Stub | Cadence/Synopsys | cuDSS |
| Collision | Stub | Ansys LS-DYNA | cuDSS |

### Flow360 as the reference implementation (ADR-006)

Flow360 is the first fully implemented adapter, commited in Phase 0
infrastructure work. It demonstrates the pattern:

- `dispatch()` calls the Flow360 Python SDK (synchronous calls wrapped
  in `asyncio.get_event_loop().run_in_executor()` to stay non-blocking
  in the FastAPI event loop)
- `poll_status()` maps Flow360 case status strings (`"running"`,
  `"completed"`, `"diverged"`) to `SimRunStatus` enum values
- `fetch_results()` returns a normalised dict of aerodynamic coefficients
  (CL, CD, CM), convergence history, and download URLs for field data
- `cancel()` calls `flow360.Case.cancel(job_id)`

The full reasoning for Flow360 as the primary CFD solver is in ADR-006.

---

## Consequences

### Positive

**New solver = one file.** The four-method interface is the complete
contract. A contributor who knows a solver's API can implement an adapter
without understanding the rest of the platform. The platform's core logic
never changes when a solver is added.

**Solver lock-in is architectural, not accidental.** Engineers using
EWC Compute are not locked to any single solver. If Flexcompute's pricing
changes, or if a new solver proves more accurate for a given domain, the
adapter can be swapped or added without touching template schemas, job
queue logic, result storage, or the Physical AI Assistant. The platform
value is in the orchestration layer, not in any solver relationship.

**CUDA-X routing is consistent and auditable.** Every simulation job
goes through `select_cuda_x_solver()`. The routing decision is logged
in the `AuditEvent` record for every `SimRun`. Engineers and the platform
team can inspect which solver acceleration was used for any historical run.

**Graceful degradation.** An unregistered adapter does not crash the
platform. It returns a clear, actionable error. During development, a
developer can run the full platform with only Flow360 configured and
see the rest of the solver landscape as "not available" rather than
as runtime errors.

**Independent testability.** The abstract interface means each adapter
can be tested by mocking `SolverAdapter` and verifying that the
`sim_templates` service calls the correct methods with correct parameters.
Integration tests that call the real solver API are isolated to the
adapter's own test file.

**Separation of CUDA-X concern.** The routing thresholds
(e.g. `mesh_cells > 5_000_000` for AmgX on CFD) will be calibrated
as benchmark data accumulates in Phase 2–3. Because the routing is
centralised, calibration is a one-line change in one function, not a
cross-adapter change.

### Negative / risks

**Four-method interface may be too coarse for some solvers.** Some
solvers have multi-step workflows (mesh generation → solve → post-process)
that do not map cleanly to a single `dispatch()` call. For those cases,
the adapter encapsulates the multi-step orchestration internally, and
`dispatch()` returns a top-level job ID. The caller sees one job; the
adapter manages the internal steps. This is an acceptable trade-off
for Phase 2. A richer adapter interface (with lifecycle hooks) is a
Phase 3 extension if needed.

**Async wrapping of synchronous SDKs adds latency.** The Flow360 SDK
is synchronous. Wrapping synchronous SDK calls in a thread executor
adds overhead compared to a natively async client. For simulation jobs
that run for minutes or hours, this latency is negligible. For very
large batch dispatch scenarios (Phase 4 Enterprise tier), a natively
async solver client would be preferred.

**EDA and Collision adapters are stubs in Phase 2.** They are present
in the registry as placeholders that return `503` for all operations.
This keeps the domain enum complete and the router consistent but means
engineers attempting EDA or collision runs in Phase 2 receive a clear
"not yet available" response. This is preferable to the domain simply
not existing in the schema.

---

## Alternatives considered

### Direct solver calls in `sim_templates.py`

Rejected. Every added solver would require modifying the central
dispatch service. By Phase 3 with seven domains and multiple adapters
per domain, `sim_templates.py` would handle `if solver == "flow360":
... elif solver == "comsol": ... elif solver == "fluent": ...` chains
across dispatch, status polling, result parsing, and error handling.
This is the pattern that creates solver lock-in and makes the platform
brittle to solver API changes.

### Plugin system with dynamic loading

A plugin architecture (solver adapters as pip-installable packages
loaded at runtime) would allow third-party solver developers to
contribute adapters without touching the EWC Compute codebase.

Rejected for Phase 1–3. The current adapter count (seven planned) does
not justify the operational complexity of dynamic loading, versioning,
and plugin API stability guarantees. The explicit registration pattern
in `main.py` is simpler, more auditable, and easier to debug. A plugin
system is a Phase 4+ consideration if the adapter catalogue grows
beyond internal management.

### Separate microservice per solver

Each solver as a separate FastAPI microservice communicating via REST
or gRPC. This would allow independent scaling and deployment of each
solver integration.

Rejected for Phase 1–2. The operational overhead of seven microservices
(each with its own deployment, health check, logging, and auth) is
disproportionate to the scale. The monolithic FastAPI application with
the adapter pattern achieves the same separation of concerns at
significantly lower operational cost. Extraction to microservices is
a Phase 4 Enterprise tier option if solver-specific scaling becomes
a requirement.

---

## References

- `backend/app/sim_bridge/base.py` — abstract interface implementation
- `backend/app/sim_bridge/cuda_x_router.py` — CUDA-X routing logic
- `backend/app/sim_bridge/flow360.py` — reference adapter implementation
- ADR-006: Flow360 as primary CFD solver and Flexcompute integration strategy
- NVIDIA CUDA-X documentation: cuDSS, AmgX, cuSPARSE
- Flow360 Python SDK: [docs.flexcompute.com/projects/flow360](https://docs.flexcompute.com/projects/flow360)
- EWC Compute Post 2 (2026): *The Kickoff — Architecture, Decisions,
  and What We Are Actually Building* — Sim Bridge framing in prose

---

*Engineering World Company · EWC Compute Platform*
*ADRs record the reasoning behind significant architectural decisions.
They are never deleted — superseded ADRs are marked as such.*

