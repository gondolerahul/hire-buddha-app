"""
DebateExecutor — multi-agent debate + judge (Track 2 / Phase 12 D-3).

This is the reframed Tree-of-Thoughts. Where the legacy per-entity
``reasoning_mode="TREE_OF_THOUGHTS"`` generated N candidate answers and let one
LLM score them, the Debate executor is a *Strategist-selected, per-step* path:
the Strategist routes a high-uncertainty / high-stakes step here (it is never an
entity-level setting). It generates N persona/temperature-varied candidate
answers in parallel, then an independent LLM **judge** picks the winner. The
winner is returned as the step's output with the *real* aggregated LLM cost.

Each debate writes a ``debate`` subtree into CORTEX (one parent node plus a
child per candidate and the judge's verdict) so the deliberation is inspectable
in the trace UI. CORTEX and billing are both best-effort: a failure there
degrades transparency/attribution but never the answer.

This delivers the review's "no multi-agent debate/consensus" gap (#8).
"""
from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Any, Optional, cast
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from src.ai.core.agent_state import AgentState, ExecutorName
from src.ai.core.executors.base import ActionResult, register_executor
from src.ai.core.strategist import Move
from src.ai.core.trace import span
from src.ai.llm.router import LLMRouter
from src.ai.orm.execution import ExecutionRun

logger = logging.getLogger(__name__)

# Conservative defaults. A debate is expensive (N+1 LLM calls), so keep the
# panel small unless the entity opts up via ``reasoning_config``.
_DEFAULT_NUM_CANDIDATES = 3
_MIN_CANDIDATES = 2
_MAX_CANDIDATES = 5

# Distinct personas nudge candidates toward genuinely different answers rather
# than N near-duplicates. Cycled if more candidates than personas are requested.
_PERSONAS = [
    "a rigorous, detail-oriented analyst who double-checks every claim",
    "a creative lateral thinker who explores unconventional angles",
    "a pragmatic operator focused on the simplest correct answer",
    "a skeptical reviewer who stress-tests assumptions",
    "a domain expert who leans on first principles",
]


