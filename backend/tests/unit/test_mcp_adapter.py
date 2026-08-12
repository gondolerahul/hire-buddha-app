"""MCP tool adapter — Phase 12 `07` §1.

Hermetic: a fake MCPClient stands in for any transport. Locks in the read-only-
first policy, the per-company allow-list, namespacing, and the Tool contract.
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest

from src.ai.tools.base import ToolRegistry, ToolStatus
from src.ai.tools.mcp import (
    MCPCallResult,
    MCPServerBinding,
    MCPToolAdapter,
    MCPToolDescriptor,
    bind_mcp_server,
)


class _FakeClient:
    def __init__(self, descriptors, result=None):
        self._descriptors = descriptors
        self._result = result or MCPCallResult(text='{"ok": true}')
        self.calls = []

    async def list_tools(self):
        return self._descriptors

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self._result


def _ro(name):
    return MCPToolDescriptor(name=name, description=f"{name} desc",
                             annotations={"readOnlyHint": True})


def _rw(name):
    return MCPToolDescriptor(name=name, annotations={"destructiveHint": True})


@pytest.mark.asyncio
async def test_read_only_tool_invokes_and_namespaces() -> None:
    client = _FakeClient([_ro("search")], MCPCallResult(text='{"hits": 3}'))
    binding = MCPServerBinding(server_name="apollo", client=client)
    adapters = await bind_mcp_server(uuid4(), binding, register=False)
    assert len(adapters) == 1
    assert adapters[0].name == "mcp__apollo__search"
    out = await adapters[0].run('{"q": "x"}')
    assert json.loads(out)["hits"] == 3
    assert client.calls == [("search", {"q": "x"})]


@pytest.mark.asyncio
async def test_destructive_tool_skipped_unless_allowed() -> None:
    client = _FakeClient([_rw("delete_account")])
    binding = MCPServerBinding(server_name="apollo", client=client)
    adapters = await bind_mcp_server(uuid4(), binding, register=False)
    assert adapters == []

    binding2 = MCPServerBinding(server_name="apollo", client=client,
                               write_allow=["delete_account"])
    adapters2 = await bind_mcp_server(uuid4(), binding2, register=False)
    assert len(adapters2) == 1


@pytest.mark.asyncio
async def test_tool_allow_list_filters() -> None:
    client = _FakeClient([_ro("a"), _ro("b"), _ro("c")])
    binding = MCPServerBinding(server_name="srv", client=client, tool_allow=["b"])
    adapters = await bind_mcp_server(uuid4(), binding, register=False)
    assert [a._descriptor.name for a in adapters] == ["b"]


@pytest.mark.asyncio
async def test_adapter_status_is_experimental_and_registers_tenant() -> None:
    company_id = uuid4()
    client = _FakeClient([_ro("search")])
    binding = MCPServerBinding(server_name="enrich", client=client)
    adapters = await bind_mcp_server(company_id, binding, register=True)
    assert adapters[0].status == ToolStatus.EXPERIMENTAL
    assert ToolRegistry.get_tool("mcp__enrich__search", company_id=company_id) is not None


@pytest.mark.asyncio
async def test_error_result_surfaces_as_error_json() -> None:
    client = _FakeClient([_ro("x")], MCPCallResult(text="boom", is_error=True))
    binding = MCPServerBinding(server_name="s", client=client)
    adapters = await bind_mcp_server(uuid4(), binding, register=False)
    out = await adapters[0].run("{}")
    assert "boom" in json.loads(out)["error"]


@pytest.mark.asyncio
async def test_call_failure_is_caught() -> None:
    class _Boom:
        async def list_tools(self):
            return [_ro("x")]

        async def call_tool(self, name, arguments):
            raise RuntimeError("transport down")

    binding = MCPServerBinding(server_name="s", client=_Boom())
    adapters = await bind_mcp_server(uuid4(), binding, register=False)
    out = await adapters[0].run("{}")
    assert "transport down" in json.loads(out)["error"]


def test_function_schema_uses_input_schema() -> None:
    desc = MCPToolDescriptor(name="q", input_schema={"type": "object",
                             "properties": {"query": {"type": "string"}}})
    binding = MCPServerBinding(server_name="s", client=_FakeClient([]))
    adapter = MCPToolAdapter(binding, desc)
    schema = adapter.get_function_schema()
    assert schema["parameters"]["properties"]["query"]["type"] == "string"
