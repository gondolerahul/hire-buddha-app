"""Every paid-for bucket is spendable, soonest-expiring first (BC-02, BC-27).

Before BC-02 the deduction was ``if account_model == "pay_as_you_go": wallet
elif account_model == "subscription": subscription credits`` — a subscriber's
top-up balance still counted in ``total_available`` and could never be spent,
and ``consume`` passed its balance check and then deducted less than asked.
BC-27: the wallet was read, modified and written back with no lock, so two
concurrent deductions could each overwrite the other's.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from src.billing.billing_models import CreditWallet
from src.billing.credit_service import CreditService, InsufficientCreditsError

pytestmark = pytest.mark.needs_db


async def _wallet(db, *, model="pay_as_you_go", daily="0", sub="0", bonus="0", bal="0"):
    from src.auth.models import Company
    c = Company(name=f"credits-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    later = datetime.utcnow() + timedelta(days=10)
    db.add(CreditWallet(
        company_id=c.id, account_model=model,
        daily_credits=Decimal(daily), daily_expires_at=later,
        subscription_credits=Decimal(sub), subscription_bonus_credits=Decimal(bonus),
        sub_credits_expire_at=later, wallet_balance=Decimal(bal), wallet_expires_at=later,
    ))
    await db.flush()
    return c.id


async def _buckets(db, company_id) -> tuple:
    w = (await db.execute(select(CreditWallet).where(CreditWallet.company_id == company_id)
                          .execution_options(populate_existing=True))).scalar_one()
    return tuple(Decimal(str(v)).normalize() for v in (
        w.daily_credits, w.subscription_credits, w.subscription_bonus_credits, w.wallet_balance))


@pytest.mark.asyncio
async def test_a_subscriber_can_spend_their_top_up_balance(db):
    company = await _wallet(db, model="subscription", sub="5", bal="20")
    result = await CreditService(db).consume(company, Decimal("15"))
    assert result["subscription"] == Decimal("5")
    assert result["wallet"] == Decimal("10")
    assert await _buckets(db, company) == (0, 0, 0, 10)


@pytest.mark.asyncio
async def test_buckets_are_spent_soonest_expiring_first(db):
    company = await _wallet(db, model="subscription", daily="1", sub="2", bonus="3", bal="4")
    svc = CreditService(db)
    await svc.consume(company, Decimal("2"))       # daily 1, subscription 1
    assert await _buckets(db, company) == (0, 1, 3, 4)
    await svc.consume(company, Decimal("3"))       # subscription 1, bonus 2
    assert await _buckets(db, company) == (0, 0, 1, 4)
    await svc.consume(company, Decimal("2"))       # bonus 1, wallet 1
    assert await _buckets(db, company) == (0, 0, 0, 3)


@pytest.mark.asyncio
async def test_pay_as_you_go_spends_subscription_credits_left_after_cancelling(db):
    company = await _wallet(db, model="pay_as_you_go", sub="7", bal="1")
    await CreditService(db).consume(company, Decimal("8"))
    assert await _buckets(db, company) == (0, 0, 0, 0)


@pytest.mark.asyncio
async def test_consume_deducts_all_or_nothing(db):
    company = await _wallet(db, model="subscription", sub="1", bal="1")
    with pytest.raises(InsufficientCreditsError):
        await CreditService(db).consume(company, Decimal("3"))
    assert await _buckets(db, company) == (0, 1, 0, 1)


@pytest.mark.asyncio
async def test_incremental_drains_every_bucket_and_reports_the_shortfall(db):
    company = await _wallet(db, model="subscription", daily="1", sub="1", bonus="1", bal="1")
    result = await CreditService(db).consume_incremental(company, Decimal("6"))
    assert result["shortfall"] == Decimal("2")
    assert result["exhausted"] is True
    assert result["wallet"] == Decimal("1")
    assert await _buckets(db, company) == (0, 0, 0, 0)


@pytest.mark.asyncio
async def test_balance_counts_only_unexpired_buckets(db):
    company = await _wallet(db, model="subscription", sub="5", bal="20")
    await db.execute(text("UPDATE credit_wallets SET wallet_expires_at = now() - interval '1 day' "
                          "WHERE company_id = :c"), {"c": company})
    balance = await CreditService(db).get_balance(company)
    assert balance["wallet_balance"] == 0
    assert balance["total_available"] == 5


@pytest.mark.asyncio
async def test_concurrent_deductions_are_not_lost(_engine):
    """Two sessions deduct at once; both deductions must land (BC-27).

    Runs outside the rolled-back fixture — the two sessions need committed rows
    they can both see — and deletes what it created.
    """
    from sqlalchemy.ext.asyncio import AsyncSession
    from src.auth.models import Company

    company_id = uuid.uuid4()
    async with AsyncSession(_engine) as setup:
        setup.add(Company(id=company_id, name=f"credits-race-{company_id.hex[:6]}",
                          type="TENANT", status="active"))
        await setup.flush()
        setup.add(CreditWallet(company_id=company_id, wallet_balance=Decimal("100"),
                               wallet_expires_at=datetime.utcnow() + timedelta(days=10),
                               daily_credits=Decimal("0"),
                               daily_expires_at=datetime.utcnow() + timedelta(days=1)))
        await setup.commit()
    try:
        async def spend():
            async with AsyncSession(_engine) as s:
                for _ in range(5):
                    await CreditService(s).consume_incremental(company_id, Decimal("1"))

        await asyncio.gather(spend(), spend(), spend())
        async with AsyncSession(_engine) as check:
            wallet = (await check.execute(select(CreditWallet).where(
                CreditWallet.company_id == company_id))).scalar_one()
            assert Decimal(str(wallet.wallet_balance)) == Decimal("85")
    finally:
        async with AsyncSession(_engine) as cleanup:
            await cleanup.execute(text("DELETE FROM credit_wallets WHERE company_id = :c"), {"c": company_id})
            await cleanup.execute(text("DELETE FROM companies WHERE id = :c"), {"c": company_id})
            await cleanup.commit()
