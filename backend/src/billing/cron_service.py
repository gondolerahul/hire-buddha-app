"""
Cron Service — scheduled jobs for daily credit refresh and subscription reconciliation.

Daily job (00:00 UTC): renew daily credits that have expired, and reap
abandoned checkouts. Safe to run again the same day — it changes nothing twice.
Subscription reconciliation (01:30 UTC): grant cycles Razorpay reports paid that
the webhook missed, and copy Razorpay's subscription status.

Both are scheduled by the Arq worker (``billing.jobs``, registered in
``ai/worker.py``) and can also be run from the admin endpoints in
``cron_router.py``.
"""
import logging
from datetime import datetime, timedelta, date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.auth.models import Company
from src.billing.billing_models import PaymentTransaction, Subscription
from src.billing.credit_service import CreditService
from src.billing.payment_service import (
    LIVE_SUBSCRIPTION_STATUSES, RAZORPAY_SUBSCRIPTION_STATUS, PaymentService, razorpay_time,
)
from src.billing.razorpay_gateway import get_razorpay_creds, razorpay_client

logger = logging.getLogger(__name__)

# A checkout nobody completed within this long is abandoned (BC-18).
ABANDONED_AFTER = timedelta(hours=24)


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
        Daily cron — renew every active company's daily credits that have
        expired, then reap abandoned checkouts. Called at 00:00 UTC.

        Credits that have not expired are left alone, so running the job
        again the same day grants nothing (before BC-04 it reset every
        wallet to a full day's credits on each run).
        """
        logger.info("Starting daily credit renewal job")
        companies = await self._get_all_companies()
        credit_svc = CreditService(self.db)
        processed = 0
        errors = 0

        for company in companies:
            try:
                await credit_svc.renew_expired_credits(company.id)
                processed += 1
            except Exception as e:
                logger.error(f"Daily credit job failed for company {company.id}: {e}")
                await self.db.rollback()
                errors += 1

        reaped = await self.reap_abandoned_checkouts()
        logger.info(f"Daily credit job complete. Processed: {processed}, Errors: {errors}, Reaped: {reaped}")
        return {"processed": processed, "errors": errors, **reaped,
                "timestamp": datetime.utcnow().isoformat()}

    async def reap_abandoned_checkouts(self) -> dict:
        """Close checkouts nobody completed within a day (BC-18).

        A top-up order still ``pending`` becomes ``expired``; a subscription
        still ``pending_payment`` becomes ``failed``, and its Razorpay
        subscription is cancelled so it cannot be authorised later. A payment
        that does arrive for an expired order is still credited — money that
        moved is never refused.
        """
        cutoff = datetime.utcnow() - ABANDONED_AFTER
        orders = (await self.db.execute(select(PaymentTransaction).where(
            PaymentTransaction.transaction_type == "topup",
            PaymentTransaction.status == "pending",
            PaymentTransaction.created_at < cutoff,
        ))).scalars().all()
        for txn in orders:
            txn.status = "expired"
            txn.updated_at = datetime.utcnow()

        subs = (await self.db.execute(select(Subscription).where(
            Subscription.status == "pending_payment",
            Subscription.created_at < cutoff,
        ))).scalars().all()
        client = razorpay_client(await get_razorpay_creds(self.db)) if subs else None
        for sub in subs:
            sub.status = "failed"
            sub.updated_at = datetime.utcnow()
            if client is not None and sub.razorpay_subscription_id:
                try:
                    client.subscription.cancel(sub.razorpay_subscription_id, {"cancel_at_cycle_end": 0})
                except Exception as e:
                    logger.warning(f"Could not cancel abandoned Razorpay subscription "
                                   f"{sub.razorpay_subscription_id}: {e}")
        await self.db.commit()
        return {"expired_orders": len(orders), "failed_subscriptions": len(subs)}

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
