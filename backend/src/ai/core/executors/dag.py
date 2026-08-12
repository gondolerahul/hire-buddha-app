"""
DAGExecutor — parallel/sequential plan-step execution adapter (Track 2).

Wraps ``ExecutionEngine._execute_steps_dag``. Marshalls AgentState
into the legacy ``context_state`` dict for the duration of the call,
then re-absorbs the resulting dict.
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
from src.ai.core.executors.single_step import _resolve_redis
from src.ai.core.strategist import Move
from src.ai.orm.execution import ExecutionRun

logger = logging.getLogger(__name__)


class DAGExecutor:
    name: ExecutorName = "DAG"

    async def execute(
        self,
        move: Move,
        state: AgentState,
        db: Any,
    ) -> ActionResult:
        if not move.plan_fragment:
            # Strategist should never hand DAG an empty fragment, but
            # don't crash if it does.
            return ActionResult(
                success=False,
                error="DAGExecutor invoked with empty plan_fragment",
            )

        from src.ai.core.step_engine import StepEngine

        engine = StepEngine(db, _resolve_redis(state), state.company_id)
        engine._ensure_services(cast(UUID, state.company_id))

        run = await self._reload_run(db, state.run_id)
        entity = run.entity

        ctx = await state.materialise_context_dict()
        steps_payload = self._normalise_steps(move.plan_fragment)

        start = time.time()
        try:
            results = await engine._execute_steps_dag(run, entity, steps_payload, ctx)
        except Exception as exc:                                           # noqa: BLE001
            return ActionResult(
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=int((time.time() - start) * 1000),
            )

        latency_ms = int((time.time() - start) * 1000)
        await state.absorb_context_dict(ctx)

        cost = Decimal("0")
        completed: list[str] = []
        errored = False
        last_output = ""
        for r in results or []:
            if not isinstance(r, dict):
                continue
            if r.get("error"):
                errored = True
            cost += Decimal(str(r.get("cost_usd", 0) or 0))
            sid = str(r.get("step_id") or r.get("id") or "")
            if sid:
                completed.append(sid)
            out = r.get("output")
            if out:
                last_output = str(out)

        return ActionResult(
            output=last_output[:8000] if last_output else "",
            cost_usd=cost,
            latency_ms=latency_ms,
            success=not errored,
            error="; ".join(str(r.get("error")) for r in (results or []) if isinstance(r, dict) and r.get("error"))[:500],
            completed_step_ids=completed,
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
    def _normalise_steps(plan_fragment: list[Any]) -> list[dict[str, Any]]:
        """Legacy expects list-of-dict steps."""
        out: list[dict[str, Any]] = []
        for s in plan_fragment:
            if isinstance(s, dict):
                out.append(s)
            elif hasattr(s, "model_dump"):
                out.append(s.model_dump())
            else:
                out.append(dict(getattr(s, "__dict__", {})))
        return out


register_executor(DAGExecutor())
