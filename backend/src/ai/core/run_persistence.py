"""run_persistence.py — how an AgentLoop run's state reaches the database.

Moved out of ``agent_loop.py`` (IN-17, ON-09) so the control loop has room under
its line cap: the per-iteration snapshot, the final and the suspended writes,
the run's spend, the parent resume and the locked reload. ``AgentLoop`` mixes
this in; the attributes below are set by ``AgentLoop.__init__``.
"""
from __future__ import annotations

import logging
from typing import Any, Optional, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.ai.core.agent_loop_sse import event_async
from src.ai.core.agent_state import AgentState
from src.ai.core.credit_guard import CreditGuard
from src.ai.core.stuck_runs import SUSPENDED_AT_KEY, utc_now_iso
from src.ai.orm.execution import ExecutionRun
from src.ai.schemas.enums import RunStatus

logger = logging.getLogger("src.ai.core.agent_loop")


class RunPersistence:
    db: Any
    redis: Any
    cortex: Any
    credits: Optional[CreditGuard]
    _run_id: Optional[UUID]
    _snapshot_each_iteration: bool

    async def _refresh_spend(self, state: AgentState) -> Any:
        """Write the run's spend — its usage rows plus its children's totals —
        onto the run row and set the budget from it (P4.1, AK-02). The loop is
        the only writer of ``total_cost_usd``; spenders only write rows."""
        from src.ai.governance.run_cost import RunSpend, refresh_run_cost
        if not self._run_id:
            return RunSpend(state.budget.usd_used, int(state.budget.tokens_used or 0))
        try:
            spend = await refresh_run_cost(self.db, self._run_id)
        except Exception:                                                   # pragma: no cover
            logger.exception("Run cost refresh failed for run %s", self._run_id)
            await self.db.rollback()
            return RunSpend(state.budget.usd_used, int(state.budget.tokens_used or 0))
        state.budget.usd_used = spend.cost_usd
        state.budget.tokens_used = spend.tokens
        return spend

    async def _spend_for_persist(self, state: AgentState, run_id: Any) -> Any:
        """The run's spend for its final or suspended write. A failing sum must
        not stop the run being finalised: it falls back to the last refreshed
        value (the budget), loudly."""
        from src.ai.governance.run_cost import RunSpend, run_spend
        try:
            return await run_spend(self.db, run_id)
        except Exception:
            logger.exception("Run cost sum failed for run %s; using the last refreshed spend", run_id)
            return RunSpend(state.budget.usd_used, int(state.budget.tokens_used or 0))

    async def _snapshot(self, state: AgentState) -> None:
        """Persist an AgentState snapshot node each iteration.

        Commits so the ``/agent_state`` rail and any StepHealthRecords written
        earlier in the same iteration become visible live (CortexService.write
        only flushes).
        """
        if (
            not self._snapshot_each_iteration
            or self.cortex is None
            or state.cortex_working_root_id is None
        ):
            return
        try:
            await self.cortex.write(
                parent_id=state.cortex_working_root_id,
                node_type="snapshot",
                title=f"🧠 snapshot iter={state.iteration}",
                summary=f"pressure={state.budget.pressure:.2f} "
                        f"subgoals={len(state.open_subgoals)}",
                content=state.snapshot_json(),
                status="complete",
                source_ref={"type": "agent_state_snapshot",
                            "iteration": state.iteration},
            )
            await self.db.commit()
        except Exception:                                                  # pragma: no cover
            await self.db.rollback()
            logger.exception("Snapshot write failed; continuing")

    async def _persist_final(
        self,
        run: ExecutionRun,
        state: AgentState,
        status: str,
        error: Optional[str],
        output: str,
    ) -> None:
        from datetime import datetime
        run_id = self._run_id or getattr(run, "id", None)
        try:
            # Commit the final iteration's pending work (planner cost, its
            # LLM log, critic usage) before reloading — a blind rollback here
            # once lost it all and billed $0 — and fall back to rollback only
            # if the session is broken. Then reload: the passed-in ``run`` has
            # expired attributes, and lazy-loading them raises MissingGreenlet.
            try:
                await self.db.commit()
            except Exception:                                              # pragma: no cover
                try:
                    await self.db.rollback()
                except Exception:
                    pass
            # Locked and re-read: a cancel that landed since the loop's last
            # status check is seen here and keeps the run CANCELLED (DM-17).
            fresh = await self._reload_run(run_id, for_update=True) if run_id else None
            if fresh is None:
                logger.error("Final persist: run %s not found; skipping", run_id)
                return
            fresh.status = status
            fresh.completed_at = datetime.utcnow()
            if fresh.started_at is not None:
                # Wall-clock run time (EP-15): reports, registry search and the
                # run's episode read it; nothing wrote it before.
                fresh.execution_time_ms = max(0, int(
                    (fresh.completed_at - fresh.started_at).total_seconds() * 1000
                ))
            # The run's spend: its usage rows plus its children's totals — the
            # amount settlement bills (AK-02).
            spend = await self._spend_for_persist(state, run_id)
            fresh.total_cost_usd = spend.cost_usd
            fresh.total_tokens = spend.tokens
            state.budget.usd_used = spend.cost_usd
            if state.cortex_tree_id:  # read by retry and refine (EP-29)
                fresh.context_state = {**(fresh.context_state or {}), "__cortex_tree_id__": str(state.cortex_tree_id)}
            if error:
                fresh.error_message = error[:1000]
            # Mirror the legacy engine's result_data shape
            # ({"output", "steps":[...]}) so downstream consumers (the refine
            # flow in service.py reads result_data["steps"]) don't regress when
            # the loop becomes the sole engine. Don't clobber a nested engine's
            # result_data (e.g. a recursive child run set its own).
            if not fresh.result_data and (output or state.step_results):
                result_data: dict[str, Any] = {"output": (output or "")[:8000]}
                if state.step_results:
                    result_data["steps"] = list(state.step_results)
                fresh.result_data = result_data
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            logger.exception("Final persist failed for run %s", run_id)
            return

        # Final billing settlement. The legacy ``execute_run`` used to settle
        # billing for us via the SingleStep full-run fallback; now that the loop
        # drives steps directly and never calls ``execute_run``, the loop owns
        # settlement. Without this, plan-driven agent_loop runs accumulate
        # per-tool/LLM cost on ``run.total_cost_usd`` but never deduct credits.
        # Settling also releases the run's credit hold (BC-06).
        if self.credits is not None:
            await self.credits.settle(fresh)

    async def _persist_suspended(self, run: ExecutionRun, state: AgentState) -> None:
        """Persist a resumable snapshot + WAITING_ON_CHILDREN status, or PAUSED
        when the run waits on a person's decision (GH-07).

        Stores ``state.snapshot()`` under ``run.context_state`` so ``resume``
        can rehydrate. Does NOT settle billing — the run hasn't finished.
        """
        run_id = self._run_id or getattr(run, "id", None)
        try:
            try:
                await self.db.commit()
            except Exception:                                              # pragma: no cover
                await self.db.rollback()
            fresh = await self._reload_run(run_id, for_update=True) if run_id else None
            if fresh is None:
                logger.error("Persist-suspended: run %s not found", run_id)
                return
            cs = dict(fresh.context_state or {})
            cs["__agent_state_snapshot__"] = state.snapshot()
            cs[SUSPENDED_AT_KEY] = utc_now_iso()
            fresh.context_state = cs
            fresh.status = (RunStatus.PAUSED if state.awaiting_approval
                            else RunStatus.WAITING_ON_CHILDREN).value
            spend = await self._spend_for_persist(state, run_id)
            fresh.total_cost_usd = spend.cost_usd
            fresh.total_tokens = spend.tokens
            await self.db.commit()
            await event_async(
                "agent.loop.suspended",
                run_id=str(run_id),
                awaiting=len(state.awaiting_children),
                approval_id=(state.awaiting_approval or {}).get("approval_id"),
            )
        except Exception:
            await self.db.rollback()
            logger.exception("Persist-suspended failed for run %s", run_id)

    async def _maybe_resume_parent(self, run: ExecutionRun) -> None:
        """If this run is a child, enqueue a resume for its parent.

        No-op when there is no parent or no Redis. ``resume_parent_run`` guards
        against parents that aren't actually WAITING (e.g. legacy inline
        children), so an unconditional enqueue here is safe and idempotent.
        """
        parent_id = getattr(run, "parent_run_id", None)
        if not parent_id or self.redis is None:
            return
        try:
            from arq.connections import ArqRedis
            arq_redis = ArqRedis(self.redis.connection_pool)
            await arq_redis.enqueue_job("resume_parent_run", str(parent_id))
            logger.info("Enqueued resume_parent_run for parent %s", parent_id)
        except Exception as exc:                                            # noqa: BLE001
            logger.warning(
                "Failed to enqueue parent resume for %s: %s", parent_id, exc
            )

    async def _reload_run(self, run_id: UUID, *, for_update: bool = False) -> Optional[ExecutionRun]:
        """Load the run with the database's current values.

        ``populate_existing`` overwrites an instance already in the session
        (which ``expire_on_commit=False`` leaves stale), so the status the run
        model's transition guard checks against is the stored one. With
        ``for_update`` the row stays locked until the caller commits, so a
        concurrent cancel cannot slip in between the read and the write.
        """
        stmt = (
            select(ExecutionRun)
            .options(selectinload(ExecutionRun.entity))
            .where(ExecutionRun.id == run_id)
            .execution_options(populate_existing=True)
        )
        if for_update:
            stmt = stmt.with_for_update(of=ExecutionRun)
        result = await self.db.execute(stmt)
        return cast(Optional[ExecutionRun], result.scalar_one_or_none())
