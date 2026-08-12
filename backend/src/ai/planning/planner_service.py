"""
planner_service.py — Plan reconciliation, validation, and step management.

Extracted from ExecutionEngine during Phase 6 monolith decomposition
(Step 3.2). Handles static/dynamic plan merging, CHILD_ENTITY_INVOCATION
injection, and step-id generation.
"""
import copy
import json
import logging
from uuid import UUID, uuid4
from typing import Any, List, Optional, cast

from src.ai.models import ExecutionRun, HierarchicalEntity, LLMInteractionLog
from src.ai.schemas import EntityType, PlanStep
from src.ai.llm.router import LLMRouter
from src.ai.usage_service import UsageService

logger = logging.getLogger(__name__)


class PlannerService:
    """Generates and reconciles execution plans from entity configuration."""

    def __init__(self, db: Any, company_id: UUID) -> None:
        self.db = db
        self.company_id = company_id
        self.llm = LLMRouter(db=db, company_id=company_id)
        self.usage_service = UsageService(db)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def reconcile(
        self,
        run: ExecutionRun,
        entity: HierarchicalEntity,
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Merges static and dynamic plans based on strategy.

        Returns a plan dict with a ``steps`` key containing the final
        ordered list of step dicts.
        """
        planning = entity.planning or {}
        static_plan = copy.deepcopy(planning.get("static_plan", {})) or {}

        if "steps" not in static_plan:
            static_plan["steps"] = []

        # Fallback: If no steps and it is a leaf action/skill, add a default step
        if not static_plan["steps"] and entity.type in [EntityType.ACTION, EntityType.SKILL]:
            static_plan["steps"] = [{
                "step_id": "auto_generated",
                "order": 1,
                "name": "Execute",
                "description": f"Executing {entity.name}",
                "type": "ACTION",
                "target": {
                    "prompt_template": entity.description or "Process instruction: {{instruction}}"
                },
                "required": True
            }]

        dynamic_config = planning.get("dynamic_planning", {}) or {}

        if not dynamic_config.get("enabled"):
            return await self._maybe_enforce_router(run, entity, input_data, static_plan)

        # Dynamic planning routes through the v2 PlanGenerator
        # (multi-candidate generation + invariants + judge) when the
        # planner.v2_enabled flag is on. The legacy single-shot v1 planner
        # was retired in the cut-C5 consolidation; the static plan is the
        # only fallback when v2 is off, returns nothing, or errors.
        try:
            from src.ai.core.feature_flags import FeatureFlags
            flags = FeatureFlags(self.db)
            v2 = await flags.is_on("planner.v2_enabled", company_id=self.company_id)
        except Exception:                                                   # pragma: no cover
            v2 = False
        if v2:
            try:
                v2_plan = await self._generate_dynamic_plan_v2(
                    run, entity, input_data, static_plan,
                )
                if v2_plan is not None:
                    # The v2 PlanGenerator has no routing directive, so a
                    # static-less router can come back with flat THOUGHT/ACTION
                    # steps. Enforce delegation here so it can't dead-end on
                    # text output (see _maybe_enforce_router).
                    return await self._maybe_enforce_router(
                        run, entity, input_data, v2_plan
                    )
            except Exception as e:                                          # noqa: BLE001
                logger.warning(f"PlanGenerator reconcile failed; falling back to static: {e}")

        return await self._maybe_enforce_router(run, entity, input_data, static_plan)

    async def _generate_dynamic_plan_v2(
        self,
        run: ExecutionRun,
        entity: HierarchicalEntity,
        input_data: dict[str, Any],
        static_plan: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Phase 11 Track 7 — multi-candidate planner path.

        Generates N candidate plans, validates each with invariants,
        and selects via PlanJudge. Stores the chosen plan + alternates
        in ``_plan_meta`` so the frontend can render the compare modal.
        """
        from src.ai.planning.plan_generator import PlanContext, PlanGenerator

        try:
            from src.ai.core.feature_flags import NUMERIC_DEFAULTS
            n_candidates = int(NUMERIC_DEFAULTS.get("planner.n_candidates", 3))
        except Exception:                                                    # pragma: no cover
            n_candidates = 2

        ctx = PlanContext(
            entity=entity,
            input_data=input_data or {},
            static_plan=static_plan or {},
            company_id=self.company_id,
            goal=getattr(entity, "goal", "") or "",
        )
        gen = PlanGenerator(llm_router=self.llm, db=self.db)
        result = await gen.generate(ctx, n=n_candidates)
        steps = self._assign_step_ids(list(result.chosen.steps), start_from=1)
        return {
            "steps": steps,
            "_plan_meta": {
                "style": result.chosen.style,
                "estimated_cost_usd": str(result.chosen.estimated_cost_usd),
                "alternates": [
                    {
                        "style": c.style,
                        "estimated_cost_usd": str(c.estimated_cost_usd),
                        "judge_score": getattr(c, "judge_score", 0.0),
                    }
                    for c in result.alternates
                ],
                "judge_reasoning": result.judge_reasoning,
            },
        }

    def has_parallel_steps(self, steps: List[dict[str, Any]]) -> bool:
        """Return True ONLY if at least two steps can run simultaneously.

        The previous implementation returned True whenever *any* step had
        input_dependencies — but that means 'this step needs output from step X',
        NOT 'run me in parallel'.  A pure chain like:

            step1 (no deps) → step2 (deps=[step1]) → step3 (deps=[step2])

        has input_dependencies on steps 2 and 3 but is 100% sequential and must
        NEVER be routed to the DAG/parallel executor (which opens isolated
        AsyncSessions per step and races for the shared self.db).

        Correct logic: simulate one round of DAG scheduling.  If the first wave
        of 'ready' steps (those whose deps are all absent/empty) has two or more
        members, genuine parallelism exists → use the DAG executor.  Otherwise
        the plan is sequential → use the sequential loop.
        """
        if not steps:
            return False

        # Build dep sets from explicit input_dependencies + {{step_id}} refs
        step_ids = {s.get("step_id") for s in steps if s.get("step_id")}
        step_deps: dict[Any, set[Any]] = {}

        for s in steps:
            s_id = s.get("step_id")
            if not s_id:
                continue
            deps: set[Any] = set()
            target = s.get("target") or {}
            for dep in target.get("input_dependencies", []):
                if dep in step_ids:
                    deps.add(dep)
            # Also honour {{step_id}} template references
            prompt = target.get("prompt_template", "") or ""
            if isinstance(prompt, dict):
                import json as _json
                prompt = _json.dumps(prompt)
            import re as _re
            for var in _re.findall(r'\{\{(.*?)\}\}', str(prompt)):
                base = var.split('.')[0]
                if base in step_ids and base != s_id:
                    deps.add(base)
            step_deps[s_id] = deps

        # Count steps that are immediately ready (no dependencies at all)
        initially_ready = sum(1 for deps in step_deps.values() if not deps)
        return initially_ready >= 2


    async def validate_goal_progress(
        self,
        goal: str,
        completed_steps: List[dict[str, Any]],
        total_steps: int,
    ) -> dict[str, Any]:
        """Lightweight LLM call to assess goal completion progress.

        Phase 5: Used by the autonomous loop to decide whether to
        early-exit (goal achieved) or trigger re-planning (low progress).

        Returns ``{"score": 0-100, "reasoning": "...", "goal_achieved": bool}``.
        """
        step_summaries = json.dumps(
            [
                {
                    "name": s.get("name", s.get("step", "")),
                    "output_summary": str(s.get("output", ""))[:500],
                }
                for s in completed_steps
            ],
            indent=2,
        )
        prompt = (
            f"Given the original goal and completed work, assess progress.\n\n"
            f"Goal: {goal}\n\n"
            f"Completed steps ({len(completed_steps)}/{total_steps}):\n"
            f"{step_summaries}\n\n"
            f'Respond with JSON: {{"score": 0-100, "reasoning": "...", "goal_achieved": true/false}}'
        )
        try:
            result = await self.llm.call_llm(
                task_type="goal_validation",
                system_prompt="You assess goal completion progress. Be precise and conservative.",
                user_prompt=prompt,
                temperature=0.1,
                max_tokens=300,
            )
            # Parse JSON from response
            output = result.output.strip()
            if "```json" in output:
                output = output.split("```json")[1].split("```")[0]
            elif "{" in output:
                output = output[output.find("{"):output.rfind("}") + 1]
            return cast("dict[str, Any]", json.loads(output))
        except Exception as e:
            logger.warning(f"Goal validation failed: {e}")
            return {"score": 50, "reasoning": f"Validation failed: {e}", "goal_achieved": False}

    async def adapt_plan(
        self,
        original_plan: list[dict[str, Any]],
        completed_steps: list[dict[str, Any]],
        failed_step: dict[str, Any],
        goal: str,
    ) -> List[dict[str, Any]]:
        """Mid-execution re-planning (autonomous loop).

        Delegates to :class:`PlanGenerator.generate` (multi-candidate +
        invariants + judge) when ``planner.v2_enabled`` is on. On any
        failure — or when the flag is off — returns the not-yet-completed
        steps of the original plan unchanged.
        """
        completed_ids = {s.get("step_id") for s in completed_steps if s.get("step_id")}
        remaining = [s for s in original_plan if s.get("step_id") not in completed_ids]

        try:
            from src.ai.core.feature_flags import FeatureFlags
            flags = FeatureFlags(self.db)
            v2 = await flags.is_on("planner.v2_enabled", company_id=self.company_id)
        except Exception:                                                   # pragma: no cover
            v2 = False
        if v2:
            try:
                from src.ai.planning.plan_generator import (
                    PlanContext,
                    PlanGenerator,
                )
                ctx = PlanContext(
                    entity=None,
                    static_plan={"steps": list(original_plan or [])},
                    goal=goal or "",
                    failed_step=failed_step or {},
                )
                gen = PlanGenerator(llm_router=self.llm, db=self.db)
                result = await gen.generate(ctx, n=2)
                return self._assign_step_ids(
                    list(result.chosen.steps),
                    start_from=len(completed_steps) + 1,
                )
            except Exception as e:                                          # noqa: BLE001
                logger.warning(f"PlanGenerator replan failed; returning remaining steps: {e}")

        return remaining

    def _assign_step_ids(self, steps: list[dict[str, Any]], start_from: int = 1) -> list[dict[str, Any]]:
        """Assign sequential step_ids to a list of step dicts."""
        for i, s in enumerate(steps):
            s["step_id"] = f"step_{start_from + i}_{str(uuid4())[:8]}"
            s["order"] = start_from + i
        return steps

    # ------------------------------------------------------------------
    # Private: Routing enforcement (router PROCESS/AGENT with children)
    # ------------------------------------------------------------------

    async def _maybe_enforce_router(
        self,
        run: ExecutionRun,
        entity: HierarchicalEntity,
        input_data: dict[str, Any],
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        """Guarantee a router-with-children delegates — for ANY plan source.

        Dynamic plans come from ``_generate_dynamic_plan_v2``
        (``planner.v2_enabled`` defaults True), whose PlanGenerator has no
        routing directive, so a static-less router can come back with flat
        THOUGHT/ACTION steps. Centralising the post-hoc enforcement here means
        a static-less routing PROCESS/AGENT ends up with ≥1
        CHILD_ENTITY_INVOCATION step regardless of which generator produced
        the plan — otherwise the AgentLoop drives flat THOUGHT/ACTION steps that
        produce no child run and no artifact.

        Idempotent and best-effort: a plan that already delegates to a real
        child passes through untouched; a non-router (no children, or a
        tool-bearing AGENT) is returned unchanged; any failure leaves the plan
        as-is.
        """
        if not isinstance(plan, dict) or not isinstance(plan.get("steps"), list):
            return plan
        entity_type = getattr(entity, "type", "")
        entity_type = str(getattr(entity_type, "value", entity_type)).upper()
        if entity_type not in ("PROCESS", "AGENT"):
            return plan
        try:
            from src.ai.meta.platform_schema_compiler import load_entity_children
            child_entities = await load_entity_children(
                db=self.db, entity_id=entity.id, company_id=self.company_id,
            )
        except Exception as e:                                              # noqa: BLE001
            logger.warning(
                "Router enforcement: failed to load children for %s: %s",
                getattr(entity, "name", "?"), e,
            )
            return plan
        if not child_entities:
            return plan
        caps = getattr(entity, "capabilities", None) or {}
        has_tools = bool(caps.get("tools"))
        # A router cannot do the work itself: a PROCESS, or any entity binding no
        # tools. A tool-bearing AGENT is left free to use its own tools.
        if not (entity_type == "PROCESS" or not has_tools):
            return plan

        user_input = (input_data or {}).get("input") or {
            k: v for k, v in (input_data or {}).items()
            if k not in ("__memory__", "company_id", "user_id")
        }
        if isinstance(user_input, dict):
            user_input = json.dumps(user_input, default=str)
        try:
            plan["steps"] = await self._enforce_child_routing(
                run=run, entity=entity, user_input=user_input,
                valid_steps=plan["steps"], child_entities=child_entities,
            )
        except Exception as e:                                              # noqa: BLE001
            logger.warning(
                "Router enforcement failed for %s: %s",
                getattr(entity, "name", "?"), e,
            )
        return plan

    @staticmethod
    def _routing_directive(entity_type: str, has_tools: bool) -> str:
        """System-prompt directive forcing a router to delegate to children."""
        no_tools = "" if has_tools else (
            " It binds NO tools of its own and therefore CANNOT perform the "
            "work directly — a THOUGHT/ACTION step here only makes you *print* "
            "code or prose as text, producing no document and no artifact."
        )
        return (
            f"\n\n## ROUTING DIRECTIVE (MANDATORY)\n"
            f"This entity is a {entity_type} that orchestrates the child "
            f"entities listed under 'Available Child Entities'.{no_tools}\n"
            f"- You MUST delegate the actual work using `CHILD_ENTITY_INVOCATION` "
            f"steps, each with `target.entity_id` set to the EXACT child UUID.\n"
            f"- DO NOT emit THOUGHT or ACTION steps that attempt to do the work "
            f"yourself (e.g. writing openpyxl/python-docx code, generating the "
            f"file, or computing the deliverable).\n"
            f"- Select ONLY the child(ren) whose role matches the user's request "
            f"and pass the full instruction to each via `target.prompt_template`.\n"
            f"- The plan MUST contain at least one CHILD_ENTITY_INVOCATION step."
        )

    async def _enforce_child_routing(
        self,
        run: ExecutionRun,
        entity: HierarchicalEntity,
        user_input: Any,
        valid_steps: List[dict[str, Any]],
        child_entities: list[Any],
    ) -> List[dict[str, Any]]:
        """Guarantee a router-with-children delegates to >=1 child.

        If the reconciled plan already contains a CHILD_ENTITY_INVOCATION step
        targeting a real child, it passes through untouched. Otherwise we run a
        constrained routing LLM call to pick the matching child(ren); if that
        also yields nothing, we deterministically route to every child rather
        than letting flat THOUGHT/ACTION steps (which produce no artifact) run.
        """
        child_ids = {str(c.id) for c in child_entities}

        def _is_real_invocation(step: dict[str, Any]) -> bool:
            if step.get("type") != "CHILD_ENTITY_INVOCATION":
                return False
            eid = (step.get("target") or {}).get("entity_id")
            return eid is not None and str(eid) in child_ids

        if any(_is_real_invocation(s) for s in valid_steps):
            return valid_steps

        logger.warning(
            "Router %s (%s) produced a plan with no CHILD_ENTITY_INVOCATION "
            "targeting a real child; enforcing delegation.",
            getattr(entity, "name", "?"), getattr(entity, "id", "?"),
        )

        routed = await self._route_children_llm(run, entity, user_input, child_entities)
        if not routed:
            # Deterministic last resort: route to every child so the run still
            # spawns child work instead of dead-ending on text output.
            instr = user_input if isinstance(user_input, str) else json.dumps(
                user_input, default=str
            )
            routed = [{"entity_id": str(c.id), "instruction": instr} for c in child_entities]
            logger.warning(
                "Router %s: routing LLM yielded no selection; falling back to "
                "all %d children.", getattr(entity, "name", "?"), len(routed),
            )

        steps = []
        for r in routed:
            steps.append({
                "name": f"Delegate to {r.get('name') or r['entity_id']}",
                "description": "Routed child invocation (delegation enforced).",
                "type": "CHILD_ENTITY_INVOCATION",
                "target": {
                    "entity_id": r["entity_id"],
                    "prompt_template": r.get("instruction") or "",
                },
                "required": True,
            })
        return self._assign_step_ids(steps, start_from=1)

    async def _route_children_llm(
        self,
        run: ExecutionRun,
        entity: HierarchicalEntity,
        user_input: Any,
        child_entities: list[Any],
    ) -> List[dict[str, Any]]:
        """Constrained LLM call: pick the child(ren) that match the request.

        Returns a list of ``{"entity_id", "name", "instruction"}`` dicts (only
        for child ids that actually exist). Empty list on any failure.
        """
        child_ids = {str(c.id): c for c in child_entities}
        catalog_lines = []
        for c in child_entities:
            goal = (c.goal or c.description or "")[:200]
            catalog_lines.append(f"- entity_id: {c.id} | {c.name} ({c.type}) — {goal}")
        catalog = "\n".join(catalog_lines)
        req = user_input if isinstance(user_input, str) else json.dumps(
            user_input, default=str
        )

        system_prompt = (
            "You are a routing dispatcher. Given a user request and a catalog "
            "of child entities, select the child(ren) whose role best matches "
            "the request and write a concise instruction for each. Respond ONLY "
            'with a JSON array: [{"entity_id": "<exact UUID from the catalog>", '
            '"instruction": "<what this child should do>"}]. '
            "Use only entity_id values present in the catalog. Select the "
            "minimum set of children needed — usually exactly one."
        )
        user_prompt = (
            f"User request:\n{req}\n\n"
            f"Child entity catalog:\n{catalog}\n\n"
            f"Return the routing JSON array."
        )
        try:
            resp = await self.llm.call_llm(
                task_type="thinking",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1,
                max_tokens=500,
            )
            try:
                planner_log = LLMInteractionLog(
                    run_id=run.id,
                    model_provider=resp.provider,
                    model_name=resp.model_name,
                    input_prompt=f"System: {system_prompt[:1000]}\nUser: {user_prompt[:1000]}",
                    output_response=(resp.output[:2000] if resp.output else ""),
                    prompt_tokens=resp.prompt_tokens,
                    completion_tokens=resp.completion_tokens,
                    latency_ms=resp.latency_ms,
                    reasoning_mode="PLANNER",
                    step_name="__router__",
                )
                self.db.add(planner_log)
                await self._log_planner_usage(run, resp, planner_log)
            except Exception:                                               # pragma: no cover
                pass

            out = (resp.output or "").strip()
            if "```json" in out:
                out = out.split("```json")[1].split("```")[0]
            elif "[" in out and "]" in out:
                out = out[out.find("["):out.rfind("]") + 1]
            selected = json.loads(out)
        except Exception as e:                                              # noqa: BLE001
            logger.warning(f"Child routing LLM call failed: {e}")
            return []

        routed = []
        for item in selected if isinstance(selected, list) else []:
            eid = str(item.get("entity_id", "")).strip()
            child = child_ids.get(eid)
            if not child:
                continue
            routed.append({
                "entity_id": eid,
                "name": child.name,
                "instruction": item.get("instruction") or req,
            })
        return routed

    async def _log_planner_usage(
        self, run: ExecutionRun, plan_result_resp: Any, planner_log: Any
    ) -> None:
        """Log LLM usage for the planner call."""
        try:
            model_name = plan_result_resp.model_name or "unknown"
            in_sku = f"{model_name}-in"
            out_sku = f"{model_name}-out"

            in_usage = await self.usage_service.log_usage(
                company_id=run.company_id,
                service_sku=in_sku,
                raw_quantity=float(plan_result_resp.prompt_tokens or 0),
                execution_id=run.id,
                attribution="planner",
            )
            out_usage = await self.usage_service.log_usage(
                company_id=run.company_id,
                service_sku=out_sku,
                raw_quantity=float(plan_result_resp.completion_tokens or 0),
                execution_id=run.id,
                attribution="planner",
            )

            from decimal import Decimal
            if run.total_cost_usd is None:
                run.total_cost_usd = Decimal("0")
            if in_usage:
                run.total_cost_usd += in_usage.calculated_cost
            if out_usage:
                run.total_cost_usd += out_usage.calculated_cost
        except Exception as e:
            logger.debug(f"Planner usage logging failed: {e}")
