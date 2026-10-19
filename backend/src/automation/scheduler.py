"""The tenant scheduler (tech spec §7.7): ``python -m src.automation.scheduler``.

Every ``SCHEDULER_TICK_SECONDS`` it claims the control plane's due
``time_index`` rows (``FOR UPDATE SKIP LOCKED`` with a 60-second lease, so
two replicas share the work and a crashed one's rows come back) and, for a
trigger, stores one ``schedule.fired`` / ``timer.fired`` event per fire time
in the business's database — ``dedupe_key`` is the trigger and the time, so a
double tick cannot fire twice — then nudges the router.

* **Late** (the due time is older than ``SCHEDULER_GRACE_SECONDS``: the
  scheduler was down or the business was paused): the trigger's catch-up rule,
  else the business's (D47) — ``skip`` records the missed times as
  ``skipped_missed``, ``once`` fires the latest, ``all`` fires each, the latest
  ``catch_up_max`` when the business set that limit.
* **Paused** automation: nothing fires; the row is looked at again a minute
  later, and the missed times follow the catch-up rule after the resume.
* Fire times are cron in the trigger's IANA zone (else the business's): a
  DST gap fires at the next valid minute, an overlap fires once (``schedules``).
* At most ``FIRE_BATCH`` events per trigger per tick; the rest are still due
  and fire on the next tick.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import delete, or_, select, update

from src.automation import guards, schedules, store, triggers as triggers_mod
from src.automation.events import Envelope, schedule_dedupe_key
from src.automation.limits import AutomationLimits, automation_state_for, limits_for
from src.automation.models import TimeIndexEntry, Trigger, TriggerFiring

logger = logging.getLogger(__name__)

LEASE = timedelta(seconds=60)
PAUSED_RECHECK = timedelta(seconds=60)
UNSUPPORTED_RECHECK = timedelta(minutes=5)
CLAIM_BATCH = 200
FIRE_BATCH = 200


@dataclass(frozen=True)
class Due:
    company_id: UUID
    ref_kind: str
    ref_id: UUID
    due_at: datetime


def owner_id() -> str:
    return f"scheduler:{socket.gethostname()}:{os.getpid()}"


def _grace() -> timedelta:
    from src.common.config import settings

    return timedelta(seconds=settings.SCHEDULER_GRACE_SECONDS)


# ── Which times fire (pure) ────────────────────────────────────────────────

def latest_times(expression: str, tz_name: str, first: datetime, until: datetime, count: int) -> List[datetime]:
    """The last ``count`` fire times in ``[first, until]``, without walking every
    one of a long outage: look back an hour, then twice as far, until enough."""
    floor = first - timedelta(seconds=1)
    window = timedelta(hours=1)
    while True:
        since = max(floor, until - window)
        times = schedules.missed_times(expression, tz_name, since, until, limit=100_000)
        if len(times) >= count or since <= floor:
            return times[-count:]
        window *= 2


@dataclass
class Plan:
    fire: List[datetime]          # times to store events for, oldest first
    skipped: Optional[Tuple[datetime, datetime]] = None  # the first and last missed time not fired
    after: Optional[datetime] = None  # the next fire time is after this


def plan(trigger: Any, *, now: datetime, tz_name: str, limits: AutomationLimits, grace: timedelta) -> Plan:
    """What one due trigger fires now (no I/O)."""
    first = trigger.next_fire_at
    if first is None or first > now:
        return Plan(fire=[], after=now)
    late = now - first > grace
    policy = guards.catch_up_policy(trigger.catch_up, limits) if late else "all"

    if trigger.kind == "timer":
        fire = [] if policy == "skip" else [first]
        return Plan(fire=fire, skipped=None if fire else (first, first), after=now)

    floor = first - timedelta(seconds=1)
    until = min(now, trigger.until_at) if trigger.until_at is not None else now
    if policy == "skip":
        missed = schedules.missed_times(trigger.cron, tz_name, floor, until, limit=1)
        return Plan(fire=[], skipped=(first, until) if missed else None, after=now)
    if policy == "once":
        fire = latest_times(trigger.cron, tz_name, first, until, 1)
    elif late and limits.catch_up_max is not None:
        fire = latest_times(trigger.cron, tz_name, first, until, limits.catch_up_max)
    else:
        fire = schedules.missed_times(trigger.cron, tz_name, floor, until, limit=FIRE_BATCH + 1)
    if trigger.max_firings is not None:
        fire = fire[:max(0, trigger.max_firings - (trigger.firings or 0))]
    skipped = (first, fire[0] - timedelta(seconds=1)) if fire and fire[0] > first and late else None
    if len(fire) > FIRE_BATCH:  # the rest on the next tick
        return Plan(fire=fire[:FIRE_BATCH], skipped=skipped, after=fire[FIRE_BATCH - 1])
    return Plan(fire=fire, skipped=skipped, after=now)


# ── Claiming and firing ────────────────────────────────────────────────────

async def claim(owner: str, now: datetime, *, batch: int = CLAIM_BATCH) -> List[Due]:
    """Lease the due rows no other scheduler holds."""
    from src.common.tenancy.session import control_session

    async with control_session() as cdb:
        rows = (await cdb.execute(
            select(TimeIndexEntry)
            .where(TimeIndexEntry.due_at <= now,
                   or_(TimeIndexEntry.lease_until.is_(None), TimeIndexEntry.lease_until < now))
            .order_by(TimeIndexEntry.due_at).limit(batch).with_for_update(skip_locked=True)
        )).scalars().all()
        due = [Due(r.company_id, r.ref_kind, r.ref_id, r.due_at) for r in rows]
        for row in rows:
            row.lease_owner, row.lease_until = owner, now + LEASE
        await cdb.commit()
    return due


def _key(due: Due) -> Dict[str, Any]:
    return {"company_id": due.company_id, "ref_kind": due.ref_kind, "ref_id": due.ref_id}


async def _hold(cdb: Any, due: Due, owner: str, until: datetime) -> None:
    await cdb.execute(update(TimeIndexEntry).filter_by(**_key(due), lease_owner=owner).values(lease_until=until))
    await cdb.commit()


def _envelope(trigger: Trigger, moment: datetime, tz_name: str, now: datetime) -> Envelope:
    kind = "timer.fired" if trigger.kind == "timer" else "schedule.fired"
    return Envelope(
        type=kind, source="automation:scheduler", trust="internal", subject=f"trigger:{trigger.id}",
        dedupe_key=schedule_dedupe_key(trigger.id, moment), time=moment,
        data={"trigger_id": str(trigger.id), "trigger_name": trigger.name,
              "scheduled_for": moment.isoformat() + "Z", "timezone": tz_name,
              "late_seconds": max(0, int((now - moment).total_seconds()))},
    )


async def fire_trigger(due: Due, owner: str, now: datetime) -> Dict[str, Any]:
    """Fire one due trigger: its events in the tenant database, then its next time in the index."""
    from src.common.tenancy.session import control_session, tenant_session
    from src.common.timezones import company_timezone_name

    async with tenant_session(due.company_id) as db, control_session() as cdb:
        trigger = await triggers_mod.get(db, due.company_id, due.ref_id)
        if trigger is None:
            await cdb.execute(delete(TimeIndexEntry).filter_by(**_key(due)))
            await cdb.commit()
            return {"trigger": str(due.ref_id), "gone": True}
        if await automation_state_for(due.company_id, cdb) != "running":
            await _hold(cdb, due, owner, now + PAUSED_RECHECK)
            return {"trigger": str(trigger.id), "paused": True}

        tz_name = trigger.timezone or await company_timezone_name(due.company_id, cdb)
        result: Dict[str, Any] = {"trigger": str(trigger.id), "fired": 0}
        created: List[UUID] = []
        missed = None
        if trigger.next_fire_at is not None and trigger.next_fire_at > now:
            pass  # an edit moved the trigger later than its index row: the row only follows
        elif trigger.enabled and trigger.kind in triggers_mod.TIMED:
            decided = plan(trigger, now=now, tz_name=tz_name, limits=await limits_for(due.company_id, cdb),
                           grace=_grace())
            for moment in decided.fire:
                row, new = await store.record(db, due.company_id, _envelope(trigger, moment, tz_name, now))
                if new:
                    created.append(row.id)
            if decided.skipped:
                start, end = decided.skipped
                missed = (start, end)  # the owner is told after the commit
                db.add(TriggerFiring(trigger_id=trigger.id, event_id=None, decided_at=now,
                                     outcome=guards.SKIPPED_MISSED,
                                     reason=f"missed while automation was not running: {start:%Y-%m-%d %H:%M} to "
                                            f"{end:%Y-%m-%d %H:%M} UTC (catch-up rule)"))
            if trigger.kind != "condition":  # a condition trigger counts the runs its checks start (router)
                trigger.firings = (trigger.firings or 0) + len(created)
            trigger.next_fire_at = triggers_mod.next_fire_at(trigger, now=decided.after or now,
                                                             default_timezone=tz_name)
            if trigger.kind == "timer":
                trigger.next_fire_at = None  # a timer fires (or is skipped) once
            result.update(fired=len(created), skipped=bool(decided.skipped), events=[str(e) for e in created])
        else:
            trigger.next_fire_at = None
        await db.commit()
        await triggers_mod.sync_time_index(cdb, due.company_id, trigger)
        await cdb.commit()
        result["next_fire_at"] = trigger.next_fire_at.isoformat() + "Z" if trigger.next_fire_at else None

    for event_id in created:
        await store.nudge(due.company_id, event_id)
    if missed is not None:
        from src.automation import notify

        await notify.missed_schedule(due.company_id, trigger, *missed)
    return result


async def fire_wait(due: Due) -> Dict[str, Any]:
    """A wait's deadline: expire it if still open and resume its run with the timeout."""
    from src.automation import waits as waits_mod
    from src.automation.models import Wait
    from src.common.tenancy.session import control_session, tenant_session

    async with tenant_session(due.company_id) as db, control_session() as cdb:
        wait = await db.get(Wait, due.ref_id)
        expired = wait is not None and wait.status == "waiting"
        if wait is None:
            await cdb.execute(delete(TimeIndexEntry).filter_by(**_key(due)))
        else:
            await waits_mod.close(db, cdb, due.company_id, wait.id, "expired")
        await db.commit()
        await cdb.commit()
        run_id = wait.run_id if wait is not None else None
    if expired:
        await waits_mod.enqueue_resume(due.company_id, run_id, due.ref_id)
    return {"wait": str(due.ref_id), "expired": expired}


