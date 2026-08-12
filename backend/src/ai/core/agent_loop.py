"""
ai.core.agent_loop — The autonomous control loop (Track 2).

This file is the sole run entry point for every entity. The legacy
``ExecutionEngine.execute_run`` plan-walker it replaced has been deleted
(C4); there is no longer an engine switch.

Per-iteration sequence (mirrors the agent kernel overview, §2):

    perceive → strategize → pre-critic → act → observe →
    post-critic → alignment → supervisor → reflect → decide

Track 2 critic pipeline is the NoOp (Track 3 replaces). The Strategist
is deterministic. The Reflector is deterministic. Output: same
``RunResult`` shape as legacy.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.ai.core.agent_state import (
    Action,
    AgentState,
    PreCriticVerdict,
    Verdicts,
)
from src.ai.core.agent_loop_sse import event_async, set_sse_redis
from src.ai.core.budget import Budget
from src.ai.core.executors import get_executor  # noqa: F401 — triggers registry side-effects
from src.ai.core.executors.base import ActionResult
from src.ai.core.feature_flags import FeatureFlags
from src.ai.core.observer import Observer
from src.ai.core.perceiver import Perceiver
from src.ai.core.reflector import Reflector
from src.ai.core.strategist import Strategist
from src.ai.core.step_results import record_step_result, record_child_step_result
from src.ai.core.trace import current_recorder, span
from src.ai.orm.execution import ExecutionRun
from src.ai.planning.critic_pipeline import (
    CriticPipeline,
    NoOpCriticPipeline,
    RealCriticPipeline,
)
from src.ai.planning.retry_strategies import (
    RetryDecision,
    RetryExecutor,
    RetryStrategy,
    pick_retry,
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


class AgentLoop:
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
        self.perceiver: Optional[Perceiver] = None
        self.strategist: Optional[Strategist] = None
        self.observer: Optional[Observer] = None
        self.reflector: Optional[Reflector] = None
        self.cortex: Any = None
        self._entity: Any = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self, run_id: UUID) -> dict[str, Any]:
        # Cache the run id and register our redis client so per-iteration
        # events fan out to the ``execution:{run_id}`` SSE channel the
        # frontend ExecutionDetail page subscribes to.
        self._run_id = run_id
        set_sse_redis(self.redis)
        run = await self._reload_run(run_id)
        if not run:
            raise LookupError(f"Run {run_id} not found")
        entity = run.entity
        if not entity:
            raise LookupError(f"Run {run_id} has no entity")

        state = self._bootstrap_state(run, entity)
        self._entity = entity
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

        # Reconcile a plan up front when the loop has none. Without this a
        # dynamic-planning PROCESS/AGENT enters the loop with no plan_steps, the
        # Strategist defaults to SingleStep-with-no-fragment, and the old
        # fallback handed the WHOLE run to ExecutionEngine.execute_run —
        # defeating the loop and re-billing (Phase 11 AgentLoop incident #2).
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
                outcome_status = RunStatus.WAITING_ON_CHILDREN.value
                total_cost = float(state.budget.usd_used)
            else:
                outcome_status = self._final_status(state)
                last_output = self._final_output(state)
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

        # Async child dispatch: suspended waiting on children. Persist the
        # resumable snapshot + WAITING_ON_CHILDREN and return WITHOUT finalizing
        # or settling billing. ``resume_parent_run`` re-enters via ``resume``
        # once the children are terminal.
        if state.suspend_requested and not last_error:
            await self._persist_suspended(run, state)
            return AgentLoopOutcome(
                run_id=str(run_id),
                status=RunStatus.WAITING_ON_CHILDREN.value,
                iterations=state.iteration,
                total_cost_usd=total_cost,
                output="",
                error=None,
            ).to_dict()

        await self._finalize_bandit(state, outcome_status)
        await self._enqueue_dreaming_trigger(state, outcome_status)
        await self._persist_final(run, state, outcome_status, last_error, last_output)
        await self._maybe_resume_parent(run)

        return AgentLoopOutcome(
            run_id=str(run_id),
            status=outcome_status,
            iterations=state.iteration,
            total_cost_usd=total_cost,
            output=last_output,
            error=last_error,
        ).to_dict()

    async def resume(self, run_id: UUID) -> dict[str, Any]:
        """Resume a parent run suspended on async child dispatch.

        Rehydrates ``AgentState`` from the snapshot persisted at suspend, folds
        in terminal child results (marking the child step complete + adding
        child cost), and continues the loop via ``_drive``. If children are
        still pending, re-persists WAITING and returns. A no-op if the run is
        not actually WAITING_ON_CHILDREN (idempotent against duplicate resume
        jobs / legacy children whose parent never suspended).
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

        snapshot = (run.context_state or {}).get("__agent_state_snapshot__")
        if not snapshot:
            logger.error("resume(%s): no AgentState snapshot found; failing run.", run_id)
            await self._persist_final(run, self._bootstrap_state(run, run.entity),
                                      RunStatus.FAILED.value,
                                      "resume: missing AgentState snapshot", "")
            return {"run_id": str(run_id), "status": "FAILED", "resumed": False}

        state = AgentState.restore(snapshot)
        state.redis_client = self.redis
        self._entity = run.entity
        await self._compose(state)

        # Fold terminal children; bail back to WAITING if any are still running.
        all_terminal, any_failed = await self._fold_children(state)
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

        await event_async("agent.loop.resumed", run_id=str(run_id),
                          iteration=state.iteration, any_failed=any_failed)
        return await self._drive(run, state, run_id)

    async def _fold_children(self, state: AgentState) -> tuple[bool, bool]:
        """Reload each awaited child; fold terminal ones into context + budget.

        Returns ``(all_terminal, any_failed)``. Marks the child's parent step
        complete and folds the child output into ``context_state`` so the loop
        advances past it on resume.
        """
        from decimal import Decimal
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
            if step_id:
                state.mark_step_complete(step_id)
                state.context_state[step_id] = output
                record_child_step_result(
                    state, step_id, output, child.get("run_id"),
                )
            # Fold child cost into the parent budget (child billed its own row).
            try:
                state.budget.consume(usd=Decimal(str(child_run.total_cost_usd or 0)),
                                     tokens=int(child_run.total_tokens or 0))
            except Exception:
                pass
            if status in (RunStatus.FAILED.value, RunStatus.CANCELLED.value):
                any_failed = True
        return all_terminal, any_failed

    # ------------------------------------------------------------------
    # Loop body
    # ------------------------------------------------------------------

    async def _loop(self, state: AgentState) -> None:
        while not state.done:
            if state.iteration >= self.max_iterations:
                logger.warning(
                    "AgentLoop hit hard iteration cap (%d); aborting run %s",
                    self.max_iterations, state.run_id,
                )
                state.done = True
                state.next_decision = "ABORT"
                break

            await self._iteration(state)

            # Async child dispatch: the iteration spawned children and asked to
            # suspend. Stop the loop WITHOUT finalizing; ``run`` persists the
            # WAITING snapshot and returns. ``resume`` re-enters here later.
            if state.suspend_requested:
                break

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
        assert self.perceiver is not None
        assert self.strategist is not None
        assert self.observer is not None
        assert self.reflector is not None
        # Cooperative cancellation: re-read the run's status before doing any
        # (billable) work. An operator can stop a spinning run by flipping
        # ExecutionRun.status away from RUNNING via POST /executions/{id}/cancel;
        # we honour it here so the run terminates without killing the worker.
        if await self._check_cancelled(state):
            return

        state.iteration += 1
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

        # 1. Perceive
        perception = await self.perceiver.gather(state)
        state.perception = perception

        # 2. Strategize — drain the retry queue first if present.
        queued = state.retry_queue.pop(0) if state.retry_queue else None
        if queued is not None:
            move = self._move_from_retry(queued, state)
            await event_async(
                "agent.retry.dequeued",
                run_id=str(state.run_id),
                iteration=state.iteration,
                strategy=queued.get("strategy"),
            )
        else:
            move = await self.strategist.next_move(state, perception)
        state.chosen_executor = move.executor

        await event_async(
            "agent.loop.iteration_start",
            run_id=str(state.run_id),
            iteration=state.iteration,
            executor=move.executor,
            budget_pressure=state.budget.pressure,
            open_subgoals=len(state.open_subgoals),
        )

        # 3. Pre-critic
        # Skip the pre-critic for plan-driven moves. A move that dispatches a
        # step from an already-reconciled, invariant-checked plan
        # (SingleStep / ChildEntity / DAG carrying a plan_fragment) must not be
        # second-guessed here: the deterministic Strategist re-proposes the
        # IDENTICAL move every iteration, so a single pre-critic BLOCK becomes 3
        # consecutive blocks → circuit-breaker ABORT with zero work done and $0
        # billed (Phase 11 AgentLoop incident #2 follow-up). The pre-critic still
        # guards open-ended moves (recursive goal expansion, or SingleStep with
        # no concrete fragment), where blocking is actionable.
        if move.plan_fragment:
            pre_verdict = PreCriticVerdict(kind="PASS")
        else:
            pre_verdict = await self.critic_pipeline.pre_action(move, state)
        if pre_verdict.kind == "BLOCK":
            state.consecutive_pre_critic_blocks += 1
            await event_async(
                "agent.loop.pre_critic_block",
                run_id=str(state.run_id),
                iteration=state.iteration,
                concerns=pre_verdict.concerns,
                consecutive=state.consecutive_pre_critic_blocks,
            )
            # Circuit breaker: a move that keeps getting blocked makes no
            # progress, so trip ABORT once we've burned N consecutive blocks
            # rather than spinning to the hard iteration cap. The block still
            # consumed this iteration's budget step (above), so each block also
            # advances the run toward _HARD_MAX_ITERATIONS as a backstop.
            if state.consecutive_pre_critic_blocks >= self.max_consecutive_pre_critic_blocks:
                logger.warning(
                    "AgentLoop tripping pre-critic circuit breaker after %d "
                    "consecutive blocks; aborting run %s",
                    state.consecutive_pre_critic_blocks, state.run_id,
                )
                await event_async(
                    "agent.loop.pre_critic_circuit_break",
                    run_id=str(state.run_id),
                    iteration=state.iteration,
                    consecutive=state.consecutive_pre_critic_blocks,
                    concerns=pre_verdict.concerns,
                )
                state.done = True
                state.next_decision = "ABORT"
            return
        # Move cleared the pre-critic — reset the consecutive-block streak.
        state.consecutive_pre_critic_blocks = 0

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
                action_result: ActionResult = await executor.execute(move, state, self.db)
            except NotImplementedError as exc:
                logger.warning("Stub executor invoked: %s", exc)
                action_result = ActionResult(
                    success=False,
                    error=f"stub: {exc}",
                )
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

        # 5. Observe
        observation = self.observer.parse(action_result, state)
        state.apply_observation(observation)

        # 6. Critics (Track 3: real pipeline by default; NoOp if flag off)
        post = await self.critic_pipeline.post_action(state, observation)
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
        await event_async(
            "agent.critic.alignment",
            run_id=str(state.run_id), iteration=state.iteration,
            aligned=align.aligned, drift=align.drift,
        )
        await event_async(
            "agent.critic.supervisor",
            run_id=str(state.run_id), iteration=state.iteration,
            recommendation=supervise.recommendation, confidence=supervise.confidence,
        )

        # 6.b Pick a retry strategy from the freshly-built health record.
        record = None
        try:
            record = await self.critic_pipeline.finalize_iteration(state)
        except Exception:                                                   # pragma: no cover
            logger.exception("finalize_iteration failed; continuing")

        # This iteration's critic LLM spend. The critic pipeline already wrote
        # attributed ``usage_logs`` rows (``log_llm_response_usage``) but —
        # unlike the planner and the nested actor engine — it never incremented
        # ``run.total_cost_usd``. We fold it into the budget below (step 9) so
        # the final ``_persist_final`` write lands it on ``total_cost_usd``.
        iter_critic_cost = self._critic_cost_from_record(record)

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
            if not RetryExecutor.is_exhausted(state, step_id):
                retry_decision = pick_retry(record, state)
                if retry_decision.strategy not in (RetryStrategy.NONE, RetryStrategy.ABANDON):
                    follow_up = self.retry_executor.build(retry_decision, move, record)
                    if follow_up:
                        state.retry_queue.append(follow_up)
                        state.corrective_retries_used += 1
                        await event_async(
                            "agent.retry.picked",
                            run_id=str(state.run_id), iteration=state.iteration,
                            strategy=retry_decision.strategy.value,
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

        # 9. Bookkeeping: cost + snapshot
        state.budget.consume(
            usd=action_result.cost_usd,
            wall_s=max(action_result.latency_ms // 1000, 0),
        )
        # Reconcile USD with the run's real accumulated cost — the nested
        # engine bills on its own session, so action_result.cost_usd is 0 here
        # and the budget bar would otherwise show $0.
        await self._sync_budget_cost(state)
        # Add this iteration's critic spend on TOP of the just-synced run cost.
        # Order matters: _sync_budget_cost pulls the run's accumulated cost UP
        # into the budget via max(), so adding the critic cost beforehand would
        # be clobbered. Doing it after keeps planner + nested-actor + critic all
        # accounted for. Budget is in-memory, so this survives the
        # _persist_final session reset and lands on total_cost_usd via that
        # final max() write — making settle_billing bill the real amount.
        if iter_critic_cost > 0:
            state.budget.consume(usd=iter_critic_cost)
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
            if key in ("feature_flags", "cortex_tree_id", "subtree_root_id"):
                continue  # internal plumbing, not task input
            state.context_state.setdefault(key, value)

        # Seed a single root subgoal so DONE never triggers prematurely
        # on a goal-only AGENT without subgoals.
        if entity.goal:
            state.add_subgoal(entity.goal[:200], priority=10)

        return state

    async def _compose(self, state: AgentState) -> None:
        # Track 4: classify task once at bootstrap.
        await self._classify_task(state)

        # Track 6: wire a CORTEX tree so the loop persists AgentState
        # snapshots (feeding the /agent_state rail) and the critic pipeline
        # persists StepHealthRecords (feeding the /health_records timeline
        # backfill for finished runs).
        await self._setup_cortex(state)

        # Track 4: optional bandit shared by Strategist + finalize().
        self.bandit = await self._build_bandit(state)
        self.strategist = Strategist(bandit=self.bandit)
        self.observer = Observer()
        self.reflector = Reflector(db=self.db)
        # Perceiver gets the live CORTEX service (None-safe in tests).
        self.perceiver = Perceiver(db=self.db, cortex=self.cortex, memory_assembler=None)

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

    @staticmethod
    def _critic_cost_from_record(record: Any) -> "Decimal":
        """Sum the four critic-stage costs recorded for one iteration.

        ``finalize_iteration`` returns the iteration's ``StepHealthRecord``
        (or ``None`` for the NoOp pipeline). Each critic stage stamps its LLM
        spend onto the record; we total them so the AgentLoop can fold the
        critic's cost into ``total_cost_usd`` (the critic pipeline writes
        ``usage_logs`` rows but never touches the run's cost column).
        """
        from decimal import Decimal
        if record is None:
            return Decimal("0")
        total = Decimal("0")
        for attr in (
            "pre_critic_cost_usd",
            "post_critic_cost_usd",
            "alignment_cost_usd",
            "supervisor_cost_usd",
        ):
            val = getattr(record, attr, None)
            if not val:
                continue
            try:
                total += Decimal(str(val))
            except Exception:                                               # pragma: no cover
                pass
        return total

    async def _sync_budget_cost(self, state: AgentState) -> None:
        """Pull the run's real accumulated cost into the budget so the rail /
        budget bar reflect actual spend (the nested engine bills separately)."""
        if not self._run_id:
            return
        try:
            from decimal import Decimal
            row = (await self.db.execute(
                select(ExecutionRun.total_cost_usd).where(
                    ExecutionRun.id == self._run_id
                )
            )).scalar_one_or_none()
            if row is not None:
                actual = Decimal(str(row))
                if actual > state.budget.usd_used:
                    state.budget.usd_used = actual
        except Exception:                                                   # pragma: no cover
            pass

    async def _sync_budget_tokens(self) -> int:
        """Sum ``total_tokens`` across this run + all descendant child runs.

        Token axis counterpart to ``_sync_budget_cost``: the nested engine bills
        tokens onto the *child* run row, so a delegating parent otherwise reports
        ``total_tokens == 0``. Best-effort — any failure returns 0.
        """
        if not self._run_id:
            return 0
        try:
            from sqlalchemy import text
            total = (await self.db.execute(text(
                "WITH RECURSIVE subtree AS ("
                " SELECT id, total_tokens FROM execution_runs WHERE id = :rid"
                " UNION ALL SELECT c.id, c.total_tokens FROM execution_runs c"
                " JOIN subtree s ON c.parent_run_id = s.id)"
                " SELECT COALESCE(SUM(total_tokens), 0) FROM subtree"
            ), {"rid": str(self._run_id)})).scalar_one_or_none()
            return int(total or 0)
        except Exception:                                                   # pragma: no cover
            return 0

    async def _setup_cortex(self, state: AgentState) -> None:
        """Track 6 completion: attach a CortexService + working root.

        Both ``_snapshot`` and the critic pipeline's ``_persist_record`` are
        gated on ``self.cortex`` and ``state.cortex_working_root_id``; without
        them the AgentState rail and the health-record timeline backfill stay
        empty. Best-effort — any failure simply leaves persistence disabled.
        """
        try:
            from src.ai.memory.cortex_service import CortexService

            cortex = CortexService(db=self.db, company_id=cast(UUID, state.company_id))
            run = await self._reload_run(self._run_id) if self._run_id else None
            input_data = (getattr(run, "input_data", None) or {}) if run else {}

            existing = input_data.get("cortex_tree_id")
            if existing:
                tree, _vp, _ck = await cortex.resume_tree(UUID(str(existing)))
            else:
                task = (
                    input_data.get("input")
                    or getattr(self._entity, "goal", None)
                    or "agent loop run"
                )
                tree = await cortex.create_tree(
                    entity_id=state.entity_id,
                    user_id=getattr(run, "user_id", None) if run else None,
                    task_description=str(task)[:500],
                )
            await self.db.commit()
            self.cortex = cortex
            state.cortex_working_root_id = tree.root_node_id
        except Exception as exc:                                            # noqa: BLE001
            logger.warning(
                "AgentLoop CORTEX setup failed; snapshots/health disabled: %s", exc
            )
            self.cortex = None

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
        }
        return RealCriticPipeline(
            db=self.db,
            llm_router=llm,
            cortex_service=self.cortex,
            intelligence_reader=None,           # wired in Track 6
            config=config,
        )

    def _entity_extras(self) -> Optional[dict[str, Any]]:
        if self._entity is None:
            return None
        if isinstance(self._entity, dict):
            return self._entity.get("metadata_extensions")
        return getattr(self._entity, "metadata_extensions", None)

    async def _flag_or_default(self, key: str, default: bool, state: AgentState) -> bool:
        try:
            return await self.flags.is_on(
                key,
                company_id=state.company_id,
                entity_extras=self._entity_extras(),
            )
        except Exception:                                                   # pragma: no cover
            return default

    async def _ensure_plan(self, state: AgentState) -> None:
        """Reconcile a plan once when the loop has none.

        ``_extract_plan_steps`` only finds steps for entities with a
        pre-existing ``run.dynamic_plan`` or a ``static_plan``. A PROCESS/AGENT
        configured for *dynamic* planning (``static_plan.enabled=False``,
        ``dynamic_planning.enabled=True``) enters the loop with
        ``state.plan_steps == []``. The Strategist then defaults to
        SingleStep-with-no-fragment, which used to hand the entire run to the
        legacy ``execute_run`` (BUG 1). Reconciling here populates
        ``state.plan_steps`` (and persists ``run.dynamic_plan``) so the
        Strategist's plan-driven branch dispatches one ready step per iteration
        — CHILD_ENTITY_INVOCATION steps via ChildEntity, others via SingleStep.

        Best-effort: any failure leaves the loop on its existing (empty) plan;
        a recursive AGENT still expands its goal, and other entities wind down
        via the no-op + iteration cap rather than the old full-run fallback.
        """
        if state.plan_steps:
            return
        entity = self._entity
        if entity is None:
            return
        planning = (getattr(entity, "planning", None) or {})
        static_on = bool((planning.get("static_plan") or {}).get("enabled"))
        dynamic_on = bool((planning.get("dynamic_planning") or {}).get("enabled"))
        # No planning configured at all → leave plan empty (e.g. a goal-only
        # AGENT routed to recursive expansion).
        if not static_on and not dynamic_on:
            return
        try:
            from src.ai.planning.planner_service import PlannerService

            run = await self._reload_run(self._run_id) if self._run_id else None
            if run is None:
                return
            input_data = run.input_data if isinstance(run.input_data, dict) else {}
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

    async def _snapshot(self, state: AgentState) -> None:
        """Persist an AgentState snapshot node each iteration.

        Commits so the ``/agent_state`` rail and any StepHealthRecords written
        earlier in the same iteration become visible live (CortexService.write
        only flushes).
        """
        if self.cortex is None or state.cortex_working_root_id is None:
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
            # Flush any still-pending writes from the final iteration BEFORE
            # reloading. The last loop body may have left uncommitted work on
            # the shared session — e.g. the planner's ``run.total_cost_usd``
            # bump + its ``LLMInteractionLog``, or a critic usage row that a
            # later per-iteration commit would normally have captured. A blind
            # ``rollback()`` here discarded all of it, which is how agent_loop
            # runs ended up with ``$0`` total_cost_usd and ZERO
            # ``llm_interaction_logs`` despite real planner/critic spend (and
            # then ``settle_billing`` short-circuited at $0, leaving
            # ``billed_amount`` NULL). Commit first to persist that work; only
            # if the session is genuinely half-open/errored does the commit
            # raise, in which case we fall back to ``rollback()`` so the
            # subsequent reload still succeeds.
            #
            # After this, reload a fully-populated instance: the passed-in
            # ``run`` has expired attributes, and reading them
            # (e.g. ``run.result_data``) would trigger a synchronous lazy-load
            # on the async session → MissingGreenlet. A fresh SELECT loads
            # every column up front so the writes below are pure in-memory
            # mutations.
            try:
                await self.db.commit()
            except Exception:                                              # pragma: no cover
                try:
                    await self.db.rollback()
                except Exception:
                    pass
            fresh = await self._reload_run(run_id) if run_id else None
            if fresh is None:
                logger.error("Final persist: run %s not found; skipping", run_id)
                return
            fresh.status = status
            fresh.completed_at = datetime.utcnow()
            # Don't clobber the engine-billed cost with the loop's budget — keep
            # whichever is larger (the nested engine bills on its own session).
            fresh.total_cost_usd = Decimal(str(max(
                float(state.budget.usd_used), float(fresh.total_cost_usd or 0)
            )))
            # Roll up tokens from the whole run subtree (child runs bill onto
            # their own rows) so a delegating parent reports the real total.
            synced_tokens = await self._sync_budget_tokens()
            fresh.total_tokens = max(
                int(state.budget.tokens_used or 0),
                int(synced_tokens or 0),
                int(fresh.total_tokens or 0),
            )
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
        await self._settle_billing(fresh)

    async def _settle_billing(self, run: ExecutionRun) -> None:
        """Deduct credits for a finished top-level run (best-effort).

        Mirrors ``ExecutionEngine.execute_run``'s final settlement step.
        ``GovernanceService.settle_billing`` is a no-op for child runs
        (``parent_run_id`` set) and for zero-cost runs, and is idempotent enough
        for a single end-of-run call. Any failure is swallowed — a billing
        hiccup must never crash run finalization.
        """
        try:
            if getattr(run, "parent_run_id", None):
                return  # only top-level runs settle
            from src.ai.governance.governance_service import GovernanceService

            governance = GovernanceService(self.db, self.redis)
            entity_name = getattr(self._entity, "name", "") or ""
            billed = await governance.settle_billing(run, entity_name)
            await event_async(
                "agent.loop.billing_settled",
                run_id=str(self._run_id or getattr(run, "id", None)),
                billed_amount=float(billed or 0),
                total_cost_usd=float(getattr(run, "total_cost_usd", 0) or 0),
            )
        except Exception as exc:                                            # noqa: BLE001
            logger.warning(
                "AgentLoop billing settlement failed for run %s: %s",
                self._run_id, exc,
            )

    async def _persist_suspended(self, run: ExecutionRun, state: AgentState) -> None:
        """Persist a resumable snapshot + WAITING_ON_CHILDREN status.

        Stores ``state.snapshot()`` under ``run.context_state`` so ``resume``
        can rehydrate. Does NOT settle billing — the run hasn't finished.
        """
        run_id = self._run_id or getattr(run, "id", None)
        try:
            try:
                await self.db.commit()
            except Exception:                                              # pragma: no cover
                await self.db.rollback()
            fresh = await self._reload_run(run_id) if run_id else None
            if fresh is None:
                logger.error("Persist-suspended: run %s not found", run_id)
                return
            cs = dict(fresh.context_state or {})
            cs["__agent_state_snapshot__"] = state.snapshot()
            fresh.context_state = cs
            fresh.status = RunStatus.WAITING_ON_CHILDREN.value
            fresh.total_cost_usd = Decimal(str(max(
                float(state.budget.usd_used), float(fresh.total_cost_usd or 0)
            )))
            await self.db.commit()
            await event_async(
                "agent.loop.suspended",
                run_id=str(run_id),
                awaiting=len(state.awaiting_children),
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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _reload_run(self, run_id: UUID) -> Optional[ExecutionRun]:
        result = await self.db.execute(
            select(ExecutionRun)
            .options(selectinload(ExecutionRun.entity))
            .where(ExecutionRun.id == run_id)
        )
        return cast(Optional[ExecutionRun], result.scalar_one_or_none())

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

    async def _classify_task(self, state: AgentState) -> None:
        try:
            from src.ai.memory.task_classifier import TaskClassifier
            v2_enabled = await self._flag_or_default(
                "task_classifier.v2_enabled", False, state,
            )
            classifier = TaskClassifier(
                db=self.db, company_id=state.company_id,
                v2_enabled=v2_enabled,
            )
            task_desc = ""
            entity = self._entity
            if entity is not None:
                task_desc = (
                    getattr(entity, "name", "")
                    or getattr(entity, "goal", "")
                    or ""
                )
            state.task_class = await classifier.classify(
                task_description=task_desc, entity=entity,
            )
            await event_async(
                "agent.task_class.classified",
                run_id=str(state.run_id),
                entity_id=str(state.entity_id) if state.entity_id else None,
                task_class=state.task_class,
                classifier_version="v2" if v2_enabled else "v1",
            )
        except Exception as exc:                                            # noqa: BLE001
            logger.debug("task_class classification fell back to default: %s", exc)
            state.task_class = "general"

    async def _build_bandit(self, state: AgentState) -> Optional[Any]:
        try:
            enabled = await self._flag_or_default("bandit.enabled", True, state)
        except Exception:                                                   # pragma: no cover
            enabled = False
        if not enabled or state.company_id is None:
            return None
        try:
            from src.ai.core.feature_flags import NUMERIC_DEFAULTS
            from src.ai.planning.plan_style_bandit import PlanStyleBandit
            epsilon = float(NUMERIC_DEFAULTS.get("bandit.epsilon", 0.10))
            return PlanStyleBandit(
                db=self.db, company_id=state.company_id, epsilon=epsilon,
            )
        except Exception as exc:                                            # noqa: BLE001
            logger.debug("bandit construction failed; running without bandit: %s", exc)
            return None

    async def _enqueue_dreaming_trigger(self, state: AgentState, status: str) -> None:
        """Phase 11 Track 6 — enqueue an outcome-triggered Dreaming pass.

        Best-effort: silently no-op when the feature flag is off or the
        Arq queue isn't reachable (tests, local runs without Redis).
        """
        try:
            enabled = await self._flag_or_default(
                "memory.dreaming_outcome_trigger", True, state,
            )
        except Exception:                                                   # pragma: no cover
            enabled = False
        if not enabled or state.entity_id is None:
            return
        reason = "success" if status == RunStatus.COMPLETED.value else "failure"
        try:
            from arq.connections import ArqRedis
            redis = self.redis
            if redis is None:
                return
            arq = redis if isinstance(redis, ArqRedis) else ArqRedis(
                getattr(redis, "connection_pool", redis),
            )
            await arq.enqueue_job(
                "dreaming_outcome_trigger",
                str(state.entity_id),
                reason,
                str(state.company_id) if state.company_id else None,
                _queue_name="arq:queue",
            )
            await event_async(
                "agent.dreaming.triggered",
                entity_id=str(state.entity_id),
                reason=reason,
            )
        except Exception as exc:                                            # noqa: BLE001
            logger.debug(f"dreaming_outcome_trigger enqueue skipped: {exc}")

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
            from src.ai.planning.planner_service import PlannerService
            planner = PlannerService(self.db, company_id=cast(UUID, state.company_id))
            new_goal = (
                "\n".join(g.description for g in supervise.proposed_subgoals)
                if supervise and supervise.proposed_subgoals
                else (self._entity_goal_or_blank())
            )
            completed = [
                {"step_id": sid, "name": sid, "output": ""}
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
                goal=new_goal,
            )
            if new_plan:
                state.plan_steps = list(new_plan)
                state.completed_step_ids = set()
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

    async def _finalize_bandit(self, state: AgentState, status: str) -> None:
        if not getattr(self, "bandit", None):
            return
        assert self.bandit is not None
        arms = list(state.chosen_arms_by_iteration)
        if not arms:
            return
        success = status == RunStatus.COMPLETED.value
        per_arm_cost = float(state.budget.usd_used) / max(len(arms), 1)
        # Update each arm once (de-duplicate consecutive identical pulls
        # so a long run dominated by one arm doesn't double-count).
        seen: dict[str, int] = {}
        for arm in arms:
            seen[arm] = seen.get(arm, 0) + 1
        for arm, _pulls in seen.items():
            try:
                st = await self.bandit.update_arm(
                    entity_id=state.entity_id,
                    task_class=state.task_class,
                    arm=arm,
                    success=success,
                    cost_usd=per_arm_cost,
                )
                await event_async(
                    "agent.bandit.arm_updated",
                    entity_id=str(state.entity_id),
                    task_class=state.task_class,
                    arm=arm, success=success,
                    cost_usd=per_arm_cost,
                    new_score=self.bandit.score(st),
                )
            except Exception as exc:                                        # noqa: BLE001
                logger.debug("bandit arm update failed for %s: %s", arm, exc)

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

    @staticmethod
    def _final_status(state: AgentState) -> str:
        # A status set out of band (operator cancellation) wins so the abort
        # below doesn't relabel a CANCELLED run as a generic FAILED.
        if state.external_status:
            return state.external_status
        if state.next_decision == "ABORT":
            return RunStatus.FAILED.value
        if state.next_decision == "PAUSE_HITL":
            return RunStatus.PAUSED.value
        if state.all_subgoals_achieved() or (
            state.has_plan() and not state.plan_ready_steps()
        ):
            return RunStatus.COMPLETED.value
        return RunStatus.PARTIAL_COMPLETE.value

    @staticmethod
    def _final_output(state: AgentState) -> str:
        # Prefer last observation summary, then any context_state['output'].
        if state.last_observation and state.last_observation.summary:
            return state.last_observation.summary
        out = state.context_state.get("output") or state.context_state.get("result")
        return str(out) if out else ""


