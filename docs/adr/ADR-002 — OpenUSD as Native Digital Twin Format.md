# ADR-002 — OpenUSD as Native Digital Twin Format

**Status:** Accepted
**Date:** March 2026
**Deciders:** Engineering World Company
**Relates to:** ADR-001 (technology stack), ADR-003 (Sim Bridge adapter pattern)

---

## Context

The Digital Twin Engine is the foundational pillar of EWC Compute. Every
other pillar depends on it: Sim Templates operate on twin geometry and
physics parameterisation; KPI Dashboards track simulation results tied to
specific twin versions; the Physical AI Assistant reasons about twin state.

A digital twin requires a persistent, structured file format. The choice
of format is an irreversible infrastructure decision. Every twin created
on the platform, every simulation job dispatched, every fabrication export
generated, and every Omniverse collaboration session will use this format.
The format also determines which external tools — CAD packages, simulation
suites, visualisation environments — can consume EWC Compute twins without
a conversion step.

The requirements:

**Technical requirements**
- Carry geometry, material properties, physics parameterisation, and
  metadata in a single self-describing file
- Support layered composition — multiple contributors (geometry, physics,
  materials) writing into a single stage without overwriting each other
- Support schema extension — EWC Compute's domain-specific parameterisation
  (fidelity level, ai_mode, solver configuration) must attach to the
  standard schema without breaking interoperability
- Readable and writable from Python without a proprietary runtime
- Support streaming and sparse access for large assemblies
- Support time-varying data for predictive twin state (Phase 3+)

**Strategic requirements**
- Interoperable with NVIDIA Omniverse — the Digital Twin Engine must
  produce twins that Omniverse can ingest directly, enabling the Phase 4
  Nucleus collaboration layer and the Phase 3 SimReady certification path
- Interoperable with the major CAD and simulation vendors — Siemens,
  Dassault, PTC, Ansys, Cadence, ABB, and others must be able to consume
  EWC Compute twins without a proprietary conversion step
- Not proprietary to a single vendor — the format must not create lock-in
  to any company whose business model could change independently of EWC
  Compute's roadmap
- Open-licensed — no licence fee, no royalty, no usage restriction

**Operational requirements**
- Installable via `pip` without a local OpenUSD application installation
- Version-controllable — USD files are ASCII or binary; ASCII `.usda`
  files are human-readable, diffable, and committable to Git

---

## Decision

**We adopt OpenUSD (Universal Scene Description, usd-core 25.08) as the
native digital twin format for the EWC Compute Digital Twin Engine.**

OpenUSD is the only format that satisfies every requirement in the list
above. No other format comes close on the strategic interoperability
requirement alone.

### What OpenUSD is

Universal Scene Description was developed by Pixar to handle the
composition complexity of animated feature film production. It was
open-sourced in 2016 under the modified Apache 2.0 licence. In 2022,
NVIDIA built the Omniverse platform on top of it. In 2023 and 2024, the
Alliance for OpenUSD (AOUSD) was formed with founding members including
Apple, Adobe, Autodesk, NVIDIA, and Pixar, and production-grade
interoperability commitments from Siemens, Dassault Systèmes, PTC,
Ansys, Cadence, ABB, Fanuc, Caterpillar, and others.

For engineering applications specifically, the `UsdPhysics` schema
extension provides rigid body physics, collision geometry, joints,
mass properties, and contact parameters — directly relevant to the
Digital Twin Engine's behavioural fidelity level.

### How EWC Compute uses OpenUSD

```python
# usd-core 25.08 — EWC Twin → OpenUSD stage (twin_exporter.py)
from pxr import Usd, UsdGeom, UsdPhysics

def export_twin_to_usd(twin: DigitalTwin, output_path: str) -> None:
    stage = Usd.Stage.CreateNew(output_path)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)

    # Geometry layer
    root = UsdGeom.Xform.Define(stage, f"/{twin.name}")
    mesh = UsdGeom.Mesh.Define(stage, f"/{twin.name}/geometry")
    mesh.GetPointsAttr().Set(twin.geometry.vertices)
    mesh.GetFaceVertexIndicesAttr().Set(twin.geometry.face_indices)
    mesh.GetFaceVertexCountsAttr().Set(twin.geometry.face_counts)

    # Physics layer
    UsdPhysics.RigidBodyAPI.Apply(root.GetPrim())

    # EWC custom schema layer (fidelity, ai_mode, solver config)
    prim = root.GetPrim()
    prim.SetCustomDataByKey("ewc:fidelity_level", twin.fidelity_level)
    prim.SetCustomDataByKey("ewc:ai_mode", twin.ai_mode)
    prim.SetCustomDataByKey("ewc:project_id", twin.project_id)

    stage.GetRootLayer().Save()
```

