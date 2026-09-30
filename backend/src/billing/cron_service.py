"""
Cron Service — scheduled jobs for daily credit refresh and subscription reconciliation.

Daily job (00:00:00): Flush expired daily credits, inject fresh $5 for every company.
Subscription reconciliation: grant cycles Razorpay reports paid that the webhook
missed, and copy Razorpay's subscription status.

These can be triggered by:
  1. An external cron scheduler (systemd timer, crontab)
  2. Internal admin API endpoints (see cron_router.py)
  3. APScheduler (can be added to main.py startup)
"""
import logging
from datetime import datetime, timedelta, date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.auth.models import Company
from src.billing.billing_models import Subscription
from src.billing.credit_service import CreditService
from src.billing.payment_service import (
    LIVE_SUBSCRIPTION_STATUSES, RAZORPAY_SUBSCRIPTION_STATUS, PaymentService, razorpay_time,
)
from src.billing.razorpay_gateway import get_razorpay_creds, razorpay_client

logger = logging.getLogger(__name__)


class CronService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_all_companies(self) -> list:
        """Return all active companies."""
        result = await self.db.execute(
            select(Company).where(Company.status == "active")
        )
        return result.scalars().all()

    async def run_daily_credit_job(self) -> dict:
        """
        Daily cron — flush old daily credits and inject fresh $5 for all companies.
        Called at 00:00:00 every day.
        """
        logger.info("Starting daily credit flush and injection job")
        companies = await self._get_all_companies()
        credit_svc = CreditService(self.db)
        processed = 0
        errors = 0

        for company in companies:
            try:
                await credit_svc.flush_and_inject_daily_credits(company.id)
                processed += 1
            except Exception as e:
                logger.error(f"Daily credit job failed for company {company.id}: {e}")
                errors += 1

        logger.info(f"Daily credit job complete. Processed: {processed}, Errors: {errors}")
        return {"processed": processed, "errors": errors, "timestamp": datetime.utcnow().isoformat()}

    async def run_subscription_reconciliation(self) -> dict:
        """Bring each subscription in line with Razorpay (BC-04).

        Renewal is Razorpay's: it charges each cycle and sends
        ``subscription.charged``, which grants the cycle's credits. This job
        catches what the webhook missed — for every invoice Razorpay reports
        ``paid`` whose payment is not recorded, the cycle is granted — and
        copies Razorpay's status (``past_due`` when a charge failed,
        ``cancelled`` when it ended). It grants nothing without a paid invoice;
        before BC-04 the monthly job recorded a "success" payment and granted
        a month of credits whether or not anyone had paid.

        Subscriptions paid with a one-time order before BC-16 have no Razorpay
        subscription and nothing can renew them: they end when the month they
        paid for ends.
        """
        logger.info("Starting subscription reconciliation")
        client = razorpay_client(await get_razorpay_creds(self.db))
        payments = PaymentService(self.db)
        counts = {"checked": 0, "credited": 0, "status_changed": 0,
                  "legacy_ended": 0, "skipped": 0, "errors": 0}
        now = datetime.utcnow()

        result = await self.db.execute(select(Subscription).where(
            Subscription.status.in_(("pending_payment",) + LIVE_SUBSCRIPTION_STATUSES)))
        for sub in result.scalars().all():
            try:
                if not sub.razorpay_subscription_id:
                    paid_until = sub.next_billing_date or sub.created_at + timedelta(days=31)
                    if sub.status in LIVE_SUBSCRIPTION_STATUSES and paid_until < now:
                        await payments.set_subscription_status(sub, "cancelled")
                        counts["legacy_ended"] += 1
                    continue
                if client is None:
                    counts["skipped"] += 1
                    continue
                counts["checked"] += 1
                invoices = client.invoice.all({"subscription_id": sub.razorpay_subscription_id})
                paid = [i for i in (invoices or {}).get("items", [])
                        if i.get("status") == "paid" and i.get("payment_id")]
                for inv in sorted(paid, key=lambda i: i.get("billing_end") or 0):
                    if await payments.record_subscription_charge(
                        sub,
                        payment_id=inv["payment_id"],
                        amount=Decimal(str(inv.get("amount_paid") or inv.get("amount") or 0)) / 100,
                        cycle_end=razorpay_time(inv.get("billing_end")),
                    ):
                        counts["credited"] += 1
                rz_status = client.subscription.fetch(sub.razorpay_subscription_id).get("status")
                status = RAZORPAY_SUBSCRIPTION_STATUS.get(rz_status or "")
                if status and status != sub.status:
                    await payments.set_subscription_status(sub, status)
                    counts["status_changed"] += 1
            except Exception as e:
                logger.error(f"Subscription reconciliation failed for {sub.id}: {e}")
                await self.db.rollback()
                counts["errors"] += 1

        logger.info(f"Subscription reconciliation complete: {counts}")
        return {**counts, "timestamp": datetime.utcnow().isoformat()}

    # The /cron/monthly-billing endpoint's name for it.
    run_monthly_subscription_job = run_subscription_reconciliation
