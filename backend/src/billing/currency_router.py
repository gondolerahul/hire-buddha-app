"""Currencies, FX rates, country profiles and currency settings — for staff (Phase 15 T2-4, tech design §3, §15).

Only ``app_admin`` changes them (FX-3, REQ-CO-4); every change writes
``admin_audit_log``. Rates are append-only: "changing" the INR rate adds a row
that takes effect at ``effective_from`` (now by default) — events already
priced keep the rate they locked (FX-4, FX-6).

    GET  /api/v1/admin/currencies                   currencies with their current rate
    GET  /api/v1/admin/fx-rates?currency=INR        a currency's rates, newest first
    POST /api/v1/admin/fx-rates                     add a rate (reason required)
    GET  /api/v1/admin/fx-rates/preview             what amounts become at a proposed rate
    GET  /api/v1/admin/currency-settings            display and default currency
    PUT  /api/v1/admin/currency-settings
    GET  /api/v1/admin/country-profiles
    PUT  /api/v1/admin/country-profiles/{code}

    GET  /api/v1/countries                          (no sign-in) countries and their currency, for sign-up
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import RoleChecker
from src.auth.models import User
from src.auth.roles import Role
from src.billing.billing_models import CountryProfile, Currency, FxRate
from src.billing.currency import USD, Rate, UnknownCurrency, current_rate, to_ccy
from src.common.admin_audit import record_admin_change
from src.common.settings_store import get_platform_setting, set_platform_setting
from src.common.tenancy.session import get_control_db

router = APIRouter(prefix="/api/v1", tags=["Currency & FX"])
staff = RoleChecker([Role.APP_ADMIN])

# An effective time a little in the past is "now" (a form's clock); further back
# would re-price events already priced (FX-6).
_CLOCK_SKEW = timedelta(minutes=5)
PREVIEW_AMOUNTS_USD = (Decimal("1"), Decimal("20"), Decimal("100"))


def _rate_dict(row: FxRate) -> Dict[str, Any]:
    return {"id": str(row.id), "currency": row.currency, "units_per_usd": float(row.units_per_usd),
            "effective_from": row.effective_from.isoformat() if row.effective_from else None,
            "created_by": str(row.created_by) if row.created_by else None, "reason": row.reason,
            "created_at": row.created_at.isoformat() if row.created_at else None}


async def _currency(db: AsyncSession, code: str) -> Currency:
    row = (await db.execute(select(Currency).where(Currency.code == code.upper()))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown currency {code!r}")
    return row


@router.get("/admin/currencies")
async def list_currencies(db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    rows = (await db.execute(select(Currency).order_by(Currency.code))).scalars().all()
    out = []
    for c in rows:
        try:
            rate = await current_rate(db, c.code)
            current = {"units_per_usd": float(rate.units_per_usd),
                       "effective_from": rate.effective_from.isoformat() if rate.effective_from else None}
        except UnknownCurrency:
            current = None
        out.append({"code": c.code, "name": c.name, "symbol": c.symbol, "minor_units": c.minor_units,
                    "active": c.active, "gateway": c.gateway, "current_rate": current})
    return out


@router.get("/admin/fx-rates")
async def list_fx_rates(
    currency: Optional[str] = Query(None, description="One currency; every currency when omitted"),
    db: AsyncSession = Depends(get_control_db),
    user: User = Depends(staff),
):
    query = select(FxRate).order_by(FxRate.effective_from.desc(), FxRate.created_at.desc())
    if currency:
        query = query.where(FxRate.currency == currency.upper())
    return [_rate_dict(r) for r in (await db.execute(query.limit(500))).scalars().all()]


class FxRateCreate(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    units_per_usd: Decimal = Field(gt=0)
    effective_from: Optional[datetime] = None
    reason: str = Field(min_length=3, max_length=500)


@router.post("/admin/fx-rates", status_code=201)
async def add_fx_rate(body: FxRateCreate, db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    """Add a rate (FX-3): it applies to events from ``effective_from`` (now when omitted)."""
    code = body.currency.upper()
    if code == USD:
        raise HTTPException(status_code=422, detail="USD is always 1: costs are computed in USD")
    await _currency(db, code)
    now = datetime.utcnow()
    effective = body.effective_from.replace(tzinfo=None) if body.effective_from else now
    if effective < now - _CLOCK_SKEW:
        raise HTTPException(status_code=422, detail="a rate cannot start in the past: events already priced keep "
                                                    "the rate they used (FX-6)")
    try:
        old = await current_rate(db, code)
        old_value = {"units_per_usd": str(old.units_per_usd), "fx_rate_id": str(old.id) if old.id else None}
    except UnknownCurrency:
        old_value = None
    row = FxRate(currency=code, units_per_usd=body.units_per_usd, effective_from=effective,
                 created_by=getattr(user, "id", None), reason=body.reason)
    db.add(row)
    await db.flush()
    record_admin_change(db, actor=user, action="set", object_type="fx_rate", object_key=code, old_value=old_value,
                        new_value={"units_per_usd": str(body.units_per_usd), "fx_rate_id": str(row.id),
                                   "effective_from": effective.isoformat()}, reason=body.reason)
    await db.commit()
    await db.refresh(row)
    return _rate_dict(row)


@router.get("/admin/fx-rates/preview")
async def preview_fx_rate(
    currency: str = Query(..., min_length=3, max_length=3),
    units_per_usd: Decimal = Query(..., gt=0),
    db: AsyncSession = Depends(get_control_db),
    user: User = Depends(staff),
):
    """What sample USD amounts are in ``currency`` today and at the proposed rate (07 §5.6)."""
    code = currency.upper()
    await _currency(db, code)
    current = await current_rate(db, code)
    proposed = Rate(code, units_per_usd)
    return {"currency": code, "current_units_per_usd": float(current.units_per_usd),
            "proposed_units_per_usd": float(units_per_usd),
            "change_pct": float((units_per_usd - current.units_per_usd) / current.units_per_usd * 100),
            "examples": [{"usd": float(a), "current": float(to_ccy(a, current)), "proposed": float(to_ccy(a, proposed))}
                         for a in PREVIEW_AMOUNTS_USD]}


class CurrencySettings(BaseModel):
    display_currency: Optional[str] = Field(None, min_length=3, max_length=3)
    default_currency: Optional[str] = Field(None, min_length=3, max_length=3)
    reason: Optional[str] = None


@router.get("/admin/currency-settings")
async def get_currency_settings(db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    return {"display_currency": await get_platform_setting(db, "billing.display_currency"),
            "default_currency": await get_platform_setting(db, "billing.default_currency")}


@router.put("/admin/currency-settings")
async def put_currency_settings(body: CurrencySettings, db: AsyncSession = Depends(get_control_db),
                                user: User = Depends(staff)):
    """REQ-BL-4 (what staff views show) and REQ-BL-2 (a country with no profile)."""
    for field in ("display_currency", "default_currency"):
        value = getattr(body, field)
        if value is None:
            continue
        currency = await _currency(db, value)
        if not currency.active:
            raise HTTPException(status_code=422, detail=f"{currency.code} is not active")
        await set_platform_setting(db, f"billing.{field}", currency.code, actor=user, reason=body.reason)
    await db.commit()
    return await get_currency_settings(db, user)


def _profile_dict(p: CountryProfile) -> Dict[str, Any]:
    return {"country_code": p.country_code, "name": p.name, "billing_currency": p.billing_currency,
            "default_timezone": p.default_timezone, "phone_country_code": p.phone_country_code,
            "tax_regime": p.tax_regime, "calling_rules": p.calling_rules or {}}


@router.get("/admin/country-profiles")
async def list_country_profiles(db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    rows = (await db.execute(select(CountryProfile).order_by(CountryProfile.name))).scalars().all()
    return [_profile_dict(p) for p in rows]


class CountryProfileUpdate(BaseModel):
    billing_currency: Optional[str] = Field(None, min_length=3, max_length=3)
    default_timezone: Optional[str] = None
    phone_country_code: Optional[str] = Field(None, pattern=r"^\+[0-9]{1,4}$")
    tax_regime: Optional[str] = Field(None, pattern=r"^(IN_GST|EXPORT|NONE)$")
    calling_rules: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None


@router.put("/admin/country-profiles/{country_code}")
async def put_country_profile(country_code: str, body: CountryProfileUpdate,
                              db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    """A country's defaults for companies made **after** the change; existing ones keep theirs (FX-1)."""
    profile = (await db.execute(select(CountryProfile).where(
        CountryProfile.country_code == country_code.upper()))).scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail=f"unknown country {country_code!r}")
    changes = body.model_dump(exclude_unset=True, exclude={"reason"})
    if "billing_currency" in changes:
        changes["billing_currency"] = (await _currency(db, changes["billing_currency"])).code
    if changes.get("default_timezone"):
        from src.common.timezones import is_valid_timezone
        if not is_valid_timezone(changes["default_timezone"]):
            raise HTTPException(status_code=422, detail="not an IANA time zone")
    old = _profile_dict(profile)
    for field, value in changes.items():
        setattr(profile, field, value)
    profile.updated_at = datetime.utcnow()
    record_admin_change(db, actor=user, action="set", object_type="country_profile", object_key=profile.country_code,
                        old_value={k: old[k] for k in changes}, new_value=changes, reason=body.reason)
    await db.commit()
    return _profile_dict(profile)


@router.get("/countries")
async def list_countries(db: AsyncSession = Depends(get_control_db)):
    """Every country with its billing currency — the sign-up and company forms' list (T2-3).
    No sign-in: names and currencies only."""
    rows = (await db.execute(select(CountryProfile.country_code, CountryProfile.name, CountryProfile.billing_currency)
                             .order_by(CountryProfile.name))).all()
    return [{"code": r.country_code, "name": r.name, "currency": r.billing_currency} for r in rows]
