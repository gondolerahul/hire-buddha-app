"""tools.mcp — MCP-as-external-tool-protocol adapter (Phase 12 `07` §1)."""
from src.ai.tools.mcp.adapter import (
    MCPServerBinding,
    MCPToolAdapter,
    bind_mcp_server,
)
from src.ai.tools.mcp.client import MCPCallResult, MCPClient, MCPToolDescriptor

__all__ = [
    "MCPClient",
    "MCPToolDescriptor",
    "MCPCallResult",
    "MCPServerBinding",
    "MCPToolAdapter",
    "bind_mcp_server",
]
