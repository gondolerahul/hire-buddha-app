"""
Cron Router — admin-triggered endpoints for daily credit and monthly subscription jobs.
Protected by app_admin role.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.database import get_db
from src.auth.router import get_current_user
from src.auth.models import User
from src.billing.cron_service import CronService

router = APIRouter(prefix="/api/v1/cron", tags=["Cron Jobs (Admin)"])


def _require_admin(user: User):
    if user.role not in ("app_admin",):
        raise HTTPException(status_code=403, detail="app_admin role required")


@router.post("/daily-credits", summary="Trigger daily credit flush and injection (admin)")
async def run_daily_credits(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(current_user)
    svc = CronService(db)
    result = await svc.run_daily_credit_job()
    return result


@router.post("/monthly-billing", summary="Trigger monthly subscription billing (admin)")
async def run_monthly_billing(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(current_user)
    svc = CronService(db)
    result = await svc.run_monthly_subscription_job()
    return result
