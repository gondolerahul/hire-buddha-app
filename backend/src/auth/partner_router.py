"""
Partner Router — Enhanced management endpoints for partner_admin users.

Provides tenant health scores, detailed tenant overviews,
aggregated analytics, and tenant integration configuration.
"""

import logging
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from src.common.database import get_db
from src.auth.models import Company, User
from src.auth.dependencies import get_current_user, RoleChecker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/partner", tags=["Partner Management"])

partner_only = RoleChecker(["partner_admin", "app_admin"])


@router.get("/tenants")
async def list_tenants_with_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(partner_only),
):
    """
    List tenants managed by this partner with health scores.
    
    Health score (0-100) is calculated from:
      - Wallet balance (30 pts)
      - Active integrations (20 pts)
      - Active agents (25 pts)
      - Recent executions (25 pts)
    """
    # Get tenants belonging to this partner
    if current_user.role == "app_admin":
        tenant_query = select(Company).where(Company.type == "TENANT")
    else:
        tenant_query = select(Company).where(
            Company.type == "TENANT",
            Company.parent_id == current_user.company_id,
        )

    result = await db.execute(tenant_query)
    tenants = result.scalars().all()

    tenant_summaries = []
    for tenant in tenants:
        summary = await _build_tenant_summary(db, tenant)
        tenant_summaries.append(summary)

    return {
        "total_tenants": len(tenant_summaries),
        "tenants": tenant_summaries,
    }


@router.get("/tenants/{tenant_id}/details")
async def get_tenant_details(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
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

    summary = await _build_tenant_summary(db, tenant)

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

    # Fetch entities
    entities = []
    try:
        from src.ai.models import HierarchicalEntity
        ent_result = await db.execute(
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
    except Exception:
        pass

    # Fetch recent executions
    executions = []
    try:
        from src.ai.models import ExecutionRun
        exec_result = await db.execute(
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
        pass

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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(partner_only),
):
    """Aggregated analytics across all tenants managed by this partner."""
    if current_user.role == "app_admin":
        tenant_query = select(Company.id).where(Company.type == "TENANT")
    else:
        tenant_query = select(Company.id).where(
            Company.type == "TENANT",
            Company.parent_id == current_user.company_id,
        )

    result = await db.execute(tenant_query)
    tenant_ids = [row[0] for row in result.fetchall()]

    if not tenant_ids:
        return {
            "total_tenants": 0,
            "total_entities": 0,
            "total_executions": 0,
            "total_cost_usd": 0.0,
            "total_wallet_balance": 0.0,
            "active_tenants": 0,
            "suspended_tenants": 0,
        }

    # Aggregate entity count
    try:
        from src.ai.models import HierarchicalEntity
        ent_count = await db.execute(
            select(func.count(HierarchicalEntity.id)).where(
                HierarchicalEntity.company_id.in_(tenant_ids)
            )
        )
        total_entities = ent_count.scalar() or 0
    except Exception:
        total_entities = 0

    # Aggregate execution count and cost
    try:
        from src.ai.models import ExecutionRun
        exec_result = await db.execute(
            select(
                func.count(ExecutionRun.id),
                func.coalesce(func.sum(ExecutionRun.total_cost_usd), 0),
            ).where(ExecutionRun.company_id.in_(tenant_ids))
        )
        row = exec_result.one()
        total_executions = row[0] or 0
        total_cost = float(row[1])
    except Exception:
        total_executions = 0
        total_cost = 0.0

    # Aggregate wallet balance
    total_wallet = 0.0
    try:
        from src.billing.billing_models import CreditWallet
        wallet_result = await db.execute(
            select(func.coalesce(func.sum(CreditWallet.wallet_balance), 0)).where(
                CreditWallet.company_id.in_(tenant_ids)
            )
        )
        total_wallet = float(wallet_result.scalar() or 0)
    except Exception:
        pass

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
        "total_wallet_balance": round(total_wallet, 4),
        "active_tenants": status_counts.get("active", 0),
        "suspended_tenants": status_counts.get("suspended", 0),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _build_tenant_summary(db: AsyncSession, tenant: Company) -> dict:
    """Build a health-scored summary for a single tenant."""
    summary = {
        "id": str(tenant.id),
        "name": tenant.name,
        "status": tenant.status,
        "onboarding_status": tenant.onboarding_status or "pending",
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
    }

    health_score = 0.0

    # 1. Wallet balance (0-30 pts)
    try:
        from src.billing.billing_models import CreditWallet
        wallet_result = await db.execute(
            select(CreditWallet).where(CreditWallet.company_id == tenant.id)
        )
        wallet = wallet_result.scalar_one_or_none()
        if wallet:
            balance = float(wallet.wallet_balance or 0) + float(wallet.daily_credits or 0)
            summary["wallet_balance"] = round(balance, 2)
            summary["daily_credits"] = float(wallet.daily_credits or 0)
            # Score: full points if balance > $10, proportional below
            health_score += min(30, (balance / 10) * 30)
        else:
            summary["wallet_balance"] = 0.0
            summary["daily_credits"] = 0.0
    except Exception:
        summary["wallet_balance"] = 0.0
        summary["daily_credits"] = 0.0

    # 2. Active integrations (0-20 pts)
    try:
        from src.config.models import IntegrationRegistry
        int_count = await db.execute(
            select(func.count(IntegrationRegistry.id)).where(
                IntegrationRegistry.company_id == tenant.id,
                IntegrationRegistry.status == "active",
            )
        )
        count = int_count.scalar() or 0
        summary["integration_count"] = count
        health_score += min(20, count * 10)  # 2+ integrations = full score
    except Exception:
        summary["integration_count"] = 0

    # 3. Active agents (0-25 pts)
    try:
        from src.ai.models import HierarchicalEntity
        agent_count = await db.execute(
            select(func.count(HierarchicalEntity.id)).where(
                HierarchicalEntity.company_id == tenant.id,
                HierarchicalEntity.is_template == False,
            )
        )
        count = agent_count.scalar() or 0
        summary["entity_count"] = count
        health_score += min(25, count * 5)  # 5+ entities = full score
    except Exception:
        summary["entity_count"] = 0

    # 4. Recent executions — last 7 days (0-25 pts)
    try:
        from src.ai.models import ExecutionRun
        from datetime import timedelta
        week_ago = datetime.utcnow() - timedelta(days=7)
        exec_count = await db.execute(
            select(func.count(ExecutionRun.id)).where(
                ExecutionRun.company_id == tenant.id,
                ExecutionRun.created_at >= week_ago,
            )
        )
        count = exec_count.scalar() or 0
        summary["recent_executions_7d"] = count
        health_score += min(25, count * 2.5)  # 10+ executions = full score
    except Exception:
        summary["recent_executions_7d"] = 0

    # User count
    user_count = await db.execute(
        select(func.count(User.id)).where(User.company_id == tenant.id)
    )
    summary["user_count"] = user_count.scalar() or 0

    summary["health_score"] = round(min(100, health_score), 1)
    summary["health_level"] = (
        "green" if health_score >= 70 else
        "amber" if health_score >= 40 else
        "red"
    )

    return summary
