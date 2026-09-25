"""
Mobile dialer business logic behind /api/v1/mobile (docs 06 §2).

Every public method takes the authenticated ``User`` and scopes by its
company. Errors are raised as ``MobileError`` and mapped to HTTP by the router.
"""
import logging
import secrets
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.campaign_models import Campaign, CampaignCall
from src.auth.models import User
from src.common.config import settings
from src.mobile import realtime
from src.mobile.identification import hash_verification_code
from src.mobile.models import (
    MobileClientLog,
    ATTEMPT_ABANDONED, ATTEMPT_AI_FAILED, ATTEMPT_COMPLETED, ATTEMPT_LEAD_FAILED,
    ATTEMPT_MERGE_FAILED, ATTEMPT_MERGED, ATTEMPT_PENDING, ATTEMPT_SKIPPED,
    ATTEMPT_SUPERSEDED, DEVICE_REVOKED, DEVICE_UNVERIFIED, DEVICE_VERIFIED,
    EXECUTION_MODE_MOBILE, OPEN_ATTEMPT_STATUSES, RUN_COMPLETED, RUN_PAUSED,
    RUN_RUNNING, RUN_STOPPED, CampaignAssignee, MobileCallAttempt,
    MobileCallEvent, MobileCampaignRun, UserDevice,
)
from src.mobile.phone import to_e164

logger = logging.getLogger(__name__)

ADMIN_ROLES = {"tenant_admin"}
MOBILE_ROLES = {"tenant_admin", "tenant_user"}
IST = timezone(timedelta(hours=5, minutes=30))

LEAD_FAILURE_CAUSES = {"busy", "no_answer", "rejected", "unreachable", "invalid", "failed"}


