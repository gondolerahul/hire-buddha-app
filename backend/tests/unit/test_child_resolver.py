"""Phase 11 Track 7 — ChildResolver strategy matrix."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from src.ai.planning.child_resolver import (
    EntityNotFoundError,
    resolve_child_entity_id,
)


def _step(name="invoke child", entity_id=None, name_hint=None) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        target=SimpleNamespace(entity_id=entity_id, entity_name_hint=name_hint),
    )


def _parent(static_steps=None, children=None, parent_id=None):
    return SimpleNamespace(
        id=parent_id or uuid4(),
        planning={"static_plan": {"steps": list(static_steps or [])}},
        hierarchy={"children": list(children or [])},
    )


# ---------------------------------------------------------------------------
# Strategy 1 — UUID passthrough
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strategy_1_uuid_object_passthrough() -> None:
    eid = uuid4()
    resolved = await resolve_child_entity_id(
        _step(entity_id=eid), _parent(),
    )
    assert resolved == eid


@pytest.mark.asyncio
async def test_strategy_1_uuid_string_passthrough() -> None:
    eid = uuid4()
    resolved = await resolve_child_entity_id(
        _step(entity_id=str(eid)), _parent(),
    )
    assert resolved == eid


# ---------------------------------------------------------------------------
# Strategy 2 — static-plan name match
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strategy_2_static_plan_exact_name() -> None:
    child_eid = uuid4()
    parent = _parent(static_steps=[
        {"type": "CHILD_ENTITY_INVOCATION", "name": "Research",
         "target": {"entity_id": str(child_eid)}},
    ])
    resolved = await resolve_child_entity_id(
        _step(name="Research"), parent,
    )
    assert resolved == child_eid


@pytest.mark.asyncio
async def test_strategy_2_substring_match() -> None:
    child_eid = uuid4()
    parent = _parent(static_steps=[
        {"type": "CHILD_ENTITY_INVOCATION", "name": "Research",
         "target": {"entity_id": str(child_eid)}},
    ])
    resolved = await resolve_child_entity_id(
        _step(name="Research topic"), parent,
    )
    assert resolved == child_eid


# ---------------------------------------------------------------------------
# Strategy 3 — hierarchy children index
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strategy_3_hierarchy_index_match() -> None:
    h_eid = uuid4()
    parent = _parent(
        static_steps=[
            {"type": "CHILD_ENTITY_INVOCATION", "name": "RunChild",
             "target": {}},
        ],
        children=[{"child_id": str(h_eid)}],
    )
    resolved = await resolve_child_entity_id(
        _step(name="RunChild"), parent,
    )
    assert resolved == h_eid


# ---------------------------------------------------------------------------
# Strategy 4 — DB entity_name_hint lookup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strategy_4_name_hint_db_lookup() -> None:
    db_eid = uuid4()
    db = AsyncMock()
    row_result = AsyncMock()
    row_result.scalar_one_or_none = lambda: SimpleNamespace(id=db_eid)
    db.execute.return_value = row_result
    parent = _parent()
    resolved = await resolve_child_entity_id(
        _step(name="Anything", name_hint="My Other Agent"),
        parent,
        db,
    )
    assert resolved == db_eid


# ---------------------------------------------------------------------------
# Failure surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_strategy_resolves_raises() -> None:
    with pytest.raises(EntityNotFoundError):
        await resolve_child_entity_id(_step(), _parent(), None)


@pytest.mark.asyncio
async def test_event_emitter_called_on_success() -> None:
    eid = uuid4()
    events: list[tuple[str, dict]] = []

    async def emit(name, **payload):
        events.append((name, payload))

    await resolve_child_entity_id(
        _step(entity_id=eid), _parent(), emit_event=emit,
    )
    assert events and events[0][0] == "agent.child_resolver.fallback"
    assert events[0][1]["strategy_used"] == 1


@pytest.mark.asyncio
async def test_event_emitter_called_on_failure() -> None:
    events: list[tuple[str, dict]] = []

    async def emit(name, **payload):
        events.append((name, payload))

    with pytest.raises(EntityNotFoundError):
        await resolve_child_entity_id(_step(), _parent(), emit_event=emit)
    assert any(e[0] == "agent.child_resolver.failed" for e in events)
