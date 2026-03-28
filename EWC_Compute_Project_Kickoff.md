# EWC Compute — Project Kickoff Document
### Engineering World Company · Digital Engineering Platform
**Version:** 0.1 — Initial Architecture & Strategy  
**Date:** March 2026  
**Status:** Active — Iteration Phase 0

---

## 1. Vision & Mission

**Vision:** A general-purpose digital industrial engineering platform that places professional-grade computational tools, digital twin capabilities, and AI-assisted engineering reasoning in the hands of any engineer — from a solo practitioner to a mid-size firm — without the enterprise-scale lock-in of incumbents like Dassault Systèmes 3DEXPERIENCE or Siemens Xcelerator.

**Mission:** To build EWC Compute as a modular, open-architecture platform where engineers request, configure, simulate, monitor, and export engineering solutions through a unified, human-in-the-loop interface, underpinned by ethical AI and first-principles engineering.

**The gap we fill:** The market currently bifurcates between expensive, monolithic enterprise suites (CATIA, NX, PAVE360) and disconnected point tools (individual FEA packages, standalone dashboards, isolated CAD tools). EWC Compute targets the professional engineering middle — practitioners who need real capability without seven-figure procurement cycles.

---

## 2. Market Context (March 2026)

The timing is validated by several converging macro-signals:

**NVIDIA GTC 2026 Industry Confirmation:** NVIDIA announced partnerships with Cadence, Dassault Systèmes, PTC, Siemens, and Synopsys to bring CUDA-X, Omniverse, and GPU-accelerated industrial software to major manufacturers including FANUC, Honda, Mercedes-Benz, and TSMC. Jensen Huang declared "the dawn of a new industrial revolution where physical AI and autonomous AI agents are fundamentally reinventing how the world designs, engineers and manufactures." The toolchain is being democratised at the compute level — the platform layer above it is still fragmented.

**Software-Defined Engineering (SDX):** As reported by Siemens' PAVE360 launch at CES 2026, the automotive sector's software complexity has grown ~40% annually since 2021 while productivity has moved only 6% per year. The solution Siemens promotes — concurrent hardware/software co-design using digital twins — is exactly the paradigm EWC Compute must support for general engineering domains.

**Physical AI Realism Calibration:** The physical AI space is at peak hype. The honest assessment from production deployments (Agility Robotics, Vention) is that the bar for commercial utility — not demo — is 99%+ reliability over thousands of cycles. EWC Compute's human-in-the-loop approach is the right response: AI as a capable copilot, not an autonomous replacement for engineer judgment.

**SimScale benchmark:** GPU-accelerated simulation on NVIDIA AI infrastructure is achieving 10–20× speedups over traditional meshing-based solvers for complex industrial applications. This sets the benchmark expectation for our Sim Bridge layer.

---

## 3. Platform Architecture

EWC Compute is built as a five-layer stack:

```
┌─────────────────────────────────────────────────────────────┐
│                   USER ACCESS LAYER                         │
│   Secure Login · Web Dashboard · Role-Based Project Portal  │
├────────────┬───────────────┬────────────────┬───────────────┤
│  DIGITAL   │      SIM      │      KPI       │  PHYSICAL AI  │
│   TWIN     │  TEMPLATES    │  DASHBOARDS    │  ASSISTANT    │
│  ENGINE    │               │                │               │
├────────────┴───────────────┴────────────────┴───────────────┤
│                    PLATFORM CORE                            │
│  FastAPI Gateway · Pydantic Schemas · Agentic Orchestration │
├─────────────────┬──────────────────┬────────────────────────┤
│   MONGODB ATLAS │   SIM BRIDGE     │   FABRICATION EXPORT   │
│  Project Store  │ Lumerical·COMSOL │   GDSII · STL · CAD   │
├─────────────────┴──────────────────┴────────────────────────┤
│           DEVSEOPS · CI/CD · GITHUB · SECURITY              │
└─────────────────────────────────────────────────────────────┘
```

### Layer 1 — User Access Layer
- JWT-based authentication with role differentiation: Individual Engineer, Team Lead, Admin
- Web portal built in React/TypeScript (Lovable for rapid UI iteration)
- Project management interface: create, fork, archive engineering projects
- Credential security: OAuth2 + PKCE flow; secrets management via environment isolation

### Layer 2 — The Four Pillars (Engineering Workbench)

