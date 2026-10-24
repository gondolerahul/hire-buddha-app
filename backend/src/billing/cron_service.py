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
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.billing.billing_models import PaymentTransaction, Subscription
from src.billing.payment_service import (
    LIVE_SUBSCRIPTION_STATUSES, RAZORPAY_SUBSCRIPTION_STATUS, PaymentService, razorpay_time,
)
from src.billing.gateways import GatewayUnavailable, get_gateway

logger = logging.getLogger(__name__)

# A checkout nobody completed within ``checkout.abandoned_after_hours`` is
# abandoned (BC-18; a setting since Phase 15 T5-2, default 24).


class CronService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def run_daily_credit_job(self) -> dict:
        """
        The wallet tick (every 15 minutes, Phase 15 M15.2): lots past their
        expiry expire; each active company whose local date has no daily lot
        gets today's (``src.billing.daily_credits``); wallet states are
        enforced; then abandoned checkouts are reaped.

        Running it again grants nothing twice: a daily lot is granted once per
        company and local date (before BC-04 every run reset every wallet).
        """
        from src.billing.wallet_jobs import tick

        logger.info("Starting the wallet tick")
        result = await tick(self.db)
        daily = result["daily_credits"]
        reaped = await self.reap_abandoned_checkouts()
        logger.info(f"Wallet tick complete: {result}; reaped: {reaped}")
        return {"processed": daily["companies"], "granted": daily["granted"],
                "errors": daily["errors"] + result["expired"]["errors"] + result["enforcement"]["errors"],
                **result, **reaped, "timestamp": datetime.utcnow().isoformat()}

    async def reap_abandoned_checkouts(self) -> dict:
        """Close checkouts nobody completed within a day (BC-18).

        A top-up order still ``pending`` becomes ``expired``; a subscription
        still ``pending_payment`` becomes ``failed``, and its Razorpay
        subscription is cancelled so it cannot be authorised later. A payment
        that does arrive for an expired order is still credited — money that
        moved is never refused.
        """
        from src.billing.settings_catalogue import value
        cutoff = datetime.utcnow() - timedelta(hours=await value(self.db, "checkout.abandoned_after_hours"))
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
        gateway = await self._gateway() if subs else None
        for sub in subs:
            sub.status = "failed"
            sub.updated_at = datetime.utcnow()
            if gateway is not None and sub.razorpay_subscription_id:
                try:
                    await gateway.cancel_subscription(sub.razorpay_subscription_id, at_cycle_end=False)
                except Exception as e:
                    logger.warning(f"Could not cancel abandoned gateway subscription "
                                   f"{sub.razorpay_subscription_id}: {e}")
        await self.db.commit()
        return {"expired_orders": len(orders), "failed_subscriptions": len(subs)}

    async def _gateway(self):
        try:
            return await get_gateway(self.db)
        except GatewayUnavailable:
            return None

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

        Then every live subscription whose price changed — a new plan version,
        FX rate or tax rate — is moved to its new gateway plan at the cycle's
        end (Phase 15 T6-4), so its next renewal is at today's price.
        """
        logger.info("Starting subscription reconciliation")
        gateway = await self._gateway()
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
                if gateway is None:
                    counts["skipped"] += 1
                    continue
                counts["checked"] += 1
                from src.billing.currency import minor_units
                digits = Decimal(10) ** await minor_units(self.db, sub.currency or "USD")
                invoices = await gateway.subscription_invoices(sub.razorpay_subscription_id)
                paid = [i for i in invoices if i.get("status") == "paid" and i.get("payment_id")]
                for inv in sorted(paid, key=lambda i: i.get("billing_end") or 0):
                    if await payments.record_subscription_charge(
                        sub,
                        payment_id=inv["payment_id"],
                        amount=Decimal(str(inv.get("amount_paid") or inv.get("amount") or 0)) / digits,
                        cycle_end=razorpay_time(inv.get("billing_end")),
                    ):
                        counts["credited"] += 1
                rz_status = (await gateway.fetch_subscription(sub.razorpay_subscription_id)).get("status")
                status = RAZORPAY_SUBSCRIPTION_STATUS.get(rz_status or "")
                if status and status != sub.status:
                    await payments.set_subscription_status(sub, status)
                    counts["status_changed"] += 1
            except Exception as e:
                logger.error(f"Subscription reconciliation failed for {sub.id}: {e}")
                await self.db.rollback()
                counts["errors"] += 1

        if gateway is not None:
            from src.billing.subscriptions import reprice_for_renewal
            counts["repriced"] = (await reprice_for_renewal(self.db, gateway))["moved"]
        logger.info(f"Subscription reconciliation complete: {counts}")
        return {**counts, "timestamp": datetime.utcnow().isoformat()}

    # The /cron/monthly-billing endpoint's name for it.
    run_monthly_subscription_job = run_subscription_reconciliation
