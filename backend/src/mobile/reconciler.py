"""
Periodic mobile-dialer housekeeping (Arq cron, every 5 minutes).

1. Post-call reconciliation (ADR-001 §6): an AI leg that ended ``unidentified``
   is matched to the attempt of the device whose caller ID it came from, when
   the app-reported ``ai_answered_at`` is within the reconcile window of the
   session start. Never crosses company or device.
2. Expiry: pending attempts whose AI leg never arrived become ``expired`` and
   release their lead.
3. Stuck calls: campaign calls left ``calling`` by a merged attempt whose
   handler never cleaned up are closed after 2 h.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import and_, select, update

from src.common.config import settings
from src.common.database import AsyncSessionLocal
from src.mobile.models import (
    ATTEMPT_EXPIRED, ATTEMPT_PENDING, IDENT_RECONCILED, IDENT_UNIDENTIFIED,
    SESSION_MODE_MOBILE, MobileCallAttempt, UserDevice,
)

logger = logging.getLogger(__name__)


async def reconcile_unidentified_sessions(db) -> int:
    from src.ai.campaign_models import CampaignCall
    from src.voice.models import VoiceSession

    since = datetime.utcnow() - timedelta(days=1)
    sessions = (await db.execute(
        select(VoiceSession).where(and_(
            VoiceSession.status == "ended",
            VoiceSession.started_at >= since,
            VoiceSession.session_metadata["mode"].astext == SESSION_MODE_MOBILE,
            VoiceSession.session_metadata["identification"]["method"].astext == IDENT_UNIDENTIFIED,
        ))
    )).scalars().all()

    window = timedelta(seconds=settings.MOBILE_RECONCILE_WINDOW_SECONDS)
    fixed = 0
    for session in sessions:
        meta = dict(session.session_metadata or {})
        caller = meta.get("caller")
        if not caller:
            continue
        attempt = (await db.execute(
            select(MobileCallAttempt)
            .join(UserDevice, UserDevice.id == MobileCallAttempt.device_id)
            .where(and_(
                MobileCallAttempt.company_id == session.company_id,
                UserDevice.company_id == session.company_id,
                UserDevice.verified_cli == caller,
                MobileCallAttempt.voice_session_id.is_(None),
                MobileCallAttempt.ai_answered_at.isnot(None),
                MobileCallAttempt.ai_answered_at.between(session.started_at - window, session.started_at + window),
            ))
            .order_by(MobileCallAttempt.created_at.desc())
            .limit(2)
        )).scalars().all()
        if len(attempt) != 1:
            continue  # none, or ambiguous — leave it for a human
        a = attempt[0]
        a.voice_session_id = session.id
        a.identification_method = IDENT_RECONCILED
        meta["identification"] = {**meta.get("identification", {}), "method": IDENT_RECONCILED,
                                  "reconciled_at": datetime.utcnow().isoformat() + "Z"}
        meta["attempt_id"] = str(a.id)
        session.session_metadata = meta
        await db.execute(
            update(CampaignCall)
            .where(and_(CampaignCall.id == a.campaign_call_id, CampaignCall.voice_session_id.is_(None)))
            .values(voice_session_id=session.id)
        )
        fixed += 1
    await db.commit()
    return fixed


async def expire_stale_attempts(db) -> int:
    from src.ai.campaign_models import CampaignCall

    now = datetime.utcnow()
    expired = (await db.execute(
        update(MobileCallAttempt)
        .where(and_(MobileCallAttempt.status == ATTEMPT_PENDING, MobileCallAttempt.expires_at < now))
        .values(status=ATTEMPT_EXPIRED, ended_at=now, end_reason="ai_leg_never_arrived", updated_at=now)
        .returning(MobileCallAttempt.campaign_call_id, MobileCallAttempt.device_id)
    )).all()
    for call_id, device_id in expired:
        await db.execute(
            update(CampaignCall)
            .where(and_(CampaignCall.id == call_id, CampaignCall.status == "leased",
                        CampaignCall.leased_by_device_id == device_id))
            .values(status="pending", leased_by_user_id=None, leased_by_device_id=None, lease_expires_at=None)
        )
    stuck_before = now - timedelta(hours=2)
    await db.execute(
        update(CampaignCall)
        .where(and_(
            CampaignCall.status == "calling",
            CampaignCall.called_at < stuck_before,
            CampaignCall.id.in_(select(MobileCallAttempt.campaign_call_id)),
        ))
        .values(status="completed", outcome="unknown", outcome_notes="updated_by=mobile_reconciler",
                completed_at=now)
    )
    await db.commit()
    return len(expired)


async def mobile_housekeeping_job(ctx=None) -> dict:
    async with AsyncSessionLocal() as db:
        expired = await expire_stale_attempts(db)
    async with AsyncSessionLocal() as db:
        reconciled = await reconcile_unidentified_sessions(db)
    if expired or reconciled:
        logger.info(f"[Mobile] housekeeping: expired={expired} reconciled={reconciled}")
    return {"expired": expired, "reconciled": reconciled}
