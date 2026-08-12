"""Phase 11 Track 8 — ToolStatus + experimental filter."""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

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
# get_visible_tools_for_company — filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_tool_visible_without_opt_in() -> None:
    ToolRegistry.register(_NoopTool())
    flags = AsyncMock()
    flags.is_on = AsyncMock(return_value=False)
    visible = await ToolRegistry.get_visible_tools_for_company(
        uuid4(), feature_flags=flags,
    )
    assert "noop_test" in visible


@pytest.mark.asyncio
async def test_experimental_tool_hidden_without_opt_in() -> None:
    ToolRegistry.register(_ExperimentalTool())
    flags = AsyncMock()
    flags.is_on = AsyncMock(return_value=False)
    visible = await ToolRegistry.get_visible_tools_for_company(
        uuid4(), feature_flags=flags,
    )
    assert "exp_test" not in visible


@pytest.mark.asyncio
async def test_experimental_tool_visible_when_flag_on() -> None:
    ToolRegistry.register(_ExperimentalTool())

    async def is_on(key, **_kw):
        return key == "tools.experimental.exp_test"

    flags = AsyncMock()
    flags.is_on = AsyncMock(side_effect=is_on)
    visible = await ToolRegistry.get_visible_tools_for_company(
        uuid4(), feature_flags=flags,
    )
    assert "exp_test" in visible


@pytest.mark.asyncio
async def test_deprecated_tool_hidden_by_default() -> None:
    ToolRegistry.register(_DeprecatedTool())
    flags = AsyncMock()
    flags.is_on = AsyncMock(return_value=False)
    visible = await ToolRegistry.get_visible_tools_for_company(
        uuid4(), feature_flags=flags,
    )
    assert "old_test" not in visible


@pytest.mark.asyncio
async def test_deprecated_tool_visible_when_explicitly_included() -> None:
    ToolRegistry.register(_DeprecatedTool())
    flags = AsyncMock()
    flags.is_on = AsyncMock(return_value=False)
    visible = await ToolRegistry.get_visible_tools_for_company(
        uuid4(), feature_flags=flags, include_deprecated=True,
    )
    assert "old_test" in visible
