"""Planner and critic calls have an interaction row too (P4.7, LP-I9).

Only a step's own LLM calls wrote ``llm_interaction_logs``; the planner's, the
judge's and the critics' calls wrote usage rows only, so the run page could
not show what those models saw or said. Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from src.ai.orm import ExecutionRun, HierarchicalEntity, LLMInteractionLog
from src.ai.services.attributed_usage import log_llm_response_usage
from src.config.models import IntegrationRegistry

pytestmark = pytest.mark.needs_db

MODEL = "p47-model"


async def _run(db):
    from src.auth.models import Company
    c = Company(name=f"p47-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    for suffix, cost in (("in", "1.00"), ("out", "4.00")):
        db.add(IntegrationRegistry(company_id=c.id, provider_name="test", service_sku=f"{MODEL}-{suffix}",
                                   model_name=MODEL, component_type=f"{suffix}put_token",
                                   internal_cost=Decimal(cost), cost_unit_code="PER_1M_TOKENS",
                                   status="active", service_category="LLM"))
    ent = HierarchicalEntity(company_id=c.id, type="AGENT", status="ACTIVE", name="critiqued")
    db.add(ent)
    await db.flush()
    run = ExecutionRun(entity_id=ent.id, company_id=c.id, status="RUNNING", input_data={},
                       total_cost_usd=Decimal("0"))
    db.add(run)
    await db.flush()
    return c.id, run


def _resp(output='{"verdict": "PASS"}'):
    return SimpleNamespace(model_name=MODEL, provider="test", output=output,
                           prompt_tokens=1_000_000, completion_tokens=250_000, latency_ms=42)


@pytest.mark.asyncio
async def test_a_critic_call_has_an_interaction_row(db):
    company, run = await _run(db)
    await log_llm_response_usage(db=db, response=_resp(), attribution="critic_post",
                                 company_id=company, run_id=run.id,
                                 system_prompt="You are a critic.", user_prompt="Judge this step.")
    [row] = (await db.execute(select(LLMInteractionLog).where(
        LLMInteractionLog.run_id == run.id))).scalars().all()
    assert row.reasoning_mode == "CRITIC_POST" and row.step_name == "__critic_post__"
    assert row.input_prompt == "System: You are a critic.\nUser: Judge this step."
    assert row.output_response == '{"verdict": "PASS"}'
    assert (row.prompt_tokens, row.completion_tokens, row.latency_ms) == (1_000_000, 250_000, 42)
    assert Decimal(str(row.cost_usd)) == Decimal("2.00")          # 1.00 in + 1.00 out


@pytest.mark.asyncio
async def test_a_call_with_no_run_writes_no_interaction_row(db):
    company, run = await _run(db)
    await log_llm_response_usage(db=db, response=_resp(), attribution="planner", company_id=company)
    rows = (await db.execute(select(LLMInteractionLog).where(
        LLMInteractionLog.company_id == company))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_the_post_critic_passes_the_prompt_it_sent(db, monkeypatch):
    from src.ai.planning import critic_pipeline as cp
    import src.ai.services.attributed_usage as au

    company, run = await _run(db)
    seen = {}

    async def _capture(**kw):
        seen.update(kw)

    monkeypatch.setattr(au, "log_llm_response_usage", _capture)
    pipe = cp.RealCriticPipeline.__new__(cp.RealCriticPipeline)
    pipe.db = db
    pipe.llm = SimpleNamespace(call_llm=AsyncMock(return_value=_resp()))
    pipe.config = SimpleNamespace(entity_goal="goal", task_description="task", enable_different_model=False,
                                  enable_post_critic=True, calibration_note="")
    record = SimpleNamespace(post_critic_tags=[])
    monkeypatch.setattr(pipe, "_ensure_record", lambda _s: record, raising=False)
    monkeypatch.setattr(pipe, "_budget_mode", lambda _s: None, raising=False)
    monkeypatch.setattr(pipe, "_step_description", lambda _s: "step one", raising=False)
    monkeypatch.setattr(pipe, "_render_prior_history", lambda _s: "", raising=False)
    monkeypatch.setattr(pipe, "_render_intel_rules", AsyncMock(return_value=""), raising=False)
    monkeypatch.setattr(pipe, "_cumulative_critic_cost", Decimal("0"), raising=False)
    state = SimpleNamespace(run_id=run.id, company_id=company, iteration=1)
    await pipe.post_action(state, SimpleNamespace(outcome="success", summary="[success] the out", output="the output"))
    assert seen.get("attribution") == "critic_post"
    assert seen["system_prompt"] == cp.POST_PROMPT_SYSTEM and "the output" in seen["user_prompt"]
