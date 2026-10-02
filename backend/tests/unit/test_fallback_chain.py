"""The fallback chain walks past a failed fallback, and never loops (P8.7 —
EP-23).

``get_fallback_tool`` returned the first alternative and the ladder tried
that one hop: ``web_search`` → ``headless_browser``, and if the browser failed
too the step got ``[TOOL_EMPTY]``. Now the ladder walks the table — each
fallback's own fallback next — up to three hops, never trying a tool twice
(the pairs are reciprocal: ``scraper_tool`` ↔ ``headless_browser``).
"""
from __future__ import annotations

import pytest

from src.ai.tool_executor import ToolResult


def test_the_chain_follows_the_table_and_stops_at_a_tool_already_tried():
    from src.ai.tool_fallback import fallback_chain
    chain = [tool for tool, _input in fallback_chain("web_search", '{"query": "tides"}')]
    assert chain == ["headless_browser", "scraper_tool"]          # not back to headless_browser
    assert fallback_chain("calculator", "1+1") == []


@pytest.mark.asyncio
async def test_the_ladder_tries_the_second_fallback_when_the_first_fails():
    from src.ai.tools.resilience import ToolResilience

    tried: list[str] = []

    class _Executor:
        @staticmethod
        async def execute_tools(calls, extra_context=None, *, access, via="plan"):
            [call] = calls
            tried.append(call["tool"])
            if call["tool"] == "scraper_tool":
                return [ToolResult(tool="scraper_tool", args={}, output="Tide tables for June …", success=True)]
            return [ToolResult(tool=call["tool"], args={}, output="", success=False, error="blocked")]

    ladder = ToolResilience(reformat_fn=None, tool_executor=_Executor, access=object())
    result = await ladder.run(tool_id="web_search", raw_input='{"query": "tides"}', extra_context={})

    assert tried == ["web_search", "headless_browser", "scraper_tool"]
    assert result.success and result.tool == "web_search→scraper_tool"
