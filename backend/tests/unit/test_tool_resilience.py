"""Phase 11 Track 8 — ToolResilience reformat / fallback / final-empty."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.ai.tool_executor import ToolResult
from src.ai.tools.resilience import (
    FailureKind,
    ToolResilience,
    classify_tool_failure,
)


def _ok(output: str = "good"):
    return ToolResult(tool="web_search", args={}, output=output, success=True)


def _format_fail():
    return ToolResult(
        tool="web_search", args={},
        output='ERROR: invalid json {"missing": ', success=False,
    )


def _empty():
    return ToolResult(tool="web_search", args={}, output="", success=True)


def _timeout():
    return ToolResult(
        tool="web_search", args={},
        output="ERROR: request timed out", success=False,
    )


def _io():
    return ToolResult(
        tool="file_writer", args={},
        output="ERROR: errno 22 invalid argument", success=False,
    )


# ---------------------------------------------------------------------------
# classify_tool_failure
# ---------------------------------------------------------------------------


def test_classify_clean_result_is_none() -> None:
    assert classify_tool_failure(_ok()) is FailureKind.NONE


def test_classify_empty_result() -> None:
    assert classify_tool_failure(_empty()) is FailureKind.EMPTY


def test_classify_format_error() -> None:
    assert classify_tool_failure(_format_fail()) is FailureKind.FORMAT


def test_classify_timeout() -> None:
    assert classify_tool_failure(_timeout()) is FailureKind.TIMEOUT


def test_classify_io() -> None:
    assert classify_tool_failure(_io()) is FailureKind.IO


def test_classify_error_msg_bucket() -> None:
    tr = ToolResult(tool="x", args={}, output="ERROR: something else",
                    success=True)
    assert classify_tool_failure(tr) is FailureKind.ERROR_MSG


# ---------------------------------------------------------------------------
# run() — reformat-retry path
# ---------------------------------------------------------------------------


class _FakeExecutor:
    """Stub for ToolExecutor.execute_tools; returns a queue of results."""

    def __init__(self, results: list[ToolResult]):
        self.results = list(results)
        self.calls: list[dict] = []

    async def execute_tools(self, payload, extra_context=None):
        self.calls.append({"payload": payload, "ctx": extra_context})
        return [self.results.pop(0)]


@pytest.mark.asyncio
async def test_reformat_retry_recovers_after_format_error() -> None:
    fx = _FakeExecutor([_format_fail(), _ok("recovered")])
    reformat_fn = AsyncMock(return_value="rewritten input")
    res = ToolResilience(
        reformat_fn=reformat_fn,
        fallback_table=lambda *_a, **_k: (None, None),
        tool_executor=fx,
    )
    tr = await res.run(tool_id="web_search", raw_input="orig",
                       extra_context={})
    assert tr.success
    assert tr.output == "recovered"
    reformat_fn.assert_awaited_once()
    assert len(fx.calls) == 2


@pytest.mark.asyncio
async def test_reformat_unchanged_input_skips_retry() -> None:
    fx = _FakeExecutor([_format_fail()])
    reformat_fn = AsyncMock(return_value="orig")  # same as raw_input
    res = ToolResilience(
        reformat_fn=reformat_fn,
        fallback_table=lambda *_a, **_k: (None, None),
        tool_executor=fx,
    )
    tr = await res.run(tool_id="web_search", raw_input="orig",
                       extra_context={})
    assert not tr.success
    # Only one exec call (no retry because rewritten input == original).
    assert len(fx.calls) == 1


# ---------------------------------------------------------------------------
# run() — fallback chain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_taken_when_primary_persists() -> None:
    fx = _FakeExecutor([_empty(), _ok("from headless")])
    res = ToolResilience(
        reformat_fn=AsyncMock(return_value=None),
        fallback_table=lambda tid, inp: ("headless_browser", inp),
        tool_executor=fx,
    )
    tr = await res.run(tool_id="web_search", raw_input="orig",
                       extra_context={})
    assert tr.success
    assert tr.tool == "web_search→headless_browser"


@pytest.mark.asyncio
async def test_fallback_blocked_when_not_in_capabilities() -> None:
    fx = _FakeExecutor([_empty()])
    res = ToolResilience(
        reformat_fn=AsyncMock(return_value=None),
        fallback_table=lambda tid, inp: ("scraper_tool", inp),
        tool_executor=fx,
    )

    class _Ent:
        capabilities = {"tools": [{"tool_id": "web_search"}]}

    tr = await res.run(tool_id="web_search", raw_input="orig",
                       entity=_Ent(), extra_context={})
    # No fallback exec call; only the primary ran.
    assert len(fx.calls) == 1
    assert tr.output.startswith("[TOOL_EMPTY]")
    assert tr.success is False


# ---------------------------------------------------------------------------
# Final empty marker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_final_empty_marker_carries_failure_kind() -> None:
    fx = _FakeExecutor([_empty(), _empty()])
    res = ToolResilience(
        reformat_fn=AsyncMock(return_value="new input"),
        fallback_table=lambda *_a, **_k: (None, None),
        tool_executor=fx,
    )
    tr = await res.run(tool_id="web_search", raw_input="orig",
                       extra_context={})
    assert tr.output.startswith("[TOOL_EMPTY]")
    assert "EMPTY" in tr.output
    assert tr.success is False


# ---------------------------------------------------------------------------
# run_function_call() — REACT/AFC variant
# ---------------------------------------------------------------------------


class _FakeAfcExecutor:
    """Stub matching both execute_from_function_calls + execute_tools."""

    def __init__(
        self,
        afc_results: list[ToolResult],
        string_results: list[ToolResult] | None = None,
    ):
        self.afc_results = list(afc_results)
        self.string_results = list(string_results or [])
        self.afc_calls: list[dict] = []
        self.string_calls: list[dict] = []

    async def execute_from_function_calls(
        self, function_calls, extra_context=None, call_counts=None,
    ):
        self.afc_calls.append({"calls": function_calls, "ctx": extra_context})
        return [self.afc_results.pop(0)]

    async def execute_tools(self, payload, extra_context=None):
        self.string_calls.append({"payload": payload, "ctx": extra_context})
        return [self.string_results.pop(0)]


@pytest.mark.asyncio
async def test_run_function_call_passthrough_on_success() -> None:
    fx = _FakeAfcExecutor(afc_results=[_ok("hit")])
    res = ToolResilience(reformat_fn=AsyncMock(), tool_executor=fx)
    tr = await res.run_function_call(
        function_call={"name": "web_search", "args": {"input": "cats"}},
        extra_context={},
    )
    assert tr.success
    assert tr.output == "hit"
    assert len(fx.afc_calls) == 1
    assert fx.string_calls == []


@pytest.mark.asyncio
async def test_run_function_call_reformat_retry_on_format_fail() -> None:
    fx = _FakeAfcExecutor(
        afc_results=[_format_fail()],
        string_results=[_ok("recovered")],
    )
    reformat_fn = AsyncMock(return_value="rewritten")
    res = ToolResilience(
        reformat_fn=reformat_fn,
        fallback_table=lambda *_a, **_k: (None, None),
        tool_executor=fx,
    )
    tr = await res.run_function_call(
        function_call={"name": "web_search", "args": {"input": "orig"}},
        extra_context={},
    )
    assert tr.success
    assert tr.output == "recovered"
    reformat_fn.assert_awaited_once()
    # The retry uses the string-input path so execute_tools fires once.
    assert len(fx.string_calls) == 1


@pytest.mark.asyncio
async def test_run_function_call_fallback_taken_when_primary_persists() -> None:
    fx = _FakeAfcExecutor(
        afc_results=[_empty()],
        string_results=[_ok("from headless")],
    )
    res = ToolResilience(
        reformat_fn=AsyncMock(return_value=None),
        fallback_table=lambda tid, inp: ("headless_browser", inp),
        tool_executor=fx,
    )
    tr = await res.run_function_call(
        function_call={"name": "web_search", "args": {"input": "orig"}},
        extra_context={},
    )
    assert tr.success
    assert tr.tool == "web_search→headless_browser"
    assert len(fx.string_calls) == 1


@pytest.mark.asyncio
async def test_run_function_call_final_empty_after_exhaustion() -> None:
    fx = _FakeAfcExecutor(afc_results=[_empty()])
    res = ToolResilience(
        reformat_fn=AsyncMock(return_value=None),
        fallback_table=lambda *_a, **_k: (None, None),
        tool_executor=fx,
    )
    tr = await res.run_function_call(
        function_call={"name": "web_search", "args": {"input": "orig"}},
        extra_context={},
    )
    assert tr.output.startswith("[TOOL_EMPTY]")
    assert tr.success is False
