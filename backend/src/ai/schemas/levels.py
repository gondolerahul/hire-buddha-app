"""schemas/levels.py — the six levels of the entity hierarchy (R1).

    GRAPH (6)   the entire business
    LOOP (5)    a department or function
    PROCESS (4) a business process
    AGENT (3)   a role
    SKILL (2)   reusable instructions, scripts and assets with an IO contract
    ACTION (1)  a wrapper around a tool

Every entity runs through the same ``AgentLoop`` with the same planning,
critics and limits; the level is the only thing that differs between them.
Anything that has to vary with the kind of entity derives it from
:func:`entity_level` here, never from a comparison against a type name.

Composition rule: a child sits at its parent's level or below it, never above
(:func:`can_parent`). Same-level composition is allowed, so a department can
federate sub-departments, a process can call sub-processes and a skill can
reuse a skill.
"""
from __future__ import annotations

from typing import Any

from src.ai.schemas.enums import EntityType

__all__ = [
    "ENTITY_LEVELS",
    "ENTITY_TYPES_BY_LEVEL",
    "LEVEL_DESCRIPTIONS",
    "entity_level",
    "can_parent",
]

ENTITY_LEVELS: dict[EntityType, int] = {
    EntityType.ACTION: 1,
    EntityType.SKILL: 2,
    EntityType.AGENT: 3,
    EntityType.PROCESS: 4,
    EntityType.LOOP: 5,
    EntityType.GRAPH: 6,
}

# Lowest level first.
ENTITY_TYPES_BY_LEVEL: tuple[EntityType, ...] = tuple(
    sorted(ENTITY_LEVELS, key=lambda t: ENTITY_LEVELS[t])
)

# What each level maps to in the business — shown to authors and to the
# Meta-Agent's manifest.
LEVEL_DESCRIPTIONS: dict[EntityType, str] = {
    EntityType.ACTION: "A wrapper around one tool: its binding, schema and policy.",
    EntityType.SKILL: (
        "Reusable instructions, scripts and assets with an input/output contract."
    ),
    EntityType.AGENT: "A role: the skills, tools and memory one job needs.",
    EntityType.PROCESS: "A business process: the roles and skills it coordinates.",
    EntityType.LOOP: "A department or function: the processes it runs.",
    EntityType.GRAPH: "The entire business: its departments and functions.",
}


def _as_entity_type(value: Any) -> EntityType:
    raw = getattr(value, "value", value)
    return EntityType(str(raw).upper())


def entity_level(entity_type: Any) -> int:
    """The level of an ``EntityType`` (or its string value).

    Raises ``ValueError`` for a value that is not one of the six types.
    """
    return ENTITY_LEVELS[_as_entity_type(entity_type)]


def can_parent(parent_type: Any, child_type: Any) -> bool:
    """Whether an entity of ``parent_type`` may compose one of ``child_type``."""
    return entity_level(child_type) <= entity_level(parent_type)
