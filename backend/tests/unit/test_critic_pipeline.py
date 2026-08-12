"""Phase 11 Track 3 — CriticPipeline unit tests.

Covers the deterministic surface area of ``RealCriticPipeline``,
``StepHealthRecord`` serialisation, and the model-resolver heuristic.
LLM-call paths are stubbed; the goal here is the *structure*, not
the prompt content.
"""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.ai.core.agent_state import AgentState, Observation
from src.ai.core.budget import Budget
from src.ai.core.strategist import Move
from src.ai.planning.critic_pipeline import (
    CriticMode,
    NoOpCriticPipeline,
    RealCriticPipeline,
    StepHealthRecord,
    resolve_critic_model,
)
from src.ai.planning.failure_tags import FailureTag
from src.ai.schemas.enums import EntityType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state(*, budget: Budget | None = None, iteration: int = 1) -> AgentState:
    s = AgentState(
        run_id=uuid4(),
        entity_id=uuid4(),
        company_id=uuid4(),
        entity_type=EntityType.SKILL,
        iteration=iteration,
        budget=budget or Budget.from_governance(max_cost_usd=1.0, timeout_ms=60_000),
    )
    return s


def _move(**kw) -> Move:
    return Move(
        move_id=kw.get("move_id", "m1"),
        goal_id=kw.get("goal_id", None),
        executor=kw.get("executor", "SingleStep"),
        plan_fragment=kw.get("plan_fragment", [{"step_id": "s1", "type": "TOOL_CALL"}]),
        rationale=kw.get("rationale", "test"),
    )


def _llm_response(text: str, *, cost: float = 0.001) -> SimpleNamespace:
    return SimpleNamespace(output=text, cost_usd=cost)


def _stub_llm(payloads: list[str]) -> AsyncMock:
    """LLMRouter stub returning canned payloads in order."""
    mock = AsyncMock()
    side_effect = [_llm_response(p) for p in payloads]
    mock.call_llm.side_effect = side_effect
    return mock


# ---------------------------------------------------------------------------
# StepHealthRecord
# ---------------------------------------------------------------------------


def test_step_health_record_round_trip_json() -> None:
    rec = StepHealthRecord(
        step_id="s1",
        iteration=2,
        move_id="m1",
        pre_critic_verdict="PASS",
        pre_critic_concerns=["maybe redundant"],
        post_critic_verdict="REVISE",
        post_critic_tags=[FailureTag.OFF_TOPIC, FailureTag.INCOMPLETE],
        post_critic_suggestion="tighten the scope",
        post_critic_cost_usd=Decimal("0.0123"),
    )
    back = StepHealthRecord.from_json(rec.to_json())
    assert back.step_id == "s1"
    assert back.iteration == 2
    assert back.post_critic_verdict == "REVISE"
    assert set(back.post_critic_tags) == {FailureTag.OFF_TOPIC, FailureTag.INCOMPLETE}
    assert back.post_critic_suggestion == "tighten the scope"


def test_step_health_record_is_actionable_failure() -> None:
    assert StepHealthRecord(post_critic_verdict="PASS").is_actionable_failure() is False
    assert StepHealthRecord(post_critic_verdict="REVISE").is_actionable_failure() is True
    assert StepHealthRecord(post_critic_verdict="REJECT").is_actionable_failure() is True


# ---------------------------------------------------------------------------
# resolve_critic_model
# ---------------------------------------------------------------------------


def test_resolve_critic_model_entity_override_wins() -> None:
    assert (
        resolve_critic_model(
            entity_override="gpt-5",
            company_override="claude-opus-4-1",
            actor_model="gemini-2.5-flash",
        )
        == "gpt-5"
    )


def test_resolve_critic_model_company_override_when_no_entity() -> None:
    assert (
        resolve_critic_model(
            entity_override=None,
            company_override="claude-opus-4-1",
            actor_model="gemini-2.5-flash",
        )
        == "claude-opus-4-1"
    )


def test_resolve_critic_model_heuristic_picks_different_model() -> None:
    chosen = resolve_critic_model(actor_model="gemini-2.5-flash")
    assert chosen is not None
    assert "flash" not in chosen.lower()


def test_resolve_critic_model_returns_none_when_no_signal() -> None:
    assert resolve_critic_model() is None


# ---------------------------------------------------------------------------
# NoOpCriticPipeline (parity)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_noop_pipeline_always_passes() -> None:
    p = NoOpCriticPipeline()
    state = _state()
    obs = Observation(iteration=1, outcome="success", novelty_score=0.5, goal_delta_estimate=0.1)
    assert (await p.pre_action(_move(), state)).kind == "PASS"
    assert (await p.post_action(state, obs)).kind == "PASS"
    align = await p.alignment(state, obs)
    assert align.aligned is True and align.drift == 0.0
    sup = await p.supervisor(state)
    assert sup.recommendation == "CONTINUE"
    assert await p.finalize_iteration(state) is None