async def fire_scratch_cleanup(due: Due) -> Dict[str, Any]:
    """Scratch code reached its clean-up date (WS6, D35): delete it unless it was promoted."""
    from src.code_lanes.service import expire_scratch
    from src.common.tenancy.session import control_session

    result = await expire_scratch(due.company_id, due.ref_id)
    async with control_session() as cdb:
        await cdb.execute(delete(TimeIndexEntry).filter_by(**_key(due)))
        await cdb.commit()
    return result


async def fire(due: Due, owner: str, now: datetime) -> Dict[str, Any]:
    from src.automation import metrics

    metrics.lag((now - due.due_at).total_seconds())
    if due.ref_kind == "trigger":
        return await fire_trigger(due, owner, now)
    if due.ref_kind == "wait":
        return await fire_wait(due)
    if due.ref_kind == "scratch_cleanup":
        return await fire_scratch_cleanup(due)
    # Connection refreshes run on their own cron (WS5 connection_refresh).
    from src.common.tenancy.session import control_session

    async with control_session() as cdb:
        await _hold(cdb, due, owner, now + UNSUPPORTED_RECHECK)
    return {"ref": f"{due.ref_kind}:{due.ref_id}", "unsupported": due.ref_kind}


async def tick(owner: Optional[str] = None, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """One pass: claim what is due and fire it. A failure leaves its lease to lapse (a retry in a minute)."""
    owner = owner or owner_id()
    now = now or datetime.utcnow()
    results = []
    for due in await claim(owner, now):
        try:
            results.append(await fire(due, owner, now))
        except Exception:
            logger.exception("scheduler: %s %s of company %s failed", due.ref_kind, due.ref_id, due.company_id)
            results.append({"ref": f"{due.ref_kind}:{due.ref_id}", "error": True})
    return results


# ── The process ────────────────────────────────────────────────────────────

async def run_forever(stop: asyncio.Event) -> None:
    from src.common.config import settings

    from src.automation import metrics

    owner = owner_id()
    logger.info("scheduler %s: tick every %ss", owner, settings.SCHEDULER_TICK_SECONDS)
    while not stop.is_set():
        try:
            fired = [r for r in await tick(owner) if r.get("fired")]
            if fired:
                logger.info("scheduler: fired %s", fired)
            metrics.SCHEDULER_TICKS.labels("ok").inc()
        except Exception:  # the database or Redis away: try again next tick
            metrics.SCHEDULER_TICKS.labels("error").inc()
            logger.exception("scheduler tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.SCHEDULER_TICK_SECONDS)
        except asyncio.TimeoutError:
            pass


async def _main() -> None:
    from src.common.orm_models import import_all_models
    from src.common.telemetry import setup_tracing, shutdown_tracing

    import_all_models()  # every mapper, as the API and workers have (a trigger refers to its agent)
    setup_tracing("hirebuddha-scheduler")
    from src.common.config import settings
    from src.common.worker_metrics import serve_metrics

    serve_metrics(settings.SCHEDULER_METRICS_PORT, settings.WORKER_METRICS_ADDR)  # also its liveness probe
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, name, None)
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError, TypeError):  # Windows: Ctrl+C raises instead
            pass
    try:
        await run_forever(stop)
    finally:
        shutdown_tracing()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
