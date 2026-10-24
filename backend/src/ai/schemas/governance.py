"""schemas/governance.py — Governance, HITL checkpoints, execution limits."""
from __future__ import annotations

from decimal import Decimal

from typing import Any, ClassVar, Collection, List, Optional

from pydantic import BaseModel, Field, ValidationError, model_validator

from src.ai.schemas.enums import HITLTriggerType
from src.ai.schemas.hitl_expression import ExpressionError, parse

__all__ = [
    "ExecutionLimits",
    "HITLCheckpoint",
    "Governance",
    "checkpoint_problem",
]


class ExecutionLimits(BaseModel):
    max_tool_calls: Optional[int] = None

    # The old spelling of Governance.max_recursion_depth — the one the entity
    # builder edited. Accepted, and folded into the one setting by Governance.
    extra_accepted_keys: ClassVar[frozenset[str]] = frozenset({"max_recursion_depth"})


class HITLCheckpoint(BaseModel):
    """A user-configured checkpoint that pauses execution for human approval."""
    trigger_type: HITLTriggerType
    step_ref: Optional[str] = None           # For BEFORE_STEP/AFTER_STEP: step name or step_id
    tool_ref: Optional[str] = None           # For TOOL_CALL: tool_id to gate
    threshold: Optional[float] = None        # For COST_THRESHOLD: USD amount that triggers pause
    expression: Optional[str] = None         # For CUSTOM: see schemas/hitl_expression.py (GH-10)
    timeout_ms: int = 300000                 # How long to wait for approval (default 5 min)
    notification_channels: List[str] = []    # e.g. ["email", "slack", "dashboard"]
    message: Optional[str] = None            # Custom message shown to the reviewer
    auto_approve_on_timeout: bool = False    # If True, auto-approve when timeout expires


def checkpoint_problem(raw: Any, step_refs: Optional[Collection[str]] = None) -> Optional[str]:
    """Why a checkpoint cannot work, or ``None`` (GH-09).

    A checkpoint that does not parse, lacks the field its trigger needs, has a
    ``CUSTOM`` expression outside the grammar, or names a step the plan does
    not have (when ``step_refs`` — the plan's step names and ids — is given)
    would never fire. The entity API refuses it (422); at run time one stored
    before that asks a person instead (``GovernanceService.evaluate_hitl``).
    """
    try:
        cp = HITLCheckpoint.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", ())) or "checkpoint"
        return f"{where}: {first.get('msg', 'invalid')}"
    kind = cp.trigger_type
    if cp.timeout_ms <= 0:
        return "timeout_ms must be positive"
    if kind in (HITLTriggerType.BEFORE_STEP, HITLTriggerType.AFTER_STEP):
        if not (cp.step_ref or "").strip():
            return f"{kind.value} needs step_ref, the step's name or id"
        if step_refs is not None and cp.step_ref not in step_refs:
            return f"step_ref {cp.step_ref!r} is not a step of the plan"
    elif kind is HITLTriggerType.TOOL_CALL:
        if not (cp.tool_ref or "").strip():
            return "TOOL_CALL needs tool_ref, the tool's id"
    elif kind is HITLTriggerType.COST_THRESHOLD:
        if cp.threshold is None or cp.threshold <= 0:
            return "COST_THRESHOLD needs a threshold above 0 (USD)"
    elif kind is HITLTriggerType.CUSTOM:
        try:
            parse(cp.expression or "")
        except ExpressionError as exc:
            return f"expression {cp.expression!r}: {exc}"
    return None


class MaxBill(BaseModel):
    """What one run may be billed, in the company's currency (Phase 15 T5-7, K-19)."""
    amount: Decimal = Field(..., ge=0, decimal_places=4)
    currency: Optional[str] = Field(None, min_length=3, max_length=3)


class Governance(BaseModel):
    # The cap's raw-cost equivalent: derived from ``max_bill`` when the agent is
    # saved (``src.billing.agent_budget``); set on its own only by older agents.
    max_cost_usd: Optional[float] = None
    max_bill: Optional[MaxBill] = None
    timeout_ms: int = 60000
    # How deep the tree below this entity may go: a child run past it is refused
    # (EP-06). One setting; ``execution_limits.max_recursion_depth`` is folded
    # into it (EP-28).
    max_recursion_depth: int = 5
    execution_limits: Optional[ExecutionLimits] = None
    hitl_checkpoints: List[HITLCheckpoint] = []

    @model_validator(mode="before")
    @classmethod
    def _fold_recursion_limit(cls, data: Any) -> Any:
        """``execution_limits.max_recursion_depth`` — the spelling the builder
        sent — becomes ``max_recursion_depth``. When both are sent, it wins:
        it is the one a person set (the other was the schema default)."""
        if not isinstance(data, dict):
            return data
        limits = data.get("execution_limits")
        if isinstance(limits, dict) and "max_recursion_depth" in limits:
            limits = dict(limits)
            folded = limits.pop("max_recursion_depth")
            data = {**data, "execution_limits": limits}
            if folded is not None:
                data["max_recursion_depth"] = folded
        return data

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
