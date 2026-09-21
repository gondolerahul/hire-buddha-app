"""
Lead identification for inbound AI legs placed by the mobile app (ADR-001).

Webhook path (HTTP, <2 s budget):   resolve_mobile_inbound()
  1. caller-ID match -> session bound to the attempt (method "cli")
  2. DID has open attempts / device verifications -> unbound mobile session;
     the stream handler waits for a DTMF token or verification code
  3. nothing mobile-related -> None (caller continues the normal inbound flow)

Stream path (gateway):  bind_session_by_token(), complete_device_verification()
"""
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from uuid import NAMESPACE_DNS, UUID, uuid5

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.config import settings
from src.mobile import realtime
from src.mobile.models import (
    ATTEMPT_AI_CONNECTED, ATTEMPT_PENDING, BINDABLE_ATTEMPT_STATUSES,
    DEVICE_UNVERIFIED, DEVICE_VERIFIED, IDENT_CLI, IDENT_CLI_DTMF, IDENT_DTMF,
    SESSION_MODE_MOBILE, MobileCallAttempt, UserDevice,
)
from src.mobile.phone import same_subscriber, to_e164
from src.voice.models import VoiceSession

logger = logging.getLogger(__name__)


def lead_customer_id(company_id, lead_phone: str) -> UUID:
    """Deterministic voice_sessions.customer_id per lead, so conversation
    history carries across repeat calls to the same lead."""
    return uuid5(NAMESPACE_DNS, f"lead:{company_id}:{lead_phone}")


def hash_verification_code(device_id, code: str) -> str:
    return hashlib.sha256(f"{device_id}:{code}".encode()).hexdigest()


def is_mobile_session(session: Optional[VoiceSession]) -> bool:
    return bool(session and (session.session_metadata or {}).get("mode") == SESSION_MODE_MOBILE)


async def _attempt_context(db: AsyncSession, attempt: MobileCallAttempt) -> Dict[str, Any]:
    """Lead contact + names injected into the agent prompt."""
    from src.ai.campaign_models import CampaignCall
    from src.auth.models import Company, User

    contact = (await db.execute(
        select(CampaignCall.contact_data).where(CampaignCall.id == attempt.campaign_call_id)
    )).scalar_one_or_none() or {}
    rep_name = (await db.execute(select(User.full_name).where(User.id == attempt.user_id))).scalar_one_or_none()
    company_name = (await db.execute(select(Company.name).where(Company.id == attempt.company_id))).scalar_one_or_none()
    return {
        "contact_data": dict(contact),
        "rep_name": rep_name or "",
        "company_name": company_name or "",
    }


def _bound_metadata(base: Dict[str, Any], attempt: MobileCallAttempt, ctx: Dict[str, Any],
                    method: str, conflict: bool = False) -> Dict[str, Any]:
    meta = dict(base or {})
    meta.update({
        "mode": SESSION_MODE_MOBILE,
        "bound": True,
        "attempt_id": str(attempt.id),
        "campaign_id": str(attempt.campaign_id),
        "campaign_call_id": str(attempt.campaign_call_id),
        "user_id": str(attempt.user_id),
        "device_id": str(attempt.device_id),
        "contact_data": ctx["contact_data"],
        "rep_name": ctx["rep_name"],
        "company_name": ctx["company_name"],
        "identification": {
            "method": method,
            "at": datetime.utcnow().isoformat() + "Z",
            "conflict": conflict,
        },
    })
    return meta


