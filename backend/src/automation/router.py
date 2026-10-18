"""The event router (tech spec §7.8): ``route_event`` on queue ``events``.

For one stored event, in the event's tenant database:

1. Only an event still ``received`` (or ``parked``, when released) is routed:
   a duplicate nudge does nothing.
2. Automation paused (the business, or the platform's emergency stop) →
   the event is ``parked``; resuming releases parked events, oldest first.
3. Each matching trigger decides once (``trigger_firings`` is unique per
   trigger and event): a schedule or timer event names its one trigger; any
   other event goes to the enabled event and data triggers listening to its
   type whose filter passes, made before the event happened ("run now" is a
   ``manual.fired`` event for its trigger). Then, in order: the loop limit, the trigger's
   rate, overlap, the business's concurrency (each only if set, D47), the
   agent's own policy (active, not opted out of automatic runs), and the
   run's checks — input, wallet, quota — through ``AIService.trigger_execution``.
   Every decision is recorded with its reason; a started run and its firing
   commit together.
4. The event is ``routed``. An error leaves it for a retry with backoff
   (1, 5, 30 minutes); after the fifth attempt it is ``dead`` (an
   ``automation.event_dead`` event says so) until someone replays it.

A run that must wait its turn (overlap ``queue``, the business's
concurrency, the company's runs-a-minute quota) is a ``queued`` firing with
no run yet; ``drain_queued`` starts the oldest when there is room. (The spec
sketches a PENDING run with a ``not_before``; a firing keeps the kernel's run
states as they are, and the run is created only when it can start.)

Waiting runs (``wait_for_event``) are matched here once the kernel can
suspend on events (WS3 3.6).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func, select

from src.automation import filters, guards, templates, triggers as triggers_mod
from src.automation.events import Envelope
from src.automation.limits import AutomationLimits, automation_state_for, limits_for
from src.automation.models import Event, Trigger, TriggerFiring

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
RETRY_DELAYS = (60, 300, 1800, 1800)  # seconds before attempts 2, 3, 4, 5
# Events addressed to one trigger (``data.trigger_id``): its schedule, its timer, "run now".
DIRECTED_TYPES = ("schedule.fired", "timer.fired", "manual.fired")
ACTIVE_RUN_STATUSES = ("PENDING", "RUNNING", "PAUSED", "RESUMING", "REFINING", "WAITING_ON_CHILDREN",
                       "WAITING_ON_EVENT")
RUNNABLE_STATUSES = ("ACTIVE", "DEPRECATED")


def _control(db: Any) -> Any:
    """The session to read automation settings with: in single mode the tenant
    session is on the control database too; in split mode, a control session of its own."""
    from src.common.tenancy.session import is_split

    return None if is_split() else db


def event_view(event: Event) -> Dict[str, Any]:
    """The JSON an event's filter and input template see."""
    return {
        "id": str(event.id), "type": event.type, "source": event.source, "subject": event.subject,
        "time": event.time.isoformat() + "Z" if event.time else None, "trust": event.trust,
        "chain_depth": event.chain_depth,
        "correlation_id": str(event.correlation_id) if event.correlation_id else None,
        "data": event.data or {},
    }


async def _candidates(db: Any, company_id: Any, event: Event) -> List[Trigger]:
    if event.type in DIRECTED_TYPES:
        trigger_id = (event.data or {}).get("trigger_id")
        trigger = await triggers_mod.get(db, company_id, trigger_id) if trigger_id else None
        return [trigger] if trigger is not None and trigger.enabled else []
    return await triggers_mod.listening(db, company_id, event.type)


async def _active_runs(db: Any, company_id: Any, trigger_id: Optional[UUID] = None) -> int:
    """Top-level runs still going: of one trigger, or of every trigger of the business."""
    from src.ai.orm import ExecutionRun

    query = select(func.count()).select_from(ExecutionRun).where(
        ExecutionRun.company_id == company_id, ExecutionRun.status.in_(ACTIVE_RUN_STATUSES),
        ExecutionRun.parent_run_id.is_(None))
    query = query.where(ExecutionRun.trigger_id == trigger_id) if trigger_id else \
        query.where(ExecutionRun.trigger_id.isnot(None))
    return (await db.execute(query)).scalar() or 0


async def _started_last_hour(db: Any, trigger_id: UUID, now: datetime) -> int:
    return (await db.execute(select(func.count()).select_from(TriggerFiring).where(
        TriggerFiring.trigger_id == trigger_id, TriggerFiring.outcome.in_((guards.STARTED, guards.QUEUED)),
        TriggerFiring.decided_at > now - timedelta(hours=1)))).scalar() or 0


