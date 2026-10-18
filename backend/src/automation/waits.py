"""Durable waiting (tech spec §7.9; functional spec §3.3 "Wait for something").

An agent calls ``wait_for_event`` ("wait until the customer replies, up to 48
hours"): a ``waits`` row (and a ``time_index`` row at its deadline) is
written, the step ends, and the agent loop — seeing the run has a wait —
parks the run ``WAITING_ON_EVENT`` and gives its worker back, keeping its
snapshot and credit hold (as a HITL approval does). Nothing runs while it
waits.

Whichever comes first resumes it, through ``resume_waiting_run``:

* the router: a matching event (its type, its ``match`` filter, after the
  wait began) marks the wait ``satisfied`` — waits are matched before triggers;
* the scheduler: the deadline marks it ``expired``;
* an operator: cancelling it from the Control Room.

On resume the event (or the timeout / cancellation) becomes the waiting
step's result, and the loop carries on from there. The step is not run again,
so nothing it did before waiting is done twice. A resume that was lost is
re-sent by the event worker's sweep.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from src.automation import events as events_mod
from src.automation import filters, guards, schedules
from src.automation.limits import limits_for
from src.automation.models import Event, TimeIndexEntry, Wait

logger = logging.getLogger(__name__)

RESUME_JOB = "resume_waiting_run"
MAX_RESULT_CHARS = 8000
LOST_RESUME_GRACE = timedelta(minutes=2)


class WaitError(ValueError):
    """A wait that cannot be made; the message is what the agent reads."""


# ── Making one (the tool) ──────────────────────────────────────────────────

async def create(db: Any, control_db: Any, company_id: Any, *, run_id: Any, event_type: str,
                 match: Optional[Dict[str, Any]], timeout: str, now: Optional[datetime] = None) -> Wait:
    """A run's wait for an event, with its deadline in the time index (no commit)."""
    now = now or datetime.utcnow()
    pattern = str(event_type or "").strip()
    try:
        events_mod.validate_type(pattern[:-2] + ".x" if pattern.endswith(".*") else pattern)
    except events_mod.EventError:
        raise WaitError("type must be an event type like email.received or custom.lead.replied, "
                        "or a prefix like custom.lead.*") from None
    try:
        spec = filters.validate(match) or None
    except filters.FilterError as error:
        raise WaitError(f"match: {error}") from None
    try:
        length = schedules.parse_duration(timeout)
        guards.wait_timeout(length, await limits_for(company_id, control_db))
    except schedules.ScheduleError as error:
        raise WaitError(f"timeout: {error}") from None
    except guards.AgentLimitExceeded as error:
        raise WaitError(str(error)) from None
    if length > schedules.MAX_DELAY:
        raise WaitError("timeout: a wait may last at most 100 years")
    run_id = UUID(str(run_id))
    if await pending_for_run(db, run_id) is not None:
        raise WaitError("this run is already waiting for an event")

    wait = Wait(id=uuid.uuid4(), company_id=company_id, run_id=run_id, step_ref="", event_type=pattern,
                match=spec, deadline_at=now + length, status="waiting", created_at=now)
    db.add(wait)
    await db.flush()
    await control_db.execute(
        insert(TimeIndexEntry).values(company_id=company_id, ref_kind="wait", ref_id=wait.id,
                                      due_at=wait.deadline_at)
        .on_conflict_do_update(index_elements=["company_id", "ref_kind", "ref_id"],
                               set_={"due_at": wait.deadline_at, "lease_owner": None, "lease_until": None}))
    return wait


def may_wait(entity: Any) -> bool:
    """Whether the entity is granted ``wait_for_event`` — only then can its run have a wait."""
    from src.ai.governance.tool_access import grants_of

    return entity is not None and "wait_for_event" in grants_of(entity)


async def pending_for_run(db: Any, run_id: Any) -> Optional[Wait]:
    """The run's wait that has not been answered yet, if any."""
    return (await db.execute(select(Wait).where(Wait.run_id == UUID(str(run_id)), Wait.status == "waiting")
                             .order_by(Wait.created_at.desc()).limit(1))).scalar_one_or_none()


