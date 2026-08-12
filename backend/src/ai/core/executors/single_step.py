"""
SingleStepExecutor — thin adapter around the legacy per-step path.

Track 2 implementation delegates to ``ExecutionEngine._execute_step_wrapper``
for each ready plan step (when a plan_fragment is provided). When no
plan_fragment is supplied it returns a no-op result — it MUST NOT hand the
whole run to ``ExecutionEngine.execute_run``.

Why no full-run fallback: ``execute_run`` owns the ENTIRE run lifecycle
(re-plans, runs the whole DAG, settles billing, marks the run COMPLETED). If
the AgentLoop dispatched the run, invoking ``execute_run`` from inside a single
loop iteration defeats the loop — the run terminalises mid-iteration, the
loop's next ``_check_cancelled`` reads status=COMPLETED and emits a spurious
``agent.loop.cancelled`` (frozen UI), and the legacy engine's flat re-plan
never descends to child/tool dispatch. The loop now reconciles a plan up front
(``AgentLoop._ensure_plan``) so a concrete plan_fragment is always available;
this no-fragment branch is only reached when there is genuinely nothing to do.

Adapter-only: no new business logic.
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.ai.core.agent_state import AgentState, ExecutorName
from src.ai.core.executors.base import ActionResult, register_executor
from src.ai.core.strategist import Move
from src.ai.core.trace import span
from src.ai.orm.execution import ExecutionRun

logger = logging.getLogger(__name__)


class SingleStepExecutor:
    name: ExecutorName = "SingleStep"

    async def execute(
        self,
        move: Move,
        state: AgentState,
        db: Any,
    ) -> ActionResult:
        if not move.plan_fragment:
            return await self._no_plan_noop(state)
        return await self._execute_steps(move, state, db)

    async def _execute_steps(
        self,
        move: Move,
        state: AgentState,
        db: Any,
    ) -> ActionResult:
        from src.ai.core.step_engine import StepEngine
        from src.common.database import AsyncSessionLocal

        ctx = await state.materialise_context_dict()
        cost = Decimal("0")
        last_output = ""
        completed: list[str] = []
        errored = False
        error_msg = ""

        start = time.time()
        # Run the legacy step engine on its OWN session. ``_execute_step_wrapper``
        # (especially for CHILD_ENTITY_INVOCATION steps, which spawn a child run
        # and commit its lifecycle) performs its own commits/status writes. Doing
        # that on the AgentLoop's shared session corrupts it — the next loop DB
        # access then raises PendingRollbackError / "greenlet_spawn has not been
        # called". Isolating the engine session keeps the loop's session clean.
        async with AsyncSessionLocal() as inner_db:
            engine = StepEngine(inner_db, _resolve_redis(state), state.company_id)
            engine._ensure_services(cast(UUID, state.company_id))

            run = await self._reload_run(inner_db, state.run_id)
            entity = run.entity

            # The legacy step path bills tool/LLM spend by mutating
            # ``run.total_cost_usd`` in place (see StepExecutorService._log_usage
            # / ToolCostResolver.charge) — it never returns cost on the step
            # result dict. Snapshot the run's accumulated cost before the
            # fragment so we can report the real per-iteration delta below; the
            # raw step ``cost_usd`` is almost always 0.0.
            cost_before = Decimal(str(getattr(run, "total_cost_usd", 0) or 0))

            for step in move.plan_fragment or []:
                step_obj = self._coerce_step(step)
                _step_name = str(getattr(step_obj, "name", "") or getattr(step_obj, "step_id", "") or "step")
                _step_type = str(getattr(step_obj, "type", "") or "")
                # Step span — parent of the tool / LLM spans the legacy engine
                # opens for this step. Tags it with the step's input context.
                async with span(
                    "step", _step_name,
                    step_id=str(getattr(step_obj, "step_id", "") or ""),
                    step_type=_step_type,
                    instruction=getattr(step_obj, "instruction", None) or getattr(step_obj, "description", None),
                ) as _step_span:
                    try:
                        result = await engine._execute_step_wrapper(run, entity, step_obj, ctx)
                    except Exception as exc:                               # noqa: BLE001
                        errored = True
                        error_msg = f"{type(exc).__name__}: {exc}"
                        logger.warning("[SingleStepExecutor] step failed: %s", error_msg)
                        _step_span.set_error(error_msg)
                        break

                    step_id = str(getattr(step_obj, "step_id", None) or step_obj.name or "")
                    if step_id:
                        ctx[step_id] = result.get("output") or result.get("result") or ""
                        completed.append(step_id)
                    last_output = result.get("output", last_output) or last_output
                    cost += Decimal(str(result.get("cost_usd", 0) or 0))
                    _step_span.set_output(result.get("output") or result.get("result") or "")
                    _step_span.set_cost(result.get("cost_usd", 0) or 0)
                    if result.get("error"):
                        _step_span.set_error(str(result.get("error")))

            # Reconcile with the engine-tracked spend. ``run`` is the same ORM
            # instance the step executor mutated, so its cost is current; the
            # delta captures tool + LLM cost the step dicts don't surface. Take
            # the larger so the per-iteration ActionResult (and the critic /
            # budget that read it) see the real money spent, not 0.0.
            cost_after = Decimal(str(getattr(run, "total_cost_usd", 0) or 0))
            engine_delta = cost_after - cost_before
            if engine_delta > cost:
                cost = engine_delta

        latency_ms = int((time.time() - start) * 1000)
        await state.absorb_context_dict(ctx)

        return ActionResult(
            output=last_output or "",
            cost_usd=cost,
            latency_ms=latency_ms,
            success=not errored,
            error=error_msg,
            completed_step_ids=completed,
        )

    async def _no_plan_noop(self, state: AgentState) -> ActionResult:
        """No plan_fragment → do nothing this iteration. NEVER run execute_run.

        Previously this branch handed the entire run to
        ``ExecutionEngine.execute_run``, which owns the full run lifecycle
        (re-plan, run the whole DAG, settle billing, mark COMPLETED). Doing that
        from inside one AgentLoop iteration defeated the loop and re-billed the
        run (Phase 11 AgentLoop incidents #1/#2). The loop now reconciles a plan
        up front (``AgentLoop._ensure_plan``) so a concrete one-step
        plan_fragment is normally always available; reaching this branch means
        the Strategist genuinely has nothing concrete to dispatch.

        Returning a zero-cost, zero-progress success lets the loop's own
        termination machinery (Strategist.decide_next + the hard iteration cap /
        pre-critic circuit breaker) wind the run down cleanly — no nested
        lifecycle, no double billing, no terminal-status race.
        """
        logger.info(
            "[SingleStepExecutor] no plan_fragment for run %s; returning no-op "
            "(not invoking execute_run)",
            state.run_id,
        )
        return ActionResult(
            output="",
            cost_usd=Decimal("0"),
            latency_ms=0,
            success=True,
            completed_step_ids=[],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
        """Adapter: legacy expects a PlanStep-like object with attrs."""
        from src.ai.schemas.planning import PlanStep

        if isinstance(step, PlanStep):
            return step
        if isinstance(step, dict):
            return PlanStep.model_validate(step)
        return step


def _resolve_redis(state: AgentState) -> Any:
    """Pull the live redis client off the state.

    Prefers the transient ``redis_client`` attribute; falls back to the legacy
    ``__redis__`` context key for any older snapshot/caller that still set it.
    """
    return getattr(state, "redis_client", None) or state.context_state.get("__redis__")


register_executor(SingleStepExecutor())
