"""One tool call cannot hold the worker past its timeout (P8.3 — EP-08).

``ToolDefinition.max_execution_seconds`` was unreachable configuration; what
bounded a call was the enclosing step's timeout and whatever the tool did
itself, so a tool with no internal timeout in a step with a generous one held
the worker. Now every call runs under a timeout: the grant's
``timeout_seconds``, else the tool's own (120 s; slow renderers declare more).
A call that runs out is a failed call the healing ladder may handle.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from src.ai.governance.tool_access import ToolAccess
from src.ai.schemas.capabilities import ToolGrant
from src.ai.tool_executor import ToolExecutor
from src.ai.tools.base import Tool, ToolOutput, ToolParams, ToolRegistry


class _SleepParams(ToolParams):
    seconds: float = 30.0


class _Sleeps(Tool):
    name = "p83_sleeper"
    description = "sleeps"
    Params = _SleepParams
    timeout_seconds = 5

    async def execute(self, params, ctx):
        await asyncio.sleep(params.seconds)
        return ToolOutput(output="woke")


@pytest.fixture
def sleeper():
    tool = _Sleeps()
    ToolRegistry._tools[tool.name] = tool
    yield tool
    ToolRegistry._tools.pop(tool.name, None)


@pytest.mark.asyncio
async def test_the_grants_timeout_fails_a_call_that_runs_long(sleeper):
    access = ToolAccess(company_id=None, grants={sleeper.name: ToolGrant(tool_id=sleeper.name, timeout_seconds=1)})
    start = time.monotonic()
    [tr] = await ToolExecutor.execute_from_function_calls(
        [{"name": sleeper.name, "args": {"seconds": 30}}], extra_context={}, access=access)
    assert time.monotonic() - start < 5
    assert not tr.success and "tool_timeout" in tr.error and "1s" in tr.error


@pytest.mark.asyncio
async def test_without_a_grant_timeout_the_tools_own_applies(sleeper):
    access = ToolAccess(company_id=None, grants={sleeper.name: ToolGrant(tool_id=sleeper.name)})
    assert access.timeout_for(sleeper.name, sleeper) == 5
    [tr] = await ToolExecutor.execute_from_function_calls(
        [{"name": sleeper.name, "args": {"seconds": 0.01}}], extra_context={}, access=access)
    assert tr.success and tr.output == "woke"


def test_slow_tools_declare_longer_timeouts_and_the_grant_is_bounded():
    from src.ai.tools.media.video.video_generate import VideoGenerateTool
    assert VideoGenerateTool.timeout_seconds == 600 and Tool.timeout_seconds == 120
    with pytest.raises(ValueError):
        ToolGrant(tool_id="x", timeout_seconds=601)
