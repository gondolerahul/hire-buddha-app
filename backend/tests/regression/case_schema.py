"""
tests/regression/case_schema.py — Pydantic schema for regression cases.

A regression case is the unit of nightly testing for the agent kernel.
Each YAML file under ``cases/`` declares:

  * what to run (fixture + input)
  * what to expect (status, cost band, must / must-not mentions)
  * how to grade ambiguous output (LLM-judge threshold)

The schema is validated at load time so a malformed case fails fast in
CI rather than during the nightly run.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

__all__ = [
    "AcceptanceConfig",
    "RegressionCase",
]


class AcceptanceConfig(BaseModel):
    llm_judge_threshold: float = Field(
        0.7,
        description="LLM-judge confidence required to pass (0..1).",
    )
    output_min_chars: Optional[int] = None
    output_max_chars: Optional[int] = None
    judge_rubric: Optional[str] = Field(
        None,
        description="Custom rubric passed to the LLM judge (overrides default).",
    )


class RegressionCase(BaseModel):
    case_id: str
    entity_fixture: str
    input: dict = Field(default_factory=dict)
    expected_status: str = "COMPLETED"

    child_fixtures: dict = Field(
        default_factory=dict,
        description="For PROCESS cases: maps a CHILD_ENTITY_INVOCATION step's "
                    "``target.entity_name_hint`` to the child entity fixture to "
                    "seed. The seeded child's id is wired into the parent plan "
                    "step's ``target.entity_id`` so child resolution is "
                    "deterministic (Strategy 1) and isolated per run.",
    )

    expected_min_cost_usd: Optional[float] = None
    expected_max_cost_usd: Optional[float] = None

    expected_must_mention: List[str] = Field(default_factory=list)
    expected_must_not_mention: List[str] = Field(default_factory=list)

    track_min: int = Field(
        0,
        description="The earliest Phase 11 Track at which this case is "
                    "expected to pass. Cases needing AgentLoop are >= 2.",
    )
    tags: List[str] = Field(default_factory=list)
    timeout_seconds: int = 600

    acceptance: AcceptanceConfig = Field(default_factory=AcceptanceConfig)

    @model_validator(mode="after")
    def _validate_cost_bounds(self) -> "RegressionCase":
        lo = self.expected_min_cost_usd
        hi = self.expected_max_cost_usd
        if lo is not None and hi is not None and lo > hi:
            raise ValueError(
                f"{self.case_id}: expected_min_cost_usd ({lo}) > "
                f"expected_max_cost_usd ({hi})"
            )
        return self
