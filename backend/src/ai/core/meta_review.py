"""
ai.core.meta_review — DEPRECATED back-compat shim (Phase 11 Track 4).

The Phase 10D ``MetaReviewer.review_execution`` one-shot LLM call has
been replaced by :class:`ai.planning.supervisor_critic.SupervisorCritic`
which reads the full :class:`AgentState`. ``CriticPipeline.supervisor``
uses it directly.

The engine caller (``execute_run``'s in-loop meta-review hook) was deleted
with the legacy engine (C4). This shim is retained as ``CriticPipeline``'s
legacy-supervisor fallback (when ``supervisor_v2_enabled`` is OFF).

The shim:
  * keeps the public class name + ``review_execution`` signature;
  * builds a minimal :class:`AgentState`-like input on the fly so the
    new SupervisorCritic can score it;
  * logs a one-shot deprecation warning per process.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_DEPRECATION_LOGGED = False


class MetaReviewer:
    """Back-compat shim around :class:`SupervisorCritic`."""

    def __init__(self, db: AsyncSession, company_id: UUID):
        global _DEPRECATION_LOGGED
        if not _DEPRECATION_LOGGED:
            logger.info(
                "ai.core.meta_review.MetaReviewer is deprecated. New AgentLoop "
                "entities go through CriticPipeline.supervisor → "
                "SupervisorCritic.assess(); this shim is only the "
                "supervisor_v2_enabled=False fallback."
            )
            _DEPRECATION_LOGGED = True
        self.db = db
        self.company_id = company_id

    async def review_execution(
        self,
        entity_goal: str,
        completed_steps: List[Dict[str, Any]],
        remaining_steps: List[Dict[str, Any]],
        total_cost_usd: float = 0,
        context_summary: str = "",
    ) -> Dict[str, Any]:
        """Lightweight wrapper that builds a stub AgentState and delegates."""
        try:
            from src.ai.core.agent_state import AgentState
            from src.ai.core.budget import Budget
            from src.ai.llm.router import LLMRouter
            from src.ai.planning.supervisor_critic import (
                SupervisorCritic,
                SupervisorCriticConfig,
            )
            from src.ai.schemas.enums import EntityType
            from uuid import uuid4

            state = AgentState(
                run_id=uuid4(),
                entity_id=uuid4(),
                company_id=self.company_id,
                entity_type=EntityType.ACTION,
                iteration=max(1, len(completed_steps)),
                budget=Budget.from_governance(
                    max_cost_usd=max(total_cost_usd * 2, 0.10),
                    timeout_ms=600_000,
                    max_iters=50,
                ),
            )
            state.budget.consume(usd=__import__("decimal").Decimal(str(total_cost_usd or 0)))
            critic = SupervisorCritic(
                llm_router=LLMRouter(db=self.db, company_id=self.company_id),
                config=SupervisorCriticConfig(
                    entity_goal=entity_goal or "",
                    fast_path_enabled=False,
                ),
            )
            verdict = await critic.assess(state)
            return {
                "recommendation": verdict.recommendation,
                "confidence": verdict.confidence,
                "reasoning": verdict.reasoning,
                "adjustments": [],
            }
        except Exception as exc:                                            # noqa: BLE001
            logger.warning("MetaReviewer shim assess failed: %s", exc)
            return {
                "recommendation": "CONTINUE",
                "confidence": 0.5,
                "reasoning": "Review unavailable",
            }
