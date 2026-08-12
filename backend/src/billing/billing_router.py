"""
Billing Router — billing config management and reporting endpoints.
"""
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.database import get_db
from src.auth.router import get_current_user
from src.auth.models import User
from src.billing.billing_service import BillingService
from src.billing.billing_models import BillingEvent, BillingConfig

router = APIRouter(prefix="/api/v1", tags=["Billing & Reports"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class BillingConfigUpdate(BaseModel):
    multiplier_factor: Optional[Decimal] = None
    platform_fee_pct: Optional[Decimal] = None
    sales_partner_fee_pct: Optional[Decimal] = None
    discount_pct: Optional[Decimal] = None
    default_daily_credits: Optional[Decimal] = None
    base_cost_telephony: Optional[Decimal] = None
    base_cost_llm: Optional[Decimal] = None
    base_cost_image_gen: Optional[Decimal] = None
    company_id: Optional[UUID] = None  # None = update global default


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
    telephony_in_minutes: float
    telephony_out_minutes: float
    image_gen_count: int
    video_gen_count: int
    other_ai_cost: float

    class Config:
        from_attributes = True


def _event_to_dict(e: BillingEvent) -> dict:
    return {
        "id": str(e.id),
        "company_id": str(e.company_id),
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
        "telephony_in_minutes": float(e.telephony_in_minutes),
        "telephony_out_minutes": float(e.telephony_out_minutes),
        "image_gen_count": e.image_gen_count,
        "video_gen_count": e.video_gen_count,
        "other_ai_cost": float(e.other_ai_cost),
    }


def _config_to_dict(c: BillingConfig) -> dict:
    return {
        "id": str(c.id),
        "company_id": str(c.company_id) if c.company_id else None,
        "config_name": c.config_name,
        "multiplier_factor": float(c.multiplier_factor),
        "platform_fee_pct": float(c.platform_fee_pct),
        "sales_partner_fee_pct": float(c.sales_partner_fee_pct),
        "discount_pct": float(c.discount_pct),
        "default_daily_credits": float(c.default_daily_credits),
        "base_cost_telephony": float(c.base_cost_telephony) if c.base_cost_telephony is not None else None,
        "base_cost_llm": float(c.base_cost_llm) if c.base_cost_llm is not None else None,
        "base_cost_image_gen": float(c.base_cost_image_gen) if c.base_cost_image_gen is not None else None,
        "is_active": c.is_active,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


# ─── Billing Config ──────────────────────────────────────────────────────────

@router.get("/billing/config", summary="Get billing configuration")
async def get_billing_config(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = BillingService(db)
    config = await svc.get_billing_config(current_user.company_id)
    if not config:
        return {"message": "No billing config found", "config": None}
    return {"config": _config_to_dict(config)}


@router.put("/billing/config", summary="Update billing configuration")
async def update_billing_config(
    payload: BillingConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Only admins can update billing config
    if current_user.role not in ("app_admin", "partner_admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    svc = BillingService(db)
    config = await svc.update_billing_config(
        company_id=payload.company_id,
        multiplier_factor=payload.multiplier_factor,
        platform_fee_pct=payload.platform_fee_pct,
        sales_partner_fee_pct=payload.sales_partner_fee_pct,
        discount_pct=payload.discount_pct,
        default_daily_credits=payload.default_daily_credits,
        base_cost_telephony=payload.base_cost_telephony,
        base_cost_llm=payload.base_cost_llm,
        base_cost_image_gen=payload.base_cost_image_gen,
    )
    return {"config": _config_to_dict(config)}


# ─── Costing Report (Internal / Operational) ──────────────────────────────────

@router.get("/reports/costing", summary="Internal costing report (operational expenses)")
async def get_costing_report(
    period_month: Optional[date] = Query(None, description="First day of month, e.g. 2026-02-01"),
    grouping_type: Optional[str] = Query(None, description="partner|tenant|user|process|agent"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = BillingService(db)
    events = await svc.get_costing_report(
        company_id=current_user.company_id,
        period_month=period_month,
        grouping_type=grouping_type,
    )
    rows = [_event_to_dict(e) for e in events]
    totals = {
        "total_base_cost": sum(r["base_cost"] for r in rows),
        "total_billing": sum(r["total_billing"] for r in rows),
        "total_telephony_in_minutes": sum(r["telephony_in_minutes"] for r in rows),
        "total_telephony_out_minutes": sum(r["telephony_out_minutes"] for r in rows),
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # For now billing and costing use the same data source;
    # billing shows TB formula result prominently
    svc = BillingService(db)
    events = await svc.get_costing_report(
        company_id=current_user.company_id,
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