async def resolve_mobile_inbound(
    db: AsyncSession,
    *,
    from_number: Optional[str],
    to_number: Optional[str],
    call_sid: str,
    provider: str,
    raw_metadata: Optional[Dict[str, Any]] = None,
) -> Optional[VoiceSession]:
    """Create a voice session for a mobile AI leg, or return None."""
    from_e164, did = to_e164(from_number), to_e164(to_number)
    if not did:
        return None
    now = datetime.utcnow()
    base_meta = {"provider_payload": raw_metadata or {}, "did": did, "caller": from_e164,
                 "presented_from": from_number}

    # 1. Caller-ID match — claim the newest open attempt atomically.
    if from_e164:
        claimed = (await db.execute(
            update(MobileCallAttempt)
            .where(MobileCallAttempt.id == (
                select(MobileCallAttempt.id)
                .where(and_(
                    MobileCallAttempt.device_cli == from_e164,
                    MobileCallAttempt.did == did,
                    MobileCallAttempt.status == ATTEMPT_PENDING,
                    MobileCallAttempt.expires_at > now,
                ))
                .order_by(MobileCallAttempt.created_at.desc())
                .limit(1)
                .with_for_update(skip_locked=True)
                .scalar_subquery()
            ))
            .values(status=ATTEMPT_AI_CONNECTED, identification_method=IDENT_CLI, updated_at=now)
            .returning(MobileCallAttempt)
        )).scalar_one_or_none()
        if claimed:
            ctx = await _attempt_context(db, claimed)
            lead_phone = ctx["contact_data"].get("phone") or ""
            session = VoiceSession(
                company_id=claimed.company_id,
                customer_id=lead_customer_id(claimed.company_id, lead_phone),
                agent_id=claimed.agent_id,
                phone_number=lead_phone or from_e164,
                provider=provider,
                call_sid=call_sid,
                direction="inbound",
                status="active",
                session_metadata=_bound_metadata(base_meta, claimed, ctx, IDENT_CLI),
                context_state={},
            )
            db.add(session)
            await db.flush()
            claimed.voice_session_id = session.id
            await db.commit()
            await db.refresh(session)
            logger.info(f"[Mobile] AI leg {call_sid} bound by CLI to attempt {claimed.id} (session {session.id})")
            return session

    # 2. Unbound: only when this DID is actually expecting a mobile call.
    open_attempts = (await db.execute(
        select(func.count()).select_from(MobileCallAttempt).where(and_(
            MobileCallAttempt.did == did,
            MobileCallAttempt.status == ATTEMPT_PENDING,
            MobileCallAttempt.expires_at > now,
        ))
    )).scalar_one()
    open_verifications = (await db.execute(
        select(func.count()).select_from(UserDevice).where(and_(
            UserDevice.verification_did == did,
            UserDevice.verification_expires_at > now,
            UserDevice.verification_code_hash.isnot(None),
        ))
    )).scalar_one()
    if not open_attempts and not open_verifications:
        return None

    from src.voice.number_router import NumberRouter
    assignment = await NumberRouter(db).find_customer_by_number(did)
    if not assignment:
        logger.warning(f"[Mobile] DID {did} has open attempts but no active assignment")
        return None

    known_device = False
    if from_e164:
        known_device = (await db.execute(
            select(func.count()).select_from(UserDevice).where(and_(
                UserDevice.company_id == assignment.company_id,
                UserDevice.verified_cli == from_e164,
                UserDevice.status == DEVICE_VERIFIED,
            ))
        )).scalar_one() > 0

    meta = dict(base_meta)
    meta.update({
        "mode": SESSION_MODE_MOBILE,
        "bound": False,
        "expects_attempt": bool(open_attempts),
        "expects_verification": bool(open_verifications),
        # An unknown caller on a DID that is merely *expecting* a mobile call
        # may be a genuine inbound customer: if no code arrives, the handler
        # falls back to the normal inbound flow instead of hanging up.
        "fallback_inbound": not known_device,
    })
    session = VoiceSession(
        company_id=assignment.company_id,
        customer_id=assignment.customer_id or uuid5(NAMESPACE_DNS, f"caller:{from_e164 or call_sid}"),
        agent_id=assignment.agent_id,
        phone_number=from_e164 or (from_number or ""),
        provider=provider,
        call_sid=call_sid,
        direction="inbound",
        status="active",
        session_metadata=meta,
        context_state={},
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    logger.info(
        f"[Mobile] AI leg {call_sid} on {did} unbound (attempts={open_attempts}, "
        f"verifications={open_verifications}, known_device={known_device}); awaiting DTMF"
    )
    return session


@dataclass
class BindResult:
    status: str  # "bound" | "confirmed" | "rebound" | "no_match"
    attempt_id: Optional[UUID] = None
    method: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    agent_id: Optional[UUID] = None
    customer_id: Optional[UUID] = None
    phone_number: Optional[str] = None
    user_id: Optional[UUID] = None


async def bind_session_by_token(db: AsyncSession, session_id: UUID, token: str) -> BindResult:
    """Apply a DTMF attempt token to a mobile session (ADR-001 §4)."""
    session = await db.get(VoiceSession, session_id)
    if session is None:
        return BindResult("no_match")
    meta = dict(session.session_metadata or {})
    did = meta.get("did")
    current_attempt_id = meta.get("attempt_id")
    now = datetime.utcnow()

    attempt = (await db.execute(
        select(MobileCallAttempt).where(and_(
            MobileCallAttempt.company_id == session.company_id,
            MobileCallAttempt.did == did,
            MobileCallAttempt.dtmf_token == token,
            MobileCallAttempt.expires_at > now - timedelta(seconds=settings.MOBILE_MERGE_WAIT_SECONDS),
        )).order_by(MobileCallAttempt.created_at.desc()).limit(1).with_for_update()
    )).scalar_one_or_none()
    if attempt is None:
        logger.warning(f"[Mobile] DTMF token matched no attempt for session {session_id}")
        return BindResult("no_match")

    # Same attempt already CLI-bound to this session: confirmation.
    if current_attempt_id and str(attempt.id) == current_attempt_id:
        attempt.identification_method = IDENT_CLI_DTMF
        meta["identification"] = {**meta.get("identification", {}), "method": IDENT_CLI_DTMF,
                                  "confirmed_at": now.isoformat() + "Z"}
        session.session_metadata = meta
        await db.commit()
        return BindResult("confirmed", attempt.id, IDENT_CLI_DTMF, meta, session.agent_id,
                          session.customer_id, session.phone_number, attempt.user_id)

    if attempt.status not in BINDABLE_ATTEMPT_STATUSES or (
        attempt.voice_session_id and attempt.voice_session_id != session.id
    ):
        logger.warning(
            f"[Mobile] DTMF token for attempt {attempt.id} ignored: status={attempt.status}, "
            f"session={attempt.voice_session_id}"
        )
        return BindResult("no_match")

    conflict = bool(current_attempt_id)
    if conflict:
        # CLI picked the wrong attempt — DTMF wins. Release the wrongly bound
        # attempt so its own AI leg can still bind when it arrives.
        await db.execute(
            update(MobileCallAttempt)
            .where(MobileCallAttempt.id == UUID(current_attempt_id))
            .values(status=ATTEMPT_PENDING, voice_session_id=None, identification_method=None, updated_at=now)
        )
        logger.warning(f"[Mobile] Identification conflict on session {session_id}: "
                       f"CLI attempt {current_attempt_id} -> DTMF attempt {attempt.id}")

    ctx = await _attempt_context(db, attempt)
    lead_phone = ctx["contact_data"].get("phone") or session.phone_number
    attempt.status = ATTEMPT_AI_CONNECTED
    attempt.voice_session_id = session.id
    attempt.identification_method = IDENT_DTMF
    attempt.identification_conflict = conflict
    new_meta = _bound_metadata(meta, attempt, ctx, IDENT_DTMF, conflict)
    new_meta.pop("fallback_inbound", None)
    session.session_metadata = new_meta
    session.agent_id = attempt.agent_id
    session.customer_id = lead_customer_id(attempt.company_id, lead_phone)
    session.phone_number = lead_phone
    await db.commit()
    logger.info(f"[Mobile] Session {session_id} bound by DTMF to attempt {attempt.id} (conflict={conflict})")
    return BindResult("rebound" if conflict else "bound", attempt.id, IDENT_DTMF, new_meta,
                      attempt.agent_id, session.customer_id, lead_phone, attempt.user_id)


@dataclass
class VerificationResult:
    device_id: UUID
    user_id: UUID
    verified_cli: Optional[str]
    cli_available: bool


async def complete_device_verification(
    db: AsyncSession, session_id: UUID, code: str
) -> Optional[VerificationResult]:
    """Match a 6-digit code to an open device verification on this session's DID."""
    session = await db.get(VoiceSession, session_id)
    if session is None:
        return None
    meta = session.session_metadata or {}
    did = meta.get("did")
    now = datetime.utcnow()
    candidates = (await db.execute(
        select(UserDevice).where(and_(
            UserDevice.company_id == session.company_id,
            UserDevice.verification_did == did,
            UserDevice.verification_expires_at > now,
            UserDevice.verification_code_hash.isnot(None),
        )).with_for_update()
    )).scalars().all()
    for device in candidates:
        if device.verification_code_hash == hash_verification_code(device.id, code):
            caller = meta.get("caller")
            device.presented_cli = (meta.get("presented_from") or "")[:40] or None
            device.verified_cli = caller
            device.cli_available = bool(caller)
            device.status = DEVICE_VERIFIED
            device.verified_at = now
            device.verification_code_hash = None
            device.verification_expires_at = None
            await db.commit()
            logger.info(f"[Mobile] Device {device.id} verified (cli_available={bool(caller)})")
            return VerificationResult(device.id, device.user_id, caller, bool(caller))
    logger.warning(f"[Mobile] Verification code on session {session_id} matched no device")
    return None


async def verify_device_by_cli(db: AsyncSession, session_id: UUID) -> Optional[VerificationResult]:
    """Fallback for complete_device_verification() when no DTMF arrived.

    Some carrier/provider combinations silently drop the keypad tones on the AI
    leg, which would leave a rep unable to finish setup at all. The caller ID is
    what the verification call exists to capture (ADR-001 §1), so the code is
    not the only way to trust the call — but it must be *this* call, so the app
    announces the dial (``realtime.announce_verification_dial``) a moment before
    placing it, and only the device named in that announcement can be verified.
    An inbound caller who happens to ring the DID matches nothing.
    """
    session = await db.get(VoiceSession, session_id)
    if session is None:
        return None
    meta = session.session_metadata or {}
    did, caller = meta.get("did"), meta.get("caller")
    if not caller:
        logger.warning(f"[Mobile] No caller ID on session {session_id}; cannot verify without a code")
        return None
    dial = await realtime.pending_verification_dial(did)
    if not dial:
        logger.info(f"[Mobile] No app announced a verification call on {did}; not verifying by caller ID")
        return None
    sim_number = dial.get("sim_number")
    if sim_number and not same_subscriber(sim_number, caller):
        logger.warning(
            f"[Mobile] Caller ID {caller} on {did} is not the SIM the app announced; not verifying"
        )
        return None
    now = datetime.utcnow()
    device = (await db.execute(
        select(UserDevice).where(and_(
            UserDevice.id == UUID(dial["device_id"]),
            UserDevice.company_id == session.company_id,
            UserDevice.verification_did == did,
            UserDevice.verification_expires_at > now,
            UserDevice.verification_code_hash.isnot(None),
        )).with_for_update()
    )).scalar_one_or_none()
    if device is None:
        logger.warning(f"[Mobile] Announced device for {did} has no open verification; not verifying")
        return None
    other_owner = (await db.execute(
        select(func.count()).select_from(UserDevice).where(and_(
            UserDevice.company_id == session.company_id,
            UserDevice.verified_cli == caller,
            UserDevice.status == DEVICE_VERIFIED,
            UserDevice.user_id != device.user_id,
        ))
    )).scalar_one()
    if other_owner:
        logger.warning(f"[Mobile] Caller ID {caller} already belongs to another rep; not verifying {device.id}")
        return None
    await realtime.clear_verification_dial(did)
    device.presented_cli = (meta.get("presented_from") or "")[:40] or None
    device.verified_cli = caller
    device.cli_available = True
    device.status = DEVICE_VERIFIED
    device.verified_at = now
    device.verification_code_hash = None
    device.verification_expires_at = None
    await db.commit()
    logger.warning(f"[Mobile] Device {device.id} verified by caller ID alone (no DTMF reached the server)")
    return VerificationResult(device.id, device.user_id, caller, True)
