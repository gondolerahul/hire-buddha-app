"""The event worker's jobs (tech spec §7.6, §7.8): queue ``events``.

``src.ai.worker.EventWorkerSettings`` runs them
(``python -m arq src.ai.worker.EventWorkerSettings``), so a burst of events
never takes the slots runs need, nor runs the slots events need:

* ``route_event`` — one event (``router.route_event``), nudged after it is stored;
* ``release_parked`` — after a resume: the business's held events, oldest
  first, then its queued firings;
* ``automation_sweep`` — every 30 seconds, per tenant database: re-nudge
  events whose nudge was lost (the relay of the outbox), release parked
  events of businesses running again, start queued firings that have room,
  record ``run.*`` events for runs that ended (``run_events``), and re-send
  the resume of a waiting run whose wait was answered (``waits``).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import select

from src.automation import guards, router, run_events, store, waits
from src.automation.limits import forget_state
from src.automation.models import Trigger, TriggerFiring
from src.automation.router import route_event  # noqa: F401 — registered by EventWorkerSettings

logger = logging.getLogger(__name__)


async def _companies_with_queued(db: Any) -> list:
    return list((await db.execute(
        select(Trigger.company_id).join(TriggerFiring, TriggerFiring.trigger_id == Trigger.id)
        .where(TriggerFiring.outcome == guards.QUEUED, TriggerFiring.run_id.is_(None)).distinct()
    )).scalars())


async def release_parked(ctx: Dict[str, Any], company_id: Optional[str] = None) -> Dict[str, Any]:
    """arq job: a business resumed — route what it held, then what was queued."""
    from src.common.tenancy.session import tenant_session

    company = UUID(str(company_id)) if company_id else None
    forget_state(company)  # this process's cached state, so the resume takes hold at once
    if company is None:
        return await automation_sweep(ctx)
    async with tenant_session(company) as db:
        released = await router.release_parked(db, company)
        started = await router.drain_queued(db, company)
    return {"company": str(company), "released": released, "started": started}


async def automation_sweep(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """arq cron: the relay sweep, parked events of running businesses, queued firings."""
    from src.common.tenancy.session import tenant_scopes, tenant_session

    totals = {"renudged": 0, "released": 0, "started": 0, "run_events": 0, "resumes_resent": 0}
    for scope in await tenant_scopes():
        try:
            async with tenant_session(scope) as db:
                for event_id, company_id in await store.stale_received(db):
                    await store.nudge(company_id, event_id)
                    totals["renudged"] += 1
                companies = set(await store.companies_with_parked(db)) | set(await _companies_with_queued(db))
                for company_id in companies:
                    totals["released"] += await router.release_parked(db, company_id)
                    totals["started"] += await router.drain_queued(db, company_id)
                totals["run_events"] += await run_events.relay_all(db)
                totals["resumes_resent"] += await waits.sweep_lost_resumes(db)
        except Exception:  # one tenant database away must not stop the others
            logger.exception("automation sweep of tenant %s failed", scope)
    if any(totals.values()):
        logger.info("automation sweep: %s", totals)
    try:
        from src.automation import metrics

        totals["sampled"] = await metrics.sample([lambda scope=scope: tenant_session(scope)
                                                  for scope in await tenant_scopes()])
    except Exception:  # noqa: BLE001 - metrics never stop the sweep
        logger.warning("automation metrics not sampled", exc_info=True)
    return totals
