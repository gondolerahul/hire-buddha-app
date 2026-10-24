"""Fixed prices (Phase 15 T5-3, tech design §8.3).

What is not rated by the formula — phone-number rent, partner annual fees —
has a price item: a USD amount and, per currency, an optional override
(``{"INR": 2000}``: Indian tenants pay ₹2,000 a number whatever the FX rate,
K-5). ``price_for(code, currency)`` is the override when there is one, else the
USD amount at today's rate.

An edit is a new ``version`` (each kept in ``price_item_versions`` for audit
and invoices); it applies from each recurring item's next charge (a rental
already charged for its current period is not re-priced, O-2).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select


class UnknownPriceItem(LookupError):
    pass


@dataclass(frozen=True)
class Price:
    code: str
    version: int
    currency: str
    amount: Decimal
    overridden: bool
    amount_usd: Decimal
    fx_rate_id: Any = None


async def price_for(db: Any, code: str, currency: str) -> Price:
    """The item's price in ``currency`` now (``UnknownPriceItem`` when there is no active item)."""
    from src.billing.billing_models import PriceItem
    from src.billing.currency import current_rate, to_ccy

    item = (await db.execute(select(PriceItem).where(PriceItem.code == code))).scalar_one_or_none()
    if item is None or not item.active:
        raise UnknownPriceItem(code)
    currency = currency.upper()
    overrides = item.currency_overrides or {}
    usd = Decimal(str(item.amount_usd))
    if currency in overrides and overrides[currency] is not None:
        return Price(code, item.version, currency, Decimal(str(overrides[currency])), True, usd)
    rate = await current_rate(db, currency)
    return Price(code, item.version, currency, to_ccy(usd, rate), False, usd, rate.id)


async def set_price_item(db: Any, code: str, *, amount_usd: Decimal, currency_overrides: dict,
                         active: bool, actor: Any, reason: Optional[str], name: Optional[str] = None) -> Any:
    """A new version of ``code`` (the caller commits); audited."""
    from src.billing.billing_models import PriceItem, PriceItemVersion
    from src.common.admin_audit import record_admin_change

    item = (await db.execute(select(PriceItem).where(PriceItem.code == code).with_for_update())).scalar_one_or_none()
    if item is None:
        raise UnknownPriceItem(code)
    old = {"version": item.version, "amount_usd": str(item.amount_usd), "currency_overrides": item.currency_overrides,
           "active": item.active}
    overrides = {k.upper(): str(Decimal(str(v))) for k, v in (currency_overrides or {}).items() if v not in (None, "")}
    item.version += 1
    item.amount_usd, item.currency_overrides, item.active = Decimal(str(amount_usd)), overrides, active
    if name:
        item.name = name
    item.updated_by = getattr(actor, "id", None)
    item.updated_at = datetime.utcnow()
    db.add(PriceItemVersion(code=code, version=item.version, amount_usd=item.amount_usd,
                            currency_overrides=overrides, active=active, reason=reason,
                            created_by=getattr(actor, "id", None)))
    record_admin_change(db, actor=actor, action="set", object_type="price_item", object_key=code,
                        old_value=old, new_value={"version": item.version, "amount_usd": str(item.amount_usd),
                                                  "currency_overrides": overrides, "active": active}, reason=reason)
    await db.flush()
    return item
