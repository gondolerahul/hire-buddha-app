"""The event store (tech spec §7.3, §7.6; TD-03): the tenant's ``events`` table
is the outbox.

An event is written once — a second one with the same ``dedupe_key`` for the
same business is acknowledged and dropped — in the caller's transaction, so a
webhook is answered only once its event is stored and a data change commits
its event with its row. After the commit a **nudge** (an arq job on queue
``events``) asks the router to look at it; a nudge that is lost is covered by
the relay sweep, which re-nudges anything still ``received`` after half a
minute.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.automation.events import Envelope
from src.automation.models import Event
from src.common.job_queue import EVENT_QUEUE

logger = logging.getLogger(__name__)

RELAY_AFTER = timedelta(seconds=30)


async def record(db: Any, company_id: Any, envelope: Envelope) -> Tuple[Event, bool]:
    """Store the business's event unless its ``dedupe_key`` is already stored; ``(row, created)``.

    Does not commit: the caller's transaction decides (outbox).
    """
    values = {
        "id": envelope.id, "company_id": company_id, "type": envelope.type, "source": envelope.source,
        "subject": envelope.subject, "time": envelope.time, "dedupe_key": envelope.dedupe_key,
        "trust": envelope.trust, "causation_id": envelope.causation_id, "correlation_id": envelope.correlation_id,
        "chain_depth": envelope.chain_depth, "data": envelope.data or {}, "data_ref": envelope.data_ref,
        "status": "received", "received_at": datetime.utcnow(),
    }
    inserted = (await db.execute(
        insert(Event).values(**values)
        .on_conflict_do_nothing(index_elements=["company_id", "dedupe_key"]).returning(Event.id)
    )).scalar()
    if inserted is not None:
        return await db.get(Event, inserted), True
    existing = (await db.execute(select(Event).where(
        Event.company_id == company_id, Event.dedupe_key == envelope.dedupe_key))).scalar_one()
    return existing, False


async def nudge(company_id: Any, event_id: Any, *, attempt: str = "") -> None:
    """Ask the router to route the event (best effort: the relay sweep covers a lost nudge).

    One job per event (arq drops a second job with the same id while the first
    is queued, running or its result is kept); a replay names a new ``attempt``.
    """
    from src.common.job_queue import enqueue_job, tenant_arg

    job_id = f"route:{event_id}" + (f":{attempt}" if attempt else "")
    try:
        await enqueue_job("route_event", str(event_id), company_id=tenant_arg(company_id),
                          _queue_name=EVENT_QUEUE, _job_id=job_id)
    except Exception as error:  # Redis down: the sweep will find it
        logger.warning("nudge for event %s not queued (%s); the relay sweep will", event_id, error)


async def emit(db: Any, company_id: Any, envelope: Envelope) -> Tuple[Event, bool]:
    """Store, commit and nudge — for callers that own no wider transaction."""
    row, created = await record(db, company_id, envelope)
    await db.commit()
    if created:
        await nudge(company_id, row.id)
    return row, created


async def stale_received(db: Any, now: Optional[datetime] = None, limit: int = 500) -> List[Tuple[UUID, UUID]]:
    """``(event, company)`` still ``received`` after the relay delay: their nudge was lost."""
    cutoff = (now or datetime.utcnow()) - RELAY_AFTER
    return [tuple(row) for row in (await db.execute(
        select(Event.id, Event.company_id).where(Event.status == "received", Event.received_at < cutoff)
        .order_by(Event.received_at).limit(limit)
    )).all()]


async def parked(db: Any, company_id: Any, limit: int = 1000) -> List[UUID]:
    """The business's events held while automation was paused, oldest first."""
    return list((await db.execute(
        select(Event.id).where(Event.company_id == company_id, Event.status == "parked")
        .order_by(Event.received_at, Event.id).limit(limit)
    )).scalars().all())


async def companies_with_parked(db: Any) -> List[UUID]:
    return list((await db.execute(select(Event.company_id).where(Event.status == "parked").distinct())).scalars())
