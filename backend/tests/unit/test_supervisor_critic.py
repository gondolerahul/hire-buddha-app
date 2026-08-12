"""Phase 11 Track 4 — SupervisorCritic tests.

Pins the deterministic short-circuits (budget ABORT, 3-clean fast path)
and the LLM-output parsing into a typed SupervisorVerdict.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.ai.core.agent_state import AgentState
from src.ai.core.budget import Budget
from src.ai.planning.step_health_record import StepHealthRecord
from src.ai.planning.supervisor_critic import (
    SupervisorCritic,
    SupervisorCriticConfig,
)
from src.ai.schemas.enums import EntityType


def _state(*, budget: Budget | None = None, iteration: int = 1) -> AgentState:
    return AgentState(
        run_id=uuid4(),
        entity_id=uuid4(),
        company_id=uuid4(),
        entity_type=EntityType.SKILL,
        iteration=iteration,
        budget=budget or Budget.from_governance(max_cost_usd=1.0, timeout_ms=60_000),
    )


def _llm(payload: str, *, cost: float = 0.002) -> AsyncMock:
    m = AsyncMock()
    m.call_llm.return_value = SimpleNamespace(output=payload, cost_usd=cost)
    return m


# ---------------------------------------------------------------------------
# 1. Budget-pressure short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_abort_on_budget_pressure_at_threshold() -> None:
    sc = SupervisorCritic(llm_router=AsyncMock())
    state = _state()
    # Consume 96% of the budget.
    state.budget.consume(usd=Decimal("0.96"))
    verdict = await sc.assess(state)
    assert verdict.recommendation == "ABORT"
    assert verdict.confidence >= 0.9


# ---------------------------------------------------------------------------
# 2. Fast path: three clean health records
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fast_path_continue_skips_llm() -> None:
    llm = AsyncMock()
    sc = SupervisorCritic(llm_router=llm)
    state = _state()
    state.health_records = [
        StepHealthRecord(post_critic_verdict="PASS", alignment_aligned=True),
        StepHealthRecord(post_critic_verdict="PASS", alignment_aligned=True),
        StepHealthRecord(post_critic_verdict="PASS", alignment_aligned=None),
    ]
    verdict = await sc.assess(state)
    assert verdict.recommendation == "CONTINUE"
    llm.call_llm.assert_not_called()


@pytest.mark.asyncio
async def test_fast_path_disabled_falls_through_to_llm() -> None:
    llm = _llm('{"recommendation": "CONTINUE", "confidence": 0.7, "reasoning": "ok"}')
    sc = SupervisorCritic(
        llm_router=llm,
        config=SupervisorCriticConfig(fast_path_enabled=False),
    )
    state = _state()
    state.health_records = [
        StepHealthRecord(post_critic_verdict="PASS", alignment_aligned=True),
    ] * 3
    await sc.assess(state)
    llm.call_llm.assert_called_once()


@pytest.mark.asyncio
async def test_fast_path_rejects_when_alignment_false() -> None:
    llm = _llm('{"recommendation": "REPLAN", "confidence": 0.6, "reasoning": "drift"}')
    sc = SupervisorCritic(llm_router=llm)
    state = _state()
    state.health_records = [
        StepHealthRecord(post_critic_verdict="PASS", alignment_aligned=True),
        StepHealthRecord(post_critic_verdict="PASS", alignment_aligned=False),
        StepHealthRecord(post_critic_verdict="PASS", alignment_aligned=True),
    ]
    verdict = await sc.assess(state)
    # Falls through to LLM path
    assert verdict.recommendation == "REPLAN"


# ---------------------------------------------------------------------------
# 3. JSON parsing — proposed subgoals on REPLAN
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replan_parses_proposed_subgoals() -> None:
    payload = (
        '{"recommendation": "REPLAN", "confidence": 0.82, '
        '"reasoning": "Off-topic drift in last 2 steps", '
        '"proposed_subgoals": ['
        '{"description": "narrow scope to brain modelling", "priority": 5},'
        '{"description": "exclude asset-management results", "priority": 3}'
        ']}'
    )
    sc = SupervisorCritic(
        llm_router=_llm(payload),
        config=SupervisorCriticConfig(fast_path_enabled=False),
    )
    verdict = await sc.assess(_state())
    assert verdict.recommendation == "REPLAN"
    assert verdict.confidence == pytest.approx(0.82)
    assert len(verdict.proposed_subgoals) == 2
    assert verdict.proposed_subgoals[0].description == "narrow scope to brain modelling"
    assert verdict.proposed_subgoals[0].priority == 5


@pytest.mark.asyncio
async def test_continue_does_not_parse_proposed_subgoals() -> None:
    payload = (
        '{"recommendation": "CONTINUE", "confidence": 0.7, '
        '"reasoning": "ok", '
        '"proposed_subgoals": [{"description": "ignored", "priority": 1}]}'
    )
    sc = SupervisorCritic(
        llm_router=_llm(payload),
        config=SupervisorCriticConfig(fast_path_enabled=False),
    )
    verdict = await sc.assess(_state())
    assert verdict.recommendation == "CONTINUE"
    assert verdict.proposed_subgoals == []


@pytest.mark.asyncio
async def test_bad_json_falls_back_to_continue() -> None:
    sc = SupervisorCritic(
        llm_router=_llm("not json at all"),
        config=SupervisorCriticConfig(fast_path_enabled=False),
    )
    verdict = await sc.assess(_state())
    assert verdict.recommendation == "CONTINUE"


@pytest.mark.asyncio
async def test_llm_error_returns_continue() -> None:
    llm = AsyncMock()
    llm.call_llm.side_effect = RuntimeError("provider down")
    sc = SupervisorCritic(
        llm_router=llm,
        config=SupervisorCriticConfig(fast_path_enabled=False),
    )
    verdict = await sc.assess(_state())
    assert verdict.recommendation == "CONTINUE"
    assert "Supervisor LLM error" in verdict.reasoning


@pytest.mark.asyncio
async def test_no_llm_router_returns_continue() -> None:
    sc = SupervisorCritic(llm_router=None)
    verdict = await sc.assess(_state())
    assert verdict.recommendation == "CONTINUE"
