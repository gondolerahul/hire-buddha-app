"""A step's output is stored once, by id; step names are unique (P8.4 — EP-18,
EP-I6).

``store_step_output`` wrote every output under the step's name and again
under its id: twice the context (trimmed sooner by summarisation), and two
steps with one name silently overwrote each other. Now it is stored once,
under the id, and ``{{name}}`` resolves through the run's name→id map; names
are unique — the API refuses a repeat, the planner renames one, the graph
editor flags it.
"""
from __future__ import annotations

import pytest

from src.ai.core.context_utils import store_step_output
from src.ai.core.prompt_utils import parse_variables
from src.ai.core.step_signals import StepSignals, step_signals


def test_a_name_reference_resolves_to_the_output_stored_by_id():
    ctx: dict = {}
    store_step_output(ctx, "Research", "step_1_ab12", "twelve sources")
    assert ctx == {"step_1_ab12": "twelve sources"}
    with step_signals(StepSignals(step_names={"Research": "step_1_ab12"})):
        assert parse_variables("Use {{Research}} and {{step_1_ab12}}.", ctx) == \
            "Use twelve sources and twelve sources."
    assert parse_variables("{{Research}}", ctx) == "{{Research}}"   # no map, no guess


def test_the_api_refuses_a_plan_that_repeats_a_step_name():
    from pydantic import ValidationError
    from src.ai.schemas.entity import HierarchicalEntityCreateRequest
    steps = [{"step_id": "a", "name": "Draft", "type": "ACTION"}, {"step_id": "b", "name": "Draft", "type": "ACTION"}]
    with pytest.raises(ValidationError, match="Step names must be unique.*Draft"):
        HierarchicalEntityCreateRequest(name="x", type="AGENT", planning={"static_plan": {"enabled": True, "steps": steps}})


def test_the_planner_renames_a_repeated_name():
    from src.ai.planning.planner_service import assign_step_ids
    steps = assign_step_ids([{"name": "Search"}, {"name": "Search"}, {"name": "Write"}])
    assert [s["name"] for s in steps] == ["Search", "Search (2)", "Write"]
