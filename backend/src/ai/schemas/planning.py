"""schemas/planning.py — Static plans, plan steps, dynamic planning.

Track 1 typed-enum upgrade: ``PlanStep.type`` is now ``StepType`` (was
``Optional[str]``). The model accepts any case-insensitive string the
upstream LLM emits and raises ``ValueError`` for unknown values.
"""
from __future__ import annotations

import json as _json
import logging
import re as _re
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator

from src.ai.schemas.enums import StepType
from src.ai.schemas.prompts import DEFAULT_PLANNING_SYSTEM_PROMPT

__all__ = [
    "PlanStepTarget",
    "PlanStep",
    "StaticPlan",
    "AllowedDeviations",
    "DynamicPlanning",
    "ConvergenceCriterion",
    "LoopControl",
    "Planning",
    "ExitCondition",
]


class ExitCondition(BaseModel):
    condition: str
    next_step: Any  # Integer | 'END' | 'ESCALATE'


class PlanStepTarget(BaseModel):
    entity_id: Optional[UUID] = None
    tool_id: Optional[str] = None
    prompt_template: Optional[str] = None
    input_dependencies: List[str] = []  # Explicit step output dependencies (e.g., ["step_1", "step_2"])
    # When entity_id is a name string rather than a UUID, it's captured here for DB lookup.
    entity_name_hint: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def capture_entity_name_hint(cls, data):
        """Run before ALL field validation. If entity_id is a name string (not a UUID),
        copy it into entity_name_hint so Strategy 3 in step_executor can resolve it by
        name lookup. This fires in every Pydantic code path — direct construction,
        model_validate(), and nested parsing."""
        if not isinstance(data, dict):
            return data
        raw_eid = data.get("entity_id")
        if raw_eid is not None:
            is_uuid = _re.match(
                r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
                str(raw_eid),
            )
            if not is_uuid and not data.get("entity_name_hint"):
                logging.getLogger(__name__).warning(
                    f"[PlanStepTarget] entity_id '{raw_eid}' is not a valid UUID — "
                    f"storing as entity_name_hint for name-based resolution."
                )
                data = {**data, "entity_name_hint": str(raw_eid), "entity_id": None}
        return data

    @field_validator("prompt_template", mode="before")
    @classmethod
    def coerce_prompt_template(cls, v):
        """LLM planners sometimes emit prompt_template as a dict/list instead of a string.
        Auto-convert to a JSON string so downstream variable resolution still works."""
        if isinstance(v, (dict, list)):
            return _json.dumps(v, default=str)
        return v


class PlanStep(BaseModel):
    step_id: Optional[str] = None  # Accept string IDs from frontend
    order: int = 0
    name: str = ""
    description: Optional[str] = None
    type: StepType = StepType.ACTION
    target: Optional[PlanStepTarget] = None
    required: bool = True
    exit_conditions: List[ExitCondition] = []
    # Per-step reasoning selection (D-3 / C13). The Strategist reads this to
    # choose an executor (e.g. DEBATE) and the step executor reads it to pick a
    # reasoning mode (REACT / CHAIN_OF_THOUGHT). It supersedes the deprecated
    # entity-level ``reasoning_config.reasoning_mode``.
    reasoning_hint: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _legacy_reasoning_mode_to_hint(cls, data: Any) -> Any:
        """Map a legacy per-step ``reasoning_mode`` onto ``reasoning_hint`` so
        authored plans that still carry a step-level mode keep steering
        reasoning per step."""
        if isinstance(data, dict) and not data.get("reasoning_hint") and data.get("reasoning_mode"):
            data = {**data, "reasoning_hint": data.get("reasoning_mode")}
        return data

    @field_validator("type", mode="before")
    @classmethod
    def _coerce_type(cls, v):
        """LLM planners emit ``"tool_call"`` / ``"TOOL_CALL"`` / etc.
        Accept any case; ``None`` defaults to ACTION; raise for unknown values.
        """
        if v is None:
            return StepType.ACTION
        if isinstance(v, StepType):
            return v
        if isinstance(v, str):
            key = v.strip().upper()
            try:
                return StepType[key]
            except KeyError as exc:
                raise ValueError(
                    f"Unknown step type: {v!r}. "
                    f"Valid: {[s.value for s in StepType]}"
                ) from exc
        raise ValueError(
            f"PlanStep.type must be str or StepType, got {type(v).__name__}"
        )


class StaticPlan(BaseModel):
    enabled: bool = True
    steps: List[PlanStep] = []
    # How the dynamic planner (PlanGenerator) treats these authored steps:
    #   ADAPTIVE (default) — the static plan competes as a first-class
    #       "authored" candidate alongside the LLM-generated candidates; the
    #       judge may pick it, augment it, or prefer a generated plan.
    #   STRICT — binding: the chosen plan MUST cover every authored step
    #       (enforced by the authored_steps_covered invariant). Use for
    #       compliance / deterministic workflows. If no generated candidate
    #       covers them, the authored plan is used verbatim.
    #   DYNAMIC_ONLY — ignore the static plan entirely; do not seed it as a
    #       candidate.
    fallback_behavior: str = "ADAPTIVE"  # STRICT | ADAPTIVE | DYNAMIC_ONLY


class AllowedDeviations(BaseModel):
    can_add_steps: bool = True
    can_skip_optional_steps: bool = True
    can_reorder_steps: bool = False
    can_change_tools: bool = False


class DynamicPlanning(BaseModel):
    enabled: bool = False
    planning_prompt: Optional[str] = None  # Additional planning instructions (appended)
    planning_system_prompt: str = DEFAULT_PLANNING_SYSTEM_PROMPT  # Base planning prompt (overridable)
    constraints: List[str] = []
    reconciliation_strategy: str = "HYBRID"  # STATIC_PRIORITY | DYNAMIC_PRIORITY | HYBRID
    allowed_deviations: AllowedDeviations = AllowedDeviations()


class ConvergenceCriterion(BaseModel):
    metric: str
    threshold: float
    operator: str  # GT | LT | EQ | GTE | LTE


class LoopControl(BaseModel):
    max_iterations: Optional[int] = 1
    convergence_criteria: List[ConvergenceCriterion] = []
    iteration_context_mode: str = "FULL_HISTORY"  # FULL_HISTORY | SUMMARIZED | LAST_N
    summary_every_n_iterations: Optional[int] = None


class Planning(BaseModel):
    static_plan: StaticPlan = StaticPlan()
    dynamic_planning: DynamicPlanning = DynamicPlanning()
    loop_control: LoopControl = LoopControl()
