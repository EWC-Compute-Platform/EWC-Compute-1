# Contributing to EWC Compute Platform

Thank you for contributing. EWC Compute is built with engineering rigour as a first principle — the same standard that applies to the platform's outputs applies to the code that produces them.

---

## Before You Start

1. Open an Issue first for any significant feature, API change, or architectural decision. Describe the problem and your proposed approach before writing code.
2. For architectural changes, check whether an existing ADR covers the area (`docs/adr/`). If your change deviates from an existing ADR, open a discussion before submitting a PR.
3. Security findings should be reported privately via GitHub's Security Advisory feature — not as public issues.

---

## Development Workflow

```
main          ← protected; production-ready at all times
  └── develop ← integration branch; all feature PRs target here
        └── feat/your-feature-name
        └── fix/issue-description
        └── docs/adr-005-description
```

**Never commit directly to `main` or `develop`.**

### Branch naming

```
feat/<short-description>
fix/<short-description>
refactor/<short-description>
docs/<short-description>
chore/<short-description>
security/<short-description>
```

---

## Commit Messages — Conventional Commits

All commits must follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description in sentence case>

[optional body — explain WHY, not just what]

[optional footer — Closes #N]
```

**Types:** `feat` · `fix` · `docs` · `style` · `refactor` · `test` · `chore` · `security`

**Scopes:** `backend` · `frontend` · `omniverse` · `sim-bridge` · `ci` · `infra` · `docs`

**Examples:**

```
feat(backend): add OpenUSD twin export endpoint with physics schema

Writes DigitalTwin objects to .usda stages using usd-core 25.08.
Includes UsdPhysics.RigidBodyAPI for mass and material properties.

Closes #42
```

```
security(backend): move JWT secret to environment-only resolution

Previously the secret had a hardcoded fallback. Removed fallback;
app now raises on startup if JWT_SECRET is not set in environment.
```

---

## Local Setup

See the README for the full quickstart. Short version:

```bash
cp .env.example .env
docker compose up --build
```

Run backend tests:
```bash
cd backend && pytest tests/ -v --cov=app --cov-fail-under=80
```

Run frontend tests:
```bash
cd frontend && npm run test
```

---

## Pull Request Requirements

All PRs must:

- Target `develop` (not `main`)
- Complete the PR checklist in `.github/PULL_REQUEST_TEMPLATE.md`
- Pass all four CI workflows (backend, frontend, security, and deploy-dry-run)
- Have two reviewer approvals
- Not decrease test coverage below 80%
- Not introduce any Bandit HIGH findings, Safety CVEs, or Trivy CRITICAL vulnerabilities
- Not introduce secrets or credentials (enforced by Gitleaks)

Architecture-changing PRs must additionally reference an ADR.

---

## Architecture Decision Records (ADRs)

Significant technical decisions are documented in `docs/adr/`. When your PR changes an architectural decision:

1. Create `docs/adr/ADR-NNN-short-title.md` using the template below
2. Reference it in your PR description

**ADR template:**

```markdown
# ADR-NNN — Title

**Status:** Proposed | Accepted | Deprecated | Superseded by ADR-NNN

## Context
What is the problem or situation that requires a decision?

## Decision
What was decided, and why?

## Consequences
What are the positive and negative outcomes of this decision?
What becomes easier or harder?
```

---

## Code Standards

### Python (backend)

- Python 3.12. Type annotations on all public functions and class attributes.
- `ruff` for lint and format. `mypy --strict` for type checking.
- All API request/response types defined as Pydantic v2 models — no untyped dicts in route handlers.
- Use `async def` for all route handlers and service functions. Blocking I/O (solver calls, file I/O) must run in a thread executor or Celery task.
- Docstrings on all public classes and non-trivial functions.

### TypeScript (frontend)

- TypeScript strict mode. No `any`.
- ESLint with project config. All warnings are errors.
- API types must be generated from or consistent with the backend OpenAPI spec.
- React components: functional only. Props typed with interfaces.

### OpenUSD / Omniverse (omniverse/)

- Use `usd-core` Python API for all USD I/O.
- Validate all exported USD stages with `AssetValidator` before writing to disk or Nucleus.
- Document the USD schema version compatibility in docstrings.

---

## Questions

Open a GitHub Discussion or join the conversation on [engineeringworldcompany.substack.com](https://engineeringworldcompany.substack.com).
