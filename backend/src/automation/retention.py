"""Event history kept (functional spec §3.5; decision D47): the
``event_retention_days`` limit — none by default, so nothing is deleted.

When a business (or the platform's default) sets it, a daily job deletes the
business's handled (``routed``) events older than that, with the decisions
recorded for them; events still waiting, held or failed stay until someone
deals with them. Runs keep their ``event_id`` (a plain reference) and their
own history.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, delete, select

from src.automation.limits import limits_for
from src.automation.models import Event, Trigger, TriggerFiring

logger = logging.getLogger(__name__)

BATCH = 5000


async def prune(db: Any, company_id: Any, days: int, *, now: Optional[datetime] = None,
                batch: int = BATCH) -> int:
    """Delete one batch of the business's handled events older than ``days``; returns how many."""
    cutoff = (now or datetime.utcnow()) - timedelta(days=days)
    ids = (await db.execute(select(Event.id).where(
        Event.company_id == company_id, Event.status == "routed", Event.received_at < cutoff)
        .order_by(Event.received_at).limit(batch))).scalars().all()
    if ids:
        await db.execute(delete(TriggerFiring).where(TriggerFiring.event_id.in_(ids)))
        await db.execute(delete(Event).where(Event.id.in_(ids)))
    # Decisions with no event (missed schedule times) age out the same way.
    trigger_ids = select(Trigger.id).where(Trigger.company_id == company_id).scalar_subquery()
    await db.execute(delete(TriggerFiring).where(and_(
        TriggerFiring.event_id.is_(None), TriggerFiring.trigger_id.in_(trigger_ids),
        TriggerFiring.decided_at < cutoff)))
    await db.commit()
    return len(ids)


async def _companies_with_events(db: Any) -> List[Any]:
    return list((await db.execute(select(Event.company_id).distinct())).scalars())


async def prune_event_history(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """arq cron (daily): every business that set how long its events are kept."""
    from src.common.tenancy.session import is_split, tenant_scopes, tenant_session

    deleted: Dict[str, int] = {}
    for scope in await tenant_scopes():
        try:
            async with tenant_session(scope) as db:
                for company_id in await _companies_with_events(db):
                    days = (await limits_for(company_id, None if is_split() else db)).event_retention_days
                    if days is None:
                        continue
                    total = 0
                    while True:
                        removed = await prune(db, company_id, days)
                        total += removed
                        if removed < BATCH:
                            break
                    if total:
                        deleted[str(company_id)] = total
        except Exception:  # one tenant database away must not stop the others
            logger.exception("event history clean-up of tenant %s failed", scope)
    if deleted:
        logger.info("event history clean-up: %s", deleted)
    return {"deleted": deleted}
