"""The billing crons run on a schedule, and the daily one is safe to re-run (BC-04, BC-18).

Before: nothing scheduled either billing job — they were admin endpoints only —
and the daily job assigned every wallet a full day's credits, so running it
again mid-day handed back whatever had been spent. Abandoned checkouts stayed
``pending`` / ``pending_payment`` forever.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from src.billing.billing_models import CreditWallet, PaymentTransaction, Subscription
from src.billing.cron_service import CronService

pytestmark = pytest.mark.needs_db


async def _company(db):
    from src.auth.models import Company
    c = Company(name=f"cron-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    return c.id


async def _daily(db, company_id) -> Decimal:
    w = (await db.execute(select(CreditWallet).where(CreditWallet.company_id == company_id)
                          .execution_options(populate_existing=True))).scalar_one()
    return Decimal(str(w.daily_credits))


def test_the_worker_schedules_both_billing_crons():
    from src.ai.worker import WorkerSettings
    names = {c.name for c in WorkerSettings.cron_jobs}
    assert any("billing_daily_credits" in n for n in names), names
    assert any("billing_subscription_reconciliation" in n for n in names), names


@pytest.mark.asyncio
async def test_rerunning_the_daily_job_does_not_refill_spent_credits(db):
    company = await _company(db)
    db.add(CreditWallet(company_id=company, daily_credits=Decimal("1.25"),
                        daily_expires_at=datetime.utcnow() + timedelta(hours=6)))
    await db.flush()
    await CronService(db).run_daily_credit_job()
    await CronService(db).run_daily_credit_job()
    assert await _daily(db, company) == Decimal("1.25")


@pytest.mark.asyncio
async def test_the_daily_job_renews_expired_credits(db):
    company = await _company(db)
    db.add(CreditWallet(company_id=company, daily_credits=Decimal("0.10"),
                        daily_expires_at=datetime.utcnow() - timedelta(minutes=1)))
    await db.flush()
    configured = (await db.execute(text(
        "select default_daily_credits from billing_config where company_id is null and is_active"))).scalar()
    await CronService(db).run_daily_credit_job()
    assert await _daily(db, company) == Decimal(str(configured or 0))
    w = (await db.execute(select(CreditWallet).where(CreditWallet.company_id == company))).scalar_one()
    assert w.daily_expires_at > datetime.utcnow()


@pytest.mark.asyncio
async def test_abandoned_checkouts_are_closed_and_recent_ones_left(db):
    company = await _company(db)
    old = datetime.utcnow() - timedelta(hours=30)
    stale_order = PaymentTransaction(company_id=company, razorpay_order_id=f"order_{uuid.uuid4().hex[:10]}",
                                     amount=Decimal("5"), transaction_type="topup", status="pending",
                                     created_at=old)
    fresh_order = PaymentTransaction(company_id=company, razorpay_order_id=f"order_{uuid.uuid4().hex[:10]}",
                                     amount=Decimal("5"), transaction_type="topup", status="pending")
    stale_sub = Subscription(company_id=company, plan_tier=1, monthly_fee=Decimal("29"),
                             bonus_pct=Decimal("20"), status="pending_payment", created_at=old)
    db.add_all([stale_order, fresh_order, stale_sub])
    await db.flush()
    result = await CronService(db).reap_abandoned_checkouts()
    assert result["expired_orders"] >= 1 and result["failed_subscriptions"] >= 1
    await db.refresh(stale_order)
    await db.refresh(fresh_order)
    await db.refresh(stale_sub)
    assert (stale_order.status, fresh_order.status, stale_sub.status) == ("expired", "pending", "failed")


@pytest.mark.asyncio
async def test_a_payment_that_arrives_for_an_expired_order_is_still_credited(db):
    from src.billing.payment_service import PaymentService
    company = await _company(db)
    order_id = f"order_{uuid.uuid4().hex[:10]}"
    db.add(PaymentTransaction(company_id=company, razorpay_order_id=order_id, amount=Decimal("5"),
                              transaction_type="topup", status="pending",
                              created_at=datetime.utcnow() - timedelta(hours=30)))
    await db.flush()
    await CronService(db).reap_abandoned_checkouts()
    _, wallet, credited = await PaymentService(db).credit_topup(order_id=order_id, payment_id="pay_late")
    assert credited and Decimal(str(wallet.wallet_balance)) == Decimal("5")
