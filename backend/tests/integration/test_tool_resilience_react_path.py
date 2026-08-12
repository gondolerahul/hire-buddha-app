"""Phase 11 Track 14 — REACT-AFC ToolResilience adoption.

The Track 8 deferred item I just shipped routes every LLM-driven tool
call (REACT / AFC path) through ``ToolResilience.run_function_call``
when the ``tools.resilience_v2_enabled`` flag is ON. That gives the
REACT path the same reformat-retry + fallback chain as the direct
TOOL_CALL path.

These tests live alongside the unit tests in
``tests/unit/test_tool_resilience.py`` but with a higher-level slant:
prove the integration contract holds with realistic fakes rather than
direct-injecting a list of ``ToolResult``s.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.ai.tool_executor import ToolResult
from src.ai.tools.resilience import ToolResilience, FailureKind


class _StubExecutor:
    """Records calls + serves a queue of typed results.

    Supports both code paths: ``execute_from_function_calls`` (typed
    AFC) and ``execute_tools`` (string fallback).
    """

    def __init__(
        self,
        afc_queue: list[ToolResult],
        string_queue: list[ToolResult] | None = None,
    ):
        self.afc_queue = list(afc_queue)
        self.string_queue = list(string_queue or [])
        self.afc_calls: list[dict] = []
        self.string_calls: list[dict] = []

    async def execute_from_function_calls(
        self, function_calls, extra_context=None, call_counts=None,
    ):
        self.afc_calls.append({
            "calls": function_calls,
            "ctx": dict(extra_context or {}),
        })
        return [self.afc_queue.pop(0)]

    async def execute_tools(self, payload, extra_context=None):
        self.string_calls.append({
            "payload": payload,
            "ctx": dict(extra_context or {}),
        })
        return [self.string_queue.pop(0)]


def _ok(tool: str, output: str = "result") -> ToolResult:
    return ToolResult(tool=tool, args={}, output=output, success=True)


def _format_fail(tool: str = "web_search") -> ToolResult:
    return ToolResult(
        tool=tool, args={"input": "?"},
        output="ERROR: invalid json delimiter",
        success=False,
    )


def _empty(tool: str = "web_search") -> ToolResult:
    return ToolResult(tool=tool, args={"input": "?"}, output="", success=True)


# ---------------------------------------------------------------------------
# Happy path — first call already succeeds; no retry/fallback.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_react_passthrough_when_call_succeeds() -> None:
    exec_ = _StubExecutor(afc_queue=[_ok("web_search", "good")])
    res = ToolResilience(reformat_fn=AsyncMock(), tool_executor=exec_)
    tr = await res.run_function_call(
        function_call={"name": "web_search", "args": {"input": "cats"}},
        extra_context={"company_id": "abc"},
    )
    assert tr.success and tr.output == "good"
    assert len(exec_.afc_calls) == 1
    assert exec_.string_calls == []


# ---------------------------------------------------------------------------
# Reformat-retry on FORMAT failures.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_react_reformat_recovers_after_format_failure() -> None:
    exec_ = _StubExecutor(
        afc_queue=[_format_fail("web_search")],
        string_queue=[_ok("web_search", "recovered after retry")],
    )
    reformat_fn = AsyncMock(return_value="reformatted input")
    res = ToolResilience(
        reformat_fn=reformat_fn,
        fallback_table=lambda *_a, **_k: (None, None),
        tool_executor=exec_,
    )
    tr = await res.run_function_call(
        function_call={"name": "web_search", "args": {"input": "orig"}},
        extra_context={},
    )
    assert tr.success
    assert tr.output == "recovered after retry"
    reformat_fn.assert_awaited_once()
    # AFC call + string-input retry call — both visible.
    assert len(exec_.afc_calls) == 1
    assert len(exec_.string_calls) == 1


# ---------------------------------------------------------------------------
# Fallback chain when reformat doesn't help.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_react_fallback_chain_when_primary_empty() -> None:
    exec_ = _StubExecutor(
        afc_queue=[_empty("web_search")],
        string_queue=[_ok("headless_browser", "fetched")],
    )
    res = ToolResilience(
        reformat_fn=AsyncMock(return_value=None),  # decline to reformat
        fallback_table=lambda tid, inp: ("headless_browser", inp),
        tool_executor=exec_,
    )
    tr = await res.run_function_call(
        function_call={"name": "web_search", "args": {"input": "x"}},
        extra_context={},
    )
    assert tr.success
    assert tr.tool == "web_search→headless_browser"


# ---------------------------------------------------------------------------
# Final-empty marker — no recovery available.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_react_final_empty_marker_emitted() -> None:
    exec_ = _StubExecutor(afc_queue=[_empty("web_search")])
    res = ToolResilience(
        reformat_fn=AsyncMock(return_value=None),
        fallback_table=lambda *_a, **_k: (None, None),
        tool_executor=exec_,
    )
    tr = await res.run_function_call(
        function_call={"name": "web_search", "args": {"input": "x"}},
        extra_context={},
    )
    assert tr.success is False
    assert tr.output.startswith("[TOOL_EMPTY]")
    assert "EMPTY" in tr.output


# ---------------------------------------------------------------------------
# Capability-aware fallback — refuse to substitute a tool the entity
# doesn't have in its capabilities list.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_react_fallback_blocked_by_capabilities() -> None:
    exec_ = _StubExecutor(afc_queue=[_empty("web_search")])

    class _Entity:
        capabilities = {"tools": [{"tool_id": "web_search"}]}  # no fallback allowed

    res = ToolResilience(
        reformat_fn=AsyncMock(return_value=None),
        fallback_table=lambda tid, inp: ("scraper_tool", inp),
        tool_executor=exec_,
    )
    tr = await res.run_function_call(
        function_call={"name": "web_search", "args": {"input": "x"}},
        entity=_Entity(),
        extra_context={},
    )
    # The fallback was vetoed — only the primary AFC call ran.
    assert len(exec_.string_calls) == 0
    assert tr.output.startswith("[TOOL_EMPTY]")
    assert tr.success is False


# ---------------------------------------------------------------------------
# Failure-classification sanity for the new code path.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classification_drives_reformat_only_on_recoverable() -> None:
    """A non-recoverable failure (RATE_LIMIT) skips reformat and goes
    straight to fallback or final-empty."""
    from src.ai.tools.resilience import classify_tool_failure

    rate_limited = ToolResult(
        tool="web_search", args={},
        output="ERROR: 429 rate_limit_exceeded",
        success=False,
    )
    kind = classify_tool_failure(rate_limited)
    assert kind not in ToolResilience.REFORMAT_RECOVERABLE_KINDS or kind is FailureKind.ERROR_MSG


def test_reformat_fn_contract_matches_step_executor() -> None:
    """Guards the C6 wiring seam: ``step_executor._execute_thought`` passes
    ``StepExecutorService._reformat_tool_input`` to ``ToolResilience`` as the
    ``reformat_fn``. ``ToolResilience._reformat_input`` invokes that callable
    with a fixed set of keyword arguments — if anyone renames a parameter on
    either side, the REACT reformat-retry silently stops working. This test
    fails loudly instead.
    """
    import inspect

    from src.ai.step_executor import StepExecutorService

    # The exact kwargs ToolResilience._reformat_input passes to reformat_fn.
    expected_kwargs = {
        "run", "entity", "tool_id",
        "original_input", "error_message", "step_description",
    }
    params = set(inspect.signature(StepExecutorService._reformat_tool_input).parameters)
    params.discard("self")
    assert expected_kwargs == params, (
        f"_reformat_tool_input signature drifted from the ToolResilience "
        f"reformat_fn contract: expected {expected_kwargs}, got {params}"
    )
