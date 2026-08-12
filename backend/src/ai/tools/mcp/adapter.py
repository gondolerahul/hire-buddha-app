"""tools.mcp.adapter — wrap MCP server tools as first-class platform Tools.

Phase 12 `07` §1. Each MCP tool becomes an :class:`MCPToolAdapter` (a ``Tool``)
so entities invoke MCP-exposed connectors (Apollo, enrichment, ...) through the
normal tool path with the normal cost/attribution wrappers. Scope is bounded by
design:

  * **read-only first** — a tool the server hints is destructive (or not hinted
    read-only) is refused unless its name is in the binding's ``write_allow``
    list (HITL-curated). The default posture is list + invoke read-only tools.
  * **per-company allow-list** — only tools named in :class:`MCPServerBinding`'s
    ``tool_allow`` (empty = all the server lists) are bound, tenant-scoped.
  * **cost attribution `mcp`** — every call meters latency against the MCP SKU.

Binding registers the adapters as EXPERIMENTAL tenant tools, so they still need
the per-company ``tools.experimental.<name>`` opt-in to become visible.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

from src.ai.tools.base import Tool, ToolStatus
from src.ai.tools.mcp.client import MCPClient, MCPToolDescriptor

logger = logging.getLogger(__name__)

__all__ = ["MCPServerBinding", "MCPToolAdapter", "bind_mcp_server"]


def _qualified_name(server: str, tool: str) -> str:
    """Namespaced platform tool name so two servers can't collide."""
    return f"mcp__{server}__{tool}"


@dataclass
class MCPServerBinding:
    """Per-company configuration for binding one MCP server's tools."""

    server_name: str
    client: MCPClient
    tool_allow: List[str] = field(default_factory=list)   # empty = all listed
    write_allow: List[str] = field(default_factory=list)  # destructive tools permitted
    cost_per_call_usd: float = 0.0

    def permits(self, desc: MCPToolDescriptor) -> bool:
        if self.tool_allow and desc.name not in self.tool_allow:
            return False
        if (desc.destructive or not desc.read_only) and desc.name not in self.write_allow:
            return False
        return True


class MCPToolAdapter(Tool):
    """Adapts a single MCP tool to the platform ``Tool`` contract."""

    status = ToolStatus.EXPERIMENTAL

    def __init__(
        self,
        binding: MCPServerBinding,
        descriptor: MCPToolDescriptor,
    ) -> None:
        self._binding = binding
        self._descriptor = descriptor
        self.name = _qualified_name(binding.server_name, descriptor.name)
        self.description = (
            descriptor.description
            or f"MCP tool '{descriptor.name}' from server '{binding.server_name}'."
        )

    def get_function_schema(self) -> Dict[str, Any]:
        params = self._descriptor.input_schema or {
            "type": "object",
            "properties": {"input": {"type": "string"}},
        }
        return {"name": self.name, "description": self.description, "parameters": params}

    async def run(self, input_data: str) -> str:
        return await self._invoke(input_data, context=None)

    async def run_with_context(
        self, input_data: str, context: Optional[Dict[str, Any]] = None,
    ) -> str:
        return await self._invoke(input_data, context=context or {})

    async def _invoke(self, input_data: str, context: Optional[Dict[str, Any]]) -> str:
        try:
            arguments = json.loads(input_data) if input_data and input_data.strip() else {}
            if not isinstance(arguments, dict):
                arguments = {"input": arguments}
        except json.JSONDecodeError:
            arguments = {"input": input_data}

        started = time.monotonic()
        try:
            result = await self._binding.client.call_tool(self._descriptor.name, arguments)
        except Exception as exc:  # noqa: BLE001
            logger.warning("MCP call %s failed: %s", self.name, exc)
            return json.dumps({"error": f"MCP call failed: {type(exc).__name__}: {exc}"})
        latency_ms = int((time.monotonic() - started) * 1000)

        await self._meter(context, latency_ms)

        if result.is_error:
            return json.dumps({"error": result.text or "MCP tool reported an error"})
        return result.text

    async def _meter(self, context: Optional[Dict[str, Any]], latency_ms: int) -> None:
        if not context:
            return
        company_id = context.get("company_id")
        if not company_id or not self._binding.cost_per_call_usd:
            return
        try:
            from decimal import Decimal

            from src.ai.services.cost_attribution import CostAttribution, CostLedger
            from src.common.database import AsyncSessionLocal

            run_id = context.get("run_id")
            async with AsyncSessionLocal() as db:
                ledger = CostLedger(db)
                await ledger.add(
                    run_id=UUID(str(run_id)) if run_id else None,
                    company_id=UUID(str(company_id)),
                    amount=Decimal(str(self._binding.cost_per_call_usd)),
                    attribution=CostAttribution.MCP.value,
                    latency_ms=latency_ms,
                    log_metadata={"mcp_server": self._binding.server_name,
                                  "mcp_tool": self._descriptor.name},
                    commit=True,
                )
        except Exception:  # noqa: BLE001 - metering must never break a tool call
            logger.debug("MCP cost metering skipped", exc_info=True)


async def bind_mcp_server(
    company_id: UUID,
    binding: MCPServerBinding,
    *,
    register: bool = True,
) -> List[MCPToolAdapter]:
    """List a server's tools, filter by policy, and register the permitted ones.

    Returns the adapters created (also registered as EXPERIMENTAL tenant tools
    for ``company_id`` when ``register`` is True). Tools the binding does not
    permit (destructive without write_allow, or outside tool_allow) are skipped.
    """
    from src.ai.tools.base import ToolRegistry

    descriptors = await binding.client.list_tools()
    adapters: List[MCPToolAdapter] = []
    for desc in descriptors:
        if not binding.permits(desc):
            logger.info("MCP bind: skipping %s/%s (policy)", binding.server_name, desc.name)
            continue
        adapter = MCPToolAdapter(binding, desc)
        adapters.append(adapter)
        if register:
            ToolRegistry.register_tenant_tool(company_id, adapter)
    return adapters
