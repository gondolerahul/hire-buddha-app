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


def _has_fallback(tool_id: str) -> bool:
    from src.ai.tool_fallback import TOOL_FALLBACK_CHAINS
    return bool((TOOL_FALLBACK_CHAINS.get(tool_id) or {}).get("alternatives"))


class RetryExecutor:
    """Translate a RetryDecision into a follow-up Move dict.

    Stored in ``state.retry_queue`` as a dict (rather than a Move
    object) so it is JSON-serialisable into the AgentState snapshot.
    The loop re-hydrates the dict back into a ``Move`` when it pops
    from the queue.

    The remedy is a ``directive`` written onto the copy of each step the
    retry dispatches (PC-06): it travels with the step through any
    executor and the step executor honours it. Before, the remedy was set
    on the queued dict, dropped by the rehydration, and every strategy ran
    as ``RETRY_AS_IS``.
    """

    def build(
        self,
        decision: RetryDecision,
        original_move: Any,
        record: StepHealthRecord,
    ) -> Optional[dict[str, Any]]:
        if decision.strategy in (RetryStrategy.NONE, RetryStrategy.ABANDON):
            return None
        plan = [dict(s) for s in (getattr(original_move, "plan_fragment", None) or []) if isinstance(s, dict)]
        if not plan:
            return None  # nothing concrete to run again
        applied = decision.strategy
        steps = []
        for step in plan:
            directive, used = self._directive(decision.strategy, step, record)
            if used is not decision.strategy:
                applied = used
            steps.append({**step, "directive": directive})
        return {
            "strategy": applied.value,
            "picked": decision.strategy.value,
            "executor": getattr(original_move, "executor", "SingleStep"),
            "plan_fragment": steps,
            "rationale": f"retry via {applied.value}: {decision.reason}",
            "original_move_id": getattr(original_move, "move_id", ""),
            "retry_move_id": str(uuid4()),
            "metadata": dict(decision.metadata),
        }

    @staticmethod
    def _directive(strategy: RetryStrategy, step: dict[str, Any],
                   record: StepHealthRecord) -> tuple[dict[str, Any], RetryStrategy]:
        """The step's directive for ``strategy``, and the strategy it really
        applies: a remedy that does not exist for this step falls back to a
        prompt rewrite naming the failure."""
        suggestion = record.post_critic_suggestion or ""
        concerns = "; ".join(list(record.pre_critic_concerns)
                             + [t.value for t in record.post_critic_tags])
        if strategy is RetryStrategy.RETRY_DIFFERENT_TOOL:
            target = step.get("target") if isinstance(step.get("target"), dict) else {}
            tool_id = str((target or {}).get("tool_id") or "")
            is_tool_step = str(step.get("type", "")).upper() == "TOOL_CALL"
            if is_tool_step and tool_id and _has_fallback(tool_id):
                return {"strategy": strategy.value, "use_fallback_tool": True}, strategy
            hint = "A tool call failed last time; use a different tool or approach."
            return ({"strategy": RetryStrategy.RETRY_DIFFERENT_PROMPT.value,
                     "prompt_hint": f"{hint} {suggestion}".strip()},
                    RetryStrategy.RETRY_DIFFERENT_PROMPT)
        if strategy is RetryStrategy.RETRY_DIFFERENT_MODEL:
            return {"strategy": strategy.value, "escalate_model": True,
                    "prompt_hint": suggestion or None}, strategy
        if strategy is RetryStrategy.RETRY_DIFFERENT_PROMPT:
            return {"strategy": strategy.value,
                    "prompt_hint": suggestion or f"The last attempt was judged: {concerns}"}, strategy
        if strategy is RetryStrategy.ASK_USER:
            question = suggestion or concerns or "The step needs clarification before it can run again."
            return {"strategy": strategy.value, "ask_user": question}, strategy
        return {"strategy": strategy.value}, strategy

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
