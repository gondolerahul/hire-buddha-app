"""gateway/call_spend.py — the model use of a live call, on a run and billed (LP-26).

A video call describes a sampled frame every few seconds with the ``vision``
model. Those calls wrote no ``usage_logs`` row: there was no run to attribute
them to, so every description was free to the tenant. Now the first one opens
a run for the call (the call's agent, channel ``video``), each writes its usage
and interaction rows against it, and the call's end closes the run with the
sum of its rows and settles it like any finished top-level run (TB formula,
credits deducted, billing event).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select, update

logger = logging.getLogger(__name__)

__all__ = ["CallSpend"]


class CallSpend:
    """The run one live call's model calls are billed to."""

    def __init__(self, *, company_id: Any, agent_id: Any, channel: str, session_id: str) -> None:
        self.company_id = UUID(str(company_id))
        self.agent_id = UUID(str(agent_id))
        self.channel = channel
        self.session_id = session_id
        self.run_id: Optional[UUID] = None
        self._lock = asyncio.Lock()   # frames are analysed as concurrent tasks

    async def _open(self, db: Any) -> Optional[UUID]:
        """The call's run, opened by the first model call; ``None`` when the
        agent is not this company's (nothing to bill it to)."""
        async with self._lock:
            if self.run_id is not None:
                return self.run_id
            from src.ai.models import ExecutionRun, HierarchicalEntity
            from src.ai.schemas.enums import RunStatus

            entity = (await db.execute(select(HierarchicalEntity.id).where(
                HierarchicalEntity.id == self.agent_id,
                HierarchicalEntity.company_id == self.company_id,
            ))).scalar_one_or_none()
            if entity is None:
                logger.warning("%s call %s: agent %s is not its company's; its model use has no run",
                               self.channel, self.session_id, self.agent_id)
                return None
            run = ExecutionRun(
                company_id=self.company_id, entity_id=self.agent_id, status=RunStatus.RUNNING,
                started_at=datetime.utcnow(), total_cost_usd=Decimal("0"),
                input_data={"input": f"{self.channel} call", "channel": self.channel,
                            f"{self.channel}_session_id": self.session_id},
            )
            db.add(run)
            await db.commit()
            self.run_id = run.id
            return self.run_id

    async def record(self, db: Any, response: Any, *, attribution: str,
                     system_prompt: str = "", user_prompt: str = "") -> None:
        """Write one model call's usage (and interaction) rows against the call's run."""
        from src.ai.services.attributed_usage import log_llm_response_usage

        run_id = await self._open(db)
        await log_llm_response_usage(db=db, response=response, attribution=attribution,
                                     company_id=self.company_id, run_id=run_id,
                                     system_prompt=system_prompt, user_prompt=user_prompt)

    async def finish(self, db: Any, *, error: Optional[str] = None) -> Decimal:
        """Close the run with the sum of its rows and settle it; returns the
        amount billed. A call that made no model call has nothing to settle."""
        if self.run_id is None:
            return Decimal("0")
        from src.ai.governance.governance_service import GovernanceService
        from src.ai.governance.run_cost import refresh_run_cost
        from src.ai.models import ExecutionRun
        from src.ai.schemas.enums import RunStatus

        await refresh_run_cost(db, self.run_id, commit=False)
        now = datetime.utcnow()
        run = (await db.execute(select(ExecutionRun).where(ExecutionRun.id == self.run_id))).scalar_one()
        started = run.started_at or now
        await db.execute(update(ExecutionRun).where(ExecutionRun.id == self.run_id).values(
            status=RunStatus.FAILED if error else RunStatus.COMPLETED, error_message=error,
            completed_at=now, execution_time_ms=int((now - started).total_seconds() * 1000),
        ))
        await db.commit()
        await db.refresh(run)
        return await GovernanceService(db, None).settle_billing(run, f"{self.channel} call")
