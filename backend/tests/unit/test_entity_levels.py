"""The six levels of the hierarchy and the composition rule (R1).

GRAPH (the business) > LOOP (a department) > PROCESS > AGENT (a role) >
SKILL > ACTION (a tool wrapper). The level is the only thing that differs
between entities; a child sits at its parent's level or below.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.ai.schemas import EntityType
from src.ai.schemas.entity import HierarchicalEntityCreate, HierarchicalEntityResponse
from src.ai.schemas.levels import (
    ENTITY_LEVELS,
    ENTITY_TYPES_BY_LEVEL,
    LEVEL_DESCRIPTIONS,
    can_parent,
    entity_level,
)

SIX = ["ACTION", "SKILL", "AGENT", "PROCESS", "LOOP", "GRAPH"]


def test_entity_type_is_the_six_levels_lowest_first() -> None:
    assert [t.value for t in EntityType] == SIX
    assert [t.value for t in ENTITY_TYPES_BY_LEVEL] == SIX
    assert [ENTITY_LEVELS[t] for t in ENTITY_TYPES_BY_LEVEL] == [1, 2, 3, 4, 5, 6]
    assert set(LEVEL_DESCRIPTIONS) == set(EntityType)


@pytest.mark.parametrize("value, level", [
    ("ACTION", 1), ("SKILL", 2), ("AGENT", 3), ("PROCESS", 4), ("LOOP", 5), ("GRAPH", 6),
    ("loop", 5), (EntityType.GRAPH, 6),
])
def test_entity_level(value, level) -> None:
    assert entity_level(value) == level


def test_entity_level_refuses_an_unknown_type() -> None:
    with pytest.raises(ValueError):
        entity_level("WORKFLOW")


def test_a_child_sits_at_its_parents_level_or_below() -> None:
    # Same level: sub-departments, sub-processes, a skill reusing a skill.
    for t in EntityType:
        assert can_parent(t, t)
    assert can_parent("GRAPH", "LOOP")
    assert can_parent("GRAPH", "ACTION")
    assert can_parent("LOOP", "PROCESS")
    assert can_parent("PROCESS", "AGENT")
    assert can_parent("AGENT", "SKILL")
    assert can_parent("SKILL", "ACTION")
    # Never above.
    assert not can_parent("ACTION", "SKILL")
    assert not can_parent("AGENT", "PROCESS")
    assert not can_parent("PROCESS", "LOOP")
    assert not can_parent("LOOP", "GRAPH")


@pytest.mark.parametrize("value", ["LOOP", "GRAPH"])
def test_loop_and_graph_can_be_authored(value) -> None:
    entity = HierarchicalEntityCreate(name=f"A {value.lower()}", type=value)
    assert entity.type == EntityType(value)


@pytest.mark.parametrize("value", ["LOOP", "GRAPH"])
def test_loop_and_graph_are_read_as_themselves(value) -> None:
    """The read path used to present LOOP (and anything unmodelled) as PROCESS."""
    now = datetime.now(timezone.utc)
    response = HierarchicalEntityResponse.model_validate({
        "id": uuid4(), "company_id": uuid4(), "parent_id": None,
        "name": "Sales", "type": value, "created_at": now, "updated_at": now,
    })
    assert response.type == EntityType(value)


def test_an_unknown_stored_type_still_reads() -> None:
    now = datetime.now(timezone.utc)
    response = HierarchicalEntityResponse.model_validate({
        "id": uuid4(), "company_id": uuid4(), "parent_id": None,
        "name": "Legacy", "type": "WORKFLOW", "created_at": now, "updated_at": now,
    })
    assert response.type == EntityType.PROCESS


def test_the_table_is_held_to_the_six_levels() -> None:
    from src.ai.orm.entity import HierarchicalEntity

    checks = {
        c.name: str(c.sqltext)
        for c in HierarchicalEntity.__table__.constraints
        if c.__class__.__name__ == "CheckConstraint"
    }
    sql = checks["ck_hierarchical_entities_type"]
    for value in SIX:
        assert f"'{value}'" in sql
