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


__all__ = ["Observer"]


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
        )

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    @staticmethod
    def _outcome(ar: "ActionResult") -> str:
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
        if ar.error:
            return f"[{outcome}] {ar.error[:200]}"
        out = (ar.output or "")[:160]
        tools = ", ".join(ar.tools_used) if ar.tools_used else ""
        return f"[{outcome}]{' tools=' + tools if tools else ''} {out}".strip()
