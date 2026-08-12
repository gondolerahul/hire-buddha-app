"""Phase 11 Track 2 — Strategist unit tests."""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from src.ai.core.agent_state import AgentState, SupervisorVerdict
from src.ai.core.budget import Budget
from src.ai.core.strategist import Strategist
from src.ai.schemas.enums import EntityType


def _state(entity_type=EntityType.SKILL, plan_steps=None, completed=None,
           budget=None, **kw) -> AgentState:
    s = AgentState(
        run_id=uuid4(),
        entity_id=uuid4(),
        company_id=uuid4(),
        entity_type=entity_type,
        budget=budget or Budget.from_governance(max_cost_usd=1.0, timeout_ms=60_000),
        plan_steps=plan_steps or [],
        completed_step_ids=set(completed or []),
        **kw,
    )
    return s


# ---------------------------------------------------------------------------
# next_move
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_picks_singlestep_when_one_ready_step() -> None:
    s = _state(plan_steps=[{"step_id": "s1", "type": "TOOL_CALL"}])
    move = await Strategist().next_move(s, perception=None)
    assert move.executor == "SingleStep"
    assert move.plan_fragment and move.plan_fragment[0]["step_id"] == "s1"


@pytest.mark.asyncio
async def test_picks_dag_when_multiple_ready_steps() -> None:
    s = _state(plan_steps=[
        {"step_id": "s1", "type": "ACTION"},
        {"step_id": "s2", "type": "ACTION"},
    ])
    move = await Strategist().next_move(s, perception=None)
    assert move.executor == "DAG"
    assert len(move.plan_fragment) == 2


@pytest.mark.asyncio
async def test_dag_disabled_falls_back_to_singlestep() -> None:
    s = _state(plan_steps=[
        {"step_id": "s1", "type": "ACTION"},
        {"step_id": "s2", "type": "ACTION"},
    ])
    move = await Strategist(allow_parallel_dag=False).next_move(s, perception=None)
    assert move.executor == "SingleStep"


@pytest.mark.asyncio
async def test_child_entity_invocation_takes_precedence() -> None:
    s = _state(plan_steps=[
        {"step_id": "s1", "type": "CHILD_ENTITY_INVOCATION"},
        {"step_id": "s2", "type": "ACTION"},
    ])
    move = await Strategist().next_move(s, perception=None)
    assert move.executor == "ChildEntity"


@pytest.mark.asyncio
async def test_agent_without_plan_chooses_recursive() -> None:
    s = _state(entity_type=EntityType.AGENT)
    move = await Strategist().next_move(s, perception=None)
    assert move.executor == "Recursive"


@pytest.mark.asyncio
async def test_default_fallback_is_singlestep() -> None:
    s = _state(entity_type=EntityType.SKILL)
    move = await Strategist().next_move(s, perception=None)
    assert move.executor == "SingleStep"


# ---------------------------------------------------------------------------
# D-3 (Phase 12): per-step Debate selection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_step_never_picks_debate() -> None:
    """Conservative by construction: an ordinary ready step is never debated."""
    s = _state(plan_steps=[{"step_id": "s1", "type": "TOOL_CALL"}])
    move = await Strategist().next_move(s, perception=None)
    assert move.executor == "SingleStep"
    assert move.reasoning_hint != "DEBATE"


@pytest.mark.asyncio
async def test_explicit_debate_hint_selects_debate() -> None:
    s = _state(plan_steps=[{"step_id": "s1", "type": "THOUGHT", "reasoning_hint": "DEBATE"}])
    move = await Strategist().next_move(s, perception=None)
    assert move.executor == "Debate"
    assert move.reasoning_hint == "DEBATE"
    assert move.plan_fragment[0]["step_id"] == "s1"


@pytest.mark.asyncio
async def test_legacy_tot_step_mode_escalates_to_debate() -> None:
    """A pre-D-3 plan carrying a per-step TREE_OF_THOUGHTS mode → Debate."""
    s = _state(plan_steps=[{"step_id": "s1", "type": "THOUGHT", "reasoning_mode": "TREE_OF_THOUGHTS"}])
    move = await Strategist().next_move(s, perception=None)
    assert move.executor == "Debate"


@pytest.mark.asyncio
async def test_governance_high_stakes_flag_selects_debate() -> None:
    s = _state(plan_steps=[{"step_id": "s1", "type": "ACTION", "governance": {"high_stakes": True}}])
    move = await Strategist().next_move(s, perception=None)
    assert move.executor == "Debate"


