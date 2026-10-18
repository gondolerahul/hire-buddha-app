"""
Base Tool classes and registry for HireBuddha AI Platform.

This module provides the abstract base class for tools and the global
registry for tool registration and lookup.
"""

from abc import ABC
from enum import Enum
from typing import Any, ClassVar, Dict, List, Optional, Type
from uuid import UUID
import json
import logging

from pydantic import BaseModel, ConfigDict, Field, ValidationError


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
# The tool contract (TL-41, TL-30, TX-I2)
# ---------------------------------------------------------------------------

class ToolParams(BaseModel):
    """Base of a tool's ``Params`` model: its arguments, typed.

    An argument the model is not told about is an error, not ignored: the
    model hears which one, and the advertised schema is the model's.
    """
    model_config = ConfigDict(extra="forbid")


class ToolOutput(BaseModel):
    """What a tool returns from ``execute``.

    ``output`` is what the model reads (text, or a JSON-able object). A failed
    call says so here (``success=False`` with ``error``) rather than in a
    string the executor has to recognise.
    """
    success: bool = True
    output: Any = ""
    error: Optional[str] = None
    error_code: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def failed(cls, error: str, code: str = "tool_error", **metadata: Any) -> "ToolOutput":
        return cls(success=False, output=f"Error: {error}", error=error, error_code=code, metadata=metadata)

    def text(self) -> str:
        """The output as the string a legacy caller expects."""
        if not self.success:
            return self.output if isinstance(self.output, str) and self.output else f"Error: {self.error}"
        return self.output if isinstance(self.output, str) else json.dumps(self.output, default=str)


class InvalidArguments(ValueError):
    """The call's arguments do not fit the tool's ``Params``."""


class Tool(ABC):
    """Base class of every tool.

    **The contract.** A tool declares ``Params`` (a ``ToolParams`` model) and
    implements ``execute(params, ctx)``; its function schema is derived from
    ``Params``. The executor calls ``invoke`` — the one entry point — for a
    model's call and a plan step alike. ``ctx`` is the server-minted execution
    context (``ExecutionContext.as_tool_context``, P3.2): the company, run and
    entity a call is for come from it, never from ``params``.

    A tool not yet converted (``Params is None``, decision D16) implements
    ``run_with_context(input: str, context)`` and a hand-written
    ``get_function_schema``; ``invoke`` adapts it in one place.
    """
    name: str
    description: str
    status: ToolStatus = ToolStatus.ACTIVE
    Params: ClassVar[Optional[Type[ToolParams]]] = None
    # The field a plan step's plain-text input fills, for a typed tool whose
    # step templates are text (``calculator``'s "17*23").
    string_field: ClassVar[Optional[str]] = None
    # Where the tool is listed; ``tool_category`` derives it from the tool's
    # subpackage unless the tool refines it here (TL-35).
    category: ClassVar[Optional[str]] = None
    # How long one call may run before the executor fails it (EP-08); a grant's
    # ``timeout_seconds`` overrides it. Tools that render or wait on slow
    # providers declare more.
    timeout_seconds: ClassVar[int] = 120

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

    # ── The typed contract ─────────────────────────────────────────────────
    async def execute(self, params: Any, ctx: Dict[str, Any]) -> ToolOutput:
        """Run the call. A typed tool overrides this."""
        raise NotImplementedError(f"tool '{self.name}' declares Params but does not implement execute")

    def parse_args(self, args: Any) -> ToolParams:
        """``args`` (a dict, a JSON object string, or a plan step's text) as ``Params``."""
        assert self.Params is not None
        if isinstance(args, str):
            text = args.strip()
            parsed: Any = None
            if text.startswith("{"):
                try:
                    parsed = json.loads(text)
                except ValueError:
                    parsed = None
            if isinstance(parsed, dict):
                args = parsed
            elif self.string_field:
                args = {self.string_field: args}
            else:
                raise InvalidArguments(f"expected a JSON object with {self._field_list()}")
        if not isinstance(args, dict):
            raise InvalidArguments(f"expected an object with {self._field_list()}")
        try:
            return self.Params.model_validate(args)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}" for e in exc.errors()
            )
            raise InvalidArguments(f"{problems}. Expected {self._field_list()}") from None

    def _field_list(self) -> str:
        assert self.Params is not None
        fields = self.Params.model_fields
        required = [f for f, info in fields.items() if info.is_required()]
        optional = [f for f in fields if f not in required]
        return f"required {required}" + (f", optional {optional}" if optional else "")

    async def invoke(self, args: Any, context: Optional[Dict[str, Any]] = None) -> ToolOutput:
        """The one entry point: validate, then run (TL-41).

        Arguments that do not fit are a failed call naming the fields — never
        a silent fallback to another path.
        """
        if self.Params is None:
            return ToolOutput(output=await self.run_with_context(_legacy_input(args), context))
        try:
            params = self.parse_args(args)
        except InvalidArguments as exc:
            return ToolOutput.failed(f"{self.name}: invalid arguments — {exc}", code="invalid_arguments")
        return await self.execute(params, dict(context or {}))

    # ── The adapter for tools not yet converted (D16) ──────────────────────
    async def run(self, input_data: str) -> str:
        """A call without a context (legacy callers)."""
        return await self.run_with_context(input_data, None)

    async def run_with_context(self, input_data: str, context: Optional[Dict[str, Any]] = None) -> str:
        """A string call. An unconverted tool overrides this (or ``run``); for a
        typed tool it goes through ``invoke``."""
        if self.Params is not None:
            return (await self.invoke(input_data, context)).text()
        if type(self).run is not Tool.run:
            return await self.run(input_data)
        raise NotImplementedError(f"tool '{self.name}' implements neither execute nor run_with_context")

    def get_function_schema(self) -> Dict[str, Any]:
        """The function declaration the model is shown: from ``Params`` when typed."""
        if self.Params is not None:
            schema = _plain_schema(self.Params.model_json_schema())
            schema.setdefault("properties", {})
            return {"name": self.name, "description": self.description, "parameters": schema}
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {"input": {"type": "string", "description": "Input for the tool"}},
                "required": ["input"],
            },
        }