# ── The loop's side ────────────────────────────────────────────────────────

def park(state: Any, move: Any, completed: List[str], failed: Dict[str, str], wait: Wait) -> None:
    """Ask the loop to park on ``wait``: the move's steps that did not run go back
    to the front of the queue; the step that asked to wait gets the event as its result."""
    from src.ai.core.approval_pause import _step_id

    done = set(completed) | set(failed)
    unrun = [s for s in (getattr(move, "plan_fragment", None) or []) if _step_id(s) not in done]
    if unrun:
        state.retry_queue.insert(0, {
            "plan_fragment": unrun, "executor": move.executor, "retry_move_id": move.move_id,
            "strategy": "after_wait", "rationale": "dispatched after the run's wait for an event",
        })
    state.awaiting_event = {
        "wait_id": str(wait.id), "event_type": wait.event_type,
        "step_id": completed[-1] if completed else "",
        "deadline": wait.deadline_at.isoformat() + "Z" if wait.deadline_at else None,
    }
    state.suspend_requested = True


async def outcome_for(db: Any, marker: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """What the waiting step learns — the event, a timeout, a cancellation — or
    ``None`` while the wait is still open."""
    wait = await db.get(Wait, UUID(str(marker["wait_id"])))
    if wait is None:
        return {"status": "cancelled", "text": "The wait no longer exists; continue without the event."}
    if wait.status == "waiting":
        return None
    if wait.status == "satisfied" and wait.satisfied_by_event_id:
        event = await db.get(Event, wait.satisfied_by_event_id)
        payload = {"type": event.type, "time": event.time.isoformat() + "Z", "subject": event.subject,
                   "data": event.data} if event else {"event_id": str(wait.satisfied_by_event_id)}
        text = "The event you waited for arrived: " + json.dumps(payload, default=str)
        return {"status": "satisfied", "text": text[:MAX_RESULT_CHARS]}
    if wait.status == "cancelled":
        return {"status": "cancelled", "text": f"The wait for {wait.event_type} was cancelled by an operator; "
                                               "continue without it."}
    return {"status": "expired", "text": f"No {wait.event_type} event arrived before the deadline "
                                         f"({wait.deadline_at:%Y-%m-%d %H:%M} UTC); the wait timed out."}


async def claim_run(db: Any, run_id: Any) -> bool:
    """WAITING_ON_EVENT → RUNNING, once: two resumes cannot both drive the run."""
    from src.ai.orm import ExecutionRun

    claimed = (await db.execute(
        update(ExecutionRun)
        .where(ExecutionRun.id == UUID(str(run_id)), ExecutionRun.status == "WAITING_ON_EVENT")
        .values(status="RUNNING").execution_options(synchronize_session=False))).rowcount
    await db.commit()
    return bool(claimed)


def fold(state: Any, marker: Dict[str, Any], outcome: Dict[str, Any]) -> None:
    """The waiting step's result becomes the event (or the timeout)."""
    from src.ai.core.step_results import find_plan_step

    state.awaiting_event = None
    state.suspend_requested = False
    step_id = str(marker.get("step_id") or "")
    if step_id:
        state.context_state[step_id] = outcome["text"]
    step = find_plan_step(state.plan_steps, step_id) if step_id else None
    state.step_results.append({
        "step": (step.get("name") if step else None) or step_id or "wait_for_event",
        "step_id": step_id, "type": "WAIT", "output": outcome["text"][:MAX_RESULT_CHARS],
    })


# ── What answers a wait ────────────────────────────────────────────────────

async def satisfy(db: Any, company_id: Any, event: Event) -> List[Wait]:
    """Waits this event answers (its type and filter, begun before it happened); marked
    ``satisfied`` (no commit). The caller commits, then :func:`enqueue_resume` each run."""
    from src.automation.router import event_view

    rows = (await db.execute(select(Wait).where(
        Wait.company_id == company_id, Wait.status == "waiting", Wait.event_type.isnot(None))
        .order_by(Wait.created_at))).scalars().all()
    view = event_view(event)
    answered = []
    for wait in rows:
        if not events_mod.type_matches(wait.event_type, event.type):
            continue
        if wait.created_at and event.time and event.time < wait.created_at:
            continue  # an event from before the wait began is not its answer
        if not filters.matches(wait.match, view):
            continue
        wait.status, wait.satisfied_by_event_id = "satisfied", event.id
        answered.append(wait)
    if answered:
        await db.flush()
    return answered


async def close(db: Any, control_db: Any, company_id: Any, wait_id: Any, status: str) -> Optional[Wait]:
    """Expire or cancel an open wait and drop its deadline row (no commit)."""
    wait = await db.get(Wait, UUID(str(wait_id)))
    if wait is None or wait.company_id != company_id:
        return None
    if wait.status == "waiting":
        wait.status = status
        await db.flush()
    await control_db.execute(delete(TimeIndexEntry).filter_by(company_id=company_id, ref_kind="wait",
                                                              ref_id=wait.id))
    return wait


async def enqueue_resume(company_id: Any, run_id: Any, wait_id: Any) -> None:
    """Resume the run (best effort: the sweep re-sends a lost one)."""
    from src.common.job_queue import enqueue_job, tenant_arg

    try:
        await enqueue_job(RESUME_JOB, str(run_id), company_id=tenant_arg(company_id), _job_id=f"wait:{wait_id}")
    except Exception as error:  # Redis away: the sweep will
        logger.warning("resume of run %s after its wait not queued (%s); the sweep will", run_id, error)


async def sweep_lost_resumes(db: Any, *, now: Optional[datetime] = None) -> int:
    """Runs still WAITING_ON_EVENT whose wait was answered a while ago: send the resume again.
    Also expires waits past their deadline whose time-index row was lost."""
    from src.ai.orm import ExecutionRun

    now = now or datetime.utcnow()
    resent = 0
    # A wait whose run ended without it (failed, cancelled): nothing will answer it.
    from src.ai.schemas.enums import TERMINAL_RUN_STATUSES

    orphans = (await db.execute(select(Wait).join(ExecutionRun, ExecutionRun.id == Wait.run_id).where(
        Wait.status == "waiting", ExecutionRun.status.in_(tuple(TERMINAL_RUN_STATUSES))))).scalars().all()
    for wait in orphans:
        wait.status = "cancelled"
    if orphans:
        await db.commit()
    rows = (await db.execute(
        select(Wait, ExecutionRun.status).join(ExecutionRun, ExecutionRun.id == Wait.run_id)
        .where(ExecutionRun.status == "WAITING_ON_EVENT"))).all()
    for wait, _status in rows:
        if wait.status == "waiting":
            if wait.deadline_at and wait.deadline_at < now - LOST_RESUME_GRACE:
                wait.status = "expired"
                await db.commit()
                await enqueue_resume(wait.company_id, wait.run_id, f"{wait.id}:late")
                resent += 1
            continue
        answered_at = wait.deadline_at if wait.status == "expired" else None
        if wait.status == "satisfied" and wait.satisfied_by_event_id:
            event = await db.get(Event, wait.satisfied_by_event_id)
            answered_at = event.received_at if event else None
        if answered_at is not None and answered_at > now - LOST_RESUME_GRACE:
            continue  # its resume is most likely on its way
        await enqueue_resume(wait.company_id, wait.run_id, f"{wait.id}:{now:%Y%m%d%H%M}")
        resent += 1
    return resent


async def list_waiting(db: Any, company_id: Any, limit: int = 200) -> List[Wait]:
    return list((await db.execute(select(Wait).where(Wait.company_id == company_id, Wait.status == "waiting")
                                  .order_by(Wait.deadline_at).limit(limit))).scalars().all())
