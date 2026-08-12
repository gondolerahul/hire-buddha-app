"""
Base Tool classes and registry for HireBuddha AI Platform.

This module provides the abstract base class for tools and the global
registry for tool registration and lookup.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID
import json
import logging

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Tool lifecycle status
# ---------------------------------------------------------------------------

class ToolStatus(str, Enum):
    ACTIVE       = "ACTIVE"
    EXPERIMENTAL = "EXPERIMENTAL"
    DEPRECATED   = "DEPRECATED"
    # A freshly synthesized tool (Phase 12 `06` §2). Like EXPERIMENTAL it needs
    # an explicit per-company ``tools.experimental.{id}`` opt-in to be visible,
    # but it is ALSO never registered globally — only as a tenant tool for the
    # authoring company — and carries trust=low until a human promotes it.
    DRAFT        = "DRAFT"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed Tool Protocol
# ---------------------------------------------------------------------------

class ToolParams(BaseModel):
    """Base class for typed tool parameters.

    Subclass this in each tool to define strongly-typed inputs that
    replace the legacy string-JSON-string interface.
    """
    pass


class ToolResult(BaseModel):
    """Structured tool result with error handling.

    All tools should progressively migrate to returning ToolResult
    from run_typed() instead of raw strings from run().
    """
    success: bool = True
    output: str = ""
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = {}


class Tool(ABC):
    """Abstract base class for all AI tools.
    
    Subclasses must implement:
        - name: Human-readable tool name
        - description: Tool description for LLM context
        - run(): Async execution method
    
    Subclasses that need execution context (e.g. to look up API keys from the DB)
    should also override:
        - run_with_context(): Async method that receives extra_context dict
    """
    name: str
    description: str
    status: ToolStatus = ToolStatus.ACTIVE

    @abstractmethod
    async def run(self, input_data: str) -> str:
        """Execute the tool with the given input.
        
        Args:
            input_data: String input from the LLM
            
        Returns:
            String output to be returned to the LLM
        """
        pass

    async def run_with_context(self, input_data: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Execute the tool with extra execution context.

        Override this in tools that need access to context fields like
        'company_id' or 'user_id' (e.g. to look up API keys from the DB).

        Default implementation ignores context and delegates to run().

        Args:
            input_data: String (JSON) input from the LLM
            context: Optional dict containing extra_context keys such as
                     'company_id', 'user_id', and any injected args.

        Returns:
            String output to be returned to the LLM
        """
        return await self.run(input_data)

    async def run_typed(self, params: ToolParams) -> ToolResult:
        """New typed interface (Phase 6).

        Default implementation falls back to the legacy string interface.
        Override in subclasses for full type safety.
        """
        try:
            result_str = await self.run(json.dumps(params.model_dump()))
            return ToolResult(output=result_str)
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error_code="TOOL_ERROR",
                error_message=str(e),
            )

    def supports_context(self) -> bool:
        """Return True if this tool overrides run_with_context for special DB/key handling."""
        return type(self).run_with_context is not Tool.run_with_context
    
    def get_function_schema(self) -> Dict[str, Any]:
        """Return JSON schema for function calling.
        
        Override this method to provide custom parameter schemas.
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": "Input for the tool"
                    }
                },
                "required": ["input"]
            }
        }


class ToolRegistry:
    """Global and tenant-scoped registry for tool registration and lookup.
    
    Tools are registered at module import time and can be retrieved
    by name for execution by the AI engine.

    Phase 6: Added tenant-scoped tool registration so companies
    can have custom tools that don't leak across tenants.
    """
    _tools: Dict[str, Tool] = {}
    _tenant_tools: Dict[str, Dict[str, Tool]] = {}  # company_id -> {name: Tool}

    @classmethod
    def register(cls, tool: Tool) -> None:
        """Register a tool in the global registry."""
        cls._tools[tool.name] = tool

    @classmethod
    def register_tenant_tool(cls, company_id: UUID, tool: Tool) -> None:
        """Register a tool scoped to a specific company."""
        cid = str(company_id)
        if cid not in cls._tenant_tools:
            cls._tenant_tools[cid] = {}
        cls._tenant_tools[cid][tool.name] = tool
        logger.info(f"Registered tenant tool '{tool.name}' for company {cid}")

    @classmethod
    def get_tool(cls, name: str, company_id: Optional[UUID] = None) -> Optional[Tool]:
        """Get a tool by name. Tenant tools take priority over global."""
        if company_id:
            tenant = cls._tenant_tools.get(str(company_id), {})
            if name in tenant:
                return tenant[name]
        return cls._tools.get(name)

    @classmethod
    def get_tools_for_company(cls, company_id: UUID) -> Dict[str, Tool]:
        """Get merged dict of global + tenant-specific tools."""
        merged = dict(cls._tools)
        merged.update(cls._tenant_tools.get(str(company_id), {}))
        return merged

    @classmethod
    async def get_visible_tools_for_company(
        cls,
        company_id: UUID,
        *,
        feature_flags: Any = None,
        include_deprecated: bool = False,
    ) -> Dict[str, "Tool"]:
        """Phase 11 Track 8 — filter EXPERIMENTAL / DEPRECATED tools.

        EXPERIMENTAL tools require an explicit per-company feature flag
        ``tools.experimental.{tool_id}=true`` before they appear. DEPRECATED
        tools are hidden unless ``include_deprecated`` is True (admin path).
        """
        from src.ai.core.feature_flags import FeatureFlags as _FF
        flags = feature_flags or _FF()
        merged = cls.get_tools_for_company(company_id)
        out: Dict[str, "Tool"] = {}
        for name, tool in merged.items():
            status = getattr(tool, "status", ToolStatus.ACTIVE)
            if status == ToolStatus.DEPRECATED and not include_deprecated:
                continue
            if status in (ToolStatus.EXPERIMENTAL, ToolStatus.DRAFT):
                try:
                    enabled = await flags.is_on(
                        f"tools.experimental.{name}",
                        company_id=company_id,
                    )
                except Exception:                                           # pragma: no cover
                    enabled = False
                if not enabled:
                    try:
                        from src.ai.core.events import event
                        event(
                            "agent.tool.status_filtered",
                            tool_id=name,
                            company_id=str(company_id) if company_id else None,
                            reason="experimental_opt_in_required",
                        )
                    except Exception:                                       # pragma: no cover
                        pass
                    continue
            out[name] = tool
        return out

    @classmethod
    def list_tools(cls, company_id: Optional[UUID] = None) -> List[Dict[str, str]]:
        """List all registered tools with their descriptions."""
        tools = cls.get_tools_for_company(company_id) if company_id else cls._tools
        return [
            {"name": t.name, "description": t.description} 
            for t in tools.values()
        ]
    
    @classmethod
    def get_all_schemas(cls, company_id: Optional[UUID] = None) -> List[Dict[str, Any]]:
        """Get function schemas for all registered tools."""
        tools = cls.get_tools_for_company(company_id) if company_id else cls._tools
        return [t.get_function_schema() for t in tools.values()]