class MobileError(Exception):
    def __init__(self, status_code: int, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        # Merged into the error detail. Lets an error name the thing that is in the
        # way — e.g. device_busy returns the run the rep has to stop — so the app can
        # offer the fix instead of a dead end.
        self.extra = extra


def is_admin(user: User) -> bool:
    return user.role in ADMIN_ROLES


# ── Devices ──────────────────────────────────────────────────────────────

async def _resolve_company_did(db: AsyncSession, company_id: UUID, agent_id: Optional[UUID] = None,
                               provider: Optional[str] = None):
    from src.voice.number_router import NumberRouter

    router = NumberRouter(db)
    for p in ([provider] if provider else ["tata_tele", "twilio"]):
        number = await router.get_company_number(company_id, provider=p, agent_id=agent_id)
        if number:
            return number
    return None


async def issue_device_verification(db: AsyncSession, device: UserDevice) -> Dict[str, Any]:
    number = await _resolve_company_did(db, device.company_id)
    if not number:
        raise MobileError(409, "no_company_did",
                          "Your company has no phone number assigned to a voice agent. Ask your admin to assign one.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    device.verification_code_hash = hash_verification_code(device.id, code)
    device.verification_did = to_e164(number.phone_number)
    device.verification_expires_at = datetime.utcnow() + timedelta(seconds=settings.MOBILE_VERIFICATION_TTL_SECONDS)
    await db.commit()
    return {
        "did": device.verification_did,
        "code": code,
        "dtmf_sequence": f"*{code}#",
        "expires_at": device.verification_expires_at,
    }


async def announce_verification_dial(
    db: AsyncSession, user, device_id, sim_number: Optional[str] = None
) -> Dict[str, Any]:
    """Claim the DID for this device's verification call for the next minute."""
    device = await get_owned_device(db, user, device_id)
    if not device.verification_did or not device.verification_code_hash:
        raise MobileError(409, "no_open_verification",
                          "This phone has no verification in progress. Start setup again.")
    if device.verification_expires_at and device.verification_expires_at <= datetime.utcnow():
        raise MobileError(409, "verification_expired",
                          "The verification expired. Start setup again.")
    recorded = await realtime.announce_verification_dial(
        device.verification_did, device.id, sim_number)
    return {"did": device.verification_did, "recorded": recorded}


def device_view(device: UserDevice, verification: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "device_id": device.id,
        "status": device.status,
        "verified_cli": device.verified_cli,
        "cli_available": device.cli_available,
        "verified_at": device.verified_at,
        "phone_account_label": device.phone_account_label,
        "verification": verification,
    }


async def register_device(db: AsyncSession, user: User, payload: Dict[str, Any]) -> Dict[str, Any]:
    install_id = payload["install_id"]
    device = (await db.execute(select(UserDevice).where(UserDevice.install_id == install_id))).scalar_one_or_none()
    now = datetime.utcnow()
    fields = {k: payload.get(k) for k in ("model", "os_version", "app_version", "fcm_token", "phone_account_label")}

    if device is None:
        device = UserDevice(install_id=install_id, user_id=user.id, company_id=user.company_id,
                            status=DEVICE_UNVERIFIED, **fields)
        db.add(device)
        await db.flush()
    else:
        if device.user_id != user.id or device.company_id != user.company_id:
            # Phone handed to another rep: the old caller-ID binding is void.
            device.user_id = user.id
            device.company_id = user.company_id
            device.status = DEVICE_UNVERIFIED
            device.verified_cli = None
            device.cli_available = False
            device.verified_at = None
        sim_changed = (
            payload.get("phone_account_label")
            and device.phone_account_label
            and payload["phone_account_label"] != device.phone_account_label
        )
        if sim_changed and device.status == DEVICE_VERIFIED:
            device.status = DEVICE_UNVERIFIED
            device.verified_cli = None
            device.cli_available = False
        for k, v in fields.items():
            if v is not None:
                setattr(device, k, v)
    device.last_seen_at = now
    await db.commit()

    verification = None
    if device.status == DEVICE_UNVERIFIED:
        verification = await issue_device_verification(db, device)
    elif device.status == DEVICE_REVOKED:
        raise MobileError(403, "device_revoked", "This device has been revoked by your admin.")
    return device_view(device, verification)


async def get_owned_device(db: AsyncSession, user: User, device_id: UUID) -> UserDevice:
    device = await db.get(UserDevice, device_id)
    if device is None or device.user_id != user.id or device.company_id != user.company_id:
        raise MobileError(404, "device_not_found", "Device not found")
    return device


# ── Campaign access ──────────────────────────────────────────────────────

async def get_accessible_campaign(db: AsyncSession, user: User, campaign_id: UUID) -> Campaign:
    campaign = await db.get(Campaign, campaign_id)
    if campaign is None or campaign.company_id != user.company_id:
        raise MobileError(404, "campaign_not_found", "Campaign not found")
    if campaign.execution_mode != EXECUTION_MODE_MOBILE:
        raise MobileError(409, "not_mobile_campaign", "This campaign is dialed by the server, not the mobile app")
    if not is_admin(user):
        assigned = (await db.execute(
            select(func.count()).select_from(CampaignAssignee).where(and_(
                CampaignAssignee.campaign_id == campaign_id, CampaignAssignee.user_id == user.id,
            ))
        )).scalar_one()
        if not assigned:
            raise MobileError(403, "not_assigned", "You are not assigned to this campaign")
    return campaign


async def campaign_counts(db: AsyncSession, campaign_ids: List[UUID]) -> Dict[UUID, Dict[str, int]]:
    if not campaign_ids:
        return {}
    rows = await db.execute(
        select(CampaignCall.campaign_id, CampaignCall.status, func.count())
        .where(CampaignCall.campaign_id.in_(campaign_ids))
        .group_by(CampaignCall.campaign_id, CampaignCall.status)
    )
    out: Dict[UUID, Dict[str, int]] = {}
    for cid, status, n in rows:
        out.setdefault(cid, {})[status] = n
    interested = await db.execute(
        select(CampaignCall.campaign_id, func.count())
        .where(CampaignCall.campaign_id.in_(campaign_ids), CampaignCall.disposition == "interested")
        .group_by(CampaignCall.campaign_id)
    )
    for cid, n in interested:
        out.setdefault(cid, {})["interested"] = n
    return out


async def list_mobile_campaigns(db: AsyncSession, user: User, status: Optional[str] = None) -> List[Dict[str, Any]]:
    from src.ai.models import HierarchicalEntity

    q = (
        select(Campaign, HierarchicalEntity.display_name, HierarchicalEntity.name)
        .join(HierarchicalEntity, HierarchicalEntity.id == Campaign.agent_id)
        .where(Campaign.company_id == user.company_id, Campaign.execution_mode == EXECUTION_MODE_MOBILE)
        .order_by(Campaign.created_at.desc())
    )
    if status:
        q = q.where(Campaign.status == status)
    if not is_admin(user):
        q = q.join(CampaignAssignee, and_(CampaignAssignee.campaign_id == Campaign.id,
                                          CampaignAssignee.user_id == user.id))
    rows = (await db.execute(q)).all()
    counts = await campaign_counts(db, [r[0].id for r in rows])
    assignees = await _assignees(db, [r[0].id for r in rows])
    return [
        campaign_view(c, counts.get(c.id, {}), agent_name=dn or n, assignees=assignees.get(c.id, []))
        for c, dn, n in rows
    ]


async def _assignees(db: AsyncSession, campaign_ids: List[UUID]) -> Dict[UUID, List[Dict[str, Any]]]:
    if not campaign_ids:
        return {}
    rows = await db.execute(
        select(CampaignAssignee.campaign_id, User.id, User.full_name)
        .join(User, User.id == CampaignAssignee.user_id)
        .where(CampaignAssignee.campaign_id.in_(campaign_ids))
    )
    out: Dict[UUID, List[Dict[str, Any]]] = {}
    for cid, uid, name in rows:
        out.setdefault(cid, []).append({"user_id": uid, "name": name})
    return out


def campaign_view(c: Campaign, counts: Dict[str, int], agent_name: Optional[str] = None,
                  assignees: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    done = sum(counts.get(s, 0) for s in ("completed", "completed-voicemail", "failed", "skipped"))
    return {
        "id": c.id,
        "name": c.name,
        "description": c.description,
        "status": c.status,
        "agent_id": c.agent_id,
        "agent_name": agent_name,
        "provider": c.provider,
        "total_contacts": c.total_contacts,
        "pending": counts.get("pending", 0) + counts.get("leased", 0),
        "completed": counts.get("completed", 0) + counts.get("completed-voicemail", 0),
        "failed": counts.get("failed", 0),
        "skipped": counts.get("skipped", 0),
        "interested": counts.get("interested", 0),
        "done": done,
        "assignees": assignees or [],
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }


async def list_voice_agents(db: AsyncSession, user: User) -> List[Dict[str, Any]]:
    """ACTIVE agents of the company that have an assigned active DID."""
    from src.ai.models import HierarchicalEntity
    from src.voice.phone_pool_models import PhoneNumber

    rows = (await db.execute(
        select(HierarchicalEntity.id, HierarchicalEntity.display_name, HierarchicalEntity.name,
               PhoneNumber.phone_number, PhoneNumber.provider)
        .join(PhoneNumber, PhoneNumber.agent_id == HierarchicalEntity.id)
        .where(
            HierarchicalEntity.company_id == user.company_id,
            HierarchicalEntity.status == "ACTIVE",
            HierarchicalEntity.deleted_at.is_(None),
            PhoneNumber.status == "assigned",
            PhoneNumber.is_active == True,  # noqa: E712
        )
        .order_by(HierarchicalEntity.name)
    )).all()
    seen, out = set(), []
    for aid, dn, n, number, provider in rows:
        if aid in seen:
            continue
        seen.add(aid)
        out.append({"agent_id": aid, "name": dn or n, "did": to_e164(number), "provider": provider})
    return out


async def list_company_reps(db: AsyncSession, user: User) -> List[Dict[str, Any]]:
    rows = (await db.execute(
        select(User.id, User.full_name, User.email, User.role)
        .where(User.company_id == user.company_id, User.is_active == True,  # noqa: E712
               User.role.in_(MOBILE_ROLES))
        .order_by(User.full_name)
    )).all()
    return [{"user_id": r.id, "name": r.full_name, "email": r.email, "role": r.role} for r in rows]


async def set_campaign_assignees(db: AsyncSession, user: User, campaign_id: UUID,
                                 user_ids: List[UUID]) -> List[Dict[str, Any]]:
    """Replace who works a mobile campaign (admins only).

    The same rule as at creation: every assignee is an active tenant user of the
    campaign's company. Leasing does not re-check assignment, so a rep taken off
    mid-run keeps calling until that run ends; they cannot start another.
    """
    if not is_admin(user):
        raise MobileError(403, "admin_only", "Only tenant admins can assign reps")
    campaign = await get_accessible_campaign(db, user, campaign_id)
    requested = list(dict.fromkeys(user_ids))
    if not requested:
        raise MobileError(422, "assignees_required", "Assign at least one rep")
    valid = set((await db.execute(
        select(User.id).where(
            User.id.in_(requested),
            User.company_id == campaign.company_id,
            User.is_active == True,  # noqa: E712
            User.role.in_(MOBILE_ROLES),
        )
    )).scalars().all())
    missing = [uid for uid in requested if uid not in valid]
    if missing:
        raise MobileError(422, "invalid_assignees",
                          f"{len(missing)} assignee(s) are not active tenant users of this company")

    current = set((await db.execute(
        select(CampaignAssignee.user_id).where(CampaignAssignee.campaign_id == campaign.id)
    )).scalars().all())
    removed = current - set(requested)
    if removed:
        await db.execute(delete(CampaignAssignee).where(
            CampaignAssignee.campaign_id == campaign.id, CampaignAssignee.user_id.in_(removed),
        ))
    for uid in requested:
        if uid not in current:
            db.add(CampaignAssignee(campaign_id=campaign.id, user_id=uid))
    await db.commit()
    logger.info("Campaign assignees updated", extra={
        "campaign_id": str(campaign.id), "by": str(user.id),
        "added": len(set(requested) - current), "removed": len(removed),
    })
    return (await _assignees(db, [campaign.id])).get(campaign.id, [])


# ── Runs & leases ────────────────────────────────────────────────────────

async def _get_owned_run(db: AsyncSession, user: User, run_id: UUID) -> MobileCampaignRun:
    run = await db.get(MobileCampaignRun, run_id)
    if run is None or run.user_id != user.id or run.company_id != user.company_id:
        raise MobileError(404, "run_not_found", "Run not found")
    return run


async def start_run(db: AsyncSession, user: User, campaign_id: UUID, device_id: UUID) -> MobileCampaignRun:
    campaign = await get_accessible_campaign(db, user, campaign_id)
    device = await get_owned_device(db, user, device_id)
    if device.status != DEVICE_VERIFIED:
        raise MobileError(409, "device_not_verified", "Verify this phone before running campaigns")
    if campaign.status in ("completed", "failed"):
        raise MobileError(409, "campaign_finished", f"Campaign is {campaign.status}")

    existing = (await db.execute(
        select(MobileCampaignRun).where(and_(
            MobileCampaignRun.device_id == device.id,
            MobileCampaignRun.status.in_((RUN_RUNNING, RUN_PAUSED)),
        ))
    )).scalar_one_or_none()
    if existing:
        if existing.campaign_id == campaign.id:
            existing.status = RUN_RUNNING
            await db.commit()
            return existing
        blocking = await db.get(Campaign, existing.campaign_id)
        raise MobileError(
            409, "device_busy",
            f"This phone is still on \u201c{blocking.name if blocking else 'another campaign'}\u201d.",
            blocking_run_id=str(existing.id),
            blocking_campaign_id=str(existing.campaign_id),
            blocking_campaign_name=blocking.name if blocking else None,
            blocking_run_status=existing.status,
        )

    await _check_credits(db, user.company_id)
    run = MobileCampaignRun(company_id=user.company_id, campaign_id=campaign.id, user_id=user.id,
                            device_id=device.id, status=RUN_RUNNING, dial_order="ai_first")
    db.add(run)
    if campaign.status in ("draft", "scheduled", "paused"):
        campaign.status = "running"
        campaign.started_at = campaign.started_at or datetime.utcnow()
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise MobileError(409, "device_busy", "This phone is already running a campaign")
    await db.refresh(run)
    return run


async def active_runs(db: AsyncSession, user: User) -> List[Dict[str, Any]]:
    """Every run of this user's that is still open, newest first.

    The app keeps the live run in memory only, so a process death, a crash or a
    reinstall used to leave a run that nothing could reach — and `start_run` would
    then refuse the device with no way to clear it. This is how the app finds one
    again and offers to stop it.
    """
    rows = (await db.execute(
        select(MobileCampaignRun, Campaign.name)
        .join(Campaign, Campaign.id == MobileCampaignRun.campaign_id)
        .where(and_(
            MobileCampaignRun.user_id == user.id,
            MobileCampaignRun.status.in_((RUN_RUNNING, RUN_PAUSED)),
        ))
        .order_by(MobileCampaignRun.started_at.desc())
    )).all()
    return [
        {
            "run_id": str(run.id),
            "campaign_id": str(run.campaign_id),
            "campaign_name": name,
            "status": run.status,
            "device_id": str(run.device_id),
            "started_at": run.started_at,
        }
        for run, name in rows
    ]


async def _release_device_leases(db: AsyncSession, device_id: UUID, campaign_id: Optional[UUID] = None) -> None:
    conds = [CampaignCall.status == "leased", CampaignCall.leased_by_device_id == device_id]
    if campaign_id:
        conds.append(CampaignCall.campaign_id == campaign_id)
    await db.execute(
        update(CampaignCall).where(and_(*conds))
        .values(status="pending", leased_by_user_id=None, leased_by_device_id=None, lease_expires_at=None)
    )


async def update_run(db: AsyncSession, user: User, run_id: UUID, status: str) -> MobileCampaignRun:
    run = await _get_owned_run(db, user, run_id)
    if run.status in (RUN_STOPPED, RUN_COMPLETED):
        raise MobileError(409, "run_finished", f"Run is {run.status}")
    if status not in (RUN_RUNNING, RUN_PAUSED, RUN_STOPPED):
        raise MobileError(422, "invalid_status", "status must be running, paused or stopped")
    run.status = status
    if status == RUN_STOPPED:
        run.ended_at = datetime.utcnow()
        await _release_device_leases(db, run.device_id, run.campaign_id)
    await db.commit()
    return run


def _parse_hhmm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def calling_hours_open(now_utc: Optional[datetime] = None) -> bool:
    if not settings.MOBILE_CALLING_HOURS_ENFORCED:
        return True
    now_ist = (now_utc or datetime.utcnow()).replace(tzinfo=timezone.utc).astimezone(IST).time()
    return _parse_hhmm(settings.MOBILE_CALLING_HOURS_START) <= now_ist < _parse_hhmm(settings.MOBILE_CALLING_HOURS_END)


def _ist_day_start_utc(now_utc: Optional[datetime] = None) -> datetime:
    now_ist = (now_utc or datetime.utcnow()).replace(tzinfo=timezone.utc).astimezone(IST)
    start_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_ist.astimezone(timezone.utc).replace(tzinfo=None)


_LEASE_SQL = text("""
UPDATE campaign_calls
SET status = 'leased', leased_by_user_id = :user_id, leased_by_device_id = :device_id,
    lease_expires_at = :lease_until
WHERE id = (
    SELECT cc.id FROM campaign_calls cc
    WHERE cc.campaign_id = :campaign_id
      AND (cc.status = 'pending' OR (cc.status = 'leased' AND cc.lease_expires_at < :now))
      AND (cc.callback_at IS NULL OR cc.callback_at <= :now)
      AND NOT EXISTS (
          SELECT 1 FROM campaign_calls dnc
          JOIN campaigns dc ON dc.id = dnc.campaign_id
          WHERE dc.company_id = :company_id
            AND dnc.disposition = 'do_not_call'
            AND dnc.contact_data->>'phone' = cc.contact_data->>'phone'
      )
    ORDER BY (cc.callback_at IS NOT NULL) DESC, cc.callback_at ASC,
             cc.retry_count ASC, cc.created_at ASC, cc.id ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
RETURNING id, contact_data, lease_expires_at
""")


async def next_lead(db: AsyncSession, user: User, run_id: UUID) -> Optional[Dict[str, Any]]:
    run = await _get_owned_run(db, user, run_id)
    if run.status != RUN_RUNNING:
        raise MobileError(409, "run_not_running", f"Run is {run.status}")
    if not calling_hours_open():
        raise MobileError(423, "outside_calling_hours",
                          f"Calls are allowed {settings.MOBILE_CALLING_HOURS_START}–"
                          f"{settings.MOBILE_CALLING_HOURS_END} IST")
    today = (await db.execute(
        select(func.count()).select_from(MobileCallAttempt).where(and_(
            MobileCallAttempt.user_id == user.id,
            MobileCallAttempt.created_at >= _ist_day_start_utc(),
            MobileCallAttempt.status.notin_((ATTEMPT_SUPERSEDED,)),
        ))
    )).scalar_one()
    if settings.MOBILE_REP_DAILY_ATTEMPT_CAP and today >= settings.MOBILE_REP_DAILY_ATTEMPT_CAP:
        raise MobileError(429, "daily_cap_reached",
                          f"Daily limit of {settings.MOBILE_REP_DAILY_ATTEMPT_CAP} calls reached")

    open_attempt = (await db.execute(
        select(MobileCallAttempt.id).where(and_(
            MobileCallAttempt.device_id == run.device_id,
            MobileCallAttempt.status.in_(OPEN_ATTEMPT_STATUSES),
        ))
    )).scalar_one_or_none()
    if open_attempt:
        raise MobileError(409, "attempt_in_progress", "Finish the current call before taking the next lead")

    now = datetime.utcnow()
    await _release_device_leases(db, run.device_id, run.campaign_id)
    row = (await db.execute(_LEASE_SQL, {
        "user_id": user.id, "device_id": run.device_id, "campaign_id": run.campaign_id,
        "company_id": user.company_id, "now": now,
        "lease_until": now + timedelta(seconds=settings.MOBILE_LEASE_SECONDS),
    })).first()

    if row is None:
        await db.commit()
        remaining = await _remaining_calls(db, run.campaign_id)
        if remaining == 0:
            run.status = RUN_COMPLETED
            run.ended_at = now
            await db.execute(update(Campaign).where(and_(Campaign.id == run.campaign_id, Campaign.status == "running"))
                             .values(status="completed", completed_at=now, updated_at=now))
            await db.commit()
        return None

    await db.commit()
    remaining = await _remaining_calls(db, run.campaign_id)
    return {
        "campaign_call_id": row.id,
        "contact": row.contact_data,
        "lease_expires_at": row.lease_expires_at,
        "remaining": max(remaining - 1, 0),
    }


async def _remaining_calls(db: AsyncSession, campaign_id: UUID) -> int:
    return (await db.execute(
        select(func.count()).select_from(CampaignCall).where(and_(
            CampaignCall.campaign_id == campaign_id,
            CampaignCall.status.in_(("pending", "leased", "calling")),
        ))
    )).scalar_one()


# ── Attempts ─────────────────────────────────────────────────────────────

async def _check_credits(db: AsyncSession, company_id: UUID) -> None:
    from src.billing.credit_service import CreditService, InsufficientCreditsError

    try:
        await CreditService(db).check_sufficient_for_execution(company_id=company_id, entity_type="AGENT")
    except InsufficientCreditsError as e:
        raise MobileError(402, "insufficient_credits", str(e) or "Insufficient credits")


async def create_attempt(db: AsyncSession, user: User, *, run_id: UUID, campaign_call_id: UUID,
                         device_id: UUID, assisted: bool = False) -> MobileCallAttempt:
    run = await _get_owned_run(db, user, run_id)
    if run.device_id != device_id:
        raise MobileError(409, "wrong_device", "This run belongs to another device")
    if run.status != RUN_RUNNING:
        raise MobileError(409, "run_not_running", f"Run is {run.status}")
    device = await get_owned_device(db, user, device_id)
    if device.status != DEVICE_VERIFIED:
        raise MobileError(409, "device_not_verified", "Verify this phone before calling")
    campaign = await db.get(Campaign, run.campaign_id)

    now = datetime.utcnow()
    call = await db.get(CampaignCall, campaign_call_id)
    if (
        call is None or call.campaign_id != run.campaign_id or call.status != "leased"
        or call.leased_by_device_id != device_id
    ):
        raise MobileError(409, "lease_not_held", "This lead is not leased to your phone. Fetch the next lead again.")

    await _check_credits(db, user.company_id)

    number = await _resolve_company_did(db, campaign.company_id, agent_id=campaign.agent_id,
                                        provider=campaign.provider)
    if not number:
        raise MobileError(409, "no_company_did", "The campaign's agent has no assigned phone number")

    superseded = (await db.execute(
        update(MobileCallAttempt)
        .where(and_(MobileCallAttempt.device_id == device_id, MobileCallAttempt.status.in_(OPEN_ATTEMPT_STATUSES)))
        .values(status=ATTEMPT_SUPERSEDED, ended_at=now, end_reason="superseded", updated_at=now)
        .returning(MobileCallAttempt.voice_session_id)
    )).scalars().all()

    call.lease_expires_at = now + timedelta(seconds=settings.MOBILE_LEASE_SECONDS)
    call.called_at = now
    await db.flush()

    did = to_e164(number.phone_number)
    for _ in range(8):
        attempt = MobileCallAttempt(
            company_id=campaign.company_id, campaign_id=campaign.id, campaign_call_id=call.id,
            run_id=run.id, user_id=user.id, device_id=device_id, agent_id=campaign.agent_id,
            device_cli=device.verified_cli, did=did, dtmf_token=f"{secrets.randbelow(10_000):04d}",
            status=ATTEMPT_PENDING, assisted=assisted,
            expires_at=now + timedelta(seconds=settings.MOBILE_ATTEMPT_TTL_SECONDS),
        )
        try:
            async with db.begin_nested():
                db.add(attempt)
            break
        except IntegrityError:
            continue  # token collision among open attempts on this DID
    else:
        await db.rollback()
        raise MobileError(503, "token_exhausted", "Could not allocate a call token, retry shortly")
    await db.commit()
    await db.refresh(attempt)

    for session_id in filter(None, superseded):
        await realtime.publish_session_control(session_id, "abort", reason="superseded")
    return attempt


def attempt_view(a: MobileCallAttempt) -> Dict[str, Any]:
    return {
        "attempt_id": a.id,
        "campaign_id": a.campaign_id,
        "campaign_call_id": a.campaign_call_id,
        "did": a.did,
        "dtmf_token": a.dtmf_token,
        "dtmf_sequence": f"*{a.dtmf_token}#",
        "expires_at": a.expires_at,
        "ident_timeout_seconds": settings.MOBILE_IDENT_TIMEOUT_SECONDS,
        "status": a.status,
        "identification_method": a.identification_method,
        "identification_conflict": a.identification_conflict,
        "voice_session_id": a.voice_session_id,
        "assisted": a.assisted,
        "ai_answered_at": a.ai_answered_at,
        "ai_ready_at": a.ai_ready_at,
        "lead_dialed_at": a.lead_dialed_at,
        "lead_answered_at": a.lead_answered_at,
        "merged_at": a.merged_at,
        "ended_at": a.ended_at,
        "lead_failure_cause": a.lead_failure_cause,
        "end_reason": a.end_reason,
        "conversation_seconds": a.conversation_seconds,
    }


async def get_owned_attempt(db: AsyncSession, user: User, attempt_id: UUID) -> MobileCallAttempt:
    attempt = await db.get(MobileCallAttempt, attempt_id)
    if attempt is None or attempt.user_id != user.id or attempt.company_id != user.company_id:
        raise MobileError(404, "attempt_not_found", "Call attempt not found")
    return attempt


async def attempt_detail(db: AsyncSession, user: User, attempt_id: UUID) -> Dict[str, Any]:
    from src.voice.models import VoiceSession

    attempt = await get_owned_attempt(db, user, attempt_id)
    view = attempt_view(attempt)
    call = await db.get(CampaignCall, attempt.campaign_call_id)
    view["disposition"] = call.disposition if call else None
    view["summary"] = None
    if attempt.voice_session_id:
        session = await db.get(VoiceSession, attempt.voice_session_id)
        if session is not None:
            view["summary"] = (session.context_state or {}).get("call_summary")
    return view


# ── Events ───────────────────────────────────────────────────────────────

INFO_EVENTS = {
    "lease_acquired", "attempt_created", "ai_dialing", "dtmf_sent", "ai_ready_received",
    "ai_held", "lead_ringing", "rep_muted", "rep_unmuted",
}
TERMINAL_EVENTS = {"completed", "rep_hangup", "lead_disconnected", "ai_disconnected"}
KNOWN_EVENTS = INFO_EVENTS | TERMINAL_EVENTS | {
    "ai_answered", "lead_dialing", "lead_answered", "lead_failed", "merged",
    "merge_failed", "ai_failed", "rep_takeover", "skipped",
}


def _parse_device_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
    except ValueError:
        return None


async def ingest_events(db: AsyncSession, user: User, attempt_id: UUID,
                        events: List[Dict[str, Any]]) -> Dict[str, List[int]]:
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    attempt = await get_owned_attempt(db, user, attempt_id)
    accepted: List[int] = []
    duplicates: List[int] = []
    now = datetime.utcnow()
    for ev in sorted(events, key=lambda e: e["seq"]):
        etype = ev["type"]
        if etype not in KNOWN_EVENTS:
            raise MobileError(422, "unknown_event", f"Unknown event type: {etype}")
        inserted = (await db.execute(
            pg_insert(MobileCallEvent)
            .values(attempt_id=attempt.id, seq=ev["seq"], type=etype,
                    device_ts=_parse_device_ts(ev.get("device_ts")), elapsed_ms=ev.get("elapsed_ms"),
                    payload=ev.get("payload") or {}, received_at=now)
            .on_conflict_do_nothing(index_elements=["attempt_id", "seq"])
            .returning(MobileCallEvent.id)
        )).scalar_one_or_none()
        if inserted is None:
            duplicates.append(ev["seq"])
            continue
        accepted.append(ev["seq"])
        await _apply_event(db, attempt, etype, ev.get("payload") or {}, now)
    await db.commit()
    return {"accepted": accepted, "duplicates": duplicates}


async def _finish_campaign_call(db: AsyncSession, attempt: MobileCallAttempt, **values) -> None:
    """Update the leased campaign_call row this attempt holds and drop the lease."""
    await db.execute(
        update(CampaignCall)
        .where(and_(CampaignCall.id == attempt.campaign_call_id,
                    CampaignCall.leased_by_device_id == attempt.device_id,
                    CampaignCall.status == "leased"))
        .values(leased_by_user_id=None, leased_by_device_id=None, lease_expires_at=None, **values)
    )


async def _return_to_pending(db: AsyncSession, attempt: MobileCallAttempt) -> None:
    await _finish_campaign_call(db, attempt, status="pending", retry_count=CampaignCall.retry_count + 1)


async def _apply_event(db: AsyncSession, attempt: MobileCallAttempt, etype: str,
                       payload: Dict[str, Any], now: datetime) -> None:
    is_open = attempt.status in OPEN_ATTEMPT_STATUSES
    session_id = attempt.voice_session_id

    if etype in INFO_EVENTS:
        return
    if etype == "ai_answered":
        attempt.ai_answered_at = attempt.ai_answered_at or now
    elif etype == "lead_dialing":
        attempt.lead_dialed_at = attempt.lead_dialed_at or now
    elif etype == "lead_answered":
        attempt.lead_answered_at = attempt.lead_answered_at or now
        if attempt.lead_dialed_at:
            attempt.lead_ring_seconds = int((attempt.lead_answered_at - attempt.lead_dialed_at).total_seconds())
    elif etype == "merged":
        if is_open and attempt.status != ATTEMPT_MERGED:
            attempt.status = ATTEMPT_MERGED
            attempt.merged_at = now
            await _finish_campaign_call(db, attempt, status="calling")
            await db.flush()
            if session_id:
                await realtime.publish_session_control(session_id, "merged", attempt_id=attempt.id)
    elif etype == "lead_failed":
        cause = str(payload.get("cause") or "failed")
        cause = cause if cause in LEAD_FAILURE_CAUSES else "failed"
        if is_open:
            attempt.status = ATTEMPT_LEAD_FAILED
            attempt.lead_failure_cause = cause
            attempt.ended_at = now
            attempt.end_reason = f"lead_{cause}"
            await _finish_campaign_call(db, attempt, status="failed", outcome=cause, disposition=cause,
                                        completed_at=now)
            if session_id:
                await realtime.publish_session_control(session_id, "abort", reason=f"lead_{cause}")
    elif etype in ("merge_failed", "ai_failed"):
        if is_open:
            attempt.status = ATTEMPT_MERGE_FAILED if etype == "merge_failed" else ATTEMPT_AI_FAILED
            attempt.ended_at = now
            attempt.end_reason = str(payload.get("reason") or etype)[:50]
            await _return_to_pending(db, attempt)
            if session_id:
                await realtime.publish_session_control(session_id, "abort", reason=etype)
    elif etype == "rep_takeover":
        attempt.end_reason = "rep_takeover"
        if session_id:
            await realtime.publish_session_control(session_id, "rep_takeover")
    elif etype == "skipped":
        if is_open:
            attempt.status = ATTEMPT_SKIPPED
            attempt.ended_at = now
            attempt.end_reason = "skipped"
            await _finish_campaign_call(db, attempt, status="skipped", completed_at=now)
            if session_id:
                await realtime.publish_session_control(session_id, "abort", reason="skipped")
    elif etype in TERMINAL_EVENTS:
        if attempt.status == ATTEMPT_MERGED:
            attempt.status = ATTEMPT_COMPLETED
            attempt.ended_at = attempt.ended_at or now
            attempt.end_reason = attempt.end_reason or etype
            if attempt.merged_at:
                attempt.conversation_seconds = int((attempt.ended_at - attempt.merged_at).total_seconds())
        elif is_open:
            # Ended before the lead was merged: the lead was never talked to.
            attempt.status = ATTEMPT_ABANDONED
            attempt.ended_at = now
            attempt.end_reason = etype
            await _return_to_pending(db, attempt)
            if session_id:
                await realtime.publish_session_control(session_id, "abort", reason=etype)
    attempt.updated_at = now


# ── Client logs ──────────────────────────────────────────────────────────

MAX_LOG_ENTRIES = 500
LOG_LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")


async def ingest_logs(db: AsyncSession, user: User, payload: Dict[str, Any]) -> int:
    """Store a batch of app log entries. Never rejects a batch for one bad row —
    losing diagnostics is worse than storing a slightly odd entry."""
    entries = payload.get("entries") or []
    if len(entries) > MAX_LOG_ENTRIES:
        raise MobileError(413, "too_many_entries", f"Send at most {MAX_LOG_ENTRIES} entries per batch")

    def _uuid(value):
        try:
            return UUID(str(value)) if value else None
        except (ValueError, AttributeError, TypeError):
            return None

    device_id = _uuid(payload.get("device_id"))
    app_version = (payload.get("app_version") or "")[:50] or None
    rows = []
    for entry in entries:
        level = str(entry.get("level") or "INFO").upper()
        rows.append(MobileClientLog(
            company_id=user.company_id,
            user_id=user.id,
            device_id=device_id,
            run_id=_uuid(entry.get("run_id")),
            attempt_id=_uuid(entry.get("attempt_id")),
            seq=int(entry.get("seq") or 0),
            level=level if level in LOG_LEVELS else "INFO",
            tag=str(entry.get("tag") or "")[:64],
            message=str(entry.get("message") or "")[:4000],
            fields=entry.get("fields") if isinstance(entry.get("fields"), dict) else {},
            app_version=app_version,
            device_ts=_parse_device_ts(entry.get("device_ts")),
        ))
    db.add_all(rows)
    await db.commit()
    return len(rows)


async def list_logs(db: AsyncSession, user: User, *, device_id: Optional[UUID] = None,
                    attempt_id: Optional[UUID] = None, run_id: Optional[UUID] = None,
                    level: Optional[str] = None, search: Optional[str] = None,
                    since: Optional[datetime] = None, limit: int = 200) -> List[Dict[str, Any]]:
    """Newest-first log view. Tenant users only ever see their own device's logs."""
    conds = [MobileClientLog.company_id == user.company_id]
    if not is_admin(user):
        conds.append(MobileClientLog.user_id == user.id)
    if device_id:
        conds.append(MobileClientLog.device_id == device_id)
    if attempt_id:
        conds.append(MobileClientLog.attempt_id == attempt_id)
    if run_id:
        conds.append(MobileClientLog.run_id == run_id)
    if level:
        wanted = LOG_LEVELS[LOG_LEVELS.index(level.upper()):] if level.upper() in LOG_LEVELS else None
        if wanted:
            conds.append(MobileClientLog.level.in_(wanted))
    if search:
        conds.append(MobileClientLog.message.ilike(f"%{search}%"))
    if since:
        conds.append(MobileClientLog.received_at >= since)

    rows = (await db.execute(
        select(MobileClientLog).where(and_(*conds))
        .order_by(MobileClientLog.received_at.desc(), MobileClientLog.seq.desc())
        .limit(min(limit, 1000))
    )).scalars().all()
    return [{
        "id": r.id, "level": r.level, "tag": r.tag, "message": r.message, "fields": r.fields,
        "device_ts": r.device_ts, "received_at": r.received_at, "attempt_id": r.attempt_id,
        "run_id": r.run_id, "device_id": r.device_id, "seq": r.seq, "app_version": r.app_version,
    } for r in rows]


# ── App version (private distribution) ──────────────────────────────────

def app_version_info(version_code: Optional[int]) -> Dict[str, Any]:
    latest = settings.MOBILE_APP_LATEST_VERSION_CODE
    return {
        "latest_version_code": latest,
        "latest_version_name": settings.MOBILE_APP_LATEST_VERSION_NAME,
        "min_supported_version_code": settings.MOBILE_APP_MIN_SUPPORTED_VERSION_CODE,
        "download_url": settings.MOBILE_APP_DOWNLOAD_URL or None,
        "update_available": version_code is not None and version_code < latest,
        "update_required": version_code is not None and version_code < settings.MOBILE_APP_MIN_SUPPORTED_VERSION_CODE,
    }


# ── Rep-captured outcomes (docs 11 §3.1) ─────────────────────────────────
#
# The model only ever reads a transcript; the rep heard the call. Both answers are
# kept: ``rep_disposition`` is the rep's and nothing else ever writes it, while
# ``disposition`` stays the effective value every existing report reads. The LLM
# pass in voice/websocket_handler.py only fills ``disposition`` when it is NULL,
# so a rep who answers first wins there too.

REP_DISPOSITIONS = {
    "interested", "not_interested", "callback", "wrong_number", "do_not_call", "voicemail",
}
MAX_REP_NOTE = 2000
# How far ahead a callback may be booked. Longer than this is a CRM task, not a dialer one.
MAX_CALLBACK_DAYS = 30


async def _get_owned_call(db: AsyncSession, user: User, campaign_call_id: UUID) -> CampaignCall:
    """A rep may only disposition a lead they called; a tenant admin, any in the company."""
    call = await db.get(CampaignCall, campaign_call_id)
    if call is None:
        raise MobileError(404, "call_not_found", "That lead is not on this device's list")
    campaign = await db.get(Campaign, call.campaign_id)
    if campaign is None or campaign.company_id != user.company_id:
        raise MobileError(404, "call_not_found", "That lead is not on this device's list")
    if not is_admin(user) and call.leased_by_user_id not in (None, user.id):
        raise MobileError(403, "not_your_lead", "Another rep called this lead")
    return call


async def set_rep_disposition(
    db: AsyncSession,
    user: User,
    campaign_call_id: UUID,
    *,
    disposition: str,
    note: Optional[str] = None,
    callback_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    if disposition not in REP_DISPOSITIONS:
        raise MobileError(422, "bad_disposition",
                          f"Choose one of: {', '.join(sorted(REP_DISPOSITIONS))}")
    call = await _get_owned_call(db, user, campaign_call_id)
    now = datetime.utcnow()

    if disposition == "callback":
        if callback_at is None:
            raise MobileError(422, "callback_time_required", "Say when to call back")
        if callback_at.tzinfo is not None:
            callback_at = callback_at.astimezone(timezone.utc).replace(tzinfo=None)
        if callback_at <= now:
            raise MobileError(422, "callback_in_past", "Pick a time in the future")
        if callback_at > now + timedelta(days=MAX_CALLBACK_DAYS):
            raise MobileError(422, "callback_too_far",
                              f"Callbacks can be booked up to {MAX_CALLBACK_DAYS} days ahead")
        # Back into the queue, held by callback_at until it is due (see _LEASE_SQL).
        call.callback_at = callback_at
        call.status = "pending"
        call.leased_by_user_id = None
        call.leased_by_device_id = None
        call.lease_expires_at = None
    else:
        call.callback_at = None

    call.rep_disposition = disposition
    call.rep_note = (note or "").strip()[:MAX_REP_NOTE] or None
    call.rep_dispositioned_at = now
    call.rep_dispositioned_by = user.id
    call.disposition = disposition
    call.disposition_source = "rep"
    call.updated_at = now
    await db.commit()

    logger.info("[Mobile] rep disposition %s for call %s by %s", disposition, call.id, user.id)
    return {
        "campaign_call_id": str(call.id),
        "disposition": disposition,
        "callback_at": call.callback_at,
        "note": call.rep_note,
    }


async def callbacks_due(db: AsyncSession, user: User, *, within_hours: int = 24,
                        limit: int = 50) -> List[Dict[str, Any]]:
    """Leads this rep promised to call back, soonest first. Overdue ones come first."""
    horizon = datetime.utcnow() + timedelta(hours=within_hours)
    scope = [CampaignCall.callback_at.isnot(None), CampaignCall.callback_at <= horizon]
    if is_admin(user):
        company_campaigns = select(Campaign.id).where(Campaign.company_id == user.company_id)
        scope.append(CampaignCall.campaign_id.in_(company_campaigns))
    else:
        scope.append(CampaignCall.rep_dispositioned_by == user.id)
    rows = (await db.execute(
        select(CampaignCall, Campaign.name)
        .join(Campaign, Campaign.id == CampaignCall.campaign_id)
        .where(and_(*scope))
        .order_by(CampaignCall.callback_at.asc())
        .limit(limit)
    )).all()
    out = []
    for call, campaign_name in rows:
        contact = call.contact_data or {}
        out.append({
            "campaign_call_id": str(call.id),
            "campaign_id": str(call.campaign_id),
            "campaign_name": campaign_name,
            "contact_name": contact.get("name") or contact.get("Name"),
            "phone_masked": mask_phone(contact.get("phone")),
            "callback_at": call.callback_at,
            "note": call.rep_note,
        })
    return out


def mask_phone(phone: Optional[str]) -> str:
    """Matches the masking used everywhere else: keep the country code and last four."""
    if not phone:
        return ""
    digits = str(phone)
    if len(digits) <= 7:
        return digits
    return f"{digits[:3]}{'•' * (len(digits) - 7)}{digits[-4:]}"


# ── Pre-flight (docs 11 §3, screen 13) ───────────────────────────────────
#
# Every condition here is already enforced somewhere; the app just had no way to
# read them before a run, so a rep met each one as a failed call instead.

async def preflight(db: AsyncSession, user: User, *, campaign_id: Optional[UUID] = None,
                    device_id: Optional[UUID] = None) -> Dict[str, Any]:
    now = datetime.utcnow()

    used_today = (await db.execute(
        select(func.count()).select_from(MobileCallAttempt).where(and_(
            MobileCallAttempt.user_id == user.id,
            MobileCallAttempt.created_at >= _ist_day_start_utc(now),
            MobileCallAttempt.status.notin_((ATTEMPT_SUPERSEDED,)),
        ))
    )).scalar_one()
    cap = settings.MOBILE_REP_DAILY_ATTEMPT_CAP or 0

    credits_ok, credits_message = True, None
    try:
        await _check_credits(db, user.company_id)
    except MobileError as e:
        credits_ok, credits_message = False, e.message

    device: Optional[UserDevice] = None
    if device_id is not None:
        device = await db.get(UserDevice, device_id)
        if device is not None and device.user_id != user.id:
            device = None

    result: Dict[str, Any] = {
        "checked_at": now,
        "calling_window": {
            "enforced": settings.MOBILE_CALLING_HOURS_ENFORCED,
            "open": calling_hours_open(now),
            "start": settings.MOBILE_CALLING_HOURS_START,
            "end": settings.MOBILE_CALLING_HOURS_END,
            "timezone": "Asia/Kolkata",
        },
        "daily_cap": {
            "limit": cap or None,
            "used": used_today,
            "remaining": max(cap - used_today, 0) if cap else None,
        },
        "credits": {"ok": credits_ok, "message": credits_message},
        "device": {
            "verified": bool(device and device.status == DEVICE_VERIFIED),
            "phone_account_label": device.phone_account_label if device else None,
            "verified_cli": device.verified_cli if device else None,
        },
        "campaign": None,
    }

    if campaign_id is not None:
        from src.ai.models import HierarchicalEntity

        campaign = await get_accessible_campaign(db, user, campaign_id)
        pending = await _remaining_calls(db, campaign.id)
        did, agent_name = None, None
        # Returns a PhoneNumber row, not a string.
        number = await _resolve_company_did(db, user.company_id, campaign.agent_id,
                                            provider=campaign.provider)
        if number is not None:
            did = to_e164(number.phone_number)
        agent = await db.get(HierarchicalEntity, campaign.agent_id) if campaign.agent_id else None
        if agent is not None:
            agent_name = agent.display_name or agent.name
        result["campaign"] = {
            "id": str(campaign.id),
            "name": campaign.name,
            "pending": pending,
            "agent_name": agent_name,
            "did": did,
            "ready": bool(did) and pending > 0,
        }

    blockers = []
    if not result["calling_window"]["open"]:
        blockers.append("outside_calling_hours")
    if cap and used_today >= cap:
        blockers.append("daily_cap_reached")
    if not credits_ok:
        blockers.append("insufficient_credits")
    if device_id is not None and not result["device"]["verified"]:
        blockers.append("device_not_verified")
    if result["campaign"] is not None and not result["campaign"]["ready"]:
        blockers.append("no_did" if not result["campaign"]["did"] else "no_leads")
    result["blockers"] = blockers
    result["can_start"] = not blockers
    return result
