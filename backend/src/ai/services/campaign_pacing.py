"""campaign_pacing.py — a campaign's hourly cap and its retries (VT-09, VT-10, VT-I2).

``Campaign.max_calls_per_hour`` and ``CampaignCall.max_retries`` were stored and
shown in the UI and read by nothing: a campaign dialed its whole list at the
concurrency limit, and a busy or unanswered lead was never called again.

The executor dials what is pending and then, instead of sleeping on a worker,
schedules its own **continuation** (``execute_campaign_task`` deferred):

* **the hourly cap** — before each call it counts the campaign's calls placed in
  the last hour; at the cap it stops and continues when the oldest of those is
  an hour old;
* **retries** — a call that ended busy, unanswered, rejected or failed (or
  failed to be placed) is dialed again while ``retry_count < max_retries``,
  after ``CAMPAIGN_RETRY_BACKOFF_SECONDS × 2^retry_count``. At the start of each
  pass the due ones go back to ``pending``;
* the campaign is ``completed`` only when nothing is pending, in flight or
  waiting for a retry.

A continuation runs only while the campaign is still ``running``: pausing or
stopping it is not undone by a deferred job.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select, update

logger = logging.getLogger(__name__)

__all__ = ["RETRYABLE_OUTCOMES", "retry_backoff", "requeue_due_retries", "hourly_wait",
           "next_pass_in", "schedule_continuation"]

RETRYABLE_OUTCOMES = ("busy", "no_answer", "rejected", "failed", "placement_error")
HOUR = timedelta(hours=1)
# A call still "calling" after this long lost its status callback; it does not
# hold the campaign open.
IN_FLIGHT_FOR = timedelta(minutes=15)
CHECK_IN_FLIGHT_SECONDS = 120


def retry_backoff(retry_count: int) -> timedelta:
    from src.common.config import settings
    return timedelta(seconds=int(settings.CAMPAIGN_RETRY_BACKOFF_SECONDS) * (2 ** max(int(retry_count), 0)))


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value


def _retryable():
    from src.ai.campaign_models import CampaignCall
    return (CampaignCall.status == "failed", CampaignCall.outcome.in_(RETRYABLE_OUTCOMES),
            CampaignCall.retry_count < CampaignCall.max_retries)


async def requeue_due_retries(db: Any, campaign_id: UUID, now: datetime) -> int:
    """Put the retryable failed calls whose backoff has passed back to ``pending``."""
    from src.ai.campaign_models import CampaignCall
    rows = (await db.execute(
        select(CampaignCall.id, CampaignCall.retry_count, CampaignCall.completed_at, CampaignCall.called_at)
        .where(CampaignCall.campaign_id == campaign_id, *_retryable())
    )).all()
    due = [cid for cid, tries, done, called in rows
           if _naive(done or called or now) + retry_backoff(tries) <= now]
    if due:
        await db.execute(
            update(CampaignCall).where(CampaignCall.id.in_(due))
            .values(status="pending", retry_count=CampaignCall.retry_count + 1, voice_session_id=None)
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        logger.info("Campaign %s: %d call(s) back for another try", campaign_id, len(due))
    return len(due)


async def hourly_wait(db: Any, campaign_id: UUID, max_per_hour: Optional[int], now: datetime) -> float:
    """Seconds until the campaign may place another call under its hourly cap (0: now)."""
    if not max_per_hour or max_per_hour <= 0:
        return 0.0
    from src.ai.campaign_models import CampaignCall
    count, oldest = (await db.execute(
        select(func.count(), func.min(CampaignCall.called_at))
        .where(CampaignCall.campaign_id == campaign_id, CampaignCall.called_at >= now - HOUR)
    )).one()
    if int(count or 0) < max_per_hour or oldest is None:
        return 0.0
    return max((_naive(oldest) + HOUR - now).total_seconds(), 1.0)


async def next_pass_in(db: Any, campaign_id: UUID, now: datetime) -> Optional[float]:
    """Seconds until the campaign has more to do — calls still in flight, or
    a retry coming due — or ``None`` when it is done."""
    from src.ai.campaign_models import CampaignCall
    in_flight = (await db.execute(
        select(func.count()).where(CampaignCall.campaign_id == campaign_id,
                                   CampaignCall.status == "calling",
                                   CampaignCall.called_at >= now - IN_FLIGHT_FOR)
    )).scalar()
    waits: list[float] = [float(CHECK_IN_FLIGHT_SECONDS)] if in_flight else []
    rows = (await db.execute(
        select(CampaignCall.retry_count, CampaignCall.completed_at, CampaignCall.called_at)
        .where(CampaignCall.campaign_id == campaign_id, *_retryable())
    )).all()
    for tries, done, called in rows:
        due = _naive(done or called or now) + retry_backoff(tries)
        waits.append(max((due - now).total_seconds(), 1.0))
    return min(waits) if waits else None


async def schedule_continuation(campaign_id: UUID, delay_seconds: float) -> None:
    """Run the campaign again in ``delay_seconds`` (only while it is still running)."""
    from src.common.job_queue import enqueue_job
    when = int((datetime.utcnow() + timedelta(seconds=delay_seconds)).timestamp())
    await enqueue_job("execute_campaign_task", str(campaign_id), True,
                      _job_id=f"campaign-continue:{campaign_id}:{when}", _defer_by=max(delay_seconds, 1.0))
    logger.info("Campaign %s continues in %.0fs", campaign_id, delay_seconds)
