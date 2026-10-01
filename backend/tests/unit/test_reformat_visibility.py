"""A reformat retry is visible beside the tool call it heals (P4.5, EP-24).

It was billed (an LLM call with ``reformat_retry`` usage rows) but nothing tied
it to the tool call: the call's log row and the trace showed no reformat.
"""
from __future__ import annotations

import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.ai.step_executor import StepExecutorService, log_tool_call
from src.ai.tool_executor import ToolResult
from src.ai.tools.resilience import ToolResilience


class _Exec:
    """First call fails with a format error; the reformatted call succeeds."""

    def __init__(self):
        self.calls = []

    async def execute_tools(self, payload, extra_context=None, **_kw):
        self.calls.append(payload[0]["input"])
        if len(self.calls) == 1:
            return [ToolResult(tool="t", args={}, output="Error: invalid json, expecting ','", success=False)]
        return [ToolResult(tool="t", args={}, output="ok", success=True)]


@pytest.mark.asyncio
async def test_a_result_from_reformatted_input_is_marked():
    res = ToolResilience(reformat_fn=AsyncMock(return_value='{"q": "fixed"}'),
                         fallback_table=lambda *_a: (None, None), tool_executor=_Exec())
    tr = await res.run(tool_id="t", raw_input="{q: broken")
    assert tr.success and tr.reformatted is True


@pytest.mark.asyncio
async def test_a_first_time_success_is_not_marked():
    ex = _Exec()
    ex.calls.append("warm")                      # skip the failing first call
    res = ToolResilience(reformat_fn=AsyncMock(), tool_executor=ex)
    tr = await res.run(tool_id="t", raw_input="x")
    assert tr.success and tr.reformatted is False


def test_the_log_row_says_reformatted():
    db = MagicMock()
    access = MagicMock()
    tr = ToolResult(tool="t", args={}, output="ok", success=True, reformatted=True)
    log_tool_call(db, uuid4(), "step", access, tr, {}, 3)
    assert db.add.call_args.args[0].log_metadata == {"reformatted": True}
    plain = ToolResult(tool="t", args={}, output="ok", success=True)
    log_tool_call(db, uuid4(), "step", access, plain, {}, 3)
    assert db.add.call_args.args[0].log_metadata is None


@pytest.mark.asyncio
async def test_the_reformat_call_has_its_own_span(monkeypatch):
    import src.ai.core.trace as trace_mod
    import src.ai.step_executor as se

    opened = []

    @contextlib.asynccontextmanager
    async def _span(kind, name=None, **payload):
        opened.append((kind, name))
        yield SimpleNamespace()

    class _Router:
        def __init__(self, **_kw):
            pass

        async def call_llm(self, **_kw):
            return SimpleNamespace(output='{"q": 1}', provider="p", model_name="m",
                                   prompt_tokens=1, completion_tokens=1, latency_ms=1)

    monkeypatch.setattr(trace_mod, "span", _span)
    monkeypatch.setattr(se, "LLMRouter", _Router)
    svc = StepExecutorService(db=MagicMock(), redis=None, company_id=uuid4(), usage_service=None)
    svc._log_usage = AsyncMock()
    run = SimpleNamespace(id=uuid4(), company_id=uuid4())
    entity = SimpleNamespace(company_id=uuid4())
    out = await svc._reformat_tool_input(run=run, entity=entity, tool_id="web_search",
                                         original_input="{q", error_message="bad json",
                                         step_description="search")
    assert out == '{"q": 1}'
    assert ("tool", "reformat:web_search") in opened