#### Pillar 1: Digital Twin Engine
The centrepiece of the platform. Engineers request a digital twin of a part, sub-assembly, or system component.

- **Input modalities:** CAD file upload (STEP, IGES, DXF), parametric specification form, or natural language description via Physical AI Assistant
- **Twin fidelity levels:** Geometric (mesh/CAD), Behavioural (physics-based simulation), Predictive (ML-surrogate enhanced)
- **DSR-CRAG integration:** Dual-State Corrective RAG for knowledge-augmented twin generation — retrieval from engineering corpus + correction loop to prevent hallucinated physics
- **Simulation coupling:** Twins connect to Sim Bridge for validation runs via Lumerical (optical/photonic domains), COMSOL (multiphysics), or lightweight in-platform FEA
- **Export:** GDSII for photonic/semiconductor layout, STL for additive manufacturing, STEP for mechanical handoff

#### Pillar 2: Computational Templates (Sim Templates)
Software-defined templates for standardised computational workflows.

- **Template structure:** Parametric YAML/JSON schema defining solver type, mesh settings, boundary conditions, material library references, output targets, convergence criteria
- **Template library:** Seeded with foundational engineering categories (thermal, structural, optical, fluid, electromagnetic)
- **User flow:** Engineer selects or customises a template → parameters are validated by Pydantic schemas → job is dispatched to Sim Bridge → results returned to Dashboard
- **Reproducibility:** Every template run is versioned and logged; results traceable to input parameters
- **Collaboration:** Templates are shareable within the project portal; community template marketplace is a Phase 2 commercial feature

#### Pillar 3: KPI Dashboards
Real-time and historical monitoring of engineering figures of merit.

- **Dashboard builder:** Drag-and-drop widget configuration for KPI tiles, trend charts, threshold alerts, simulation result overlays
- **Engineering KPI categories:**
  - Performance: FOM, efficiency, loss, yield
  - Simulation status: convergence, residuals, runtime, queue position
  - Design iteration: parameter sweep history, Pareto fronts
  - Fabrication readiness: DRC status, tolerance checks, export readiness
- **Alerting:** Configurable thresholds with email/webhook notifications
- **Data backend:** MongoDB Atlas time-series collections for live telemetry; aggregation pipelines for historical analytics
- **Frontend:** React + TypeScript with Recharts / D3 for interactive engineering charts

#### Pillar 4: Physical AI Assistant (Engineering Copilot)
A prompt-driven AI assistant purpose-built for engineering queries.

- **Design philosophy:** Human-in-the-loop at every step. The assistant surfaces reasoning, cites sources, and explicitly flags uncertainty. It does not make autonomous design decisions.
- **Query types:** Literature lookup, parameter estimation, design trade-off analysis, error diagnosis, standards compliance checks, material selection guidance
- **Knowledge grounding:** RAG over the platform's curated engineering corpus (starting from the six founding papers of the Precision with Light project; expanding to general engineering domains)
- **Agent actions:** Triggered simulations (via Sim Bridge), dashboard queries, template parameter suggestions — all requiring explicit engineer confirmation before execution
- **Hallucination mitigation:** DSR-CRAG corrective retrieval; all numeric claims are sourced or explicitly flagged as estimates; confidence levels displayed
- **Ethical guardrails:** Transparency about model limitations; refusal to provide outputs that could be used to circumvent safety-critical design review processes

### Layer 3 — Platform Core

The central nervous system of the platform.

- **API Framework:** FastAPI (Python) — async, high performance, OpenAPI spec auto-generated
- **Schema validation:** Pydantic v2 — strict typing for all engineering data models, simulation requests, export specifications
- **Agentic orchestration:** Lightweight agent framework managing multi-step workflows (e.g.: upload CAD → validate → create twin → dispatch simulation → update dashboard)
- **Authentication middleware:** JWT validation, role-based access control (RBAC), audit logging
- **Job queue:** Redis-backed task queue for simulation dispatch (Celery or equivalent)
- **API versioning:** Semantic versioning from v1.0; backward compatibility guaranteed across minor versions

### Layer 4 — Infrastructure & Data

- **MongoDB Atlas:** Primary data store. Collections: Projects, Twins, Templates, SimRuns, KPITimeSeries, Users, AuditLog. Vector search enabled for RAG retrieval.
- **Simulation Bridge:** Adapter layer connecting Platform Core to external solvers. Abstracted interface allows adding new solver backends without changing upstream API. Current targets: Lumerical FDTD/MODE, COMSOL Multiphysics. Future: Ansys, OpenFOAM, custom in-house solvers.
- **Fabrication Export Pipeline:** Post-processing layer that takes twin geometry + material specifications and generates industry-standard files. GDSII for photonics/semiconductors, STL for 3D printing, STEP/IGES for mechanical CAD handoff.

