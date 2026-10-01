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


NO_CONTEXT_ERROR = (
    "this tool runs only inside a run or a session: it was called without an "
    "execution context, so it has no company"
)


def context_company_id(context: Optional[Dict[str, Any]]) -> Optional[str]:
    """The call's company, from the platform-built execution context only.

    A tool never takes its tenant from its own parameters — the model writes
    those (TL-03). Without a context there is no company, and the tool refuses
    the call (``NO_CONTEXT_ERROR``) rather than guess one.
    """
    cid = (context or {}).get("company_id")
    return str(cid) if cid else None


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

    # One registered instance serves every run of every company at once, so a
    # tool must keep nothing per call on ``self`` (TX-02). Registration freezes
    # the instance: an attribute write after it raises, at the moment of the
    # mistake, instead of leaking one run's company or credential into another.
    def __setattr__(self, name: str, value: Any) -> None:
        if self.__dict__.get("_frozen"):
            raise AttributeError(
                f"tool '{getattr(self, 'name', type(self).__name__)}' is shared by every run "
                f"and may not keep per-call state: set '{name}' in a local or read it from "
                "the execution context (TX-02)"
            )
        super().__setattr__(name, value)

    def freeze(self) -> None:
        """Make the instance read-only (done by ``ToolRegistry`` on registration)."""
        object.__setattr__(self, "_frozen", True)

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

    Execution and advertisement never look tools up here directly: they go
    through ``ai.governance.tool_access.ToolAccess``, which applies the entity's grants,
    the admin kill switch and the status opt-in (P3.1).
    """
    _tools: Dict[str, Tool] = {}
    _tenant_tools: Dict[str, Dict[str, Tool]] = {}  # company_id -> {name: Tool}

    @classmethod
    def register(cls, tool: Tool) -> None:
        """Register a tool in the global registry (and freeze it, TX-02)."""
        tool.freeze()
        cls._tools[tool.name] = tool

    @classmethod
    def register_tenant_tool(cls, company_id: UUID, tool: Tool) -> None:
        """Register a tool scoped to a specific company."""
        tool.freeze()
        cid = str(company_id)
        if cid not in cls._tenant_tools:
            cls._tenant_tools[cid] = {}
        cls._tenant_tools[cid][tool.name] = tool
        logger.debug(f"Registered tenant tool '{tool.name}' for company {cid}")

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
    def list_tools(cls, company_id: Optional[UUID] = None) -> List[Dict[str, str]]:
        """List all registered tools with their descriptions."""
        tools = cls.get_tools_for_company(company_id) if company_id else cls._tools
        return [
            {"name": t.name, "description": t.description} 
            for t in tools.values()
        ]
