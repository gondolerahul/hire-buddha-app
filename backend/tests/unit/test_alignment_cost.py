"""The alignment check's cost is on its verdict and its health record (P4.2, PC-03).

``AlignmentVerdict`` had no cost field and ``StepHealthRecord.alignment_cost_usd``
was never set, so a paid LLM call showed as free in the run's iteration record
and telemetry. (Its spend reaches the run's bill through its usage rows since
P4.1.)
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.ai.core.agent_state import AlignmentVerdict


def test_the_verdict_has_a_cost():
    assert AlignmentVerdict().cost_usd == Decimal("0")


@pytest.mark.asyncio
async def test_the_verifier_returns_what_its_rows_cost(monkeypatch):
    import src.ai.llm.router as router_mod
    import src.ai.usage_service as usage_mod
    from src.ai.planning.goal_alignment import GoalAlignmentVerifier

    resp = SimpleNamespace(model_name="m", prompt_tokens=100, completion_tokens=20,
                           output='{"aligned": false, "confidence": 0.2, "correction_hint": "stay on topic"}')

    class _Router:
        def __init__(self, **_kw):
            pass

        async def call_llm(self, **_kw):
            return resp

    rows = iter([SimpleNamespace(calculated_cost=Decimal("0.0010")),
                 SimpleNamespace(calculated_cost=Decimal("0.0004"))])
    monkeypatch.setattr(router_mod, "LLMRouter", _Router)
    monkeypatch.setattr(usage_mod.UsageService, "log_usage", AsyncMock(side_effect=lambda **_k: next(rows)))
    run_id = uuid4()
    result = await GoalAlignmentVerifier(None, uuid4(), run_id=run_id).verify_step_alignment(
        entity_goal="g", task_desc="t", step_output="off-topic text", step_name="s")
    assert result["cost_usd"] == Decimal("0.0014")
    assert result["aligned"] is False and result["correction_hint"] == "stay on topic"
    assert all(c.kwargs["execution_id"] == run_id for c in usage_mod.UsageService.log_usage.await_args_list)


@pytest.mark.asyncio
async def test_the_pipeline_puts_the_cost_on_the_verdict_and_the_record(monkeypatch):
    import src.ai.planning.goal_alignment as ga
    from src.ai.planning import critic_pipeline as cp

    monkeypatch.setattr(ga.GoalAlignmentVerifier, "verify_step_alignment", AsyncMock(return_value={
        "aligned": True, "confidence": 0.9, "correction_hint": "", "cost_usd": Decimal("0.0021")}))
    pipe = cp.RealCriticPipeline.__new__(cp.RealCriticPipeline)
    pipe.db = None
    pipe.config = SimpleNamespace(goal_validation_interval=1, entity_goal="g", task_description="t")
    record = SimpleNamespace()
    monkeypatch.setattr(pipe, "_ensure_record", lambda _s: record, raising=False)
    monkeypatch.setattr(pipe, "_budget_mode", lambda _s: None, raising=False)
    monkeypatch.setattr(pipe, "_step_description", lambda _s: "step", raising=False)
    state = SimpleNamespace(iteration=1, company_id=uuid4(), run_id=uuid4())

    verdict = await pipe.alignment(state, SimpleNamespace(summary="output"))

    assert verdict.cost_usd == Decimal("0.0021")
    assert record.alignment_cost_usd == Decimal("0.0021")
