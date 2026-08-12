"""schemas/execution.py — Execution-run DTOs and supporting log shapes."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator

from src.ai.schemas.entity import HierarchicalEntityResponse
from src.ai.schemas.enums import RunStatus

__all__ = [
    "ExecutionRunCreate",
    "ExecutionRefineRequest",
    "CSATRequest",
    "LLMInteractionLogResponse",
    "ToolInteractionLogResponse",
    "HumanApprovalResponse",
    "ExecutionRunSummary",
    "ExecutionRunResponse",
]


class ExecutionRunCreate(BaseModel):
    entity_id: UUID
    input_data: Dict[str, Any]


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


class ExecutionRunSummary(BaseModel):
    id: UUID
    entity_id: UUID
    parent_run_id: Optional[UUID]
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


ExecutionRunResponse.model_rebuild()
