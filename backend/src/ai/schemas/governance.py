"""schemas/governance.py — Governance, HITL checkpoints, execution limits."""
from __future__ import annotations

from typing import ClassVar, List, Optional

from pydantic import BaseModel

from src.ai.schemas.enums import HITLTriggerType

__all__ = [
    "ExecutionLimits",
    "HITLCheckpoint",
    "Governance",
]


class ExecutionLimits(BaseModel):
    max_recursion_depth: int = 5
    max_tool_calls: Optional[int] = None


class HITLCheckpoint(BaseModel):
    """A user-configured checkpoint that pauses execution for human approval."""
    trigger_type: HITLTriggerType
    step_ref: Optional[str] = None           # For BEFORE_STEP/AFTER_STEP: step name or step_id
    tool_ref: Optional[str] = None           # For TOOL_CALL: tool_id to gate
    threshold: Optional[float] = None        # For COST_THRESHOLD: USD amount that triggers pause
    expression: Optional[str] = None         # For CUSTOM: a Python-like boolean expression
    timeout_ms: int = 300000                 # How long to wait for approval (default 5 min)
    notification_channels: List[str] = []    # e.g. ["email", "slack", "dashboard"]
    message: Optional[str] = None            # Custom message shown to the reviewer
    auto_approve_on_timeout: bool = False    # If True, auto-approve when timeout expires


class Governance(BaseModel):
    max_cost_usd: Optional[float] = None
    timeout_ms: int = 60000
    max_recursion_depth: int = 5
    execution_limits: Optional[ExecutionLimits] = None
    hitl_checkpoints: List[HITLCheckpoint] = []

    # Critic-pipeline knobs the AgentLoop reads (agent_loop._critic_pipeline_for).
    # Defaults are the runtime's own fallbacks, so declaring them changes nothing
    # for entities that do not set them.
    critic_cost_share_pct: float = 0.20      # degrade critics above this share of run cost
    goal_validation_interval: int = 2        # alignment critic every N iterations
    meta_review_interval: int = 3            # supervisor meta-review every N iterations
    # Async child-run ceiling per parent (executors/child_entity.py); None = default.
    max_concurrent_children: Optional[int] = None

    # Sent by the entity builder; nothing reads it, so it is accepted and not stored.
    extra_accepted_keys: ClassVar[frozenset[str]] = frozenset({"checkpoint_every_n_steps"})
