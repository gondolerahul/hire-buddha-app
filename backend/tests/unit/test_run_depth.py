"""max_recursion_depth is a limit on runs, and one setting (EP-06, EP-28)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.ai.governance.composition import child_depth, max_recursion_depth
from src.ai.schemas.entity import HierarchicalEntityCreateRequest
from src.ai.schemas.governance import Governance


@pytest.mark.parametrize("governance, limit", [
    (None, 5),
    ({}, 5),
    ({"max_recursion_depth": 2}, 2),
    ({"max_recursion_depth": 5, "execution_limits": {"max_recursion_depth": 8}}, 8),   # the builder's value
    ({"execution_limits": {"max_recursion_depth": "abc"}, "max_recursion_depth": 3}, 3),
    ({"max_recursion_depth": 0}, 0),
])
def test_the_limit_reads_one_setting_and_the_builders_old_spelling(governance, limit) -> None:
    assert max_recursion_depth(governance) == limit


def test_the_schema_folds_the_old_spelling_into_the_one_setting() -> None:
    gov = Governance(execution_limits={"max_recursion_depth": 3, "max_tool_calls": 7})
    assert gov.max_recursion_depth == 3
    assert gov.execution_limits is not None and gov.execution_limits.max_tool_calls == 7
    assert "max_recursion_depth" not in gov.model_dump()["execution_limits"]


def test_the_api_still_accepts_the_old_spelling() -> None:
    entity = HierarchicalEntityCreateRequest.model_validate({
        "name": "x", "type": "AGENT",
        "governance": {"execution_limits": {"max_recursion_depth": 2}},
    })
    assert entity.governance is not None and entity.governance.max_recursion_depth == 2


def _run(depth=0, max_depth=None):
    return SimpleNamespace(depth=depth, max_depth=max_depth)


def _entity(limit=None):
    return SimpleNamespace(name="e", governance={} if limit is None else {"max_recursion_depth": limit})


def test_a_top_level_runs_limit_comes_from_its_entity() -> None:
    d = child_depth(_run(), _entity(2), _entity())
    assert (d.depth, d.max_depth, d.refused) == (1, 2, None)


def test_a_child_past_the_limit_is_refused() -> None:
    d = child_depth(_run(depth=2, max_depth=2), _entity(), _entity())
    assert d.depth == 3 and d.refused and "depth 3" in d.refused


def test_a_descendants_own_limit_narrows_the_tree_but_never_widens_it() -> None:
    narrowed = child_depth(_run(max_depth=5), _entity(), _entity(1))
    assert narrowed.max_depth == 2            # depth 1 + its own limit 1
    widened = child_depth(_run(max_depth=2), _entity(), _entity(9))
    assert widened.max_depth == 2             # the ancestor's limit holds
