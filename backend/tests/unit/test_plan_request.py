"""PC-25 — the planner and the judge see what the run was asked to do.

``PlanContext`` carried ``input_data`` but the prompt only rendered ``## Goal``,
which ``PlannerService`` fills with the entity's standing goal, so every
dynamic plan (and the judge's pick) was made without the request.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.ai.planning.plan_generator import PlanContext, PlanGenerator, run_request
from src.ai.planning.plan_judge import PlanJudge
from src.ai.planning.planner_service import PlannerService

ASK = "a short brief on how long-term memory is designed in LLM agent frameworks"


def test_the_request_is_the_input_or_the_callers_own_keys():
    assert run_request({"input": ASK, "__memory__": "x"}) == ASK
    assert json.loads(run_request({"topic": "x", "company_id": "c", "__agent_state__": {}})) == {"topic": "x"}
    assert run_request({}) == "" and run_request(None) == ""


def test_the_plan_prompt_carries_the_request():
    gen = PlanGenerator(llm_router=AsyncMock())
    ctx = PlanContext(entity=SimpleNamespace(goal="Produce research reports"),
                      goal="Produce research reports", request=ASK)
    prompt = gen._build_prompt(ctx, temperature=0.2)
    assert "## Request" in prompt and ASK in prompt
    assert "## Goal\nProduce research reports" in prompt


@pytest.mark.asyncio
async def test_the_judge_prompt_carries_the_request():
    seen: dict = {}

    async def call_llm(**kw):
        seen["prompt"] = kw["user_prompt"]
        return SimpleNamespace(output='{"winner": 0, "scores": [1, 0], "reasoning": "r"}',
                               prompt_tokens=0, completion_tokens=0, model_name="")

    judge = PlanJudge(SimpleNamespace(call_llm=call_llm))
    cands = [SimpleNamespace(steps=[], style="DAG_SEQUENTIAL", estimated_cost_usd=0,
                             estimated_latency_s=0, rationale="", invariant_violations=[])] * 2
    await judge.pick(cands, goal="Produce research reports", request=ASK)
    assert "## Request" in seen["prompt"] and ASK in seen["prompt"]


@pytest.mark.asyncio
async def test_the_planner_service_puts_the_runs_request_in_the_context(monkeypatch):
    captured: dict = {}

    async def generate(self, ctx, n=3):  # noqa: ARG001
        captured["ctx"] = ctx
        cand = SimpleNamespace(steps=[{"step_id": "a", "name": "a", "type": "THOUGHT"}],
                               style="DAG_SEQUENTIAL", rationale="", estimated_cost_usd=0)
        return SimpleNamespace(chosen=cand, alternates=[], judge_scores=[], judge_reasoning="")

    monkeypatch.setattr(PlanGenerator, "generate", generate)
    service = PlannerService(AsyncMock(), company_id=uuid4())

    async def roster(*_a, **_k):
        return "", None

    monkeypatch.setattr(service, "_child_roster", roster)
    entity = SimpleNamespace(goal="Produce research reports", planning={}, type="PROCESS")
    run = SimpleNamespace(id=uuid4())
    await service._generate_dynamic_plan_v2(run, entity, {"input": ASK}, {})
    assert captured["ctx"].request == ASK
