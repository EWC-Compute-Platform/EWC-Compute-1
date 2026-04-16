# EWC Compute — Substack Series Content Plan
### Engineering World Company · Platform Build Series
**Status:** Living document — updated as architecture evolves
**Last updated:** April 2026

---

## Series architecture

The series runs in two tracks that alternate in a single publication feed.

**Track A — Platform Build posts** are technical deep-dives tied directly to each build phase. They are the intellectual record of *why* each architectural decision was made, written as the code is being built. They establish Engineering World Company's credibility as the team building a serious platform.

**Track B — Engineering Methods posts** are domain deep-dives (like the AB-UPT and space data centres analyses) that are not phase-dependent. They seed the Physical AI Assistant corpus and serve as standalone reference content for the engineering audience. They maintain publication frequency when a build phase is between milestones.

The two tracks reinforce each other: methods posts establish domain credibility that makes the platform posts believable; platform posts give the methods posts commercial context that justifies the depth.

---

## Published

### Post 1 — "From Writing to Building: Introducing EWC Compute"
**Track:** A · **Status:** Published
**Purpose:** Platform introduction. Establishes the market gap, differentiation argument, and commercial intent.
**Key content:** Market analysis (SimScale/rescale/Xcelerator gap), four pillars, OpenUSD format decision, `ai_mode` field, ANSYS licence pricing comparison, call to action.

### Post 2 — "The Kickoff: Architecture, Decisions, and What We Are Actually Building"
**Track:** A · **Status:** Draft ready — scheduled 6 April 2026
**Purpose:** Full technical architecture post. Readers who clicked through from Post 1 get the complete stack, the reasoning behind every layer, and the build sequence.
**Key content:** Five-layer stack, NVIDIA CAE five-step canonical workflow, PhysicsNeMo/NIM/Warp/CUDA-X (cuDSS + AmgX), seven simulation domains including EDA and Collision, five Phase 0 ADRs, 36-week build sequence.

---

## In series — planned

### Post 3 — "Building an Engineering Copilot That Does Not Hallucinate Physics"
**Track:** A · **Timing:** Week 3 · **Platform phase:** 1

**Purpose:** Deep-dive into the Physical AI Assistant — the most architecturally distinct pillar and the hardest to do correctly. Establishes why EWC Compute's approach is structurally different from general-purpose AI products.

**Core technical content:**
- DSR-CRAG pipeline: how the corrective loop differs from standard RAG; why retrieval without correction is insufficient for physics-critical queries
- NVIDIA NIM inference serving: what versioned model endpoints give over raw API calls; OpenAI-compatible interface; how model rollback works against accuracy benchmarks
- Engineering corpus construction: what goes in, how it is chunked and embedded, how the AB-UPT and space data centres posts become retrievable structured knowledge
- Uncertainty quantification in the UI: the `retrieved from [source], confidence: high` vs `model estimate, confidence: moderate` distinction; why this is enforced at architecture level not UX
- Human-in-the-loop confirmation gate: how the agent orchestrator routes proposed actions; what "no write access without confirmation" means in practice
- Honest scope limits: what the assistant declines and why that is the right design

**Engineering methods crossover:** Reference the AB-UPT post as an example of corpus-grade physics content.

---

### Post 4 — "Sim Templates and the ai_mode Decision: Generative, Surrogate, or Principled Solve?"
**Track:** A · **Timing:** Week 5 · **Platform phase:** 2

**Purpose:** The deepest technical post in the series. The three AI modes as a genuine trade-off analysis — not marketing copy — with engineering rigour and citations.

**Core technical content:**
- `generative` mode: PhysicsNeMo cWGAN-GP architecture; conditional generation for design space exploration; hard physics constraints by construction vs post-hoc filtering; failure modes (sparse training data, out-of-distribution geometry)
- `surrogate` mode: PINNs vs AB-UPT vs other surrogate architectures; CAD-native inference breakthrough (no meshing); inference speed vs accuracy trade-off; domain validity bounds; NVIDIA Warp validation layer
- `principled_solve` mode: cuDSS (direct sparse, FEM/EDA/collision) vs AmgX (algebraic multigrid, large-scale CFD/EM) routing logic; the 20–500× CUDA-X acceleration range; COMSOL and Ansys Fluent adapter design
- Why hiding `ai_mode` behind "AI-optimised" is an engineering anti-pattern and an architectural honesty failure
- Template versioning and reproducibility: guaranteeing the same result three months later despite model updates

**Engineering methods crossover:** The AB-UPT post is the direct reference architecture for surrogate mode. This post closes the loop between that research coverage and the platform implementation.

---

### Post 5 — "Digital Twin Engine: OpenUSD, Physics Parameterisation, and the Meshing Problem"
**Track:** A · **Timing:** Week 7 · **Platform phase:** 3

**Purpose:** The twin engine in technical depth. The meshing problem is the central engineering insight — CAD-native surrogate inference changes the preprocessing cost structure that has constrained simulation accessibility for decades.

