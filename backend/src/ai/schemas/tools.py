"""schemas/tools.py — Tool registry management DTOs."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

__all__ = [
    "ToolRegistryEntryCreate",
    "ToolRegistryEntryUpdate",
    "ToolRegistryEntryResponse",
    "NetworkPolicy",
    "ToolSpec",
    "ToolExample",
]


class NetworkPolicy(str, Enum):
    """What network access a synthesized tool declares it needs.

    Enforced at execution by the per-tenant container (`02`): NONE runs with
    ``--network none``; ALLOWLIST is gated on the egress proxy (the remaining
    `02` S7 prod gate); FULL is never granted to synthesized tools in P12.
    """

    NONE = "none"
    ALLOWLIST = "allowlist"
    FULL = "full"


class ToolExample(BaseModel):
    """One input→expected-output example used to sandbox-test a synthesized tool."""

    input: str
    expected_contains: Optional[str] = None
    should_error: bool = False


class ToolSpec(BaseModel):
    """The typed contract for a to-be-synthesized tool (Phase 12 `06` §2.1).

    Produced by the Architect/Skill-Library need-detector; consumed by the
    ToolSmith (LLM writes a ``Tool`` subclass) and the ``ToolValidator`` (AST
    static analysis + red-team). A synthesized tool is constrained to the
    ``Tool`` base contract, this import allow-list, no filesystem access outside
    the sandbox workdir, and this network policy.
    """

    name: str = Field(..., pattern=r"^[a-z][a-z0-9_]{2,48}$")
    description: str
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_contract: str = ""
    examples: List[ToolExample] = Field(default_factory=list)
    allowed_imports: List[str] = Field(default_factory=list)
    network_policy: NetworkPolicy = NetworkPolicy.NONE
    est_cost_usd: float = 0.0


class ToolRegistryEntryCreate(BaseModel):
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    function_schema: Optional[Dict[str, Any]] = None
    is_enabled: bool = True
    configuration: Optional[Dict[str, Any]] = None


class ToolRegistryEntryUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    function_schema: Optional[Dict[str, Any]] = None
    is_enabled: Optional[bool] = None
    configuration: Optional[Dict[str, Any]] = None


class ToolRegistryEntryResponse(BaseModel):
    id: UUID
    company_id: Optional[UUID] = None
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    tool_type: str = "BUILT_IN"
    function_schema: Optional[Dict[str, Any]] = None
    is_enabled: bool = True
    configuration: Optional[Dict[str, Any]] = None
    created_by: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
