"""
ChildEntityExecutor — async suspend/resume child dispatch for the loop.

CHILD_ENTITY_INVOCATION steps spawn sub-runs. The Strategist hands this
executor the ready child steps, up to ``governance.max_concurrent_children``
(AK-07); each is dispatched as its own isolated run job (own session, own
budget) and the parent suspends (WAITING_ON_CHILDREN) until all of them are
terminal — every child's finalize fires ``resume_parent_run``. This is the sole
child path — the inline nested-run variant (which amplified cost ~$11/child on
the parent's session) is retired.
"""
from __future__ import annotations

import logging
import time
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.ai.core.agent_state import AgentState, ExecutorName
from src.ai.core.executors.base import ActionResult, register_executor
from src.ai.core.executors.single_step import _resolve_redis
from src.ai.core.strategist import Move
from src.ai.orm.execution import ExecutionRun

logger = logging.getLogger(__name__)

class ChildEntityExecutor:
    name: ExecutorName = "ChildEntity"

    async def execute(
        self,
        move: Move,
        state: AgentState,
        db: Any,
    ) -> ActionResult:
        if not move.plan_fragment:
            return ActionResult(
                success=False,
                error="ChildEntityExecutor invoked with empty plan_fragment",
            )

        from src.ai.core.step_engine import StepEngine

        redis = _resolve_redis(state)
        engine = StepEngine(db, redis, state.company_id)
        engine._ensure_services(cast(UUID, state.company_id))

        run = await self._reload_run(db, state.run_id)
        entity = run.entity

        start = time.time()

        # ── Async child dispatch (suspend/resume) — the sole child path ──────
        # Create the child run, enqueue it as its OWN isolated job (own session
        # + own budget), and return an ``awaiting_children`` marker. The
        # AgentLoop snapshots and suspends (WAITING_ON_CHILDREN) instead of
        # blocking this worker; the child's finalize enqueues
        # ``resume_parent_run`` which folds the result back in. There is no
        # inline fallback: running a child inline meant a nested full run on the
        # parent's session — the ~$11/child amplification this design retired.
        if redis is None:
            return ActionResult(
                success=False,
                error=(
                    "child-entity dispatch requires Redis "
                    "(async child dispatch is the sole child path)"
                ),
                latency_ms=int((time.time() - start) * 1000),
            )

        try:
            return await self._dispatch_async(
                engine, redis, run, entity,
                [self._coerce_step(step) for step in move.plan_fragment], state, start,
            )
        except Exception as exc:                                           # noqa: BLE001
            logger.warning("Async child dispatch failed: %s", exc)
            return ActionResult(
                success=False,
                error=f"child dispatch failed: {type(exc).__name__}: {exc}",
                latency_ms=int((time.time() - start) * 1000),
            )

    async def _dispatch_async(
        self,
        engine: Any,
        redis: Any,
        run: ExecutionRun,
        entity: Any,
        steps: list[Any],
        state: AgentState,
        start: float,
    ) -> ActionResult:
        """Create and enqueue a child run per step; return them as
        ``awaiting_children`` so the loop suspends until all are terminal.

        Stops at the first step that cannot be dispatched (a composition or
        depth refusal, a missing child): the children already dispatched are
        awaited, and the refused step stays ready for the next move. When none
        was dispatched the move fails with the reason.
        """
        from src.common.job_queue import enqueue_child_run

        ctx = await state.materialise_context_dict()
        awaiting: list[dict[str, Any]] = []
        error = ""
        for step_obj in steps:
            try:
                child_run = await engine._step_executor.create_child_run(run, entity, step_obj, ctx)
                # Its own isolated run job (same entry point a top-level run
                # uses → own session, budget and AgentLoop), on the child-run
                # queue and its own worker (SA-07).
                await enqueue_child_run(redis, child_run.id)
            except Exception as exc:                                       # noqa: BLE001
                error = f"child dispatch failed: {type(exc).__name__}: {exc}"
                logger.warning("Async child dispatch failed for parent %s: %s", run.id, exc)
                break
            step_id = str(getattr(step_obj, "step_id", None) or getattr(step_obj, "name", "") or "")
            awaiting.append({"run_id": str(child_run.id), "step_id": step_id, "status": "PENDING"})
        await state.absorb_context_dict(ctx)

        latency_ms = int((time.time() - start) * 1000)
        if not awaiting:
            return ActionResult(success=False, error=error or "no child dispatched", latency_ms=latency_ms)
        logger.info(
            "Async-dispatched %d child run(s) for parent %s; suspending.", len(awaiting), run.id,
        )
        return ActionResult(
            success=True,
            output="",
            latency_ms=latency_ms,
            children_run_ids=[UUID(c["run_id"]) for c in awaiting],
            awaiting_children=awaiting,
        )

    @staticmethod
    async def _reload_run(db: Any, run_id: Any) -> ExecutionRun:
        result = await db.execute(
            select(ExecutionRun)
            .options(selectinload(ExecutionRun.entity))
            .where(ExecutionRun.id == run_id)
        )
        return cast(ExecutionRun, result.scalar_one())

    @staticmethod
    def _coerce_step(step: Any) -> Any:
        from src.ai.schemas.planning import PlanStep

        if isinstance(step, PlanStep):
            return step
        if isinstance(step, dict):
            return PlanStep.model_validate(step)
        return step


register_executor(ChildEntityExecutor())
