"""
Cron Router — admin-triggered endpoints for daily credit and monthly subscription jobs.
Protected by app_admin role.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.database import get_db
from src.auth.dependencies import RoleChecker
from src.auth.roles import Role
from src.auth.models import User
from src.billing.cron_service import CronService

router = APIRouter(prefix="/api/v1/cron", tags=["Cron Jobs (Admin)"])


@router.post("/daily-credits", summary="Trigger daily credit flush and injection (admin)")
async def run_daily_credits(
    current_user: User = Depends(RoleChecker([Role.APP_ADMIN])),
    db: AsyncSession = Depends(get_db),
):
    svc = CronService(db)
    result = await svc.run_daily_credit_job()
    return result


@router.post("/monthly-billing", summary="Trigger monthly subscription billing (admin)")
async def run_monthly_billing(
    current_user: User = Depends(RoleChecker([Role.APP_ADMIN])),
    db: AsyncSession = Depends(get_db),
):
    svc = CronService(db)
    result = await svc.run_monthly_subscription_job()
    return result
