"""
Mobile-dialer analytics shared by the web frontend and the app (docs 07).

All numbers are computed server-side from mobile_call_attempts (app + gateway
facts), campaign_calls (dispositions) and voice_sessions/usage (cost), so
both clients render identical figures. Tenant users only ever see their own
attempts; tenant admins may filter by rep.
"""
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_, case, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.campaign_models import Campaign, CampaignCall
from src.auth.models import User
from src.mobile.models import (
    ATTEMPT_SUPERSEDED, EXECUTION_MODE_MOBILE, IDENT_CLI, IDENT_CLI_DTMF, IDENT_DTMF,
    MobileCallAttempt,
)
from src.mobile.phone import mask_phone

CONVERSATION_MIN_SECONDS = 30


def _rate(num: int, den: int) -> Optional[float]:
    return round(num / den, 4) if den else None


def _percentile(values: List[float], pct: float) -> Optional[float]:
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * pct
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return round(values[lo] + (values[hi] - values[lo]) * (k - lo), 1)


async def compute_analytics(
    db: AsyncSession,
    *,
    company_id: UUID,
    campaign_id: Optional[UUID] = None,
    user_id: Optional[UUID] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> Dict[str, Any]:
    conds = [MobileCallAttempt.company_id == company_id, MobileCallAttempt.status != ATTEMPT_SUPERSEDED]
    if campaign_id:
        conds.append(MobileCallAttempt.campaign_id == campaign_id)
    if user_id:
        conds.append(MobileCallAttempt.user_id == user_id)
    if date_from:
        conds.append(MobileCallAttempt.created_at >= date_from)
    if date_to:
        conds.append(MobileCallAttempt.created_at < date_to)
    where = and_(*conds)

    A = MobileCallAttempt
    agg = (await db.execute(
        select(
            func.count(func.distinct(A.campaign_call_id)).label("attempted_leads"),
            func.count().label("attempts"),
            func.count().filter(A.ai_ready_at.isnot(None)).label("ai_ready"),
            func.count().filter(A.lead_dialed_at.isnot(None)).label("lead_dialed"),
            func.count().filter(A.lead_answered_at.isnot(None)).label("lead_answered"),
            func.count().filter(A.merged_at.isnot(None)).label("merged"),
            func.count().filter(A.conversation_seconds >= CONVERSATION_MIN_SECONDS).label("conversation"),
            func.count().filter(A.identification_method.in_((IDENT_CLI, IDENT_DTMF, IDENT_CLI_DTMF))).label("identified"),
            func.count().filter(A.identification_method.in_((IDENT_CLI, IDENT_CLI_DTMF))).label("cli_bound"),
            func.count().filter(A.identification_method == IDENT_CLI_DTMF).label("dtmf_confirmed"),
            func.count().filter(A.identification_conflict.is_(True)).label("conflicts"),
            func.count().filter(A.assisted.is_(True)).label("assisted"),
            func.coalesce(func.sum(A.conversation_seconds).filter(A.merged_at.isnot(None)), 0).label("talk_seconds"),
            func.coalesce(func.avg(A.conversation_seconds).filter(
                A.conversation_seconds >= CONVERSATION_MIN_SECONDS), 0).label("avg_conversation"),
            func.coalesce(func.sum(
                func.extract("epoch", func.coalesce(A.ended_at, A.updated_at) - A.ai_answered_at)
            ).filter(and_(A.merged_at.is_(None), A.ai_answered_at.isnot(None))), 0).label("idle_ai_seconds"),
        ).where(where)
    )).one()

    ready_latencies = [float(r[0]) for r in (await db.execute(
        select(func.extract("epoch", A.ai_ready_at - A.created_at)).where(and_(where, A.ai_ready_at.isnot(None)))
    )).all()]

    failures = dict((await db.execute(
        select(A.lead_failure_cause, func.count()).where(and_(where, A.lead_failure_cause.isnot(None)))
        .group_by(A.lead_failure_cause)
    )).all())
    system_failures = dict((await db.execute(
        select(A.status, func.count()).where(and_(where, A.status.in_(("merge_failed", "ai_failed", "abandoned", "expired"))))
        .group_by(A.status)
    )).all())

    # Dispositions come from the campaign calls these attempts dialed (latest classification).
    call_ids = select(A.campaign_call_id).where(where).distinct()
    dispositions = dict((await db.execute(
        select(CampaignCall.disposition, func.count())
        .where(and_(CampaignCall.id.in_(call_ids), CampaignCall.disposition.isnot(None)))
        .group_by(CampaignCall.disposition)
    )).all())
    interested = dispositions.get("interested", 0)

    leads_total = None
    if campaign_id:
        leads_total = (await db.execute(
            select(func.count()).select_from(CampaignCall).where(CampaignCall.campaign_id == campaign_id)
        )).scalar_one()

    cost = await _cost(db, where)

    return {
        "funnel": {
            "leads": leads_total,
            "attempted": agg.attempted_leads,
            "attempts": agg.attempts,
            "ai_ready": agg.ai_ready,
            "lead_dialed": agg.lead_dialed,
            "lead_answered": agg.lead_answered,
            "merged": agg.merged,
            "conversation": agg.conversation,
            "interested": interested,
        },
        "rates": {
            "answer": _rate(agg.lead_answered, agg.lead_dialed),
            "merge_success": _rate(agg.merged, agg.lead_answered),
            "identification": _rate(agg.identified, agg.ai_ready),
            "dtmf_confirmation": _rate(agg.dtmf_confirmed, agg.cli_bound),
            "identification_conflict": _rate(agg.conflicts, agg.ai_ready),
            "conversion": _rate(interested, agg.conversation),
        },
        "timing": {
            "ai_ready_p50_s": _percentile(ready_latencies, 0.5),
            "ai_ready_p95_s": _percentile(ready_latencies, 0.95),
            "avg_conversation_s": round(float(agg.avg_conversation or 0), 1),
            "talk_minutes": round(float(agg.talk_seconds or 0) / 60, 1),
            "idle_ai_minutes": round(float(agg.idle_ai_seconds or 0) / 60, 1),
        },
        "outcomes": {**failures, **system_failures, **dispositions},
        "assisted_attempts": agg.assisted,
        "cost": cost,
    }


async def _cost(db: AsyncSession, where) -> Dict[str, Any]:
    from src.voice.models import VoiceSession

    total = (await db.execute(
        select(func.coalesce(func.sum(VoiceSession.total_cost_usd), 0))
        .where(VoiceSession.id.in_(select(MobileCallAttempt.voice_session_id).where(
            and_(where, MobileCallAttempt.voice_session_id.isnot(None)))))
    )).scalar_one()
    return {"raw_cost_usd": round(float(total or 0), 4)}


async def by_rep(db: AsyncSession, *, company_id: UUID, campaign_id: Optional[UUID],
                 date_from: Optional[datetime], date_to: Optional[datetime],
                 only_user: Optional[UUID] = None) -> List[Dict[str, Any]]:
    A = MobileCallAttempt
    conds = [A.company_id == company_id, A.status != ATTEMPT_SUPERSEDED]
    if campaign_id:
        conds.append(A.campaign_id == campaign_id)
    if only_user:
        conds.append(A.user_id == only_user)
    if date_from:
        conds.append(A.created_at >= date_from)
    if date_to:
        conds.append(A.created_at < date_to)
    rows = (await db.execute(
        select(
            A.user_id, User.full_name,
            func.count().label("attempts"),
            func.count().filter(A.lead_dialed_at.isnot(None)).label("dialed"),
            func.count().filter(A.lead_answered_at.isnot(None)).label("answered"),
            func.count().filter(A.merged_at.isnot(None)).label("merged"),
            func.coalesce(func.sum(A.conversation_seconds), 0).label("talk_seconds"),
            func.count(func.distinct(case((CampaignCall.disposition == "interested", A.campaign_call_id)))).label("interested"),
        )
        .join(User, User.id == A.user_id)
        .join(CampaignCall, CampaignCall.id == A.campaign_call_id)
        .where(and_(*conds))
        .group_by(A.user_id, User.full_name)
        .order_by(func.count().desc())
    )).all()
    return [{
        "user_id": r.user_id, "name": r.full_name, "attempts": r.attempts,
        "answer_rate": _rate(r.answered, r.dialed), "merge_success": _rate(r.merged, r.answered),
        "interested": r.interested, "talk_minutes": round(float(r.talk_seconds) / 60, 1),
    } for r in rows]


async def daily(db: AsyncSession, *, company_id: UUID, user_id: Optional[UUID],
                date_from: datetime, date_to: datetime) -> List[Dict[str, Any]]:
    A = MobileCallAttempt
    # Bucket by IST calendar day.
    day = func.date(A.created_at + literal(timedelta(hours=5, minutes=30)))
    conds = [A.company_id == company_id, A.status != ATTEMPT_SUPERSEDED,
             A.created_at >= date_from, A.created_at < date_to]
    if user_id:
        conds.append(A.user_id == user_id)
    rows = (await db.execute(
        select(day.label("day"), func.count().label("attempts"),
               func.count().filter(A.merged_at.isnot(None)).label("merged"),
               func.count(func.distinct(case((CampaignCall.disposition == "interested", A.campaign_call_id)))).label("interested"))
        .join(CampaignCall, CampaignCall.id == A.campaign_call_id)
        .where(and_(*conds)).group_by(day).order_by(day)
    )).all()
    return [{"date": r.day.isoformat() if isinstance(r.day, date) else str(r.day),
             "attempted": r.attempts, "merged": r.merged, "interested": r.interested} for r in rows]


async def call_list(db: AsyncSession, *, company_id: UUID, campaign_id: UUID, user_id: Optional[UUID],
                    status: Optional[str], disposition: Optional[str], limit: int, offset: int) -> Dict[str, Any]:
    """Paged campaign calls with their latest attempt (for web + app lists)."""
    A = MobileCallAttempt
    latest = (
        select(A.campaign_call_id, func.max(A.created_at).label("latest_at"))
        .where(and_(A.campaign_id == campaign_id, A.status != ATTEMPT_SUPERSEDED))
        .group_by(A.campaign_call_id).subquery()
    )
    q = (
        select(CampaignCall, A, User.full_name)
        .select_from(CampaignCall)
        .join(Campaign, Campaign.id == CampaignCall.campaign_id)
        .outerjoin(latest, latest.c.campaign_call_id == CampaignCall.id)
        .outerjoin(A, and_(A.campaign_call_id == CampaignCall.id, A.created_at == latest.c.latest_at))
        .outerjoin(User, User.id == A.user_id)
        .where(Campaign.id == campaign_id, Campaign.company_id == company_id)
    )
    if user_id:
        q = q.where(A.user_id == user_id)
    if status:
        q = q.where(CampaignCall.status == status)
    if disposition:
        q = q.where(CampaignCall.disposition == disposition)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (await db.execute(
        q.order_by(func.coalesce(A.created_at, CampaignCall.created_at).desc()).limit(limit).offset(offset)
    )).all()
    items = []
    for call, attempt, rep_name in rows:
        contact = call.contact_data or {}
        items.append({
            "campaign_call_id": call.id,
            "contact_name": contact.get("name") or contact.get("Name"),
            "phone_masked": mask_phone(contact.get("phone")),
            "call_status": call.status,
            "disposition": call.disposition,
            "disposition_reason": call.disposition_reason,
            "rep_name": rep_name,
            "attempt_id": attempt.id if attempt else None,
            "attempt_status": attempt.status if attempt else None,
            "identification_method": attempt.identification_method if attempt else None,
            "lead_failure_cause": attempt.lead_failure_cause if attempt else None,
            "conversation_seconds": attempt.conversation_seconds if attempt else None,
            "called_at": attempt.created_at if attempt else call.called_at,
            "voice_session_id": (attempt.voice_session_id if attempt else None) or call.voice_session_id,
            "assisted": attempt.assisted if attempt else False,
        })
    return {"total": total, "items": items}


async def attempt_timeline(db: AsyncSession, attempt: MobileCallAttempt) -> List[Dict[str, Any]]:
    from src.mobile.models import MobileCallEvent

    events = (await db.execute(
        select(MobileCallEvent).where(MobileCallEvent.attempt_id == attempt.id).order_by(MobileCallEvent.seq)
    )).scalars().all()
    timeline = [{"at": attempt.created_at, "source": "server", "type": "attempt_created"}]
    for label, ts in (("ai_ready", attempt.ai_ready_at), ("ended", attempt.ended_at)):
        if ts:
            timeline.append({"at": ts, "source": "server", "type": label})
    for e in events:
        timeline.append({"at": e.received_at, "device_ts": e.device_ts, "source": "app", "type": e.type,
                         "payload": e.payload})
    return sorted(timeline, key=lambda x: x["at"])


def parse_range(date_from: Optional[date], date_to: Optional[date], default_days: int = 7):
    """IST calendar dates -> naive UTC bounds [from, to)."""
    ist = timedelta(hours=5, minutes=30)
    today = (datetime.utcnow() + ist).date()
    end = (date_to or today) + timedelta(days=1)
    start = date_from or (end - timedelta(days=default_days))
    return datetime.combine(start, datetime.min.time()) - ist, datetime.combine(end, datetime.min.time()) - ist


__all__ = ["compute_analytics", "by_rep", "daily", "call_list", "attempt_timeline", "parse_range",
           "EXECUTION_MODE_MOBILE"]