async def room(db: Any, company_id: Any, trigger: Trigger, limits: AutomationLimits,
               policy: Optional[str] = None) -> guards.Decision:
    """Overlap, then the business's concurrency: start now, queue, or skip."""
    overlap = guards.overlap(await _active_runs(db, company_id, trigger.id), policy or trigger.overlap,
                             trigger.max_concurrency, limits)
    if overlap.outcome != guards.STARTED:
        return overlap
    if limits.max_active_runs is not None:
        busy = guards.business_concurrency(await _active_runs(db, company_id), limits)
        if busy:
            return busy
    return overlap


async def policy(db: Any, company_id: Any, trigger: Trigger) -> Optional[guards.Decision]:
    """The agent's own rules: it exists, is active, and allows automatic runs."""
    from src.ai.orm import HierarchicalEntity

    entity = await db.get(HierarchicalEntity, trigger.entity_id)
    if entity is None or entity.company_id != company_id or entity.status == "DELETED":
        return guards.Decision(guards.BLOCKED_POLICY, "not started: the agent no longer exists")
    status = str(getattr(entity.status, "value", entity.status) or "").upper()
    if trigger.entity_version_id is None and status not in RUNNABLE_STATUSES:
        return guards.Decision(guards.BLOCKED_POLICY,
                               f"not started: the agent is {status}; only an active agent runs automatically")
    automation = (entity.capabilities or {}).get("automation") if isinstance(entity.capabilities, dict) else None
    if isinstance(automation, dict) and automation.get("triggerable") is False:
        return guards.Decision(guards.BLOCKED_POLICY, "not started: the agent does not allow automatic runs")
    return None


async def decide(db: Any, company_id: Any, trigger: Trigger, event: Event, limits: AutomationLimits,
                 now: datetime) -> guards.Decision:
    """The rules for one trigger and event, in the order of §7.8 (none apply unless set)."""
    stopped = guards.chain_depth(event.chain_depth, limits)
    if stopped:
        return stopped
    if trigger.rate_per_hour is not None or limits.trigger_rate_per_hour is not None:
        stopped = guards.rate(await _started_last_hour(db, trigger.id, now), trigger.rate_per_hour, limits)
        if stopped:
            return stopped
    decision = await room(db, company_id, trigger, limits)
    if not decision.starts:
        return decision
    return await policy(db, company_id, trigger) or decision


def _render_input(trigger: Trigger, event: Event) -> Dict[str, Any]:
    rendered = templates.render(trigger.input_template or {}, event_view(event),
                                {"id": str(trigger.id), "name": trigger.name})
    return rendered if isinstance(rendered, dict) else {"input": rendered}


def _refusal(error: Exception) -> guards.Decision:
    """Why the run's own checks refused it, as a firing outcome."""
    status = getattr(error, "status_code", None)
    detail = getattr(error, "detail", None) or str(error)
    if status == 402:
        return guards.Decision(guards.BLOCKED_BUDGET, f"not started: {detail}")
    if status == 429:  # the company's runs-a-minute quota: wait a turn
        return guards.Decision(guards.QUEUED, f"queued: {detail}")
    if isinstance(error, templates.TemplateError):
        return guards.Decision(guards.FAILED, f"input template: {error}")
    return guards.Decision(guards.BLOCKED_POLICY, f"not started: {detail}")


async def _firing(db: Any, trigger_id: UUID, event_id: UUID) -> Optional[TriggerFiring]:
    return (await db.execute(select(TriggerFiring).where(
        TriggerFiring.trigger_id == trigger_id, TriggerFiring.event_id == event_id))).scalar_one_or_none()


async def start(db: Any, company_id: Any, trigger: Trigger, event: Event, firing: TriggerFiring) -> guards.Decision:
    """Create the trigger's run; ``firing`` (pending in ``db``) commits with it.

    Returns the decision that stands: ``started``, or why the run's checks
    refused it (the firing is then rolled back for the caller to record).
    """
    from src.ai.schemas.execution import ExecutionRunCreate
    from src.ai.service import AIService

    run_id, trigger_id, event_id = uuid.uuid4(), trigger.id, event.id  # a rollback expires the objects
    firing.run_id, firing.outcome = run_id, guards.STARTED
    try:
        await AIService(db).trigger_execution(
            ExecutionRunCreate(entity_id=trigger.entity_id, input_data=_render_input(trigger, event)), company_id,
            user_id=trigger.created_by_id if trigger.created_by_kind == "user" else None,
            entity_version_id=trigger.entity_version_id,
            # Written on the run as it is created, with its firing in the same commit.
            automation={"id": run_id, "trigger_id": trigger.id, "event_id": event.id,
                        "correlation_id": event.correlation_id or event.id, "chain_depth": event.chain_depth},
        )
    except Exception as error:
        await db.rollback()
        if await _firing(db, trigger_id, event_id) is not None:
            # The run and its firing committed; only queueing it failed — the
            # stuck-run sweep queues a PENDING run whose job was lost.
            logger.warning("run %s for trigger %s committed but was not queued: %s", run_id, trigger_id, error)
            return guards.Decision(guards.STARTED)
        return _refusal(error)
    return guards.Decision(guards.STARTED)


