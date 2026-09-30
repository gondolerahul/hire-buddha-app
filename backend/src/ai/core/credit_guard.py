"""
ai.core.credit_guard — the credit side of one AgentLoop run (BC-05, BC-06).

Three points, all for top-level runs only (a child run spends its parent's
credit, which the parent's guard watches):

* **admit** — before any billable work, the run holds its estimated bill.
  A company with less than the entity type's minimum free (the wallet minus
  other runs' holds) is refused, and the run fails with that reason.
* **check** — after every iteration, the run's bill so far (raw cost through
  the TB formula) is compared with the credit it may spend; at zero the run
  stops with :class:`CreditExhaustedError` and finishes ``PARTIAL_COMPLETE``.
* **settle** — at the end, the run is billed and its hold released.

Before BC-05 none of this ran: ``check_credit_gate`` and
``check_credit_circuit_breaker`` had no callers, so a run started on an empty
wallet ran to completion and was debited only at the end.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select

from src.ai.core.agent_loop_sse import event_async
from src.ai.core.exceptions import CreditExhaustedError
from src.ai.orm.execution import ExecutionRun
from src.billing.credit_service import InsufficientCreditsError

logger = logging.getLogger(__name__)

# How many of the entity's recent finished runs the estimate averages.
_HISTORY_RUNS = 10


class CreditGuard:
    def __init__(self, db: Any, redis: Any, run: ExecutionRun, entity: Any) -> None:
        self.db = db
        self.redis = redis
        # Read once, while the ORM attributes are loaded (reading an expired
        # attribute later would lazy-load on the async session).
        self.run_id = run.id
        self.company_id = run.company_id
        self.top_level = not getattr(run, "parent_run_id", None)
        self.entity = entity

    def _governance(self) -> Any:
        from src.ai.governance.governance_service import GovernanceService
        return GovernanceService(self.db, self.redis)

    def _run_ref(self) -> Any:
        from types import SimpleNamespace
        return SimpleNamespace(id=self.run_id, company_id=self.company_id)

    async def estimate(self, plan_steps: list[Any]) -> Decimal:
        """The run's likely bill: the larger of its plan's estimate and the
        average billed for the entity's last finished top-level runs."""
        from src.ai.planning.cost_estimator import estimate_plan_cost
        from src.billing.billing_service import BillingService, compute_billed_amount

        config = await BillingService(self.db).get_billing_config(self.company_id)
        planned = compute_billed_amount(estimate_plan_cost(plan_steps, self.entity), config)
        recent = (await self.db.execute(
            select(ExecutionRun.billed_amount)
            .where(ExecutionRun.entity_id == getattr(self.entity, "id", None),
                   ExecutionRun.parent_run_id.is_(None),
                   ExecutionRun.billed_amount.isnot(None),
                   ExecutionRun.billed_amount > 0)
            .order_by(ExecutionRun.created_at.desc())
            .limit(_HISTORY_RUNS)
        )).scalars().all()
        history = sum((Decimal(str(b)) for b in recent), Decimal("0")) / len(recent) if recent else Decimal("0")
        return max(planned, history)

    async def admit(self, entity_type: str, plan_steps: list[Any]) -> Optional[str]:
        """Hold the run's estimated bill. Returns the refusal, or None when admitted."""
        if not self.top_level:
            return None
        estimate = await self.estimate(plan_steps)
        try:
            held = await self._governance().check_credit_gate(self._run_ref(), entity_type, estimate)
        except InsufficientCreditsError as exc:
            await event_async("agent.loop.credit_refused", run_id=str(self.run_id), reason=str(exc))
            return str(exc)
        await event_async("agent.loop.credit_hold", run_id=str(self.run_id),
                          held_usd=float(held), estimate_usd=float(estimate))
        return None

    async def check(self, accumulated_cost: Decimal) -> None:
        """Raise CreditExhaustedError once the bill so far uses up the run's credit."""
        if not self.top_level:
            return
        try:
            await self._governance().check_credit_circuit_breaker(self._run_ref(), accumulated_cost)
        except InsufficientCreditsError as exc:
            await event_async("agent.loop.credit_exhausted", run_id=str(self.run_id), reason=str(exc))
            raise CreditExhaustedError(str(exc)) from exc

    async def settle(self, run: ExecutionRun) -> None:
        """Bill a finished top-level run and release its hold (best-effort).

        ``GovernanceService.settle_billing`` is a no-op for child runs and for
        zero-cost runs. Any failure is swallowed — a billing hiccup must never
        crash run finalization.
        """
        if not self.top_level:
            return
        try:
            billed = await self._governance().settle_billing(run, getattr(self.entity, "name", "") or "")
            await event_async(
                "agent.loop.billing_settled",
                run_id=str(self.run_id),
                billed_amount=float(billed or 0),
                total_cost_usd=float(getattr(run, "total_cost_usd", 0) or 0),
            )
        except Exception as exc:                                            # noqa: BLE001
            logger.warning("AgentLoop billing settlement failed for run %s: %s", self.run_id, exc)
