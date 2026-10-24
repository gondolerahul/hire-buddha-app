"""Fixed prices, for staff (Phase 15 T5-3, T5-6; tech design §8.3, O-2).

    GET /api/v1/admin/price-items                 every item: USD amount, overrides, the price per active currency today
    GET /api/v1/admin/price-items/{code}/versions every version it has had
    PUT /api/v1/admin/price-items/{code}          {amount_usd, currency_overrides, active, reason}: a new version

Only ``app_admin``; each edit is audited and kept as a version.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import RoleChecker
from src.auth.models import User
from src.auth.roles import Role
from src.billing.billing_models import Currency, PriceItem, PriceItemVersion
from src.billing.price_items import UnknownPriceItem, price_for, set_price_item
from src.common.tenancy.session import get_control_db

router = APIRouter(prefix="/api/v1/admin/price-items", tags=["Pricing"])
staff = RoleChecker([Role.APP_ADMIN])


async def _view(db: AsyncSession, item: PriceItem, currencies: list) -> dict:
    prices = {}
    for code in currencies:
        try:
            p = await price_for(db, item.code, code) if item.active else None
        except Exception:  # noqa: BLE001 - a currency with no rate shows no price
            p = None
        if p is not None:
            prices[code] = {"amount": str(p.amount), "overridden": p.overridden}
    return {"code": item.code, "name": item.name, "kind": item.kind, "interval": item.interval,
            "amount_usd": str(item.amount_usd), "currency_overrides": item.currency_overrides or {},
            "taxable": item.taxable, "active": item.active, "version": item.version,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None, "prices": prices}


@router.get("")
async def list_price_items(db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    currencies = list((await db.execute(select(Currency.code).where(Currency.active.is_(True))
                                        .order_by(Currency.code))).scalars().all())
    items = (await db.execute(select(PriceItem).order_by(PriceItem.code))).scalars().all()
    return [await _view(db, item, currencies) for item in items]


@router.get("/{code}/versions")
async def price_item_versions(code: str, db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    rows = (await db.execute(select(PriceItemVersion).where(PriceItemVersion.code == code)
                             .order_by(PriceItemVersion.version.desc()))).scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="no such price item")
    return [{"version": v.version, "amount_usd": str(v.amount_usd), "currency_overrides": v.currency_overrides or {},
             "active": v.active, "reason": v.reason, "created_by": str(v.created_by) if v.created_by else None,
             "created_at": v.created_at.isoformat() if v.created_at else None} for v in rows]


class PriceItemBody(BaseModel):
    amount_usd: Decimal = Field(..., ge=0, decimal_places=4)
    currency_overrides: Dict[str, Optional[Decimal]] = Field(default_factory=dict)
    active: bool = True
    name: Optional[str] = Field(None, min_length=2, max_length=120)
    reason: Optional[str] = Field(None, max_length=500)

    @field_validator("currency_overrides")
    @classmethod
    def _overrides(cls, value: Dict[str, Optional[Decimal]]) -> Dict[str, Optional[Decimal]]:
        for code, amount in value.items():
            if len(code) != 3 or not code.isalpha():
                raise ValueError(f"{code!r} is not a currency code")
            if amount is not None and amount < 0:
                raise ValueError(f"the {code.upper()} price is not negative")
        return value


@router.put("/{code}")
async def put_price_item(code: str, body: PriceItemBody, db: AsyncSession = Depends(get_control_db),
                         user: User = Depends(staff)):
    known = set((await db.execute(select(Currency.code))).scalars().all())
    unknown = sorted({c.upper() for c in body.currency_overrides} - known)
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown currencies: {', '.join(unknown)}")
    try:
        item = await set_price_item(db, code, amount_usd=body.amount_usd, currency_overrides=body.currency_overrides,
                                    active=body.active, actor=user, reason=body.reason, name=body.name)
    except UnknownPriceItem:
        raise HTTPException(status_code=404, detail="no such price item") from None
    await db.commit()
    currencies = list((await db.execute(select(Currency.code).where(Currency.active.is_(True))
                                        .order_by(Currency.code))).scalars().all())
    return await _view(db, item, currencies)
