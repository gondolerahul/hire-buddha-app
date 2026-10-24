"""Changing a company's billing currency (Phase 15 T2-7, tech design §6.7).

A company is billed in one currency (FX-1, Q3), set from its country when it
is made. Changing it converts everything the wallet holds at one locked rate:

* each live lot — a ``convert`` entry out (its remaining, old currency) and
  one in (the same value, new currency), the lot re-denominated;
* the debt — a ``convert`` entry, so the ledger still proves the debt (W-9);
* open holds of running work — re-denominated;

then the wallet's and the company's currency change. Staff do it with the
tool below (``change_currency``: audited, refused while a subscription is
live, since its plan is priced in the old currency); the onboarding profile
step does it for a company that has not paid or used anything yet, whose
wallet holds at most its daily credits (``convert_wallet``).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select

ZERO = Decimal(0)


class CurrencyChangeRefused(ValueError):
    pass


async def convert_wallet(db: Any, company_id: UUID, new_currency: str, *, reason: str,
                         actor_id: Optional[UUID] = None) -> dict:
    """Re-denominate the wallet in ``new_currency`` at one locked rate (the caller commits)."""
    from src.billing.billing_models import CreditHold, CreditWallet, WalletEntry
    from src.billing.currency import current_rate, to_ccy, to_usd
    from src.billing.wallet import WalletService

    wallets = WalletService(db)
    wallet = (await db.execute(select(CreditWallet).where(CreditWallet.company_id == company_id)
                               .with_for_update())).scalar_one_or_none()
    new_currency = new_currency.upper()
    if wallet is None or wallet.currency == new_currency:
        return {"lots": 0, "from": wallet.currency if wallet else None, "to": new_currency}
    old_rate, new_rate = await current_rate(db, wallet.currency), await current_rate(db, new_currency)

    def convert(amount: Any) -> Decimal:
        return to_ccy(to_usd(Decimal(str(amount or 0)), old_rate), new_rate)

    now = datetime.utcnow()
    old_currency = wallet.currency
    lots = await wallets.live_lots(company_id, now=now, lock=True)
    available_old = sum((Decimal(str(lot.remaining)) for lot in lots), ZERO)
    available_new = ZERO
    for lot in lots:
        before = Decimal(str(lot.remaining))
        after = convert(before)
        available_old -= before
        db.add(WalletEntry(company_id=company_id, lot_id=lot.id, kind="convert", amount=-before,
                           currency=old_currency, balance_after=convert(available_old) + available_new,
                           debt_after=Decimal(str(wallet.debt)), reason=f"{reason}: out of {old_currency}",
                           source_type="currency_change", actor_id=actor_id, fx_rate_id=old_rate.id))
        lot.currency, lot.original, lot.remaining = new_currency, convert(lot.original), after
        available_new += after
        db.add(WalletEntry(company_id=company_id, lot_id=lot.id, kind="convert", amount=after,
                           currency=new_currency, balance_after=available_new + convert(available_old),
                           debt_after=Decimal(str(wallet.debt)), reason=f"{reason}: into {new_currency}",
                           source_type="currency_change", actor_id=actor_id, fx_rate_id=new_rate.id))
    debt_old = Decimal(str(wallet.debt))
    if debt_old > 0:
        debt_new = convert(debt_old)
        wallet.debt = debt_new
        # A convert entry with no lot moves the debt from one denomination to the other.
        db.add(WalletEntry(company_id=company_id, kind="convert", amount=debt_old - debt_new, currency=new_currency,
                           balance_after=available_new, debt_after=debt_new,
                           reason=f"{reason}: debt {old_currency} {debt_old} → {new_currency} {debt_new}",
                           source_type="currency_change", actor_id=actor_id, fx_rate_id=new_rate.id))
    holds = (await db.execute(select(CreditHold).where(CreditHold.company_id == company_id,
                                                       CreditHold.released_at.is_(None))
                              .with_for_update())).scalars().all()
    for hold in holds:
        hold.amount, hold.currency = convert(hold.amount), new_currency
    wallet.currency, wallet.cached_available, wallet.updated_at = new_currency, available_new, now
    await db.flush()
    return {"lots": len(lots), "from": old_currency, "to": new_currency, "rate_from": str(old_rate.units_per_usd),
            "rate_to": str(new_rate.units_per_usd), "available": str(available_new), "debt": str(wallet.debt),
            "holds": len(holds)}


async def change_currency(db: Any, company_id: UUID, new_currency: str, *, actor: Any, reason: str) -> dict:
    """The staff tool (§6.7): convert the wallet, change the company's currency, audit. The caller commits."""
    from src.auth.models import Company
    from src.billing.billing_models import Currency, Subscription
    from src.billing.payment_service import LIVE_SUBSCRIPTION_STATUSES
    from src.common.admin_audit import record_admin_change

    if not reason or not reason.strip():
        raise CurrencyChangeRefused("a currency change needs a reason")
    new_currency = new_currency.upper()
    company = (await db.execute(select(Company).where(Company.id == company_id).with_for_update())
               ).scalar_one_or_none()
    if company is None:
        raise LookupError("no such company")
    active = (await db.execute(select(Currency.active).where(Currency.code == new_currency))).scalar_one_or_none()
    if not active:
        raise CurrencyChangeRefused(f"{new_currency} is not an active currency")
    if company.billing_currency == new_currency:
        raise CurrencyChangeRefused(f"the company is billed in {new_currency} already")
    live = (await db.execute(select(Subscription.id).where(
        Subscription.company_id == company_id, Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES)))).first()
    if live is not None:
        raise CurrencyChangeRefused("the company has a live subscription, priced in its currency: cancel it first")
    old = company.billing_currency
    result = await convert_wallet(db, company_id, new_currency, reason=reason, actor_id=getattr(actor, "id", None))
    company.billing_currency = new_currency
    record_admin_change(db, actor=actor, action="change_currency", object_type="company_currency",
                        object_key=str(company_id), target_company_id=company_id,
                        old_value={"currency": old}, new_value={"currency": new_currency, **result}, reason=reason)
    return {"company_id": str(company_id), **result, "from": old}
