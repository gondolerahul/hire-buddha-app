"""hitl_gate.py — the approval a fired HITL checkpoint waits on (GH-07, PO-20).

A checkpoint that fires does not hold the worker. It opens a PENDING
``HumanApproval`` and raises ``HITLPending``; the loop parks the run ``PAUSED``
and gives the worker back (``core/approval_pause.py``). The reviewer's answer,
or the deadline, resumes the run, and the step is dispatched again. This time
the checkpoint finds its approval: APPROVED lets the step run, REJECTED or
TIMEOUT end the run (GH-25), still PENDING parks it again.

A decision is used once (``consumed_at``), so the next time the checkpoint
fires — the step retried, another step past a cost threshold — a person is
asked again, as when the wait blocked.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select, update

from src.ai.core.exceptions import HITLDecisionError, HITLPending, HITLRejected, HITLTimeout
from src.ai.orm import HumanApproval

logger = logging.getLogger(__name__)


@dataclass
class OpenApproval:
    """An approval no step has acted on yet."""

    id: Any
    status: str
    notes: str
    timeout_ms: int
    requested_at: Optional[datetime]


def _utc(value: Optional[datetime]) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def deadline_of(requested_at: Optional[datetime], timeout_ms: int) -> datetime:
    return _utc(requested_at) + timedelta(milliseconds=max(int(timeout_ms or 0), 0))


async def open_approval(db: Any, run_id: Any, trigger: str) -> Optional[OpenApproval]:
    """The run's latest approval for this checkpoint that no step has used."""
    row = (await db.execute(
        select(HumanApproval.id, HumanApproval.status, HumanApproval.reviewer_notes,
               HumanApproval.timeout_ms, HumanApproval.requested_at)
        .where(HumanApproval.run_id == run_id,
               HumanApproval.checkpoint_trigger == trigger,
               HumanApproval.consumed_at.is_(None))
        .order_by(HumanApproval.requested_at.desc())
        .limit(1)
    )).first()
    if row is None:
        return None
    approval_id, status, notes, timeout_ms, requested_at = row
    return OpenApproval(approval_id, str(status or "PENDING"), str(notes or "").strip(),
                        int(timeout_ms or 0), requested_at)


async def consume(db: Any, approval_id: Any) -> None:
    """Mark a decision used: the step it decided has acted on it."""
    await db.execute(
        update(HumanApproval)
        .where(HumanApproval.id == approval_id, HumanApproval.consumed_at.is_(None))
        .values(consumed_at=datetime.now(timezone.utc))
    )
    await db.commit()


def pending(approval: OpenApproval, *, trigger: str, phase: str, step_id: str,
            auto_approve: bool) -> HITLPending:
    return HITLPending(
        str(approval.id), trigger=trigger, phase=phase, step_id=step_id,
        deadline=deadline_of(approval.requested_at, approval.timeout_ms).isoformat(),
        timeout_ms=approval.timeout_ms, auto_approve=auto_approve,
    )


def decision_error(status: str, trigger: str, *, notes: str, timeout_ms: int,
                   approval_id: Any) -> HITLDecisionError:
    """What a REJECTED or TIMEOUT approval raises: the loop ends the run on it."""
    if status == "REJECTED":
        return HITLRejected(
            f"Execution blocked by human reviewer: {trigger}" + (f" — {notes}" if notes else ""),
            approval_id=str(approval_id),
        )
    return HITLTimeout(f"HITL checkpoint timed out after {timeout_ms}ms: {trigger}",
                       approval_id=str(approval_id))


async def read_decision(db: Any, approval_id: Any) -> tuple[str, str]:
    """The approval's status and the reviewer's notes."""
    row = (await db.execute(
        select(HumanApproval.status, HumanApproval.reviewer_notes)
        .where(HumanApproval.id == approval_id)
    )).first()
    if row is None:
        return "MISSING", ""
    return str(row[0] or "PENDING"), str(row[1] or "").strip()


async def settle_deadline(db: Any, approval_id: Any, *, auto_approve: bool) -> tuple[str, str]:
    """The deadline has passed: TIMEOUT, or APPROVED when the checkpoint
    auto-approves. Only a PENDING row changes — a decision that landed first
    wins. Returns the status and notes after."""
    final = "APPROVED" if auto_approve else "TIMEOUT"
    await db.execute(
        update(HumanApproval)
        .where(HumanApproval.id == approval_id, HumanApproval.status == "PENDING")
        .values(status=final, responded_at=datetime.now(timezone.utc),
                reviewer_notes="Auto-approved on timeout" if auto_approve else None)
    )
    await db.commit()
    from src.automation.run_events import emit_approval

    approval = await db.get(HumanApproval, approval_id, populate_existing=True)
    if approval is not None:
        await emit_approval(db, approval)  # approval.decided: TIMEOUT or auto-approved (W3-1)
    return await read_decision(db, approval_id)