The EWC custom schema (`ewc_twin.usda`) layers EWC-specific metadata
onto the standard USD stage without breaking USD interoperability.
Any USD-compatible tool can open the file and read the geometry and
physics layers; only EWC Compute reads the `ewc:` custom data layer.

### Three fidelity levels and their USD representation

| Fidelity level | USD content | Use case |
| --- | --- | --- |
| `geometric` | `UsdGeom.Mesh` + transforms | Shape, dimensions, interference checking, visualisation |
| `behavioural` | Geometric + `UsdPhysics` APIs + material properties | Physics validation runs, solver dispatch, boundary conditions |
| `predictive` | Behavioural + time-sampled prediction fields + surrogate model reference | Sub-second physics prediction, live KPI feeds |

The fidelity level is stored in the `ewc:fidelity_level` custom data key
and determines which platform operations are available on a given twin.

### The `ewc_twin.usda` custom schema

Located at `nvidia_cae/omniverse/schemas/ewc_twin.usda`. Defines the
EWC-specific attribute namespace:

```
ewc:fidelity_level    — string: geometric | behavioural | predictive
ewc:ai_mode           — string: generative | surrogate | principled_solve
ewc:project_id        — string: UUID of the owning project
ewc:surrogate_compute_budget — string: exploratory | standard | high_fidelity
ewc:solver_domain     — string: cfd | fem | thermal | electromagnetic |
                                eda | collision | optical
ewc:created_at        — string: ISO 8601 UTC
ewc:platform_version  — string: EWC Compute version that created this twin
```

### Phase roadmap for USD usage

| Phase | USD capability | Implementation |
| --- | --- | --- |
| 0 | Core twin export/import | `usd-core` pip package, `twin_exporter.py`, `twin_importer.py` |
| 1 | Twin referenced by AI Assistant corpus | `ewc:project_id` enables project-scoped corpus filtering |
| 2 | Sim Bridge dispatches from USD parameterisation | Solver adapters read physics params from USD stage |
| 3 | SimReady asset ingestion | `simready_adapter.py` + OpenUSD Exchange SDK |
| 3 | Warp validation kernels operate on USD mesh data | `warp_kernels.py` consumes USD geometry directly |
| 4 | Live multi-user USD authoring | Omniverse Nucleus — shared USD stage, real-time collaboration |

---

## Consequences

### Positive

**Solver-agnostic geometry.** The USD stage is the single source of truth
for twin geometry. Every Sim Bridge adapter reads from the same USD stage
rather than maintaining its own geometry representation. Adding a new
solver in Phase 2+ requires only a new adapter that reads from USD —
no new geometry format, no conversion step.

**Omniverse path is trivial.** Because EWC Compute twins are native USD,
integrating with Omniverse Nucleus (Phase 4) and ovphysx (Phase 3) is a
connection, not a migration. The heavy work of format conversion is
eliminated.

**SimReady compatibility.** The SimReady SDK certifies vendor assets
(ABB robots, Fanuc machines, Caterpillar equipment, Siemens PLCs) that
are already in USD format. EWC Compute's USD-native twin engine can
ingest these certified assets without conversion in Phase 3, giving
engineers access to a large library of validated simulation-ready geometry.

**Open standard, open licence.** No licence fee. No royalty. No API key
for the format itself. The modified Apache 2.0 licence is compatible with
EWC Compute's MIT licence. `usd-core` installs with `pip install usd-core`.

**Human-readable ASCII format.** `.usda` files (ASCII USD) are diffable,
committable to Git, and inspectable in a text editor. Twin version history
is a standard Git diff. This is not true of binary formats like GLTF
binary, FBX, or proprietary formats.

**Industry convergence.** GTC 2026 confirmed production-grade USD
interoperability commitments from Siemens Xcelerator, Dassault Systèmes
3DEXPERIENCE, PTC Creo, Ansys, Cadence, and others. An EWC Compute twin
in USD format can be opened by any of these tools without a conversion
step. This is the strongest possible argument for interoperability for
the professional engineering firms that are EWC Compute's target market.

