"""Phase 11 Track 13 §7.2 chaos case — mock tool returns 500.

When a third-party tool returns a server error, the resilience layer
should:

  1. Classify the failure (ERROR_MSG / TIMEOUT depending on payload).
  2. Try the reformat-retry path (capped at 1 retry).
  3. Try the fallback chain (capped at 1 swap).
  4. Emit a structured ``agent.tool.resilience.final_empty`` telemetry
     event if both fail.
  5. Return a TOOL_EMPTY marker — never raise.

This proves the user-visible contract: a misbehaving external tool
does NOT crash the run; it surfaces as a clean degradation point.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.ai.core.events import capture_test_events
from src.ai.tool_executor import ToolResult
from src.ai.tools.resilience import ToolResilience


def _http_500(tool: str) -> ToolResult:
    return ToolResult(
        tool=tool, args={"input": "?"},
        output="ERROR: 500 internal_server_error",
        success=False,
    )


class _AlwaysFailingExecutor:
    """Both code paths return HTTP 500 — chaos: provider is down hard."""

    def __init__(self):
        self.calls: list[str] = []

    async def execute_from_function_calls(
        self, function_calls, extra_context=None, call_counts=None,
    ):
        self.calls.append("afc")
        return [_http_500(function_calls[0]["name"])]

    async def execute_tools(self, payload, extra_context=None):
        self.calls.append("string")
        return [_http_500(payload[0]["tool"])]


@pytest.mark.asyncio
async def test_run_function_call_survives_persistent_500() -> None:
    exec_ = _AlwaysFailingExecutor()
    res = ToolResilience(
        reformat_fn=AsyncMock(return_value="rewritten"),
        fallback_table=lambda tid, inp: ("fallback_tool", inp),
        tool_executor=exec_,
    )
    with capture_test_events() as evts:
        tr = await res.run_function_call(
            function_call={"name": "flaky_api", "args": {"input": "x"}},
            extra_context={},
        )
    # Never raised; returned a structured failure marker.
    assert tr.success is False
    assert tr.output.startswith("[TOOL_EMPTY]")
    # The full chain was attempted: primary AFC + reformat string + fallback string.
    assert exec_.calls == ["afc", "string", "string"]
    # A ``final_empty`` telemetry event was emitted for the dashboard.
    final = [e for e in evts if e.name.endswith("final_empty")]
    assert final, "expected agent.tool.resilience.final_empty event"


@pytest.mark.asyncio
async def test_string_path_survives_persistent_500() -> None:
    """Same guarantee for the direct TOOL_CALL path that uses
    ``ToolResilience.run`` (not the REACT/AFC variant)."""
    exec_ = _AlwaysFailingExecutor()
    res = ToolResilience(
        reformat_fn=AsyncMock(return_value="rewritten"),
        fallback_table=lambda tid, inp: ("fallback_tool", inp),
        tool_executor=exec_,
    )
    tr = await res.run(
        tool_id="flaky_api",
        raw_input='{"q":"x"}',
        extra_context={},
    )
    assert tr.success is False
    assert tr.output.startswith("[TOOL_EMPTY]")
