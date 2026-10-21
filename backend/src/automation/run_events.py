"""Run-finished events (functional spec §3.1 "Run finished"; tech spec
Appendix B ``run.*``): "when *Research* completes → run *Report writer*".

A top-level run that ends becomes one event — ``run.completed`` (also for a
partial completion; ``data.status`` says which), ``run.failed`` or
``run.cancelled`` — one step deeper in the run's own chain, so the loop limit
sees agents that start each other. Its ``dedupe_key`` is the run and its
outcome (``events.run_dedupe_key``), so it exists once however often it is
looked for.

Approvals the same way (plan WS3 3.8): ``approval.requested`` when a run
asks a person, ``approval.decided`` when it is answered (``data.status``:
APPROVED, REJECTED or TIMEOUT) — "when an approval waits, message the manager".

The kernel emits them itself (W3-1): a run's final persist and its
cancellation call ``emit_run_finished``, opening and answering an approval
call ``emit_approval`` — each best-effort (a failure is logged, never the
run's) and only for a business with a trigger listening for ``run.*`` /
``approval.*``. The event worker's sweep still relays them from
``execution_runs`` and ``human_approvals`` (the last hour, after the oldest
such trigger was made) for anything an emission missed — a worker that died
between the run's commit and its event; the same dedupe keys keep each one
single.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func, select

from src.automation import store
from src.automation.events import Envelope, run_dedupe_key
from src.automation.models import Event, Trigger

logger = logging.getLogger(__name__)

LOOKBACK = timedelta(hours=1)
BATCH = 500
MAX_OUTPUT_BYTES = 64 * 1024
OUTCOMES = {"COMPLETED": "completed", "PARTIAL_COMPLETE": "completed", "FAILED": "failed",
            "CANCELLED": "cancelled"}


def outcome_of(status: Any) -> Optional[str]:
    return OUTCOMES.get(str(getattr(status, "value", status) or "").upper())


async def listeners(db: Any, prefix: str = "run.") -> Dict[UUID, datetime]:
    """Businesses with an enabled trigger on ``<prefix>*``, and when the oldest was made."""
    rows = (await db.execute(
        select(Trigger.company_id, func.min(Trigger.created_at))
        .where(Trigger.enabled.is_(True), Trigger.kind.in_(("event", "data")),
               Trigger.event_type.like(f"{prefix}%"))
        .group_by(Trigger.company_id))).all()
    return {company_id: since for company_id, since in rows}


def _output(run: Any) -> Dict[str, Any]:
    result = run.result_data
    if result is None:
        return {}
    if len(json.dumps(result, default=str)) > MAX_OUTPUT_BYTES:
        return {"output_truncated": True}
    return {"output": result}


def envelope(run: Any, entity_name: Optional[str]) -> Envelope:
    outcome = outcome_of(run.status)
    status = str(getattr(run.status, "value", run.status))
    return Envelope(
        type=f"run.{outcome}", source="automation:runs", trust="internal", subject=f"run:{run.id}",
        dedupe_key=run_dedupe_key(run.id, outcome), time=run.completed_at or datetime.utcnow(),
        causation_id=run.event_id, correlation_id=run.correlation_id or run.event_id or run.id,
        chain_depth=(run.chain_depth or 0) + 1,
        data={"run_id": str(run.id), "entity_id": str(run.entity_id), "entity_name": entity_name, "status": status,
              "trigger_id": str(run.trigger_id) if run.trigger_id else None,
              "error": (run.error_message or None) and run.error_message[:2000], **_output(run)},
    )


async def relay(db: Any, company_id: Any, since: datetime, *, now: Optional[datetime] = None) -> List[UUID]:
    """Record the business's run events not recorded yet (no commit); returns the new event ids."""
    from src.ai.orm import ExecutionRun, HierarchicalEntity

    now = now or datetime.utcnow()
    floor = max(since, now - LOOKBACK)
    runs = (await db.execute(select(ExecutionRun).where(
        ExecutionRun.company_id == company_id, ExecutionRun.parent_run_id.is_(None),
        ExecutionRun.status.in_(tuple(OUTCOMES)), ExecutionRun.completed_at >= floor)
        .order_by(ExecutionRun.completed_at).limit(BATCH))).scalars().all()
    if not runs:
        return []
    keys = {run_dedupe_key(r.id, outcome_of(r.status)): r for r in runs}
    known = set((await db.execute(select(Event.dedupe_key).where(
        Event.company_id == company_id, Event.dedupe_key.in_(list(keys))))).scalars().all())
    missing = [r for key, r in keys.items() if key not in known]
    if not missing:
        return []
    names = dict((await db.execute(select(HierarchicalEntity.id, HierarchicalEntity.name).where(
        HierarchicalEntity.id.in_({r.entity_id for r in missing})))).all())
    created = []
    for run in missing:
        row, new = await store.record(db, company_id, envelope(run, names.get(run.entity_id)))
        if new:
            created.append(row.id)
    return created