**Version-stable format.** USD's layered composition model means that
adding the `ewc:` custom schema layer does not break USD compatibility.
When the standard evolves (new UsdPhysics capabilities, new UsdGeom
primitives), EWC Compute updates to the new schema version without
breaking existing twins.

### Negative / risks

**`usd-core` Python bindings are large.** The pip package is
approximately 300–500 MB depending on platform. This increases Docker
image size. Mitigation: the base image is built once and cached in the
container registry. Incremental layer rebuilds do not re-download the
package.

**USD expertise is less common than GLTF expertise.** Engineers building
custom integrations against the EWC Compute API may be more familiar
with GLTF than USD. Mitigation: the `twin_exporter.py` and
`twin_importer.py` modules abstract the USD API behind EWC Compute's
`DigitalTwin` Pydantic model. External integrations work with the REST
API, not the USD Python bindings directly.

**`UsdPhysics` schema is not a simulation definition.** USD physics
schemas describe rigid body dynamics and collision geometry. They do
not describe CFD boundary conditions, FEM material failure criteria,
or electromagnetic excitation parameters. The `ewc:` custom schema
carries these domain-specific parameters. This is the correct design —
USD carries what it was designed to carry; EWC Compute's schema carries
the rest — but it means the twin is not self-describing for simulation
without the EWC custom schema layer.

**Phase 3 SimReady requires the OpenUSD Exchange SDK** (not just
`usd-core`). The Exchange SDK is distributed as an NGC container, not
a pip package. Phase 3 deployment will require an additional Docker
image or sidecar service. This is a known and planned cost, not a
surprise.

---

## Alternatives considered

### GLTF 2.0 (Khronos Group)

GLTF is the most widely supported 3D format outside the USD ecosystem.
It has excellent web rendering support (Three.js, Babylon.js) and is
used in game engines, AR/VR frameworks, and web visualisation.

**Rejected** because:
- GLTF has no native physics schema. `KHR_physics_rigid_bodies` is a
  draft extension, not ratified at time of decision.
- GLTF has no composition model. USD's layering (geometry layer,
  physics layer, materials layer, EWC layer) is architecturally central
  to how the platform manages twin state across multiple contributors and
  phases.
- GLTF is not supported by Omniverse natively. Phase 4 Nucleus
  collaboration requires USD.
- GLTF is not the target format for SimReady-certified vendor assets.

Note: EWC Compute's Three.js-based twin viewer in the frontend uses
GLTF for web rendering — a USD stage is converted to GLTF for display
purposes only. The canonical twin format remains USD.

### FBX (Autodesk)

Widely used in game development and CAD interchange. Proprietary format
owned by Autodesk. Closed specification. Rejected on the open standard
requirement alone — a proprietary format creates a dependency on
Autodesk's business decisions. No further analysis required.

### STEP / IGES (ISO 10303 / IGES 5.3)

STEP is the ISO standard for CAD data exchange. It is the format EWC
Compute accepts as *input* — engineers upload STEP or IGES files that
are imported and converted to USD twins.

STEP is rejected as the *native* twin format because it carries geometry
only. It has no physics parameterisation, no material database schema,
no composition model, and no time-varying data support. It is a
transfer format, not a living document format.

### Proprietary JSON schema

Defining an EWC-specific JSON schema for twins would give maximum
flexibility at the cost of all interoperability. Every external tool
integration would require a bespoke converter. Every Omniverse
integration would require a translation layer. Rejected — the
interoperability cost is prohibitive for the target market.

---

## References

- OpenUSD specification: [openusd.org](https://openusd.org)
- Alliance for OpenUSD (AOUSD): [aousd.org](https://aousd.org)
- `usd-core` Python package: [pypi.org/project/usd-core](https://pypi.org/project/usd-core/)
- UsdPhysics schema: [openusd.org/release/api/usd_physics_page_front.html](https://openusd.org/release/api/usd_physics_page_front.html)
- NVIDIA Omniverse SimReady: [developer.nvidia.com/simready](https://developer.nvidia.com/simready)
- GTC 2026: OpenUSD ecosystem interoperability announcements
- EWC Compute Post 4 (2026): *The Digital Twin Engine: OpenUSD, physics
  parameterisation, and the meshing problem*

---

*Engineering World Company · EWC Compute Platform*
*ADRs record the reasoning behind significant architectural decisions.
They are never deleted — superseded ADRs are marked as such.*

