"""
ai.core.step_engine — Per-step execution surface for the AgentLoop.

``StepEngine`` owns everything the loop's executors delegate into: the DAG
step runner, the per-step wrapper (timeout + HITL + budget guard + GoalGuard),
the cost-cap guard, and the CORTEX helper delegators. It deliberately does NOT
own a full-run entry point — driving an entire run is the AgentLoop's job.

The loop's SingleStep / DAG / ChildEntity executors (and the recursive engine)
construct a ``StepEngine`` directly. The legacy ``ExecutionEngine.execute_run``
plan-walker this was extracted from has been deleted (C4); the AgentLoop is the
sole run entry point.
"""
import asyncio
import copy
import json
import logging
import re
from typing import List, Optional, Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.database import AsyncSessionLocal
from src.ai.models import ExecutionRun, HierarchicalEntity
from src.ai.schemas import PlanStep
from src.config.service import ConfigService
from src.ai.usage_service import UsageService
from src.ai.governance.governance_service import GovernanceService
from src.ai.planning.planner_service import PlannerService
from src.ai.memory.cortex_bridge import CortexBridge
from src.ai.step_executor import StepExecutorService
from src.ai.memory.cortex_service import CortexService

from src.ai.core.exceptions import UncertaintySignal, BudgetExhaustedError
from src.ai.core.context_utils import store_step_output

logger = logging.getLogger(__name__)

# Alias for backward compat within the class body
_store_step_output = store_step_output