### Layer 5 — DevSecOps & CI/CD (Cross-Cutting)

This layer is not beneath infrastructure — it wraps and governs every layer above it.

- **Repository:** GitHub monorepo (Engineering World Company organisation). Branching strategy: `main` (protected), `develop`, feature branches, release tags.
- **CI/CD:** GitHub Actions pipelines — lint, test, build, security scan, deploy. Separate pipelines for frontend and backend.
- **Security gates:** SAST (static analysis) on every PR; dependency scanning (Dependabot); secrets scanning; container vulnerability scanning
- **Infrastructure as Code:** Terraform or Pulumi for cloud resource provisioning. Target clouds: AWS (primary), with architecture designed for multi-cloud portability.
- **Observability:** Structured logging (JSON), distributed tracing, metrics collection. Stack: OpenTelemetry → Grafana/Prometheus or AWS CloudWatch.
- **Pull Request requirements:** Two reviewers, passing CI, security scan clear, test coverage maintained.

---

## 4. Technology Stack Summary

| Layer | Technology | Rationale |
|---|---|---|
| Frontend | React + TypeScript + Lovable | Rapid UI iteration, type safety, component reuse |
| Backend | FastAPI (Python) | Async, auto-docs, engineering ecosystem compatibility |
| Data validation | Pydantic v2 | Strict schemas, native FastAPI integration |
| Database | MongoDB Atlas | Flexible schema for engineering objects, vector search |
| AI/RAG | DSR-CRAG architecture | Corrective retrieval prevents hallucinated physics |
| Generative Engine | cWGAN-GP + PINNs | Physics-informed generation for twin synthesis |
| Sim Bridge | Lumerical SDK, COMSOL API | Domain-specific simulation fidelity |
| Export | gdspy, numpy-stl, Open CASCADE | Industry-standard fabrication formats |
| Auth | JWT + OAuth2 + PKCE | Secure, standards-compliant, stateless |
| CI/CD | GitHub Actions | Native to repo, extensive marketplace |
| IaC | Terraform | Cloud-agnostic, reproducible environments |
| Observability | OpenTelemetry + Grafana | Vendor-neutral, production-grade |

---

## 5. Commercial Strategy & Business Moats

### Target Customer Segments

**Tier 1 — Individual Engineers / Consultants:** Solo practitioners doing design work for clients. Pain point: no access to enterprise simulation tools; cobbling together point solutions. Value: professional-grade platform at SaaS pricing.

**Tier 2 — SME Engineering Firms (5–50 engineers):** Growing firms needing shared project infrastructure, collaborative simulation, and client-reportable dashboards. Value: team collaboration + reproducibility + client-facing outputs.

**Tier 3 — Research Groups & Universities:** Academic teams doing applied engineering research. Value: reproducible computational workflows, publication-ready outputs, integration with scientific literature RAG.

### Pricing Model (Proposed)

- **Free tier:** 1 active project, 3 twin creations/month, community templates only, 1 dashboard
- **Professional (€49/month):** 10 projects, unlimited twins, full template library, unlimited dashboards, Physical AI Assistant
- **Team (€199/month, up to 10 seats):** All Professional features + shared project workspaces, team dashboards, priority simulation queue
- **Enterprise (custom):** On-premise deployment option, custom simulation bridge connections, SLA, dedicated support

### Business Moats

**1. Engineering corpus & RAG quality:** The platform's AI assistant is only as good as its knowledge base. Building and curating a high-quality, domain-specific engineering corpus — starting with the six founding papers and expanding systematically — creates a durable knowledge moat that improves with usage.

**2. Template library network effects:** As engineers share and refine computational templates, the library grows in quality and coverage. A well-populated template library with community ratings is a significant switching cost.

**3. Twin history and project continuity:** Engineers accumulate project history, parametric studies, and iteration logs on the platform. This data gravity increases retention.

**4. Simulation bridge integrations:** Each validated, production-grade solver integration (Lumerical, COMSOL, future Ansys) takes significant engineering effort to build. Each integration expands addressable market and creates a technical barrier.

