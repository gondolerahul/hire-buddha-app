"""
ai.planning.plan_generator — Phase 11 Track 7 multi-candidate planner.

Generates N candidate plans at varied temperatures, runs
:func:`ai.planning.plan_invariants.validate_plan` on each, repairs or
discards violators, and picks one via :class:`PlanJudge` (with priors
biasing the selection when available).

Used as:
  * the new code path inside :class:`PlannerService.adapt_plan` when
    ``planner.v2_enabled`` is ON, and
  * the implementation of :meth:`PlanGenerator.replan` invoked by
    AgentLoop's supervisor-triggered REPLAN path.

The class is **DB-light** — it consumes Intelligence + anti-patterns
through pluggable readers so tests can construct it with stubs.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional, cast
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

__all__ = [
    "PlanContext",
    "PlanCandidate",
    "PlanCandidates",
    "PlanGenerator",
    "classify_plan_style",
]


# ---------------------------------------------------------------------------
# Typed envelopes
# ---------------------------------------------------------------------------


@dataclass
class PlanContext:
    entity: Any
    input_data: dict[str, Any] = field(default_factory=dict)
    static_plan: dict[str, Any] = field(default_factory=dict)
    intelligence_rules: list[Any] = field(default_factory=list)
    anti_patterns: list[Any] = field(default_factory=list)
    task_class: str = "general"
    budget: Any = None
    company_id: Optional[UUID] = None
    goal: str = ""
    proposed_subgoals: list[Any] = field(default_factory=list)
    failed_step: Optional[dict[str, Any]] = None


@dataclass
class PlanCandidate:
    steps: list[dict[str, Any]]
    style: str = "DAG_SEQUENTIAL"
    estimated_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    estimated_latency_s: int = 0
    rationale: str = ""
    invariant_violations: list[str] = field(default_factory=list)
    judge_score: Optional[float] = None
    # "generated" (LLM candidate) or "authored" (the entity's static plan,
    # competing as a first-class candidate — D-2).
    source: str = "generated"

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": list(self.steps),
            "style": self.style,
            "estimated_cost_usd": str(self.estimated_cost_usd),
            "estimated_latency_s": int(self.estimated_latency_s),
            "rationale": self.rationale,
            "invariant_violations": list(self.invariant_violations),
            "judge_score": self.judge_score,
            "source": self.source,
        }


@dataclass
class PlanCandidates:
    chosen: PlanCandidate
    alternates: list[PlanCandidate] = field(default_factory=list)
    judge_reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "chosen": self.chosen.to_dict(),
            "alternates": [c.to_dict() for c in self.alternates],
            "judge_reasoning": self.judge_reasoning,
        }


# ---------------------------------------------------------------------------
# Plan-style classifier
# ---------------------------------------------------------------------------


def classify_plan_style(steps: list[dict[str, Any]]) -> str:
    """Best-effort mapping of a plan shape to a ``PlanStyleArm`` value.

    The Bandit (Track 4) keys arm stats by this string so the planner
    can later prefer styles with proven priors.
    """
    if not steps:
        return "SINGLE_TOOL"
    if len(steps) == 1:
        first = steps[0]
        stype = str(first.get("type", "")).upper()
        if stype == "TOOL_CALL":
            return "SINGLE_TOOL"
        if stype == "CHILD_ENTITY_INVOCATION":
            return "CHILD_ENTITY"
        return "DAG_SEQUENTIAL"
    if any(str(s.get("type", "")).upper() == "CHILD_ENTITY_INVOCATION" for s in steps):
        return "CHILD_ENTITY"
    if any(((s.get("target") or {}).get("input_dependencies") or []) for s in steps):
        # Steps reference earlier outputs → sequential.
        return "DAG_SEQUENTIAL"
    if len(steps) >= 2:
        return "DAG_PARALLEL"
    return "DAG_SEQUENTIAL"


# ---------------------------------------------------------------------------
# PlanGenerator
# ---------------------------------------------------------------------------


_PLAN_SYSTEM = (
    "You design a plan for an autonomous AI agent. Output JSON only:\n"
    '{"steps": [ {"step_id":"s1","name":"...","type":"TOOL_CALL|THOUGHT|'
    'CHILD_ENTITY_INVOCATION|ACTION","target": {...}, '
    '"input_dependencies": ["..."]} ]}\n'
    "Keep the plan tight — no extraneous steps. Reference upstream outputs "
    "via {{step_id}} placeholders. Prefer reusing existing tools and entities.\n"
    "For CHILD_ENTITY_INVOCATION steps, target.entity_id is REQUIRED and must "
    "be the EXACT child UUID from the provided child roster — never null, never "
    "the child's name."
)


class PlanGenerator:
    """Multi-candidate planner. Cheap to construct."""

    DEFAULT_N: int = 3
    REPAIR_ATTEMPTS: int = 1
    TEMPERATURES: tuple[float, ...] = (0.2, 0.5, 0.8)

    def __init__(
        self,
        *,
        llm_router: Any,
        cost_estimator: Any = None,
        plan_judge: Any = None,
        emit_event: Any = None,
        db: Any = None,
    ):
        self.llm = llm_router
        if cost_estimator is None:
            from src.ai.planning import cost_estimator as _ce
            cost_estimator = _ce
        self.cost_estimator = cost_estimator
        if plan_judge is None:
            from src.ai.planning.plan_judge import PlanJudge
            plan_judge = PlanJudge(llm_router, db=db)
        self.judge = plan_judge
        self.emit = emit_event
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self, ctx: PlanContext, n: Optional[int] = None,
    ) -> PlanCandidates:
        n = max(1, min(int(n or self.DEFAULT_N), len(self.TEMPERATURES)))
        await self._emit("agent.plan.generation_start",
                         n_candidates=n, task_class=ctx.task_class)

        candidates = await self._generate_candidates(ctx, n=n)

        # D-2: the entity's static plan competes as a first-class candidate
        # (``source="authored"``) rather than only serving as prompt
        # reference / repair fallback — unless the author opted out via
        # ``fallback_behavior == "DYNAMIC_ONLY"``.
        authored = self._authored_candidate(ctx)
        if authored is not None:
            candidates.append(authored)

        for i, cand in enumerate(candidates):
            await self._emit("agent.plan.candidate_generated",
                             style=cand.style, source=cand.source,
                             estimated_cost_usd=str(cand.estimated_cost_usd),
                             latency_estimate_s=int(cand.estimated_latency_s))

        kept = await self._apply_invariants(candidates, ctx)
        if not kept:
            repaired = await self._repair(candidates, ctx)
            kept = await self._apply_invariants(repaired, ctx) if repaired else []
        if not kept:
            # Last-resort fallback — use the cheapest invariant-failing
            # candidate so the agent still has something to run.
            kept = [self._cheapest(candidates)]

        # D-2: when the static plan is binding (``fallback_behavior ==
        # "STRICT"``), the chosen plan MUST cover every authored step. Drop
        # candidates that don't; if that empties the pool, honour the binding
        # contract by falling back to the authored plan verbatim.
        if self._is_binding(ctx):
            kept = await self._enforce_binding(kept, ctx)
            if not kept and authored is not None:
                await self._emit("agent.plan.binding_fallback",
                                 reason="no_candidate_covered_authored_steps")
                kept = [authored]

        chosen = await self._select(kept, ctx)
        await self._emit("agent.plan.chosen",
                         style=chosen.style,
                         expected_cost_usd=str(chosen.estimated_cost_usd),
                         alternates=[c.style for c in kept if c is not chosen])
        return PlanCandidates(
            chosen=chosen,
            alternates=[c for c in kept if c is not chosen],
            judge_reasoning=getattr(chosen, "_judge_reasoning", ""),
        )

    async def replan(
        self,
        state: Any,
        *,
        proposed_subgoals: Optional[list[Any]] = None,
        failed_step: Optional[dict[str, Any]] = None,
        n: int = 2,
    ) -> PlanCandidates:
        ctx = self._ctx_from_state(state, proposed_subgoals, failed_step)
        result = await self.generate(ctx, n=n)
        await self._emit("agent.plan.replan",
                         by="strategist",
                         reason="failed_step" if failed_step else "supervisor",
                         new_steps=len(result.chosen.steps))
        return result

    # ------------------------------------------------------------------
    # Candidate generation
    # ------------------------------------------------------------------

    async def _generate_candidates(
        self, ctx: PlanContext, *, n: int,
    ) -> list[PlanCandidate]:
        temps = list(self.TEMPERATURES[:n])

        async def one(temp: float) -> PlanCandidate:
            prompt = self._build_prompt(ctx, temperature=temp)
            try:
                resp = await self.llm.call_llm(
                    task_type="thinking",
                    system_prompt=_PLAN_SYSTEM,
                    user_prompt=prompt,
                    temperature=temp,
                    max_tokens=2000,
                )
                steps = self._parse_plan(resp.output)
                await self._log_attributed_usage(ctx, resp, "planner")
            except Exception as exc:                                        # noqa: BLE001
                logger.warning(f"PlanGenerator candidate (t={temp}) failed: {exc}")
                steps = list(ctx.static_plan.get("steps") or [])
            steps = self._tidy(steps)
            est_cost = self.cost_estimator.estimate_plan_cost(steps, ctx.entity)
            est_lat = self.cost_estimator.estimate_latency_s(steps)
            return PlanCandidate(
                steps=steps,
                style=classify_plan_style(steps),
                estimated_cost_usd=Decimal(str(est_cost)),
                estimated_latency_s=int(est_lat),
                rationale=f"temp={temp}",
            )

        return await asyncio.gather(*(one(t) for t in temps))

    def _build_prompt(self, ctx: PlanContext, *, temperature: float) -> str:
        parts: list[str] = []
        parts.append(f"## Goal\n{ctx.goal or self._goal_from_entity(ctx.entity)}")
        if ctx.proposed_subgoals:
            sg_block = "\n".join(
                f"  - {getattr(g, 'description', str(g))}" for g in ctx.proposed_subgoals
            )
            parts.append(f"## Proposed subgoals (replan)\n{sg_block}")
        if ctx.failed_step:
            parts.append(
                "## Previous attempt\n"
                f"  failed step: {ctx.failed_step.get('name','?')} — "
                f"error: {str(ctx.failed_step.get('error','?'))[:200]}"
            )
        if ctx.intelligence_rules:
            ir_block = "\n".join(
                f"  - {self._render_rule(r)}"
                for r in list(ctx.intelligence_rules)[:5]
            )
            parts.append(f"## Intelligence rules\n{ir_block}")
        if ctx.anti_patterns:
            ap_block = "\n".join(
                f"  - {self._render_rule(r)}"
                for r in list(ctx.anti_patterns)[:5]
            )
            parts.append(f"## Anti-patterns to avoid\n{ap_block}")
        if ctx.static_plan and ctx.static_plan.get("steps"):
            parts.append(
                "## Static plan (reference; you may adapt)\n"
                + json.dumps(ctx.static_plan, default=str, indent=2)[:3000]
            )
        parts.append(
            f"## Variation cue\nGenerate at temperature={temperature:.1f}. "
            "Vary structure: prefer parallel DAG when steps are independent."
        )
        return "\n\n".join(parts)

    @staticmethod
    def _parse_plan(text: Optional[str]) -> list[dict[str, Any]]:
        from src.ai.shared.json_utils import parse_json_array, parse_json_object
        raw = text or ""
        # Object shape: {"steps": [...]}
        obj = parse_json_object(raw, warn_label="plan_generator") or {}
        steps = obj.get("steps")
        if isinstance(steps, list):
            return [s for s in steps if isinstance(s, dict)]
        # Bare array shape: [step, step, ...]  (legacy adapt_plan output)
        arr = parse_json_array(raw, warn_label="plan_generator") or []
        if isinstance(arr, list) and arr:
            return [s for s in arr if isinstance(s, dict)]
        return []

    @staticmethod
    def _tidy(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for i, s in enumerate(steps):
            sid = str(s.get("step_id") or s.get("id") or "")
            if not sid:
                sid = f"step_{i + 1}_{str(uuid4())[:6]}"
            if sid in seen_ids:
                sid = f"{sid}_dup_{i}"
            seen_ids.add(sid)
            s["step_id"] = sid
            s.setdefault("order", i + 1)
            s.setdefault("name", sid)
            out.append(s)
        return out

    # ------------------------------------------------------------------
    # Invariants + repair
    # ------------------------------------------------------------------

    async def _apply_invariants(
        self, candidates: list[PlanCandidate], ctx: PlanContext,
    ) -> list[PlanCandidate]:
        from src.ai.planning.plan_invariants import validate_plan
        kept: list[PlanCandidate] = []
        for idx, cand in enumerate(candidates):
            invs = validate_plan(cand.steps, ctx.entity, ctx.budget)
            failures = [i.name for i in invs if not i.passed]
            cand.invariant_violations = failures
            if failures:
                await self._emit("agent.plan.invariant_violation",
                                 candidate_idx=idx, violations=failures)
            else:
                kept.append(cand)
        return kept

    async def _repair(
        self, candidates: list[PlanCandidate], ctx: PlanContext,
    ) -> list[PlanCandidate]:
        """One-shot repair attempt: re-emit the static plan as a safe fallback.

        The plan calls out "re-prompt once or fall back to static"; the
        cheapest deterministic option is to wrap the static plan as a
        candidate. If the static plan is empty too, we have nothing to
        repair.
        """
        if self.REPAIR_ATTEMPTS <= 0:
            return []
        static_steps = list(ctx.static_plan.get("steps") or [])
        if not static_steps:
            return []
        repaired = PlanCandidate(
            steps=self._tidy([dict(s) for s in static_steps]),
            style=classify_plan_style(static_steps),
            estimated_cost_usd=Decimal(str(
                self.cost_estimator.estimate_plan_cost(static_steps, ctx.entity)
            )),
            estimated_latency_s=int(self.cost_estimator.estimate_latency_s(static_steps)),
            rationale="repair: static plan fallback",
        )
        return [repaired]

    @staticmethod
    def _cheapest(candidates: list[PlanCandidate]) -> PlanCandidate:
        return min(candidates, key=lambda c: c.estimated_cost_usd)

    # ------------------------------------------------------------------
    # Static-plan-as-candidate (D-2)
    # ------------------------------------------------------------------

    @staticmethod
    def _fallback_behavior(ctx: PlanContext) -> str:
        sp = ctx.static_plan or {}
        return str(sp.get("fallback_behavior") or "ADAPTIVE").upper()

    def _is_binding(self, ctx: PlanContext) -> bool:
        return self._fallback_behavior(ctx) == "STRICT"

    def _authored_candidate(self, ctx: PlanContext) -> Optional[PlanCandidate]:
        """Wrap the entity's static plan as a competing candidate.

        Returns ``None`` when there is no authored plan or the author opted
        out of static seeding via ``fallback_behavior == "DYNAMIC_ONLY"``.
        """
        if self._fallback_behavior(ctx) == "DYNAMIC_ONLY":
            return None
        static_steps = list((ctx.static_plan or {}).get("steps") or [])
        if not static_steps:
            return None
        steps = self._tidy([dict(s) for s in static_steps])
        return PlanCandidate(
            steps=steps,
            style=classify_plan_style(steps),
            estimated_cost_usd=Decimal(str(
                self.cost_estimator.estimate_plan_cost(steps, ctx.entity)
            )),
            estimated_latency_s=int(self.cost_estimator.estimate_latency_s(steps)),
            rationale="authored static plan",
            source="authored",
        )

    async def _enforce_binding(
        self, kept: list[PlanCandidate], ctx: PlanContext,
    ) -> list[PlanCandidate]:
        """Keep only candidates that cover every authored step (STRICT)."""
        from src.ai.planning.plan_invariants import authored_steps_covered
        out: list[PlanCandidate] = []
        for cand in kept:
            inv = authored_steps_covered(cand.steps, ctx.static_plan or {})
            if inv.passed:
                out.append(cand)
            else:
                cand.invariant_violations = list(cand.invariant_violations) + [inv.name]
                await self._emit("agent.plan.binding_violation",
                                 source=cand.source, detail=inv.detail)
        return out

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    async def _select(
        self, kept: list[PlanCandidate], ctx: PlanContext,
    ) -> PlanCandidate:
        if len(kept) == 1:
            return kept[0]
        # Cap to the cheapest two before invoking the LLM judge.
        ranked = sorted(kept, key=lambda c: c.estimated_cost_usd)[:2]
        try:
            chosen, scores, reasoning = await self.judge.pick(
                ranked,
                goal=ctx.goal or self._goal_from_entity(ctx.entity),
                intelligence_rules=ctx.intelligence_rules,
                anti_patterns=ctx.anti_patterns,
                company_id=ctx.company_id,
            )
            for c, s in zip(ranked, scores):
                c.judge_score = s
            chosen._judge_reasoning = reasoning
            await self._emit("agent.plan.judge_decision",
                             winner_idx=ranked.index(chosen),
                             scores=list(scores))
            return cast(PlanCandidate, chosen)
        except Exception as exc:                                            # noqa: BLE001
            logger.warning(f"PlanJudge selection failed: {exc}")
            return self._cheapest(ranked)

    # ------------------------------------------------------------------
    # Replan context builder
    # ------------------------------------------------------------------

    def _ctx_from_state(
        self,
        state: Any,
        proposed_subgoals: Optional[list[Any]],
        failed_step: Optional[dict[str, Any]],
    ) -> PlanContext:
        entity = getattr(state, "entity", None)
        static_plan = {"steps": list(getattr(state, "plan_steps", []) or [])}
        goal = ""
        if entity is not None:
            goal = getattr(entity, "goal", "") or ""
        elif proposed_subgoals:
            goal = "\n".join(getattr(g, "description", str(g)) for g in proposed_subgoals)
        return PlanContext(
            entity=entity,
            input_data={},
            static_plan=static_plan,
            intelligence_rules=[],
            anti_patterns=[],
            task_class=getattr(state, "task_class", "general"),
            budget=getattr(state, "budget", None),
            company_id=getattr(state, "company_id", None),
            goal=goal,
            proposed_subgoals=list(proposed_subgoals or []),
            failed_step=failed_step,
        )

    # ------------------------------------------------------------------
    # Tiny helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _render_rule(rule: Any) -> str:
        if isinstance(rule, str):
            return rule[:200]
        if isinstance(rule, dict):
            return str(rule.get("text") or rule.get("rule") or rule.get("title") or rule)[:200]
        for attr in ("text", "rule", "title"):
            v = getattr(rule, attr, None)
            if v:
                return str(v)[:200]
        return str(rule)[:200]

    @staticmethod
    def _goal_from_entity(entity: Any) -> str:
        if entity is None:
            return ""
        return str(getattr(entity, "goal", "") or "")

    async def _emit(self, name: str, **payload: Any) -> None:
        if self.emit is None:
            return
        try:
            await self.emit(name, **payload)
        except Exception:                                                   # pragma: no cover
            return

    async def _log_attributed_usage(
        self, ctx: PlanContext, resp: Any, attribution: str,
    ) -> None:
        from src.ai.services.attributed_usage import log_llm_response_usage
        await log_llm_response_usage(
            db=self.db, response=resp, attribution=attribution,
            company_id=ctx.company_id,
        )
