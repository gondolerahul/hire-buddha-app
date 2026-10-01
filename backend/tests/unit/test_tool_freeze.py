"""A registered tool keeps no per-call state (P3.6, TX-02).

One instance serves every run of every company at once. Registration freezes
it, so a tool that writes a company, credential or client to ``self`` fails at
the write instead of leaking into a concurrent run.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from src.ai.tools.base import Tool, ToolRegistry


class _Leaky(Tool):
    name = "p36_leaky"
    description = "writes per-call state to self"

    def __init__(self):
        self.configured = True  # set before registration: allowed

    async def run(self, input_data):
        self.last_company = input_data  # the bug TX-02 is about
        return "ok"


@pytest.mark.asyncio
async def test_a_registered_tool_cannot_keep_per_call_state():
    tool = _Leaky()
    ToolRegistry.register(tool)
    try:
        with pytest.raises(AttributeError, match="per-call state"):
            await tool.run("company-a")
        with pytest.raises(AttributeError):
            tool.configured = False
    finally:
        ToolRegistry._tools.pop(tool.name, None)


@pytest.mark.asyncio
async def test_a_tenant_tool_is_frozen_too():
    tool, company = _Leaky(), uuid4()
    ToolRegistry.register_tenant_tool(company, tool)
    try:
        with pytest.raises(AttributeError):
            await tool.run("x")
    finally:
        ToolRegistry._tenant_tools.pop(str(company), None)


@pytest.mark.asyncio
async def test_an_unregistered_instance_is_an_ordinary_object():
    tool = _Leaky()
    assert await tool.run("x") == "ok" and tool.last_company == "x"


def test_every_built_in_tool_is_frozen():
    import src.ai.tools  # noqa: F401 — registers the built-ins
    unfrozen = [n for n, t in ToolRegistry._tools.items() if not t.__dict__.get("_frozen")]
    assert unfrozen == []
