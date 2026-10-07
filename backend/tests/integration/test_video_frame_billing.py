"""A video call's frame descriptions are on a run and billed (LP-26).

``VideoSession._analyze_video_frame`` asked the ``vision`` model to describe a
frame every few seconds and wrote no usage row: no run to attribute it to, so
every description was free. Real Postgres, rolled back per test.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from src.ai.orm import ExecutionRun, HierarchicalEntity
from src.ai.orm.execution import LLMInteractionLog
from src.ai.orm.usage import UsageLog
from src.config.models import IntegrationRegistry
from src.gateway.call_spend import CallSpend

pytestmark = pytest.mark.needs_db

MODEL = "lp26-vision"


async def _video_call(db):
    from src.auth.models import Company
    c = Company(name=f"lp26-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    db.add_all([
        IntegrationRegistry(company_id=c.id, provider_name="test", service_sku=f"{MODEL}-in",
                            component_type="input_token", internal_cost=Decimal("1.00"),
                            cost_unit="per_1M_tokens", status="active", service_category="LLM"),
        IntegrationRegistry(company_id=c.id, provider_name="test", service_sku=f"{MODEL}-out",
                            component_type="output_token", internal_cost=Decimal("4.00"),
                            cost_unit="per_1M_tokens", status="active", service_category="LLM"),
    ])
    agent = HierarchicalEntity(company_id=c.id, type="AGENT", status="ACTIVE", name="video concierge")
    db.add(agent)
    await db.flush()
    return c.id, agent.id


def _description(prompt_tokens: int, completion_tokens: int):
    return SimpleNamespace(model_name=MODEL, provider="test", output="A person smiling at the camera.",
                           prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, latency_ms=900)


@pytest.mark.asyncio
async def test_each_frame_description_is_billed_to_the_calls_run(db, monkeypatch):
    company, agent = await _video_call(db)
    spend = CallSpend(company_id=company, agent_id=agent, channel="video", session_id="vs-1")
    await spend.record(db, _description(1_000_000, 0), attribution="video_frame",
                       system_prompt="Describe", user_prompt="Describe this frame.")
    await spend.record(db, _description(0, 250_000), attribution="video_frame")

    run = (await db.execute(select(ExecutionRun).where(ExecutionRun.id == spend.run_id))).scalar_one()
    assert run.entity_id == agent and run.input_data["video_session_id"] == "vs-1"
    rows = (await db.execute(select(UsageLog).where(UsageLog.run_id == run.id))).scalars().all()
    assert len(rows) == 2 and {r.attribution for r in rows} == {"video_frame"}
    assert sum(Decimal(str(r.calculated_cost)) for r in rows) == Decimal("2.00")   # $1 in + $1 out
    interactions = (await db.execute(select(LLMInteractionLog).where(
        LLMInteractionLog.run_id == run.id))).scalars().all()
    assert len(interactions) == 2 and "base64" not in interactions[0].input_prompt

    settled = {}

    async def _settle(self, r, name):
        settled.update(run=r.id, cost=Decimal(str(r.total_cost_usd)), status=r.status, name=name)
        return Decimal(str(r.total_cost_usd))

    from src.ai.governance.governance_service import GovernanceService
    monkeypatch.setattr(GovernanceService, "settle_billing", _settle)
    billed = await spend.finish(db)
    assert billed == Decimal("2.00")
    assert settled == {"run": run.id, "cost": Decimal("2.00"), "status": "COMPLETED", "name": "video call"}


@pytest.mark.asyncio
async def test_a_call_with_no_frame_described_settles_nothing(db):
    company, agent = await _video_call(db)
    spend = CallSpend(company_id=company, agent_id=agent, channel="video", session_id="vs-2")
    assert await spend.finish(db) == Decimal("0") and spend.run_id is None


@pytest.mark.asyncio
async def test_an_agent_of_another_company_opens_no_run(db):
    company, _agent = await _video_call(db)
    _other, foreign_agent = await _video_call(db)
    spend = CallSpend(company_id=company, agent_id=foreign_agent, channel="video", session_id="vs-3")
    await spend.record(db, _description(1000, 10), attribution="video_frame")
    assert spend.run_id is None
