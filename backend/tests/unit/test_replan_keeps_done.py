"""A replan replaces what is left, never what is done (P7.7 — PC-09, AK-17).

``_handle_replan`` guarded static plans only. For a dynamic plan it replaced
``plan_steps`` and cleared ``completed_step_ids``, so every supervisor REPLAN
re-ran and re-paid for the finished steps — and the higher spend made the
supervisor more likely to intervene again. Now the finished steps stay
(ids, steps, outputs), the planner is told they are done, and only the rest
is replaced.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.ai.core.agent_loop import AgentLoop
from src.ai.core.agent_state import AgentState, Budget, SupervisorVerdict
from src.ai.core.feature_flags import FeatureFlags
from src.ai.schemas.enums import EntityType


def _state() -> AgentState:
    state = AgentState(run_id=uuid4(), entity_id=uuid4(), company_id=uuid4(), entity_type=EntityType.AGENT,
                       budget=Budget.from_governance(max_cost_usd=5.0, timeout_ms=60_000))
    state.plan_steps = [{"step_id": "s1", "name": "Research"}, {"step_id": "s2", "name": "Write"}]
    state.completed_step_ids = {"s1"}
    state.context_state["s1"] = "twelve sources found"
    return state


@pytest.mark.asyncio
async def test_a_replan_keeps_the_finished_steps(monkeypatch):
    from src.ai.planning.planner_service import PlannerService
    asked: dict = {}

    async def _adapt(self, *, original_plan, completed_steps, failed_step, goal, request, entity, run_id):
        asked["completed"] = completed_steps
        return [{"step_id": "step_3_ab", "name": "Write, shorter",
                 "target": {"input_dependencies": ["s1"]}}]

    monkeypatch.setattr(PlannerService, "adapt_plan", _adapt)
    loop = AgentLoop(db=SimpleNamespace(), redis=None, feature_flags=FeatureFlags(db=None))
    loop._entity = SimpleNamespace(goal="report", planning={"dynamic_planning": {"enabled": True}})
    state = _state()
    await loop._handle_replan(state, SupervisorVerdict(recommendation="REPLAN"))

    assert [s["step_id"] for s in state.plan_steps] == ["s1", "step_3_ab"]
    assert state.completed_step_ids == {"s1"}                    # not wiped
    assert [s["step_id"] for s in state.plan_ready_steps()] == ["step_3_ab"]
    assert asked["completed"] == [{"step_id": "s1", "name": "s1", "output": "twelve sources found"}]


def test_the_generator_is_told_what_is_done():
    from src.ai.planning.plan_generator import PlanContext, PlanGenerator
    gen = PlanGenerator.__new__(PlanGenerator)
    ctx = PlanContext(entity=None, goal="report",
                      completed_steps=[{"step_id": "s1", "name": "Research", "output": "twelve sources"}])
    prompt = gen._build_prompt(ctx, temperature=0.2)
    assert "## Already done" in prompt and "{{s1}} Research: twelve sources" in prompt
