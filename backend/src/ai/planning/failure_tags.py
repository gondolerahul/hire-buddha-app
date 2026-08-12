"""
ai.planning.failure_tags — Closed-enum failure tags emitted by critics.

Used by:
  - CriticPipeline (Track 3) — to tag StepHealthRecord
  - Strategist (Track 2) — to pick a retry strategy
  - IntelligenceTree (Tracks 5-7) — to mine recurring patterns
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

__all__ = ["FailureTag"]


class FailureTag(str, Enum):
    OFF_TOPIC = "OFF_TOPIC"
    HALLUCINATION = "HALLUCINATION"
    INCOMPLETE = "INCOMPLETE"
    WRONG_FORMAT = "WRONG_FORMAT"
    TOOL_FAILURE = "TOOL_FAILURE"
    CONTRADICTION = "CONTRADICTION"
    UNVERIFIABLE = "UNVERIFIABLE"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    UNDER_BUDGET = "UNDER_BUDGET"
    OVER_BUDGET = "OVER_BUDGET"
    BLOCKED_DEPENDENCY = "BLOCKED_DEPENDENCY"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"

    @classmethod
    def from_string(cls, s: Optional[str]) -> Optional["FailureTag"]:
        """Tolerant parser used when an LLM emits a tag from text."""
        if not s:
            return None
        key = s.strip().upper().replace(" ", "_").replace("-", "_")
        return cls.__members__.get(key)

    @property
    def severity(self) -> int:
        """0 (informational) .. 3 (critical). Drives retry strategy."""
        return _SEVERITY[self]


_SEVERITY: dict["FailureTag", int] = {
    FailureTag.OFF_TOPIC:            2,
    FailureTag.HALLUCINATION:        3,
    FailureTag.INCOMPLETE:           1,
    FailureTag.WRONG_FORMAT:         1,
    FailureTag.TOOL_FAILURE:         2,
    FailureTag.CONTRADICTION:        2,
    FailureTag.UNVERIFIABLE:         2,
    FailureTag.POLICY_VIOLATION:     3,
    FailureTag.UNDER_BUDGET:         0,
    FailureTag.OVER_BUDGET:          2,
    FailureTag.BLOCKED_DEPENDENCY:   1,
    FailureTag.NEEDS_CLARIFICATION:  1,
}
