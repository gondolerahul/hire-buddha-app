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

from sqlalchemy import and_, func, select, update

from src.common.config import settings
from src.common.database import AsyncSessionLocal
from src.ai.campaign_models import Campaign, CampaignCall
from src.mobile.models import (
    ATTEMPT_EXPIRED, ATTEMPT_PENDING, IDENT_RECONCILED, IDENT_UNIDENTIFIED,
    RUN_COMPLETED, RUN_PAUSED, RUN_RUNNING, SESSION_MODE_MOBILE,
    MobileCallAttempt, MobileCampaignRun, UserDevice,
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


# A run only ever ends because the app told us so. An app that is killed, crashes,
# is reinstalled (which mints a new device row) or simply loses the network leaves the
# run RUNNING forever — which pins the campaign to "running" in every report and makes
# start_run refuse the device with `device_busy` with nothing in the UI able to clear it.
STALE_RUN_HOURS = 6


async def close_stale_runs(db) -> int:
    """Close runs that no app is driving any more.

    Conservative on purpose: a run is only stale when it has had no call attempt for
    STALE_RUN_HOURS *and* nothing is currently in flight on it. Paused runs are left
    alone unless they are equally cold, because a pause is a deliberate act a rep
    expects to come back to.
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=STALE_RUN_HOURS)

    candidates = (await db.execute(
        select(MobileCampaignRun).where(and_(
            MobileCampaignRun.status.in_((RUN_RUNNING, RUN_PAUSED)),
            MobileCampaignRun.started_at < cutoff,
        ))
    )).scalars().all()
    if not candidates:
        return 0

    closed = 0
    for run in candidates:
        last_attempt = (await db.execute(
            select(func.max(MobileCallAttempt.created_at))
            .where(MobileCallAttempt.run_id == run.id)
        )).scalar_one_or_none()
        if last_attempt is not None and last_attempt >= cutoff:
            continue  # still warm
        run.status = RUN_COMPLETED
        run.ended_at = now
        closed += 1
        logger.info("[Mobile] closing stale run %s (campaign %s, started %s)",
                    run.id, run.campaign_id, run.started_at)
        # Hand any lead it was still holding back to the queue.
        await db.execute(
            update(CampaignCall)
            .where(and_(CampaignCall.campaign_id == run.campaign_id,
                        CampaignCall.leased_by_device_id == run.device_id,
                        CampaignCall.status == "leased"))
            .values(status="pending", leased_by_user_id=None, leased_by_device_id=None,
                    lease_expires_at=None)
        )
    await db.commit()
    return closed


async def close_finished_campaigns(db) -> int:
    """Mark a mobile campaign completed once nothing is left to call.

    `/mobile/runs/{id}/next` does this when it runs out of leads, but a campaign whose
    run died before that point sits at "running" with zero pending leads indefinitely.
    """
    now = datetime.utcnow()
    stuck = (await db.execute(
        select(Campaign.id).where(and_(
            Campaign.status == "running",
            Campaign.execution_mode == "mobile_conference",
            ~select(CampaignCall.id).where(and_(
                CampaignCall.campaign_id == Campaign.id,
                CampaignCall.status.in_(("pending", "leased", "calling")),
            )).exists(),
            ~select(MobileCampaignRun.id).where(and_(
                MobileCampaignRun.campaign_id == Campaign.id,
                MobileCampaignRun.status.in_((RUN_RUNNING, RUN_PAUSED)),
            )).exists(),
        ))
    )).scalars().all()
    if not stuck:
        return 0
    await db.execute(
        update(Campaign).where(Campaign.id.in_(stuck))
        .values(status="completed", completed_at=now, updated_at=now)
    )
    await db.commit()
    logger.info("[Mobile] completed %d campaign(s) with nothing left to call", len(stuck))
    return len(stuck)


async def mobile_housekeeping_job(ctx=None) -> dict:
    async with AsyncSessionLocal() as db:
        expired = await expire_stale_attempts(db)
    async with AsyncSessionLocal() as db:
        reconciled = await reconcile_unidentified_sessions(db)
    async with AsyncSessionLocal() as db:
        runs_closed = await close_stale_runs(db)
    async with AsyncSessionLocal() as db:
        campaigns_closed = await close_finished_campaigns(db)
    if expired or reconciled or runs_closed or campaigns_closed:
        logger.info(
            f"[Mobile] housekeeping: expired={expired} reconciled={reconciled} "
            f"runs_closed={runs_closed} campaigns_closed={campaigns_closed}"
        )
    return {
        "expired": expired, "reconciled": reconciled,
        "runs_closed": runs_closed, "campaigns_closed": campaigns_closed,
    }
