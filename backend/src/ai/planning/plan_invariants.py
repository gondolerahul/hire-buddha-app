"""
ai.planning.plan_invariants — Phase 11 Track 7 deterministic plan checks.

Each invariant is a pure function over a list of plan-step dicts plus
the parent entity + (optional) :class:`Budget`. They return an
:class:`Invariant` carrying ``name``, ``passed`` and an optional
``detail`` string explaining the failure. The :func:`validate_plan`
top-level helper runs the full suite and is the entry point used by
:class:`PlanGenerator` (Track 7) and the Validator role
(:mod:`ai.meta.board.validator` — Track 5).

Design notes:
  * Pure: no DB, no LLM, no I/O. All inputs are plain Python objects.
  * Forgiving: each invariant catches its own errors so a malformed
    candidate yields a structured violation report instead of crashing
    the planner.
  * Cheap: each check is O(n) over plan-step count and ≤ ~30 LoC.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

__all__ = [
    "Invariant",
    "validate_plan",
    "no_cycle_in_child_invocations",
    "all_required_tools_in_capabilities",
    "no_dangling_variable_refs",
    "no_dangling_step_dependencies",
    "cost_estimate_within_budget",
    "no_orphaned_outputs",
    "child_invocations_have_entity_id",
    "prompt_templates_are_strings",
    "authored_steps_covered",
]


@dataclass
class Invariant:
    name: str
    passed: bool
    detail: Optional[str] = None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def validate_plan(
    plan: list[dict[str, Any]],
    entity: Any,
    budget: Any = None,
) -> list[Invariant]:
    """Run every invariant. Returns a list (order matches the spec)."""
    return [
        no_cycle_in_child_invocations(plan, entity),
        all_required_tools_in_capabilities(plan, entity),
        no_dangling_variable_refs(plan),
        no_dangling_step_dependencies(plan),
        cost_estimate_within_budget(plan, entity, budget),
        no_orphaned_outputs(plan),
        child_invocations_have_entity_id(plan, entity),
        prompt_templates_are_strings(plan),
    ]


# ---------------------------------------------------------------------------
# Individual invariants
# ---------------------------------------------------------------------------


def no_cycle_in_child_invocations(plan: list[dict[str, Any]], entity: Any) -> Invariant:
    """A CHILD_ENTITY_INVOCATION must not target the parent entity itself."""
    parent_id = str(getattr(entity, "id", None) or "")
    if not parent_id:
        return Invariant("no_cycle_in_child_invocations", passed=True)
    bad: list[str] = []
    for s in plan:
        if str(s.get("type", "")).upper() != "CHILD_ENTITY_INVOCATION":
            continue
        eid = str(((s.get("target") or {}).get("entity_id") or ""))
        if eid and eid == parent_id:
            bad.append(str(s.get("step_id") or s.get("name") or "?"))
    return Invariant(
        "no_cycle_in_child_invocations",
        passed=not bad,
        detail=("self-targeting steps: " + ",".join(bad)) if bad else None,
    )


def all_required_tools_in_capabilities(plan: list[dict[str, Any]], entity: Any) -> Invariant:
    caps = getattr(entity, "capabilities", None) or {}
    if isinstance(entity, dict):
        caps = entity.get("capabilities") or {}
    declared = {str(t) for t in (caps.get("tools") or [])}
    missing: list[str] = []
    for s in plan:
        if str(s.get("type", "")).upper() != "TOOL_CALL":
            continue
        target = s.get("target") or {}
        tool_id = str(target.get("tool_id") or s.get("tool_id") or "")
        if tool_id and tool_id not in declared:
            missing.append(tool_id)
    return Invariant(
        "all_required_tools_in_capabilities",
        passed=not missing,
        detail=("tools used but not declared: " + ",".join(missing[:5])) if missing else None,
    )


_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*\}\}")
_PLAIN_VAR_RE = re.compile(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_.]*)\}(?!\})")


def _collect_var_refs(text: str) -> set[str]:
    refs: set[str] = set()
    if not text:
        return refs
    refs.update(_VAR_RE.findall(text))
    refs.update(_PLAIN_VAR_RE.findall(text))
    return refs


def no_dangling_variable_refs(plan: list[dict[str, Any]]) -> Invariant:
    """Every ``{{step_x}}`` reference in a prompt template must point at
    a step that exists earlier in the plan (or at ``input``).

    Inputs (``input``, ``goal``, ``__memory__`` etc.) are whitelisted.
    """
    WHITELIST = {"input", "goal", "context", "__memory__",
                 "__intelligence_rules__", "__episodic_memory__",
                 "step_id", "iteration", "user_id"}
    defined: set[str] = set(WHITELIST)
    dangling: list[str] = []
    for s in plan:
        target = s.get("target") or {}
        tmpl = target.get("prompt_template") or s.get("prompt_template") or ""
        if not isinstance(tmpl, str):
            tmpl = str(tmpl)
        refs = _collect_var_refs(tmpl)
        for r in refs:
            root = r.split(".")[0]
            if root not in defined:
                dangling.append(f"{s.get('name','?')}:{r}")
        sid = str(s.get("step_id") or s.get("id") or s.get("name") or "")
        if sid:
            defined.add(sid)
    return Invariant(
        "no_dangling_variable_refs",
        passed=not dangling,
        detail=("dangling refs: " + ",".join(dangling[:5])) if dangling else None,
    )


def no_dangling_step_dependencies(plan: list[dict[str, Any]]) -> Invariant:
    """Every ``input_dependencies`` entry must reference a real earlier step."""
    ids = {str(s.get("step_id") or s.get("id") or s.get("name") or "")
           for s in plan if s.get("step_id") or s.get("id") or s.get("name")}
    ids.discard("")
    dangling: list[str] = []
    for s in plan:
        deps = (s.get("target") or {}).get("input_dependencies") or []
        for d in deps:
            if str(d) not in ids:
                dangling.append(f"{s.get('name','?')}->{d}")
    return Invariant(
        "no_dangling_step_dependencies",
        passed=not dangling,
        detail=("dangling deps: " + ",".join(dangling[:5])) if dangling else None,
    )


def cost_estimate_within_budget(
    plan: list[dict[str, Any]], entity: Any, budget: Any = None,
) -> Invariant:
    """Sum of per-step cost estimates must not exceed governance cap.

    Uses :mod:`ai.planning.cost_estimator` for per-step cost. A None
    budget cap (e.g. tests) is treated as ``Invariant.passed=True`` —
    this invariant only fires when the entity / Budget explicitly
    constrains cost.
    """
    cap = _resolve_cost_cap(entity, budget)
    if cap is None or cap <= 0:
        return Invariant("cost_estimate_within_budget", passed=True)
    try:
        from src.ai.planning.cost_estimator import estimate_plan_cost
        est = estimate_plan_cost(plan, entity)
    except Exception as exc:                                                # pragma: no cover
        return Invariant("cost_estimate_within_budget", passed=False,
                         detail=f"estimator error: {exc}")
    return Invariant(
        "cost_estimate_within_budget",
        passed=est <= cap,
        detail=(f"estimate {est} > cap {cap}") if est > cap else None,
    )


def no_orphaned_outputs(plan: list[dict[str, Any]]) -> Invariant:
    """Every non-final step with an ``output_slot`` should be referenced
    somewhere downstream. Pure heuristic: the final step is exempt and
    a missing ``output_slot`` is fine.
    """
    if not plan:
        return Invariant("no_orphaned_outputs", passed=True)
    referenced: set[str] = set()
    for s in plan:
        target = s.get("target") or {}
        tmpl = target.get("prompt_template") or ""
        if not isinstance(tmpl, str):
            tmpl = str(tmpl)
        referenced.update(_collect_var_refs(tmpl))
        for d in (target.get("input_dependencies") or []):
            referenced.add(str(d))
    orphans: list[str] = []
    for s in plan[:-1]:
        slot = (s.get("target") or {}).get("output_slot") or s.get("output_slot")
        sid = str(s.get("step_id") or s.get("id") or s.get("name") or "")
        if slot and slot not in referenced and sid not in referenced:
            orphans.append(f"{s.get('name','?')}:{slot}")
    return Invariant(
        "no_orphaned_outputs",
        passed=not orphans,
        detail=("orphaned outputs: " + ",".join(orphans[:5])) if orphans else None,
    )


def child_invocations_have_entity_id(
    plan: list[dict[str, Any]], entity: Any,                                          # noqa: ARG001
) -> Invariant:
    """Every CHILD_ENTITY_INVOCATION must have either an entity_id or an
    entity_name_hint that downstream resolution can disambiguate."""
    missing: list[str] = []
    for s in plan:
        if str(s.get("type", "")).upper() != "CHILD_ENTITY_INVOCATION":
            continue
        target = s.get("target") or {}
        if not target.get("entity_id") and not target.get("entity_name_hint"):
            missing.append(str(s.get("name") or s.get("step_id") or "?"))
    return Invariant(
        "child_invocations_have_entity_id",
        passed=not missing,
        detail=("missing entity_id: " + ",".join(missing[:5])) if missing else None,
    )


def prompt_templates_are_strings(plan: list[dict[str, Any]]) -> Invariant:
    """LLMs sometimes emit prompt_template as a dict/list; the planner
    coerces these, but the invariant catches anything that slipped past."""
    bad: list[str] = []
    for s in plan:
        target = s.get("target") or {}
        tmpl = target.get("prompt_template")
        if tmpl is not None and not isinstance(tmpl, str):
            bad.append(str(s.get("name") or s.get("step_id") or "?"))
    return Invariant(
        "prompt_templates_are_strings",
        passed=not bad,
        detail=("non-string prompt_templates: " + ",".join(bad[:5])) if bad else None,
    )


def authored_steps_covered(plan: list[dict[str, Any]], static_plan: dict[str, Any]) -> Invariant:
    """When the static plan is *binding*, every authored step must appear in
    the candidate plan.

    "Binding" is signalled by ``static_plan.fallback_behavior == "STRICT"``
    (D-2: static plan as a guardrail for compliance / deterministic
    workflows). For ``ADAPTIVE`` (default) and ``DYNAMIC_ONLY`` the static
    plan is advisory and this invariant always passes. Authored steps are
    matched by ``step_id`` first, then case-insensitively by ``name``, so a
    dynamic candidate may augment and reorder around the authored steps as
    long as it does not drop them.

    This invariant is NOT part of the default :func:`validate_plan` suite
    because that helper has no static-plan argument; :class:`PlanGenerator`
    applies it directly when a binding static plan is present.
    """
    if not isinstance(static_plan, dict):
        return Invariant("authored_steps_covered", passed=True)
    if str(static_plan.get("fallback_behavior") or "ADAPTIVE").upper() != "STRICT":
        return Invariant("authored_steps_covered", passed=True)
    authored = static_plan.get("steps") or []
    if not authored:
        return Invariant("authored_steps_covered", passed=True)

    present_ids = {str(s.get("step_id") or s.get("id") or "").strip() for s in plan}
    present_names = {str(s.get("name") or "").strip().lower() for s in plan}
    present_ids.discard("")
    present_names.discard("")

    missing: list[str] = []
    for a in authored:
        if not isinstance(a, dict):
            continue
        aid = str(a.get("step_id") or a.get("id") or "").strip()
        aname = str(a.get("name") or "").strip().lower()
        if aid and aid in present_ids:
            continue
        if aname and aname in present_names:
            continue
        missing.append(str(a.get("name") or a.get("step_id") or "?"))
    return Invariant(
        "authored_steps_covered",
        passed=not missing,
        detail=(
            "binding (STRICT) static plan missing authored steps: "
            + ",".join(missing[:5])
        ) if missing else None,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_cost_cap(entity: Any, budget: Any) -> Optional[Decimal]:
    if budget is not None:
        cap = getattr(budget, "usd_max", None)
        if cap is not None:
            try:
                return Decimal(str(cap))
            except Exception:
                pass
    gov = getattr(entity, "governance", None)
    if isinstance(entity, dict):
        gov = entity.get("governance")
    if isinstance(gov, dict) and gov.get("max_cost_usd") is not None:
        try:
            return Decimal(str(gov["max_cost_usd"]))
        except Exception:
            return None
    return None
