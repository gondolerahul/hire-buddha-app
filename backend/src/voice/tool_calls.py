"""voice/tool_calls.py — a voice call's tool calls, run like a step's (TL-20).

A voice agent's tool calls used to run with only a company and a user in their
context: no run, no ``tool_interaction_logs`` row, no charge. Now the first
tool call of a call opens an ``ExecutionRun`` for it (the voice agent, channel
``voice``), and every call is resolved through the agent's ``ToolAccess``,
told who it is for by an ``ExecutionContext``, logged against the run and
priced through ``ToolCostResolver`` — the same path as a step's tool call.

The run is not settled on its own: its cost joins the call's total, which the
call-end path charges once with the telephony and audio cost.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select, update

logger = logging.getLogger(__name__)

__all__ = ["VoiceToolCalls"]


class VoiceToolCalls:
    """The tool calls of one voice call."""

    STEP_NAME = "voice call"

    def __init__(self, db: Any, voice_session: Any):
        self.db = db
        self.voice_session = voice_session
        self.run: Any = None
        self.access: Any = None
        self.context: Any = None
        self.cost = Decimal("0")
        self._resolver: Any = None
        # The handler runs each tool-call message as its own task, and they
        # share one AsyncSession: one batch at a time.
        self._lock = asyncio.Lock()

    async def _open(self) -> None:
        """Load the agent's access and open the call's run, once."""
        if self.access is not None:
            return
        from src.ai.governance.tool_access import ExecutionContext, ToolAccess
        from src.ai.governance.subjects import voice_subjects
        from src.ai.governance.tool_cost_resolver import ToolCostResolver
        from src.ai.orm import ExecutionRun, HierarchicalEntity
        from src.ai.schemas.enums import RunStatus

        vs = self.voice_session
        entity = (await self.db.execute(
            select(HierarchicalEntity).where(
                HierarchicalEntity.id == vs.agent_id,
                HierarchicalEntity.company_id == vs.company_id,
            )
        )).scalar_one_or_none()
        if entity is None:
            # No agent in this company: nothing is granted, every call is refused.
            self.access = ToolAccess(company_id=vs.company_id)
            self.context = ExecutionContext.for_session(vs.company_id, None)
            return
        self.run = ExecutionRun(
            company_id=vs.company_id, entity_id=entity.id, status=RunStatus.RUNNING,
            started_at=datetime.utcnow(),
            input_data={"input": "voice call", "channel": "voice", "voice_session_id": str(vs.id),
                        # The caller or the campaign's contact: whom this
                        # call's tools may message or update (TL-09).
                        "subjects": voice_subjects(vs)},
        )
        self.db.add(self.run)
        await self.db.flush()
        self.access = await ToolAccess.load(self.db, vs.company_id, entity, meta_tools=False,
                                            run_id=self.run.id)
        self.context = ExecutionContext.for_session(
            vs.company_id, entity, user_id=vs.customer_id, run_id=self.run.id,
            campaign_id=(vs.session_metadata or {}).get("campaign_id"),
        )
        self._resolver = ToolCostResolver(self.db, vs.company_id)  # one price cache per call
        await self.db.commit()

    async def run_calls(self, function_calls: list[dict[str, Any]]) -> list[Any]:
        """Run the model's function calls; log and charge each one."""
        async with self._lock:
            return await self._run_calls(function_calls)

    async def _run_calls(self, function_calls: list[dict[str, Any]]) -> list[Any]:
        from src.ai.step_executor import log_tool_call
        from src.ai.tool_executor import ToolExecutor

        await self._open()
        results = await ToolExecutor.execute_from_function_calls(
            function_calls, extra_context=self.context.as_tool_context(), access=self.access,
        )
        if self.run is None:
            return results
        for call, tr in zip(function_calls, results):
            log_tool_call(self.db, self.run.id, self.STEP_NAME, self.access, tr,
                          call.get("args") or {}, tr.latency_ms or 0)
            if tr.success and not tr.skipped:  # a failed or refused call is not billed
                try:
                    charge = await self._resolver.charge(
                        run=self.run, tool_id=tr.tool, latency_ms=tr.latency_ms or 0, units=tr.units)
                    self.cost += charge.amount
                except Exception as exc:                            # noqa: BLE001
                    logger.warning("Could not charge voice tool call %s: %s", tr.tool, exc)
        await self.db.commit()
        return results

    async def finish(self, db: Any, *, error: Optional[str] = None) -> Decimal:
        """Close the call's run with its tool cost; returns that cost.

        ``db`` is the call-end session (the call's own may already be gone).
        """
        if self.run is None:
            return Decimal("0")
        from src.ai.orm import ExecutionRun
        from src.ai.schemas.enums import RunStatus

        now = datetime.utcnow()
        started = self.run.started_at or now
        await db.execute(
            update(ExecutionRun).where(ExecutionRun.id == self.run.id).values(
                status=RunStatus.FAILED if error else RunStatus.COMPLETED,
                error_message=error,
                total_cost_usd=self.cost,
                completed_at=now,
                execution_time_ms=int((now - started).total_seconds() * 1000),
            )
        )
        await db.commit()
        return self.cost
