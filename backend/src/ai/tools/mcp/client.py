"""tools.mcp.client — transport-agnostic MCP client contract (Phase 12 `07` §1).

The platform's tool system is bespoke (``Tool`` + ``ToolRegistry``); MCP is the
emerging standard for external connectors. Rather than couple the adapter to one
transport (stdio / HTTP / SSE), it depends on this small :class:`MCPClient`
Protocol. A real client (e.g. the official MCP SDK) or a fake (tests) satisfies
it identically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol, runtime_checkable

__all__ = ["MCPToolDescriptor", "MCPCallResult", "MCPClient"]


@dataclass
class MCPToolDescriptor:
    """One tool exposed by an MCP server (mirrors the MCP ``tools/list`` shape)."""

    name: str
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)
    # MCP annotations: read-only hint, destructive hint, etc.
    annotations: Dict[str, Any] = field(default_factory=dict)

    @property
    def read_only(self) -> bool:
        """True when the server hints this tool does not mutate state."""
        return bool(self.annotations.get("readOnlyHint", False))

    @property
    def destructive(self) -> bool:
        return bool(self.annotations.get("destructiveHint", False))


@dataclass
class MCPCallResult:
    """Result of an MCP ``tools/call`` (text content + error flag)."""

    text: str = ""
    is_error: bool = False
    raw: Any = None


@runtime_checkable
class MCPClient(Protocol):
    """Minimal contract the adapter needs from any MCP transport."""

    async def list_tools(self) -> List[MCPToolDescriptor]:
        ...

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> MCPCallResult:
        ...
