"""Phase 11 Track 3 — Retry-strategy picker tests.

Exhaustively pins the (FailureTag, budget_pressure) → RetryStrategy
mapping so the picker stays predictable.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from src.ai.core.agent_state import AgentState
from src.ai.core.budget import Budget
from src.ai.core.strategist import Move
from src.ai.planning.critic_pipeline import StepHealthRecord
from src.ai.planning.failure_tags import FailureTag
from src.ai.planning.retry_strategies import (
    RetryExecutor,
    RetryStrategy,
    pick_retry,
)
from src.ai.schemas.enums import EntityType


def _state(*, used_pct: float = 0.0) -> AgentState:
    bud = Budget.from_governance(max_cost_usd=1.0, timeout_ms=60_000)
    if used_pct > 0:
        bud.consume(usd=Decimal(str(used_pct)))
    return AgentState(
        run_id=uuid4(), entity_id=uuid4(), company_id=uuid4(),
        entity_type=EntityType.SKILL, budget=bud,
    )


def _rec(verdict: str, *tags: FailureTag) -> StepHealthRecord:
    return StepHealthRecord(
        step_id="s1", iteration=1, move_id="m1",
        post_critic_verdict=verdict, post_critic_tags=list(tags),
    )


# ---------------------------------------------------------------------------
# Pass-through
# ---------------------------------------------------------------------------


def test_pass_verdict_yields_none() -> None:
    d = pick_retry(_rec("PASS"), _state())
    assert d.strategy is RetryStrategy.NONE


def test_no_post_verdict_yields_none() -> None:
    d = pick_retry(StepHealthRecord(), _state())
    assert d.strategy is RetryStrategy.NONE


# ---------------------------------------------------------------------------
# Budget pressure precedence
# ---------------------------------------------------------------------------


def test_high_budget_pressure_forces_abandon() -> None:
    d = pick_retry(_rec("REJECT", FailureTag.OFF_TOPIC), _state(used_pct=0.95))
    assert d.strategy is RetryStrategy.ABANDON


# ---------------------------------------------------------------------------
# Tag → strategy mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tag,expected", [
    (FailureTag.POLICY_VIOLATION, RetryStrategy.ABANDON),
    (FailureTag.NEEDS_CLARIFICATION, RetryStrategy.ASK_USER),
    (FailureTag.TOOL_FAILURE, RetryStrategy.RETRY_DIFFERENT_TOOL),
    (FailureTag.WRONG_FORMAT, RetryStrategy.RETRY_DIFFERENT_PROMPT),
    (FailureTag.OFF_TOPIC, RetryStrategy.RETRY_DIFFERENT_MODEL),
    (FailureTag.HALLUCINATION, RetryStrategy.RETRY_DIFFERENT_MODEL),
    (FailureTag.CONTRADICTION, RetryStrategy.RETRY_DIFFERENT_MODEL),
    (FailureTag.UNVERIFIABLE, RetryStrategy.RETRY_DIFFERENT_PROMPT),
])
def test_single_tag_strategy(tag: FailureTag, expected: RetryStrategy) -> None:
    d = pick_retry(_rec("REVISE", tag), _state(used_pct=0.1))
    assert d.strategy is expected


def test_incomplete_with_low_pressure_retries_as_is() -> None:
    d = pick_retry(_rec("REVISE", FailureTag.INCOMPLETE), _state(used_pct=0.1))
    assert d.strategy is RetryStrategy.RETRY_AS_IS


def test_incomplete_with_high_pressure_abandons() -> None:
    d = pick_retry(_rec("REVISE", FailureTag.INCOMPLETE), _state(used_pct=0.7))
    assert d.strategy is RetryStrategy.ABANDON


def test_no_tags_with_revise_abandons() -> None:
    d = pick_retry(_rec("REVISE"), _state(used_pct=0.1))
    assert d.strategy is RetryStrategy.ABANDON


# ---------------------------------------------------------------------------
# Tag precedence — POLICY_VIOLATION wins over OFF_TOPIC etc.
# ---------------------------------------------------------------------------


def test_policy_violation_takes_precedence_over_other_tags() -> None:
    d = pick_retry(
        _rec("REJECT", FailureTag.OFF_TOPIC, FailureTag.POLICY_VIOLATION),
        _state(used_pct=0.1),
    )
    assert d.strategy is RetryStrategy.ABANDON


def test_needs_clarification_beats_tool_failure() -> None:
    d = pick_retry(
        _rec("REVISE", FailureTag.TOOL_FAILURE, FailureTag.NEEDS_CLARIFICATION),
        _state(used_pct=0.1),
    )
    assert d.strategy is RetryStrategy.ASK_USER


# ---------------------------------------------------------------------------
# RetryExecutor — follow-up move scaffolding
# ---------------------------------------------------------------------------


def test_retry_executor_builds_followup_with_metadata() -> None:
    rec = _rec("REVISE", FailureTag.WRONG_FORMAT)
    rec.post_critic_suggestion = "wrap in JSON"
    decision = pick_retry(rec, _state(used_pct=0.1))
    move = Move(move_id="m1", goal_id=None, executor="SingleStep",
                plan_fragment=[{"step_id": "s1"}], rationale="orig")
    follow_up = RetryExecutor().build(decision, move, rec)
    assert follow_up is not None
    assert follow_up["strategy"] == RetryStrategy.RETRY_DIFFERENT_PROMPT.value
    assert follow_up["prompt_rewrite_hint"] == "wrap in JSON"
    assert follow_up["original_move_id"] == "m1"


def test_retry_executor_returns_none_for_abandon() -> None:
    rec = _rec("REJECT", FailureTag.POLICY_VIOLATION)
    decision = pick_retry(rec, _state(used_pct=0.1))
    move = Move(move_id="m1", goal_id=None, executor="SingleStep",
                plan_fragment=[], rationale="orig")
    assert RetryExecutor().build(decision, move, rec) is None


def test_retry_executor_ask_user_payload() -> None:
    rec = _rec("REVISE", FailureTag.NEEDS_CLARIFICATION)
    rec.post_critic_suggestion = "what timeframe?"
    decision = pick_retry(rec, _state(used_pct=0.1))
    move = Move(move_id="m1", goal_id=None, executor="SingleStep",
                plan_fragment=[], rationale="orig")
    follow_up = RetryExecutor().build(decision, move, rec)
    assert follow_up is not None
    assert follow_up["ask_user"] is True
    assert follow_up["suggestion"] == "what timeframe?"


# ---------------------------------------------------------------------------
# Retry exhaustion
# ---------------------------------------------------------------------------


def test_is_exhausted_counts_only_actionable_failures() -> None:
    state = _state()
    state.health_records = [
        _rec("PASS"),
        _rec("REVISE", FailureTag.INCOMPLETE),
        _rec("REJECT", FailureTag.OFF_TOPIC),
        _rec("REVISE", FailureTag.WRONG_FORMAT),
    ]
    # 3 actionable failures > max_retries=2 → exhausted
    assert RetryExecutor.is_exhausted(state, "s1") is True


def test_is_exhausted_false_below_cap() -> None:
    state = _state()
    state.health_records = [_rec("REVISE", FailureTag.INCOMPLETE)]
    assert RetryExecutor.is_exhausted(state, "s1") is False