**5. Fabrication export accuracy:** GDSII and STL generation with DRC validation that actually works for real fabrication flows is non-trivial. Getting this right is a strong signal of credibility to serious engineering users.

**6. Ethical AI differentiation:** In a market where AI hallucination in engineering contexts is a serious risk (wrong material properties, incorrect physics, fabrication-killing errors), a platform with explicit uncertainty quantification, source citation, and human confirmation gates is meaningfully differentiated from "chat with your CAD file" competitors.

---

## 6. Iteration Plan

### Phase 0 — Foundation (Current, Weeks 1–4)
**Goal:** Establish architecture, development environment, and first deployable skeleton.

- GitHub monorepo structure created with DevSecOps scaffolding
- FastAPI backend skeleton with health endpoint, auth middleware, Pydantic base schemas
- React frontend skeleton with login page and empty dashboard shell
- MongoDB Atlas instance connected, base collections defined
- CI/CD pipeline: lint, test, build, deploy to dev environment
- Architecture Decision Records (ADRs) for key technology choices
- First Substack post: platform vision and architecture rationale

**Deliverable:** A running, authenticated, empty platform skeleton deployed to a dev URL.

### Phase 1 — Physical AI Assistant MVP (Weeks 5–10)
**Goal:** The AI copilot is the highest-value, lowest-infrastructure-dependency pillar to build first. It generates immediate value and seeds the engineering corpus.

- DSR-CRAG pipeline connected to founding engineering corpus (6 papers)
- Chat interface with source citation and confidence display
- Basic engineering query types: literature lookup, parameter estimation
- Human-confirmation gate before any agent-triggered action
- Corpus expansion tooling (PDF ingestion, chunking, embedding, storage in Atlas)

**Deliverable:** Functional Physical AI Assistant with grounded engineering queries and citation display.

### Phase 2 — Computational Templates (Weeks 11–18)
**Goal:** Engineers can define, save, run, and version computational workflows.

- Template schema (Pydantic) for major solver types
- Template builder UI (form-based parameter configuration)
- Sim Bridge v1: connection to one solver (Lumerical or COMSOL)
- Template run execution, logging, result storage
- Basic result viewer in dashboard

**Deliverable:** End-to-end template workflow: define → validate → run → view results.

### Phase 3 — Digital Twin Engine (Weeks 19–28)
**Goal:** Engineers can create, visualise, and simulate digital twins.

- CAD upload and validation pipeline
- Twin geometry viewer (Three.js or OpenCASCADE web)
- Physics-based twin parameterisation (material library, boundary conditions)
- Integration with Sim Bridge for twin validation runs
- GDSII/STL export pipeline

**Deliverable:** Full twin creation workflow with simulation coupling and fabrication export.

### Phase 4 — KPI Dashboards & Platform Polish (Weeks 29–36)
**Goal:** Complete the four-pillar experience and prepare for first external users.

- Dashboard builder with drag-and-drop KPI widgets
- Real-time simulation monitoring (WebSocket updates)
- Alert configuration and notification system
- User onboarding flow, documentation, tutorial templates
- Security audit and penetration testing
- Pricing page and subscription management integration

**Deliverable:** Complete four-pillar platform ready for controlled beta launch.

---

## 7. Ethical AI Framework

EWC Compute is designed with a deliberate ethical posture, not as a compliance exercise but as a first-principles engineering requirement.

**Transparency:** The Physical AI Assistant always displays its reasoning chain, source documents, and confidence level. Engineers can inspect why a recommendation was made.

**Human-in-the-loop mandatory:** No agent action (simulation dispatch, template application, export generation) executes without explicit engineer confirmation. The platform is a copilot, not an autopilot.

**Uncertainty quantification:** Numeric outputs from AI-generated responses carry explicit uncertainty estimates. The system distinguishes between "retrieved from source" (high confidence) and "estimated by model" (lower confidence, clearly flagged).

**Hallucination mitigation by design:** DSR-CRAG's corrective retrieval loop is not a bolt-on — it is the core retrieval architecture. Physics-incorrect outputs are caught before reaching the engineer.

**Data privacy:** Engineer project data is not used to train or fine-tune any model without explicit opt-in consent. Multi-tenant data isolation is enforced at the database query level, not just the API level.

**Audit logging:** Every AI-assisted decision, simulation dispatch, and export event is logged with a timestamp, user identity, and the specific AI output that informed it. Engineers can produce a full audit trail for any project deliverable.

