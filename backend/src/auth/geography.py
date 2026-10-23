"""A company's country, billing currency and billing profile (Phase 15 T2-2, T2-3; tech design §3.2).

FX-1: a company's ``billing_currency`` is its country profile's currency (else
``billing.default_currency``), set when the company is made — at self sign-up,
by a partner, by staff — and it does not change by itself. While no money has
moved (no payment, no usage), the onboarding profile step may still set the
country, and the currency follows it; after that only staff can change the
currency, with the conversion tool (T2-7), which converts what the wallet holds.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import exists, select

# GSTIN: 2-digit state code, PAN (5 letters, 4 digits, 1 letter), entity number, 'Z', check character (TX-5).
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
STATE_RE = re.compile(r"^[A-Z0-9]{2}$")


def normalise_country(value: Optional[str]) -> Optional[str]:
    return value.strip().upper() if value and value.strip() else None


def valid_gstin(value: Optional[str]) -> Optional[str]:
    """The GSTIN upper-cased, or ``ValueError`` (pydantic: 422)."""
    if value is None or not value.strip():
        return None
    value = value.strip().upper()
    if not GSTIN_RE.match(value):
        raise ValueError("not a valid GSTIN (15 characters: state code, PAN, entity, Z, check)")
    return value


def valid_state(value: Optional[str]) -> Optional[str]:
    """An Indian state code (two letters or digits, e.g. KA), or ``ValueError``."""
    if value is None or not value.strip():
        return None
    value = value.strip().upper()
    if not STATE_RE.match(value):
        raise ValueError("billing_state is a two-character state code, e.g. KA")
    return value


async def money_moved(db: Any, company_id: Any) -> bool:
    """Whether the company has paid or used anything — its currency is then fixed."""
    from src.ai.orm.usage import UsageLog
    from src.billing.billing_models import PaymentTransaction

    paid = await db.scalar(select(exists().where(PaymentTransaction.company_id == company_id,
                                                  PaymentTransaction.status == "success")))
    used = await db.scalar(select(exists().where(UsageLog.company_id == company_id)))
    return bool(paid or used)


async def set_geography(db: Any, company: Any, country_code: Optional[str], *,
                        billing_state: Optional[str] = None, initial: bool = True) -> None:
    """Set ``company``'s country and derive its billing currency (FX-1). 422 for an unknown country.

    ``initial``: the company is being made. Otherwise (onboarding) the currency
    may follow a new country only while no money has moved (409 after).
    """
    from src.billing.billing_models import CountryProfile
    from src.billing.currency import currency_for_country

    country = normalise_country(country_code) or "IN"
    if (await db.execute(select(CountryProfile.country_code).where(
            CountryProfile.country_code == country))).scalar_one_or_none() is None:
        raise HTTPException(status_code=422, detail=f"unknown country {country!r} (ISO 3166 code, e.g. IN)")
    currency = await currency_for_country(db, country)
    if not initial and currency != company.billing_currency and await money_moved(db, company.id):
        raise HTTPException(status_code=409, detail=(
            f"This company is billed in {company.billing_currency} and money has moved; "
            "only HireBuddha staff can change its currency."))
    company.country_code, company.billing_currency = country, currency
    if billing_state is not None:
        company.billing_state = valid_state(billing_state)
