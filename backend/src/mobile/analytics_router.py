"""
Analytics endpoints for mobile campaigns, used by both the web frontend and
the Android app (docs 07 §3). Mounted under /api/v1.
"""
from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.campaign_models import Campaign
from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.common.database import get_db
from src.mobile import analytics
from src.mobile.models import EXECUTION_MODE_MOBILE, CampaignAssignee, MobileCallAttempt

router = APIRouter(tags=["Mobile Analytics"])

COMPANY_ADMIN_ROLES = {"tenant_admin"}
CROSS_TENANT_ROLES = {"app_admin", "partner_admin"}


def _is_admin(user: User) -> bool:
    return user.role in COMPANY_ADMIN_ROLES or user.role in CROSS_TENANT_ROLES


async def _campaign_for(db: AsyncSession, user: User, campaign_id: UUID) -> Campaign:
    campaign = await db.get(Campaign, campaign_id)
    if campaign is None or (campaign.company_id != user.company_id and user.role not in CROSS_TENANT_ROLES):
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.execution_mode != EXECUTION_MODE_MOBILE:
        raise HTTPException(status_code=409, detail={"code": "not_mobile_campaign",
                                                     "message": "Analytics here are for mobile campaigns"})
    return campaign


@router.get("/campaigns/{campaign_id}/mobile-analytics")
async def campaign_mobile_analytics(
    campaign_id: UUID,
    user_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    campaign = await _campaign_for(db, user, campaign_id)
    admin = _is_admin(user)
    scope_user = user_id if admin else user.id
    data = await analytics.compute_analytics(db, company_id=campaign.company_id, campaign_id=campaign.id,
                                             user_id=scope_user)
    data["campaign_id"] = campaign.id
    data["execution_mode"] = campaign.execution_mode
    data["by_rep"] = await analytics.by_rep(db, company_id=campaign.company_id, campaign_id=campaign.id,
                                            date_from=None, date_to=None, only_user=scope_user)
    return data


@router.get("/campaigns/{campaign_id}/calls")
async def campaign_calls(
    campaign_id: UUID,
    status: Optional[str] = None,
    disposition: Optional[str] = None,
    user_id: Optional[UUID] = None,
    include_pending: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    campaign = await _campaign_for(db, user, campaign_id)
    admin = _is_admin(user)
    scope_user = user_id if admin else user.id
    # A rep may see the uncalled leads of a list they are assigned to work, and no other.
    include_unattempted = include_pending and (admin or await _is_assigned(db, campaign.id, user.id))
    return await analytics.call_list(db, company_id=campaign.company_id, campaign_id=campaign.id,
                                     user_id=scope_user, status=status, disposition=disposition,
                                     limit=limit, offset=offset, include_unattempted=include_unattempted)


async def _is_assigned(db: AsyncSession, campaign_id: UUID, user_id: UUID) -> bool:
    row = await db.execute(select(CampaignAssignee.user_id).where(
        CampaignAssignee.campaign_id == campaign_id, CampaignAssignee.user_id == user_id,
    ))
    return row.first() is not None


@router.get("/mobile/analytics/summary")
async def mobile_summary(
    date_from: Optional[date] = Query(default=None, alias="from"),
    date_to: Optional[date] = Query(default=None, alias="to"),
    user_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    start, end = analytics.parse_range(date_from, date_to)
    scope_user = user_id if _is_admin(user) else user.id
    data = await analytics.compute_analytics(db, company_id=user.company_id, user_id=scope_user,
                                             date_from=start, date_to=end)
    data["from"] = start
    data["to"] = end
    data["daily"] = await analytics.daily(db, company_id=user.company_id, user_id=scope_user,
                                          date_from=start, date_to=end)
    data["by_rep"] = await analytics.by_rep(db, company_id=user.company_id, campaign_id=None,
                                            date_from=start, date_to=end, only_user=scope_user)
    return data


@router.get("/mobile/call-attempts/{attempt_id}/timeline")
async def attempt_timeline(attempt_id: UUID, db: AsyncSession = Depends(get_db),
                           user: User = Depends(get_current_user)):
    attempt = await db.get(MobileCallAttempt, attempt_id)
    allowed = attempt is not None and (
        attempt.user_id == user.id
        or (_is_admin(user) and (attempt.company_id == user.company_id or user.role in CROSS_TENANT_ROLES))
    )
    if not allowed:
        raise HTTPException(status_code=404, detail="Call attempt not found")
    return {"attempt_id": attempt.id, "timeline": await analytics.attempt_timeline(db, attempt)}
