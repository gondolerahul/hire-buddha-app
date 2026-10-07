"""Every usage row a run writes reaches its execution page (P4.8, AK-11 remainder).

The page's reducer handles a ``cost_charged`` frame (cost by attribution), but
nothing published one: ``CostLedger`` logged ``agent.cost.charged`` to the
structured log only, and ``UsageService.log_usage`` — every LLM row — emitted
nothing. Real Postgres, rolled back.
"""
from __future__ import annotations

import json
import uuid
from decimal import Decimal

import pytest

from src.ai.core import agent_loop_sse
from src.ai.orm import ExecutionRun, HierarchicalEntity
from src.ai.services.cost_attribution import CostLedger
from src.ai.usage_service import UsageService
from src.config.models import IntegrationRegistry

pytestmark = pytest.mark.needs_db


class _Redis:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    async def publish(self, channel, body):
        self.published.append((channel, json.loads(body)))


@pytest.fixture
def redis(monkeypatch):
    fake = _Redis()
    monkeypatch.setattr(agent_loop_sse, "_SSE_REDIS", fake)
    return fake


async def _run(db):
    from src.auth.models import Company
    c = Company(name=f"p48-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    db.add(IntegrationRegistry(company_id=c.id, provider_name="test", service_sku="p48-model-in",
                               model_name="p48-model", component_type="input_token",
                               internal_cost=Decimal("1.00"), cost_unit="per_1M_tokens",
                               status="active", service_category="LLM"))
    ent = HierarchicalEntity(company_id=c.id, type="AGENT", status="ACTIVE", name="framed")
    db.add(ent)
    await db.flush()
    run = ExecutionRun(entity_id=ent.id, company_id=c.id, status="RUNNING", input_data={},
                       total_cost_usd=Decimal("0"))
    db.add(run)
    await db.flush()
    return c.id, run


@pytest.mark.asyncio
async def test_an_llm_row_publishes_a_cost_charged_frame(db, redis):
    company, run = await _run(db)
    await UsageService(db).log_usage(company, "p48-model-in", 500_000, execution_id=run.id,
                                     attribution="critic_post")
    [(channel, frame)] = redis.published
    assert channel == f"execution:{run.id}"
    assert frame["type"] == "cost_charged" and frame["attribution"] == "critic_post"
    assert frame["sku"] == "p48-model-in" and frame["amount_usd"] == pytest.approx(0.5)
    assert frame["persisted"] is True


@pytest.mark.asyncio
async def test_a_tool_charge_publishes_one_too(db, redis):
    company, run = await _run(db)
    await CostLedger(db).add(run_id=run.id, company_id=company, amount=Decimal("0.03"),
                             attribution="tool", latency_ms=12)
    [(_, frame)] = redis.published
    assert (frame["type"], frame["attribution"], frame["amount_usd"]) == ("cost_charged", "tool", 0.03)


@pytest.mark.asyncio
async def test_a_row_with_no_run_publishes_nothing(db, redis):
    company, _run_row = await _run(db)
    await UsageService(db).log_usage(company, "p48-model-in", 1000)
    assert redis.published == []
