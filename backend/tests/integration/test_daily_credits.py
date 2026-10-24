"""Daily credits: policies, bands, overrides, local midnight (Phase 15 T5-5; tech design §7).

The examples of §7.3: *Direct trial* — 30 days, days 1–10 USD 2.00, days 11–30
USD 0.50 — gives an Indian direct tenant ₹200 a day for ten days, then ₹50 a
day until day 30; *Partner XYZ* — 0 days — gives its tenants none. A grant is
once per company and local date, replacing yesterday's lot; it never repays
debt. Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.auth.models import Company
from src.billing.billing_models import (
    CompanyDailyCreditOverride, DailyCreditBand, DailyCreditPolicy, WalletEntry, WalletLot,
)
from src.billing.daily_credits import grant_today, local_day, resolve
from src.billing.wallet import WalletService
from tests.harness.wallet import available

pytestmark = pytest.mark.needs_db
NOON_UTC = datetime(2026, 10, 24, 6, 30)        # 12:00 in Asia/Kolkata


@pytest.fixture(autouse=True)
async def _no_other_policies(db):
    """These tests own the policies: any already active stand aside (rolled back after)."""
    from sqlalchemy import update
    await db.execute(update(DailyCreditPolicy).values(active=False))
    await db.flush()


async def _company(db, *, created_days_ago=0, parent=None, kind="TENANT", tz="Asia/Kolkata", currency="INR"):
    c = Company(name=f"daily-{uuid.uuid4().hex[:6]}", type=kind, status="active", billing_currency=currency,
                timezone=tz, parent_id=parent, created_at=NOON_UTC - timedelta(days=created_days_ago))
    db.add(c)
    await db.flush()
    return c


async def _policy(db, audience, bands, duration, partner=None, name=None):
    p = DailyCreditPolicy(name=name or f"{audience} {uuid.uuid4().hex[:4]}", audience=audience,
                          partner_id=partner, duration_days=duration, effective_from=NOON_UTC - timedelta(days=400))
    db.add(p)
    await db.flush()
    for start, end, amount in bands:
        db.add(DailyCreditBand(policy_id=p.id, from_day=start, to_day=end, amount_usd=Decimal(amount)))
    await db.flush()
    return p


@pytest.mark.asyncio
@pytest.mark.parametrize("age, expected", [(0, "200"), (9, "200"), (10, "50"), (29, "50"), (30, "0")])
async def test_the_direct_trial_example(db, age, expected):
    await _policy(db, "direct", [(1, 10, "2.00"), (11, 30, "0.50")], 30, name="Direct trial")
    company = await _company(db, created_days_ago=age)
    resolution = await resolve(db, company, now=NOON_UTC)
    assert resolution.source == "direct" and resolution.day == age + 1
    await grant_today(db, company.id, now=NOON_UTC)
    assert await _granted(db, company.id) == Decimal(expected)


async def _granted(db, company_id) -> Decimal:
    lots = (await db.execute(select(WalletLot.original).where(WalletLot.company_id == company_id,
                                                              WalletLot.kind == "daily"))).scalars().all()
    return sum((Decimal(str(x)) for x in lots), Decimal(0))


@pytest.mark.asyncio
async def test_a_partners_zero_day_policy_gives_its_tenants_none(db):
    await _policy(db, "direct", [(1, 30, "2.00")], 30)
    await _policy(db, "all_partners", [(1, 30, "1.00")], 30)
    partner = await _company(db, kind="PARTNER")
    await _policy(db, "partner", [], 0, partner=partner.id, name="Partner XYZ")
    tenant = await _company(db, parent=partner.id)
    resolution = await resolve(db, tenant, now=NOON_UTC)
    assert (resolution.source, resolution.amount_usd) == ("partner", 0)
    other_partner = await _company(db, kind="PARTNER")
    elsewhere = await _company(db, parent=other_partner.id)
    assert (await resolve(db, elsewhere, now=NOON_UTC)).source == "all_partners"


@pytest.mark.asyncio
async def test_an_upline_partners_policy_applies_only_when_inheritance_is_on(db, monkeypatch):
    top = await _company(db, kind="PARTNER")
    await _policy(db, "partner", [(1, 365, "3.00")], 365, partner=top.id)
    await _policy(db, "all_partners", [(1, 365, "1.00")], 365)
    middle = await _company(db, kind="PARTNER", parent=top.id)
    tenant = await _company(db, parent=middle.id)
    assert (await resolve(db, tenant, now=NOON_UTC)).source == "all_partners"
    import src.billing.settings_catalogue as catalogue
    real = catalogue.value

    async def inherit(db_, key, company_id=None):
        return True if key == "daily_credits.inherit_up_partner_chain" else await real(db_, key, company_id)

    monkeypatch.setattr(catalogue, "value", inherit)
    resolution = await resolve(db, tenant, now=NOON_UTC)
    assert (resolution.source, resolution.amount_usd) == ("upline_partner", Decimal("3.00"))


@pytest.mark.asyncio
async def test_overrides_come_first(db):
    await _policy(db, "direct", [(1, 365, "2.00")], 365)
    none = await _company(db)
    custom = await _company(db, created_days_ago=20)
    db.add_all([CompanyDailyCreditOverride(company_id=none.id, mode="none", reason="test"),
                CompanyDailyCreditOverride(company_id=custom.id, mode="custom", amount_usd=Decimal("0.75"),
                                           duration_days=30, reason="test")])
    await db.flush()
    assert (await resolve(db, none, now=NOON_UTC)).amount_usd == 0
    assert (await resolve(db, custom, now=NOON_UTC)).amount_usd == Decimal("0.75")
    assert (await resolve(db, custom, now=NOON_UTC + timedelta(days=15))).amount_usd == 0   # past 30 days


@pytest.mark.asyncio
async def test_one_grant_per_local_date_replacing_yesterdays_at_local_midnight(db):
    await _policy(db, "direct", [(1, 365, "1.00")], 365)
    company = await _company(db)
    today, day, midnight = local_day(company.created_at, company.timezone, NOON_UTC)
    assert midnight == datetime(2026, 10, 24, 18, 30)                       # 00:00 IST in UTC
    assert await grant_today(db, company.id, now=NOON_UTC) is not None
    assert await grant_today(db, company.id, now=NOON_UTC + timedelta(hours=5)) is None   # still the 24th in IST
    await WalletService(db).deduct(company.id, Decimal("30"), source_type="test")
    after_midnight = datetime(2026, 10, 24, 18, 31)
    assert await grant_today(db, company.id, now=after_midnight) is not None
    lots = (await db.execute(select(WalletLot).where(WalletLot.company_id == company.id)
                             .order_by(WalletLot.granted_at))).scalars().all()
    assert [(lot.local_date.isoformat(), lot.remaining) for lot in lots] == [
        ("2026-10-24", Decimal("0")), ("2026-10-25", Decimal("100"))]
    expired = (await db.execute(select(WalletEntry.amount).where(
        WalletEntry.lot_id == lots[0].id, WalletEntry.kind == "expire"))).scalars().all()
    assert expired == [Decimal("-70")]                                    # ₹70 unspent, never carried over
    assert await WalletService(db).check(company.id) == []


@pytest.mark.asyncio
async def test_a_wallet_in_debt_still_gets_its_daily_lot_but_it_repays_nothing(db):
    await _policy(db, "direct", [(1, 365, "1.00")], 365)
    company = await _company(db)
    await WalletService(db).deduct(company.id, Decimal("40"), source_type="test")
    change = await grant_today(db, company.id, now=NOON_UTC)
    assert change.debt_repaid == 0 and await available(db, company.id) == Decimal("100")
    wallet = await WalletService(db).get(company.id)
    assert wallet.debt == Decimal("40") and wallet.state != "ok"


@pytest.mark.asyncio
async def test_a_suspended_or_inactive_company_gets_none(db):
    await _policy(db, "direct", [(1, 365, "1.00")], 365)
    company = await _company(db)
    company.status = "suspended"
    await db.flush()
    assert await grant_today(db, company.id, now=NOON_UTC) is None
