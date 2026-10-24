"""Phone-number rent (Phase 15 T7-1, tech design §13).

* A rental starts when a number becomes a company's — an admin claims it, or
  staff create or assign it to the company (NR-1) — and its first 30-day
  period is charged at once; it ends on release, with no refund of the period
  (NR-3).
* Each period is charged in advance at ``price_for('phone_number_rent',
  company currency)`` — the currency override (₹2,000 seeded) or the USD amount
  at today's rate — at the item's current version, stored on the rental: an
  edit in the console applies from each rental's next period (NR-2, O-2). Not
  through the usage formula; category ``phone_numbers``; from the wallet like
  usage, lots then debt.
* The hourly job (``billing_number_rent``) charges every rental that is due.
* Over the tolerance for ``numbers.hold_after_days_over_tolerance`` days, a
  company's rentals are ``held``: calls to and from the number are refused, the
  number stays the company's (staff decide a release); repaid, they are active
  again (NR-4).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import select

logger = logging.getLogger(__name__)

PERIOD = timedelta(days=30)
RENT = "phone_number_rent"


async def record_fixed_line(db: Any, *, company_id: UUID, category: str, grouping_type: str,
                            grouping_id: Optional[UUID], amount: Decimal, currency: str) -> None:
    """A fixed charge (not usage) on the day's billing line for its category (§5.3)."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from src.billing.billing_models import BillingLine
    from src.billing.currency import current_rate, to_usd

    rate = await current_rate(db, currency)
    usd = to_usd(amount, rate)
    values = {"company_id": company_id, "period_day": datetime.utcnow().date(), "category": category,
              "grouping_type": grouping_type, "grouping_id": grouping_id, "currency": currency, "fx_rate_id": rate.id,
              "cost_usd": Decimal(0), "billed_usd": usd, "billed_ccy": amount, "quantity": Decimal(1), "rows": 1,
              "updated_at": datetime.utcnow()}
    insert = pg_insert(BillingLine).values(**values)
    table = BillingLine.__table__
    await db.execute(insert.on_conflict_do_update(
        constraint="uq_billing_lines_key",
        set_={**{c: table.c[c] + insert.excluded[c] for c in ("billed_usd", "billed_ccy", "quantity", "rows")},
              "updated_at": insert.excluded.updated_at}))


async def charge_period(db: Any, rental: Any, *, now: Optional[datetime] = None) -> Any:
    """Charge the rental's next period in advance (the caller commits); the wallet change."""
    from src.billing.price_items import price_for
    from src.billing.wallet import WalletService
    from src.voice.phone_pool_models import PhoneNumber

    now = now or datetime.utcnow()
    wallets = WalletService(db)
    wallet = await wallets.lock(rental.company_id)
    price = await price_for(db, RENT, wallet.currency)
    number = await db.get(PhoneNumber, rental.phone_number_id)
    period = rental.periods_charged + 1
    change = await wallets.deduct(rental.company_id, price.amount, source_type="rent",
                                  source_id=f"rental:{rental.id}:{period}", category="phone_numbers",
                                  reason=f"rent of {number.phone_number if number else 'a number'}, period {period}",
                                  fx_rate_id=price.fx_rate_id, now=now)
    await record_fixed_line(db, company_id=rental.company_id, category="phone_numbers", grouping_type="phone_number",
                            grouping_id=rental.phone_number_id, amount=price.amount, currency=wallet.currency)
    rental.periods_charged = period
    rental.price_item_version, rental.last_amount, rental.currency = price.version, price.amount, wallet.currency
    rental.next_charge_at = rental.next_charge_at + PERIOD if rental.next_charge_at > now - PERIOD else now + PERIOD
    return change


async def start_rental(db: Any, number: Any, company_id: UUID) -> Any:
    """The company rents ``number`` from now; its first period is charged (the caller commits)."""
    from src.billing.billing_models import NumberRental

    existing = (await db.execute(select(NumberRental).where(
        NumberRental.phone_number_id == number.id, NumberRental.status != "ended"))).scalar_one_or_none()
    if existing is not None:
        if existing.company_id == company_id:
            return existing
        await end_rental(db, number)
    now = datetime.utcnow()
    rental = NumberRental(phone_number_id=number.id, company_id=company_id, status="active", started_at=now,
                          next_charge_at=now)
    db.add(rental)
    await db.flush()
    await charge_period(db, rental, now=now)
    return rental