**Avoiding over-reliance:** The UI is designed to prompt critical review. Results are framed as "candidate outputs for engineer review" not "answers." Documentation explicitly states the boundaries of AI competence.

---

## 8. Human-in-the-Loop Design Principles

These principles govern every UI and workflow decision:

1. **The engineer decides, the platform executes.** No consequential action (simulation run, export, publish) happens without an explicit engineer-initiated trigger.
2. **Explain before you act.** Every agent action shows a plain-language summary of what it will do and what it will cost (compute time, credits) before the confirm button is active.
3. **Reversibility by default.** Destructive operations (delete, overwrite, publish to external) require two-step confirmation and maintain a 30-day soft-delete recovery window.
4. **Progressive disclosure.** Complex simulation parameters are hidden behind an "Advanced" toggle. Defaults are sensible and documented. Engineers are not overwhelmed on first encounter.
5. **Failure is informative.** When a simulation fails, the error is presented in plain engineering language (not a stack trace), with a suggested corrective action and a direct link to relevant documentation.
6. **AI suggestions are proposals, not verdicts.** Every AI-generated value (material property, boundary condition, mesh setting) is displayed in an editable field, not a read-only label.

---

## 9. GitHub Project Structure

```
ewc-compute/
├── .github/
│   ├── workflows/
│   │   ├── ci-backend.yml
│   │   ├── ci-frontend.yml
│   │   ├── security-scan.yml
│   │   └── deploy-dev.yml
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── ISSUE_TEMPLATE/
├── backend/
│   ├── app/
│   │   ├── api/v1/
│   │   ├── core/           # config, security, logging
│   │   ├── models/         # Pydantic schemas
│   │   ├── services/       # business logic
│   │   ├── agents/         # AI orchestration
│   │   └── sim_bridge/     # solver adapters
│   ├── tests/
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── hooks/
│   │   └── api/
│   └── Dockerfile
├── infrastructure/
│   ├── terraform/
│   └── docker-compose.yml
├── docs/
│   ├── adr/               # Architecture Decision Records
│   ├── api/               # OpenAPI specs
│   └── engineering/       # Domain documentation
├── scripts/
├── .env.example
├── README.md
└── CONTRIBUTING.md
```

---

## 10. Immediate Next Steps (Week 1)

Priority order, each a discrete GitHub issue:

1. **ADR-001:** Document FastAPI + MongoDB choice with rationale and alternatives considered
2. **Backend skeleton:** FastAPI app with `/health`, `/auth/login`, `/auth/refresh` endpoints; Pydantic User model; JWT middleware
3. **Frontend skeleton:** React app with login page, protected route wrapper, empty dashboard shell
4. **MongoDB Atlas setup:** Provision cluster, define base collections (users, projects, audit_log), create indexes
5. **CI/CD pipeline:** GitHub Actions for backend (pytest, ruff, mypy) and frontend (vitest, eslint, tsc)
6. **Docker Compose:** Full local dev environment (FastAPI + MongoDB + Redis) runnable with `docker compose up`
7. **CONTRIBUTING.md:** PR conventions, commit message format (Conventional Commits), branch naming, code review checklist
8. **Substack post draft:** "EWC Compute — Why we're building a Digital Engineering Platform and what that actually means"

---

## 11. Success Metrics

### Phase 0–1 (Technical)
- Backend test coverage ≥ 80%
- CI pipeline green on every PR
- Physical AI Assistant latency: median query response < 4 seconds
- Retrieval precision: ≥ 85% of engineer-reviewed answers rated "accurate and sourced"

### Phase 2–3 (Product)
- Template execution success rate ≥ 95%
- Sim Bridge uptime ≥ 99.5%
- GDSII export validated against at least one external DRC tool
- Time-to-first-twin for a new user < 15 minutes

### Phase 4 (Commercial)
- Beta cohort: 20 external engineers providing structured feedback
- Net Promoter Score (NPS) ≥ 40 from beta cohort
- Activation metric: ≥ 60% of beta users complete at least one full twin → simulate → export workflow

---

*EWC Compute — Engineering World Company*  
*Document maintained in GitHub: Engineering World Company organisation*  
*Contact: [Project leads]*

---

## 12. Architecture Update — NVIDIA GTC 2026 Intelligence (March 2026)

*Added after analysis of NVIDIA GTC 2026 keynote slides on computational engineering.*

### 12.1 NVIDIA "Engineering With AI" — Canonical AI Mode Mapping

