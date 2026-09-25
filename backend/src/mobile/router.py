"""
/api/v1/mobile — REST API for the Android dialer app (docs 06 §2).

Only tenant_admin and tenant_user may call these endpoints; everything is
scoped to the caller's company.
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.common.database import get_db
from src.mobile import campaign_setup, service
from src.mobile.service import MobileError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mobile", tags=["Mobile Dialer"])


async def mobile_user(user: User = Depends(get_current_user)) -> User:
    if user.role not in service.MOBILE_ROLES:
        raise HTTPException(status_code=403, detail={
            "code": "role_not_supported",
            "message": "The mobile app is for tenant admins and tenant users. Please use the web app.",
            # Lets the app's role gate say whose account this is and what it is, rather
            # than a bare sentence (wireframe 03). Only the caller's own details.
            "role": user.role,
            "full_name": user.full_name,
            "email": user.email,
        })
    return user


def _raise(e: MobileError):
    detail = {"code": e.code, "message": e.message}
    detail.update(getattr(e, "extra", None) or {})
    raise HTTPException(status_code=e.status_code, detail=detail)


# ── Schemas ──────────────────────────────────────────────────────────────

class DeviceRegister(BaseModel):
    install_id: str = Field(min_length=8, max_length=64)
    model: Optional[str] = Field(default=None, max_length=100)
    os_version: Optional[str] = Field(default=None, max_length=30)
    app_version: Optional[str] = Field(default=None, max_length=50)
    fcm_token: Optional[str] = Field(default=None, max_length=512)
    phone_account_label: Optional[str] = Field(default=None, max_length=100)


class VerificationDialing(BaseModel):
    # Best effort: most Indian SIMs report nothing, and the server copes.
    sim_number: Optional[str] = Field(default=None, max_length=30)


class RunStart(BaseModel):
    device_id: UUID
    dial_order: str = "ai_first"


class RepDisposition(BaseModel):
    """The wrap-up sheet's answer (docs 11 §3.1, screen 18)."""
    disposition: str
    note: Optional[str] = Field(default=None, max_length=2000)
    # Required when disposition == "callback". UTC; the app sends an absolute time.
    callback_at: Optional[datetime] = None


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


class LogEntry(BaseModel):
    seq: int = 0
    level: str = "INFO"
    tag: str = ""
    message: str = ""
    fields: Dict[str, Any] = Field(default_factory=dict)
    device_ts: Optional[str] = None
    run_id: Optional[str] = None
    attempt_id: Optional[str] = None


class LogBatch(BaseModel):
    device_id: Optional[str] = None
    app_version: Optional[str] = None
    entries: List[LogEntry] = Field(min_length=1, max_length=500)


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


@router.post("/devices/{device_id}/verification/dialing")
async def verification_dialing(device_id: UUID, body: VerificationDialing,
                               db: AsyncSession = Depends(get_db), user: User = Depends(mobile_user)):
    """The app is placing the verification call now (lets the server fall back to
    caller ID if the provider drops the keypad tones)."""
    try:
        return await service.announce_verification_dial(
            db, user, device_id, body.sim_number)
    except MobileError as e:
        _raise(e)


# ── Campaign helpers ─────────────────────────────────────────────────────

@router.get("/campaigns")
async def list_campaigns(status: Optional[str] = None, db: AsyncSession = Depends(get_db),
                         user: User = Depends(mobile_user)):
    campaigns = await service.list_mobile_campaigns(db, user, status)
    # The same DID lookup as GET /campaigns/{id}. Without it the app cannot tell a
    # campaign whose agent has no number from one that simply was not told the number,
    # and flagged every unfinished campaign as needing attention.
    agents = {a["agent_id"]: a for a in await service.list_voice_agents(db, user)}
    for view in campaigns:
        agent = agents.get(view.get("agent_id"))
        view["did"] = agent["did"] if agent else None
    return {"campaigns": campaigns}


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


class AssigneesUpdate(BaseModel):
    user_ids: List[UUID] = Field(..., min_length=1, max_length=200)


