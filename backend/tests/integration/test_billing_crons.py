"""The billing crons run on a schedule, and the wallet tick is safe to re-run (BC-04, BC-18, Phase 15 M15.2).

Before: nothing scheduled either billing job — they were admin endpoints only —
and the daily job assigned every wallet a full day's credits, so running it
again mid-day handed back whatever had been spent. Abandoned checkouts stayed
``pending`` / ``pending_payment`` forever. Since M15.2 the daily job is the
wallet tick (every 15 minutes): lot expiry, daily credits once per local date,
enforcement.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from src.billing.billing_models import (
    CreditWallet, DailyCreditBand, DailyCreditPolicy, PaymentTransaction, Subscription, WalletEntry, WalletLot,
)
from src.billing.cron_service import CronService
from src.billing.wallet import WalletService
from tests.harness.wallet import available, fund

pytestmark = pytest.mark.needs_db


async def _company(db):
    from src.auth.models import Company
    c = Company(name=f"cron-{uuid.uuid4().hex[:6]}", type="TENANT", status="active", billing_currency="USD")
    db.add(c)
    await db.flush()
    return c.id


async def _direct_policy(db, amount="1.25"):
    policy = DailyCreditPolicy(name=f"cron direct {uuid.uuid4().hex[:4]}", audience="direct", duration_days=None,
                               effective_from=datetime.utcnow() - timedelta(days=1))
    db.add(policy)
    await db.flush()
    db.add(DailyCreditBand(policy_id=policy.id, from_day=1, to_day=100000, amount_usd=Decimal(amount)))
    await db.flush()
    return policy


def test_the_worker_schedules_the_billing_crons():
    from src.ai.worker import WorkerSettings
    names = {c.name for c in WorkerSettings.cron_jobs}
    for job in ("billing_wallet_tick", "billing_settle_standalone", "billing_wallet_check",
                "billing_subscription_reconciliation"):
        assert any(job in n for n in names), (job, names)


@pytest.mark.asyncio
async def test_rerunning_the_tick_does_not_refill_spent_daily_credits(db):
    await _direct_policy(db, "1.25")
    company = await _company(db)
    await CronService(db).run_daily_credit_job()
    assert await available(db, company) == Decimal("1.25")
    await WalletService(db).deduct(company, Decimal("1"), source_type="test")
    await CronService(db).run_daily_credit_job()
    assert await available(db, company) == Decimal("0.25")
    lots = (await db.execute(select(WalletLot).where(WalletLot.company_id == company,
                                                     WalletLot.kind == "daily"))).scalars().all()
    assert len(lots) == 1


@pytest.mark.asyncio
async def test_the_tick_expires_lots_past_their_expiry(db):
    company = await _company(db)
    await fund(db, company, "3", expires_in=timedelta(minutes=5))
    lot = (await db.execute(select(WalletLot).where(WalletLot.company_id == company))).scalar_one()
    lot.expires_at = datetime.utcnow() - timedelta(minutes=1)
    await db.flush()
    await CronService(db).run_daily_credit_job()
    await db.refresh(lot)
    assert lot.remaining == 0
    [entry] = (await db.execute(select(WalletEntry).where(WalletEntry.lot_id == lot.id,
                                                          WalletEntry.kind == "expire"))).scalars().all()
    assert entry.amount == Decimal("-3")
    assert await WalletService(db).check(company) == []


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
    assert credited and await available(db, company) == Decimal("5")


@pytest_asyncio.fixture
async def savepoint_db(_engine):
    """A session whose commit and rollback act on a SAVEPOINT, so the job's own
    rollback undoes only its current company, as it does in production."""
    from sqlalchemy.ext.asyncio import AsyncSession
    async with _engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


@pytest.mark.asyncio
async def test_one_company_failing_does_not_stop_the_tick(savepoint_db, monkeypatch):
    """BC-31: the error handler's rollback expired every loaded company, so the
    next ``company.id`` raised MissingGreenlet and the whole job failed."""
    import src.billing.daily_credits as daily
    db = savepoint_db
    await _direct_policy(db, "0.10")
    ours = await _company(db)
    other = await _company(db)
    await db.commit()

    grant = daily.grant_today
    failed: list = []

    async def grant_or_fail(session, company_id, **kwargs):
        if company_id == other:
            failed.append(company_id)
            raise RuntimeError("wallet unavailable")
        return await grant(session, company_id, **kwargs)

    monkeypatch.setattr(daily, "grant_today", grant_or_fail)
    result = await CronService(db).run_daily_credit_job()

    assert failed and result["daily_credits"]["errors"] == 1 and result["processed"] >= 2
    assert await available(db, ours) == Decimal("0.10")
    assert (await db.execute(select(CreditWallet).where(CreditWallet.company_id == other))).first() is None