async def _loop_blocked(db: Any, trigger: Trigger, event: Event, decision: guards.Decision) -> None:
    from src.automation import store

    await store.record(db, event.company_id, Envelope(
        type="automation.loop_blocked", source="automation:router", trust="internal",
        dedupe_key=f"loop:{trigger.id}:{event.id}", subject=f"trigger:{trigger.id}",
        data={"trigger_id": str(trigger.id), "trigger_name": trigger.name, "event_id": str(event.id),
              "event_type": event.type, "chain_depth": event.chain_depth, "reason": decision.reason}))


def _count_firing(trigger: Trigger, now: datetime) -> None:
    trigger.last_fired_at = now
    if trigger.kind in triggers_mod.EVENT_KINDS:  # the scheduler counts a schedule's fire times
        trigger.firings = (trigger.firings or 0) + 1
        if trigger.max_firings is not None and trigger.firings >= trigger.max_firings:
            trigger.enabled, trigger.paused_reason = False, f"finished: ran {trigger.firings} times"


async def decide_and_start(db: Any, company_id: Any, trigger: Trigger, event: Event, limits: AutomationLimits,
                           now: datetime) -> Dict[str, Any]:
    """One trigger's decision about one event, recorded and committed."""
    decision = await decide(db, company_id, trigger, event, limits, now)
    trigger_id, event_id = trigger.id, event.id
    firing = TriggerFiring(id=uuid.uuid4(), trigger_id=trigger_id, event_id=event_id, decided_at=now,
                           outcome=decision.outcome, reason=decision.reason or None)
    if decision.outcome == guards.STARTED:
        db.add(firing)
        _count_firing(trigger, now)
        decision = await start(db, company_id, trigger, event, firing)
        if decision.outcome != guards.STARTED:  # refused and rolled back: record why
            trigger = await db.get(Trigger, trigger_id)
            firing = TriggerFiring(id=uuid.uuid4(), trigger_id=trigger_id, event_id=event_id, decided_at=now,
                                   outcome=decision.outcome, reason=decision.reason or None)
            db.add(firing)
    else:
        db.add(firing)
        if decision.outcome == guards.SKIPPED_CHAIN_DEPTH:
            await _loop_blocked(db, trigger, await db.get(Event, event_id), decision)
    await db.commit()
    return {"trigger": str(trigger_id), "outcome": decision.outcome, "reason": decision.reason or None,
            "run": str(firing.run_id) if firing.run_id else None}


