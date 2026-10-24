"""Plans and entitlements (Phase 15 T6-1, T6-2; tech design §10.2, §12.1, §15).

The company:

    GET  /api/v1/plans                                   the plans on offer, priced in its currency, with what each includes
    GET  /api/v1/me/entitlements                         its plan and every feature and limit it has

Staff (``app_admin``; every write audited):

    GET  /api/v1/admin/plans                             every plan, archived too, with subscribers and tolerance
    POST /api/v1/admin/plans                             a new plan
    PUT  /api/v1/admin/plans/{id}                        a change (a new version when the price, bonus or name changes)
    POST /api/v1/admin/plans/{id}/archive                no new subscribers; existing ones keep it
    GET  /api/v1/admin/plans/{id}/versions
    GET  /api/v1/admin/features                          the catalogue
    GET  /api/v1/admin/plans/entitlements                the matrix: plan × feature
    PUT  /api/v1/admin/plans/{id}/entitlements           {entitlements: [{feature_key, enabled, limit_value}], reason}
    POST /api/v1/admin/plans/{id}/entitlements/impact    what the change would take from companies on the plan
    GET  /api/v1/admin/companies/{id}/entitlements       one company's, with sources
    PUT  /api/v1/admin/companies/{id}/entitlements/{key} {enabled, limit_value, until, reason}
    DELETE /api/v1/admin/companies/{id}/entitlements/{key}
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import RoleChecker
from src.auth.models import Company, User
from src.auth.roles import Role
from src.auth.router import get_current_user
from src.billing.billing_models import (
    CompanyEntitlementOverride, Plan, PlanEntitlement, PlanVersion, Subscription,
)
from src.billing.features import FEATURE, catalogue, entitlements_for, forget as forget_entitlements
from src.billing.plans import PlanProblem, plan_id_of, price_in, save_plan
from src.common.tenancy.session import get_control_db

router = APIRouter(tags=["Plans"])
staff = RoleChecker([Role.APP_ADMIN])
CODE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


def _ent_view(ent) -> dict:
    return {"enabled": ent.enabled, "limit": ent.limit, "source": ent.source}


async def _plan_matrix(db: AsyncSession) -> Dict[UUID, Dict[str, dict]]:
    """Every plan's entitlements, the catalogue's defaults filled in."""
    specs = catalogue()
    plans = (await db.execute(select(Plan.id))).scalars().all()
    out = {pid: {k: {"enabled": True, "limit": s.default_limit} for k, s in specs.items()} for pid in plans}
    for row in (await db.execute(select(PlanEntitlement))).scalars().all():
        if row.plan_id in out and row.feature_key in specs:
            out[row.plan_id][row.feature_key] = {"enabled": row.enabled, "limit": row.limit_value}
    return out


async def _tolerance(db: AsyncSession, plan_id: UUID) -> Optional[str]:
    from src.common.settings_store import read_values

    values = await read_values(db, "wallet.negative_tolerance_usd", [("plan", plan_id)])
    value = values.get(("plan", plan_id))
    return None if value is None else str(value)


async def _subscribers(db: AsyncSession) -> Dict[UUID, int]:
    from src.billing.payment_service import LIVE_SUBSCRIPTION_STATUSES

    return dict((await db.execute(select(Subscription.plan_id, func.count()).where(
        Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES)).group_by(Subscription.plan_id))).all())


def _plan_view(plan: Plan) -> dict:
    return {"id": str(plan.id), "code": plan.code, "name": plan.name, "tier_level": plan.tier_level,
            "monthly_fee_usd": str(plan.monthly_fee_usd), "bonus_pct": str(plan.bonus_pct),
            "currency_overrides": plan.currency_overrides or {}, "active": plan.active, "sort": plan.sort,
            "version": plan.version, "updated_at": plan.updated_at.isoformat() if plan.updated_at else None}


# ── the company ────────────────────────────────────────────────────────────

@router.get("/api/v1/plans", summary="The plans on offer, in the company's currency")
async def list_plans(db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    from src.billing.tax import tax_for

    company = await db.get(Company, user.company_id)
    currency = company.billing_currency if company else "INR"
    current = await plan_id_of(db, user.company_id)
    matrix = await _plan_matrix(db)
    tax = await tax_for(db, company) if company else None
    plans = (await db.execute(select(Plan).where((Plan.active.is_(True)) | (Plan.id == current))
                              .order_by(Plan.sort, Plan.tier_level))).scalars().all()
    out = []
    for plan in plans:
        price = await price_in(db, plan, currency)
        out.append({**{k: v for k, v in _plan_view(plan).items() if k not in ("currency_overrides", "monthly_fee_usd")},
                    "currency": currency, "monthly_fee": str(price.net),
                    "tax_rate": str(tax.rate) if tax else "0", "current": plan.id == current,
                    "entitlements": matrix.get(plan.id, {})})
    return {"currency": currency, "current_plan_id": str(current) if current else None, "plans": out,
            "features": [{"key": s.key, "group": s.group, "label": s.label, "kind": s.kind}
                         for s in catalogue().values()]}


@router.get("/api/v1/me/entitlements", summary="The company's plan and entitlements")
async def my_entitlements(db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    plan_id = await plan_id_of(db, user.company_id)
    plan = await db.get(Plan, plan_id) if plan_id else None
    ents = await entitlements_for(db, user.company_id)
    return {"plan": {"id": str(plan.id), "code": plan.code, "name": plan.name, "tier_level": plan.tier_level}
            if plan else None,
            "entitlements": {k: _ent_view(e) for k, e in ents.items()}}


# ── staff: plans ───────────────────────────────────────────────────────────

class PlanBody(BaseModel):
    code: Optional[str] = Field(None, max_length=40)
    name: Optional[str] = Field(None, min_length=2, max_length=80)
    tier_level: Optional[int] = Field(None, ge=0, le=100)
    monthly_fee_usd: Optional[Decimal] = Field(None, ge=0, decimal_places=4)
    bonus_pct: Optional[Decimal] = Field(None, ge=0, le=100, decimal_places=4)
    currency_overrides: Optional[Dict[str, Optional[Decimal]]] = None
    active: Optional[bool] = None
    sort: Optional[int] = None
    negative_tolerance_usd: Optional[Decimal] = Field(None, ge=0, decimal_places=4)
    reason: Optional[str] = Field(None, max_length=500)


async def _set_tolerance(db: AsyncSession, plan: Plan, value: Optional[Decimal], user: User,
                         reason: Optional[str]) -> None:
    from src.common.settings_store import set_setting

    if value is not None:
        await set_setting(db, "wallet.negative_tolerance_usd", str(value), scope="plan", scope_id=plan.id,
                          actor=user, reason=reason or f"tolerance of {plan.name}")


@router.get("/api/v1/admin/plans")
async def admin_plans(db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    subscribers = await _subscribers(db)
    payg_companies = (await db.execute(select(func.count()).select_from(Company).where(
        Company.type == "TENANT", Company.status == "active"))).scalar() or 0
    rows = (await db.execute(select(Plan).order_by(Plan.sort, Plan.tier_level))).scalars().all()
    out = []
    for plan in rows:
        count = subscribers.get(plan.id, 0)
        if plan.tier_level == 0:
            count = max(payg_companies - sum(subscribers.values()), 0)
        out.append({**_plan_view(plan), "companies": count, "negative_tolerance_usd": await _tolerance(db, plan.id),
                    "prices": {c: str((await price_in(db, plan, c)).net) for c in ("INR", "USD")}})
    return out


@router.post("/api/v1/admin/plans", status_code=201)
async def create_plan(body: PlanBody, db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    if not body.code or not CODE.match(body.code) or not body.name or body.tier_level is None:
        raise HTTPException(status_code=422, detail="a plan needs a code (a-z, 0-9, _), a name and a level")
    if (await db.execute(select(Plan.id).where((Plan.code == body.code) | (Plan.tier_level == body.tier_level)))
            ).first() is not None:
        raise HTTPException(status_code=409, detail="a plan with that code or level exists")
    try:
        plan = await save_plan(db, actor=user, reason=body.reason, **body.model_dump(
            exclude={"reason", "negative_tolerance_usd"}, exclude_none=True))
    except PlanProblem as problem:
        raise HTTPException(status_code=422, detail=str(problem)) from None
    await _set_tolerance(db, plan, body.negative_tolerance_usd, user, body.reason)
    await db.commit()
    return _plan_view(plan)


@router.put("/api/v1/admin/plans/{plan_id}")
async def update_plan(plan_id: UUID, body: PlanBody, db: AsyncSession = Depends(get_control_db),
                      user: User = Depends(staff)):
    if body.tier_level is not None:
        clash = (await db.execute(select(Plan.id).where(Plan.tier_level == body.tier_level, Plan.id != plan_id))
                 ).first()
        if clash is not None:
            raise HTTPException(status_code=409, detail="another plan has that level")
    try:
        plan = await save_plan(db, actor=user, reason=body.reason, plan_id=plan_id, **body.model_dump(
            exclude={"reason", "negative_tolerance_usd", "code"}, exclude_none=True))
    except LookupError:
        raise HTTPException(status_code=404, detail="no such plan") from None
    except PlanProblem as problem:
        raise HTTPException(status_code=422, detail=str(problem)) from None
    await _set_tolerance(db, plan, body.negative_tolerance_usd, user, body.reason)
    await db.commit()
    from src.billing.plans import forget
    forget()
    return _plan_view(plan)


@router.post("/api/v1/admin/plans/{plan_id}/archive")
async def archive_plan(plan_id: UUID, reason: Optional[str] = None, db: AsyncSession = Depends(get_control_db),
                       user: User = Depends(staff)):
    try:
        plan = await save_plan(db, actor=user, reason=reason or "archived", plan_id=plan_id, active=False)
    except LookupError:
        raise HTTPException(status_code=404, detail="no such plan") from None
    except PlanProblem as problem:
        raise HTTPException(status_code=422, detail=str(problem)) from None
    await db.commit()
    return _plan_view(plan)


@router.get("/api/v1/admin/plans/{plan_id}/versions")
async def plan_versions(plan_id: UUID, db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    rows = (await db.execute(select(PlanVersion).where(PlanVersion.plan_id == plan_id)
                             .order_by(PlanVersion.version.desc()))).scalars().all()
    return [{"version": v.version, "name": v.name, "monthly_fee_usd": str(v.monthly_fee_usd),
             "bonus_pct": str(v.bonus_pct), "currency_overrides": v.currency_overrides or {}, "active": v.active,
             "reason": v.reason, "created_at": v.created_at.isoformat() if v.created_at else None} for v in rows]


# ── staff: entitlements ────────────────────────────────────────────────────

@router.get("/api/v1/admin/features")
async def features(user: User = Depends(staff)):
    return [{"key": s.key, "group": s.group, "label": s.label, "kind": s.kind, "default_limit": s.default_limit,
             "limit_label": s.limit_label} for s in catalogue().values()]


@router.get("/api/v1/admin/plans/entitlements")
async def entitlement_matrix(db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    return {str(pid): ents for pid, ents in (await _plan_matrix(db)).items()}


class EntitlementItem(BaseModel):
    feature_key: str
    enabled: bool = True
    limit_value: Optional[int] = Field(None, ge=0)


class EntitlementsBody(BaseModel):
    entitlements: List[EntitlementItem]
    reason: Optional[str] = Field(None, max_length=500)


def _check_keys(items: List[EntitlementItem]) -> None:
    specs = catalogue()
    unknown = sorted({i.feature_key for i in items} - set(specs))
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown features: {', '.join(unknown)}")


async def _companies_on(db: AsyncSession, plan: Plan) -> int:
    subscribers = await _subscribers(db)
    if plan.tier_level != 0:
        return subscribers.get(plan.id, 0)
    total = (await db.execute(select(func.count()).select_from(Company).where(
        Company.type == "TENANT", Company.status == "active"))).scalar() or 0
    return max(total - sum(subscribers.values()), 0)


async def _impact(db: AsyncSession, plan: Plan, items: List[EntitlementItem]) -> List[dict]:
    """What turning features off or lowering limits takes from the plan's companies (07 §5.4)."""
    current = (await _plan_matrix(db))[plan.id]
    companies = await _companies_on(db, plan)
    out = []
    for item in items:
        before = current[item.feature_key]
        spec = catalogue()[item.feature_key]
        if before["enabled"] and not item.enabled:
            out.append({"feature_key": item.feature_key, "change": "loses", "companies": companies,
                        "text": f"{companies} compan{'y' if companies == 1 else 'ies'} on {plan.name} would lose "
                                f"{spec.label}"})
        elif item.limit_value is not None and (before["limit"] is None or item.limit_value < before["limit"]):
            out.append({"feature_key": item.feature_key, "change": "lower_limit", "companies": companies,
                        "text": f"{companies} compan{'y' if companies == 1 else 'ies'} on {plan.name} would be "
                                f"limited to {item.limit_value} ({spec.limit_label or spec.label})"})
    return out