@router.put("/campaigns/{campaign_id}/assignees")
async def set_assignees(campaign_id: UUID, body: AssigneesUpdate, db: AsyncSession = Depends(get_db),
                        user: User = Depends(mobile_user)):
    """Replace the reps working a campaign (admins only). Returns the new assignee list."""
    try:
        return {"assignees": await service.set_campaign_assignees(db, user, campaign_id, body.user_ids)}
    except MobileError as e:
        _raise(e)


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


@router.post("/logs")
async def post_logs(body: LogBatch, db: AsyncSession = Depends(get_db), user: User = Depends(mobile_user)):
    """App diagnostics (docs 10 §6). Stored permanently so field-only failures —
    carrier merge behaviour above all — can be debugged after the fact."""
    try:
        accepted = await service.ingest_logs(db, user, body.model_dump())
    except MobileError as e:
        _raise(e)
    return {"accepted": accepted}


@router.get("/logs")
async def get_logs(
    device_id: Optional[UUID] = None,
    attempt_id: Optional[UUID] = None,
    run_id: Optional[UUID] = None,
    level: Optional[str] = None,
    search: Optional[str] = None,
    since_minutes: Optional[int] = Query(default=None, ge=1, le=20160),
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(mobile_user),
):
    """Read the logs back (newest first). Reps see their own; tenant admins see the company."""
    since = datetime.utcnow() - timedelta(minutes=since_minutes) if since_minutes else None
    entries = await service.list_logs(
        db, user, device_id=device_id, attempt_id=attempt_id, run_id=run_id,
        level=level, search=search, since=since, limit=limit,
    )
    return {"total": len(entries), "entries": entries}


@router.post("/call-attempts/{attempt_id}/events")
async def post_events(attempt_id: UUID, body: EventBatch, db: AsyncSession = Depends(get_db),
                      user: User = Depends(mobile_user)):
    try:
        return await service.ingest_events(db, user, attempt_id, [e.model_dump() for e in body.events])
    except MobileError as e:
        _raise(e)


# ── Rep-captured outcomes, callbacks & pre-flight ────────────────────────

@router.patch("/campaign-calls/{campaign_call_id}/disposition")
async def set_disposition(campaign_call_id: UUID, body: RepDisposition,
                          db: AsyncSession = Depends(get_db), user: User = Depends(mobile_user)):
    """What the rep heard. Wins over the model's guess; see service.set_rep_disposition."""
    try:
        return await service.set_rep_disposition(
            db, user, campaign_call_id,
            disposition=body.disposition, note=body.note, callback_at=body.callback_at,
        )
    except MobileError as e:
        _raise(e)


@router.get("/callbacks")
async def get_callbacks(
    within_hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(mobile_user),
):
    """Leads this rep promised to call back, soonest first."""
    items = await service.callbacks_due(db, user, within_hours=within_hours, limit=limit)
    return {"total": len(items), "items": items}


@router.get("/uploads/recent")
async def recent_uploads(db: AsyncSession = Depends(get_db), user: User = Depends(mobile_user)):
    """Contact uploads this user can still turn into a campaign (unused, unexpired)."""
    return {"uploads": await campaign_setup.recent_uploads(db, user)}


@router.get("/leads/lookup")
async def lookup_lead(
    phone: str = Query(..., min_length=4, max_length=32),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(mobile_user),
):
    """The lead behind an incoming caller ID, or null. Read-only."""
    return {"lead": await service.lookup_lead(db, user, phone)}


@router.get("/runs/active")
async def get_active_runs(db: AsyncSession = Depends(get_db), user: User = Depends(mobile_user)):
    """Runs of this user's that are still open.

    The app holds the live run in memory only; after a crash, a force-stop or a
    reinstall this is the only way back to it. Without it a stale run pins the device
    and `start_run` refuses every campaign with nothing able to clear it."""
    runs = await service.active_runs(db, user)
    return {"total": len(runs), "items": runs}


@router.get("/preflight")
async def get_preflight(
    campaign_id: Optional[UUID] = None,
    device_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(mobile_user),
):
    """Everything that decides whether a run can start, in one call (docs 11 §3, screen 13).

    Each condition is already enforced elsewhere; the app previously met them all as
    failed calls instead of as a check."""
    try:
        return await service.preflight(db, user, campaign_id=campaign_id, device_id=device_id)
    except MobileError as e:
        _raise(e)
