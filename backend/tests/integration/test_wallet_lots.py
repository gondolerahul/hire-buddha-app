"""The lot wallet: spend order, debt, repayment, state, expiry, the ledger (Phase 15 T4-1; tech design §6).

Replaces the bucket tests (BC-02, BC-27): credit is lots with their own expiry,
spent daily → subscription → bonus → top-ups and grants by earliest expiry,
then debt; paid credit repays debt first; every change is an entry, and the
wallet always equals its ledger. Real Postgres, rolled back.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from src.billing.billing_models import CreditWallet, WalletEntry, WalletLot
from src.billing.credit_service import CreditService, InsufficientCreditsError, WalletBlocked
from src.billing.wallet import WalletService
from tests.harness.wallet import available, fund

pytestmark = pytest.mark.needs_db


async def _company(db, currency="USD"):
    from src.auth.models import Company
    c = Company(name=f"lots-{uuid.uuid4().hex[:6]}", type="TENANT", status="active", billing_currency=currency)
    db.add(c)
    await db.flush()
    return c.id


async def _lot(db, company_id, kind, amount, days=10):
    return await WalletService(db).grant(company_id, kind, Decimal(amount),
                                         expires_at=datetime.utcnow() + timedelta(days=days),
                                         paid=kind in ("topup", "subscription"), source_type="test")


async def _remaining(db, company_id) -> dict:
    lots = (await db.execute(select(WalletLot).where(WalletLot.company_id == company_id)
                             .execution_options(populate_existing=True))).scalars().all()
    out: dict = {}
    for lot in lots:
        out[lot.kind] = out.get(lot.kind, Decimal(0)) + Decimal(str(lot.remaining))
    return {k: v.normalize() for k, v in out.items()}


@pytest.mark.asyncio
async def test_lots_are_spent_in_order_then_debt(db):
    company = await _company(db)
    await _lot(db, company, "topup", "4", days=80)
    await _lot(db, company, "subscription_bonus", "3")
    await _lot(db, company, "subscription", "2")
    await _lot(db, company, "daily", "1", days=1)
    wallets = WalletService(db)
    await wallets.deduct(company, Decimal("2"), source_type="test")           # daily 1, subscription 1
    assert await _remaining(db, company) == {"daily": 0, "subscription": 1, "subscription_bonus": 3, "topup": 4}
    await wallets.deduct(company, Decimal("4"), source_type="test")           # subscription 1, bonus 3
    assert await _remaining(db, company) == {"daily": 0, "subscription": 0, "subscription_bonus": 0, "topup": 4}
    change = await wallets.deduct(company, Decimal("6.5"), source_type="test")  # top-up 4, debt 2.5
    assert change.debt_added == Decimal("2.5") and change.amount == Decimal("6.5")
    wallet = await wallets.get(company)
    assert Decimal(str(wallet.debt)) == Decimal("2.5") and wallet.state == "over_tolerance"  # tolerance 0 (PAYG)
    assert wallet.in_debt_since is not None and wallet.over_tolerance_since is not None
    assert await wallets.check(company) == []


@pytest.mark.asyncio
async def test_top_ups_and_grants_are_spent_soonest_expiring_first(db):
    company = await _company(db)
    later = await _lot(db, company, "topup", "5", days=60)
    sooner = await _lot(db, company, "grant", "5", days=5)
    await WalletService(db).deduct(company, Decimal("3"), source_type="test")
    rows = dict((await db.execute(select(WalletLot.id, WalletLot.remaining).where(
        WalletLot.company_id == company))).all())
    assert rows[sooner.lot_id] == Decimal("2") and rows[later.lot_id] == Decimal("5")


@pytest.mark.asyncio
async def test_paid_credit_repays_debt_first_and_daily_credit_does_not(db):
    company = await _company(db)
    wallets = WalletService(db)
    await wallets.deduct(company, Decimal("3"), source_type="test")
    daily = await _lot(db, company, "daily", "1", days=1)
    assert daily.debt_repaid == 0 and (await wallets.get(company)).state == "over_tolerance"
    change = await _lot(db, company, "topup", "10")
    assert change.debt_repaid == Decimal("3") and change.amount == Decimal("7")
    wallet = await wallets.get(company)
    assert wallet.state == "ok" and Decimal(str(wallet.debt)) == 0 and wallet.in_debt_since is None
    assert await available(db, company) == Decimal("8")                  # daily 1 + top-up 7
    assert await wallets.check(company) == []


@pytest.mark.asyncio
async def test_under_the_tolerance_the_wallet_is_in_debt_and_over_it_over_tolerance(db, monkeypatch):
    from src.billing import wallet as wallet_module

    async def tolerance(self, company_id, currency):
        return Decimal("5")

    monkeypatch.setattr(wallet_module.WalletService, "tolerance", tolerance)
    company = await _company(db)
    wallets = WalletService(db)
    first = await wallets.deduct(company, Decimal("2"), source_type="test")
    assert first.state_after == "in_debt"
    second = await wallets.deduct(company, Decimal("3"), source_type="test")
    assert second.state_after == "over_tolerance"
    back = await wallets.grant(company, "topup", Decimal("1"), expires_at=None, paid=True, source_type="test")
    assert back.state_after == "in_debt"                                  # 4 owed, under 5 again
    assert await wallets.check(company) == []


@pytest.mark.asyncio
async def test_expired_lots_are_not_credit_and_expire_with_an_entry(db):
    company = await _company(db)
    await _lot(db, company, "topup", "20")
    old = await _lot(db, company, "grant", "5")
    await db.execute(text("UPDATE wallet_lots SET expires_at = now() - interval '1 minute' WHERE id = :i"),
                     {"i": old.lot_id})
    assert await available(db, company) == Decimal("20")
    change = await WalletService(db).expire(company)
    assert change.amount == Decimal("5")
    [entry] = (await db.execute(select(WalletEntry).where(WalletEntry.lot_id == old.lot_id,
                                                          WalletEntry.kind == "expire"))).scalars().all()
    assert entry.amount == Decimal("-5") and entry.balance_after == Decimal("20")
    assert await WalletService(db).check(company) == []


@pytest.mark.asyncio
async def test_the_balance_is_in_the_companys_currency(db):
    company = await _company(db, currency="INR")
    await fund(db, company, "1.50")                                        # USD 1.50 at ₹100
    balance = await CreditService(db).get_balance(company)
    assert balance["currency"] == "INR" and Decimal(balance["available"]) == Decimal("150")
    assert balance["wallet_balance"] == 150.0 and balance["free"] == 150.0 and balance["state"] == "ok"


@pytest.mark.asyncio
async def test_a_wallet_in_debt_admits_nothing(db):
    company = await _company(db)
    await WalletService(db).deduct(company, Decimal("1"), source_type="test")
    await _lot(db, company, "daily", "50", days=1)                         # credit, but still owing (DC-4)
    svc = CreditService(db)
    with pytest.raises(WalletBlocked, match="owes USD 1.00"):
        await svc.place_hold(company, uuid.uuid4(), Decimal("0.10"), Decimal("0.05"))
    with pytest.raises(InsufficientCreditsError):
        await svc.check_sufficient_for_execution(company, "AGENT")
    assert await svc.admission_refusal(company, Decimal("0.05")) is not None


@pytest.mark.asyncio
async def test_a_subscription_cycle_replaces_the_last_and_repays_debt(db):
    company = await _company(db, currency="INR")
    svc = CreditService(db)
    end = datetime.utcnow() + timedelta(days=30)
    await svc.inject_subscription_credits(company, Decimal("29"), Decimal("20"), end - timedelta(days=1))
    assert await _remaining(db, company) == {"subscription": 2900, "subscription_bonus": 580}
    await WalletService(db).deduct(company, Decimal("4000"), source_type="test")   # 520 into debt
    await svc.inject_subscription_credits(company, Decimal("29"), Decimal("20"), end)
    assert await _remaining(db, company) == {"subscription": Decimal("2380"), "subscription_bonus": 580}
    wallet = await WalletService(db).get(company)
    assert wallet.state == "ok" and wallet.account_model == "subscription"
    # An older cycle recorded late grants nothing.
    assert await svc.inject_subscription_credits(company, Decimal("29"), Decimal("20"),
                                                 end - timedelta(days=2)) is None
    assert await WalletService(db).check(company) == []


@pytest.mark.asyncio
async def test_an_adjustment_needs_a_reason_and_is_on_the_ledger(db):
    company = await _company(db)
    wallets = WalletService(db)
    actor = uuid.uuid4()
    with pytest.raises(ValueError):
        await wallets.adjust(company, Decimal("5"), actor_id=actor, reason=" ")
    await wallets.adjust(company, Decimal("5"), actor_id=actor, reason="goodwill")
    await wallets.adjust(company, Decimal("-7"), actor_id=actor, reason="charge missed")
    entries = (await db.execute(select(WalletEntry.kind, WalletEntry.amount, WalletEntry.actor_id)
                                .where(WalletEntry.company_id == company))).all()
    assert sorted((k, a) for k, a, _ in entries) == [("debt_add", -2), ("deduct", -5), ("grant", 5)]
    assert all(who == actor for _, _, who in entries)
    assert await wallets.check(company) == []


@pytest.mark.asyncio
async def test_the_check_finds_a_wallet_that_does_not_equal_its_ledger(db):
    company = await _company(db)
    change = await _lot(db, company, "topup", "10")
    await db.execute(text("UPDATE wallet_lots SET remaining = 9 WHERE id = :i"), {"i": change.lot_id})
    await db.execute(text("UPDATE credit_wallets SET debt = 1 WHERE company_id = :c"), {"c": company})
    problems = await WalletService(db).check(company)
    assert len(problems) == 2 and "remaining 9" in problems[0] and "debt 1" in problems[1]


@pytest.mark.asyncio
async def test_concurrent_deductions_are_not_lost(_engine):
    """Three sessions deduct at once; every deduction lands (BC-27, W-9).

    Runs outside the rolled-back fixture — the sessions need committed rows
    they can all see — and deletes what it created.
    """
    from sqlalchemy.ext.asyncio import AsyncSession
    from src.auth.models import Company

    company_id = uuid.uuid4()
    async with AsyncSession(_engine) as setup:
        setup.add(Company(id=company_id, name=f"lots-race-{company_id.hex[:6]}", type="TENANT", status="active",
                          billing_currency="USD"))
        await setup.flush()
        await _lot(setup, company_id, "topup", "100")
        await setup.commit()
    try:
        async def spend():
            async with AsyncSession(_engine) as s:
                for _ in range(5):
                    await WalletService(s).deduct(company_id, Decimal("1"), source_type="test")
                    await s.commit()

        await asyncio.gather(spend(), spend(), spend())
        async with AsyncSession(_engine) as check:
            assert await available(check, company_id) == Decimal("85")
            assert await WalletService(check).check(company_id) == []
            wallet = (await check.execute(select(CreditWallet).where(CreditWallet.company_id == company_id))
                      ).scalar_one()
            assert Decimal(str(wallet.cached_available)) == Decimal("85")
    finally:
        async with AsyncSession(_engine) as cleanup:
            for table in ("wallet_entries", "wallet_lots", "credit_wallets"):
                await cleanup.execute(text(f"DELETE FROM {table} WHERE company_id = :c"), {"c": company_id})
            await cleanup.execute(text("DELETE FROM companies WHERE id = :c"), {"c": company_id})
            await cleanup.commit()
