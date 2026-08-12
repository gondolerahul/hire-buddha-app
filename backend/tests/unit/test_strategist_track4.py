"""Phase 11 Track 4 — Strategist additions: bandit consultation + REPLAN."""
from __future__ import annotations

from uuid import uuid4

import pytest

from src.ai.core.agent_state import AgentState, Subgoal, SupervisorVerdict
from src.ai.core.budget import Budget
from src.ai.core.strategist import Strategist
from src.ai.planning.plan_style_bandit import PlanStyleBandit
from src.ai.schemas.enums import EntityType


def _state(*, plan_steps=None, **kw) -> AgentState:
    return AgentState(
        run_id=uuid4(),
        entity_id=uuid4(),
        company_id=uuid4(),
        entity_type=EntityType.SKILL,
        budget=Budget.from_governance(max_cost_usd=1.0, timeout_ms=60_000),
        plan_steps=plan_steps or [],
        **kw,
    )


# ---------------------------------------------------------------------------
# Bandit consultation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strategist_consults_bandit_when_two_styles_fit() -> None:
    bandit = PlanStyleBandit(epsilon=0.0)
    # Pre-load the table so DAG_PARALLEL is preferred.
    await bandit.update_arm(
        entity_id="any", task_class="general",
        arm="DAG_PARALLEL", success=True, cost_usd=0.02,
    )
    s = Strategist(bandit=bandit)
    state = _state(plan_steps=[
        {"step_id": "s1", "type": "TOOL_CALL"},
        {"step_id": "s2", "type": "TOOL_CALL"},
    ])
    # Hack: re-use the same key the strategist will use.
    bandit._memory_tables[(state.entity_id, state.task_class)] = (
        bandit._memory_tables.pop(("any", "general"))
    )
    move = await s.next_move(state, perception=None)
    assert move.executor == "DAG"
    assert state.chosen_arms_by_iteration == ["DAG_PARALLEL"]


@pytest.mark.asyncio
async def test_strategist_records_arm_even_without_bandit() -> None:
    s = Strategist(bandit=None)
    state = _state(plan_steps=[{"step_id": "s1", "type": "TOOL_CALL"}])
    await s.next_move(state, perception=None)
    # Single ready step → SingleStep path records DAG_SEQUENTIAL.
    assert state.chosen_arms_by_iteration == ["DAG_SEQUENTIAL"]


@pytest.mark.asyncio
async def test_child_entity_path_records_child_arm() -> None:
    s = Strategist()
    state = _state(plan_steps=[
        {"step_id": "s1", "type": "CHILD_ENTITY_INVOCATION"},
    ])
    move = await s.next_move(state, perception=None)
    assert move.executor == "ChildEntity"
    assert state.chosen_arms_by_iteration == ["CHILD_ENTITY"]


# ---------------------------------------------------------------------------
# REPLAN handling in decide_next
# ---------------------------------------------------------------------------


def test_decide_next_replan_replaces_open_subgoals() -> None:
    s = Strategist()
    state = _state()
    state.add_subgoal("original goal", priority=10)
    new_sgs = [
        Subgoal(id="ng1", description="new subgoal A"),
        Subgoal(id="ng2", description="new subgoal B"),
    ]
    super_v = SupervisorVerdict(
        recommendation="REPLAN", confidence=0.8,
        reasoning="drift", proposed_subgoals=new_sgs,
    )
    decision = s.decide_next(state, super_v)
    assert decision.next == "CONTINUE"
    assert decision.next_state_patch.get("replan_requested") is True
    assert [g.description for g in state.open_subgoals] == [
        "new subgoal A", "new subgoal B",
    ]


def test_decide_next_replan_with_no_subgoals_still_continues() -> None:
    s = Strategist()
    state = _state()
    state.add_subgoal("keep me", priority=5)
    super_v = SupervisorVerdict(
        recommendation="REPLAN", confidence=0.6,
        reasoning="drift", proposed_subgoals=[],
    )
    decision = s.decide_next(state, super_v)
    assert decision.next == "CONTINUE"
    assert decision.next_state_patch.get("replan_requested") is True
    # Subgoals untouched
    assert [g.description for g in state.open_subgoals] == ["keep me"]


def test_decide_next_abort_path_unchanged() -> None:
    s = Strategist()
    state = _state()
    super_v = SupervisorVerdict(recommendation="ABORT", reasoning="bad")
    decision = s.decide_next(state, super_v)
    assert decision.next == "ABORT"
