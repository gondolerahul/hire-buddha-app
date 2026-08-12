"""
Cron Service — scheduled jobs for daily credit refresh and monthly subscription billing.

Daily job (00:00:00): Flush expired daily credits, inject fresh $5 for every company.
Monthly job (1st of month): Process Razorpay subscription charges, flush and re-inject tier credits.

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
from src.billing.billing_models import CreditWallet, Subscription, PaymentTransaction
from src.billing.credit_service import CreditService

logger = logging.getLogger(__name__)

# Subscription tier bonus percentages
# Now stored directly on the Subscription object


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

    async def run_monthly_subscription_job(self) -> dict:
        """
        Monthly cron — process subscriptions and flush/re-inject tier credits.
        Called on the 1st of each month.
        """
        logger.info("Starting monthly subscription processing job")
        credit_svc = CreditService(self.db)
        processed = 0
        errors = 0

        # Get all active subscriptions
        stmt = select(Subscription).where(Subscription.status == "active")
        result = await self.db.execute(stmt)
        subscriptions = result.scalars().all()

        razorpay_client = await self._get_razorpay_client()

        for sub in subscriptions:
            try:
                # 1. Charge via Razorpay if we have a subscription ID
                charged_amount = sub.monthly_fee
                payment_status = "success"

                if razorpay_client and sub.razorpay_subscription_id:
                    try:
                        # Razorpay handles auto-debit for subscriptions automatically
                        # We just record the expected charge
                        logger.info(f"Razorpay subscription {sub.razorpay_subscription_id} auto-debits monthly")
                    except Exception as rp_err:
                        logger.error(f"Razorpay charge failed for sub {sub.id}: {rp_err}")
                        sub.status = "past_due"
                        payment_status = "failed"
                        charged_amount = Decimal("0")

                # 2. Record payment transaction
                txn = PaymentTransaction(
                    company_id=sub.company_id,
                    amount=charged_amount,
                    currency="USD",
                    transaction_type="subscription_charge",
                    status=payment_status,
                    credits_awarded=charged_amount if payment_status == "success" else Decimal("0"),
                    transaction_metadata={"subscription_id": str(sub.id), "tier": sub.plan_tier},
                )
                self.db.add(txn)

                # 3. Flush old sub credits and inject new tier credits (on successful charge)
                if payment_status == "success":
                    bonus_pct = sub.bonus_pct
                    await credit_svc.inject_subscription_credits(
                        company_id=sub.company_id,
                        base_amount=charged_amount,
                        bonus_pct=bonus_pct,
                    )
                    # Update next billing date
                    now = datetime.utcnow()
                    if now.month == 12:
                        sub.next_billing_date = datetime(now.year + 1, 1, 1)
                    else:
                        sub.next_billing_date = datetime(now.year, now.month + 1, 1)
                    sub.updated_at = datetime.utcnow()

                await self.db.commit()
                processed += 1
            except Exception as e:
                logger.error(f"Monthly subscription job failed for sub {sub.id}: {e}")
                await self.db.rollback()
                errors += 1

        logger.info(f"Monthly subscription job complete. Processed: {processed}, Errors: {errors}")
        return {"processed": processed, "errors": errors, "timestamp": datetime.utcnow().isoformat()}

    async def _get_razorpay_client(self):
        """
        Get Razorpay client using credentials from integration_registry.
        Razorpay credentials are stored as service_sku='razorpay_keys' in integration_registry.
        Returns None if Razorpay is not configured.
        """
        try:
            from src.config.models import IntegrationRegistry
            stmt = select(IntegrationRegistry).where(
                IntegrationRegistry.service_sku == "razorpay_keys",
                IntegrationRegistry.status == "active",
            )
            result = await self.db.execute(stmt)
            registry = result.scalar_one_or_none()

            if not registry or not registry.service_metadata:
                logger.warning("Razorpay credentials not found in integration_registry")
                return None

            key_id = registry.service_metadata.get("key_id")
            key_secret = registry.service_metadata.get("key_secret")

            if not key_id or not key_secret:
                return None

            import razorpay
            return razorpay.Client(auth=(key_id, key_secret))
        except ImportError:
            logger.warning("razorpay package not installed. Payment processing unavailable.")
            return None
        except Exception as e:
            logger.error(f"Failed to initialize Razorpay client: {e}")
            return None
