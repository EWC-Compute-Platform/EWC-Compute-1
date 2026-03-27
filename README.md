# EWC Compute: The Digital Engineering Platform 

Welcome to EWC Compute, the flagship Digital Engineering platform by the Engineering World Company. EWC Compute bridges the gap between traditional physics-based solvers and modern Accelerated Computing, AI, and DevOps. We empower engineers to deploy containerized, software-defined simulation environments and real-time digital twins. 

## 🎯 Vision & Core Pillars

The industrial engineering landscape is shifting from slow, siloed desktop workflows to unified, cloud-accelerated, AI-driven environments. EWC Compute serves as the orchestrator and unified UI/UX dashboard for this shift.

1. Software-Defined Templates: Define simulation parameters and infrastructure as code (IaC).

2. Accelerated Solvers (cuDSS & CUDA-X): Offload heavy mathematical calculations (Matrix Factorization, Linear Solves) to state-of-the-art GPU architectures.

3. PhysicalAI Assistance: Leverage conversational agents to automate meshing setup, interrogate historical engineering data, and build reports.

4. The "Aerodynamics Shortcut": Hybrid workflows enabling rapid real-time AI surrogate prototyping combined with high-fidelity numerical validation.

## Repository Architecture

Our GitHub Organization tracks our modular microservices and third-party upstream forks. Here is how the EWC ecosystem is organized:

### 🌟 Core Repositories
* ewc-compute-platform-1 (This Repo): The central hub containing platform specifications, architectural decision records (ADRs), and unified deployment scripts.

* ewc-ui-dashboards: Modern Next.js/React web app for user authentication, telemetry monitoring, and secure enterprise logins.

* ewc-physical-ai: Python-driven backend microservices hosting our LLMs, vector DBs (RAG), and agentic toolkits for engineering chat.

* ewc-compute-templates: Curated Dockerfiles and Terraform scripts containerizing OpenFOAM, structural FEM, and custom solvers.

### 🍴 Forked & Tracked Upstreams
We maintain curated forks of open-source solvers, benchmarking how they perform when accelerated by NVIDIA CUDA libraries.

Check our organization page to see our active forks and tracked dependencies!


