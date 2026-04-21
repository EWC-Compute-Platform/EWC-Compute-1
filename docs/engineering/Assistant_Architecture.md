# `assistant.py` — Architecture and Design Notes

**EWC Compute Platform · `backend/app/api/v1/assistant.py`**
**Phase 1 · Physical AI Assistant HTTP Interface**

---

## What this file is

`assistant.py` is the FastAPI router that exposes the Physical AI
Assistant as a REST API. It is the HTTP boundary between the engineer's
client and the two service-layer modules built in Phase 1:
`assistant_service.py` (the DSR-CRAG pipeline) and
`confirmation_gate.py` (the human-in-the-loop enforcement layer).

This file contains no business logic. It translates HTTP into service
calls and service results into HTTP responses.

---

## Endpoint map and the flow between them

```
Engineer's browser
       │
       │  POST /v1/assistant/query
       ▼
  query_assistant()
       │── run_assistant()         ← assistant_service.py
       │── _maybe_propose()        ← confirmation_gate.propose()
       │
       │  Returns: { assistant_response, proposal? }
       │
       │  If proposal is non-null, client surfaces confirm/abort UI
       │
       │  POST /v1/assistant/proposals/{id}/confirm
       ▼
  confirm_proposal()              ← confirmation_gate.confirm()
       │  PENDING → CONFIRMED
       │
       │  POST /v1/assistant/proposals/{id}/execute
       ▼
  execute_proposal()              ← confirmation_gate.execute()
       │  CONFIRMED → EXECUTED
       │  Handler called → e.g. Flow360 job dispatched
       │
       │  POST /v1/assistant/proposals/{id}/abort  (at any pre-execution stage)
       ▼
  abort_proposal()                ← confirmation_gate.abort()
       │  PENDING or CONFIRMED → ABORTED
```

The engineer cannot reach `execute_proposal()` without first going
through `confirm_proposal()`. The gate enforces this — the API layer
simply reflects it as separate, sequential HTTP calls.

---

## The design principle: thin router

Every FastAPI tutorial tempts you to put logic in route handlers.
The pattern here is deliberately different. Route handlers do exactly
four things:

1. Validate the request via Pydantic (automatic)
2. Check preconditions (e.g. `nim_available`)
3. Call one service function
4. Return a typed response

Nothing more. The reason: logic in route handlers is hard to test
without spinning up HTTP. Logic in service modules is testable with
a direct function call. The thinner the router, the more of the
codebase is covered by fast, dependency-free unit tests.

---

## Action detection: the two-step approach

When the DSR-CRAG pipeline returns an answer, the `query` endpoint
checks whether that answer contains an action proposal. This requires
detecting natural language, which could be done many ways. The
implementation uses two steps deliberately:

**Step 1 — keyword scan (`_contains_action_proposal`)**
A regex scan for the confirmation-request pattern defined in
`ACTIVE_SYSTEM_PROMPT_V1`. The system prompt instructs the assistant
to always close action proposals with phrases like "Shall I proceed?"
This is fast (microseconds), requires no NIM call, and catches the
vast majority of proposals.

**Step 2 — structured NIM extraction (`_extract_proposal_parameters`)**
When Step 1 fires, a second NIM call asks the model to extract the
action parameters as JSON. This produces clean, typed parameters that
the registered handler can consume directly — rather than requiring
each handler to parse free text.

Why not skip Step 1 and always run Step 2? Because Step 2 costs a NIM
call on every query. The fast keyword scan ensures that cost is only
incurred when there is actually something to extract.

Why not use a rule-based parser instead of NIM for Step 2? Because
the parameter space is large and domain-specific. A rule-based parser
would need constant maintenance as new action types and parameter
patterns emerge. NIM understands the engineering domain context and
can reliably extract Mach numbers, mesh sizes, file paths, and solver
settings without a bespoke parser for each.

---

## The `QueryResponse` model: answer + optional proposal

```python
class QueryResponse(BaseModel):
    assistant_response: AssistantResponse   # always present
    proposal: ProposalSummary | None = None # present if action detected
```

This is the key interface contract with the frontend. The client
handles two cases:

- `proposal is None`: pure Q&A interaction — display the answer
- `proposal is not None`: action proposed — display the answer AND
  a confirmation card with the proposal description, a confirm button
  (POST /proposals/{id}/confirm then /execute), and an abort button
  (POST /proposals/{id}/abort)

The frontend never calls `execute` directly from the query response.
It must always go through confirm first. This is enforced by the gate,
but the API design reflects it: there is no "confirm_and_execute"
shortcut endpoint.

---

## `ProposalSummary` vs `ActionProposal`

The gate's `ActionProposal` model contains the full `parameters` dict
— which may include internal IDs, file paths, NIM-extracted JSON, and
other data not suitable for client exposure. Every endpoint that
returns proposal data to the client returns `ProposalSummary` instead,
which contains only: `proposal_id`, `action_type`, `description`,
`status`, `created_at`, `expires_at`.

The mapping from `ActionProposal` → `ProposalSummary` happens in
each route handler, not in the gate. This keeps the gate unaware of
HTTP concerns.

---

## The `nim_available` guard

```python
if not settings.nim_available:
    raise HTTPException(503, "NIM API key not configured...")
```

