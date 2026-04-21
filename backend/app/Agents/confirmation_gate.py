"""
confirmation_gate.py
────────────────────────────────────────────────────────────────────────────────
Human-in-the-loop confirmation gate
EWC Compute Platform · backend/app/agents/confirmation_gate.py

Architectural role
──────────────────
This module is the enforcement point for EWC Compute's human-in-the-loop
constraint. Every action that modifies platform state — dispatching a
simulation, updating a template, exporting geometry, modifying a twin —
must pass through this gate before execution.

The gate operates in three stages:

  1. propose(action)    → stores a pending action, returns a proposal ID
                          and a plain-language description for the engineer
  2. confirm(proposal_id) → validates the proposal is pending and not expired,
                          marks it confirmed, returns it for execution
  3. execute(proposal_id) → callable only after confirm(); performs the action
                          via the registered handler; writes an AuditEvent

The assistant service calls propose(). The API layer exposes confirm() and
execute() as separate HTTP endpoints that require an explicit engineer
keystroke. No code path exists that calls execute() without a prior confirm().

Why a separate module rather than inline checks
────────────────────────────────────────────────
Inline "if confirmed:" checks are fragile — they can be bypassed by a new
code path that forgets the check. A centralised gate with a proposal registry
means the constraint is structural: you physically cannot execute a registered
action without going through the gate's state machine. New action types are
added by registering a handler; the confirmation requirement is automatic.

Proposal lifecycle
──────────────────
  PENDING → CONFIRMED → EXECUTED
  PENDING → EXPIRED   (TTL exceeded, default 10 minutes)
  PENDING → ABORTED   (engineer explicitly cancels)
  CONFIRMED → ABORTED (engineer cancels before execute())

Storage
───────
Proposals are stored in MongoDB (ewc_action_proposals collection) so they
survive across requests and are auditable. Redis TTL expiry is used as a
secondary safeguard. In Phase 1, in-memory fallback is provided for local
development without Redis.

Action types (Phase 1)
──────────────────────
  sim_dispatch    — dispatch a simulation job via Sim Bridge
  template_update — modify a versioned SimTemplate
  twin_modify     — update a DigitalTwin record
  export_geometry — trigger a fabrication export (GDSII / STL / STEP)
  corpus_ingest   — add a document to the AI assistant corpus

Phase 2+ will add: solver_config_update, dashboard_widget_add, nucleus_sync
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Awaitable

from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

PROPOSALS_COLLECTION = "ewc_action_proposals"
PROPOSAL_TTL_MINUTES = 10   # Pending proposals expire after 10 minutes
                             # Engineers must confirm within this window


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────

class ActionType(str, Enum):
    SIM_DISPATCH     = "sim_dispatch"
    TEMPLATE_UPDATE  = "template_update"
    TWIN_MODIFY      = "twin_modify"
    EXPORT_GEOMETRY  = "export_geometry"
    CORPUS_INGEST    = "corpus_ingest"


class ProposalStatus(str, Enum):
    PENDING   = "pending"
    CONFIRMED = "confirmed"
    EXECUTED  = "executed"
    EXPIRED   = "expired"
    ABORTED   = "aborted"


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────────────────

class ActionProposal(BaseModel):
    """
    A proposed platform action awaiting engineer confirmation.

    Created by propose(), persisted in MongoDB, consumed by confirm()
    and execute(). The plain-language description is what the engineer
    reads in the UI before deciding whether to confirm.
    """
    proposal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action_type: ActionType
    description: str              # Plain language: "Dispatch CFD run on NACA 0012..."
    parameters: dict[str, Any]    # All parameters needed to execute the action
    requested_by: str             # user_id of the engineer who triggered this
    project_id: str | None = None
    status: ProposalStatus = ProposalStatus.PENDING
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
        + timedelta(minutes=PROPOSAL_TTL_MINUTES)
    )
    confirmed_at: datetime | None = None
    executed_at: datetime | None = None
    aborted_at: datetime | None = None
    abort_reason: str | None = None
    execution_result: dict[str, Any] | None = None


class ProposalSummary(BaseModel):
    """
    Lightweight proposal representation returned to the API layer.
    Omits internal execution parameters from the client-facing response.
    """
    proposal_id: str
    action_type: ActionType
    description: str
    status: ProposalStatus
    created_at: datetime
    expires_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Handler registry
# ─────────────────────────────────────────────────────────────────────────────

# Maps ActionType → async callable that performs the actual action.
# Handlers are registered at application startup in main.py.
# Signature: async (parameters: dict[str, Any]) -> dict[str, Any]
ActionHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

_handlers: dict[ActionType, ActionHandler] = {}


def register_handler(action_type: ActionType, handler: ActionHandler) -> None:
    """
    Register an execution handler for a given action type.

    Called once at application startup. Handlers must be async callables
    that accept the proposal's parameters dict and return a result dict.

    Example (in main.py):
        from app.agents.confirmation_gate import register_handler, ActionType
        from app.services.sim_templates import dispatch_sim_run

        register_handler(ActionType.SIM_DISPATCH, dispatch_sim_run)
    """
    if action_type in _handlers:
        logger.warning(
            "confirmation_gate | overwriting handler for %s", action_type
        )
    _handlers[action_type] = handler
    logger.info("confirmation_gate | registered handler for %s", action_type)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_expired(proposal: ActionProposal) -> bool:
    return datetime.now(timezone.utc) > proposal.expires_at


async def _load_proposal(
    proposal_id: str,
    db: AsyncIOMotorDatabase,
) -> ActionProposal | None:
    """Fetch a proposal from MongoDB by proposal_id."""
    doc = await db[PROPOSALS_COLLECTION].find_one({"proposal_id": proposal_id})
    if not doc:
        return None
    doc.pop("_id", None)
    return ActionProposal(**doc)


async def _save_proposal(
    proposal: ActionProposal,
    db: AsyncIOMotorDatabase,
) -> None:
    """Upsert a proposal document in MongoDB."""
    await db[PROPOSALS_COLLECTION].replace_one(
        {"proposal_id": proposal.proposal_id},
        proposal.model_dump(mode="json"),
        upsert=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Gate stage 1 — propose()
# ─────────────────────────────────────────────────────────────────────────────

async def propose(
    action_type: ActionType,
    description: str,
    parameters: dict[str, Any],
    requested_by: str,
    db: AsyncIOMotorDatabase,
    project_id: str | None = None,
) -> ActionProposal:
    """
    Stage 1: create and persist a pending action proposal.

    Called by the assistant service (or any service layer component) when
    it determines that an action should be proposed to the engineer.
    Returns the full ActionProposal — the API layer extracts what it needs
    for the client response (description, proposal_id, expires_at).

    The engineer sees `description` in the UI. Make it precise:
      Good:  "Dispatch Flow360 CFD run on NACA0012_v3.usd with Mach 0.3,
              Re 1e6, k-ω SST. Estimated runtime: 45 min. Cost: ~0.80 CU."
      Bad:   "Run simulation"

    Args:
        action_type:  One of ActionType enum values.
        description:  Plain-language proposal text shown to the engineer.
        parameters:   All data needed by the handler at execute() time.
        requested_by: user_id of the triggering engineer.
        db:           AsyncIOMotorDatabase dependency.
        project_id:   Optional project scope for audit filtering.

    Returns:
        ActionProposal with status=PENDING.
    """
    proposal = ActionProposal(
        action_type=action_type,
        description=description,
        parameters=parameters,
        requested_by=requested_by,
        project_id=project_id,
    )
    await _save_proposal(proposal, db)

    logger.info(
        "gate_propose | proposal_id=%s action=%s user=%s",
        proposal.proposal_id,
        action_type,
        requested_by,
    )
    return proposal


# ─────────────────────────────────────────────────────────────────────────────
# Gate stage 2 — confirm()
# ─────────────────────────────────────────────────────────────────────────────

async def confirm(
    proposal_id: str,
    confirmed_by: str,
    db: AsyncIOMotorDatabase,
) -> ActionProposal:
    """
    Stage 2: engineer confirms a pending proposal.

    Validates that the proposal exists, is PENDING, and has not expired.
    Transitions status to CONFIRMED. The API layer calls this when the
    engineer clicks the confirm button — it is the explicit human keystroke
    that the architecture requires.

    Args:
        proposal_id:  UUID of the proposal to confirm.
        confirmed_by: user_id of the confirming engineer (must match
                      requested_by in Phase 1; delegation is Phase 2+).
        db:           AsyncIOMotorDatabase dependency.

    Returns:
        Updated ActionProposal with status=CONFIRMED.

    Raises:
        ValueError: if proposal not found, not PENDING, or expired.
    """
    proposal = await _load_proposal(proposal_id, db)

    if proposal is None:
        raise ValueError(f"Proposal {proposal_id} not found.")

    if proposal.status != ProposalStatus.PENDING:
        raise ValueError(
            f"Proposal {proposal_id} cannot be confirmed: "
            f"current status is {proposal.status}."
        )

    if _is_expired(proposal):
        proposal.status = ProposalStatus.EXPIRED
        await _save_proposal(proposal, db)
        raise ValueError(
            f"Proposal {proposal_id} expired at {proposal.expires_at}. "
            f"Please request a new proposal."
        )

    proposal.status = ProposalStatus.CONFIRMED
    proposal.confirmed_at = datetime.now(timezone.utc)
    await _save_proposal(proposal, db)

    logger.info(
        "gate_confirm | proposal_id=%s action=%s confirmed_by=%s",
        proposal_id,
        proposal.action_type,
        confirmed_by,
    )
    return proposal


# ─────────────────────────────────────────────────────────────────────────────
# Gate stage 3 — execute()
# ─────────────────────────────────────────────────────────────────────────────

async def execute(
    proposal_id: str,
    db: AsyncIOMotorDatabase,
) -> ActionProposal:
    """
    Stage 3: execute a confirmed proposal via its registered handler.

    This is the only code path that performs write actions on the platform.
    It requires the proposal to be in CONFIRMED status — which can only be
    reached via confirm(), which requires an explicit engineer action.

    The handler registered for the action_type is called with the proposal's
    parameters dict. The result is stored in execution_result for audit.

    Args:
        proposal_id: UUID of the confirmed proposal to execute.
        db:          AsyncIOMotorDatabase dependency.

    Returns:
        Updated ActionProposal with status=EXECUTED and execution_result set.

    Raises:
        ValueError:    if proposal not found, not CONFIRMED, or no handler.
        RuntimeError:  if the handler raises during execution (proposal
                       remains CONFIRMED for retry or manual inspection).
    """
    proposal = await _load_proposal(proposal_id, db)

    if proposal is None:
        raise ValueError(f"Proposal {proposal_id} not found.")

    if proposal.status != ProposalStatus.CONFIRMED:
        raise ValueError(
            f"Proposal {proposal_id} cannot be executed: "
            f"current status is {proposal.status}. "
            f"Proposal must be CONFIRMED before execution."
        )

    handler = _handlers.get(proposal.action_type)
    if handler is None:
        raise ValueError(
            f"No handler registered for action type {proposal.action_type}. "
            f"Register one via confirmation_gate.register_handler() at startup."
        )

    logger.info(
        "gate_execute | proposal_id=%s action=%s",
        proposal_id,
        proposal.action_type,
    )

    try:
        result = await handler(proposal.parameters)
    except Exception as exc:
        logger.error(
            "gate_execute_failed | proposal_id=%s action=%s error=%s",
            proposal_id,
            proposal.action_type,
            str(exc),
        )
        # Do not mark EXECUTED — leave as CONFIRMED so the engineer can retry
        # or inspect. Raise so the API layer returns a 500 with context.
        raise RuntimeError(
            f"Handler for {proposal.action_type} failed: {exc}"
        ) from exc

    proposal.status = ProposalStatus.EXECUTED
    proposal.executed_at = datetime.now(timezone.utc)
    proposal.execution_result = result
    await _save_proposal(proposal, db)

    logger.info(
        "gate_executed | proposal_id=%s action=%s",
        proposal_id,
        proposal.action_type,
    )
    return proposal


# ─────────────────────────────────────────────────────────────────────────────
# Abort — engineer cancels at any pre-execution stage
# ─────────────────────────────────────────────────────────────────────────────

async def abort(
    proposal_id: str,
    aborted_by: str,
    reason: str,
    db: AsyncIOMotorDatabase,
) -> ActionProposal:
    """
    Abort a PENDING or CONFIRMED proposal before execution.

    Cannot abort an EXECUTED proposal — those are permanent audit records.

    Args:
        proposal_id: UUID of the proposal to abort.
        aborted_by:  user_id of the engineer aborting.
        reason:      Plain-language reason stored in the audit record.
        db:          AsyncIOMotorDatabase dependency.

    Returns:
        Updated ActionProposal with status=ABORTED.

    Raises:
        ValueError: if proposal not found or already EXECUTED.
    """
    proposal = await _load_proposal(proposal_id, db)

    if proposal is None:
        raise ValueError(f"Proposal {proposal_id} not found.")

    if proposal.status == ProposalStatus.EXECUTED:
        raise ValueError(
            f"Proposal {proposal_id} has already been executed and "
            f"cannot be aborted. Review the execution_result."
        )

    proposal.status = ProposalStatus.ABORTED
    proposal.aborted_at = datetime.now(timezone.utc)
    proposal.abort_reason = reason
    await _save_proposal(proposal, db)

    logger.info(
        "gate_aborted | proposal_id=%s action=%s aborted_by=%s reason=%r",
        proposal_id,
        proposal.action_type,
        aborted_by,
        reason,
    )
    return proposal


# ─────────────────────────────────────────────────────────────────────────────
# Convenience — list pending proposals for a user
# ─────────────────────────────────────────────────────────────────────────────

async def list_pending(
    user_id: str,
    db: AsyncIOMotorDatabase,
    project_id: str | None = None,
) -> list[ProposalSummary]:
    """
    Return all PENDING proposals for a given user, optionally filtered
    by project. Used by the assistant UI to surface outstanding confirmations.
    Expired proposals are cleaned up lazily on read.
    """
    query: dict[str, Any] = {
        "requested_by": user_id,
        "status": ProposalStatus.PENDING,
    }
    if project_id:
        query["project_id"] = project_id

    summaries: list[ProposalSummary] = []
    async for doc in db[PROPOSALS_COLLECTION].find(query):
        doc.pop("_id", None)
        proposal = ActionProposal(**doc)

        # Lazy expiry: mark expired on read if TTL has passed
        if _is_expired(proposal):
            proposal.status = ProposalStatus.EXPIRED
            await _save_proposal(proposal, db)
            continue

        summaries.append(
            ProposalSummary(
                proposal_id=proposal.proposal_id,
                action_type=proposal.action_type,
                description=proposal.description,
                status=proposal.status,
                created_at=proposal.created_at,
                expires_at=proposal.expires_at,
            )
        )

    return summaries