@pytest.mark.asyncio
async def test_debate_dominates_parallel_dag() -> None:
    """A high-stakes first step is debated even when multiple steps are ready."""
    s = _state(plan_steps=[
        {"step_id": "s1", "type": "THOUGHT", "high_stakes": True},
        {"step_id": "s2", "type": "ACTION"},
    ])
    move = await Strategist().next_move(s, perception=None)
    assert move.executor == "Debate"
    assert len(move.plan_fragment) == 1


@pytest.mark.asyncio
async def test_singlestep_carries_per_step_reasoning_hint() -> None:
    """F-16: a non-debate hint rides along on the SingleStep move."""
    s = _state(plan_steps=[{"step_id": "s1", "type": "THOUGHT", "reasoning_hint": "chain_of_thought"}])
    move = await Strategist().next_move(s, perception=None)
    assert move.executor == "SingleStep"
    assert move.reasoning_hint == "CHAIN_OF_THOUGHT"


@pytest.mark.asyncio
async def test_strategist_never_picks_stub_executor() -> None:
    """The Track 2 Strategist must avoid Dialog / ToolBurst / Skill."""
    for et in EntityType:
        for plan in (
            [],
            [{"step_id": "s1", "type": "ACTION"}],
            [{"step_id": "s1", "type": "TOOL_CALL"},
             {"step_id": "s2", "type": "ACTION"}],
            [{"step_id": "s1", "type": "CHILD_ENTITY_INVOCATION"}],
        ):
            s = _state(entity_type=et, plan_steps=plan)
            move = await Strategist().next_move(s, perception=None)
            assert move.executor not in {"Dialog", "ToolBurst", "Skill"}, (
                f"strategist picked stub for entity_type={et} plan={plan}"
            )


# ---------------------------------------------------------------------------
# decide_next
# ---------------------------------------------------------------------------


def test_decide_next_aborts_on_budget_exhaustion() -> None:
    b = Budget(usd_max=Decimal("1.0"), usd_used=Decimal("1.0"))
    s = _state(budget=b)
    decision = Strategist().decide_next(s)
    assert decision.next == "ABORT"
    assert "budget" in decision.reason


def test_decide_next_supervisor_abort_wins() -> None:
    s = _state()
    sv = SupervisorVerdict(recommendation="ABORT", reasoning="bad")
    assert Strategist().decide_next(s, sv).next == "ABORT"


def test_decide_next_supervisor_pause_routes_to_hitl() -> None:
    s = _state()
    sv = SupervisorVerdict(recommendation="PAUSE", reasoning="waiting human")
    assert Strategist().decide_next(s, sv).next == "PAUSE_HITL"


def test_decide_next_done_when_all_steps_complete() -> None:
    s = _state(plan_steps=[{"step_id": "s1", "type": "ACTION"}],
               completed=["s1"])
    assert Strategist().decide_next(s).next == "DONE"


def test_decide_next_continue_otherwise() -> None:
    s = _state(plan_steps=[{"step_id": "s1", "type": "ACTION"}])
    s.add_subgoal("research")
    assert Strategist().decide_next(s).next == "CONTINUE"


def test_decide_next_continues_while_retry_queued_even_if_plan_complete() -> None:
    """A post-critic REVISE queues a corrective retry; the strategist must not
    declare the run DONE (dropping the retry) just because every plan step is
    marked complete. Regression for the Phase 11 critic-non-gating defect."""
    s = _state(plan_steps=[{"step_id": "s1", "type": "ACTION"}],
               completed=["s1"])
    s.retry_queue.append({"strategy": "RETRY_DIFFERENT_PROMPT", "step_id": "s1"})
    s.corrective_retries_used = 1
    decision = Strategist().decide_next(s)
    assert decision.next == "CONTINUE"
    assert "retry" in decision.reason.lower()


def test_decide_next_stops_honouring_retries_past_cap() -> None:
    """Runaway guard: once corrective retries exceed the per-run cap, a queued
    retry no longer keeps the loop alive — a perpetually-REVISE critic must not
    re-spawn expensive work forever (the doc-factory runaway)."""
    from src.ai.core.strategist import MAX_CORRECTIVE_RETRIES_PER_RUN
    s = _state(plan_steps=[{"step_id": "s1", "type": "ACTION"}],
               completed=["s1"])
    s.retry_queue.append({"strategy": "RETRY_DIFFERENT_PROMPT", "step_id": "s1"})
    s.corrective_retries_used = MAX_CORRECTIVE_RETRIES_PER_RUN + 1
    assert Strategist().decide_next(s).next == "DONE"


def test_decide_next_done_after_retry_queue_drained() -> None:
    """Once the queued retry has been consumed, a fully-complete plan is DONE."""
    s = _state(plan_steps=[{"step_id": "s1", "type": "ACTION"}],
               completed=["s1"])
    assert not s.retry_queue
    assert Strategist().decide_next(s).next == "DONE"