This guard at the top of `query_assistant()` provides a clear,
actionable error when Phase 1 features are accessed without
`NIM_API_KEY` set in `.env`. Without it, the failure would surface
as a cryptic authentication error deep in the NIM client.

The `nim_available` property is defined in `config.py`:
```python
@property
def nim_available(self) -> bool:
    return bool(self.NIM_API_KEY)
```

This is the correct place for that check — a single source of truth
about whether NIM is configured, usable from any module.

---

## The history endpoint: an honest stub

```python
@router.get("/history")
async def get_history(...) -> list[HistoryEntry]:
    return []
```

The history endpoint is a deliberate stub in Phase 1. It is present
because:

1. The OpenAPI spec is generated from the router. Having the endpoint
   in the spec from Phase 1 means frontend development can start
   against the contract, even before the implementation exists.

2. The frontend's `GET /history` call will not 404 or error during
   development — it returns an empty list, which is valid.

3. The stub is documented with exactly what Phase 2 will implement,
   making the TODO visible in the codebase rather than tracked only
   in an issue.

Phase 2 implementation: persist `AssistantResponse` to
`ewc_assistant_history` collection, indexed on
`(user_id, conversation_id, created_at)`, paginated with `limit`
and `before_turn_id` parameters.

---

## Error handling conventions

| Exception source | HTTP status | Detail |
|---|---|---|
| `settings.nim_available` is False | 503 | Clear instruction to set NIM_API_KEY |
| `run_assistant()` raises | 500 | Pipeline failure with error context |
| `confirm()` raises `ValueError` | 400 | Gate validation message (expired, wrong status) |
| `execute()` raises `ValueError` | 400 | Gate validation message (not CONFIRMED) |
| `execute()` raises `RuntimeError` | 500 | Handler failure — proposal stays CONFIRMED for retry |
| `abort()` raises `ValueError` | 400 | Gate validation message |

The 400 vs 500 distinction is important. 400 means the client
(or engineer) did something the system can't process — wrong status,
expired proposal. 500 means something in the platform failed —
the engineer should retry or report. The gate's exception types
(`ValueError` / `RuntimeError`) are designed to map cleanly to
this distinction.

---

## `_maybe_propose` failure isolation

```python
except Exception as exc:
    logger.error("proposal_creation_failed | ...")
    return None
```

Failures in proposal creation are logged and swallowed. The query
response is always returned, even if the proposal creation fails.

The reasoning: a failed proposal creation is recoverable — the
engineer got their answer, they just can't execute the proposed
action through the gate. An exception that propagates to the client
would look like the entire query failed, which is a worse outcome
than a missing proposal.

---

## Assumed Phase 0 contracts

This module imports from three Phase 0 modules. If those modules
differ from these assumptions, the imports need adjustment:

```python
# core/database.py — must export this function
from app.core.database import get_database
# signature: () -> AsyncIOMotorDatabase
# used as: db: AsyncIOMotorDatabase = Depends(get_database)

# core/security.py — must export this function
from app.core.security import get_current_user
# signature: (token: str = Depends(oauth2_scheme)) -> User
# used as: current_user: User = Depends(get_current_user)

# models/user.py — User must have this field
from app.models.user import User
# required field: user_id: str
```

If `User.user_id` is named differently (e.g. `id` or `_id`), update
the two references in this file. No other changes needed.

---

## Registration in `main.py`

The router must be registered in `main.py` under the `/v1` prefix:

```python
from app.api.v1.assistant import router as assistant_router

app.include_router(assistant_router, prefix="/v1")
```

This produces the full endpoint paths:
- `POST /v1/assistant/query`
- `GET  /v1/assistant/proposals`
- `POST /v1/assistant/proposals/{id}/confirm`
- `POST /v1/assistant/proposals/{id}/execute`
- `POST /v1/assistant/proposals/{id}/abort`
- `GET  /v1/assistant/history`

---

## Files that interact with this module

| File | Interaction |
|---|---|
| `app/services/assistant_service.py` | `run_assistant()` — the full DSR-CRAG pipeline |
| `app/agents/confirmation_gate.py` | `propose()`, `confirm()`, `execute()`, `abort()`, `list_pending()` |
| `app/core/config.py` | `settings.nim_available`, `settings.NIM_MODEL_ENGINEERING` |
| `app/core/database.py` | `get_database()` FastAPI dependency |
| `app/core/security.py` | `get_current_user()` FastAPI dependency |
| `app/models/user.py` | `User` model — requires `.user_id` field |
| `app/main.py` | Router registration under `/v1` prefix |
| `frontend/src/api/` | TypeScript client generated from OpenAPI spec |

---

## Phase 2 extensions

None of these require changes to the existing endpoints:

- **Conversation persistence**: add `POST /history` write path when
  `ewc_assistant_history` collection is introduced
- **Streaming responses**: add `GET /query/stream` using
  FastAPI `StreamingResponse` + NIM streaming API
- **Proposal delegation**: extend `confirm_proposal()` to validate
  that `confirmed_by` has delegation rights for `requested_by`
- **Approval tiers**: add a `POST /proposals/{id}/approve` endpoint
  for admin-tier approval of high-cost actions

---

*EWC Compute Platform · Engineering World Company*
*This document is part of the platform architecture record.*
*Changes to endpoint contracts (request/response schemas, status codes,
or new endpoints) must update this document and the OpenAPI spec in
the same PR.*

