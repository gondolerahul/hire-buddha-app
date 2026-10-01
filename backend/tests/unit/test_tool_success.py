"""TL-52 and TL-51 — a tool call's success comes from its result.

TL-52: tools report failure in their result (``{"error": …}``, ``"Error: …"``)
and the executor only set ``success=False`` when the call raised, so failed
calls were logged and billed as successes. TL-51: the resilience classifier
failed a *succeeding* call whose text mentioned "no results" or "timed out",
then re-ran it — a second email, post or CRM write for a write tool.
"""
from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.ai.tool_executor import ToolExecutor, ToolResult, result_error
from src.ai.tools import ToolRegistry
from src.ai.tools.resilience import (
    READS_DESPITE_NAME,
    WRITE_TOOLS,
    FailureKind,
    ToolResilience,
    classify_tool_failure,
    is_write_tool,
)


# ── TL-52: the result's own error envelope ──────────────────────────────────


@pytest.mark.parametrize("output", [
    {"error": "PDF generation failed: weasyprint missing"},
    {"success": False, "message": "quota exceeded"},
    '{"error": "PDF generation failed"}',
    "Error: invalid input",
    "Error calculating: division by zero",
    "[ERROR] upstream refused",
])
def test_an_error_envelope_is_an_error(output):
    assert result_error(output)


@pytest.mark.parametrize("output", [
    "The request timed out twice before the vendor fixed it; no results were lost.",
    '{"error": null, "results": [1, 2]}',
    {"status": "success", "data": "ok"},
    "Errors in the report were fixed.",
    "",
    None,
])
def test_ordinary_output_is_not_an_error(output):
    assert result_error(output) is None


class _ReturnsError:
    name = "pdf_generator"

    async def run_with_context(self, _input, context=None):  # noqa: ARG002
        return '{"error": "PDF generation failed: weasyprint missing"}'


@pytest.mark.asyncio
async def test_a_tool_that_returns_an_error_is_a_failed_call(monkeypatch):
    monkeypatch.setattr(ToolRegistry, "get_tool", staticmethod(lambda _name: _ReturnsError()))

    [via_string] = await ToolExecutor.execute_tools([{"tool": "pdf_generator", "input": "x"}])
    [via_call] = await ToolExecutor.execute_from_function_calls(
        [{"name": "pdf_generator", "args": {"input": "x"}}])
    for tr in (via_string, via_call):
        assert tr.success is False
        assert "weasyprint" in tr.error


# ── TL-51: content is not a failure; a write is never repeated ──────────────


@pytest.mark.parametrize("text", [
    "Search summary: no results older than 2020; the API timed out once in 2019.",
    "Email body: the build failed with 'No such file or directory' last week.",
])
def test_a_succeeding_call_that_mentions_failure_words_is_not_a_failure(text):
    tr = ToolResult(tool="web_search", args={}, output=text, success=True)
    assert classify_tool_failure(tr) is FailureKind.NONE


def test_a_failed_call_is_still_classified():
    tr = ToolResult(tool="web_search", args={}, output="request timed out", success=False)
    assert classify_tool_failure(tr) is FailureKind.TIMEOUT


class _Executor:
    def __init__(self, result: ToolResult):
        self.result = result
        self.calls: list = []

    async def execute_tools(self, calls, extra_context=None):  # noqa: ARG002
        self.calls.append(calls)
        return [self.result]

    async def execute_from_function_calls(self, calls, extra_context=None, call_counts=None):  # noqa: ARG002
        self.calls.append(calls)
        return [self.result]


def _failed_send() -> ToolResult:
    return ToolResult(tool="email_send", args={}, output="Error: SMTP said 451 try again",
                      success=False, error="SMTP said 451 try again")


@pytest.mark.asyncio
async def test_a_failed_write_is_not_retried_or_replaced():
    exec_ = _Executor(_failed_send())
    reformat = AsyncMock(return_value="reformatted")
    fallback = MagicMock(return_value=("whatsapp_send_tenant", "x"))
    res = ToolResilience(reformat_fn=reformat, fallback_table=fallback, tool_executor=exec_)

    tr = await res.run(tool_id="email_send", raw_input="send it")
    assert len(exec_.calls) == 1
    reformat.assert_not_awaited()
    fallback.assert_not_called()
    assert tr.success is False and tr.output.startswith("Error: SMTP")

    tr = await res.run_function_call(function_call={"name": "email_send", "args": {"input": "x"}})
    assert len(exec_.calls) == 2
    reformat.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_failed_read_keeps_its_last_output_in_the_marker():
    exec_ = _Executor(ToolResult(tool="web_search", args={}, output="Error: quota exceeded",
                                 success=False))
    res = ToolResilience(reformat_fn=AsyncMock(return_value=None),
                         fallback_table=lambda *_a: (None, None), tool_executor=exec_)
    tr = await res.run(tool_id="web_search", raw_input="q")
    assert tr.output.startswith("[TOOL_EMPTY]")
    assert "quota exceeded" in tr.output


_WRITE_WORDS = re.compile(r"(send|post|publish|upload|create|manage|save|update|write|draft|"
                          r"classify|delete|creator|executor|synthesis|reflect)")


def test_every_tool_that_reads_like_a_write_is_classified():
    names = {t["name"] for t in ToolRegistry.list_tools()}
    unclassified = sorted(n for n in names if _WRITE_WORDS.search(n)
                          and n not in WRITE_TOOLS and n not in READS_DESPITE_NAME)
    assert unclassified == [], f"add to resilience.WRITE_TOOLS or READS_DESPITE_NAME: {unclassified}"
    assert is_write_tool("email_send") and is_write_tool("web_search→email_send")
    assert not is_write_tool("web_search")


# ── the TOOL_CALL step: a failed call fails the step and is not billed ──────


@pytest.mark.asyncio
async def test_a_tool_call_step_whose_tool_failed_is_failed_and_not_billed(monkeypatch):
    from src.ai.schemas import PlanStep, StepType
    from src.ai.step_executor import StepExecutorService

    async def _execute_tools(calls, extra_context=None):  # noqa: ARG001
        return [ToolResult(tool=calls[0]["tool"], args={}, output='{"error": "weasyprint missing"}',
                           success=True)]

    monkeypatch.setattr(ToolExecutor, "execute_tools", staticmethod(_execute_tools))
    svc = StepExecutorService(db=MagicMock(commit=AsyncMock()), redis=AsyncMock(), company_id=uuid4(),
                              usage_service=MagicMock(), cortex_bridge=MagicMock())
    svc._charge_tool = AsyncMock()
    svc._reformat_tool_input = AsyncMock(return_value=None)
    run = SimpleNamespace(id=uuid4(), company_id=uuid4(), user_id=None)
    entity = SimpleNamespace(id=uuid4(), capabilities={"tools": [{"tool_id": "pdf_generator"}]})
    step = PlanStep(step_id="s1", name="make_pdf", type=StepType.TOOL_CALL,
                    target={"tool_id": "pdf_generator", "prompt_template": "# Report"})

    result = await svc._execute_tool_call(run, entity, step, {})
    assert "weasyprint" in result["error"]
    svc._charge_tool.assert_not_awaited()
