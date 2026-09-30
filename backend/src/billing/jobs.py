"""
Billing crons for the Arq worker (BC-04).

Registered in ``ai/worker.py``: the daily credit renewal at 00:00 UTC and the
subscription reconciliation at 01:30 UTC. Each opens its own session and runs
the same ``CronService`` method as the matching ``/api/v1/cron/*`` endpoint.
"""
import logging
from typing import Any

from src.billing.cron_service import CronService
from src.common.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def billing_daily_credits(ctx: dict[str, Any]) -> dict[str, Any]:
    """Renew expired daily credits; reap abandoned checkouts."""
    async with AsyncSessionLocal() as db:
        return await CronService(db).run_daily_credit_job()


async def billing_subscription_reconciliation(ctx: dict[str, Any]) -> dict[str, Any]:
    """Grant paid cycles the Razorpay webhook missed; copy subscription status."""
    async with AsyncSessionLocal() as db:
        return await CronService(db).run_subscription_reconciliation()
