"""A campaign keeps its hourly cap and re-dials busy or unanswered leads (VT-09, VT-10).

``max_calls_per_hour`` and ``max_retries`` were stored, shown and read by
nothing. Now the executor stops at the hourly cap and continues when the
window allows, and a failed call goes again after its backoff, up to its
``max_retries``; the campaign completes only when nothing is left. Real
Postgres, rolled back; no call is placed — the provider step is replaced.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, update

import src.common.database  # noqa: F401  (its UTC codec must be on every connection, before the engine connects)
from tests.integration.test_hitl_respond import _user

pytestmark = pytest.mark.needs_db


@pytest.fixture
def dialer(db, monkeypatch):
    """The executor on the test session: placing a call marks it answered
    and completed; credit admits; continuations are recorded, not queued."""
    import asyncio
    from src.ai import campaign_executor
    from src.ai.campaign_executor import CampaignExecutor
    from src.ai.campaign_models import CampaignCall
    from src.ai.services import campaign_pacing

    placed, continued = [], []

    @asynccontextmanager
    async def _session():
        yield db

    async def _place(cls, campaign_data, call_info):
        placed.append(call_info["id"])
        await db.execute(update(CampaignCall).where(CampaignCall.id == call_info["id"])
                         .values(status="completed", called_at=datetime.utcnow(),
                                 completed_at=datetime.utcnow()))
        await db.flush()

    async def _admit(*_a, **_k):
        return None

    async def _continue(campaign_id, delay):
        continued.append((campaign_id, delay))

    real_sleep = asyncio.sleep

    async def _no_sleep(delay, *a, **k):
        await real_sleep(0)

    monkeypatch.setattr(campaign_executor, "AsyncSessionLocal", _session)
    monkeypatch.setattr(campaign_executor, "call_refusal", _admit)
    monkeypatch.setattr(CampaignExecutor, "_place_call_safe", classmethod(_place))
    monkeypatch.setattr(campaign_pacing, "schedule_continuation", _continue)
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    return CampaignExecutor, placed, continued


async def _campaign(db, test_company_id, *, calls=3, per_hour=None, status="draft"):
    from src.ai.campaign_models import Campaign, CampaignCall
    from src.ai.orm.entity import HierarchicalEntity

    agent = HierarchicalEntity(company_id=test_company_id, type="AGENT", status="ACTIVE",
                               name=f"dialer-{uuid.uuid4().hex[:6]}")
    db.add(agent)
    await db.flush()
    campaign = Campaign(company_id=test_company_id, created_by=await _user(db, test_company_id),
                        agent_id=agent.id, name="pacing", total_contacts=calls, contact_list=[],
                        provider="twilio", max_calls_per_hour=per_hour, status=status)
    db.add(campaign)
    await db.flush()
    rows = [CampaignCall(campaign_id=campaign.id, contact_data={"phone": f"+1555000{i:04d}"},
                         status="pending") for i in range(calls)]
    db.add_all(rows)
    await db.flush()
    return campaign, rows


async def _status(db, model, row_id):
    return (await db.execute(select(model.status).where(model.id == row_id)
                             .execution_options(populate_existing=True))).scalar_one()


@pytest.mark.asyncio
async def test_the_hourly_cap_stops_and_continues_later(db, test_company_id, dialer):
    from src.ai.campaign_models import Campaign, CampaignCall
    executor, placed, continued = dialer
    campaign, rows = await _campaign(db, test_company_id, calls=3, per_hour=2)

    await executor.start_campaign_standalone(campaign.id)
    assert len(placed) == 2                                  # the third waits for the window
    [(cid, delay)] = continued
    assert cid == campaign.id and 3500 < delay <= 3600
    assert await _status(db, Campaign, campaign.id) == "running"
    assert await _status(db, CampaignCall, rows[2].id) == "pending"


@pytest.mark.asyncio
async def test_a_busy_lead_is_called_again_after_its_backoff(db, test_company_id, dialer):
    from src.ai.campaign_models import Campaign, CampaignCall
    executor, placed, continued = dialer
    campaign, (due, early, spent) = await _campaign(db, test_company_id, calls=3)
    now = datetime.utcnow()
    await db.execute(update(CampaignCall).where(CampaignCall.id == due.id).values(
        status="failed", outcome="busy", completed_at=now - timedelta(minutes=20)))
    await db.execute(update(CampaignCall).where(CampaignCall.id == early.id).values(
        status="failed", outcome="no_answer", completed_at=now - timedelta(minutes=1)))
    await db.execute(update(CampaignCall).where(CampaignCall.id == spent.id).values(
        status="failed", outcome="busy", retry_count=2, completed_at=now - timedelta(hours=5)))
    await db.flush()

    await executor.start_campaign_standalone(campaign.id)
    assert placed == [due.id]                                # 20 min > the 10 min backoff
    retry_count = (await db.execute(select(CampaignCall.retry_count).where(CampaignCall.id == due.id))).scalar()
    assert retry_count == 1
    [(_, delay)] = continued                                 # the early one comes due in ~9 min
    assert 400 < delay < 600
    assert await _status(db, Campaign, campaign.id) == "running"
    assert await _status(db, CampaignCall, spent.id) == "failed"   # no retries left


@pytest.mark.asyncio
async def test_with_nothing_left_the_campaign_completes(db, test_company_id, dialer):
    from src.ai.campaign_models import Campaign
    executor, placed, continued = dialer
    campaign, _ = await _campaign(db, test_company_id, calls=2)
    await executor.start_campaign_standalone(campaign.id)
    assert len(placed) == 2 and continued == []
    assert await _status(db, Campaign, campaign.id) == "completed"


@pytest.mark.asyncio
async def test_a_continuation_does_not_restart_a_paused_campaign(db, test_company_id, dialer):
    from src.ai.campaign_models import Campaign
    executor, placed, _ = dialer
    campaign, _ = await _campaign(db, test_company_id, calls=2, status="paused")
    await executor.start_campaign_standalone(campaign.id, continuation=True)
    assert placed == [] and await _status(db, Campaign, campaign.id) == "paused"
