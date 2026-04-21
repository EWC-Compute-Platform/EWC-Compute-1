# `confirmation_gate.py` — Architecture and Design Notes

**EWC Compute Platform · `backend/app/agents/confirmation_gate.py`**
**Phase 1 · Human-in-the-Loop Enforcement Layer**

---

## What this file is

`confirmation_gate.py` is the enforcement point for EWC Compute's
human-in-the-loop constraint. Every action that modifies platform state —
dispatching a simulation, updating a template, exporting geometry, modifying
a twin — must pass through this gate before it executes.

It is not middleware. It is not a UX feature. It is a state machine that
makes autonomous execution structurally impossible, not just policy-prohibited.

---

## The core architectural insight

Most AI systems enforce human oversight through prompts or policies:
*"always ask before acting"*. That approach has a critical weakness —
any code path that bypasses the prompt also bypasses the constraint.

The gate inverts this. Instead of telling the assistant not to act, it
makes acting require a state transition that only the engineer can trigger.
The assistant can only call `propose()`. It has no access to `execute()`.
`execute()` requires the proposal to be in `CONFIRMED` status.
`CONFIRMED` status can only be reached by calling `confirm()`.
`confirm()` is exposed only as an authenticated API endpoint that requires
an explicit HTTP request from the engineer's client.

There is no code path from `propose()` to execution without that
engineer-triggered HTTP request. This is the architectural guarantee.

---

## The three-stage state machine

```
propose()        confirm()        execute()
  │                  │                │
  ▼                  ▼                ▼
PENDING  ──────▶  CONFIRMED  ──────▶  EXECUTED
  │                  │
  ├──▶ EXPIRED (TTL exceeded, 10 min)
  └──▶ ABORTED (engineer cancels)
       ▲
       │ (also reachable from CONFIRMED)
     abort()
```

**Stage 1 — `propose()`**: called by the assistant service or any service
layer component when it determines an action should be proposed. Creates an
`ActionProposal` document with `status=PENDING` and persists it to MongoDB.
Returns the proposal with its `description` — the plain-language text the
engineer reads in the UI.

**Stage 2 — `confirm()`**: called by the API layer when the engineer clicks
confirm. Validates the proposal is PENDING and not expired. Transitions to
`CONFIRMED`. This is the explicit human keystroke the architecture requires.

**Stage 3 — `execute()`**: called by the API layer immediately after a
successful `confirm()`. Looks up the registered handler for the action type,
calls it with the proposal's parameters, stores the result, and transitions
to `EXECUTED`. If the handler fails, the proposal stays `CONFIRMED` so
the engineer can retry or inspect.

---

## The handler registry

Action handlers are registered at application startup in `main.py`:

```python
from app.agents.confirmation_gate import register_handler, ActionType
from app.services.sim_templates import dispatch_sim_run

register_handler(ActionType.SIM_DISPATCH, dispatch_sim_run)
```

Every new action type follows the same pattern: implement the async handler
in the relevant service module, register it at startup. The gate does not
need to know the implementation details of any handler — it only needs the
function signature: `async (parameters: dict) -> dict`.

This separation of concerns means adding a new action type (e.g. Phase 2's
`nucleus_sync`) requires zero changes to the gate itself.

---

## Why MongoDB for proposal storage

Proposals are persisted to MongoDB (`ewc_action_proposals` collection) rather
than held in memory for three reasons:

1. **Durability**: a server restart between `propose()` and `confirm()` does
   not lose the proposal. The engineer can still confirm after a restart.

2. **Auditability**: every proposal — including aborted and expired ones —
   is a permanent record. The audit trail is a first-class output, not a
   side effect.

3. **Multi-instance correctness**: when running multiple FastAPI worker
   processes, in-memory state would be per-process. MongoDB provides a
   shared, consistent view across all workers.

---

## The `ActionProposal` model — key fields

| Field | Purpose |
|---|---|
| `proposal_id` | UUID, stable identifier across the full lifecycle |
| `description` | Plain language shown to the engineer — must be precise enough to make a real decision |
| `parameters` | Everything the handler needs at execute time — stored at propose time so the engineer sees exactly what will run |
| `expires_at` | 10-minute TTL — prevents stale proposals from being confirmed out of context |
| `execution_result` | Handler return value — stored for audit and downstream use (e.g. the sim run ID from Flow360) |

---

## The `ProposalSummary` model

The full `ActionProposal` includes `parameters` — which may contain internal
IDs, file paths, or solver configuration that is not appropriate to expose
directly to the client API. `ProposalSummary` is the safe, client-facing
subset: `proposal_id`, `action_type`, `description`, `status`, timestamps.

The API layer always returns `ProposalSummary` in list responses.
The full `ActionProposal` is available to authenticated admin endpoints only.

---

## Lazy expiry

Proposals are not deleted when their TTL passes — they are transitioned to
`EXPIRED` status on next read. This is lazy expiry. It preserves the audit
record (an expired proposal is meaningful information) while preventing
stale proposals from being confirmed.

The 10-minute TTL is a deliberate design choice. It is long enough for an
engineer to review a proposal, ask a follow-up question to the assistant,
and confirm. It is short enough that a proposal generated in a previous
session does not remain actionable indefinitely.

---

## Error handling philosophy

`execute()` is the only point where an external system is called (via
the handler). If the handler fails:

- The proposal status stays `CONFIRMED`, not `EXECUTED`.
- The error is logged with full context.
- A `RuntimeError` is raised to the API layer, which returns a 500.
- The engineer can retry via the confirm/execute flow again, or abort.

This means failed executions are **not silent**. They appear in the
engineer's pending proposals list and in the audit log. There is no
"fail silently and pretend it worked" path.

---

## What this module does NOT do

- It does not decide *whether* to propose an action. That is the assistant
  service's responsibility.
- It does not validate the *content* of parameters. That is the handler's
  responsibility.
- It does not authenticate the engineer. That is the API layer's
  responsibility (JWT middleware).
- It does not rate-limit proposals. That is Phase 2 infrastructure work.

Each concern is in exactly one place.

---

## Phase 2+ extensions

The current implementation assumes the confirming engineer is the same as
the requesting engineer (`confirmed_by` is recorded but not validated
against `requested_by`). Phase 2 will add:

- **Delegation**: a team lead can confirm proposals made by a team member
- **Approval tiers**: high-cost actions (e.g. large Flow360 jobs above a
  compute unit threshold) require a second confirmation from a project admin
- **Proposal expiry webhooks**: notify the engineer via email/Slack when
  a proposal is about to expire

None of these require changes to the gate's core state machine — they are
additions to the `confirm()` validation logic and the proposal schema.

---

## Files that interact with this module

| File | Interaction |
|---|---|
| `app/services/assistant_service.py` | Calls `propose()` when the assistant identifies a platform action in the engineer's query |
| `app/api/v1/assistant.py` | Exposes `/confirm` and `/execute` endpoints that call `confirm()` and `execute()` |
| `app/main.py` | Calls `register_handler()` at startup for each action type |
| `app/services/sim_templates.py` | Provides the `SIM_DISPATCH` handler |
| `app/services/twin_engine.py` | Provides the `TWIN_MODIFY` and `EXPORT_GEOMETRY` handlers |

---

*EWC Compute Platform · Engineering World Company*
*This document is part of the platform architecture record.*
*Changes to `confirmation_gate.py` that alter the state machine or handler
registry contract must update this document in the same PR.*