async def route(db: Any, company_id: Any, event_id: Any, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Route one event in the tenant session ``db``; returns what was decided."""
    now = now or datetime.utcnow()
    event = await db.get(Event, event_id)
    if event is None or event.status not in ("received", "parked"):
        return {"event": str(event_id), "skipped": "not waiting to be routed"}
    if company_id is not None and event.company_id != company_id:
        return {"event": str(event_id), "skipped": "not this business's event"}
    company_id = event.company_id

    if await automation_state_for(company_id, _control(db)) != "running":
        event.status, event.last_error = "parked", "held: automation is paused"
        await db.commit()
        return {"event": str(event_id), "parked": True}

    limits = await limits_for(company_id, _control(db))
    decided: List[Dict[str, Any]] = []
    # By id: a refused run rolls the session back, which expires loaded objects.
    for trigger_id in [t.id for t in await _candidates(db, company_id, event)]:
        trigger, event = await db.get(Trigger, trigger_id), await db.get(Event, event_id)
        if await _firing(db, trigger_id, event_id) is not None:
            continue  # this trigger already decided about this event (a replay)
        if trigger.kind in triggers_mod.EVENT_KINDS:
            if trigger.created_at is not None and event.time is not None and event.time < trigger.created_at:
                continue  # a trigger answers events from after it was made, not history
            if not filters.matches(trigger.filter, event_view(event)):
                continue
        decided.append(await decide_and_start(db, company_id, trigger, event, limits, now))

    event = await db.get(Event, event_id)
    event.status, event.routed_at, event.last_error = "routed", now, None
    await db.commit()
    return {"event": str(event_id), "decisions": decided}


async def drain_queued(db: Any, company_id: Any, *, now: Optional[datetime] = None, limit: int = 100) -> int:
    """Start queued firings, oldest first, where there is room now; returns how many started."""
    now = now or datetime.utcnow()
    if await automation_state_for(company_id, _control(db)) != "running":
        return 0
    limits = await limits_for(company_id, _control(db))
    queued = (await db.execute(select(TriggerFiring.id).join(Trigger, Trigger.id == TriggerFiring.trigger_id).where(
        Trigger.company_id == company_id, TriggerFiring.outcome == guards.QUEUED, TriggerFiring.run_id.is_(None))
        .order_by(TriggerFiring.decided_at).limit(limit))).scalars().all()
    started, full = 0, set()
    for firing_id in queued:
        firing = await db.get(TriggerFiring, firing_id)
        if firing is None or firing.trigger_id in full:
            continue
        trigger = await db.get(Trigger, firing.trigger_id)
        event = await db.get(Event, firing.event_id) if firing.event_id else None
        if trigger is None or event is None or not trigger.enabled:
            firing.outcome, firing.reason = guards.BLOCKED_POLICY, "not started: the trigger was turned off while queued"
            await db.commit()
            continue
        # Waiting its turn: start only when the trigger and the business have room.
        decision = await room(db, company_id, trigger, limits, policy="skip")
        if decision.outcome == guards.STARTED:
            decision = await policy(db, company_id, trigger) or decision
        if decision.outcome == guards.SKIPPED_OVERLAP or decision.outcome == guards.QUEUED:
            full.add(trigger.id)
            continue
        if decision.outcome == guards.STARTED:
            firing.reason = f"started after waiting in the queue since {firing.decided_at:%Y-%m-%d %H:%M} UTC"
            _count_firing(trigger, now)
            decision = await start(db, company_id, trigger, event, firing)
            if decision.outcome == guards.STARTED:
                started += 1
                continue
            if decision.outcome == guards.QUEUED:  # the quota again: try on the next sweep
                full.add(trigger.id)
                continue
            firing = await db.get(TriggerFiring, firing_id)
        firing.outcome, firing.reason = decision.outcome, decision.reason or None
        await db.commit()
    return started


async def route_event(ctx: Dict[str, Any], event_id: str, company_id: Optional[str] = None) -> Dict[str, Any]:
    """arq job: route one event; retried with backoff, ``dead`` after five attempts."""
    from arq import Retry

    from src.common.tenancy.session import tenant_session

    company = UUID(str(company_id)) if company_id else None
    try:
        async with tenant_session(company) as db:
            return await route(db, company, UUID(event_id))
    except Exception as error:
        attempt = int(ctx.get("job_try") or 1)
        logger.exception("routing event %s failed (attempt %s)", event_id, attempt)
        await _note_failure(company, event_id, error, dead=attempt >= MAX_ATTEMPTS)
        if attempt >= MAX_ATTEMPTS:
            return {"event": event_id, "dead": True}
        raise Retry(defer=RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)])


async def _note_failure(company_id: Any, event_id: str, error: Exception, *, dead: bool) -> None:
    from src.automation import store
    from src.common.tenancy.session import tenant_session

    try:
        async with tenant_session(company_id) as db:
            event = await db.get(Event, UUID(event_id))
            if event is None:
                return
            event.attempts = (event.attempts or 0) + 1
            event.last_error = f"{type(error).__name__}: {error}"[:2000]
            if dead:
                event.status = "dead"
                await store.record(db, event.company_id, Envelope(
                    type="automation.event_dead", source="automation:router", trust="internal",
                    dedupe_key=f"dead:{event_id}:{event.attempts}", subject=f"event:{event_id}",
                    data={"event_id": event_id, "event_type": event.type, "error": event.last_error}))
            await db.commit()
    except Exception:
        logger.exception("could not record the failure of event %s", event_id)


async def replay(db: Any, company_id: Any, event_id: Any) -> bool:
    """An operator's replay of a dead or parked event: routed again; a trigger
    that already decided about it does not decide twice."""
    from src.automation.store import nudge

    event = await db.get(Event, event_id)
    if event is None or event.status not in ("dead", "parked"):
        return False
    event.status, event.last_error = "received", None
    await db.commit()
    await nudge(company_id, event.id, attempt=f"replay-{uuid.uuid4().hex[:8]}")
    return True


async def release_parked(db: Any, company_id: Any, *, limit: int = 1000) -> int:
    """After a resume: route the events held while paused, oldest first, in this process."""
    from src.automation.store import parked

    if await automation_state_for(company_id, _control(db)) != "running":
        return 0
    released = 0
    for event_id in await parked(db, company_id, limit=limit):
        result = await route(db, company_id, event_id)
        if result.get("parked"):  # paused again meanwhile
            break
        released += 1
    return released
