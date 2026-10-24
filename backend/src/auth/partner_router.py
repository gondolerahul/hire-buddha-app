"""
Partner Router — Enhanced management endpoints for partner_admin users.

Provides tenant health scores, detailed tenant overviews,
aggregated analytics, and tenant integration configuration.

Companies, users, wallets and integrations are control rows; a tenant's agents
and runs are in its own database (Phase 14 WS2), read through ``tenant_db_for``
— one tenant at a time, a tenant whose database is not ready counting none.
"""

import logging
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from src.common.tenancy.session import get_control_db, is_split, tenant_db_for
from src.auth.models import Company, User
from src.auth.dependencies import get_current_user, RoleChecker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/partner", tags=["Partner Management"])

partner_only = RoleChecker(["partner_admin", "app_admin"])


@router.get("/tenants")
async def list_tenants_with_health(
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(partner_only),
):
    """
    List tenants managed by this partner with health scores (0-100, the one
    score of ``tenant_health``; its signals are read for all tenants at once).
    """
    result = await db.execute(select(Company).where(*_partner_tenants(current_user)))
    tenants = result.scalars().all()
    tenant_summaries = await _tenant_summaries(db, tenants)

    return {
        "total_tenants": len(tenant_summaries),
        "tenants": tenant_summaries,
    }


