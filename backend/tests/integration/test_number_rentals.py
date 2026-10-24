"""Phone-number rent (Phase 15 T7-1, tech design §13; NR-1…NR-6).

A number becoming a company's starts a rental whose first 30 days are charged
at once — ₹2,000 for an Indian tenant (the price item's rupee price) — from the
wallet, category ``phone_numbers``; the hourly job charges each period as it
falls due, at the price item's version of the day (a console edit applies from
the next period); release ends the rental with no refund; a company over its
tolerance for too long has its numbers held (calls refused) until it repays.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.auth.models import Company
from src.billing import rentals
from src.billing.billing_models import BillingLine, CreditWallet, NumberRental, WalletEntry
from src.voice.phone_pool_models import PhoneNumber
from tests.harness.wallet import available, fund

pytestmark = pytest.mark.needs_db


async def _company(db, currency="INR"):
    c = Company(name=f"rent-{uuid.uuid4().hex[:6]}", type="TENANT", status="active", billing_currency=currency,
                country_code="IN" if currency == "INR" else "US")
    db.add(c)
    await db.flush()
    return c.id


async def _number(db, company_id=None):
    n = PhoneNumber(phone_number=f"+9180{uuid.uuid4().int % 10 ** 8:08d}", provider="tata_tele",
                    country_code="+91", status="claimed" if company_id else "available", company_id=company_id)
    db.add(n)
    await db.flush()
    return n


@pytest.mark.asyncio
async def test_claiming_charges_the_first_30_days_in_rupees(db):
    company = await _company(db)
    await fund(db, company, "100")                                 # ₹ at the seeded rate
    before = await available(db, company)
    rental = await rentals.start_rental(db, await _number(db, company), company)
    await db.flush()
    assert (rental.status, rental.periods_charged, rental.currency, rental.last_amount) == ("active", 1, "INR",
                                                                                            Decimal("2000"))
    assert abs(rental.next_charge_at - (datetime.utcnow() + timedelta(days=30))) < timedelta(minutes=1)
    assert before - await available(db, company) == Decimal("2000")
    entry = (await db.execute(select(WalletEntry).where(WalletEntry.company_id == company,
                                                         WalletEntry.source_type == "rent"))).scalars().first()
    assert entry.category == "phone_numbers" and entry.source_id == f"rental:{rental.id}:1"
    line = (await db.execute(select(BillingLine).where(BillingLine.company_id == company,
                                                        BillingLine.category == "phone_numbers"))).scalar_one()
    assert line.billed_ccy == Decimal("2000") and line.grouping_id == rental.phone_number_id


@pytest.mark.asyncio
async def test_the_same_company_claiming_again_is_not_charged_twice(db):
    company = await _company(db)
    await fund(db, company, "100")
    number = await _number(db, company)
    first = await rentals.start_rental(db, number, company)
    again = await rentals.start_rental(db, number, company)
    assert first.id == again.id and again.periods_charged == 1


@pytest.mark.asyncio
async def test_a_due_period_is_charged_at_the_new_price(db):
    """An edit in the console applies from each rental's next period (NR-2)."""
    from src.billing.price_items import price_for, set_price_item

    company = await _company(db)
    await fund(db, company, "100")
    rental = await rentals.start_rental(db, await _number(db, company), company)
    first_version = rental.price_item_version
    rent = await price_for(db, rentals.RENT, "USD")
    await set_price_item(db, rentals.RENT, amount_usd=rent.amount, currency_overrides={"INR": "2400"}, active=True,
                         actor=None, reason="test: new carrier rate")
    rental.next_charge_at = datetime.utcnow() - timedelta(minutes=1)
    await db.flush()
    change = await rentals.charge_period(db, rental)
    assert change is not None
    assert (rental.periods_charged, rental.last_amount) == (2, Decimal("2400"))
    assert rental.price_item_version == first_version + 1
    assert rental.next_charge_at > datetime.utcnow() + timedelta(days=29)


@pytest.mark.asyncio
async def test_the_hourly_job_charges_only_what_is_due(db):
    company = await _company(db)
    await fund(db, company, "100")
    due = await rentals.start_rental(db, await _number(db, company), company)
    not_due = await rentals.start_rental(db, await _number(db, company), company)
    due.next_charge_at = datetime.utcnow() - timedelta(hours=1)
    await db.commit()
    out = await rentals.charge_due(db)
    assert out["charged"] >= 1
    await db.refresh(due)
    await db.refresh(not_due)
    assert (due.periods_charged, not_due.periods_charged) == (2, 1)


@pytest.mark.asyncio
async def test_release_stops_the_rent_with_no_refund(db):
    company = await _company(db)
    await fund(db, company, "100")
    number = await _number(db, company)
    rental = await rentals.start_rental(db, number, company)
    left = await available(db, company)
    await rentals.end_rental(db, number)
    rental.next_charge_at = datetime.utcnow() - timedelta(hours=1)
    await db.commit()
    await rentals.charge_due(db)
    await db.refresh(rental)
    assert rental.status == "ended" and rental.periods_charged == 1
    assert await available(db, company) == left                      # nothing back, nothing more


@pytest.mark.asyncio
async def test_rent_without_credit_becomes_debt(db):
    company = await _company(db)
    await rentals.start_rental(db, await _number(db, company), company)
    wallet = (await db.execute(select(CreditWallet).where(CreditWallet.company_id == company))).scalar_one()
    assert Decimal(str(wallet.debt)) == Decimal("2000") and wallet.state != "ok"


@pytest.mark.asyncio
async def test_too_long_over_tolerance_holds_the_numbers_and_admission_refuses_them(db):
    from src.voice.call_admission import HELD, call_refusal

    company = await _company(db)
    number = await _number(db, company)
    rental = await rentals.start_rental(db, number, company)
    wallet = (await db.execute(select(CreditWallet).where(CreditWallet.company_id == company))).scalar_one()
    wallet.state, wallet.over_tolerance_since = "over_tolerance", datetime.utcnow() - timedelta(days=60)
    await db.commit()
    out = await rentals.hold_for_balance(db)
    await db.refresh(rental)
    assert out["held"] >= 1 and rental.status == "held"
    assert await rentals.number_held(db, number.phone_number) is True
    assert await call_refusal(db, company, direction="inbound", checkpoint="tata_webhook",
                              number=number.phone_number) == HELD
    # Repaid: the next tick frees it.
    wallet.state, wallet.over_tolerance_since = "ok", None
    await db.commit()
    out = await rentals.hold_for_balance(db)
    await db.refresh(rental)
    assert out["released"] >= 1 and rental.status == "active"


@pytest.mark.asyncio
async def test_moving_a_number_ends_the_old_companys_rental(db):
    first, second = await _company(db), await _company(db)
    await fund(db, first, "100")
    await fund(db, second, "100")
    number = await _number(db, first)
    old = await rentals.start_rental(db, number, first)
    number.company_id = second
    new = await rentals.start_rental(db, number, second)
    await db.flush()
    assert old.status == "ended" and new.company_id == second and new.periods_charged == 1
    open_ = (await db.execute(select(NumberRental).where(NumberRental.phone_number_id == number.id,
                                                          NumberRental.status != "ended"))).scalars().all()
    assert [r.id for r in open_] == [new.id]
