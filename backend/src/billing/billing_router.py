"""
Billing Router — billing config management and reporting endpoints.
"""
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.tenancy.session import get_control_db
from src.auth.router import get_current_user
from src.auth.dependencies import RoleChecker
from src.auth.models import User
from src.billing.billing_service import BillingService
from src.billing.billing_models import BillingEvent, BillingConfig

router = APIRouter(prefix="/api/v1", tags=["Billing & Reports"])

# Both reports carry base_cost — what the platform pays providers. With the
# multiplier known that is the margin, so they are app_admin only. So is the
# billing config itself: reading it states the markup (BC-26), and writing it
# with company_id null sets every tenant's price (BC-19).
app_admin_only = RoleChecker(["app_admin"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class BillingConfigUpdate(BaseModel):
    # An unknown field (a typo, or the retired base_cost_llm) is a 422, not a no-op.
    model_config = ConfigDict(extra="forbid")

    # The price formula TB = c·mf·(1 + pf − d) (Phase 15 T3-2): a change is a new
    # version in billing_formulas. pf and d are fractions — 0.15 is 15% (BC-21).
    multiplier_factor: Optional[Decimal] = Field(None, gt=0, le=100)
    platform_fee_pct: Optional[Decimal] = Field(None, ge=0, le=1)
    discount_pct: Optional[Decimal] = Field(None, ge=0, le=1)
    # Retired (K-10): partners earn commission, not a share of the customer
    # price. Accepted only as 0, so an old form still saves.
    sales_partner_fee_pct: Optional[Decimal] = Field(None, ge=0, le=1)
    # Retired (T3-2): a company's own price is its registry row
    # (in-out / tata-tele-voice-in-out per minute, image_generation per image).
    base_cost_telephony: Optional[Decimal] = None
    base_cost_image_gen: Optional[Decimal] = None
    default_daily_credits: Optional[Decimal] = Field(None, ge=0)
    company_id: Optional[UUID] = None  # None = the platform's formula
    reason: Optional[str] = Field(None, max_length=500)


class BillingEventResponse(BaseModel):
    id: str
    company_id: str
    period_month: str
    grouping_type: Optional[str]
    grouping_value: Optional[str]
    base_cost: float
    multiplied_cost: float
    platform_fee_amount: float
    partner_fee_amount: float
    discount_amount: float
    total_billing: float
    telephony_charge: float
    llm_charge: float
    image_charge: float
    video_charge: float
    api_charge: float
    telephony_in_seconds: float
    telephony_out_seconds: float
    image_gen_count: int
    video_gen_count: int
    other_ai_cost: float

    class Config:
        from_attributes = True


def _event_to_dict(e: BillingEvent) -> dict:
    return {
        "id": str(e.id),
        "company_id": str(e.company_id),
        "company_name": e.company.name if "company" in e.__dict__ and e.company else None,
        "period_month": e.period_month.isoformat() if e.period_month else None,
        "grouping_type": e.grouping_type,
        "grouping_value": e.grouping_value,
        "base_cost": float(e.base_cost),
        "multiplied_cost": float(e.multiplied_cost),
        "platform_fee_amount": float(e.platform_fee_amount),
        "partner_fee_amount": float(e.partner_fee_amount),
        "discount_amount": float(e.discount_amount),
        "total_billing": float(e.total_billing),
        "telephony_charge": float(e.telephony_charge),
        "llm_charge": float(e.llm_charge),
        "image_charge": float(e.image_charge),
        "video_charge": float(e.video_charge),
        "api_charge": float(e.api_charge),
        "telephony_in_seconds": float(e.telephony_in_seconds),
        "telephony_out_seconds": float(e.telephony_out_seconds),
        "image_gen_count": e.image_gen_count,
        "video_gen_count": e.video_gen_count,
        "other_ai_cost": float(e.other_ai_cost),
    }


async def _config_view(db: AsyncSession, company_id: Optional[UUID]) -> dict:
    """The formula in effect (the company's, else the platform's), its versions, and daily credits."""
    from sqlalchemy import select

    from src.billing.billing_models import BillingFormula
    from src.billing.formulas import formula_for

    formula = await formula_for(db, company_id)
    scope_filter = (BillingFormula.scope_id == company_id) if company_id else BillingFormula.scope_id.is_(None)
    versions = (await db.execute(select(BillingFormula).where(
        BillingFormula.scope == ("company" if company_id else "platform"), scope_filter)
        .order_by(BillingFormula.effective_from.desc(), BillingFormula.created_at.desc()).limit(50))).scalars().all()
    daily = await BillingService(db).get_billing_config(company_id) if company_id else (await db.execute(
        select(BillingConfig).where(BillingConfig.company_id.is_(None), BillingConfig.is_active.is_(True))
    )).scalars().first()
    return {
        "config": {
            "company_id": str(company_id) if company_id else None,
            "formula_id": str(formula.id) if formula.id else None,
            "formula_scope": formula.scope,
            "multiplier_factor": float(formula.mf),
            "platform_fee_pct": float(formula.pf),
            "discount_pct": float(formula.d),
            "default_daily_credits": float(daily.default_daily_credits) if daily else 0.0,
        },
        "history": [{"id": str(v.id), "multiplier_factor": float(v.mf), "platform_fee_pct": float(v.pf),
                     "discount_pct": float(v.d), "active": v.active,
                     "effective_from": v.effective_from.isoformat() if v.effective_from else None,
                     "reason": v.reason, "created_by": str(v.created_by) if v.created_by else None}
                    for v in versions],
    }


# ─── Billing Config ──────────────────────────────────────────────────────────

@router.get("/billing/config", summary="The price formula and daily credits (app_admin)")
async def get_billing_config(
    company_id: Optional[UUID] = Query(None, description="A company's formula; omit for the platform's"),
    current_user: User = Depends(app_admin_only),
    db: AsyncSession = Depends(get_control_db),
):
    return await _config_view(db, company_id)


@router.put("/billing/config", summary="Change the price formula or daily credits (app_admin)")
async def update_billing_config(
    payload: BillingConfigUpdate,
    current_user: User = Depends(app_admin_only),
    db: AsyncSession = Depends(get_control_db),
):
    """A formula change is a new version (audited), in effect at once for new
    usage; a run already running keeps the formula it started with (T3-3)."""
    from src.billing.formulas import formula_for, set_formula

    fields = payload.model_dump(exclude_unset=True)
    if fields.get("sales_partner_fee_pct"):
        raise HTTPException(status_code=422, detail=(
            "sales_partner_fee_pct is retired: partners earn commission, not a share of the customer price "
            "(Phase 15 K-10). Put a fee for everyone in platform_fee_pct."))
    if fields.get("base_cost_telephony") is not None or fields.get("base_cost_image_gen") is not None:
        raise HTTPException(status_code=422, detail=(
            "Cost overrides are retired: set the company's own registry row instead "
            "(in-out / tata-tele-voice-in-out per minute, image_generation per image)."))
    formula_fields = {"multiplier_factor", "platform_fee_pct", "discount_pct"} & set(fields)
    if formula_fields:
        current = await formula_for(db, payload.company_id)
        await set_formula(
            db, scope="company" if payload.company_id else "platform", scope_id=payload.company_id,
            mf=fields.get("multiplier_factor", current.mf), pf=fields.get("platform_fee_pct", current.pf),
            d=fields.get("discount_pct", current.d), actor=current_user, reason=payload.reason)
        await db.commit()
    if "default_daily_credits" in fields:
        await BillingService(db).update_billing_config(
            payload.company_id, default_daily_credits=fields["default_daily_credits"])
    return await _config_view(db, payload.company_id)


# ─── Costing Report (Internal / Operational) ──────────────────────────────────

@router.get("/reports/costing", summary="Internal costing report (operational expenses)")
async def get_costing_report(
    period_month: Optional[date] = Query(None, description="First day of month, e.g. 2026-02-01"),
    grouping_type: Optional[str] = Query(None, description="partner|tenant|user|process|agent"),
    company_id: Optional[UUID] = Query(None, description="One company; omit for every company"),
    current_user: User = Depends(app_admin_only),
    db: AsyncSession = Depends(get_control_db),
):
    # Events are recorded under the company that ran the work, so the
    # platform view spans every company unless one is asked for.
    svc = BillingService(db)
    events = await svc.get_costing_report(
        company_id=company_id,
        period_month=period_month,
        grouping_type=grouping_type,
    )
    rows = [_event_to_dict(e) for e in events]
    totals = {
        "total_base_cost": sum(r["base_cost"] for r in rows),
        "total_billing": sum(r["total_billing"] for r in rows),
        "total_telephony_in_seconds": sum(r["telephony_in_seconds"] for r in rows),
        "total_telephony_out_seconds": sum(r["telephony_out_seconds"] for r in rows),
        "total_image_gen": sum(r["image_gen_count"] for r in rows),
        "total_video_gen": sum(r["video_gen_count"] for r in rows),
        "total_other_ai_cost": sum(r["other_ai_cost"] for r in rows),
        "total_telephony_charge": sum(r["telephony_charge"] for r in rows),
        "total_llm_charge": sum(r["llm_charge"] for r in rows),
        "total_image_charge": sum(r["image_charge"] for r in rows),
        "total_video_charge": sum(r["video_charge"] for r in rows),
        "total_api_charge": sum(r["api_charge"] for r in rows),
    }
    return {"events": rows, "totals": totals, "count": len(rows)}


# ─── Billing Report (Client-Facing Revenue) ───────────────────────────────────

@router.get("/reports/billing", summary="Client-facing billing report (revenue tracking)")
async def get_billing_report(
    period_month: Optional[date] = Query(None),
    grouping_type: Optional[str] = Query(None, description="partner|tenant|user|process|agent"),
    company_id: Optional[UUID] = Query(None, description="One company; omit for every company"),
    current_user: User = Depends(app_admin_only),
    db: AsyncSession = Depends(get_control_db),
):
    # Same rows as the costing report (base_cost included), with revenue totals.
    svc = BillingService(db)
    events = await svc.get_costing_report(
        company_id=company_id,
        period_month=period_month,
        grouping_type=grouping_type,
    )
    rows = [_event_to_dict(e) for e in events]
    totals = {
        "total_revenue": sum(r["total_billing"] for r in rows),
        "total_platform_fees": sum(r["platform_fee_amount"] for r in rows),
        "total_partner_fees": sum(r["partner_fee_amount"] for r in rows),
        "total_discounts": sum(r["discount_amount"] for r in rows),
        "total_telephony_charge": sum(r["telephony_charge"] for r in rows),
        "total_llm_charge": sum(r["llm_charge"] for r in rows),
        "total_image_charge": sum(r["image_charge"] for r in rows),
        "total_video_charge": sum(r["video_charge"] for r in rows),
        "total_api_charge": sum(r["api_charge"] for r in rows),
    }
    return {"events": rows, "totals": totals, "count": len(rows)}
