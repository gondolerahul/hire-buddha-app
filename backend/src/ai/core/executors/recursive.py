"""
RecursiveExecutor — plans an entity that entered the loop without a plan.

The loop reconciles a plan before its first iteration (``AgentLoop._ensure_plan``)
at every level; the Strategist sends a run here only when it still has none
(R1, EP-26). This maps the goal onto a plan via ``PlannerService.reconcile`` and
hands it to the loop's plan-driven path (SingleStep / DAG / ChildEntity) for the
next iterations. When no plan can be made it fails, with the reason, and the
Strategist ends the run as FAILED — it never reports work it did not do.
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
        plan_error = ""
        try:
            planner = PlannerService(db, company_id=cast(UUID, state.company_id))
            plan = await planner.reconcile(run, entity, input_data)
            steps = plan.get("steps") if isinstance(plan, dict) else None
        except Exception as exc:                                           # noqa: BLE001
            logger.warning("Recursive goal planning failed: %s", exc)
            plan = None
            plan_error = f"{type(exc).__name__}: {exc}"

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

        # Nothing could be planned: fail with the reason. The Strategist ends
        # the run (decide_next) instead of idling to the iteration cap, and the
        # run is FAILED — not COMPLETED with work it never did.
        reason = "No plan could be made for this entity"
        if plan_error:
            reason += f": {plan_error}"
        return ActionResult(success=False, error=reason, latency_ms=latency_ms)

    @staticmethod
    async def _reload_run(db: Any, run_id: Any) -> ExecutionRun:
        result = await db.execute(
            select(ExecutionRun)
            .options(selectinload(ExecutionRun.entity))
            .where(ExecutionRun.id == run_id)
        )
        return cast(ExecutionRun, result.scalar_one())


register_executor(RecursiveExecutor())