@router.post("/api/v1/admin/plans/{plan_id}/entitlements/impact")
async def entitlement_impact(plan_id: UUID, body: EntitlementsBody, db: AsyncSession = Depends(get_control_db),
                             user: User = Depends(staff)):
    plan = await db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="no such plan")
    _check_keys(body.entitlements)
    return {"impact": await _impact(db, plan, body.entitlements)}


@router.put("/api/v1/admin/plans/{plan_id}/entitlements")
async def put_entitlements(plan_id: UUID, body: EntitlementsBody, db: AsyncSession = Depends(get_control_db),
                           user: User = Depends(staff)):
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from src.common.admin_audit import record_admin_change

    plan = await db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="no such plan")
    _check_keys(body.entitlements)
    impact = await _impact(db, plan, body.entitlements)
    before = (await _plan_matrix(db))[plan.id]
    for item in body.entitlements:
        spec = catalogue()[item.feature_key]
        limit = item.limit_value if (spec.kind != FEATURE or spec.limit_label) else None
        stmt = pg_insert(PlanEntitlement).values(plan_id=plan.id, feature_key=item.feature_key, enabled=item.enabled,
                                                 limit_value=limit, updated_by=user.id, updated_at=datetime.utcnow())
        await db.execute(stmt.on_conflict_do_update(
            index_elements=["plan_id", "feature_key"],
            set_={"enabled": stmt.excluded.enabled, "limit_value": stmt.excluded.limit_value,
                  "updated_by": stmt.excluded.updated_by, "updated_at": stmt.excluded.updated_at}))
    record_admin_change(db, actor=user, action="set", object_type="plan_entitlements", object_key=plan.code,
                        old_value={i.feature_key: before[i.feature_key] for i in body.entitlements},
                        new_value={i.feature_key: {"enabled": i.enabled, "limit": i.limit_value}
                                   for i in body.entitlements}, reason=body.reason)
    await db.commit()
    forget_entitlements()
    return {"plan_id": str(plan.id), "entitlements": (await _plan_matrix(db))[plan.id], "impact": impact}