# A tool's category is its subpackage's (TL-35): a hand-written map covered 22
# of 98 tools and listed the rest as "general".
_PACKAGE_CATEGORIES = {
    "core": "core", "documents": "document", "email": "email", "media": "media",
    "social": "social", "crm": "crm", "sandbox": "execution", "meta": "meta",
    "automation": "automation",
}


def tool_category(tool: "Tool") -> str:
    """The tool's ``category``, else its subpackage's under ``src.ai.tools``."""
    if tool.category:
        return tool.category
    parts = type(tool).__module__.split(".")
    package = parts[3] if parts[:3] == ["src", "ai", "tools"] and len(parts) > 4 else ""
    return _PACKAGE_CATEGORIES.get(package, "general")


def _plain_schema(schema: Dict[str, Any], defs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A Pydantic JSON schema in the subset every provider reads.

    ``Optional[X]`` (``anyOf: [X, null]``) becomes ``X``, ``$ref``s are inlined
    and titles dropped: the Gemini adapter rebuilds each property from its
    ``type``, and an ``anyOf`` with no ``type`` would be advertised as a string.
    """
    defs = schema.get("$defs", {}) if defs is None else defs
    if "$ref" in schema:
        target = defs.get(schema["$ref"].rsplit("/", 1)[-1], {})
        schema = {**target, **{k: v for k, v in schema.items() if k != "$ref"}}
    if "anyOf" in schema:
        variants = [v for v in schema["anyOf"] if v.get("type") != "null"]
        if len(variants) == 1:
            schema = {**{k: v for k, v in schema.items() if k != "anyOf"}, **variants[0]}
    out: Dict[str, Any] = {}
    for key, value in schema.items():
        if key in ("title", "$defs"):
            continue
        if key == "properties" and isinstance(value, dict):
            out[key] = {name: _plain_schema(prop, defs) for name, prop in value.items()}
        elif key == "items" and isinstance(value, dict):
            out[key] = _plain_schema(value, defs)
        elif key == "anyOf" and isinstance(value, list):
            out[key] = [_plain_schema(v, defs) for v in value]
        else:
            out[key] = value
    return out


def _legacy_input(args: Any) -> str:
    """The string an unconverted tool parses: the plan's text, ``args["input"]``,
    or the model's arguments as a JSON object."""
    if isinstance(args, str):
        return args
    if isinstance(args, dict):
        if "input" in args:
            value = args["input"]
            return value if isinstance(value, str) else json.dumps(value, default=str)
        # Who a call is for comes from the context, never from the arguments.
        return json.dumps({k: v for k, v in args.items() if k not in ("company_id", "user_id")}, default=str)
    return "" if args is None else str(args)


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
