"""approval_pause.py — a run parked on a person's decision (GH-07, PO-20).

A HITL checkpoint held an Arq worker slot for as long as its ``timeout_ms``
(five minutes by default) while a person decided, so a few pending approvals
starved the pool. Now the checkpoint opens its approval and raises
``HITLPending`` (``governance/hitl_gate.py``), and the loop parks the run the
way it suspends on children: a snapshot, status ``PAUSED``, the worker given
back, the credit hold kept. Three things resume it, whichever comes first:

- the approval endpoint, when the reviewer answers;
- a job deferred to the approval's deadline, which settles it TIMEOUT (or
  APPROVED when the checkpoint auto-approves);
- ``sweep_paused_runs`` in the stuck-run cron, for a resume that was lost.

Each enqueues ``resume_paused_run``, which drives
``AgentLoop.resume_after_approval``: APPROVED continues at the same step,
REJECTED ends the run CANCELLED and TIMEOUT FAILED (GH-25).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select, update

from src.ai.core.agent_state import AgentState
from src.ai.governance import hitl_gate
from src.ai.orm.execution import ExecutionRun
from src.ai.schemas.enums import RunStatus

logger = logging.getLogger(__name__)

RESUME_JOB = "resume_paused_run"
SNAPSHOT_KEY = "__agent_state_snapshot__"


def _step_id(step: Any) -> str:
    if isinstance(step, dict):
        return str(step.get("step_id") or step.get("id") or "")
    return str(getattr(step, "step_id", "") or "")


def _deadline(marker: dict[str, Any]) -> datetime:
    try:
        value = datetime.fromisoformat(str(marker.get("deadline")))
    except ValueError:
        return datetime.now(timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def park(state: AgentState, move: Any, completed: list[str], failed: dict[str, str],
         marker: dict[str, Any]) -> None:
    """Ask the loop to park: the move's steps that did not run go back to the
    front of the queue, as they were, so the resumed run dispatches them again
    — the checkpoint's step first, now with a decision."""
    done = set(completed) | set(failed)
    unrun = [s for s in (move.plan_fragment or []) if _step_id(s) not in done]
    if unrun:
        state.retry_queue.insert(0, {
            "plan_fragment": unrun, "executor": move.executor,
            "retry_move_id": move.move_id, "strategy": "after_approval",
            "rationale": "dispatched again after a person's decision",
        })
    state.awaiting_approval = dict(marker)
    state.suspend_requested = True


async def schedule_deadline(run_id: Any, marker: dict[str, Any]) -> None:
    """A resume at the approval's deadline. Best-effort: the sweeper expires
    a parked run whose deadline job was lost."""
    from src.common.job_queue import enqueue_job

    delay = max((_deadline(marker) - datetime.now(timezone.utc)).total_seconds(), 0.0) + 1.0
    try:
        await enqueue_job(RESUME_JOB, str(run_id), _job_id=f"hitl-deadline:{marker['approval_id']}",
                          _defer_by=delay)
    except Exception as exc:                                                # noqa: BLE001
        logger.warning("Deadline resume not enqueued for run %s: %s", run_id, exc)


async def enqueue_resume(run_id: Any, *, job_id: Optional[str] = None) -> None:
    """Resume a parked run now (the reviewer answered). Best-effort, as above."""
    from src.common.job_queue import enqueue_job

    try:
        await enqueue_job(RESUME_JOB, str(run_id), **({"_job_id": job_id} if job_id else {}))
    except Exception as exc:                                                # noqa: BLE001
        logger.warning("Resume not enqueued for parked run %s: %s", run_id, exc)


async def decision_for(db: Any, marker: dict[str, Any],
                       now: Optional[datetime] = None) -> tuple[str, str]:
    """The approval's decision and notes. Past the deadline a PENDING approval
    is settled — TIMEOUT, or APPROVED when the checkpoint auto-approves."""
    status, notes = await hitl_gate.read_decision(db, marker["approval_id"])
    if status == "PENDING" and (now or datetime.now(timezone.utc)) >= _deadline(marker):
        status, notes = await hitl_gate.settle_deadline(
            db, marker["approval_id"], auto_approve=bool(marker.get("auto_approve")))
    return status, notes


async def claim(db: Any, run_id: UUID) -> bool:
    """Take the parked run: PAUSED → RUNNING once, so two resumes cannot
    both drive it."""
    claimed = (await db.execute(
        update(ExecutionRun)
        .where(ExecutionRun.id == run_id, ExecutionRun.status == RunStatus.PAUSED.value)
        .values(status=RunStatus.RUNNING.value)
        .execution_options(synchronize_session=False)
    )).rowcount
    await db.commit()
    return bool(claimed)


async def take_decision(db: Any, state: AgentState, marker: dict[str, Any],
                        decision: str, notes: str) -> Optional[dict[str, str]]:
    """Fold the decision into the resumed state. Returns the ``blocked``
    marker when the decision ends the run (GH-25), else ``None``."""
    state.awaiting_approval = None
    state.suspend_requested = False
    if decision == "APPROVED":
        if marker.get("phase") == "AFTER":
            # The step already ran; a BEFORE step uses the approval when it is
            # dispatched again.
            await hitl_gate.consume(db, marker["approval_id"])
        return None
    await hitl_gate.consume(db, marker["approval_id"])
    error = hitl_gate.decision_error(decision, str(marker.get("trigger") or ""), notes=notes,
                                     timeout_ms=int(marker.get("timeout_ms") or 0),
                                     approval_id=marker["approval_id"])
    step_id = str(marker.get("step_id") or "")
    if step_id:
        state.completed_step_ids.discard(step_id)
        state.mark_step_failed(step_id, str(error))
    return {"kind": error.kind, "reason": error.reason, "step_id": step_id}


async def sweep_paused_runs(db: Any, *, grace_s: int,
                            now: Optional[datetime] = None) -> int:
    """Re-enqueue the resume of a parked run whose approval was decided, or
    whose deadline passed, more than ``grace_s`` ago — the resume was lost.
    A run paused by the supervisor (no approval) is not touched."""
    from src.ai.core.stuck_runs import SUSPENDED_AT_KEY, _aware

    now = now or datetime.now(timezone.utc)
    rows = (await db.execute(
        select(ExecutionRun.id, ExecutionRun.context_state)
        .where(ExecutionRun.status == RunStatus.PAUSED.value)
    )).all()
    resumed = 0
    for run_id, cs in rows:
        cs = cs or {}
        marker = (cs.get(SNAPSHOT_KEY) or {}).get("awaiting_approval")
        if not marker:
            continue
        try:
            status, _ = await hitl_gate.read_decision(db, marker["approval_id"])
            parked_at = _aware(cs.get(SUSPENDED_AT_KEY)) or now
            decided_long_ago = status != "PENDING" and (now - parked_at).total_seconds() >= grace_s
            expired = (now - _deadline(marker)).total_seconds() >= grace_s
            if decided_long_ago or expired:
                await enqueue_resume(run_id)
                resumed += 1
        except Exception:                                                  # noqa: BLE001
            logger.exception("Paused-run sweep failed for run %s", run_id)
            await db.rollback()
    return resumed
