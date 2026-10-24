"""
Billing crons for the Arq worker (BC-04, Phase 15 M15.2).

Registered in ``ai/worker.py``. Each opens its own session on the control
database (billing is control-plane, Phase 14 WS2):

* ``billing_wallet_tick`` — every 15 minutes: lot expiry, daily credits at each
  company's local midnight, wallet enforcement and notices
  (``src.billing.wallet_jobs.tick``); abandoned checkouts are reaped once an
  hour by the same tick.
* ``billing_settle_standalone`` — hourly: usage outside runs and anything left
  unsettled (T3-6).
* ``billing_wallet_check`` — nightly: every wallet against its ledger (W-9).
* ``billing_subscription_reconciliation`` — 01:30 UTC: paid cycles the
  Razorpay webhook missed.
"""
import logging
from typing import Any

from src.billing.cron_service import CronService
from src.common.tenancy.session import control_session

logger = logging.getLogger(__name__)


async def billing_wallet_tick(ctx: dict[str, Any]) -> dict[str, Any]:
    """Expire lots, grant daily credits, enforce wallet states; reap abandoned checkouts."""
    async with control_session() as db:
        return await CronService(db).run_daily_credit_job()


async def billing_settle_standalone(ctx: dict[str, Any]) -> dict[str, Any]:
    """Settle usage that no run or call settled (Phase 15 T3-6)."""
    from src.billing.wallet_jobs import settle_standalone

    async with control_session() as db:
        return await settle_standalone(db)


async def billing_wallet_check(ctx: dict[str, Any]) -> dict[str, Any]:
    """Each wallet equals its ledger (Phase 15 W-9)."""
    from src.billing.wallet_jobs import check_wallets

    async with control_session() as db:
        return await check_wallets(db)


async def billing_subscription_reconciliation(ctx: dict[str, Any]) -> dict[str, Any]:
    """Grant paid cycles the Razorpay webhook missed; copy subscription status."""
    async with control_session() as db:
        return await CronService(db).run_subscription_reconciliation()
