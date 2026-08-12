"""Unit tests for ai.core.step_results — the loop's per-step result
summary that mirrors the legacy engine's ``result_data["steps"]``.

Covers the entry shapes (inline + async-child fold), plan-step lookup,
and the AgentState snapshot round-trip that lets the summary survive a
suspend/resume (a PROCESS folds child results across resumes).
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from src.ai.core.agent_state import AgentState, Budget
from src.ai.core.step_results import (
    find_plan_step,
    record_step_result,
    record_child_step_result,
)
from src.ai.schemas.enums import EntityType


def _make_state() -> AgentState:
    return AgentState(
        run_id=uuid4(), entity_id=uuid4(), company_id=uuid4(),
        entity_type=EntityType.PROCESS, budget=Budget(),
    )


def test_find_plan_step_matches_dict_and_object() -> None:
    steps = [
        {"step_id": "s1", "name": "first", "type": "ACTION"},
        SimpleNamespace(step_id="s2", name="second", type="THOUGHT"),
    ]
    assert find_plan_step(steps, "s1") == {"name": "first", "type": "ACTION"}
    assert find_plan_step(steps, "s2") == {"name": "second", "type": "THOUGHT"}
    assert find_plan_step(steps, "missing") is None
    assert find_plan_step(None, "s1") is None


def test_record_step_result_inline_shape() -> None:
    state = _make_state()
    move = SimpleNamespace(plan_fragment=[
        {"step_id": "step_researcher", "name": "delegate_research",
         "type": "CHILD_ENTITY_INVOCATION"},
    ])
    child_id = uuid4()
    action = SimpleNamespace(output="brief text", children_run_ids=[child_id])

    record_step_result(state, move, "step_researcher", action)

    assert state.step_results == [{
        "step": "delegate_research",
        "step_id": "step_researcher",
        "type": "CHILD_ENTITY_INVOCATION",
        "output": "brief text",
        "child_run_id": str(child_id),
    }]


def test_record_step_result_without_children_omits_child_run_id() -> None:
    state = _make_state()
    move = SimpleNamespace(plan_fragment=[
        {"step_id": "s1", "name": "write", "type": "ACTION"},
    ])
    action = SimpleNamespace(output="done", children_run_ids=[])

    record_step_result(state, move, "s1", action)

    assert "child_run_id" not in state.step_results[0]
    assert state.step_results[0]["output"] == "done"


def test_record_step_result_unknown_step_falls_back_to_step_id() -> None:
    state = _make_state()
    move = SimpleNamespace(plan_fragment=[])
    action = SimpleNamespace(output="x", children_run_ids=None)

    record_step_result(state, move, "ghost", action)

    assert state.step_results[0]["step"] == "ghost"
    assert state.step_results[0]["step_id"] == "ghost"


def test_record_child_step_result_shape() -> None:
    state = _make_state()
    state.plan_steps = [
        {"step_id": "step_synth", "name": "delegate_synthesis",
         "type": "CHILD_ENTITY_INVOCATION"},
    ]
    child_id = uuid4()

    record_child_step_result(state, "step_synth", "folded output", child_id)

    assert state.step_results == [{
        "step": "delegate_synthesis",
        "step_id": "step_synth",
        "type": "CHILD_ENTITY_INVOCATION",
        "output": "folded output",
        "child_run_id": str(child_id),
    }]


def test_step_results_roundtrip_snapshot() -> None:
    state = _make_state()
    state.step_results = [
        {"step": "delegate_research", "step_id": "step_researcher",
         "type": "CHILD_ENTITY_INVOCATION", "output": "Success",
         "child_run_id": str(uuid4())},
    ]
    restored = AgentState.restore(state.snapshot())
    assert restored.step_results == state.step_results
