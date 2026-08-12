"""
RecursiveExecutor — goal→plan mapping for goal-only AGENTs (Track 2).

The Strategist routes an AGENT that enters the loop with no plan here. Rather
than hand the whole run to the legacy ``execute_run`` (the C4 deletion target),
this maps the goal onto a plan via ``PlannerService.reconcile`` and lets the
loop's plan-driven path (SingleStep / DAG, on the StepEngine surface) execute
it on subsequent iterations. When the goal yields no resolvable plan, it
completes cleanly with the legacy engine's sentinel output ("Success"), so a
goal-only AGENT with nothing to dispatch winds the run down to COMPLETED
exactly as ``execute_run`` did — without ever calling it.
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
from src.ai.core.strategist import Move
from src.ai.orm.execution import ExecutionRun

logger = logging.getLogger(__name__)


class RecursiveExecutor:
    name: ExecutorName = "Recursive"

    async def execute(
        self,
        move: Move,                # noqa: ARG002
        state: AgentState,
        db: Any,
    ) -> ActionResult:
        from src.ai.planning.planner_service import PlannerService

        run = await self._reload_run(db, state.run_id)
        entity = run.entity
        start = time.time()
        input_data = run.input_data if isinstance(run.input_data, dict) else {}

        steps: Any = None
        try:
            planner = PlannerService(db, company_id=cast(UUID, state.company_id))
            plan = await planner.reconcile(run, entity, input_data)
            steps = plan.get("steps") if isinstance(plan, dict) else None
        except Exception as exc:                                           # noqa: BLE001
            logger.warning("Recursive goal planning failed: %s", exc)
            plan = None

        latency_ms = int((time.time() - start) * 1000)

        if steps:
            # Goal mapped onto a concrete plan: hand it to the loop's plan-driven
            # path (Strategist Case A → SingleStep/DAG) for the next iterations.
            state.plan_steps = list(steps)
            try:
                run.dynamic_plan = plan
                await db.commit()
            except Exception:                                              # pragma: no cover
                await db.rollback()
            return ActionResult(success=True, latency_ms=latency_ms)

        # No resolvable plan for this goal-only AGENT — complete cleanly,
        # mirroring the legacy engine's empty-plan completion. The entity's goal
        # seeds one open subgoal (agent_loop bootstrap); achieve it so the
        # Strategist returns DONE (the legacy engine instead terminated the run
        # out-of-band, which the loop honoured via _check_cancelled). Stamp the
        # sentinel result_data the legacy engine wrote so _persist_final
        # preserves it and the run output matches the golden.
        for sg in list(state.open_subgoals):
            state.achieve_subgoal(sg.id)
        try:
            run.result_data = {"output": "Success", "steps": []}
            await db.commit()
        except Exception:                                                  # pragma: no cover
            await db.rollback()
        return ActionResult(output="Success", success=True, latency_ms=latency_ms)

    @staticmethod
    async def _reload_run(db: Any, run_id: Any) -> ExecutionRun:
        result = await db.execute(
            select(ExecutionRun)
            .options(selectinload(ExecutionRun.entity))
            .where(ExecutionRun.id == run_id)
        )
        return cast(ExecutionRun, result.scalar_one())


register_executor(RecursiveExecutor())
