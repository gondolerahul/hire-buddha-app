"""
ai.planning.goal_guard — Post-step goal validation middleware.

History:
  * Phase 10D introduced GoalGuard combining step alignment + overall
    plan progress validation, replacing two inline checks in
    ``execute_run``.
  * Phase 11 Track 3 unified all step-level critic logic inside
    :class:`ai.planning.critic_pipeline.RealCriticPipeline`. The new
    AgentLoop path NEVER calls GoalGuard — it goes through
    ``CriticPipeline.alignment`` and ``CriticPipeline.supervisor``.
  * The legacy ``ExecutionEngine.execute_run`` path still calls
    GoalGuard for non-AgentLoop entities. Therefore GoalGuard is now
    a thin **shim** that:
        1. Delegates the per-step alignment check to the same
           ``GoalAlignmentVerifier`` used by the new pipeline (so behaviour
           stays consistent in compatibility mode).
        2. Keeps the planner-driven goal-progress check intact for
           backwards compatibility.
        3. Logs a one-time deprecation warning per process so we can
           track residual usage during the rollout.

When Track 9 deletes the legacy path, this whole file goes away.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_DEPRECATION_LOGGED = False


class GoalGuard:
    """Backwards-compatibility shim around CriticPipeline.alignment.

    Public interface unchanged from Phase 10D — ``ExecutionEngine``
    callers do not need updating. The internal implementation now
    delegates to the same alignment primitive used by the new
    CriticPipeline so the two paths cannot drift apart.
    """

    def __init__(
        self,
        db: AsyncSession,
        company_id: UUID,
        entity_goal: str,
        task_description: str = "",
        planner: Any = None,
        confidence_threshold: float = 0.85,
    ) -> None:
        global _DEPRECATION_LOGGED
        if not _DEPRECATION_LOGGED:
            logger.info(
                "GoalGuard is deprecated as of Phase 11 Track 3. "
                "New AgentLoop entities route through "
                "CriticPipeline.alignment / .supervisor. "
                "This shim remains for legacy execute_run callers and "
                "will be removed in Track 9."
            )
            _DEPRECATION_LOGGED = True

        self.db = db
        self.company_id = company_id
        self.entity_goal = entity_goal
        self.task_description = task_description
        self.planner = planner
        self.confidence_threshold = confidence_threshold

    async def check(
        self,
        step_result: dict[str, Any],
        step_name: str,
        step_idx: int,
        all_results: list[Any],
        total_steps: int,
        is_autonomous: bool = False,
        goal_interval: int = 2,
    ) -> Dict[str, Any]:
        """Run post-step goal validation.

        Returns:
            {"action": "CONTINUE" | "RETRY" | "REPLAN" | "EARLY_EXIT",
             "reason": str,
             "correction_hint": str (if RETRY)}
        """
        result: Dict[str, Any] = {"action": "CONTINUE", "reason": ""}

        # Check 1: Per-step alignment — delegated to the same
        # GoalAlignmentVerifier the new RealCriticPipeline uses.
        if step_result and isinstance(step_result, dict):
            output = str(step_result.get("output", ""))[:2000]
            if output and not step_result.get("error"):
                try:
                    from src.ai.planning.goal_alignment import GoalAlignmentVerifier
                    verifier = GoalAlignmentVerifier(self.db, self.company_id)
                    alignment = await verifier.verify_step_alignment(
                        entity_goal=self.entity_goal,
                        task_desc=self.task_description,
                        step_output=output,
                        step_name=step_name,
                    )
                    if not alignment.get("aligned", True):
                        return {
                            "action": "RETRY",
                            "reason": (
                                f"Step '{step_name}' misaligned: "
                                f"{alignment.get('issues')}"
                            ),
                            "correction_hint": alignment.get("correction_hint", ""),
                        }
                except Exception as e:                                      # noqa: BLE001
                    logger.debug(f"Goal alignment check failed: {e}")

        # Check 2: Overall goal progress (autonomous mode only) — kept
        # intact for the legacy execute_run path.
        if is_autonomous and step_idx > 0 and step_idx % goal_interval == 0:
            if self.planner:
                try:
                    validation = await self.planner.validate_goal_progress(
                        goal=self.entity_goal,
                        completed_steps=all_results,
                        total_steps=total_steps,
                    )
                    score = validation.get("score", 0)
                    if score > self.confidence_threshold * 100:
                        return {
                            "action": "EARLY_EXIT",
                            "reason": f"Goal achieved (score={score})",
                        }
                    elif score < 30 and step_idx > total_steps // 2:
                        return {
                            "action": "REPLAN",
                            "reason": f"Low progress ({score}) past midpoint",
                        }
                except Exception as e:                                      # noqa: BLE001
                    logger.debug(f"Goal validation failed: {e}")

        return result


# ---------------------------------------------------------------------------
# Convenience: AlignmentCritic — the same logic the new CriticPipeline uses.
#
# Exposed as a separate symbol so future Tracks can import it without
# pulling in the GoalGuard shim.
# ---------------------------------------------------------------------------


class AlignmentCritic:
    """Thin wrapper for the alignment-only path; no planner involvement.

    Used by :class:`ai.planning.critic_pipeline.RealCriticPipeline`
    indirectly via :class:`GoalAlignmentVerifier`. Kept here so the
    code path is named.
    """

    def __init__(
        self,
        db: AsyncSession,
        company_id: UUID,
        entity_goal: str,
        task_description: str = "",
    ):
        self.db = db
        self.company_id = company_id
        self.entity_goal = entity_goal
        self.task_description = task_description

    async def verify(self, step_output: str, step_name: str) -> Dict[str, Any]:
        from src.ai.planning.goal_alignment import GoalAlignmentVerifier
        return await GoalAlignmentVerifier(self.db, self.company_id).verify_step_alignment(
            entity_goal=self.entity_goal,
            task_desc=self.task_description,
            step_output=step_output,
            step_name=step_name,
        )
