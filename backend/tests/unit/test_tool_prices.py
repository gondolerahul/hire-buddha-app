"""Every tool is priced, or says why it is free (GH-05).

A tool with no price resolved to $0 and warned once per process: shipping a
tool without its price made it free, permanently and quietly. Now each
registered tool must have a price — a registry SKU (``TOOL_SKU_MAP``) or a
fixed cost (``TOOL_FIXED_COST``) — or be in ``FREE_TOOLS`` with a reason. A
call to one that is none of these is recorded at $0 with an event, every time
(tests/integration/test_tool_metering.py).
"""
from __future__ import annotations

import src.ai.tools  # noqa: F401  (registers every tool)
from src.ai.governance.tool_cost_resolver import FREE_TOOLS, TOOL_FIXED_COST, TOOL_SKU_MAP
from src.ai.tools.base import ToolRegistry

PRICED = set(TOOL_SKU_MAP) | set(TOOL_FIXED_COST)


def test_every_registered_tool_is_priced_or_says_why_it_is_free():
    unpriced = sorted(set(ToolRegistry._tools) - PRICED - set(FREE_TOOLS))
    assert not unpriced, f"tools with no price — add one, or a FREE_TOOLS reason: {unpriced}"


def test_the_tables_name_only_tools_that_exist_and_none_twice():
    registered = set(ToolRegistry._tools)
    assert set(FREE_TOOLS) <= registered, sorted(set(FREE_TOOLS) - registered)
    assert not PRICED & set(FREE_TOOLS), sorted(PRICED & set(FREE_TOOLS))
    assert all(reason.strip() for reason in FREE_TOOLS.values())