**Core technical content:**
- OpenUSD as native format: ADR-002 reasoning in full; why every other format choice creates proprietary lock-in; GTC 2026 ecosystem commitments as market validation
- Three fidelity levels (geometric, behavioural, predictive): when each is appropriate; how the platform enforces the choice
- The meshing problem: what mesh generation actually costs in engineer-hours; why it is the hidden bottleneck in simulation accessibility; how AB-UPT eliminates it for surrogate paths; why `principled_solve` still needs a mesh and how templates abstract it
- SimReady SDK compatibility: what certified assets from ABB/Fanuc/Caterpillar/Siemens give an engineer; SimReady validation checks
- OpenUSD Exchange SDK (Phase 3): production-grade I/O vs development I/O; what changes at the API level
- ovphysx (Phase 3): physics validation within the USD context; what it covers and what it does not

**Engineering methods crossover:** Reference DrivAerML and AB-UPT numbers (150M cells, single GPU, under-one-day training) as the concrete CAD-native surrogate target.

---

### Post 6 — "KPI Dashboards: Engineering Monitoring and the Problem of Simulation History"
**Track:** A · **Timing:** Week 9 · **Platform phase:** 4

**Purpose:** Why simulation monitoring is underbuilt in most engineering workflows. Treating simulation results as time series rather than files changes the engineering decision-making process.

**Core technical content:**
- Why engineers lose simulation history: file-centric workflows, no project continuity, decision context locked in engineers' heads
- MongoDB time-series collections for engineering data: why Atlas time-series is the right data model; indexing strategy
- Dashboard widget types: convergence history, parameter sweep Pareto fronts, fabrication readiness (DRC, tolerance), queue position, threshold alerts via WebSocket
- The digital thread: NVIDIA's CAE documentation names traceability as a core benefit — connecting geometry, simulation data, and engineering decisions across the product lifecycle. This is what the dashboard layer implements at the project level
- Pareto front visualisation: how to read it; what decisions it enables that an individual result file does not
- Real-time monitoring via WebSockets: Celery worker → frontend subscription pattern; why polling is not acceptable for long-running CFD jobs

---

### Post 7 — "The Simulation Bridge: Solver-Agnostic Architecture and the 500× Question"
**Track:** A · **Timing:** Week 11 · **Platform phase:** 2–3

**Purpose:** The most technically-focused post for developer contributors and engineering firm CTOs. Explains the adapter pattern, CUDA-X solver routing, and what the 500× headline number actually means for a real engineering workload.

**Core technical content:**
- Why solver lock-in is the core commercial risk in engineering platforms: Siemens Xcelerator as the canonical example
- The abstract `SolverAdapter` interface and `SimDomain`/`CudaXSolver` enums as shared vocabulary
- `cuda_x_router.py` as the single source of truth: cuDSS vs AmgX routing logic; why adapters are not allowed to choose their own CUDA-X backend
- COMSOL adapter: REST vs LiveLink; which solver backends invoke cuDSS vs iterative paths
- Lumerical adapter: FDTD and MODE; optical simulation specifics
- Ansys Fluent (CFD) and LS-DYNA (Collision): Phase 2–3 plan
- EDA stub: what full implementation requires (Cadence/Synopsys API); why it is Phase 3
- The 500× figure honestly: the Synopsys + NVIDIA result from GTC 2026; what the components are (GPU hardware + CUDA-X solver + AI physics preconditioning); what a real EWC Compute user can expect for their specific domain and mesh size

---

## Track B — Engineering Methods posts (interleaved)

Written on the existing Engineering World Company editorial model. Each post also seeds the Physical AI Assistant corpus. Planned topics in priority order:

**CFD surrogate methods — Part 2** (follow-up to AB-UPT)
Where current surrogate architectures fail: complex topology, multi-phase flow, strongly nonlinear regimes. What the honest accuracy ceiling is for mesh-free surrogate CFD today.
*Corpus value: seeds surrogate mode validity limits for the Physical AI Assistant.*

**PhysicsNeMo in practice**
What the framework abstracts, what it does not; how PINN training differs from standard neural network training; what "hard constraint enforcement" means in the gradient computation.
*Corpus value: seeds surrogate mode technical detail.*

**The EDA simulation challenge**
GPU-accelerated semiconductor chip design; why EDA is computationally harder than CFD at scale; what cuDSS delivers for sparse matrix problems in circuit simulation; where Cadence/Synopsys sits in the NVIDIA ecosystem.
*Corpus value: seeds EDA domain knowledge for Phase 3.*

**Digital thread and traceability in engineering**
First-principles analysis of what "digital thread" means; the difference between having project history (files) and traceable engineering decisions (structured records). Reference the NVIDIA CAE glossary and what EWC Compute's audit log implements.
*Corpus value: seeds KPI Dashboard and audit log sections.*

**Collision simulation and crashworthiness**
LS-DYNA and explicit dynamics; what makes crash simulation computationally distinct from FEM; where AI surrogates currently work and fail in collision domains.
*Corpus value: seeds Collision domain for Phase 3.*

---

## Publication frequency

Two posts per month is the sustainable minimum for algorithmic visibility and reader retention without compromising quality. Recommended cadence:

- Week 1: Track A pillar deep-dive
- Week 3: Track B engineering methods post

Phase build-in-public updates (400–600 words) are posted as Substack Notes rather than full articles — they maintain frequency without full editorial production.

---

## Series standing tagline

Every post closes with:

*Engineering World Company covers the methods, tools, and decisions behind modern computational engineering — and builds the platform to make them accessible.*

---

*This document is the editorial planning record for the EWC Compute build series. It is updated as the architecture evolves.*
