"""
Analytics & Reports Router
Provides endpoints for all 6-role analytics reports.
"""
from __future__ import annotations
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.database import get_db
from src.auth.router import get_current_user
from src.auth.models import User
from src.ai.reports_service import ReportsService

router = APIRouter(prefix="/api/v1/reports/analytics", tags=["Analytics & Reports"])

ADMIN_ROLES = {"app_admin", "app_user", "partner_admin", "partner_user", "tenant_admin"}
APP_ROLES = {"app_admin", "app_user"}
PARTNER_ROLES = {"app_admin", "partner_admin", "partner_user"}


def _require_roles(user: User, *roles: str):
    if user.role not in roles:
        raise HTTPException(status_code=403, detail="Insufficient permissions")


# ─── Execution Health ──────────────────────────────────────────────────────────

@router.get("/execution-health", summary="Execution success/fail/pause rates")
async def get_execution_health(
    days: int = Query(30, ge=1, le=365),
    global_view: bool = Query(False, description="App admin only: view all companies"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ReportsService(db)
    company_id = None if (global_view and current_user.role == "app_admin") else current_user.company_id
    return await svc.get_execution_health(company_id=company_id, days=days)


# ─── LLM Performance ──────────────────────────────────────────────────────────

@router.get("/llm-performance", summary="LLM latency/cost/model breakdown")
async def get_llm_performance(
    days: int = Query(30, ge=1, le=365),
    global_view: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ReportsService(db)
    company_id = None if (global_view and current_user.role == "app_admin") else current_user.company_id
    return await svc.get_llm_performance(company_id=company_id, days=days)


# ─── Tool Efficacy ─────────────────────────────────────────────────────────────

@router.get("/tool-efficacy", summary="Tool error rates and latency")
async def get_tool_efficacy(
    days: int = Query(30, ge=1, le=365),
    global_view: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ReportsService(db)
    company_id = None if (global_view and current_user.role == "app_admin") else current_user.company_id
    return await svc.get_tool_efficacy(company_id=company_id, days=days)


# ─── HITL Report ───────────────────────────────────────────────────────────────

@router.get("/hitl-overview", summary="HITL pending/overdue approvals")
async def get_hitl_report(
    days: int = Query(30, ge=1, le=365),
    global_view: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ReportsService(db)
    company_id = None if (global_view and current_user.role == "app_admin") else current_user.company_id
    return await svc.get_hitl_report(company_id=company_id, days=days)


# ─── Wallet Liability ─────────────────────────────────────────────────────────

@router.get("/wallet-liability", summary="Global credit wallet balances (app_admin)")
async def get_wallet_liability(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_roles(current_user, "app_admin")
    svc = ReportsService(db)
    return await svc.get_wallet_liability()


# ─── Usage Breakdown ──────────────────────────────────────────────────────────

@router.get("/usage-breakdown", summary="Cost breakdown by channel (LLM/Voice/API)")
async def get_usage_breakdown(
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ReportsService(db)
    return await svc.get_usage_breakdown(company_id=current_user.company_id, days=days)


# ─── Tenant Health Scores ─────────────────────────────────────────────────────

@router.get("/tenant-health", summary="Per-tenant health scorecards (partner roles)")
async def get_tenant_health(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_roles(current_user, "app_admin", "partner_admin", "partner_user")
    svc = ReportsService(db)
    return await svc.get_tenant_health_scores(partner_company_id=current_user.company_id)


# ─── Campaign Analytics ────────────────────────────────────────────────────────

@router.get("/campaign-analytics", summary="Campaign execution metrics")
async def get_campaign_analytics(
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ReportsService(db)
    return await svc.get_campaign_analytics(company_id=current_user.company_id, days=days)


# ─── Personal Task History ─────────────────────────────────────────────────────

@router.get("/personal-tasks", summary="Personal execution history (tenant_user)")
async def get_personal_tasks(
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ReportsService(db)
    return await svc.get_personal_tasks(
        user_id=current_user.id,
        company_id=current_user.company_id,
        limit=limit,
        status_filter=status,
    )


# ─── Agent Error Rates ─────────────────────────────────────────────────────────

@router.get("/agent-errors", summary="Per-agent error rates and performance")
async def get_agent_errors(
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ReportsService(db)
    return await svc.get_agent_error_rates(company_id=current_user.company_id, days=days)


# ─── Credit Forecast ──────────────────────────────────────────────────────────

@router.get("/credit-forecast", summary="Credit burn rate and depletion forecast")
async def get_credit_forecast(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ReportsService(db)
    return await svc.get_credit_forecast(company_id=current_user.company_id)


# ─── Subscription MRR ─────────────────────────────────────────────────────────

@router.get("/subscription-mrr", summary="MRR, subscription tiers, churn (app_admin)")
async def get_subscription_mrr(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_roles(current_user, "app_admin")
    svc = ReportsService(db)
    return await svc.get_subscription_mrr()


# ─── Partner Performance ────────────────────────────────────────────────────────

@router.get("/partner-performance", summary="Per-partner revenue contribution (app_admin)")
async def get_partner_performance(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_roles(current_user, "app_admin")
    svc = ReportsService(db)
    return await svc.get_partner_performance()


# ─── Data Growth ────────────────────────────────────────────────────────────────

@router.get("/data-growth", summary="Table row counts and archival readiness (app_user)")
async def get_data_growth(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_roles(current_user, "app_admin", "app_user")
    svc = ReportsService(db)
    return await svc.get_data_growth()
