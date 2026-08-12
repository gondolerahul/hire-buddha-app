"""
ai.planning.step_health_record — One record per executed step.

Extracted from :mod:`ai.planning.critic_pipeline` (Phase 11 Track 4)
so the pipeline module stays under the kernel layout-lint cap. The
record carries every critic stage's verdict + cost for one iteration
of the AgentLoop.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Literal, Optional
from uuid import uuid4

from src.ai.planning.failure_tags import FailureTag

__all__ = ["StepHealthRecord"]


@dataclass
class StepHealthRecord:
    """One record per executed step, written by all four critic stages."""

    record_id: str = field(default_factory=lambda: str(uuid4()))
    step_id: str = ""
    iteration: int = 0
    move_id: str = ""

    pre_critic_verdict: Optional[Literal["PASS", "BLOCK", "REVISE"]] = None
    pre_critic_concerns: list[str] = field(default_factory=list)
    pre_critic_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))

    post_critic_verdict: Optional[Literal["PASS", "REVISE", "REJECT"]] = None
    post_critic_tags: list[FailureTag] = field(default_factory=list)
    post_critic_suggestion: str = ""
    post_critic_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    post_critic_model: str = ""

    alignment_aligned: Optional[bool] = None
    alignment_drift: Optional[float] = None
    alignment_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))

    supervisor_recommendation: Optional[
        Literal["CONTINUE", "REPLAN", "ABORT", "PAUSE"]
    ] = None
    supervisor_reasoning: str = ""
    supervisor_confidence: float = 0.5
    supervisor_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))

    total_latency_ms: int = 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def to_json(self) -> str:
        d = asdict(self)
        d["post_critic_tags"] = [t.value for t in self.post_critic_tags]
        return json.dumps(d, default=str)

    @classmethod
    def from_json(cls, payload: str) -> "StepHealthRecord":
        raw = json.loads(payload)
        tags_raw = raw.pop("post_critic_tags", []) or []
        rec = cls(**raw)
        normalised: list[FailureTag] = []
        for t in tags_raw:
            if isinstance(t, FailureTag):
                normalised.append(t)
                continue
            if isinstance(t, str) and t in FailureTag.__members__:
                normalised.append(FailureTag(t))
                continue
            parsed = FailureTag.from_string(t)
            if parsed is not None:
                normalised.append(parsed)
        rec.post_critic_tags = normalised
        return rec

    def is_actionable_failure(self) -> bool:
        """True when downstream retry logic should kick in."""
        return self.post_critic_verdict in {"REVISE", "REJECT"}