class StepEngine:
    def __init__(self, db: AsyncSession, redis_pool: Any, company_id: Optional[UUID] = None) -> None:
        self.db = db
        self.redis = redis_pool
        self.config_service = ConfigService(db)
        self.usage_service = UsageService(db)
        # Composed services (initialized when company_id is known).
        self.company_id = company_id
        self._governance = GovernanceService(db, redis_pool) if company_id else None
        self._planner = PlannerService(db, company_id) if company_id else None
        self._cortex_bridge = CortexBridge(db, company_id, self.usage_service, redis=redis_pool) if company_id else None
        self._step_executor = StepExecutorService(
            db, redis_pool, company_id, self.usage_service,
            cortex_bridge=self._cortex_bridge,
            governance=self._governance,
        ) if company_id else None

    def _ensure_services(self, company_id: UUID) -> None:
        """Lazily initialize services when company_id becomes available."""
        if not self._governance:
            self.company_id = company_id
            self._governance = GovernanceService(self.db, self.redis)
            self._planner = PlannerService(self.db, company_id)
            self._cortex_bridge = CortexBridge(self.db, company_id, self.usage_service, redis=self.redis)
            self._step_executor = StepExecutorService(
                self.db, self.redis, company_id, self.usage_service,
                cortex_bridge=self._cortex_bridge,
                governance=self._governance,
            )

    async def _execute_steps_dag(self, run: Any, entity: Any, steps: List[dict[str, Any]], context_state: dict[str, Any]) -> List[dict[str, Any]]:
        """Execute steps respecting dependencies, parallelizing independent ones.

        P1-A: Parallel steps each open their own AsyncSession to avoid
        sharing self.db across concurrent coroutines (which would cause
        PendingRollbackError under SQLAlchemy's asyncio driver).
        The orchestrator-level self.db is retained for status/plan commits.
        """

        # 1. Build Dependency Graph
        step_deps: dict[str, set[str]] = {s["step_id"]: set() for s in steps}
        step_map = {s["step_id"]: s for s in steps}

        for step in steps:
            s_id = step.get("step_id", "")
            target = step.get("target") or {}
            if target and "input_dependencies" in target:
                for dep in target.get("input_dependencies", []):
                     step_deps[s_id].add(dep)

            prompt = target.get("prompt_template", "")
            # prompt_template may be a dict if the LLM planner emitted structured input;
            # coerce to string so the regex can still discover {{step_N}} references.
            if isinstance(prompt, dict):
                prompt = json.dumps(prompt, default=str)
            elif not isinstance(prompt, str):
                prompt = str(prompt) if prompt else ""
            vars_needed = re.findall(r'\{\{(.*?)\}\}', prompt)
            for var in vars_needed:
                base_var = var.split('.')[0]
                if base_var in step_map and base_var != s_id:
                    step_deps[s_id].add(base_var)

        completed = set()
        for s in steps:
            if s["step_id"] in context_state and s["step_id"] != "input":
                completed.add(s["step_id"])

        results_map: dict[str, Any] = {}
        logger.info(f"DAG Execution Plan for {len(steps)} steps. Dependencies: {step_deps}")

        while len(completed) < len(steps):
            ready = []
            for s in steps:
                s_id = s["step_id"]
                if s_id not in completed:
                    deps = step_deps[s_id]
                    if deps.issubset(completed) or not deps:
                        ready.append(s)

            if not ready:
                remaining = [s["step_id"] for s in steps if s["step_id"] not in completed]
                logger.warning(f"Circular dependency or stall detected. Remaining: {remaining}. Switching to sequential for remainder.")
                for s in steps:
                    if s["step_id"] not in completed:
                        step_obj = PlanStep(**s)
                        res = await self._execute_step_wrapper(run, entity, step_obj, context_state)
                        results_map[s["step_id"]] = res
                        completed.add(s["step_id"])
                break

            logger.debug(f"Executing batch: {[s['name'] for s in ready]}")

            if len(ready) == 1:
                # ── Phase 9: Dependency validation before execution ──────
                step_obj = PlanStep(**ready[0])
                _dep_missing = False
                if step_obj.target and step_obj.target.prompt_template:
                    _required = re.findall(r'\{\{(.+?)\}\}', str(step_obj.target.prompt_template))
                    for _var in _required:
                        _base = _var.split('.')[0]
                        # Check if it's a step reference that should be in context
                        if _base.startswith('step_') and _base not in context_state:
                            # Check if the dependent step failed
                            _dep_step_name = step_map.get(_base, {}).get('name', _base)
                            _failed_val = context_state.get(_dep_step_name, '')
                            if str(_failed_val).startswith('[FAILED]') or str(_failed_val).startswith('[TOOL_EMPTY]'):
                                logger.warning(
                                    f"Step '{step_obj.name}' depends on '{_base}' which FAILED. "
                                    f"Skipping step to prevent hallucination."
                                )
                                _dep_error = (
                                    f"[DEPENDENCY_FAILED] Cannot execute '{step_obj.name}': "
                                    f"required data from '{_base}' ({_dep_step_name}) failed. "
                                    f"Failure: {str(_failed_val)[:200]}"
                                )
                                _store_step_output(context_state, step_obj.name, step_obj.step_id or step_obj.name, _dep_error)
                                results_map[ready[0]['step_id']] = {'step': step_obj.name, 'output': _dep_error, 'success': False}
                                completed.add(ready[0]['step_id'])
                                _dep_missing = True
                                break
                # ─────────────────────────────────────────────────────────
                if not _dep_missing:
                    result = await self._execute_step_wrapper(run, entity, step_obj, context_state)
                    results_map[ready[0]["step_id"]] = result
                    completed.add(ready[0]["step_id"])
            else:
                # Multi-step parallel batch: each step gets its own AsyncSession.
                # P1-A: This prevents PendingRollbackError when two coroutines
                # share self.db and one fails mid-transaction.
                # Each step gets a deep-copied context to prevent
                # cross-contamination between parallel coroutines.
                # Pass run_id instead of ORM object; reload in
                # isolated session. Use atomic DB increments for cost/tokens.
                async def _isolated_step(step_dict: dict[str, Any], frozen_ctx: dict[str, Any]) -> dict[str, Any]:
                    async with AsyncSessionLocal() as isolated_db:
                        isolated_engine = StepEngine(isolated_db, self.redis, company_id=self.company_id)
                        step_obj = PlanStep(**step_dict)
                        # Reload run in isolated session to avoid DetachedInstanceError
                        iso_result = await isolated_db.execute(
                            select(ExecutionRun)
                            .options(selectinload(ExecutionRun.entity))
                            .where(ExecutionRun.id == run.id)
                        )
                        iso_run = iso_result.scalar_one()
                        step_result = await isolated_engine._execute_step_wrapper(
                            iso_run, entity, step_obj, frozen_ctx
                        )
                        # Cost/token accounting is owned by StepExecutorService
                        # via _bump_run_cost, which folds each LLM/tool/child
                        # charge into run.total_cost_usd with an ATOMIC
                        # "total_cost_usd = total_cost_usd + delta" UPDATE. That
                        # is concurrency-safe across these parallel isolated
                        # sessions. The previous design merged cost here from
                        # step_result["cost_usd"], but _execute_step never
                        # populated that key, so every parallel step's cost was
                        # silently dropped (the Phase 11 billing leak). A
                        # defensive commit guarantees the final increment is
                        # durable before the isolated session closes.
                        await isolated_db.commit()
                        return step_result

                # Deep-copy context for each parallel step
                tasks = [_isolated_step(s, copy.deepcopy(context_state)) for s in ready]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)

                # ERR-2 fix: Collect ALL results first, then decide whether to raise.
                # Previously, the first failure discarded successful step results.
                failures: list[Any] = []
                for i, batch_result in enumerate(batch_results):
                    step_id = ready[i]["step_id"]
                    if isinstance(batch_result, Exception):
                        logger.error(f"Step {step_id} failed: {batch_result}")
                        results_map[step_id] = {"error": str(batch_result), "step": ready[i]["name"]}
                        _store_step_output(context_state, ready[i]["name"], step_id, f"[FAILED] {batch_result}")
                        failures.append((step_id, batch_result))
                    else:
                        results_map[step_id] = batch_result
                        completed.add(step_id)
                        # Merge results back into parent context
                        if isinstance(batch_result, dict) and "output" in batch_result:
                            _store_step_output(context_state, ready[i]["name"], step_id, batch_result["output"])

                # Refresh run from DB after parallel steps to get accumulated costs
                await self.db.refresh(run)

                if failures:
                    raise failures[0][1]  # Raise first failure after saving all results

        return [results_map.get(s["step_id"], {}) for s in steps]

    async def _enforce_cost_cap(self, run: Any, governance: dict[str, Any]) -> None:
        """Raise ``BudgetExhaustedError`` if the run's accumulated cost has
        reached the entity's ``governance.max_cost_usd``.

        Best-effort lookup: a failure to read the cost must never crash a
        healthy step, so any non-budget exception is swallowed (the run simply
        proceeds without the guard for that step).
        """
        try:
            max_cost = governance.get("max_cost_usd")
        except AttributeError:
            return
        if not max_cost:
            return
        try:
            cap = float(max_cost)
        except (TypeError, ValueError):
            return
        if cap <= 0:
            return
        try:
            spent_raw = (await self.db.execute(
                select(ExecutionRun.total_cost_usd).where(ExecutionRun.id == run.id)
            )).scalar_one_or_none()
        except Exception:
            return  # never let the guard's own lookup break a step
        if spent_raw is None:
            return
        try:
            spent = float(spent_raw)
        except (TypeError, ValueError):
            return
        if spent >= cap:
            raise BudgetExhaustedError(
                f"Run {run.id} reached governance.max_cost_usd "
                f"(spent ${spent:.4f} ≥ cap ${cap:.2f}); stopping further spend.",
                spent_usd=spent,
                cap_usd=cap,
            )

    async def _execute_step_wrapper(self, run: Any, entity: Any, step_obj: Any, context_state: dict[str, Any]) -> dict[str, Any]:
        """Wrapper to handle execution + review + context update for a single step.

        Ph-B: If the LLM raises UncertaintySignal, the step result is annotated
        with needs_clarification=True instead of crashing the run.

        Includes:
        - HITL checkpoint evaluation (BEFORE_STEP, COST_THRESHOLD, TOOL_CALL)
        - Timeout enforcement via asyncio.wait_for
        - Observability-gated logging
        """
        # Entity is detached (make_transient) — safe to access .governance etc.
        # without triggering lazy-load / MissingGreenlet.
        assert self._step_executor is not None
        observability = entity.observability or {}
        log_thoughts = observability.get("log_thoughts", True)
        governance = entity.governance or {}
        timeout_ms = governance.get("timeout_ms", 60000)

        # ── Budget guard: enforce governance.max_cost_usd as a hard stop ─────
        # The legacy run loop otherwise only guards company-wide credits and
        # HITL COST_THRESHOLD checkpoints — never the entity's own per-run cap.
        # That let a child entity (e.g. doc-xlsx-agent, cap $3) run to $15+.
        # We re-read the run's accumulated cost (a fresh scalar SELECT, never a
        # possibly-expired ORM attribute) and abort BEFORE starting the next
        # billable step once the cap is reached. Enforcement is step-granular:
        # the step that crosses the cap finishes; the following step is blocked.
        await self._enforce_cost_cap(run, governance)

        # ── HITL: Evaluate BEFORE_STEP and COST_THRESHOLD checkpoints ───────
        await self._evaluate_hitl_checkpoints(
            run, entity, step_obj, context_state, phase="BEFORE",
            governance_dict=governance
        )

        # ── Execute with timeout enforcement ────────────────────────────────
        try:
            try:
                step_result = await asyncio.wait_for(
                    self._step_executor._execute_step(run, entity, step_obj, context_state),
                    timeout=timeout_ms / 1000.0,
                )
            except asyncio.TimeoutError:
                step_result = {
                    "step": step_obj.name,
                    "step_id": step_obj.step_id,
                    "output": f"[TIMEOUT] Step '{step_obj.name}' exceeded {timeout_ms}ms timeout.",
                    "error": f"Timeout after {timeout_ms}ms",
                }
                logger.warning(f"Step '{step_obj.name}' timed out after {timeout_ms}ms")
                # DATA-2 fix: write failed step to context so it's not re-executed on retry
                _store_step_output(context_state, step_obj.name, step_obj.step_id or step_obj.name, f"[ERROR] Timeout after {timeout_ms}ms")
        except UncertaintySignal as sig:
            if log_thoughts:
                logger.info(f"UncertaintySignal from step '{step_obj.name}': {sig.question}")
            step_result = {
                "step": step_obj.name,
                "output": f"[Clarification needed] {sig.question}",
                "needs_clarification": True,
                "uncertainty_question": sig.question,
                "uncertainty_confidence": sig.confidence,
                "uncertainty_alternatives": sig.alternatives,
            }

        # ── HITL: Evaluate AFTER_STEP checkpoints ───────────────────────────
        await self._evaluate_hitl_checkpoints(
            run, entity, step_obj, context_state, phase="AFTER",
            governance_dict=governance
        )

        # (C1: the legacy v1 self-critique `_review_step_output` is deleted.
        # The AgentLoop is the default path and runs RealCriticPipeline; this
        # deprecated engine no longer does its own per-step review.)

        # ── GoalGuard step-level alignment check ─────────────
        reasoning_cfg = (entity.logic_gate or {}).get("reasoning_config", {})
        goal_interval = reasoning_cfg.get("goal_validation_interval", 0)
        if goal_interval > 0 and entity.goal and isinstance(step_result, dict) and step_result.get("output"):
            step_count = context_state.get("__goal_check_counter__", 0) + 1
            context_state["__goal_check_counter__"] = step_count
            if step_count % goal_interval == 0:
                try:
                    from src.ai.planning.goal_guard import GoalGuard
                    guard = GoalGuard(
                        db=self.db,
                        company_id=run.company_id,
                        entity_goal=entity.goal,
                        task_description=context_state.get("input", ""),
                    )
                    guard_result = await guard.check(
                        step_result=step_result,
                        step_name=step_obj.name,
                        step_idx=step_count,
                        all_results=[],
                        total_steps=0,
                    )
                    if guard_result["action"] == "RETRY":
                        _retry_key = f"__retry_{step_obj.step_id or step_obj.name}__"
                        if not context_state.get(_retry_key):
                            context_state[_retry_key] = True
                            correction = guard_result.get("correction_hint", "")
                            context_state["__alignment_correction__"] = (
                                f"⚠️ GOAL DRIFT: {guard_result['reason']}. "
                                f"Correction: {correction}. "
                                f"Focus STRICTLY on the original goal: {entity.goal}"
                            )
                            logger.info(f"GoalGuard: re-executing step '{step_obj.name}'")
                            step_result = await asyncio.wait_for(
                                self._step_executor._execute_step(run, entity, step_obj, context_state),
                                timeout=timeout_ms / 1000.0,
                            )
                            context_state.pop("__alignment_correction__", None)
                        else:
                            logger.warning(f"Step '{step_obj.name}' already retried — skipping")
                except Exception as _ga_err:
                    logger.warning(f"GoalGuard step check error: {_ga_err}")
        # ──────────────────────────────────────────────────────────────────

        # Update Context immediately (Phase 4: capped size)
        if isinstance(step_result, dict) and "output" in step_result:
            _store_step_output(context_state, step_obj.name, step_obj.step_id or "", step_result["output"])

        return step_result

    async def _evaluate_hitl_checkpoints(
        self,
        run: 'ExecutionRun',
        entity: 'HierarchicalEntity',
        step_obj: PlanStep,
        context_state: dict[str, Any],
        phase: str,
        governance_dict: Optional[dict[str, Any]] = None,
    ) -> None:
        """Delegate to GovernanceService (Phase 3 extraction)."""
        assert self._governance is not None
        await self._governance.evaluate_hitl(
            run, entity, step_obj, context_state, phase,
            governance_dict=governance_dict
        )

    # ===================================================================
    # CORTEX Execution Helpers
    # ===================================================================

    def _build_task_description(self, entity: 'HierarchicalEntity', input_data: dict[str, Any]) -> str:
        """Delegate to CortexBridge (Phase 3 extraction)."""
        assert self._cortex_bridge is not None
        return self._cortex_bridge.build_task_description(entity, input_data)

    async def _write_step_to_cortex(
        self,
        cortex: 'CortexService',
        working_root_id: UUID,
        step_result: dict[str, Any],
        run_id: UUID,
    ) -> None:
        """Delegate to CortexBridge (Phase 3 extraction)."""
        assert self._cortex_bridge is not None
        await self._cortex_bridge.write_step(cortex, working_root_id, step_result, run_id)

    async def _ingest_tool_result_to_cortex(
        self,
        run: 'ExecutionRun',
        tool_id: str,
        tool_output: str,
        context: dict[str, Any],
    ) -> None:
        """Delegate to CortexBridge (Phase 3 extraction)."""
        assert self._cortex_bridge is not None
        await self._cortex_bridge.ingest_tool_result(run, tool_id, tool_output, context)

    async def _execute_cortex_step(
        self,
        run: 'ExecutionRun',
        entity: 'HierarchicalEntity',
        step: PlanStep,
        cortex: 'CortexService',
        tree: Any,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Delegate to CortexBridge (Phase 3 extraction)."""
        assert self._cortex_bridge is not None
        return await self._cortex_bridge.execute_cortex_step(
            run, entity, step, cortex, tree, context
        )

    def _resolve_node_id(self, target: Any, context: dict[str, Any]) -> str:
        """Delegate to CortexBridge (Phase 3 extraction)."""
        assert self._cortex_bridge is not None
        return self._cortex_bridge.resolve_node_id(target, context)

    def _extract_text_from_file(self, file_path: Any, mime_type: str = "") -> str:
        """Delegate to standalone text_extractor module (Phase 6 dedup)."""
        from src.ai.text_extractor import extract_text_from_file
        return extract_text_from_file(file_path, mime_type)

    def _has_parallel_steps(self, steps: List[dict[str, Any]]) -> bool:
        """Delegate to PlannerService (Phase 3 extraction)."""
        assert self._planner is not None
        return self._planner.has_parallel_steps(steps)

    async def _get_reconciled_plan(self, run: ExecutionRun, entity: HierarchicalEntity, input_data: dict[str, Any]) -> dict[str, Any]:
        """Delegate to PlannerService (Phase 3 extraction)."""
        assert self._planner is not None
        return await self._planner.reconcile(run, entity, input_data)