NVIDIA's GTC 2026 presentation formalised a three-mode AI intervention framework for the engineering workflow that aligns directly with EWC Compute's architecture. This should be adopted as the canonical language for our platform's AI capabilities.

The engineering workflow runs: **CAD Design → Pre-processing → Simulation → Post-processing → Analysis & Optimisation**

Three AI intervention points map onto this:

| NVIDIA mode | Entry point in workflow | EWC Compute implementation | Phase |
|---|---|---|---|
| Generative Design | CAD Design / Pre-processing | cWGAN-GP in Digital Twin Engine — broader design space exploration, parametric sweep generation | Phase 3 |
| AI Preconditioning + Surrogate | Simulation | Sim Bridge intelligence layer — PINNs for real-time physics prediction; cuDSS-aware solver routing | Phase 2 |
| Inverse Design | Analysis & Optimisation | DNN inverse design (from founding paper corpus) — optimal geometry generation from target specs | Phase 3+ |

**Immediate action:** The Sim Templates Pydantic schema should expose `ai_mode` as an explicit field with values `generative`, `surrogate`, `principled_solve`. Each routes to a different backend pathway and carries a different cost/accuracy profile. Engineers should see this choice explicitly, not have it hidden inside solver configuration.

### 12.2 CUDA-X Acceleration — Sim Bridge Performance Contract

NVIDIA's CUDA-X acceleration data (Image 1 from GTC 2026 keynote) establishes the performance baseline that EWC Compute's Sim Bridge should expose when connected to GPU-accelerated solver backends:

| Simulation type | CUDA-X speedup | EWC relevance |
|---|---|---|
| FEM (Finite Element Method) | 20× | Core structural/thermal analysis workload for EWC users |
| Litho | 20× | Semiconductor/photonic mask workflows (Precision with Light overlap) |
| SPICE | 30× | Circuit simulation — Semiconductor domain users |
| DEM (Discrete Element Method) | 40× | Granular mechanics, powder flow, materials |
| Inspection | 40× | Quality/metrology workflows |
| CFD (Computational Fluid Dynamics) | 50× | High-value mechanical/thermal workload |
| TCAD | 100× | Semiconductor device simulation — highest acceleration |

COMSOL, Siemens, and Synopsys appear as CUDA-X partners. This means our COMSOL Sim Bridge adapter can surface GPU-accelerated performance without building our own solver — we route through COMSOL's CUDA-X-enabled backend.

**Architecture implication:** The Sim Templates UI should surface estimated runtime with and without GPU acceleration as a pre-run cost estimate. Engineers should be able to make an informed decision before dispatching a job.

### 12.3 NVIDIA cuDSS — Sim Bridge Numerical Kernel Awareness

cuDSS (Accelerated Direct Sparse Solvers) targets the numerical kernels common to all FEA, CFD, and structural solvers:

- Reordering: 11× speedup
- Linear Solve: 60× speedup
- Matrix Factorization: 80× speedup

Domain partners confirmed: Applied Materials, Cadence, COMSOL, Keysight, Samsung, Siemens, Synopsys, TSMC — covering Automotive, Aerospace, and Semiconductor.

**Architecture implication:** In the COMSOL Sim Bridge adapter, documentation should note which COMSOL solver backend paths invoke cuDSS (the direct sparse solver path, as opposed to iterative solvers). Sim Templates for FEA and CFD should expose a `solver_backend` field that allows engineers to select `direct_sparse` (cuDSS-accelerated) vs `iterative` (lower memory, less speedup). This is a professional-grade configuration detail that differentiates EWC Compute from casual simulation wrappers.

### 12.4 Competitive Signal — SimScale

SimScale appears as a CUDA-X partner in the GTC 2026 keynote. SimScale is a cloud-based, browser-native CFD/FEA platform targeting the same mid-market engineering segment as EWC Compute.

Assessment: SimScale validates the market. It is not a direct threat because it is a point tool — it does not have an AI assistant, a digital twin engine with generative/inverse design modes, a template library, or a fabrication export pipeline. EWC Compute's four-pillar architecture wraps around SimScale's use case entirely. An engineer using SimScale today is a natural future EWC Compute user.

The practical implication for our go-to-market: engineers who know SimScale understand cloud-based simulation. Our onboarding should reference the SimScale mental model (browser-based, project-oriented, result-first) as a starting point, then show what the AI assistant and twin engine add on top.
