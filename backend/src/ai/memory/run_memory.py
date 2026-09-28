"""
ai.memory.run_memory — the AgentLoop's CORTEX + memory wiring for one run.

  * :func:`open_run_tree` — create (or resume) the run's CORTEX tree, which the
    loop's AgentState snapshots and the critic's StepHealthRecords are written
    into.
  * :func:`assemble_run_memory` — the memory read path: assemble what past runs
    learned once per run, publish it into ``context_state`` for the step prompt
    and planner, and return a :class:`RunMemory` reader for the Perceiver and
    critic pipeline.
  * :func:`record_episode` — the write side of episodic memory: the finished
    run becomes an episode, which the next run retrieves and Dreaming distils.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

__all__ = [
    "open_run_tree", "memory_scope_for", "RunMemory", "assemble_run_memory", "record_episode",
]


async def open_run_tree(
    db: AsyncSession, state: Any, entity: Any, run_id: Optional[UUID],
) -> tuple[Any, Any]:
    """Create — or, for a run carrying ``cortex_tree_id``, resume — its tree.

    Returns ``(cortex_service, tree)``, or ``(None, None)`` when setup fails;
    snapshots and health records are then disabled for the run.
    """
    try:
        from src.ai.memory.cortex_service import CortexService
        from src.ai.orm.execution import ExecutionRun

        cortex = CortexService(db=db, company_id=state.company_id)
        run = (await db.execute(
            select(ExecutionRun.input_data, ExecutionRun.user_id).where(ExecutionRun.id == run_id)
        )).first() if run_id else None
        input_data = (run.input_data or {}) if run else {}

        existing = input_data.get("cortex_tree_id")
        if existing:
            tree, _vp, _ck = await cortex.resume_tree(UUID(str(existing)))
        else:
            task = input_data.get("input") or getattr(entity, "goal", None) or "agent loop run"
            tree = await cortex.create_tree(
                entity_id=state.entity_id,
                user_id=run.user_id if run else None,
                task_description=str(task)[:500],
            )
        await db.commit()
        return cortex, tree
    except Exception as exc:                                                # noqa: BLE001
        logger.warning("AgentLoop CORTEX setup failed; snapshots/health disabled: %s", exc)
        return None, None


def memory_scope_for(entity: Any) -> Optional[str]:
    """The entity's memory scope, or ``None`` when memory is off for it.

    Reads ``capabilities.memory`` (``MemoryConfig``): memory is opt-in via
    ``enabled``, and ``memory_scope="NONE"`` turns injection off as well.
    """
    caps = getattr(entity, "capabilities", None) or {}
    cfg = caps.get("memory") if isinstance(caps, dict) else None
    if not isinstance(cfg, dict) or not cfg.get("enabled"):
        return None
    scope = str(cfg.get("memory_scope") or "FULL").upper()
    return None if scope == "NONE" else scope


class RunMemory:
    """Memory assembled once at the start of a run, read every iteration.

    Handed to the Perceiver (and the critic pipeline) so each iteration sees
    the same rules and past runs without re-running the four-domain assembly —
    an embedding call plus vector scans — per iteration.
    """

    def __init__(self, context: Dict[str, Any]) -> None:
        self._rules: List[Dict[str, Any]] = list(context.get("__intelligence_rules__") or [])
        self._episodes: List[Dict[str, Any]] = list(context.get("__episodic_memory__") or [])

    async def intelligence_rules(self, entity_id: Any = None, top_k: int = 5) -> List[Dict[str, Any]]:
        return self._rules[:top_k]

    async def similar_runs(self, entity_id: Any = None, top_k: int = 3) -> List[Dict[str, Any]]:
        return [
            {
                "summary": f"[{ep.get('status', '')}] {str(ep.get('input') or '')[:150]}"
                           f" → {str(ep.get('output') or '')[:150]}",
                "at": ep.get("at", ""),
            }
            for ep in self._episodes[:top_k]
        ]


async def assemble_run_memory(
    db: AsyncSession,
    state: Any,
    *,
    entity: Any,
    runtime_tree: Any = None,
    resumed: bool = False,
) -> Optional[RunMemory]:
    """Assemble cross-run memory once per run and return its reader.

    Writes ``__memory__`` (the block the step prompt injects),
    ``__intelligence_rules__`` and ``__episodic_memory__`` into
    ``state.context_state``. A resumed run's snapshot already carries them, so
    the four-domain assembly is not repeated. Returns ``None`` when the entity
    has memory disabled.
    """
    from src.ai.memory import assembler

    scope = memory_scope_for(entity)
    if scope is None or state.entity_id is None:
        return None
    if resumed:
        return RunMemory(state.context_state)

    query = state.context_state.get("input")
    if not isinstance(query, str) or not query.strip():
        query = getattr(entity, "goal", None) or getattr(entity, "name", "") or ""
    try:
        memory_ctx = await assembler.assemble_memory(
            db, state.company_id, state.entity_id,
            task_description=str(query)[:2000],
            memory_scope=scope,
            runtime_tree=runtime_tree,
        )
        # Assembly writes reference nodes into the runtime tree.
        await db.commit()
    except Exception as exc:                                                # noqa: BLE001
        logger.warning("Memory assembly failed; running without memory: %s", exc)
        await db.rollback()
        memory_ctx = {}

    state.context_state.update(memory_ctx)
    from src.ai.core.agent_loop_sse import event_async
    await event_async(
        "agent.memory.assembled",
        run_id=str(state.run_id),
        scope=scope,
        rules=len(memory_ctx.get("__intelligence_rules__") or []),
        episodes=len(memory_ctx.get("__episodic_memory__") or []),
        block_chars=len(memory_ctx.get("__memory__") or ""),
    )
    return RunMemory(state.context_state)


async def record_episode(db: AsyncSession, run_id: UUID, *, runtime_tree_id: Optional[UUID] = None) -> None:
    """Write a finished run into its entity's Episodic Tree (best effort).

    Only entities with memory enabled record episodes. The episode summarises
    the task and its answer — ``input_data["input"]`` / ``result_data["output"]``
    — rather than the whole context a child run inherits from its parent.
    """
    from src.ai.memory.episodic_tree_service import EpisodicTreeService
    from src.ai.orm.execution import ExecutionRun

    try:
        run = (await db.execute(
            select(ExecutionRun).options(selectinload(ExecutionRun.entity))
            .where(ExecutionRun.id == run_id)
        )).scalar_one_or_none()
        if run is None or memory_scope_for(run.entity) is None:
            return

        def _main(data: Any, key: str) -> Any:
            return data.get(key, data) if isinstance(data, dict) else data

        episode = SimpleNamespace(
            id=run.id, created_at=run.created_at, status=run.status, entity=run.entity,
            input_data=_main(run.input_data, "input"),
            result_data=_main(run.result_data, "output"),
            context_state=run.context_state,
            total_cost_usd=run.total_cost_usd, total_tokens=run.total_tokens,
            execution_time_ms=run.execution_time_ms,
        )
        await EpisodicTreeService(db, run.company_id).write_episode(
            entity_id=run.entity_id, run=episode, runtime_tree_id=runtime_tree_id,
        )
        await db.commit()
    except Exception as exc:                                                # noqa: BLE001
        logger.warning("Episode write failed for run %s: %s", run_id, exc)
        await db.rollback()
