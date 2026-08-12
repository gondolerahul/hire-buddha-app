"""
ai.core.reflector — Produce + persist a Reflection per iteration.

Track 2 contract:
  * Always returns a Reflection (never None) so the loop log is dense.
  * Run-scope reflections live only in ``state.reflections``.

Phase 11 Track 6 additions:
  * When a Reflection carries a learnable signal (a non-empty
    ``proposed_change`` derived from post-critic tags or alignment
    drift), its scope is escalated from ``"run"`` to ``"entity"`` so
    that ``persist`` writes a candidate Intelligence rule. The
    Dreaming Engine's distillation phase later promotes corroborated
    candidates to confirmed rules.
  * ``persist`` is a no-op for ``scope="run"``; for ``scope="entity"``
    or ``"task_class"`` it best-effort-writes into the entity's
    IntelligenceTree. Failures are swallowed (the loop must never
    break on a memory-side error).
"""
from __future__ import annotations

from typing import Any, Optional, cast

from src.ai.core.agent_state import (
    AgentState,
    Observation,
    Reflection,
    Verdicts,
)

__all__ = ["Reflector"]


class Reflector:
    def __init__(
        self,
        *,
        db: Any = None,
        llm_router: Any = None,
        intelligence_tree: Any = None,
    ):
        self.db = db
        self.llm = llm_router
        self.intel = intelligence_tree

    def produce(
        self,
        state: AgentState,
        observation: Observation,
        verdicts: Optional[Verdicts] = None,
    ) -> Reflection:
        what_worked = ""
        what_didnt = ""
        cause = ""
        proposed = ""
        confidence = 0.5

        if observation.outcome == "success":
            what_worked = (
                f"executor={state.chosen_executor or 'unknown'} produced output "
                f"(novelty={observation.novelty_score:.2f})"
            )
            confidence = 0.65
        elif observation.outcome == "fail":
            what_didnt = f"fail: {observation.summary[:200]}"
            cause = "step raised or returned error"
            proposed = "consider retry with a different model/tool"
            confidence = 0.6
        elif observation.outcome == "partial":
            what_didnt = f"partial: {observation.summary[:200]}"
            cause = "step returned success=False without explicit error"
            confidence = 0.4
        else:
            what_didnt = f"blocked: {observation.summary[:200]}"
            cause = "blocker reported by observer"
            confidence = 0.5

        if verdicts and verdicts.post and verdicts.post.tags:
            tags = ", ".join(t.value for t in verdicts.post.tags)
            what_didnt = f"{what_didnt + '; ' if what_didnt else ''}post-critic tags: {tags}"
            if verdicts.post.suggestion:
                proposed = verdicts.post.suggestion

        if verdicts and verdicts.align and not verdicts.align.aligned:
            cause = (cause + "; " if cause else "") + f"drift={verdicts.align.drift:.2f}"
            if verdicts.align.correction_hint:
                proposed = (proposed + "; " if proposed else "") + verdicts.align.correction_hint

        # Track 6: escalate scope when the reflection carries a learnable
        # signal worth promoting beyond this single run.
        scope: str = "run"
        if proposed and observation.outcome != "success":
            scope = "entity"

        return Reflection(
            iteration=state.iteration,
            scope=cast(Any, scope),
            what_worked=what_worked,
            what_didnt=what_didnt,
            cause_hypothesis=cause,
            proposed_change=proposed,
            confidence=confidence,
        )

    async def persist(self, reflection: Reflection, state: AgentState) -> None:
        """Track 6 — write entity / task_class candidates to IntelligenceTree."""
        if reflection.scope == "run":
            return None
        if state.entity_id is None or state.company_id is None:
            return None
        try:
            from src.ai.memory.intelligence_tree_service import (
                IntelligenceTreeService,
                STRATEGIES_TITLE,
            )
            from src.ai.memory.cortex_models import (
                CortexNode,
                CortexNodeStatus,
                CortexNodeType,
            )
            from sqlalchemy import select
            from uuid import uuid4
            from datetime import datetime

            db = self.db or getattr(state, "db", None)
            if db is None:
                return None
            svc = IntelligenceTreeService(db, state.company_id)
            tree = await svc.get_or_create_intelligence_tree(state.entity_id)
            section = (await db.execute(
                select(CortexNode).where(
                    CortexNode.tree_id == tree.id,
                    CortexNode.parent_id == tree.root_node_id,
                    CortexNode.title == STRATEGIES_TITLE,
                )
            )).scalar_one_or_none()
            if section is None or not section.summary:
                return None
            title = f"Candidate: {reflection.proposed_change[:80]}"
            node = CortexNode(
                id=uuid4(), tree_id=tree.id, parent_id=section.id,
                node_type=CortexNodeType.STRATEGY,
                title=title,
                summary=(reflection.cause_hypothesis or reflection.what_didnt or title)[:300],
                content=reflection.proposed_change,
                status=CortexNodeStatus.ACTIVE,
                depth=section.depth + 1,
                sibling_order=0,
                source_ref={
                    "status": "candidate",
                    "kind": "reflection_candidate",
                    "scope": reflection.scope,
                    "run_id": str(state.run_id),
                    "task_class": state.task_class,
                },
                metadata_extra={
                    "confidence": reflection.confidence,
                    "iteration": reflection.iteration,
                    "task_class": state.task_class,
                    "created_at": datetime.utcnow().isoformat(),
                    "kind": "reflection_candidate",
                },
            )
            db.add(node)
            tree.total_nodes = (tree.total_nodes or 0) + 1
            await db.flush()
        except Exception:                                                   # pragma: no cover
            # Memory failures must never break the loop.
            return None
        return None
