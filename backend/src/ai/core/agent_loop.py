"""
ai.core.agent_loop — The autonomous control loop (Track 2).

This file is the sole run entry point for every entity. The legacy
``ExecutionEngine.execute_run`` plan-walker it replaced has been deleted
(C4); there is no longer an engine switch.

Per-iteration sequence (mirrors the agent kernel overview, §2):

    strategize → pre-critic → act → observe →
    post-critic → alignment → supervisor → reflect → decide

Track 2 critic pipeline is the NoOp (Track 3 replaces). The Strategist
is deterministic. The Reflector is deterministic. Output: same
``RunResult`` shape as legacy.
"""
from __future__ import annotations

import json
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional, cast
from uuid import UUID

from sqlalchemy import select

from src.ai.core.agent_state import (
    Action,
    AgentState,
    PreCriticVerdict,
    Verdicts,
)
from src.ai.core.agent_loop_sse import event_async, flush_batch, iteration_batch, set_sse_redis
from src.ai.core.step_signals import signals_from_state, step_signals
from src.ai.core.budget import Budget
from src.ai.core.credit_guard import CreditGuard
from src.ai.core import approval_pause
from src.ai.core.exceptions import CreditExhaustedError, HITLDecisionError, HITLPending
from src.ai.core.executors import get_executor  # noqa: F401 — triggers registry side-effects
from src.ai.core.executors.base import ActionResult
from src.ai.core.feature_flags import FeatureFlags
from src.ai.core.loop_learning import LoopLearning
from src.ai.core.run_persistence import RunPersistence
from src.ai.core.observer import Observer
from src.ai.core.reflector import Reflector
from src.ai.core.strategist import Strategist
from src.ai.core.step_results import (
    REUSE_OUTPUTS_KEY, record_child_step_result, record_step_result, reuse_step_outputs,
)
from src.ai.core.run_outcome import failed_steps_summary, final_status
from src.ai.governance.output_contract import apply_output_contract

from src.ai.core.stuck_runs import cancel_open_children
from src.ai.core.trace import current_recorder, span
from src.ai.governance.entity_versions import run_entity
from src.ai.orm.execution import ExecutionRun
from src.ai.planning.plan_generator import run_request
from src.ai.planning.critic_pipeline import (
    CriticPipeline,
    NoOpCriticPipeline,
    RealCriticPipeline,
)
from src.ai.planning.retry_strategies import (
    RetryDecision,
    RetryExecutor,
    RetryStrategy,
    backoff_seconds,
    failures_of,
    iteration_cap,
    pick_retry,
    retry_policy,
    with_prompt_hint,
)
from src.ai.schemas.enums import EntityType, RunStatus

logger = logging.getLogger(__name__)

__all__ = ["AgentLoop", "AgentLoopOutcome"]


# Default safety caps — applied if state.budget.iters_max wasn't set.
_HARD_MAX_ITERATIONS = 50

# Circuit breaker: if the pre-critic BLOCKs the Strategist's chosen move this
# many times *in a row*, abort the run. Without this a Strategist that keeps
# proposing a move the critic will always reject (the Phase 11 pre_critic
# livelock: executor=DAG/DAG_PARALLEL while the open subgoal says "stop all
# async/tool/specialist routing") spins until the hard iteration cap, burning
# a critic LLM call every iteration and making no progress.
_MAX_CONSECUTIVE_PRE_CRITIC_BLOCKS = 3


@dataclass
class AgentLoopOutcome:
    run_id: str
    status: str
    iterations: int
    total_cost_usd: float
    output: str
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "iterations": self.iterations,
            "total_cost_usd": self.total_cost_usd,
            "output": self.output,
            "error": self.error,
        }


