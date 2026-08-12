"""
ai.planning.retry_strategies — Deterministic retry strategy picker.

Per Phase 11 Track 3, retry is the *Strategist's* job, not the critic's.
The critic returns a verdict + structured FailureTags; this module
maps those tags into one of seven retry strategies and provides a
helper to materialise the resulting follow-up move.

Reference: the critic pipeline design notes, §3.4.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from src.ai.core.agent_state import AgentState
from src.ai.planning.critic_pipeline import StepHealthRecord
from src.ai.planning.failure_tags import FailureTag

logger = logging.getLogger(__name__)

__all__ = [
    "RetryStrategy",
    "RetryDecision",
    "pick_retry",
    "RetryExecutor",
    "MAX_RETRIES_PER_STEP",
]


# Hard ceiling — the AgentLoop / Strategist refuse to retry the same
# step more than this number of times in one run. Track 9 will surface
# it as a config flag.
MAX_RETRIES_PER_STEP: int = 2


class RetryStrategy(str, Enum):
    NONE = "NONE"
    RETRY_AS_IS = "RETRY_AS_IS"
    RETRY_DIFFERENT_MODEL = "RETRY_DIFFERENT_MODEL"
    RETRY_DIFFERENT_PROMPT = "RETRY_DIFFERENT_PROMPT"
    RETRY_DIFFERENT_TOOL = "RETRY_DIFFERENT_TOOL"
    ASK_USER = "ASK_USER"
    ABANDON = "ABANDON"


@dataclass
class RetryDecision:
    strategy: RetryStrategy
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Picker — pure function, no LLM, no DB
# ---------------------------------------------------------------------------


def pick_retry(record: StepHealthRecord, state: AgentState) -> RetryDecision:
    """Map a StepHealthRecord + AgentState into a RetryStrategy.

    Pure function. Deterministic and fully unit-testable.
    """
    if record.post_critic_verdict in (None, "PASS"):
        return RetryDecision(strategy=RetryStrategy.NONE, reason="post verdict was PASS")

    tags: set[FailureTag] = set(record.post_critic_tags or [])
    pressure = state.budget.pressure

    # Highest-precedence escape hatches first.
    if pressure > 0.85:
        return RetryDecision(
            strategy=RetryStrategy.ABANDON,
            reason=f"budget pressure {pressure:.2f} > 0.85",
        )
    if FailureTag.POLICY_VIOLATION in tags:
        return RetryDecision(
            strategy=RetryStrategy.ABANDON, reason="policy violation tag",
        )
    if FailureTag.NEEDS_CLARIFICATION in tags:
        return RetryDecision(
            strategy=RetryStrategy.ASK_USER, reason="needs clarification",
        )
    if FailureTag.TOOL_FAILURE in tags:
        return RetryDecision(
            strategy=RetryStrategy.RETRY_DIFFERENT_TOOL, reason="tool failure tag",
        )
    if FailureTag.WRONG_FORMAT in tags:
        return RetryDecision(
            strategy=RetryStrategy.RETRY_DIFFERENT_PROMPT, reason="wrong format tag",
        )
    if FailureTag.OFF_TOPIC in tags or FailureTag.HALLUCINATION in tags:
        return RetryDecision(
            strategy=RetryStrategy.RETRY_DIFFERENT_MODEL,
            reason="off-topic or hallucination → escalate model",
        )
    if FailureTag.CONTRADICTION in tags:
        return RetryDecision(
            strategy=RetryStrategy.RETRY_DIFFERENT_MODEL, reason="contradiction",
        )
    if FailureTag.UNVERIFIABLE in tags:
        return RetryDecision(
            strategy=RetryStrategy.RETRY_DIFFERENT_PROMPT,
            reason="unverifiable — require sources in prompt",
        )
    if FailureTag.INCOMPLETE in tags and pressure < 0.5:
        return RetryDecision(
            strategy=RetryStrategy.RETRY_AS_IS,
            reason="incomplete and budget available",
        )

    # REJECT verdict with no actionable tag → ABANDON; REVISE with none → ABANDON too.
    return RetryDecision(
        strategy=RetryStrategy.ABANDON,
        reason="no actionable tag found; failing forward",
    )


# ---------------------------------------------------------------------------
# Materialiser
# ---------------------------------------------------------------------------


class RetryExecutor:
    """Translate a RetryDecision into a follow-up Move dict.

    Stored in ``state.retry_queue`` as a dict (rather than a Move
    object) so it is JSON-serialisable into the AgentState snapshot.
    The Strategist re-hydrates the dict back into a ``Move`` when it
    pops from the queue.
    """

    def build(
        self,
        decision: RetryDecision,
        original_move: Any,
        record: StepHealthRecord,
    ) -> Optional[dict[str, Any]]:
        if decision.strategy in (RetryStrategy.NONE, RetryStrategy.ABANDON):
            return None
        if decision.strategy == RetryStrategy.ASK_USER:
            return {
                "strategy": decision.strategy.value,
                "ask_user": True,
                "concerns": list(record.pre_critic_concerns)
                            + [t.value for t in record.post_critic_tags],
                "suggestion": record.post_critic_suggestion,
                "original_move_id": getattr(original_move, "move_id", ""),
            }
        # Common follow-up move scaffold.
        plan = list(getattr(original_move, "plan_fragment", None) or [])
        scaffold: dict[str, Any] = {
            "strategy": decision.strategy.value,
            "executor": getattr(original_move, "executor", "SingleStep"),
            "plan_fragment": plan,
            "rationale": f"retry via {decision.strategy.value}: {decision.reason}",
            "original_move_id": getattr(original_move, "move_id", ""),
            "retry_move_id": str(uuid4()),
            "metadata": dict(decision.metadata),
        }
        if decision.strategy == RetryStrategy.RETRY_DIFFERENT_MODEL:
            scaffold["force_model_escalation"] = True
        elif decision.strategy == RetryStrategy.RETRY_DIFFERENT_PROMPT:
            scaffold["prompt_rewrite_hint"] = record.post_critic_suggestion
        elif decision.strategy == RetryStrategy.RETRY_DIFFERENT_TOOL:
            scaffold["use_fallback_tool"] = True
        elif decision.strategy == RetryStrategy.RETRY_AS_IS:
            pass
        return scaffold

    @staticmethod
    def is_exhausted(
        state: AgentState, step_id: str, *, max_retries: int = MAX_RETRIES_PER_STEP,
    ) -> bool:
        """True when retries for ``step_id`` already exceeded the cap.

        Uses the rolling ``state.health_records`` window so it is
        compatible with snapshot/restore.
        """
        if not step_id:
            return False
        count = 0
        for r in getattr(state, "health_records", []) or []:
            if getattr(r, "step_id", "") == step_id and r.post_critic_verdict in (
                "REVISE",
                "REJECT",
            ):
                count += 1
        return count > max_retries
