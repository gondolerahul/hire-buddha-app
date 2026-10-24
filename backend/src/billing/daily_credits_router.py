"""Daily credits, for staff (Phase 15 T5-5, T5-6; tech design §7, DC-1: app_admin only).

    GET    /api/v1/admin/daily-credits/policies                  every policy with its bands
    POST   /api/v1/admin/daily-credits/policies                  {name, audience, partner_id?, duration_days, bands, active}
    PUT    /api/v1/admin/daily-credits/policies/{id}             the same fields; applies from the next local midnight (DC-6)
    DELETE /api/v1/admin/daily-credits/policies/{id}             deactivates it
    POST   /api/v1/admin/daily-credits/preview                   {duration_days, bands, currency} → the amount per day range
    GET    /api/v1/admin/daily-credits/overrides                 every company override
    PUT    /api/v1/admin/daily-credits/overrides/{company_id}    {mode, amount_usd?, duration_days?, until?, reason}
    DELETE /api/v1/admin/daily-credits/overrides/{company_id}
    GET    /api/v1/admin/daily-credits/companies/{company_id}    what the company gets today, and why

Every write is audited (``admin_audit_log``, object type ``daily_credit_policy`` / ``daily_credit_override``).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import RoleChecker
from src.auth.models import Company, User
from src.auth.roles import Role
from src.billing.billing_models import CompanyDailyCreditOverride, DailyCreditBand, DailyCreditPolicy
from src.billing.daily_credits import AUDIENCES, DURATIONS
from src.common.tenancy.session import get_control_db

router = APIRouter(prefix="/api/v1/admin/daily-credits", tags=["Daily credits"])
staff = RoleChecker([Role.APP_ADMIN])


class Band(BaseModel):
    from_day: int = Field(..., ge=1)
    to_day: int = Field(..., ge=1)
    amount_usd: Decimal = Field(..., ge=0, decimal_places=4)


def _check_bands(bands: List[Band], duration_days: Optional[int]) -> None:
    previous = 0
    for band in sorted(bands, key=lambda b: b.from_day):
        if band.to_day < band.from_day:
            raise ValueError(f"band {band.from_day}–{band.to_day} ends before it starts")
        if band.from_day <= previous:
            raise ValueError(f"bands overlap at day {band.from_day}")
        previous = band.to_day
    if duration_days is not None and bands and max(b.to_day for b in bands) > max(duration_days, 1) \
            and duration_days != 0:
        raise ValueError(f"a band runs past the policy's {duration_days} days")


class PolicyBody(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    audience: str
    partner_id: Optional[UUID] = None
    duration_days: Optional[int] = None
    active: bool = True
    bands: List[Band] = Field(default_factory=list)
    reason: Optional[str] = None

    @model_validator(mode="after")
    def _valid(self) -> "PolicyBody":
        if self.audience not in AUDIENCES:
            raise ValueError(f"audience is one of {', '.join(AUDIENCES)}")
        if (self.audience == "partner") != (self.partner_id is not None):
            raise ValueError("a partner policy names its partner; other audiences do not")
        if self.duration_days is not None and self.duration_days not in DURATIONS:
            raise ValueError(f"duration_days is one of {', '.join(map(str, DURATIONS))}")
        if self.duration_days is None:
            raise ValueError("duration_days is required (policies with no end are only the migrated ones)")
        _check_bands(self.bands, self.duration_days)
        return self


def _policy_view(policy: DailyCreditPolicy, bands: list) -> dict:
    return {"id": str(policy.id), "name": policy.name, "audience": policy.audience,
            "partner_id": str(policy.partner_id) if policy.partner_id else None,
            "duration_days": policy.duration_days, "active": policy.active,
            "effective_from": policy.effective_from.isoformat() if policy.effective_from else None,
            "updated_at": policy.updated_at.isoformat() if policy.updated_at else None,
            "bands": [{"from_day": b.from_day, "to_day": b.to_day, "amount_usd": str(b.amount_usd)}
                      for b in sorted(bands, key=lambda b: b.from_day)]}


async def _bands(db: AsyncSession, policy_id: UUID) -> list:
    return list((await db.execute(select(DailyCreditBand).where(DailyCreditBand.policy_id == policy_id))
                 ).scalars().all())


async def _check_partner(db: AsyncSession, partner_id: Optional[UUID]) -> None:
    if partner_id is None:
        return
    kind = (await db.execute(select(Company.type).where(Company.id == partner_id))).scalar_one_or_none()
    if kind != "PARTNER":
        raise HTTPException(status_code=422, detail="partner_id is not a partner")


async def _one_active(db: AsyncSession, body: PolicyBody, exclude: Optional[UUID] = None) -> None:
    """One active policy per audience (and partner): the resolver takes one."""
    if not body.active:
        return
    query = select(DailyCreditPolicy.id).where(DailyCreditPolicy.audience == body.audience,
                                               DailyCreditPolicy.active.is_(True))
    query = query.where(DailyCreditPolicy.partner_id == body.partner_id) if body.partner_id else query
    if exclude is not None:
        query = query.where(DailyCreditPolicy.id != exclude)
    if (await db.execute(query)).first() is not None:
        raise HTTPException(status_code=409, detail=(
            f"an active {body.audience} policy exists already; deactivate it or edit it"))


@router.get("/policies")
async def list_policies(db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    policies = (await db.execute(select(DailyCreditPolicy).order_by(DailyCreditPolicy.audience,
                                                                     DailyCreditPolicy.name))).scalars().all()
    bands = (await db.execute(select(DailyCreditBand))).scalars().all()
    by_policy: dict = {}
    for band in bands:
        by_policy.setdefault(band.policy_id, []).append(band)
    partners = dict((await db.execute(select(Company.id, Company.name).where(Company.type == "PARTNER"))).all())
    return [{**_policy_view(p, by_policy.get(p.id, [])),
             "partner_name": partners.get(p.partner_id) if p.partner_id else None} for p in policies]


@router.post("/policies", status_code=201)
async def create_policy(body: PolicyBody, db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    from src.common.admin_audit import record_admin_change

    await _check_partner(db, body.partner_id)
    await _one_active(db, body)
    policy = DailyCreditPolicy(name=body.name, audience=body.audience, partner_id=body.partner_id,
                               duration_days=body.duration_days, active=body.active, created_by=user.id)
    db.add(policy)
    await db.flush()
    for band in body.bands:
        db.add(DailyCreditBand(policy_id=policy.id, from_day=band.from_day, to_day=band.to_day,
                               amount_usd=band.amount_usd))
    await db.flush()
    view = _policy_view(policy, await _bands(db, policy.id))
    record_admin_change(db, actor=user, action="create", object_type="daily_credit_policy", object_key=str(policy.id),
                        new_value=view, reason=body.reason)
    await db.commit()
    return view


@router.put("/policies/{policy_id}")
async def update_policy(policy_id: UUID, body: PolicyBody, db: AsyncSession = Depends(get_control_db),
                        user: User = Depends(staff)):
    from src.common.admin_audit import record_admin_change

    policy = await db.get(DailyCreditPolicy, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="no such policy")
    await _check_partner(db, body.partner_id)
    await _one_active(db, body, exclude=policy_id)
    old = _policy_view(policy, await _bands(db, policy_id))
    policy.name, policy.audience, policy.partner_id = body.name, body.audience, body.partner_id
    policy.duration_days, policy.active, policy.updated_at = body.duration_days, body.active, datetime.utcnow()
    await db.execute(delete(DailyCreditBand).where(DailyCreditBand.policy_id == policy_id))
    for band in body.bands:
        db.add(DailyCreditBand(policy_id=policy_id, from_day=band.from_day, to_day=band.to_day,
                               amount_usd=band.amount_usd))
    await db.flush()
    view = _policy_view(policy, await _bands(db, policy_id))
    record_admin_change(db, actor=user, action="update", object_type="daily_credit_policy", object_key=str(policy_id),
                        old_value=old, new_value=view, reason=body.reason)
    await db.commit()
    return view


@router.delete("/policies/{policy_id}")
async def deactivate_policy(policy_id: UUID, reason: Optional[str] = None, db: AsyncSession = Depends(get_control_db),
                            user: User = Depends(staff)):
    from src.common.admin_audit import record_admin_change

    policy = await db.get(DailyCreditPolicy, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="no such policy")
    policy.active, policy.updated_at = False, datetime.utcnow()
    record_admin_change(db, actor=user, action="deactivate", object_type="daily_credit_policy",
                        object_key=str(policy_id), old_value={"active": True}, new_value={"active": False},
                        reason=reason)
    await db.commit()
    return {"id": str(policy_id), "active": False}


class PreviewBody(BaseModel):
    duration_days: Optional[int] = None
    bands: List[Band] = Field(default_factory=list)
    currency: str = Field("INR", min_length=3, max_length=3)


@router.post("/preview")
async def preview_policy(body: PreviewBody, db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    from src.billing.currency import UnknownCurrency
    from src.billing.daily_credits import preview

    try:
        _check_bands(body.bands, body.duration_days)
        return {"currency": body.currency.upper(), "days": await preview(
            db, audience="direct", duration_days=body.duration_days,
            bands=[b.model_dump() for b in body.bands], currency=body.currency.upper())}
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except UnknownCurrency:
        raise HTTPException(status_code=422, detail=f"no FX rate for {body.currency}") from None


class OverrideBody(BaseModel):
    mode: str = Field(..., pattern="^(policy|custom|none)$")
    amount_usd: Optional[Decimal] = Field(None, ge=0, decimal_places=4)
    duration_days: Optional[int] = Field(None, ge=0, le=3650)
    until: Optional[datetime] = None
    reason: str = Field(..., min_length=3, max_length=500)

    @model_validator(mode="after")
    def _valid(self) -> "OverrideBody":
        if self.mode == "custom" and self.amount_usd is None:
            raise ValueError("a custom override gives an amount_usd")
        return self


def _override_view(o: CompanyDailyCreditOverride, name: Optional[str] = None) -> dict:
    return {"company_id": str(o.company_id), "company_name": name, "mode": o.mode,
            "amount_usd": str(o.amount_usd) if o.amount_usd is not None else None,
            "duration_days": o.duration_days, "until": o.until.isoformat() if o.until else None,
            "reason": o.reason, "updated_at": o.updated_at.isoformat() if o.updated_at else None}


@router.get("/overrides")
async def list_overrides(db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    rows = (await db.execute(select(CompanyDailyCreditOverride, Company.name)
                             .join(Company, Company.id == CompanyDailyCreditOverride.company_id)
                             .order_by(Company.name))).all()
    return [_override_view(o, name) for o, name in rows]


@router.put("/overrides/{company_id}")
async def put_override(company_id: UUID, body: OverrideBody, db: AsyncSession = Depends(get_control_db),
                       user: User = Depends(staff)):
    from src.common.admin_audit import record_admin_change

    name = (await db.execute(select(Company.name).where(Company.id == company_id))).scalar_one_or_none()
    if name is None:
        raise HTTPException(status_code=404, detail="no such company")
    row = await db.get(CompanyDailyCreditOverride, company_id)
    old = _override_view(row) if row else None
    if row is None:
        row = CompanyDailyCreditOverride(company_id=company_id, mode=body.mode)
        db.add(row)
    row.mode, row.amount_usd = body.mode, body.amount_usd if body.mode == "custom" else None
    row.duration_days, row.until, row.reason = body.duration_days, body.until, body.reason
    row.set_by, row.updated_at = user.id, datetime.utcnow()
    await db.flush()
    view = _override_view(row, name)
    record_admin_change(db, actor=user, action="set", object_type="daily_credit_override", object_key=str(company_id),
                        target_company_id=company_id, old_value=old, new_value=view, reason=body.reason)
    await db.commit()
    return view


@router.delete("/overrides/{company_id}")
async def delete_override(company_id: UUID, reason: Optional[str] = None, db: AsyncSession = Depends(get_control_db),
                          user: User = Depends(staff)):
    from src.common.admin_audit import record_admin_change

    row = await db.get(CompanyDailyCreditOverride, company_id)
    if row is None:
        return {"company_id": str(company_id), "removed": False}
    old = _override_view(row)
    await db.delete(row)
    record_admin_change(db, actor=user, action="delete", object_type="daily_credit_override",
                        object_key=str(company_id), target_company_id=company_id, old_value=old, reason=reason)
    await db.commit()
    return {"company_id": str(company_id), "removed": True}


@router.get("/companies/{company_id}")
async def company_daily_credits(company_id: UUID, db: AsyncSession = Depends(get_control_db),
                                user: User = Depends(staff)):
    from src.billing.currency import current_rate, to_ccy
    from src.billing.daily_credits import resolve

    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="no such company")
    resolution = await resolve(db, company)
    rate = await current_rate(db, company.billing_currency)
    return {"company_id": str(company_id), "company_name": company.name, "currency": company.billing_currency,
            "timezone": company.timezone, **resolution.as_dict(),
            "amount": str(to_ccy(resolution.amount_usd, rate))}