class AgentLoop(RunPersistence, LoopLearning):
    """The Phase 11 autonomous control loop.

    Construction is cheap; the heavy lifting (CORTEX, memory, critic)
    is composed lazily in ``_compose`` once ``state`` is bootstrapped
    and the entity type is known.
    """

    def __init__(
        self,
        db: Any,
        redis: Any,
        *,
        company_id: Optional[UUID] = None,
        feature_flags: Optional[FeatureFlags] = None,
        critic_pipeline: Optional[CriticPipeline] = None,
        max_iterations: int = _HARD_MAX_ITERATIONS,
        max_consecutive_pre_critic_blocks: int = _MAX_CONSECUTIVE_PRE_CRITIC_BLOCKS,
    ):
        self.db = db
        self.redis = redis
        self.company_id = company_id
        self.flags = feature_flags or FeatureFlags(db)
        self.max_consecutive_pre_critic_blocks = max_consecutive_pre_critic_blocks
        # critic_pipeline argument (if explicit) wins; otherwise the
        # pipeline is constructed lazily in _compose so that we can
        # consult feature flags + entity config.
        self._explicit_critic = critic_pipeline
        self.critic_pipeline: CriticPipeline = critic_pipeline or NoOpCriticPipeline()
        self.max_iterations = max_iterations
        self.retry_executor = RetryExecutor()
        # Cached immutable run id — used by ``_persist_final`` so the final
        # write never has to read an expired ORM attribute (which would
        # trigger a synchronous lazy-load → MissingGreenlet on the async
        # session). Set at the top of ``run()``.
        self._run_id: Optional[UUID] = None

        # Composed lazily once state.entity_type / state.cortex_tree_id known.
        self.strategist: Optional[Strategist] = None
        self.observer: Optional[Observer] = None
        self.reflector: Optional[Reflector] = None
        self.cortex: Any = None
        self.memory: Any = None  # RunMemory; None when memory is off
        self._entity: Any = None
        self.credits: Optional[CreditGuard] = None  # set once the run is loaded
        # ``agent_loop.snapshot_every_iteration``, resolved in ``_compose``.
        self._snapshot_each_iteration = True

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self, run_id: UUID) -> dict[str, Any]:
        # Cache the run id and register our redis client so per-iteration
        # events reach the run's stream (``run_events:{run_id}``) the
        # frontend ExecutionDetail page subscribes to.
        self._run_id = run_id
        set_sse_redis(self.redis)
        run = await self._reload_run(run_id)
        if not run:
            raise LookupError(f"Run {run_id} not found")
        # The version the run was pinned to, not the live row: an edit made
        # after the run was created does not reach it (EP-10).
        entity = await run_entity(self.db, run)
        if not entity:
            raise LookupError(f"Run {run_id} has no entity")

        state = self._bootstrap_state(run, entity)
        self._entity = entity
        # Credit gate + hold, before any billable work (BC-05, BC-06).
        self.credits = CreditGuard(self.db, self.redis, run, entity)
        refusal = await self.credits.admit(state.entity_type.value, self._extract_plan_steps(entity, run))
        if refusal:
            await self._persist_final(run, state, RunStatus.FAILED.value, refusal, "")
            return AgentLoopOutcome(run_id=str(run_id), status=RunStatus.FAILED.value, iterations=0,
                                    total_cost_usd=0.0, output="", error=refusal).to_dict()
        await self._compose(state)

        # Cache redis on a transient state attribute so executor adapters can
        # find it. NOT in context_state — that dict is JSON-serialised into
        # input_data / snapshots / run.context_state, and a live Redis handle
        # there raises "Object of type Redis is not JSON serializable".
        state.redis_client = self.redis

        await event_async("agent.loop.run_start",
                          run_id=str(run_id),
                          entity_id=str(entity.id),
                          entity_type=state.entity_type.value,
                          budget_caps=state.budget.snapshot())

        # Mark run as running.
        try:
            run.status = RunStatus.RUNNING.value
            from datetime import datetime
            run.started_at = datetime.utcnow()
            await self.db.commit()
        except Exception:
            await self.db.rollback()

        # Reconcile a plan up front when the loop has none (see _ensure_plan).
        await self._ensure_plan(state)

        return await self._drive(run, state, run_id)

    async def _drive(self, run: ExecutionRun, state: AgentState, run_id: UUID) -> dict[str, Any]:
        """Run the loop to a terminal state, OR suspend if it dispatched async
        children. Shared by ``run`` (fresh) and ``resume`` (rehydrated)."""
        outcome_status = RunStatus.FAILED.value
        last_error: Optional[str] = None
        last_output = ""
        total_cost = 0.0
        try:
            await self._loop(state)
            if state.suspend_requested:
                outcome_status = (RunStatus.PAUSED if state.awaiting_approval
                                  else RunStatus.WAITING_ON_CHILDREN).value
                total_cost = float(state.budget.usd_used)
            else:
                outcome_status = self._final_status(state)
                last_output = self._final_output(state)
                total_cost = float(state.budget.usd_used)
                if outcome_status in (RunStatus.FAILED.value, RunStatus.CANCELLED.value):
                    last_error = state.abort_reason or failed_steps_summary(state)
                elif outcome_status == RunStatus.PARTIAL_COMPLETE.value and state.failed_steps:
                    last_error = failed_steps_summary(state)
        except CreditExhaustedError as exc:
            # Out of credit mid-run: stop, keep and bill the work done (BC-05).
            outcome_status = RunStatus.PARTIAL_COMPLETE.value
            last_error, last_output = str(exc), self._final_output(state)
            total_cost = float(state.budget.usd_used)
        except Exception as exc:                                           # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            logger.exception("AgentLoop crashed for run %s", run_id)
            outcome_status = RunStatus.FAILED.value
        finally:
            await event_async(
                "agent.loop.run_end",
                run_id=str(run_id),
                outcome=outcome_status,
                iters=state.iteration,
                total_cost_usd=total_cost,
            )

        # Suspended — on children (WAITING_ON_CHILDREN) or on a person's
        # decision (PAUSED, GH-07). Persist the resumable snapshot and return
        # WITHOUT finalizing or settling billing; the hold stays. Children
        # re-enter via ``resume``, a decision via ``resume_after_approval``.
        if state.suspend_requested and not last_error:
            await self._persist_suspended(run, state)
            if state.awaiting_approval:
                await approval_pause.schedule_deadline(run_id, state.awaiting_approval)
            return AgentLoopOutcome(
                run_id=str(run_id),
                status=outcome_status,
                iterations=state.iteration,
                total_cost_usd=total_cost,
                output="",
                error=None,
            ).to_dict()

        await self._finalize_bandit(state, outcome_status)
        await self._persist_final(run, state, outcome_status, last_error, last_output)
        # The finished run becomes an episode before Dreaming is triggered, so
        # the dream it triggers can learn from it.
        from src.ai.memory.run_memory import record_episode
        await record_episode(self.db, run_id, runtime_tree_id=state.cortex_tree_id)
        await self._enqueue_dreaming_trigger(state, outcome_status)
        await self._maybe_resume_parent(run)

        return AgentLoopOutcome(
            run_id=str(run_id),
            status=outcome_status,
            iterations=state.iteration,
            total_cost_usd=total_cost,
            output=last_output,
            error=last_error,
        ).to_dict()

    async def resume(self, run_id: UUID, *, expire_reason: Optional[str] = None) -> dict[str, Any]:
        """Resume a parent run suspended on async child dispatch.

        Rehydrates ``AgentState`` from the snapshot persisted at suspend, folds
        in terminal child results (marking the child step complete + adding
        child cost), and continues the loop via ``_drive``. If children are
        still pending, re-persists WAITING and returns. A no-op if the run is
        not actually WAITING_ON_CHILDREN (idempotent against duplicate resume
        jobs / legacy children whose parent never suspended). With
        ``expire_reason`` (the stuck-run sweeper, AK-03) the children still
        running are cancelled and the run ends FAILED with that reason.
        """
        self._run_id = run_id
        set_sse_redis(self.redis)
        run = await self._reload_run(run_id)
        if not run:
            raise LookupError(f"Run {run_id} not found")
        if str(run.status) != RunStatus.WAITING_ON_CHILDREN.value:
            logger.info(
                "resume(%s): status=%s is not WAITING_ON_CHILDREN; skipping.",
                run_id, run.status,
            )
            return {"run_id": str(run_id), "status": str(run.status), "resumed": False}

        entity = await run_entity(self.db, run)
        snapshot = (run.context_state or {}).get("__agent_state_snapshot__")
        if not snapshot:
            logger.error("resume(%s): no AgentState snapshot found; failing run.", run_id)
            await self._persist_final(run, self._bootstrap_state(run, entity),
                                      RunStatus.FAILED.value,
                                      "resume: missing AgentState snapshot", "")
            return {"run_id": str(run_id), "status": "FAILED", "resumed": False}

        state = AgentState.restore(snapshot)
        state.redis_client = self.redis
        self._entity = entity
        self.credits = CreditGuard(self.db, self.redis, run, entity)  # the hold persists
        await self._compose(state, resumed=True)

        # Fold terminal children; bail back to WAITING if any are still running.
        all_terminal, any_failed = await self._fold_children(state)
        if expire_reason:
            await cancel_open_children(self.db, state, expire_reason)
            all_terminal = any_failed = True
        if not all_terminal:
            await self._persist_suspended(run, state)
            return {"run_id": str(run_id), "status": RunStatus.WAITING_ON_CHILDREN.value,
                    "resumed": False}

        # Children done: clear suspend, transition out of WAITING, continue.
        state.suspend_requested = False
        state.awaiting_children = []
        try:
            run.status = RunStatus.RUNNING.value
            await self.db.commit()
        except Exception:
            await self.db.rollback()

        if any_failed:
            # Mirror the inline path: a failed child fails the parent step.
            state.done = True
            state.next_decision = "ABORT"
            state.abort_reason = expire_reason or ""

        await event_async("agent.loop.resumed", run_id=str(run_id),
                          iteration=state.iteration, from_iteration=state.iteration,
                          any_failed=any_failed)
        return await self._drive(run, state, run_id)

    async def resume_after_approval(self, run_id: UUID) -> dict[str, Any]:
        """Resume a run parked on a HITL approval (GH-07, ``approval_pause``).

        A no-op while the approval is PENDING and its deadline has not passed,
        and for a run that is not parked. Otherwise the run is claimed
        (PAUSED → RUNNING, once) and the decision folded in: APPROVED dispatches
        the checkpoint's step again, REJECTED ends the run CANCELLED and
        TIMEOUT FAILED (GH-25). Past the deadline a PENDING approval is settled
        first — TIMEOUT, or APPROVED when the checkpoint auto-approves.
        """
        self._run_id = run_id
        set_sse_redis(self.redis)
        run = await self._reload_run(run_id)
        if not run:
            raise LookupError(f"Run {run_id} not found")
        snapshot = (run.context_state or {}).get(approval_pause.SNAPSHOT_KEY) or {}
        marker = snapshot.get("awaiting_approval")
        if str(run.status) != RunStatus.PAUSED.value or not marker:
            return {"run_id": str(run_id), "status": str(run.status), "resumed": False}
        decision, notes = await approval_pause.decision_for(self.db, marker)
        if decision == "PENDING" or not await approval_pause.claim(self.db, run_id):
            return {"run_id": str(run_id), "status": RunStatus.PAUSED.value, "resumed": False}

        run = await self._reload_run(run_id)
        assert run is not None
        state = AgentState.restore(snapshot)
        state.redis_client = self.redis
        entity = await run_entity(self.db, run)
        self._entity = entity
        self.credits = CreditGuard(self.db, self.redis, run, entity)  # the hold persists
        await self._compose(state, resumed=True)
        blocked = await approval_pause.take_decision(self.db, state, marker, decision, notes)
        await event_async("agent.loop.resumed_after_approval", run_id=str(run_id),
                          iteration=state.iteration, decision=decision,
                          step_id=marker.get("step_id"))
        if blocked:
            await self._end_on_human_decision(state, blocked)
        return await self._drive(run, state, run_id)

    async def _fold_children(self, state: AgentState) -> tuple[bool, bool]:
        """Reload each awaited child; fold terminal ones into context + budget.

        Returns ``(all_terminal, any_failed)``. Marks the child's parent step
        complete and folds the child output into ``context_state`` so the loop
        advances past it on resume.
        """
        _TERMINAL = {
            RunStatus.COMPLETED.value, RunStatus.FAILED.value,
            RunStatus.PARTIAL_COMPLETE.value, RunStatus.CANCELLED.value,
        }
        all_terminal = True
        any_failed = False
        for child in state.awaiting_children:
            if child.get("status") in _TERMINAL:
                continue  # already folded
            child_run = await self._reload_run(UUID(str(child["run_id"])))
            if child_run is None:
                child["status"] = RunStatus.FAILED.value
                any_failed = True
                continue
            status = str(child_run.status)
            if status not in _TERMINAL:
                all_terminal = False
                continue
            child["status"] = status
            step_id = str(child.get("step_id") or "")
            # Fold output + mark the parent step complete.
            output = ""
            if child_run.result_data:
                output = str(child_run.result_data.get("output", "") or child_run.result_data)
            if step_id and status == RunStatus.FAILED.value and self._retry_child(state, step_id, child_run):
                continue  # reopened: the next move dispatches it again (AK-19)
            if step_id:
                if status in (RunStatus.FAILED.value, RunStatus.CANCELLED.value):
                    state.mark_step_failed(
                        step_id,
                        f"child run {status}: {getattr(child_run, 'error_message', None) or ''}".strip(),
                    )
                else:
                    state.mark_step_complete(step_id)
                state.context_state[step_id] = output
                record_child_step_result(
                    state, step_id, output, child.get("run_id"),
                )
            if status in (RunStatus.FAILED.value, RunStatus.CANCELLED.value):
                any_failed = True
        return all_terminal, any_failed

    @staticmethod
    def _retry_child(state: AgentState, step_id: str, child_run: Any) -> bool:
        """Reopen a child step whose run failed transiently, once (AK-19)."""
        from src.ai.core.executors.child_entity import MAX_CHILD_RETRIES, is_transient_failure
        if not is_transient_failure(str(getattr(child_run, "error_message", None) or "")):
            return False
        if state.child_retries.get(step_id, 0) >= MAX_CHILD_RETRIES:
            return False
        state.child_retries[step_id] = state.child_retries.get(step_id, 0) + 1
        state.completed_step_ids.discard(step_id)
        state.failed_steps.pop(step_id, None)
        logger.info("Child step %s failed transiently; dispatching it again", step_id)
        return True

    # ------------------------------------------------------------------
    # Loop body
    # ------------------------------------------------------------------

    async def _loop(self, state: AgentState) -> None:
        while not state.done:
            cap = iteration_cap(self._entity, len(state.plan_steps), self.max_iterations)  # AK-I8
            if state.iteration >= cap:
                logger.warning(
                    "AgentLoop hit its iteration cap (%d); aborting run %s",
                    cap, state.run_id,
                )
                state.done = True
                state.next_decision = "ABORT"
                break

            async with iteration_batch(state.run_id):          # one SSE message (AK-I9)
                await self._iteration(state)

            # Async child dispatch: the iteration spawned children and asked to
            # suspend. Stop the loop WITHOUT finalizing; ``run`` persists the
            # WAITING snapshot and returns. ``resume`` re-enters here later.
            if state.suspend_requested:
                break

            if self.credits is not None:
                await self.credits.check(state.budget.usd_used)  # CreditExhaustedError

            if state.budget.exhausted():
                await event_async(
                    "agent.loop.budget_exhausted",
                    run_id=str(state.run_id),
                    iteration=state.iteration,
                    dim=state.budget.which_exhausted() or "unknown",
                )
                state.done = True
                state.next_decision = "ABORT"
                break

    async def _iteration(self, state: AgentState) -> None:
        assert self.strategist is not None
        assert self.observer is not None
        assert self.reflector is not None
        # Cooperative cancellation: re-read the run's status before doing any
        # (billable) work. An operator can stop a spinning run by flipping
        # ExecutionRun.status away from RUNNING via POST /executions/{id}/cancel;
        # we honour it here so the run terminates without killing the worker.
        if await self._check_cancelled(state):
            return

        # 2. Strategize — drain the retry queue first if present.
        upcoming = state.iteration + 1
        queued = state.retry_queue.pop(0) if state.retry_queue else None
        if queued is not None:
            move = self._move_from_retry(queued, state)
            await event_async(
                "agent.retry.dequeued",
                run_id=str(state.run_id),
                iteration=upcoming,
                strategy=queued.get("strategy"),
                delay_s=queued.get("delay_s", 0),
            )
            # The entity's retry backoff (PC-07): an immediate retry of a
            # rate-limited call is the one retry sure to fail again.
            if queued.get("delay_s"):
                await asyncio.sleep(float(queued["delay_s"]))
        else:
            move = await self.strategist.next_move(state)

        # 3. Pre-critic — on every move (PC-01). It sees the steps the move
        # would run, so its verdict is about them: a BLOCK does not run them
        # and marks them failed with its concerns, so the Strategist proposes
        # the next ready step instead of the same move again (the old reason
        # to skip plan moves); a REVISE runs them with its concerns as their
        # correction (PC-02). A block takes no iteration and no budget step,
        # only the critic's own call (AK-16).
        pre_verdict = await self.critic_pipeline.pre_action(move, state)
        if pre_verdict.kind == "BLOCK":
            state.consecutive_pre_critic_blocks += 1
            blocked = self._fail_blocked_steps(state, move, pre_verdict.concerns)
            await event_async(
                "agent.loop.pre_critic_block",
                run_id=str(state.run_id),
                iteration=upcoming,
                concerns=pre_verdict.concerns,
                consecutive=state.consecutive_pre_critic_blocks,
                blocked_steps=blocked,
            )
            # Circuit breaker: moves that keep getting blocked make no
            # progress, so ABORT after N in a row.
            if state.consecutive_pre_critic_blocks >= self.max_consecutive_pre_critic_blocks:
                logger.warning(
                    "AgentLoop tripping pre-critic circuit breaker after %d "
                    "consecutive blocks; aborting run %s",
                    state.consecutive_pre_critic_blocks, state.run_id,
                )
                await event_async(
                    "agent.loop.pre_critic_circuit_break",
                    run_id=str(state.run_id),
                    iteration=upcoming,
                    consecutive=state.consecutive_pre_critic_blocks,
                    concerns=pre_verdict.concerns,
                )
                state.done = True
                state.next_decision = "ABORT"
            elif blocked:
                # The blocked steps are settled (failed): the plan may be done.
                state.apply_decision(self.strategist.decide_next(state))
            return
        # Move cleared the pre-critic — reset the consecutive-block streak.
        state.consecutive_pre_critic_blocks = 0
        if pre_verdict.kind == "REVISE" and pre_verdict.concerns and move.plan_fragment:
            move.plan_fragment = with_prompt_hint(
                move.plan_fragment, "The pre-action review asks: " + "; ".join(pre_verdict.concerns))
        # The alignment critic's steer from the last iteration (PC-03), once.
        if state.pending_correction and move.plan_fragment:
            move.plan_fragment = with_prompt_hint(
                move.plan_fragment, "The run is drifting from its goal: " + state.pending_correction)
            await event_async("agent.loop.correction_applied", run_id=str(state.run_id),
                              iteration=upcoming, correction=state.pending_correction[:500])
            state.pending_correction = ""

        state.iteration = upcoming
        # Tag spans opened this iteration with the iteration number.
        _rec = current_recorder()
        if _rec is not None:
            _rec.iteration = state.iteration
        state.budget.consume(iter_step=True)
        if state.budget.pressure > 0.5:
            await event_async(
                "agent.loop.budget_pressure",
                run_id=str(state.run_id),
                iteration=state.iteration,
                pressure=state.budget.pressure,
            )
        state.chosen_executor = move.executor

        await event_async(
            "agent.loop.iteration_start",
            run_id=str(state.run_id),
            iteration=state.iteration,
            executor=move.executor,
            budget_pressure=state.budget.pressure,
            open_subgoals=len(state.open_subgoals),
        )

        # 4. Act
        try:
            executor = get_executor(move.executor)
        except LookupError as exc:
            logger.error("AgentLoop missing executor: %s", exc)
            return

        await event_async(
            "agent.executor.invoked",
            run_id=str(state.run_id),
            iteration=state.iteration,
            executor=move.executor,
            plan_size=len(move.plan_fragment or []),
        )
        await flush_batch()  # the browser sees the iteration start before the step ends
        start = time.time()
        # Executor span — parent of the step/tool/LLM spans opened deeper in the
        # stack (they inherit it via the trace ContextVar). No-op if unbound.
        async with span(
            "executor", move.executor,
            iteration=state.iteration,
            rationale=getattr(move, "rationale", None),
            plan_size=len(move.plan_fragment or []),
        ) as _exec_span:
            try:
                # Every executor on its own session (AK-18): a step that commits
                # (a child run, a plan, a bill) cannot corrupt the loop's session.
                from src.common.database import AsyncSessionLocal
                async with AsyncSessionLocal() as exec_db:
                    with step_signals(signals_from_state(state)):   # typed, not dict keys (AK-21)
                        action_result: ActionResult = await executor.execute(move, state, exec_db)
            except HITLPending as pending:
                # An executor that let a waiting checkpoint through: park all the same.
                action_result = ActionResult(success=True, awaiting_approval=pending.marker(),
                                             latency_ms=int((time.time() - start) * 1000))
            except HITLDecisionError as human:
                action_result = ActionResult(
                    success=False, error=str(human), latency_ms=int((time.time() - start) * 1000),
                    blocked={"kind": human.kind, "reason": human.reason, "step_id": ""})
            except Exception as exc:                                       # noqa: BLE001
                action_result = ActionResult(
                    success=False,
                    error=f"{type(exc).__name__}: {exc}",
                    latency_ms=int((time.time() - start) * 1000),
                )
            _exec_span.set_cost(action_result.cost_usd)
            _exec_span.update(success=action_result.success,
                              output=action_result.output or None)
            if not action_result.success and action_result.error:
                _exec_span.set_error(action_result.error)

        await event_async(
            "agent.executor.completed",
            run_id=str(state.run_id),
            iteration=state.iteration,
            executor=move.executor,
            success=action_result.success,
            cost_usd=float(action_result.cost_usd),
            latency_ms=action_result.latency_ms,
        )

        # Async child dispatch: the executor spawned child run(s) as isolated
        # jobs instead of running them inline. Record them, request SUSPEND, and
        # end the iteration here — the loop snapshots + sets WAITING_ON_CHILDREN
        # and releases the worker. The child step is NOT marked complete yet; it
        # completes on resume once the child is terminal (``resume``).
        if action_result.awaiting_children:
            state.awaiting_children.extend(action_result.awaiting_children)
            state.suspend_requested = True
            state.last_action = Action(
                iteration=state.iteration,
                executor=move.executor,
                move_id=move.move_id,
                payload={"awaiting_children": len(action_result.awaiting_children)},
            )
            await event_async(
                "agent.loop.suspended_on_children",
                run_id=str(state.run_id),
                iteration=state.iteration,
                children=[c.get("run_id") for c in action_result.awaiting_children],
            )
            return

        state.last_action = Action(
            iteration=state.iteration,
            executor=move.executor,
            move_id=move.move_id,
            payload={"plan_fragment_len": len(move.plan_fragment or [])},
        )
        for sid in action_result.completed_step_ids:
            state.mark_step_complete(sid)
            record_step_result(state, move, sid, action_result)
        for sid, err in action_result.failed_steps.items():
            state.mark_step_failed(sid, err)
            record_step_result(state, move, sid, action_result, error=err)

        # A checkpoint waits for a person (GH-07): park the run PAUSED and give
        # the worker back. The decision resumes it (``resume_after_approval``).
        if action_result.awaiting_approval:
            marker = action_result.awaiting_approval
            approval_pause.park(state, move, action_result.completed_step_ids,
                                action_result.failed_steps, marker)
            await event_async("agent.loop.paused_on_approval", run_id=str(state.run_id),
                              iteration=state.iteration, approval_id=marker.get("approval_id"),
                              trigger=marker.get("trigger"), step_id=marker.get("step_id"))
            return

        # 5. Observe
        observation = self.observer.parse(action_result, state)
        state.apply_observation(observation)

        # A person's decision ends the run here (GH-25, HD7): no critic judges
        # it and no retry asks the reviewer again.
        if action_result.blocked:
            await self._end_on_human_decision(state, action_result.blocked)
            return

        # 6. Critics (Track 3: real pipeline by default; NoOp if flag off)
        post = await self.critic_pipeline.post_action(state, observation)
        # The run's final output must fit io_contract.output_schema (EP-05).
        post = await apply_output_contract(self.critic_pipeline, self._entity, state, observation, post)
        align = await self.critic_pipeline.alignment(state, observation)
        supervise = await self.critic_pipeline.supervisor(state)
        verdicts = Verdicts(pre=pre_verdict, post=post, align=align, supervise=supervise)

        # Emit critic verdict events for SSE consumers.
        await event_async(
            "agent.critic.pre_verdict",
            run_id=str(state.run_id), iteration=state.iteration,
            verdict=pre_verdict.kind, concerns_count=len(pre_verdict.concerns),
            cost_usd=float(pre_verdict.cost_usd),
        )
        await event_async(
            "agent.critic.post_verdict",
            run_id=str(state.run_id), iteration=state.iteration,
            verdict=post.kind, tags=[t.value for t in post.tags],
            cost_usd=float(post.cost_usd),
        )
        # Drift steers the next step (PC-03): the hint was paid for and dropped.
        if not align.aligned and align.correction_hint:
            state.pending_correction = align.correction_hint
        await event_async(
            "agent.critic.alignment",
            run_id=str(state.run_id), iteration=state.iteration,
            aligned=align.aligned, drift=align.drift, cost_usd=float(align.cost_usd),
            correction=align.correction_hint if not align.aligned else "",
        )
        await event_async(
            "agent.critic.supervisor",
            run_id=str(state.run_id), iteration=state.iteration,
            recommendation=supervise.recommendation, confidence=supervise.confidence,
        )

        # The bandit's pull is judged by this iteration alone (PC-21).
        if move.bandit_arm:
            state.bandit_pulls.append({
                "arm": move.bandit_arm, "iteration": state.iteration,
                "success": observation.outcome == "success" and post.kind == "PASS",
                "cost_usd": float(action_result.cost_usd),
            })

        # 6.b Pick a retry strategy from the freshly-built health record.
        record = None
        try:
            record = await self.critic_pipeline.finalize_iteration(state)
        except Exception:                                                   # pragma: no cover
            logger.exception("finalize_iteration failed; continuing")

        # Never auto-retry a whole child-entity invocation. A ChildEntity move
        # runs an ENTIRE sub-agent (its own multi-step plan, often $10+ and
        # many minutes). Re-running it on a post-critic REVISE re-does all that
        # work, usually blows the parent's budget (→ run FAILED even when the
        # re-run finally PASSes), and rarely changes the verdict. The corrective
        # retry mechanism is for cheap single steps, not for re-spawning a whole
        # sub-run. Accept the sub-run's output and let the loop finish.
        _retryable_move = move.executor != "ChildEntity"
        if record is not None and record.is_actionable_failure() and _retryable_move:
            step_id = record.step_id or ""
            policy = retry_policy(self._entity)
            if not RetryExecutor.is_exhausted(state, step_id, max_retries=policy.max_retries):
                retry_decision = pick_retry(record, state)
                if retry_decision.strategy not in (RetryStrategy.NONE, RetryStrategy.ABANDON):
                    follow_up = self.retry_executor.build(retry_decision, move, record)
                    if follow_up:
                        follow_up["delay_s"] = backoff_seconds(policy, failures_of(state, step_id))
                        state.retry_queue.append(follow_up)
                        state.corrective_retries_used += 1
                        await event_async(
                            "agent.retry.picked",
                            run_id=str(state.run_id), iteration=state.iteration,
                            # What the retry really does: a remedy this step
                            # has no means for falls back to a prompt rewrite.
                            strategy=follow_up["strategy"],
                            picked=retry_decision.strategy.value,
                            tags=[t.value for t in record.post_critic_tags],
                        )
            else:
                await event_async(
                    "agent.retry.exhausted",
                    run_id=str(state.run_id), iteration=state.iteration,
                    step_id=step_id,
                )

        # 7. Reflect
        reflection = self.reflector.produce(state, observation, verdicts)
        await self.reflector.persist(reflection, state)
        state.reflections.append(reflection)

        # 8. Decide
        decision = self.strategist.decide_next(state, supervise)
        state.apply_decision(decision)

        # 8.b If supervisor triggered REPLAN, kick the planner.
        if (decision.next_state_patch or {}).get("replan_requested"):
            await self._handle_replan(state, supervise)

        # 9. Bookkeeping: cost + snapshot. The run's spend is the sum of its
        # usage rows (every step, tool, critic and planner call writes one)
        # plus its children's totals; the budget is set from it (AK-02).
        state.budget.consume(wall_s=max(action_result.latency_ms // 1000, 0))
        await self._refresh_spend(state)
        await self._snapshot(state)

        await event_async(
            "agent.loop.iteration_end",
            run_id=str(state.run_id),
            iteration=state.iteration,
            outcome=observation.outcome,
            decision=decision.next,
            cost_iter_usd=float(action_result.cost_usd),
            # Human-readable iteration narrative (review gap #5): the SSE stream
            # carries WHAT happened, not just the status transition.
            narrative=(observation.summary or "")[:500],
            reflection=(reflection.what_didnt or reflection.what_worked or "")[:300],
        )

    # ------------------------------------------------------------------
    # Composition / bootstrap
    # ------------------------------------------------------------------

    def _bootstrap_state(self, run: ExecutionRun, entity: Any) -> AgentState:
        # Entity type
        raw_type = entity.type
        try:
            etype = raw_type if isinstance(raw_type, EntityType) else EntityType(str(raw_type))
        except ValueError:
            etype = EntityType.ACTION

        gov = entity.governance or {}
        budget = Budget.from_governance(
            max_cost_usd=gov.get("max_cost_usd"),
            timeout_ms=gov.get("timeout_ms"),
            max_iters=self.max_iterations,
        )

        # Plan
        plan_steps = self._extract_plan_steps(entity, run)

        state = AgentState(
            run_id=run.id,
            entity_id=entity.id,
            company_id=entity.company_id,
            entity_type=etype,
            budget=budget,
            plan_steps=plan_steps,
        )

        # Seed the run's input into the context so step templates ({{input}})
        # resolve to the user's actual request. Without this the first step has
        # no input and the agent drifts onto stale episodic memory.
        run_input = run.input_data if isinstance(run.input_data, dict) else {}
        for key, value in run_input.items():
            if key in ("feature_flags", "cortex_tree_id", "subtree_root_id", REUSE_OUTPUTS_KEY, "__skip_steps__",
                       "subjects"):
                continue  # internal plumbing, not task input (subjects reach the prompt as refs)
            state.context_state.setdefault(key, value)
        # A retry or refine carries the steps it does not need to run again.
        reuse_step_outputs(state, run_input.get(REUSE_OUTPUTS_KEY))

        # Seed a single root subgoal so DONE never triggers prematurely
        # on a goal-only AGENT without subgoals.
        if entity.goal:
            state.add_subgoal(entity.goal[:200], priority=10)

        return state

    async def _compose(self, state: AgentState, *, resumed: bool = False) -> None:
        # Track 4: classify task once at bootstrap.
        await self._classify_task(state)

        # Track 6: wire a CORTEX tree so the loop persists AgentState
        # snapshots (feeding the /agent_state rail) and the critic pipeline
        # persists StepHealthRecords (feeding the /health_records timeline
        # backfill for finished runs). ``_snapshot`` and the critic's
        # ``_persist_record`` are gated on ``self.cortex`` + the working root.
        from src.ai.memory.run_memory import assemble_run_memory, open_run_tree
        self.cortex, tree = await open_run_tree(self.db, state, self._entity, self._run_id)
        if tree is not None:
            state.cortex_tree_id = tree.id
            state.cortex_working_root_id = tree.root_node_id
            # Children and retries share the tree through this key (EP-29).
            state.context_state["__cortex_tree_id__"] = str(tree.id)

        # The memory read path — what past runs learned reaches this one.
        self.memory = await assemble_run_memory(
            self.db, state, entity=self._entity, runtime_tree=tree, resumed=resumed,
        )

        # The run's subjects (TL-09) and the entity's failure patterns (PC-12),
        # computed once and shown in every step prompt beside memory.
        from src.ai.core.run_blocks import add_run_blocks
        await add_run_blocks(self.db, state, self._run_id)

        self._snapshot_each_iteration = await self._flag_or_default(
            "agent_loop.snapshot_every_iteration", True, state,
        )

        # Track 4: optional bandit shared by Strategist + finalize().
        self.bandit = await self._build_bandit(state)
        from src.ai.governance.composition import max_concurrent_children
        self.strategist = Strategist(bandit=self.bandit, max_concurrent_children=max_concurrent_children(
            getattr(self._entity, "governance", None)))
        self.observer = Observer()
        self.reflector = Reflector(db=self.db)

        # ── CriticPipeline (Track 3) ──────────────────────────────────
        # If the constructor was given an explicit pipeline, keep it.
        if self._explicit_critic is not None:
            return

        try:
            enabled = await self.flags.is_on(
                "critic_pipeline.v2_enabled",
                company_id=state.company_id,
                entity_extras=self._entity_extras(),
            )
        except Exception:                                                   # pragma: no cover
            enabled = False
        if not enabled:
            return

        try:
            self.critic_pipeline = await self._build_real_critic_pipeline(state)
        except Exception as exc:                                            # noqa: BLE001
            logger.warning("Failed to build RealCriticPipeline; using NoOp: %s", exc)
            self.critic_pipeline = NoOpCriticPipeline()

    async def _build_real_critic_pipeline(self, state: AgentState) -> CriticPipeline:
        from src.ai.llm.router import LLMRouter
        llm = LLMRouter(db=self.db, company_id=state.company_id) if state.company_id else None
        if llm is None:
            return NoOpCriticPipeline()

        entity = self._entity or {}
        gov = (getattr(entity, "governance", None) or {}) if not isinstance(entity, dict) else (entity.get("governance") or {})
        logic = (getattr(entity, "logic_gate", None) or {}) if not isinstance(entity, dict) else (entity.get("logic_gate") or {})
        review = (logic.get("review_mechanism") if isinstance(logic, dict) else {}) or {}
        prompts = (getattr(entity, "prompts", None) or {}) if not isinstance(entity, dict) else (entity.get("prompts") or {})

        config = {
            "critic_model_override": review.get("critic_model_override"),
            "company_critic_override": None,        # Track 8 wires IntegrationRegistry lookup.
            "actor_model_hint": (prompts or {}).get("model_override"),
            "critic_cost_share_pct": float(gov.get("critic_cost_share_pct", 0.20)),
            "goal_validation_interval": int(gov.get("goal_validation_interval", 2)),
            "meta_review_interval": int(gov.get("meta_review_interval", 3)),
            "entity_goal": getattr(entity, "goal", "") or "",
            "task_description": getattr(entity, "name", "") or "",
            "enable_pre_critic": await self._flag_or_default(
                "critic_pipeline.pre_critic_enabled", True, state,
            ),
            "enable_different_model": await self._flag_or_default(
                "critic_pipeline.different_model_critic", True, state,
            ),
            "calibration_note": await self._calibration_note(state),
        }
        return RealCriticPipeline(
            db=self.db,
            llm_router=llm,
            cortex_service=self.cortex,
            intelligence_reader=self.memory,
            config=config,
        )

    async def _calibration_note(self, state: AgentState) -> str:
        """What the weekly calibration found about this entity's critic for
        the run's task class (PC-22); "" when there is nothing to say."""
        try:
            from src.ai.planning.critic_calibration import calibration_note
            return await calibration_note(self.db, state.company_id, state.entity_id, state.task_class)
        except Exception as exc:                                            # noqa: BLE001
            logger.debug("calibration note unavailable: %s", exc)
            return ""

    async def _ensure_plan(self, state: AgentState) -> None:
        """Reconcile a plan once when the loop has none — every level (R1).

        ``_extract_plan_steps`` only finds steps in a pre-existing
        ``run.dynamic_plan`` or a ``static_plan``. ``PlannerService.reconcile``
        resolves the rest the same way at every level: a dynamic plan,
        delegation to children, or one default step. Reconciling here populates
        ``state.plan_steps`` (and persists ``run.dynamic_plan``) so the
        Strategist's plan-driven branch dispatches one ready step per iteration
        — CHILD_ENTITY_INVOCATION steps via ChildEntity, others via SingleStep.

        Best-effort: on a failure the plan stays empty and the Strategist sends
        the run to the Recursive executor, which plans again or fails the run.
        """
        if state.plan_steps:
            return
        entity = self._entity
        if entity is None:
            return
        try:
            from src.ai.planning.planner_service import PlannerService

            run = await self._reload_run(self._run_id) if self._run_id else None
            if run is None:
                return
            input_data = run.input_data if isinstance(run.input_data, dict) else {}
            # Learned rules shape the plan (PlanContext.intelligence_rules).
            rules = state.context_state.get("__intelligence_rules__")
            if rules:
                input_data = {**input_data, "__intelligence_rules__": rules}
            planner = PlannerService(self.db, company_id=cast(UUID, state.company_id))
            plan = await planner.reconcile(run, entity, input_data)
            steps = plan.get("steps") if isinstance(plan, dict) else None
            if steps:
                state.plan_steps = list(steps)
                run.dynamic_plan = plan
                await self.db.commit()
                await event_async(
                    "agent.loop.plan_reconciled",
                    run_id=str(state.run_id),
                    steps=len(steps),
                )
        except Exception as exc:                                            # noqa: BLE001
            logger.warning(
                "AgentLoop plan reconciliation failed; continuing without a "
                "pre-reconciled plan: %s", exc,
            )
            try:
                await self.db.rollback()
            except Exception:                                              # pragma: no cover
                pass

    @staticmethod
    def _extract_plan_steps(entity: Any, run: ExecutionRun) -> list[dict[str, Any]]:
        # Prefer run.dynamic_plan (post-planning); fall back to static.
        dp = run.dynamic_plan
        if isinstance(dp, dict) and isinstance(dp.get("steps"), list):
            return list(dp["steps"])
        planning = entity.planning or {}
        if isinstance(planning, dict):
            sp = planning.get("static_plan") or {}
            steps = sp.get("steps") if isinstance(sp, dict) else None
            if isinstance(steps, list):
                return list(steps)
        return []

    # ------------------------------------------------------------------
    # Snapshot + persistence
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _check_cancelled(self, state: AgentState) -> bool:
        """Re-read the run's status; if it is no longer RUNNING (an operator
        cancelled it, or it was otherwise moved to a terminal state out of
        band), flag the loop to ABORT and return True.

        A fresh SELECT is used (rather than reading the cached ORM instance,
        whose attributes expire after each per-iteration commit and would
        trigger a synchronous lazy-load → MissingGreenlet on the async
        session). Any lookup failure is swallowed — cancellation is
        best-effort and must never crash a healthy run.
        """
        if not self._run_id:
            return False
        try:
            status = (await self.db.execute(
                select(ExecutionRun.status).where(ExecutionRun.id == self._run_id)
            )).scalar_one_or_none()
        except Exception:                                                   # pragma: no cover
            return False
        # ``status`` is the scalar column value under real SQLAlchemy. Under the
        # unit-test fake DB (which echoes the whole run object) fall back to its
        # ``.status`` attribute so the check still reads the live value.
        if status is not None and not isinstance(status, str):
            status = getattr(status, "status", None)
        if status is None or str(status) == RunStatus.RUNNING.value:
            return False
        state.external_status = str(status)
        state.done = True
        state.next_decision = "ABORT"
        await event_async(
            "agent.loop.cancelled",
            run_id=str(state.run_id),
            iteration=state.iteration,
            status=str(status),
        )
        logger.info("AgentLoop run %s cancelled (status=%s); aborting", self._run_id, status)
        return True

    # ------------------------------------------------------------------
    # Track 4 — task classification + bandit composition + finalize
    # ------------------------------------------------------------------

    async def _handle_replan(
        self, state: AgentState, supervise: Any,
    ) -> None:
        """Invoke PlannerService.adapt_plan with supervisor's proposed subgoals.

        No-op for STATIC-plan entities (``dynamic_planning.enabled == False``):
        their deterministic plan is authoritative and must NOT be regenerated.
        Without this guard a supervisor that recommends REPLAN every iteration
        (e.g. because an early planning/THOUGHT step produces no artifact yet)
        would replace ``plan_steps`` with a freshly-generated dynamic plan AND
        reset ``completed_step_ids`` — wiping all progress each iteration, so the
        run spins re-running step 1 forever and never advances to generate/
        validate/finalize (the doc-factory-lite infinite-planning-loop incident).
        """
        planning = (getattr(self._entity, "planning", None) or {})
        if isinstance(planning, dict):
            static_on = bool((planning.get("static_plan") or {}).get("enabled"))
            dynamic_on = bool((planning.get("dynamic_planning") or {}).get("enabled"))
            if static_on and not dynamic_on:
                await event_async(
                    "agent.replan.skipped_static",
                    run_id=str(state.run_id),
                    iteration=state.iteration,
                    reason="static plan is authoritative; not regenerating",
                )
                return
        try:
            from src.ai.planning.planner_service import PlannerService, keep_completed
            planner = PlannerService(self.db, company_id=cast(UUID, state.company_id))
            new_goal = (
                "\n".join(g.description for g in supervise.proposed_subgoals)
                if supervise and supervise.proposed_subgoals
                else (self._entity_goal_or_blank())
            )
            completed = [
                {"step_id": sid, "name": sid, "output": str(state.context_state.get(sid) or "")[:500]}
                for sid in state.completed_step_ids
            ]
            new_plan = await planner.adapt_plan(
                original_plan=state.plan_steps,
                completed_steps=completed,
                failed_step={
                    "name": "supervisor_request",
                    "error": (
                        state.last_observation.summary
                        if state.last_observation else ""
                    ),
                },
                goal=new_goal, request=run_request(state.context_state),
                entity=self._entity, run_id=state.run_id,
            )
            if new_plan:
                # The work already done stays done (PC-09, AK-17): a replan
                # replaces what is left. Before, the completed ids were wiped,
                # so a dynamic plan re-ran and re-paid for its finished steps
                # on every supervisor REPLAN.
                state.plan_steps = keep_completed(state.plan_steps, list(new_plan),
                                                  state.completed_step_ids)
            await event_async(
                "agent.replan.triggered",
                run_id=str(state.run_id),
                iteration=state.iteration,
                by="supervisor",
                proposed_subgoals_count=len(getattr(supervise, "proposed_subgoals", []) or []),
                new_plan_size=len(new_plan) if new_plan else 0,
            )
        except Exception as exc:                                            # noqa: BLE001
            logger.warning("REPLAN failed; continuing with current plan: %s", exc)

    def _entity_goal_or_blank(self) -> str:
        ent = self._entity
        if ent is None:
            return ""
        return getattr(ent, "goal", "") or ""

    async def _end_on_human_decision(self, state: AgentState, blocked: dict[str, str]) -> None:
        """A rejection ends the run CANCELLED with the reviewer's reason; an
        unanswered checkpoint ends it FAILED (HD7)."""
        reason = blocked.get("reason") or "A reviewer stopped the run"
        if blocked.get("kind") == "hitl_rejected":
            state.external_status = RunStatus.CANCELLED.value
        else:
            state.next_decision = "ABORT"
        state.abort_reason = reason
        state.done = True
        await self._refresh_spend(state)
        await self._snapshot(state)
        await event_async("agent.loop.human_decision", run_id=str(state.run_id), iteration=state.iteration,
                          kind=blocked.get("kind"), step_id=blocked.get("step_id"), reason=reason[:500])

    @staticmethod
    def _fail_blocked_steps(state: AgentState, move: Any, concerns: list[str]) -> list[str]:
        """Mark the steps a blocked move would have run as failed (PC-01)."""
        reason = "blocked by the pre-action review: " + ("; ".join(concerns) or "no reason given")
        ids = [str(s.get("step_id") or s.get("id") or "") for s in (move.plan_fragment or [])
               if isinstance(s, dict)]
        for sid in ids:
            if sid:
                state.mark_step_failed(sid, reason[:1000])
        return [sid for sid in ids if sid]

    def _move_from_retry(self, queued: dict[str, Any], state: AgentState) -> Any:
        """Rehydrate a queued retry dict into a Strategist Move."""
        from src.ai.core.strategist import Move
        plan_fragment = queued.get("plan_fragment")
        return Move(
            move_id=str(queued.get("retry_move_id") or queued.get("original_move_id") or ""),
            goal_id=state.current_goal_id(),
            executor=queued.get("executor", "SingleStep"),
            plan_fragment=plan_fragment,
            rationale=queued.get("rationale", "queued retry"),
        )

    _final_status = staticmethod(final_status)

    @staticmethod
    def _final_output(state: AgentState) -> str:
        # The last step's output, whole — not its timeline summary, which
        # stored "[success] " + 160 characters as every run's result and
        # handed that to parents and episodes (PC-27).
        if state.last_observation and state.last_observation.output:
            return state.last_observation.output
        out = state.context_state.get("output") or state.context_state.get("result")
        return str(out) if out else ""