async def end_rental(db: Any, number: Any) -> Optional[Any]:
    """The number is released: no more periods (none refunded). The caller commits."""
    from src.billing.billing_models import NumberRental

    rental = (await db.execute(select(NumberRental).where(
        NumberRental.phone_number_id == number.id, NumberRental.status != "ended"))).scalar_one_or_none()
    if rental is not None:
        rental.status, rental.ended_at = "ended", datetime.utcnow()
    return rental


async def rental_of(db: Any, number_id: UUID) -> Optional[Any]:
    from src.billing.billing_models import NumberRental

    return (await db.execute(select(NumberRental).where(
        NumberRental.phone_number_id == number_id, NumberRental.status != "ended"))).scalar_one_or_none()


async def number_held(db: Any, phone_number: str) -> bool:
    """Whether calls to or from this number are refused for an unpaid balance (NR-4)."""
    from src.billing.billing_models import NumberRental
    from src.voice.phone_pool_models import PhoneNumber

    return (await db.execute(select(NumberRental.id).join(PhoneNumber, PhoneNumber.id == NumberRental.phone_number_id)
                             .where(PhoneNumber.phone_number == phone_number, NumberRental.status == "held"))
            ).first() is not None


async def charge_due(db: Any, *, now: Optional[datetime] = None) -> Dict[str, int]:
    """The hourly job: every rental (active or held) whose next period is due."""
    from src.billing.billing_models import NumberRental
    from src.billing.enforcement import wallet_changed

    now = now or datetime.utcnow()
    ids = list((await db.execute(select(NumberRental.id).where(
        NumberRental.status != "ended", NumberRental.next_charge_at <= now))).scalars().all())
    out = {"due": len(ids), "charged": 0, "errors": 0}
    for rental_id in ids:
        try:
            rental = (await db.execute(select(NumberRental).where(NumberRental.id == rental_id)
                                       .with_for_update())).scalar_one()
            if rental.status == "ended" or rental.next_charge_at > now:
                await db.commit()
                continue
            change = await charge_period(db, rental, now=now)
            await db.commit()
            out["charged"] += 1
            await wallet_changed(db, rental.company_id, change)
        except Exception as error:  # noqa: BLE001 - one rental's failure is its own
            await db.rollback()
            out["errors"] += 1
            logger.error("rent of rental %s failed: %s", rental_id, error)
    return out


async def hold_for_balance(db: Any, *, now: Optional[datetime] = None) -> Dict[str, int]:
    """Hold the rentals of companies over the tolerance too long; free those of companies back in credit."""
    from src.billing.billing_models import CreditWallet, NumberRental
    from src.billing.settings_catalogue import value

    from src.billing import rollout

    now = now or datetime.utcnow()
    out = {"held": 0, "released": 0}
    enforcing = await rollout.enabled(db, rollout.ENFORCEMENT)            # T10-3: nothing is held while off
    for w in [] if not enforcing else (await db.execute(select(CreditWallet.company_id, CreditWallet.state, CreditWallet.over_tolerance_since)
                               .where(CreditWallet.state.in_(("over_tolerance", "suspended"))))).all():
        days = int(await value(db, "numbers.hold_after_days_over_tolerance", w.company_id))
        if w.over_tolerance_since is not None and w.over_tolerance_since <= now - timedelta(days=days):
            for rental in (await db.execute(select(NumberRental).where(
                    NumberRental.company_id == w.company_id, NumberRental.status == "active"))).scalars().all():
                rental.status, rental.held_at = "held", now
                out["held"] += 1
    ok = select(CreditWallet.company_id).where(CreditWallet.state == "ok")
    for rental in (await db.execute(select(NumberRental).where(
            NumberRental.status == "held", NumberRental.company_id.in_(ok)))).scalars().all():
        rental.status, rental.held_at = "active", None
        out["released"] += 1
    await db.commit()
    return out
