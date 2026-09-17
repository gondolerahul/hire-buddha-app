"""
/api/v1/mobile — REST API for the Android dialer app (docs 06 §2).

Only tenant_admin and tenant_user may call these endpoints; everything is
scoped to the caller's company.
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.common.database import get_db
from src.mobile import service
from src.mobile.service import MobileError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mobile", tags=["Mobile Dialer"])


async def mobile_user(user: User = Depends(get_current_user)) -> User:
    if user.role not in service.MOBILE_ROLES:
        raise HTTPException(status_code=403, detail={
            "code": "role_not_supported",
            "message": "The mobile app is for tenant admins and tenant users. Please use the web app.",
        })
    return user


def _raise(e: MobileError):
    raise HTTPException(status_code=e.status_code, detail={"code": e.code, "message": e.message})


# ── Schemas ──────────────────────────────────────────────────────────────

class DeviceRegister(BaseModel):
    install_id: str = Field(min_length=8, max_length=64)
    model: Optional[str] = Field(default=None, max_length=100)
    os_version: Optional[str] = Field(default=None, max_length=30)
    app_version: Optional[str] = Field(default=None, max_length=50)
    fcm_token: Optional[str] = Field(default=None, max_length=512)
    phone_account_label: Optional[str] = Field(default=None, max_length=100)


class RunStart(BaseModel):
    device_id: UUID
    dial_order: str = "ai_first"


class RunUpdate(BaseModel):
    status: str


class AttemptCreate(BaseModel):
    run_id: UUID
    campaign_call_id: UUID
    device_id: UUID
    assisted: bool = False


class CallEvent(BaseModel):
    seq: int = Field(ge=0)
    type: str = Field(max_length=40)
    device_ts: Optional[str] = None
    elapsed_ms: Optional[int] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class EventBatch(BaseModel):
    events: List[CallEvent] = Field(min_length=1, max_length=100)


# ── App & me ─────────────────────────────────────────────────────────────

@router.get("/app-version")
async def app_version(version_code: Optional[int] = Query(default=None)):
    """Unauthenticated: the app checks for updates before login (private APK distribution)."""
    return service.app_version_info(version_code)


@router.get("/me")
async def me(user: User = Depends(mobile_user)):
    return {
        "user_id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "is_admin": service.is_admin(user),
        "company_id": user.company_id,
        "company_name": user.company.name if user.company else None,
    }


# ── Devices ──────────────────────────────────────────────────────────────

@router.post("/devices")
async def register_device(body: DeviceRegister, db: AsyncSession = Depends(get_db),
                          user: User = Depends(mobile_user)):
    try:
        return await service.register_device(db, user, body.model_dump())
    except MobileError as e:
        _raise(e)


@router.get("/devices/{device_id}")
async def get_device(device_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(mobile_user)):
    try:
        return service.device_view(await service.get_owned_device(db, user, device_id))
    except MobileError as e:
        _raise(e)


@router.post("/devices/{device_id}/verification")
async def reissue_verification(device_id: UUID, db: AsyncSession = Depends(get_db),
                               user: User = Depends(mobile_user)):
    try:
        device = await service.get_owned_device(db, user, device_id)
        device.status = service.DEVICE_UNVERIFIED
        return service.device_view(device, await service.issue_device_verification(db, device))
    except MobileError as e:
        _raise(e)


# ── Campaign helpers ─────────────────────────────────────────────────────

@router.get("/campaigns")
async def list_campaigns(status: Optional[str] = None, db: AsyncSession = Depends(get_db),
                         user: User = Depends(mobile_user)):
    return {"campaigns": await service.list_mobile_campaigns(db, user, status)}


@router.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(mobile_user)):
    try:
        campaign = await service.get_accessible_campaign(db, user, campaign_id)
    except MobileError as e:
        _raise(e)
    counts = await service.campaign_counts(db, [campaign.id])
    assignees = await service._assignees(db, [campaign.id])
    agents = {a["agent_id"]: a for a in await service.list_voice_agents(db, user)}
    view = service.campaign_view(campaign, counts.get(campaign.id, {}), assignees=assignees.get(campaign.id, []))
    agent = agents.get(campaign.agent_id)
    view["agent_name"] = agent["name"] if agent else None
    view["did"] = agent["did"] if agent else None
    return view


@router.get("/agents")
async def list_agents(db: AsyncSession = Depends(get_db), user: User = Depends(mobile_user)):
    """Voice agents that can run a mobile campaign (ACTIVE + assigned DID)."""
    return {"agents": await service.list_voice_agents(db, user)}


@router.get("/reps")
async def list_reps(db: AsyncSession = Depends(get_db), user: User = Depends(mobile_user)):
    """Assignable reps (admin campaign creation)."""
    if not service.is_admin(user):
        raise HTTPException(status_code=403, detail={"code": "admin_only", "message": "Only tenant admins can assign reps"})
    return {"reps": await service.list_company_reps(db, user)}


# ── Runs & leases ────────────────────────────────────────────────────────

def _run_view(run) -> Dict[str, Any]:
    return {"run_id": run.id, "campaign_id": run.campaign_id, "device_id": run.device_id,
            "status": run.status, "dial_order": run.dial_order, "started_at": run.started_at,
            "ended_at": run.ended_at}


@router.post("/campaigns/{campaign_id}/runs", status_code=201)
async def start_run(campaign_id: UUID, body: RunStart, db: AsyncSession = Depends(get_db),
                    user: User = Depends(mobile_user)):
    if body.dial_order != "ai_first":
        raise HTTPException(status_code=422, detail={"code": "dial_order_not_supported",
                                                     "message": "Only ai_first is supported"})
    try:
        return _run_view(await service.start_run(db, user, campaign_id, body.device_id))
    except MobileError as e:
        _raise(e)


@router.patch("/runs/{run_id}")
async def update_run(run_id: UUID, body: RunUpdate, db: AsyncSession = Depends(get_db),
                     user: User = Depends(mobile_user)):
    try:
        return _run_view(await service.update_run(db, user, run_id, body.status))
    except MobileError as e:
        _raise(e)


@router.post("/runs/{run_id}/next")
async def next_lead(run_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(mobile_user)):
    try:
        lease = await service.next_lead(db, user, run_id)
    except MobileError as e:
        _raise(e)
    if lease is None:
        return Response(status_code=204)
    return lease


# ── Attempts & events ────────────────────────────────────────────────────

@router.post("/call-attempts", status_code=201)
async def create_attempt(body: AttemptCreate, db: AsyncSession = Depends(get_db),
                         user: User = Depends(mobile_user)):
    try:
        attempt = await service.create_attempt(
            db, user, run_id=body.run_id, campaign_call_id=body.campaign_call_id,
            device_id=body.device_id, assisted=body.assisted,
        )
    except MobileError as e:
        _raise(e)
    return service.attempt_view(attempt)


@router.get("/call-attempts/{attempt_id}")
async def get_attempt(attempt_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(mobile_user)):
    try:
        return await service.attempt_detail(db, user, attempt_id)
    except MobileError as e:
        _raise(e)


@router.post("/call-attempts/{attempt_id}/events")
async def post_events(attempt_id: UUID, body: EventBatch, db: AsyncSession = Depends(get_db),
                      user: User = Depends(mobile_user)):
    try:
        return await service.ingest_events(db, user, attempt_id, [e.model_dump() for e in body.events])
    except MobileError as e:
        _raise(e)
