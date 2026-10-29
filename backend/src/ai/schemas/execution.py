"""schemas/execution.py — Execution-run DTOs and supporting log shapes."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.ai.schemas.entity import HierarchicalEntityResponse
from src.ai.schemas.enums import RunStatus

__all__ = [
    "RESERVED_INPUT_KEYS",
    "reserved_input_keys",
    "ExecutionRunCreate",
    "ExecutionRefineRequest",
    "CSATRequest",
    "LLMInteractionLogResponse",
    "ToolInteractionLogResponse",
    "HumanApprovalResponse",
    "ApprovalDecision",
    "ExecutionRunSummary",
    "ExecutionRunResponse",
]


# Keys a caller may not put in ``input_data``: the platform reads them as
# control, not as task input — attach to a CORTEX tree, override a feature
# flag, claim an identity or a runtime. Any ``__``-prefixed key is reserved too.
# Retry, refine and child runs write such keys themselves; they build their rows
# directly, not through ``ExecutionRunCreate`` (TL-53).
RESERVED_INPUT_KEYS: frozenset[str] = frozenset({
    "feature_flags", "cortex_tree_id", "subtree_root_id",
    "company_id", "user_id", "run_id", "agent_id", "entity_id",
    "container_runtime", "persistent_browser",
})


def reserved_input_keys(input_data: Dict[str, Any]) -> List[str]:
    """The keys of ``input_data`` only the platform may set."""
    return sorted(str(k) for k in input_data if str(k).startswith("__") or k in RESERVED_INPUT_KEYS)


class ExecutionRunCreate(BaseModel):
    entity_id: UUID
    input_data: Dict[str, Any]

    @field_validator("input_data")
    @classmethod
    def _no_platform_keys(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        reserved = reserved_input_keys(value)
        if reserved:
            raise ValueError(f"input_data may not set platform keys: {', '.join(reserved)}")
        return value


class CSATRequest(BaseModel):
    """A +1/-1 CSAT rating on a completed run (Phase 12 `07` §6, P-O2)."""
    score: int  # +1 = thumbs up, -1 = thumbs down
    comment: Optional[str] = None


class ExecutionRefineRequest(BaseModel):
    """Request to refine a completed execution run with user feedback.

    The system uses an LLM to auto-detect which pipeline steps need
    re-execution based on the feedback. Unchanged steps reuse cached outputs.
    """
    feedback: str  # Natural language description of desired changes


class LLMInteractionLogResponse(BaseModel):
    id: UUID
    model_provider: str
    model_name: str
    input_prompt: str
    output_response: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: Optional[int]
    cost_usd: float = 0.0
    reasoning_mode: Optional[str] = None
    step_name: Optional[str] = None
    log_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ToolInteractionLogResponse(BaseModel):
    id: UUID
    tool_id: str
    tool_name: str
    step_name: Optional[str] = None
    provider: Optional[str] = None
    input_parameters: Optional[Dict[str, Any]] = None
    output_result: Optional[Any] = None
    success: bool
    error_message: Optional[str] = None
    latency_ms: Optional[int] = None
    log_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class HumanApprovalResponse(BaseModel):
    id: UUID
    checkpoint_trigger: str
    status: str
    requested_by: Optional[str] = None
    context_snapshot: Optional[Dict[str, Any]] = None
    reviewer_notes: Optional[str] = None
    requested_at: datetime
    responded_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ApprovalDecision(BaseModel):
    """A reviewer's answer to a pending HITL approval."""
    model_config = ConfigDict(extra="forbid")

    status: Literal["APPROVED", "REJECTED"]
    notes: Optional[str] = Field(default=None, max_length=4000)


class ExecutionRunSummary(BaseModel):
    id: UUID
    entity_id: UUID
    parent_run_id: Optional[UUID]
    retry_of_run_id: Optional[UUID] = None  # the run this one retries or refines (EP-03)
    entity_version_id: Optional[UUID] = None  # the entity version this run executes (EP-10)
    depth: int = 0                          # parents above this run (EP-06)
    max_depth: Optional[int] = None         # the deepest a descendant may go
    company_id: UUID
    status: RunStatus
    error_message: Optional[str]
    total_cost_usd: float = 0.0
    billed_amount: Optional[float] = None  # TB formula result — user-facing charge
    total_tokens: int = 0
    execution_time_ms: Optional[int] = None
    csat_score: Optional[int] = None
    csat_comment: Optional[str] = None
    trace_id: Optional[UUID] = None
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    entity: Optional[HierarchicalEntityResponse] = None

    class Config:
        from_attributes = True

    @field_validator("total_cost_usd", mode="before")
    @classmethod
    def parse_total_cost_usd(cls, v):
        if v is None:
            return 0.0
        return v

    @field_validator("billed_amount", mode="before")
    @classmethod
    def parse_billed_amount(cls, v):
        if v is None:
            return None
        return float(v)

    @field_validator("total_tokens", mode="before")
    @classmethod
    def parse_total_tokens(cls, v):
        if v is None:
            return 0
        return v


class ExecutionRunResponse(ExecutionRunSummary):
    input_data: Optional[Dict[str, Any]]
    dynamic_plan: Optional[Dict[str, Any]]
    result_data: Optional[Dict[str, Any]]
    context_state: Optional[Dict[str, Any]]
    llm_logs: List[LLMInteractionLogResponse] = []
    tool_logs: List[ToolInteractionLogResponse] = []
    human_approvals: List[HumanApprovalResponse] = []
    child_runs: List["ExecutionRunResponse"] = []
    # Set for HireBuddha staff without the business's support access: what the
    # run read through its connections is withheld (SH-E6, auth.support_access).
    content_withheld: Optional[Dict[str, Any]] = None


ExecutionRunResponse.model_rebuild()
