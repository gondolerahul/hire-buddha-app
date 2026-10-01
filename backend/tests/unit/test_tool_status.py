"""Phase 11 Track 8 — ToolStatus; the opt-in gate is enforced by ToolAccess (TL-13)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.ai.governance.tool_access import ToolAccess, ToolDenied
from src.ai.tools.base import Tool, ToolRegistry, ToolStatus


class _NoopTool(Tool):
    name = "noop_test"
    description = "test tool"

    async def run(self, input_data: str) -> str:
        return input_data


class _ExperimentalTool(Tool):
    name = "exp_test"
    description = "experimental"
    status = ToolStatus.EXPERIMENTAL

    async def run(self, input_data: str) -> str:
        return input_data


class _DeprecatedTool(Tool):
    name = "old_test"
    description = "deprecated"
    status = ToolStatus.DEPRECATED

    async def run(self, input_data: str) -> str:
        return input_data


# ---------------------------------------------------------------------------
# Enum sanity
# ---------------------------------------------------------------------------


def test_tool_status_values() -> None:
    assert ToolStatus.ACTIVE.value == "ACTIVE"
    assert ToolStatus.EXPERIMENTAL.value == "EXPERIMENTAL"
    assert ToolStatus.DEPRECATED.value == "DEPRECATED"


def test_tool_defaults_to_active() -> None:
    assert _NoopTool.status == ToolStatus.ACTIVE


# ---------------------------------------------------------------------------
# The status gate, through the one resolution point (TL-13, P3.1)
# ---------------------------------------------------------------------------


@pytest.fixture
def registered():
    tools = [_NoopTool(), _ExperimentalTool(), _DeprecatedTool()]
    for t in tools:
        ToolRegistry.register(t)
    yield
    for t in tools:
        ToolRegistry._tools.pop(t.name, None)


def _entity(*names: str):
    return SimpleNamespace(
        name="e", type="ACTION", capabilities={"tools": [{"tool_id": n} for n in names]},
        planning={}, logic_gate={}, metadata_extensions={},
    )


async def _access(flag_on: bool, *names: str) -> ToolAccess:
    flags = AsyncMock()
    flags.is_on = AsyncMock(return_value=flag_on)
    return await ToolAccess.load(None, uuid4(), _entity(*names), feature_flags=flags)


@pytest.mark.asyncio
async def test_active_tool_resolves_without_opt_in(registered) -> None:
    access = await _access(False, "noop_test")
    assert isinstance(access.resolve("noop_test"), _NoopTool)


@pytest.mark.asyncio
async def test_experimental_tool_refused_without_opt_in(registered) -> None:
    access = await _access(False, "exp_test")
    denied = access.resolve("exp_test")
    assert isinstance(denied, ToolDenied) and denied.reason == "opt_in_required"
    assert access.schemas() == []


@pytest.mark.asyncio
async def test_experimental_tool_resolves_when_flag_on(registered) -> None:
    access = await _access(True, "exp_test")
    assert isinstance(access.resolve("exp_test"), _ExperimentalTool)
    assert [s["name"] for s in access.schemas()] == ["exp_test"]


@pytest.mark.asyncio
async def test_granted_deprecated_tool_still_runs(registered) -> None:
    """Like a DEPRECATED entity (D6): it runs, with an event, so an entity
    that uses it does not break the day it is deprecated."""
    access = await _access(False, "old_test")
    assert isinstance(access.resolve("old_test"), _DeprecatedTool)
