"""PC-18 — renamed step ids carry their references with them.

``_assign_step_ids`` rewrote every generated ``step_id`` but not the
``{{step_1}}`` placeholders nor ``target.input_dependencies``, so a dependent
step's input never resolved and — since its dependency named an id no step
had — it never became ready: the plan ended with it unrun.
"""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from src.ai.core.agent_state import AgentState
from src.ai.planning.planner_service import PlannerService
from src.ai.schemas.enums import EntityType


def _plan() -> list[dict]:
    return [
        {"step_id": "step_1", "name": "search", "type": "TOOL_CALL",
         "target": {"tool_id": "web_search", "prompt_template": "{{input}}"}},
        {"step_id": "step_2", "name": "summarise", "type": "THOUGHT",
         "description": "Summarise {{step_1}}",
         "target": {"prompt_template": "Summarise: {{step_1.output}} and {{ step_1 }}",
                    "input_dependencies": ["step_1"]}},
        {"step_id": "step_10", "name": "check", "type": "THOUGHT",
         "target": {"prompt_template": "Check {{step_10}} vs {{step_1}}",
                    "input_dependencies": ["step_2"]}},
    ]


def _assign(steps):
    return PlannerService(AsyncMock(), company_id=uuid4())._assign_step_ids(steps, start_from=1)


def test_placeholders_and_dependencies_follow_the_new_ids():
    steps = _assign(_plan())
    s1, s2, s3 = (s["step_id"] for s in steps)
    assert len({s1, s2, s3}) == 3 and "step_1" not in (s1, s2, s3)
    t2 = steps[1]["target"]
    assert t2["prompt_template"] == f"Summarise: {{{{{s1}.output}}}} and {{{{{s1}}}}}"
    assert t2["input_dependencies"] == [s1]
    assert steps[1]["description"] == f"Summarise {{{{{s1}}}}}"
    # "step_10" is its own id, not "step_1" followed by "0".
    assert steps[2]["target"]["prompt_template"] == f"Check {{{{{s3}}}}} vs {{{{{s1}}}}}"
    assert steps[2]["target"]["input_dependencies"] == [s2]
    assert steps[0]["target"]["prompt_template"] == "{{input}}"


def test_a_dependent_step_becomes_ready_when_its_dependency_completes():
    steps = _assign(_plan())
    state = AgentState(run_id=uuid4(), entity_id=uuid4(), company_id=uuid4(),
                       entity_type=EntityType.AGENT)
    state.plan_steps = steps
    state.mark_step_complete(steps[0]["step_id"])
    assert [s["step_id"] for s in state.plan_ready_steps()] == [steps[1]["step_id"]]
