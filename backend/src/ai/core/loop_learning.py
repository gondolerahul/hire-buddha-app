"""loop_learning.py — what an AgentLoop run feeds the platform's learning.

Moved out of ``agent_loop.py`` (IN-17, ON-09): the task classification, the
plan-style bandit and its rewards, the outcome-triggered Dreaming pass, and the
flag lookup they share with the loop. ``AgentLoop`` mixes this in; the
attributes below are set by ``AgentLoop.__init__`` and ``_compose``.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from src.ai.core.agent_loop_sse import event_async
from src.ai.core.agent_state import AgentState
from src.ai.core.feature_flags import FeatureFlags
from src.ai.schemas.enums import RunStatus

logger = logging.getLogger("src.ai.core.agent_loop")


class LoopLearning:
    db: Any
    redis: Any
    flags: FeatureFlags
    memory: Any
    bandit: Optional[Any]
    _entity: Any

    def _entity_extras(self) -> Optional[dict[str, Any]]:
        if self._entity is None:
            return None
        if isinstance(self._entity, dict):
            return self._entity.get("metadata_extensions")
        return getattr(self._entity, "metadata_extensions", None)

    async def _flag_or_default(self, key: str, default: bool, state: AgentState) -> bool:
        try:
            return await self.flags.is_on(
                key,
                company_id=state.company_id,
                entity_extras=self._entity_extras(),
            )
        except Exception:                                                   # pragma: no cover
            return default

    async def _classify_task(self, state: AgentState) -> None:
        try:
            from src.ai.memory.task_classifier import TaskClassifier
            v2_enabled = await self._flag_or_default(
                "task_classifier.v2_enabled", False, state,
            )
            classifier = TaskClassifier(
                db=self.db, company_id=state.company_id,
                v2_enabled=v2_enabled,
            )
            task_desc = ""
            entity = self._entity
            if entity is not None:
                task_desc = (
                    getattr(entity, "name", "")
                    or getattr(entity, "goal", "")
                    or ""
                )
            state.task_class = await classifier.classify(
                task_description=task_desc, entity=entity,
            )
            await event_async(
                "agent.task_class.classified",
                run_id=str(state.run_id),
                entity_id=str(state.entity_id) if state.entity_id else None,
                task_class=state.task_class,
                classifier_version="v2" if v2_enabled else "v1",
            )
        except Exception as exc:                                            # noqa: BLE001
            logger.debug("task_class classification fell back to default: %s", exc)
            state.task_class = "general"

    async def _build_bandit(self, state: AgentState) -> Optional[Any]:
        try:
            enabled = await self._flag_or_default("bandit.enabled", True, state)
        except Exception:                                                   # pragma: no cover
            enabled = False
        if not enabled or state.company_id is None:
            return None
        try:
            from src.ai.planning.plan_style_bandit import PlanStyleBandit
            # Through the resolver, so a company or global row overrides it.
            epsilon = await self.flags.get_float(
                "bandit.epsilon", company_id=state.company_id, default=0.10,
            )
            return PlanStyleBandit(
                db=self.db, company_id=state.company_id, epsilon=epsilon,
            )
        except Exception as exc:                                            # noqa: BLE001
            logger.debug("bandit construction failed; running without bandit: %s", exc)
            return None

    async def _enqueue_dreaming_trigger(self, state: AgentState, status: str) -> None:
        """Phase 11 Track 6 — enqueue an outcome-triggered Dreaming pass.

        Best-effort: silently no-op when the feature flag is off or the
        Arq queue isn't reachable (tests, local runs without Redis).
        """
        try:
            enabled = await self._flag_or_default(
                "memory.dreaming_outcome_trigger", True, state,
            )
        except Exception:                                                   # pragma: no cover
            enabled = False
        # Dreaming learns from episodes, which only memory-enabled entities record.
        if not enabled or state.entity_id is None or self.memory is None:
            return
        reason = "success" if status == RunStatus.COMPLETED.value else "failure"
        try:
            from arq.connections import ArqRedis
            redis = self.redis
            if redis is None:
                return
            arq = redis if isinstance(redis, ArqRedis) else ArqRedis(
                getattr(redis, "connection_pool", redis),
            )
            await arq.enqueue_job(
                "dreaming_outcome_trigger",
                str(state.entity_id),
                reason,
                str(state.company_id) if state.company_id else None,
                _queue_name="arq:queue",
            )
            await event_async(
                "agent.dreaming.triggered",
                entity_id=str(state.entity_id),
                reason=reason,
            )
        except Exception as exc:                                            # noqa: BLE001
            logger.debug(f"dreaming_outcome_trigger enqueue skipped: {exc}")

    async def _finalize_bandit(self, state: AgentState, status: str) -> None:  # noqa: ARG002
        """Reward each bandit pull with its own iteration's outcome and cost
        (PC-21). Before, every arm used in the run got the run's success and
        an even share of its whole cost, so one unlucky run pushed a good
        arm out for good."""
        if not getattr(self, "bandit", None) or not state.bandit_pulls:
            return
        assert self.bandit is not None
        for pull in state.bandit_pulls:
            try:
                st = await self.bandit.update_arm(
                    entity_id=state.entity_id, task_class=state.task_class, arm=pull["arm"],
                    success=bool(pull.get("success")), cost_usd=float(pull.get("cost_usd") or 0),
                )
                await event_async(
                    "agent.bandit.arm_updated", run_id=str(state.run_id), entity_id=str(state.entity_id),
                    task_class=state.task_class, arm=pull["arm"], success=bool(pull.get("success")),
                    cost_usd=float(pull.get("cost_usd") or 0), iteration=pull.get("iteration"),
                    new_score=self.bandit.score(st),
                )
            except Exception as exc:                                        # noqa: BLE001
                logger.debug("bandit arm update failed for %s: %s", pull.get("arm"), exc)
