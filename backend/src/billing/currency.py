"""Currencies, FX rates and a company's billing currency (Phase 15 T2-1, tech design §3).

All costing is in USD (REQ-CO-3). An amount becomes a company's currency only
when it is shown, held, charged or paid: ``to_ccy(usd, rate)`` with the rate
locked for that event (FX-4) — no rounding (FX-5, K-1).

* ``current_rate(db, ccy)`` — the ``fx_rates`` row with the latest
  ``effective_from`` already in effect (FX-2); USD is always 1.
* ``currency_for_country(db, country)`` — the country profile's currency, else
  the ``billing.default_currency`` setting (INR, REQ-BL-2) — FX-1.
* ``gateway_minor_units(amount, ccy)`` — the integer paise/cents a gateway is
  sent: the one rounding a payment has (K-1), half up.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select

USD = "USD"
DEFAULT_CURRENCY = "INR"


class UnknownCurrency(LookupError):
    pass


@dataclass(frozen=True)
class Rate:
    """A locked conversion: ``units_per_usd`` of ``currency`` (``id`` is the ``fx_rates`` row)."""
    currency: str
    units_per_usd: Decimal
    id: Optional[UUID] = None
    effective_from: Optional[datetime] = None


USD_RATE = Rate(USD, Decimal(1))


async def current_rate(db: Any, currency: str, *, at: Optional[datetime] = None) -> Rate:
    """The rate in effect for ``currency`` at ``at`` (now). ``UnknownCurrency`` when it has none."""
    from src.billing.billing_models import FxRate

    currency = currency.upper()
    if currency == USD:
        return USD_RATE
    row = (await db.execute(
        select(FxRate).where(FxRate.currency == currency, FxRate.effective_from <= (at or datetime.utcnow()))
        .order_by(FxRate.effective_from.desc(), FxRate.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if row is None:
        raise UnknownCurrency(f"no FX rate for {currency}")
    return Rate(currency, Decimal(str(row.units_per_usd)), row.id, row.effective_from)


def to_ccy(usd: Decimal, rate: Rate) -> Decimal:
    """USD → the rate's currency (FX-5): no rounding."""
    return Decimal(str(usd)) * rate.units_per_usd


def to_usd(amount: Decimal, rate: Rate) -> Decimal:
    """The rate's currency → USD (FX-5): no rounding."""
    return Decimal(str(amount)) / rate.units_per_usd


async def currency_for_country(db: Any, country_code: Optional[str]) -> str:
    """A new company's billing currency (FX-1): its country's, else the default setting."""
    from src.billing.billing_models import CountryProfile
    from src.common.settings_store import get_platform_setting

    if country_code:
        currency = (await db.execute(select(CountryProfile.billing_currency).where(
            CountryProfile.country_code == country_code.upper()))).scalar_one_or_none()
        if currency:
            return currency
    return str(await get_platform_setting(db, "billing.default_currency") or DEFAULT_CURRENCY)


async def minor_units(db: Any, currency: str) -> int:
    from src.billing.billing_models import Currency

    value = (await db.execute(select(Currency.minor_units).where(Currency.code == currency.upper()))).scalar_one_or_none()
    if value is None:
        raise UnknownCurrency(currency)
    return int(value)


def gateway_minor_units(amount: Decimal, digits: int = 2) -> int:
    """The integer amount a payment gateway takes (paise, cents): the one rounding of a payment (K-1)."""
    scaled = Decimal(str(amount)) * (Decimal(10) ** digits)
    return int(scaled.quantize(Decimal(1), rounding=ROUND_HALF_UP))