def approval_envelopes(approval: Any, run: Any) -> List[Envelope]:
    """The events one approval has given so far: requested, and decided once answered."""
    base = {"approval_id": str(approval.id), "run_id": str(approval.run_id),
            "entity_id": str(run.entity_id) if run else None, "checkpoint": approval.checkpoint_trigger}
    chain = {"causation_id": run.event_id if run else None,
             "correlation_id": (run.correlation_id or run.event_id or run.id) if run else None,
             "chain_depth": ((run.chain_depth or 0) + 1) if run else 1}
    out = [Envelope(type="approval.requested", source="automation:approvals", trust="internal",
                    subject=f"run:{approval.run_id}", dedupe_key=f"approval:{approval.id}:requested",
                    time=approval.requested_at or datetime.utcnow(), data={**base, "status": "PENDING"}, **chain)]
    status = str(approval.status or "").upper()
    if status in ("APPROVED", "REJECTED", "TIMEOUT"):
        out.append(Envelope(type="approval.decided", source="automation:approvals", trust="internal",
                            subject=f"run:{approval.run_id}", dedupe_key=f"approval:{approval.id}:decided",
                            time=approval.responded_at or datetime.utcnow(),
                            data={**base, "status": status, "notes": approval.reviewer_notes}, **chain))
    return out


async def relay_approvals(db: Any, company_id: Any, since: datetime, *, now: Optional[datetime] = None) -> List[UUID]:
    """Record the business's approval events not recorded yet (no commit)."""
    from sqlalchemy import or_

    from src.ai.orm import ExecutionRun, HumanApproval

    now = now or datetime.utcnow()
    floor = max(since, now - LOOKBACK)
    approvals = (await db.execute(select(HumanApproval).where(
        HumanApproval.company_id == company_id,
        or_(HumanApproval.requested_at >= floor, HumanApproval.responded_at >= floor))
        .order_by(HumanApproval.requested_at).limit(BATCH))).scalars().all()
    if not approvals:
        return []
    runs = {r.id: r for r in (await db.execute(select(ExecutionRun).where(
        ExecutionRun.id.in_({a.run_id for a in approvals})))).scalars().all()}
    candidates = [e for a in approvals for e in approval_envelopes(a, runs.get(a.run_id)) if e.time >= floor]
    known = set((await db.execute(select(Event.dedupe_key).where(
        Event.company_id == company_id, Event.dedupe_key.in_([e.dedupe_key for e in candidates])))).scalars().all())
    created = []
    for envelope_ in candidates:
        if envelope_.dedupe_key in known:
            continue
        row, new = await store.record(db, company_id, envelope_)
        if new:
            created.append(row.id)
    return created


async def is_listening(db: Any, company_id: Any, prefix: str) -> bool:
    """Whether the business has an enabled trigger on ``<prefix>*``."""
    return (await db.execute(
        select(Trigger.id).where(Trigger.company_id == company_id, Trigger.enabled.is_(True),
                                 Trigger.kind.in_(("event", "data")), Trigger.event_type.like(f"{prefix}%"))
        .limit(1))).first() is not None


async def _emit(db: Any, company_id: Any, envelopes: List[Envelope]) -> List[UUID]:
    created = []
    for envelope_ in envelopes:
        row, new = await store.record(db, company_id, envelope_)
        if new:
            created.append(row.id)
    await db.commit()
    for event_id in created:
        await store.nudge(company_id, event_id)
    return created


async def emit_run_finished(db: Any, run: Any) -> List[UUID]:
    """The kernel's ``run.<outcome>`` for a top-level run that has just ended (commits it). Never raises."""
    try:
        if run is None or run.parent_run_id is not None or outcome_of(run.status) is None:
            return []
        if not await is_listening(db, run.company_id, "run."):
            return []
        from src.ai.orm import HierarchicalEntity

        name = (await db.execute(select(HierarchicalEntity.name).where(
            HierarchicalEntity.id == run.entity_id).execution_options(include_deleted=True))).scalar()
        return await _emit(db, run.company_id, [envelope(run, name)])
    except Exception:  # noqa: BLE001 - the sweep relays it
        logger.exception("run %s: run-finished event not emitted (the sweep will relay it)",
                         getattr(run, "id", None))
        return []


async def emit_approval(db: Any, approval: Any) -> List[UUID]:
    """The kernel's ``approval.requested`` / ``approval.decided`` for an approval just opened or
    answered (commits them; one already stored is not stored again). Never raises."""
    try:
        from src.ai.orm import ExecutionRun

        run = await db.get(ExecutionRun, approval.run_id)
        company_id = approval.company_id or (run.company_id if run is not None else None)
        if company_id is None or not await is_listening(db, company_id, "approval."):
            return []
        return await _emit(db, company_id, approval_envelopes(approval, run))
    except Exception:  # noqa: BLE001 - the sweep relays it
        logger.exception("approval %s: event not emitted (the sweep will relay it)", getattr(approval, "id", None))
        return []


async def relay_all(db: Any, *, now: Optional[datetime] = None) -> int:
    """One sweep over one tenant database: commit, then nudge the router."""
    total = 0
    for prefix, relay_one in (("run.", relay), ("approval.", relay_approvals)):
        for company_id, since in (await listeners(db, prefix)).items():
            created = await relay_one(db, company_id, since, now=now)
            await db.commit()
            for event_id in created:
                await store.nudge(company_id, event_id)
            total += len(created)
    return total