@router.get("/api/v1/admin/companies/{company_id}/entitlements")
async def company_entitlements(company_id: UUID, db: AsyncSession = Depends(get_control_db),
                               user: User = Depends(staff)):
    if await db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="no such company")
    forget_entitlements(company_id)
    ents = await entitlements_for(db, company_id)
    overrides = (await db.execute(select(CompanyEntitlementOverride).where(
        CompanyEntitlementOverride.company_id == company_id))).scalars().all()
    return {"entitlements": {k: _ent_view(e) for k, e in ents.items()},
            "overrides": [{"feature_key": o.feature_key, "enabled": o.enabled, "limit_value": o.limit_value,
                           "until": o.until.isoformat() if o.until else None, "reason": o.reason} for o in overrides]}


class OverrideBody(BaseModel):
    enabled: bool = True
    limit_value: Optional[int] = Field(None, ge=0)
    until: Optional[datetime] = None
    reason: str = Field(..., min_length=3, max_length=500)


@router.put("/api/v1/admin/companies/{company_id}/entitlements/{key}")
async def put_company_entitlement(company_id: UUID, key: str, body: OverrideBody,
                                  db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    from src.common.admin_audit import record_admin_change

    if key not in catalogue():
        raise HTTPException(status_code=404, detail=f"unknown feature {key!r}")
    if await db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="no such company")
    row = await db.get(CompanyEntitlementOverride, (company_id, key))
    old = None if row is None else {"enabled": row.enabled, "limit_value": row.limit_value}
    if row is None:
        row = CompanyEntitlementOverride(company_id=company_id, feature_key=key)
        db.add(row)
    row.enabled, row.limit_value, row.until = body.enabled, body.limit_value, body.until
    row.reason, row.set_by, row.updated_at = body.reason, user.id, datetime.utcnow()
    record_admin_change(db, actor=user, action="set", object_type="company_entitlement", object_key=key,
                        target_company_id=company_id, old_value=old,
                        new_value={"enabled": body.enabled, "limit_value": body.limit_value}, reason=body.reason)
    await db.commit()
    forget_entitlements(company_id)
    return {"feature_key": key, "enabled": row.enabled, "limit_value": row.limit_value}


@router.delete("/api/v1/admin/companies/{company_id}/entitlements/{key}")
async def delete_company_entitlement(company_id: UUID, key: str, reason: Optional[str] = None,
                                     db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    from src.common.admin_audit import record_admin_change

    result = await db.execute(delete(CompanyEntitlementOverride).where(
        CompanyEntitlementOverride.company_id == company_id, CompanyEntitlementOverride.feature_key == key))
    if result.rowcount:
        record_admin_change(db, actor=user, action="delete", object_type="company_entitlement", object_key=key,
                            target_company_id=company_id, reason=reason)
    await db.commit()
    forget_entitlements(company_id)
    return {"feature_key": key, "removed": bool(result.rowcount)}
