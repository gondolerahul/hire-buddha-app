"""
Billing Router — billing config management and reporting endpoints.
"""
from datetime import date, timedelta
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
    return {
        "config": {
            "company_id": str(company_id) if company_id else None,
            "formula_id": str(formula.id) if formula.id else None,
            "formula_scope": formula.scope,
            "multiplier_factor": float(formula.mf),
            "platform_fee_pct": float(formula.pf),
            "discount_pct": float(formula.d),
        },
        "history": [{"id": str(v.id), "multiplier_factor": float(v.mf), "platform_fee_pct": float(v.pf),
                     "discount_pct": float(v.d), "active": v.active,
                     "effective_from": v.effective_from.isoformat() if v.effective_from else None,
                     "reason": v.reason, "created_by": str(v.created_by) if v.created_by else None}
                    for v in versions],
    }


# ─── Billing Config ──────────────────────────────────────────────────────────

@router.get("/billing/config", summary="The price formula (app_admin)")
async def get_billing_config(
    company_id: Optional[UUID] = Query(None, description="A company's formula; omit for the platform's"),
    current_user: User = Depends(app_admin_only),
    db: AsyncSession = Depends(get_control_db),
):
    return await _config_view(db, company_id)


@router.put("/billing/config", summary="Change the price formula (app_admin)")
async def update_billing_config(
    payload: BillingConfigUpdate,
    current_user: User = Depends(app_admin_only),
    db: AsyncSession = Depends(get_control_db),
):
    """A formula change is a new version (audited), in effect at once for new
    usage; a run already running keeps the formula it started with (T3-3)."""
    from src.billing.formulas import formula_for, set_formula

    fields = payload.model_dump(exclude_unset=True)
    if "default_daily_credits" in fields:
        raise HTTPException(status_code=422, detail=(
            "Daily credits are policies now (Phase 15 T5-5): set them on Console → Daily credits "
            "(/api/v1/admin/daily-credits)."))
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
    return await _config_view(db, payload.company_id)


# ─── Costing Report (Internal / Operational) ──────────────────────────────────

def _by_category(lines: list[dict]) -> dict:
    out: dict = {}
    for line in lines:
        cat = out.setdefault(line["category"], {"cost_usd": Decimal(0), "billed_usd": Decimal(0)})
        cat["cost_usd"] += line["cost_usd"]
        cat["billed_usd"] += line["billed_usd"]
    return {k: {"cost_usd": float(v["cost_usd"]), "billed_usd": float(v["billed_usd"])} for k, v in sorted(out.items())}


def _floats(lines: list[dict]) -> list[dict]:
    return [{k: float(v) if isinstance(v, Decimal) else v for k, v in line.items()} for line in lines]


@router.get("/reports/costing", summary="Internal costing report (operational expenses)")
async def get_costing_report(
    period_month: Optional[date] = Query(None, description="First day of month, e.g. 2026-02-01"),
    grouping_type: Optional[str] = Query(None, description="entity|agent (the grouping a settlement records)"),
    company_id: Optional[UUID] = Query(None, description="One company; omit for every company"),
    current_user: User = Depends(app_admin_only),
    db: AsyncSession = Depends(get_control_db),
):
    """Cost and billed amount per company, month, grouping and category, from
    billing lines (Phase 15 T3-8; the Platform Console's R-A02/R-A03 are the
    reports with filters and export)."""
    # Lines are recorded under the company that ran the work, so the
    # platform view spans every company unless one is asked for.
    lines = await BillingService(db).get_billing_lines(
        company_id=company_id,
        period_month=period_month,
        grouping_type=grouping_type,
    )
    totals = {
        "total_cost_usd": float(sum((line["cost_usd"] for line in lines), Decimal(0))),
        "total_billed_usd": float(sum((line["billed_usd"] for line in lines), Decimal(0))),
        "by_category": _by_category(lines),
    }
    return {"lines": _floats(lines), "totals": totals, "count": len(lines)}


async def _partner_earnings_usd(db: AsyncSession, period_month: Optional[date], company_id: Optional[UUID]) -> float:
    """Commissions and fee shares earned in the month (net of clawbacks), USD."""
    from sqlalchemy import func, select

    from src.partners.models import PartnerLedgerEntry

    query = select(func.coalesce(func.sum(PartnerLedgerEntry.amount_usd), 0)).where(
        PartnerLedgerEntry.kind.in_(("commission", "override", "fee_share", "clawback")),
        PartnerLedgerEntry.status != "reversed")
    if period_month is not None:
        start = period_month.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        query = query.where(PartnerLedgerEntry.created_at >= start, PartnerLedgerEntry.created_at < end)
    if company_id is not None:
        query = query.where(PartnerLedgerEntry.tenant_id == company_id)
    return float((await db.execute(query)).scalar() or 0)


# ─── Billing Report (Client-Facing Revenue) ───────────────────────────────────

@router.get("/reports/billing", summary="Client-facing billing report (revenue tracking)")
async def get_billing_report(
    period_month: Optional[date] = Query(None),
    grouping_type: Optional[str] = Query(None, description="entity|agent (the grouping a settlement records)"),
    company_id: Optional[UUID] = Query(None, description="One company; omit for every company"),
    current_user: User = Depends(app_admin_only),
    db: AsyncSession = Depends(get_control_db),
):
    """Revenue from billing lines (T3-8): billed, margin over cost, and what
    partners earned (the ledger, USD — Phase 15 T8-12, K-10)."""
    lines = await BillingService(db).get_billing_lines(
        company_id=company_id,
        period_month=period_month,
        grouping_type=grouping_type,
    )
    revenue = sum((line["billed_usd"] for line in lines), Decimal(0))
    cost = sum((line["cost_usd"] for line in lines), Decimal(0))
    totals = {
        "total_revenue_usd": float(revenue),
        "total_margin_usd": float(revenue - cost),
        "total_partner_fees": await _partner_earnings_usd(db, period_month, company_id),
        "by_category": _by_category(lines),
    }
    return {"lines": _floats(lines), "totals": totals, "count": len(lines)}
