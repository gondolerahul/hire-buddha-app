"""voice/tool_calls.py — a voice call is a run; its tool calls are run like a step's (TL-20, VT-21).

A voice call used to leave no run at all, and its tool calls ran with only a
company and a user in their context: no ``tool_interaction_logs`` row, no
charge. Now the call opens an ``ExecutionRun`` when it connects (the voice
agent, channel ``voice``, HD14) — the handler calls :meth:`VoiceToolCalls.start`
— so every call is in the run reports and the trace viewer. Each tool call is
resolved through the agent's ``ToolAccess``, told who it is for by an
``ExecutionContext``, logged against the run, priced through
``ToolCostResolver`` and traced under the call's span — the same path as a
step's tool call.

Critics and HITL checkpoints do not run on a call (a call cannot pause for an
approval); the builder says so.

The run is not settled on its own: the call-end path charges the call once
(telephony, audio and tools) and writes the call's usage rows on this run, then
:meth:`VoiceToolCalls.finish` closes it with what they add up to.
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
    """The run of one voice call, and its tool calls."""

    STEP_NAME = "voice call"

    def __init__(self, db: Any, voice_session: Any):
        self.db = db
        self.voice_session = voice_session
        self.run: Any = None
        self.access: Any = None
        self.context: Any = None
        self.cost = Decimal("0")
        self._resolver: Any = None
        self._recorder: Any = None
        self._span: Any = None
        # The handler runs each tool-call message as its own task, and they
        # share one AsyncSession: one batch at a time.
        self._lock = asyncio.Lock()

    @property
    def run_id(self) -> Any:
        return self.run.id if self.run is not None else None

    async def start(self) -> None:
        """Open the call's run when the call connects (VT-21)."""
        async with self._lock:
            await self._open()

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
                        "direction": getattr(vs, "direction", None),
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
        await self._open_span(entity)

    async def _open_span(self, entity: Any) -> None:
        """The call's span in the trace viewer; its tool calls nest under it."""
        from src.ai.core.trace import TraceRecorder

        try:
            from src.common.redis_client import shared_redis
            redis: Any = shared_redis()
        except Exception:                                                   # noqa: BLE001
            redis = None
        observability = getattr(entity, "observability", None) or {}
        self._recorder = TraceRecorder(
            self.run.id, company_id=self.voice_session.company_id, redis=redis,
            capture_payloads=bool(observability.get("log_thoughts", True)),
        )
        self._recorder.iteration = 1
        vs = self.voice_session
        self._span = await self._recorder.open(
            "step", self.STEP_NAME, parent_span_id=None, iteration=1,
            payload={"channel": "voice", "voice_session_id": str(vs.id),
                     "direction": getattr(vs, "direction", None),
                     "provider": getattr(vs, "provider", None)},
        )

    async def run_calls(self, function_calls: list[dict[str, Any]]) -> list[Any]:
        """Run the model's function calls; log and charge each one."""
        async with self._lock:
            return await self._run_calls(function_calls)

    async def _run_calls(self, function_calls: list[dict[str, Any]]) -> list[Any]:
        from src.ai.core.trace import _CURRENT_SPAN, set_recorder
        from src.ai.step_executor import log_tool_call
        from src.ai.tool_executor import ToolExecutor

        await self._open()
        with set_recorder(self._recorder):
            token = _CURRENT_SPAN.set(self._span.span_id if self._span is not None else None)
            try:
                results = await ToolExecutor.execute_from_function_calls(
                    function_calls, extra_context=self.context.as_tool_context(), access=self.access,
                )
            finally:
                _CURRENT_SPAN.reset(token)
        if self.run is None:
            return results
        for call, tr in zip(function_calls, results):
            log_tool_call(self.db, self.run.id, self.STEP_NAME, self.access, tr,
                          call.get("args") or {}, tr.latency_ms or 0)
            if tr.success and not tr.skipped:  # a failed or refused call is not billed
                for billed_tool, units in tr.charges():
                    try:
                        charge = await self._resolver.charge(
                            run=self.run, tool_id=billed_tool, latency_ms=tr.latency_ms or 0, units=units)
                        self.cost += charge.amount
                    except Exception as exc:                            # noqa: BLE001
                        logger.warning("Could not charge voice tool call %s: %s", billed_tool, exc)
        await self.db.commit()
        return results

    async def finish(self, db: Any, *, error: Optional[str] = None,
                     billed_amount: Optional[Decimal] = None, tokens: Optional[int] = None,
                     result: Optional[dict[str, Any]] = None) -> Decimal:
        """Close the call's run; returns its cost.

        The cost is what the run's usage rows add up to — its tool calls and,
        once the call-end path has written them on the run, the call's
        telephony and audio. ``tokens`` are the model's, as it reported them
        (a live model's rows are not counted as text tokens). ``db`` is the
        call-end session (the call's own may already be gone).
        """
        if self.run is None:
            return Decimal("0")
        from src.ai.governance.run_cost import run_spend
        from src.ai.orm import ExecutionRun
        from src.ai.schemas.enums import RunStatus

        spend = await run_spend(db, self.run.id)
        now = datetime.utcnow()
        started = self.run.started_at or now
        values: dict[str, Any] = {
            "status": RunStatus.FAILED if error else RunStatus.COMPLETED,
            "error_message": error,
            "total_cost_usd": spend.cost_usd,
            "total_tokens": spend.tokens + (tokens or 0),
            "completed_at": now,
            "execution_time_ms": int((now - started).total_seconds() * 1000),
        }
        if billed_amount is not None:
            values["billed_amount"] = billed_amount
        if result is not None:
            values["result_data"] = result
        await db.execute(update(ExecutionRun).where(ExecutionRun.id == self.run.id).values(**values))
        await db.commit()
        if self._span is not None:
            self._span.set_cost(spend.cost_usd)
            self._span.update(**(result or {}))
            if error:
                self._span.set_error(error)
            try:
                await self._recorder.close(self._span)
            except Exception as exc:                                        # noqa: BLE001
                logger.debug("Voice call span not recorded: %s", exc)
            self._span = None
        return spend.cost_usd
