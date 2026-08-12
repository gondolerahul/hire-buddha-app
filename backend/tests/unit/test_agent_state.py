"""Phase 11 Track 2 — AgentState unit tests."""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from src.ai.core.agent_state import (
    AgentState,
    Hypothesis,
    Observation,
    Reflection,
    Subgoal,
)
from src.ai.core.budget import Budget
from src.ai.schemas.enums import EntityType


def _make_state(**overrides) -> AgentState:
    base = dict(
        run_id=uuid4(),
        entity_id=uuid4(),
        company_id=uuid4(),
        entity_type=EntityType.AGENT,
        budget=Budget.from_governance(max_cost_usd=1.0, timeout_ms=60_000),
    )
    base.update(overrides)
    return AgentState(**base)


def test_subgoal_lifecycle() -> None:
    s = _make_state()
    sg = s.add_subgoal("research topic", priority=5)
    assert sg.id in {g.id for g in s.open_subgoals}
    assert not s.all_subgoals_achieved()
    assert s.achieve_subgoal(sg.id)
    assert s.all_subgoals_achieved()
    assert sg in s.achieved


def test_achieve_unknown_subgoal_returns_false() -> None:
    s = _make_state()
    s.add_subgoal("a")
    assert not s.achieve_subgoal("nonexistent-id")


def test_plan_helpers_with_no_plan() -> None:
    s = _make_state()
    assert not s.has_plan()
    assert s.plan_ready_steps() == []
    assert not s.plan_has_unblocked_steps()


def test_plan_ready_steps_respects_deps() -> None:
    s = _make_state()
    s.plan_steps = [
        {"step_id": "s1", "type": "TOOL_CALL"},
        {"step_id": "s2", "type": "ACTION",
         "target": {"input_dependencies": ["s1"]}},
        {"step_id": "s3", "type": "ACTION",
         "target": {"input_dependencies": ["s2"]}},
    ]
    # Initially only s1 is ready.
    ready = s.plan_ready_steps()
    assert [r["step_id"] for r in ready] == ["s1"]

    # Complete s1 → s2 becomes ready.
    s.mark_step_complete("s1")
    ready = s.plan_ready_steps()
    assert [r["step_id"] for r in ready] == ["s2"]


def test_plan_step_with_no_id_skipped() -> None:
    s = _make_state()
    s.plan_steps = [{"name": "no-id-step", "type": "ACTION"}]
    assert s.plan_ready_steps() == []


def test_next_step_is_child_invocation() -> None:
    s = _make_state()
    s.plan_steps = [
        {"step_id": "s1", "type": "CHILD_ENTITY_INVOCATION"},
    ]
    assert s.next_step_is_child_invocation()


def test_apply_observation_blocked_adds_blocker() -> None:
    s = _make_state()
    s.apply_observation(Observation(
        iteration=1,
        outcome="blocked",
        novelty_score=0.5,
        goal_delta_estimate=0.0,
        summary="missing data",
    ))
    assert len(s.blockers) == 1
    assert s.blockers[0].detail == "missing data"


def test_snapshot_roundtrip_preserves_state() -> None:
    s = _make_state()
    s.iteration = 7
    s.add_subgoal("g1", priority=1)
    s.add_subgoal("g2", priority=2)
    s.hypotheses.append(Hypothesis(id="h1", claim="lattice is fast", confidence=0.7))
    s.reflections.append(Reflection(iteration=7, scope="run",
                                     what_worked="x", what_didnt="",
                                     cause_hypothesis="", proposed_change="",
                                     confidence=0.6))
    s.budget.consume(tokens=200, usd=Decimal("0.5"), wall_s=15)
    s.plan_steps = [{"step_id": "p1", "type": "ACTION"}]
    s.mark_step_complete("p1")
    s.context_state["topic"] = "post-quantum"

    snap = s.snapshot()
    restored = AgentState.restore(snap)

    assert restored.iteration == 7
    assert restored.entity_type == EntityType.AGENT
    assert [g.description for g in restored.open_subgoals] == ["g1", "g2"]
    assert restored.hypotheses[0].claim == "lattice is fast"
    assert restored.reflections[0].what_worked == "x"
    assert restored.budget.usd_used == Decimal("0.5")
    assert restored.completed_step_ids == {"p1"}
    assert restored.context_state["topic"] == "post-quantum"


@pytest.mark.asyncio
async def test_materialise_then_absorb_is_noop_for_extra_data() -> None:
    s = _make_state()
    s.context_state["k"] = "v"
    out = await s.materialise_context_dict()
    assert out["k"] == "v"
    assert "__agent_state__" in out
    out["k"] = "v2"
    out["new"] = "fresh"
    await s.absorb_context_dict(out)
    assert s.context_state["k"] == "v2"
    assert s.context_state["new"] == "fresh"
    # __agent_state__ marker is NOT round-tripped back.
    assert "__agent_state__" not in s.context_state