class DebateExecutor:
    name: ExecutorName = "Debate"

    async def execute(
        self,
        move: Move,
        state: AgentState,
        db: Any,
    ) -> ActionResult:
        start = time.time()

        run = await self._reload_run(db, state.run_id)
        entity = run.entity

        step = (move.plan_fragment or [{}])[0] if move.plan_fragment else {}
        step_id = str(step.get("step_id") or step.get("id") or step.get("name") or "")

        system_prompt = self._system_prompt(entity)
        user_prompt = await self._user_prompt(entity, step, state)
        config = self._reasoning_config(entity)
        n = self._num_candidates(config)
        task_type = config.get("task_type", "text_generation")
        model_override = config.get("model_name")
        base_temp = float(config.get("temperature", 0.7) or 0.7)

        router = LLMRouter(db=db, company_id=cast(UUID, state.company_id))

        async with span("debate", step_id or "debate", num_candidates=n) as _sp:
            # 1. Generate N candidates in parallel (varied persona + temperature).
            async def _candidate(i: int) -> Any:
                persona = _PERSONAS[i % len(_PERSONAS)]
                temp = min(base_temp + 0.1 * i, 1.0)
                return await router.call_llm(
                    task_type=task_type,
                    system_prompt=(
                        f"{system_prompt}\n\nYou are debating as {persona}. "
                        f"Produce your single best answer to the task."
                    ),
                    user_prompt=user_prompt,
                    temperature=temp,
                    max_tokens=config.get("max_tokens"),
                    model_override=model_override,
                )

            candidates = await asyncio.gather(*[_candidate(i) for i in range(n)])

            # 2. Independent judge picks the winner.
            winner_idx, judge_resp = await self._judge(
                router, task_type, user_prompt, candidates, config, model_override,
            )
            winner = candidates[winner_idx]
            winner_output = winner.output or ""

            _sp.set_output(winner_output[:8000])

        # 3. Bill the real aggregated cost (best-effort).
        all_responses = list(candidates) + [judge_resp]
        cost = await self._bill(db, state, run, all_responses)

        # 4. Persist the debate subtree to CORTEX (best-effort, never fatal).
        cortex_nodes = await self._write_debate_subtree(
            db, state, step_id or "debate", user_prompt, candidates, winner_idx,
        )

        latency_ms = int((time.time() - start) * 1000)
        logger.info(
            "[DebateExecutor] run=%s step=%s candidates=%d winner=#%d cost=$%s",
            state.run_id, step_id, n, winner_idx + 1, cost,
        )
        return ActionResult(
            output=winner_output[:8000],
            cost_usd=cost,
            latency_ms=latency_ms,
            success=True,
            completed_step_ids=[step_id] if step_id else [],
            cortex_nodes_written=cortex_nodes,
        )

    # ------------------------------------------------------------------
    # Judge
    # ------------------------------------------------------------------

    async def _judge(
        self,
        router: LLMRouter,
        task_type: str,
        user_prompt: str,
        candidates: list[Any],
        config: dict[str, Any],
        model_override: Optional[str],
    ) -> tuple[int, Any]:
        """Score every candidate and return ``(winner_index, judge_response)``.

        Defaults to candidate #1 if the judge's output can't be parsed, so a
        malformed verdict never crashes the step.
        """
        candidates_text = "\n\n---\n\n".join(
            f"## Candidate {i + 1}\n{(c.output or '').strip()}"
            for i, c in enumerate(candidates)
        )
        judge_prompt = (
            f"You are an impartial judge of a debate between {len(candidates)} "
            f"candidate answers to the same task. Rate each on accuracy, "
            f"completeness, clarity, and relevance, then pick the single best.\n\n"
            f"ORIGINAL TASK:\n{user_prompt}\n\n"
            f"CANDIDATES:\n{candidates_text}\n\n"
            f'Respond with JSON only: {{"best": <candidate_number>, '
            f'"reason": "<one sentence>"}}'
        )
        judge_resp = await router.call_llm(
            task_type=task_type,
            system_prompt="You are an impartial judge. Select the single best answer.",
            user_prompt=judge_prompt,
            temperature=0.1,
            max_tokens=config.get("max_tokens") or 1000,
            model_override=model_override,
        )

        winner_idx = 0
        try:
            import json

            text = judge_resp.output or ""
            if "{" in text and "}" in text:
                parsed = json.loads(text[text.find("{"): text.rfind("}") + 1])
                best = int(parsed.get("best", 1))
                winner_idx = max(0, min(best - 1, len(candidates) - 1))
        except (ValueError, KeyError, TypeError):
            winner_idx = 0
        return winner_idx, judge_resp

    # ------------------------------------------------------------------
    # Prompt + config helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _system_prompt(entity: Any) -> str:
        identity = getattr(entity, "identity", None) or {}
        sp = identity.get("system_prompt", "You are a helpful assistant.")
        persona = identity.get("persona") or {}
        if persona:
            sp = persona.get("system_prompt", sp)
        return str(sp)

    @staticmethod
    async def _user_prompt(entity: Any, step: dict[str, Any], state: AgentState) -> str:
        instruction = (
            step.get("instruction")
            or step.get("description")
            or step.get("name")
            or getattr(entity, "goal", None)
            or "Complete the task."
        )
        ctx = await state.materialise_context_dict()
        # Surface prior step outputs (skip the internal echo key).
        prior = {
            k: v for k, v in ctx.items()
            if not k.startswith("__") and isinstance(v, (str, int, float))
        }
        if prior:
            import json

            return f"{instruction}\n\n## Context so far\n{json.dumps(prior, default=str)[:4000]}"
        return str(instruction)

    @staticmethod
    def _reasoning_config(entity: Any) -> dict[str, Any]:
        logic_gate = getattr(entity, "logic_gate", None) or {}
        return logic_gate.get("reasoning_config") or {}

    @staticmethod
    def _num_candidates(config: dict[str, Any]) -> int:
        raw = config.get("debate_num_candidates", config.get("tot_num_paths", _DEFAULT_NUM_CANDIDATES))
        try:
            n = int(raw)
        except (TypeError, ValueError):
            n = _DEFAULT_NUM_CANDIDATES
        return max(_MIN_CANDIDATES, min(n, _MAX_CANDIDATES))

    # ------------------------------------------------------------------
    # Billing — mirror StepExecutorService SKU convention + atomic bump
    # ------------------------------------------------------------------

    async def _bill(
        self, db: Any, state: AgentState, run: ExecutionRun, responses: list[Any],
    ) -> Decimal:
        """Charge the aggregated LLM cost and fold it into ``run.total_cost_usd``.

        Uses the same ``<model>-in`` / ``<model>-out`` SKU convention as
        ``StepExecutorService._log_usage`` so debate cost lands on the same
        ledger. Best-effort: with no pricing rows (or a fake DB in tests),
        ``UsageService.log_usage`` returns ``None`` and the cost is ``0`` rather
        than an error.
        """
        from src.ai.usage_service import UsageService

        usage = UsageService(db)
        total = Decimal("0")
        tokens = 0
        for resp in responses:
            model_name = getattr(resp, "model_name", "") or ""
            pt = int(getattr(resp, "prompt_tokens", 0) or 0)
            ct = int(getattr(resp, "completion_tokens", 0) or 0)
            tokens += pt + ct
            try:
                u_in = await usage.log_usage(
                    company_id=run.company_id,
                    service_sku=f"{model_name}-in" if model_name else "unknown-in",
                    raw_quantity=float(pt),
                    execution_id=run.id,
                )
                u_out = await usage.log_usage(
                    company_id=run.company_id,
                    service_sku=f"{model_name}-out" if model_name else "unknown-out",
                    raw_quantity=float(ct),
                    execution_id=run.id,
                )
            except Exception as exc:                                       # noqa: BLE001
                logger.debug("[DebateExecutor] usage logging failed: %s", exc)
                continue
            if u_in is not None:
                total += Decimal(str(u_in.calculated_cost))
            if u_out is not None:
                total += Decimal(str(u_out.calculated_cost))

        if total > 0 or tokens > 0:
            try:
                await db.execute(
                    update(ExecutionRun)
                    .where(ExecutionRun.id == run.id)
                    .values(
                        total_cost_usd=func.coalesce(ExecutionRun.total_cost_usd, 0) + total,
                        total_tokens=func.coalesce(ExecutionRun.total_tokens, 0) + tokens,
                    )
                )
                await db.commit()
            except Exception as exc:                                       # noqa: BLE001
                logger.debug("[DebateExecutor] run-cost bump failed: %s", exc)
        return total

    # ------------------------------------------------------------------
    # CORTEX debate subtree (best-effort)
    # ------------------------------------------------------------------

    async def _write_debate_subtree(
        self,
        db: Any,
        state: AgentState,
        step_id: str,
        user_prompt: str,
        candidates: list[Any],
        winner_idx: int,
    ) -> list[Any]:
        """Write a debate parent node + one child per candidate.

        Anchored under the run's CORTEX working root. ``CortexService.write``
        returns the new node's UUID, so the returned list of UUIDs feeds
        ``ActionResult.cortex_nodes_written``. The nodes use the ``finding``
        type tagged ``debate=True`` in metadata (there is no dedicated
        ``debate`` node-type enum value). Any failure is swallowed — the answer
        is already decided; this subtree is purely for transparency.
        """
        if state.cortex_working_root_id is None:
            return []
        written: list[Any] = []
        try:
            from src.ai.memory.cortex_service import CortexService

            cortex = CortexService(db=db, company_id=cast(UUID, state.company_id))
            parent_id = await cortex.write(
                parent_id=state.cortex_working_root_id,
                node_type="finding",
                title=f"🗣️ Debate: {step_id}",
                content=user_prompt[:2000],
                summary=f"{len(candidates)}-way debate; winner = candidate #{winner_idx + 1}",
                status="complete",
                metadata_extra={"debate": True, "winner": winner_idx + 1},
            )
            if parent_id is not None:
                written.append(parent_id)
            for i, c in enumerate(candidates):
                child_id = await cortex.write(
                    parent_id=parent_id or state.cortex_working_root_id,
                    node_type="finding",
                    title=f"Candidate #{i + 1}" + (" ✅ winner" if i == winner_idx else ""),
                    content=(c.output or "")[:4000],
                    summary=(c.output or "")[:200] or f"candidate #{i + 1}",
                    status="complete",
                    metadata_extra={"debate_candidate": i + 1, "winner": i == winner_idx},
                )
                if child_id is not None:
                    written.append(child_id)
            await db.commit()
        except Exception as exc:                                           # noqa: BLE001
            logger.debug("[DebateExecutor] CORTEX debate subtree write failed: %s", exc)
        return written

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


register_executor(DebateExecutor())
