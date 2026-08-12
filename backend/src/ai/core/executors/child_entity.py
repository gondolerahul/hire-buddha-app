"""
ChildEntityExecutor — async suspend/resume child dispatch for the loop.

CHILD_ENTITY_INVOCATION steps spawn a sub-run. The loop dispatches every
child as its own isolated run job (own session, own budget) and suspends
(WAITING_ON_CHILDREN) until the child's finalize fires ``resume_parent_run``.
This is the sole child path — the inline nested-run variant (which amplified
cost ~$11/child on the parent's session) is retired.
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

# Default ceiling on a single parent's in-flight (dispatched, not-yet-folded)
# async children. Bounds fleet load from a fan-out PROCESS; overridable per
# entity via ``governance.max_concurrent_children``. When the ceiling is hit
# the executor runs the next child inline (backpressure) instead of enqueuing
# another isolated job.
DEFAULT_MAX_CONCURRENT_CHILDREN = 8

_TERMINAL_CHILD_STATUSES = {
    "COMPLETED", "FAILED", "PARTIAL_COMPLETE", "CANCELLED",
}


def pending_child_count(state: Any) -> int:
    """Number of this parent's children dispatched but not yet folded."""
    return sum(
        1 for c in getattr(state, "awaiting_children", []) or []
        if c.get("status") not in _TERMINAL_CHILD_STATUSES
    )


def within_child_dispatch_cap(state: Any, governance: dict[str, Any]) -> bool:
    """True if another async child may be dispatched without exceeding the
    per-parent concurrency cap."""
    raw = (governance or {}).get("max_concurrent_children")
    try:
        cap = int(raw) if raw is not None else DEFAULT_MAX_CONCURRENT_CHILDREN
    except (TypeError, ValueError):
        cap = DEFAULT_MAX_CONCURRENT_CHILDREN
    if cap < 1:
        cap = DEFAULT_MAX_CONCURRENT_CHILDREN
    return pending_child_count(state) < cap


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

        step = move.plan_fragment[0]
        from src.ai.core.step_engine import StepEngine

        redis = _resolve_redis(state)
        engine = StepEngine(db, redis, state.company_id)
        engine._ensure_services(cast(UUID, state.company_id))

        run = await self._reload_run(db, state.run_id)
        entity = run.entity

        step_obj = self._coerce_step(step)
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

        governance = (entity.governance or {}) if entity else {}
        if not within_child_dispatch_cap(state, governance):
            # The cap is now advisory: with the inline backpressure path retired,
            # we dispatch anyway and let the child queue absorb the fan-out.
            logger.info(
                "Child dispatch cap reached for parent %s (%d in flight); "
                "dispatching anyway.", run.id, pending_child_count(state),
            )

        try:
            return await self._dispatch_async(
                engine, redis, run, entity, step_obj, state, start,
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
        step_obj: Any,
        state: AgentState,
        start: float,
    ) -> ActionResult:
        """Create the child run, enqueue it as its own job, return an
        ``awaiting_children`` ActionResult so the loop suspends."""
        from arq.connections import ArqRedis

        ctx = await state.materialise_context_dict()
        child_run = await engine._step_executor.create_child_run(
            run, entity, step_obj, ctx
        )
        await state.absorb_context_dict(ctx)

        step_id = str(getattr(step_obj, "step_id", None) or getattr(step_obj, "name", "") or "")

        # Enqueue the child as its own isolated run job (same entry point a
        # top-level run uses → its own session, budget, and AgentLoop).
        arq_redis = ArqRedis(redis.connection_pool)
        await arq_redis.enqueue_job("run_execution_recursive", str(child_run.id))

        logger.info(
            "Async-dispatched child run %s (step=%s) for parent %s; suspending.",
            child_run.id, step_id, run.id,
        )
        return ActionResult(
            success=True,
            output="",
            latency_ms=int((time.time() - start) * 1000),
            children_run_ids=[child_run.id],
            awaiting_children=[{
                "run_id": str(child_run.id),
                "step_id": step_id,
                "status": "PENDING",
            }],
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