# ---------------------------------------------------------------------------
# RealCriticPipeline — happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_pipeline_pre_action_pass(monkeypatch) -> None:
    llm = _stub_llm(['{"verdict": "PASS", "concerns": []}'])
    pipe = RealCriticPipeline(
        db=None, llm_router=llm, cortex_service=None,
        config={"entity_goal": "research X"},
    )
    state = _state()
    verdict = await pipe.pre_action(_move(), state)
    assert verdict.kind == "PASS"
    assert pipe._current_record is not None
    assert pipe._current_record.pre_critic_verdict == "PASS"


@pytest.mark.asyncio
async def test_real_pipeline_pre_action_block() -> None:
    llm = _stub_llm(['{"verdict": "BLOCK", "concerns": ["clearly off-topic"]}'])
    pipe = RealCriticPipeline(
        db=None, llm_router=llm, cortex_service=None,
        config={"entity_goal": "research brain modeling"},
    )
    state = _state()
    verdict = await pipe.pre_action(
        _move(executor="ToolBurst", rationale="generate marketing images"),
        state,
    )
    assert verdict.kind == "BLOCK"
    assert verdict.concerns == ["clearly off-topic"]


@pytest.mark.asyncio
async def test_real_pipeline_post_action_parses_tags() -> None:
    llm = _stub_llm([
        '{"verdict": "REVISE", "tags": ["off-topic", "INCOMPLETE", "definitely-not-a-tag"], '
        '"suggestion": "scope down"}'
    ])
    pipe = RealCriticPipeline(
        db=None, llm_router=llm, cortex_service=None,
        config={"entity_goal": "g", "enable_different_model": False},
    )
    state = _state()
    # Pre-create a record (post normally runs after pre_action).
    pipe._current_record = StepHealthRecord(iteration=state.iteration)

    obs = Observation(iteration=1, outcome="partial", novelty_score=0.5,
                      goal_delta_estimate=0.0, summary="some text")
    verdict = await pipe.post_action(state, obs)
    assert verdict.kind == "REVISE"
    assert set(verdict.tags) == {FailureTag.OFF_TOPIC, FailureTag.INCOMPLETE}
    assert verdict.suggestion == "scope down"


@pytest.mark.asyncio
async def test_real_pipeline_alignment_skipped_off_interval() -> None:
    pipe = RealCriticPipeline(
        db=None, llm_router=AsyncMock(), cortex_service=None,
        config={"goal_validation_interval": 5},
    )
    pipe._current_record = StepHealthRecord(iteration=1)
    state = _state(iteration=1)
    obs = Observation(iteration=1, outcome="success", novelty_score=0.5,
                      goal_delta_estimate=0.1, summary="x")
    verdict = await pipe.alignment(state, obs)
    assert verdict.aligned is True
    assert verdict.drift == 0.0


@pytest.mark.asyncio
async def test_real_pipeline_supervisor_skipped_off_interval() -> None:
    pipe = RealCriticPipeline(
        db=None, llm_router=AsyncMock(), cortex_service=None,
        config={"meta_review_interval": 5},
    )
    pipe._current_record = StepHealthRecord(iteration=1)
    state = _state(iteration=2)
    verdict = await pipe.supervisor(state)
    assert verdict.recommendation == "CONTINUE"


# ---------------------------------------------------------------------------
# Budget-degraded mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_degrades_when_critic_share_exceeds_cap() -> None:
    pipe = RealCriticPipeline(
        db=None, llm_router=AsyncMock(), cortex_service=None,
        config={"critic_cost_share_pct": 0.20},
    )
    state = _state()
    state.budget.consume(usd=Decimal("0.10"))
    pipe._cumulative_critic_cost = Decimal("0.05")    # 50% share
    assert pipe._budget_mode(state) is CriticMode.DEGRADED

    # Pre-action returns synthetic PASS without LLM call.
    verdict = await pipe.pre_action(_move(), state)
    assert verdict.kind == "PASS"
    pipe.llm.call_llm.assert_not_called()


# ---------------------------------------------------------------------------
# finalize_iteration — without cortex it is a no-op record return
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_iteration_returns_record_and_caps_history() -> None:
    pipe = RealCriticPipeline(
        db=None,
        llm_router=_stub_llm(['{"verdict": "PASS"}']),
        cortex_service=None,
    )
    state = _state()
    await pipe.pre_action(_move(), state)
    rec = await pipe.finalize_iteration(state)
    assert rec is not None
    assert rec.pre_critic_verdict == "PASS"
    assert state.health_records[-1] is rec

    # Cap to 20.
    for i in range(25):
        state.health_records.append(StepHealthRecord(iteration=i))
    # Push another to trigger trim.
    await pipe.pre_action(_move(), state)
    await pipe.finalize_iteration(state)
    assert len(state.health_records) <= 20
