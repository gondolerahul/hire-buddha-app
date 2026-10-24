"""The partner programme's jobs (registered in ``ai/worker.py``).

* ``partners_daily`` (02:10 UTC): the annual-fee lifecycle (renewal due,
  lapsed, suspended, reminders), holdback release, lead expiry, and the
  commission sweep (payments of the last week whose commissions were not
  written — the payment hooks are best-effort).
* ``partners_monthly`` (daily at 03:10; acts on ``partners.statement_day``):
  last month's margin guard, then its statements.
"""
from __future__ import annotations

from typing import Any, Dict


async def partners_daily(ctx: Dict[str, Any]) -> Dict[str, Any]:
    from src.common.tenancy.session import control_session
    from src.partners import commission, fees, leads, statements

    out: Dict[str, Any] = {}
    async with control_session() as db:
        out["fees"] = await fees.lifecycle(db)
        out["released"] = await statements.release(db)
        out["leads_expired"] = await leads.expire(db)
        await db.commit()
        out["sweep"] = await commission.sweep(db)
    return out


async def partners_monthly(ctx: Dict[str, Any]) -> Dict[str, Any]:
    from src.common.tenancy.session import control_session
    from src.partners.statements import run_month

    async with control_session() as db:
        return await run_month(db)