@router.get("/tenants/{tenant_id}/details")
async def get_tenant_details(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(partner_only),
):
    """Deep dive into a specific tenant — integrations, entities, recent executions."""
    # Verify access
    result = await db.execute(select(Company).where(Company.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if current_user.role != "app_admin" and tenant.parent_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Not authorized to view this tenant")

    summary = (await _tenant_summaries(db, [tenant]))[0]

    # Fetch integrations
    integrations = []
    try:
        from src.config.models import IntegrationRegistry
        int_result = await db.execute(
            select(IntegrationRegistry).where(
                IntegrationRegistry.company_id == tenant_id,
                IntegrationRegistry.status == "active",
            )
        )
        for entry in int_result.scalars().all():
            integrations.append({
                "id": str(entry.id),
                "provider_name": entry.provider_name,
                "service_category": entry.service_category,
                "model_name": entry.model_name,
                "status": entry.status,
            })
    except Exception:
        pass

    # Fetch entities and recent executions (the tenant's own database)
    entities = []
    executions = []
    try:
        from src.ai.orm import ExecutionRun, HierarchicalEntity
        async with tenant_db_for(db, tenant_id) as tenant_db:
            ent_result = await tenant_db.execute(
                select(HierarchicalEntity).where(
                    HierarchicalEntity.company_id == tenant_id,
                    HierarchicalEntity.is_template == False,
                ).order_by(HierarchicalEntity.created_at.desc()).limit(20)
            )
            for entity in ent_result.scalars().all():
                entities.append({
                    "id": str(entity.id),
                    "name": entity.name,
                    "type": entity.type.value if hasattr(entity.type, 'value') else str(entity.type),
                    "status": entity.status,
                    "created_at": entity.created_at.isoformat() if entity.created_at else None,
                })

            exec_result = await tenant_db.execute(
                select(ExecutionRun).where(
                    ExecutionRun.company_id == tenant_id,
                    ExecutionRun.parent_run_id.is_(None),
                ).order_by(ExecutionRun.created_at.desc()).limit(10)
            )
            for run in exec_result.scalars().all():
                executions.append({
                    "id": str(run.id),
                    "entity_id": str(run.entity_id),
                    "status": run.status,
                    "total_cost_usd": float(run.total_cost_usd) if run.total_cost_usd else 0,
                    "created_at": run.created_at.isoformat() if run.created_at else None,
                })
    except Exception:
        logger.warning("Partner view: agents and runs of tenant %s not read", tenant_id, exc_info=True)

    # Fetch users
    users = []
    user_result = await db.execute(
        select(User).where(User.company_id == tenant_id)
    )
    for user in user_result.scalars().all():
        users.append({
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "is_active": user.is_active,
        })

    summary["integrations"] = integrations
    summary["entities"] = entities
    summary["recent_executions"] = executions
    summary["users"] = users

    return summary


@router.get("/analytics/summary")
async def get_partner_analytics(
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(partner_only),
):
    """Aggregated analytics across all tenants managed by this partner."""
    result = await db.execute(select(Company.id).where(*_partner_tenants(current_user)))
    tenant_ids = [row[0] for row in result.fetchall()]

    if not tenant_ids:
        return {
            "total_tenants": 0,
            "total_entities": 0,
            "total_executions": 0,
            "total_cost_usd": 0.0,
            "total_billed_usd": 0.0,
            "total_wallet_balance": 0.0,
            "active_tenants": 0,
            "suspended_tenants": 0,
        }

    # Aggregate entity count, execution count and cost (tenant databases)
    total_entities, total_executions, total_cost, total_billed = await _tenant_totals(db, tenant_ids)

    # The tenants' credit: every live lot (Phase 15 M15.2), in USD at today's rate.
    total_wallet = 0.0
    try:
        from src.billing.wallet import summaries
        total_wallet = float(sum(w["available_usd"] for w in (await summaries(db, tenant_ids)).values()))
    except Exception:
        logger.warning("Partner analytics: wallets not read", exc_info=True)

    # Count active vs suspended
    status_result = await db.execute(
        select(Company.status, func.count(Company.id)).where(
            Company.id.in_(tenant_ids)
        ).group_by(Company.status)
    )
    status_counts = {row[0]: row[1] for row in status_result.fetchall()}

    return {
        "total_tenants": len(tenant_ids),
        "total_entities": total_entities,
        "total_executions": total_executions,
        "total_cost_usd": round(total_cost, 4),
        "total_billed_usd": round(total_billed, 4),
        "total_wallet_balance": round(total_wallet, 4),
        "active_tenants": status_counts.get("active", 0),
        "suspended_tenants": status_counts.get("suspended", 0),
    }


@router.get("/analytics/revenue")
async def get_partner_revenue(
    months: int = Query(6, ge=1, le=24),
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(partner_only),
):
    """What this partner's tenants were billed, per tenant and per month (Phase 15 T0-6).

    The partner dashboard called the app-admin-only ``partner-performance``
    report, got 403 and showed nothing (P-27). This is the partner's own view,
    in **billed** amounts — ``billing_events.total_billing``, what the wallets
    were charged — never provider cost (REQ-BL-3). ``app_admin``: every tenant.
    """
    from src.billing.billing_models import BillingEvent

    tenants = (await db.execute(select(Company).where(*_partner_tenants(current_user)))).scalars().all()
    today = datetime.utcnow().date()
    month_starts = [_month_start(today, back) for back in range(months - 1, -1, -1)]
    this_month = month_starts[-1]

    billed: dict = {}
    ids = [t.id for t in tenants]
    if ids:
        rows = (await db.execute(
            select(BillingEvent.company_id, BillingEvent.period_month, func.sum(BillingEvent.total_billing))
            .where(BillingEvent.company_id.in_(ids), BillingEvent.period_month >= month_starts[0])
            .group_by(BillingEvent.company_id, BillingEvent.period_month)
        )).all()
        for company_id, period, total in rows:
            billed[(company_id, period)] = Decimal(str(total or 0))

    per_tenant = []
    for t in tenants:
        period_total = sum((billed.get((t.id, m), Decimal("0")) for m in month_starts), Decimal("0"))
        per_tenant.append({
            "company_id": str(t.id),
            "company_name": t.name,
            "status": t.status,
            "billed_this_month": float(billed.get((t.id, this_month), Decimal("0"))),
            "billed_period": float(period_total),
        })
    per_tenant.sort(key=lambda r: r["billed_period"], reverse=True)
    monthly = [{"month": m.strftime("%Y-%m"),
                "billed": float(sum((v for (_, p), v in billed.items() if p == m), Decimal("0")))}
               for m in month_starts]
    return {
        "currency": "USD",
        "months": months,
        "totals": {
            "tenants": len(tenants),
            "active_tenants": sum(1 for t in tenants if t.status == "active"),
            "suspended_tenants": sum(1 for t in tenants if t.status == "suspended"),
            "billed_this_month": monthly[-1]["billed"],
            "billed_period": float(sum((v for v in billed.values()), Decimal("0"))),
        },
        "monthly": monthly,
        "tenants": per_tenant,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _month_start(today: date, back: int) -> date:
    """The first day of the month ``back`` months before ``today``'s."""
    index = today.year * 12 + (today.month - 1) - back
    return date(index // 12, index % 12 + 1, 1)

def _partner_tenants(user: User) -> tuple:
    """The filter for the caller's tenants: a partner's own; every tenant for app_admin."""
    if user.role == "app_admin":
        return (Company.type == "TENANT",)
    return (Company.type == "TENANT", Company.parent_id == user.company_id)


async def _tenant_totals(db: AsyncSession, tenant_ids: List[UUID]) -> tuple[int, int, float, float]:
    """Agents, top-level runs, their cost and what they were billed (USD) of
    ``tenant_ids``: one query on the shared database (single mode), one per
    tenant database (split mode). Partners see the billed total only (T9-3).

    A child run's cost is already in its parent's total, so only top-level runs
    are summed — summing every run counted child spend twice (P-25)."""
    from src.ai.orm import ExecutionRun, HierarchicalEntity

    scopes = [(tid, [tid]) for tid in tenant_ids] if is_split() else [(None, tenant_ids)]
    entities, executions, cost, billed = 0, 0, 0.0, 0.0
    for scope, ids in scopes:
        try:
            async with tenant_db_for(db, scope) as tenant_db:
                entities += (await tenant_db.execute(
                    select(func.count(HierarchicalEntity.id)).where(HierarchicalEntity.company_id.in_(ids))
                )).scalar() or 0
                row = (await tenant_db.execute(
                    select(
                        func.count(ExecutionRun.id),
                        func.coalesce(func.sum(ExecutionRun.total_cost_usd), 0),
                        func.coalesce(func.sum(ExecutionRun.billed_amount), 0),
                    ).where(ExecutionRun.company_id.in_(ids), ExecutionRun.parent_run_id.is_(None))
                )).one()
                executions += row[0] or 0
                cost += float(row[1])
                billed += float(row[2])
        except Exception:
            logger.warning("Partner analytics: agents and runs of %s not read", scope or "the tenants",
                           exc_info=True)
    return entities, executions, cost, billed


async def _tenant_summaries(db: AsyncSession, tenants: List[Company]) -> List[dict]:
    """Health-scored summaries of ``tenants``, their signals read in one batch (P-23)."""
    from src.auth.tenant_health import gather, score
    from src.config.models import IntegrationRegistry

    ids = [t.id for t in tenants]
    if not ids:
        return []
    signals = await gather(db, ids)
    users = dict((await db.execute(
        select(User.company_id, func.count(User.id)).where(User.company_id.in_(ids)).group_by(User.company_id)
    )).all())
    integrations = dict((await db.execute(
        select(IntegrationRegistry.company_id, func.count(IntegrationRegistry.id))
        .where(IntegrationRegistry.company_id.in_(ids), IntegrationRegistry.status == "active")
        .group_by(IntegrationRegistry.company_id)
    )).all())
    from src.billing.billing_models import WalletLot
    now = datetime.utcnow()
    daily = dict((await db.execute(
        select(WalletLot.company_id, func.coalesce(func.sum(WalletLot.remaining), 0))
        .where(WalletLot.company_id.in_(ids), WalletLot.kind == "daily", WalletLot.remaining > 0,
               WalletLot.expires_at > now).group_by(WalletLot.company_id)
    )).all())

    summaries = []
    for tenant in tenants:
        s = signals[tenant.id]
        summaries.append({
            "id": str(tenant.id),
            "name": tenant.name,
            "status": tenant.status,
            "onboarding_status": tenant.onboarding_status or "pending",
            "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
            "wallet_balance": round(s.credit_usd, 2),
            "daily_credits": float(daily.get(tenant.id) or 0),
            "integration_count": int(integrations.get(tenant.id, 0)),
            "entity_count": s.agents,
            "recent_executions_7d": s.runs_7d,
            "user_count": int(users.get(tenant.id, 0)),
            **score(s),
        })
    return summaries
