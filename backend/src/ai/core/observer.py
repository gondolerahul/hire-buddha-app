"""
ai.core.observer — Parse ActionResult into a typed Observation (Track 2).

Deterministic v1. Track 4+ will swap in richer heuristics (LLM-graded
novelty, goal-delta from intelligence rules, etc.).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from src.ai.core.agent_state import AgentState, Observation

if TYPE_CHECKING:
    from src.ai.core.executors.base import ActionResult


__all__ = ["CRITIC_OUTPUT_TOKENS", "Observer", "bounded_output"]

# How much of a step's output a critic reads (PC-27). Executors already bound
# their output at 8000 characters, so in practice a critic sees all of it.
CRITIC_OUTPUT_TOKENS = 2000
_CHARS_PER_TOKEN = 4


def bounded_output(text: str, max_tokens: int = CRITIC_OUTPUT_TOKENS) -> str:
    """``text`` within a token budget, saying so when the system cut it.

    The critics once judged the 160-character timeline summary and called
    every longer answer ``INCOMPLETE`` (PC-27); a cut they cannot see looks
    like the step's own fault, so a cut is always marked.
    """
    limit = max_tokens * _CHARS_PER_TOKEN
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n[… {len(text) - limit} more characters cut by the system, not by the step]"


class Observer:
    """Deterministic observer. No external deps."""

    def parse(self, action_result: "ActionResult", state: AgentState) -> Observation:
        outcome = self._outcome(action_result)
        return Observation(
            iteration=state.iteration,
            outcome=cast(Any, outcome),
            novelty_score=self._novelty(action_result),
            goal_delta_estimate=self._goal_delta(action_result, outcome),
            cortex_node_ids_written=[
                str(nid) for nid in (action_result.cortex_nodes_written or [])
            ],
            summary=self._summarise(action_result, outcome),
            output=action_result.output or "",
            blocked_by=(action_result.blocked or {}).get("kind", ""),
        )

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    @staticmethod
    def _outcome(ar: "ActionResult") -> str:
        if ar.blocked:
            # A reviewer's rejection or an unanswered checkpoint (GH-25, AK-08).
            return "blocked"
        if ar.error:
            return "fail"
        if not ar.success:
            # success=False but no explicit error → partial credit.
            return "partial"
        return "success"

    @staticmethod
    def _novelty(ar: "ActionResult") -> float:
        """Cheap proxy: writing new CORTEX nodes ⇒ novelty 1.0, else 0.5."""
        if ar.cortex_nodes_written:
            return 1.0
        if ar.output and len(ar.output) > 200:
            return 0.6
        return 0.5

    @staticmethod
    def _goal_delta(ar: "ActionResult", outcome: str) -> float:
        if outcome == "success":
            return 0.1
        if outcome == "fail":
            return -0.1
        return 0.0

    @staticmethod
    def _summarise(ar: "ActionResult", outcome: str) -> str:
        """One timeline line. Not for judging: the critics read ``output``."""
        if ar.error:
            return f"[{outcome}] {ar.error[:200]}"
        out = (ar.output or "")[:160]
        tools = ", ".join(ar.tools_used) if ar.tools_used else ""
        return f"[{outcome}]{' tools=' + tools if tools else ''} {out}".strip()
