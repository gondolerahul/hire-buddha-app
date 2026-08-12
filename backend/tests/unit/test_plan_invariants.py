"""Phase 11 Track 7 — PlanInvariants individual + suite tests."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from src.ai.planning.plan_invariants import (
    all_required_tools_in_capabilities,
    child_invocations_have_entity_id,
    cost_estimate_within_budget,
    no_cycle_in_child_invocations,
    no_dangling_step_dependencies,
    no_dangling_variable_refs,
    no_orphaned_outputs,
    prompt_templates_are_strings,
    validate_plan,
)


def _entity(*, tools=None, governance=None, eid=None):
    return SimpleNamespace(
        id=eid or uuid4(),
        capabilities={"tools": list(tools or [])},
        governance=dict(governance or {}),
    )


# ---------------------------------------------------------------------------
# 1. Cycle in child invocations
# ---------------------------------------------------------------------------


def test_cycle_detected() -> None:
    eid = uuid4()
    plan = [
        {"type": "CHILD_ENTITY_INVOCATION", "name": "loop",
         "target": {"entity_id": str(eid)}},
    ]
    res = no_cycle_in_child_invocations(plan, _entity(eid=eid))
    assert not res.passed


def test_cycle_clean_plan_passes() -> None:
    eid = uuid4()
    plan = [
        {"type": "CHILD_ENTITY_INVOCATION", "name": "child",
         "target": {"entity_id": str(uuid4())}},
    ]
    assert no_cycle_in_child_invocations(plan, _entity(eid=eid)).passed


# ---------------------------------------------------------------------------
# 2. Tool capability
# ---------------------------------------------------------------------------


def test_tool_missing_from_capabilities_fails() -> None:
    plan = [{"type": "TOOL_CALL", "name": "s1",
             "target": {"tool_id": "ghost_tool"}}]
    assert not all_required_tools_in_capabilities(plan, _entity(tools=[])).passed


def test_tool_declared_passes() -> None:
    plan = [{"type": "TOOL_CALL", "name": "s1",
             "target": {"tool_id": "web_search"}}]
    assert all_required_tools_in_capabilities(plan, _entity(tools=["web_search"])).passed


# ---------------------------------------------------------------------------
# 3. Dangling variable refs
# ---------------------------------------------------------------------------


def test_dangling_variable_ref_fails() -> None:
    plan = [{"type": "THOUGHT", "name": "s1", "step_id": "s1",
             "target": {"prompt_template": "use {{step_99}}"}}]
    assert not no_dangling_variable_refs(plan).passed


def test_referenced_earlier_step_ok() -> None:
    plan = [
        {"type": "TOOL_CALL", "name": "s1", "step_id": "s1",
         "target": {"tool_id": "web_search"}},
        {"type": "THOUGHT", "name": "s2", "step_id": "s2",
         "target": {"prompt_template": "use {{s1}} for context"}},
    ]
    assert no_dangling_variable_refs(plan).passed


def test_input_var_is_whitelisted() -> None:
    plan = [{"type": "THOUGHT", "name": "s1", "step_id": "s1",
             "target": {"prompt_template": "based on {{input}}"}}]
    assert no_dangling_variable_refs(plan).passed


# ---------------------------------------------------------------------------
# 4. Dangling step dependencies
# ---------------------------------------------------------------------------


def test_dangling_step_dep_fails() -> None:
    plan = [{"type": "TOOL_CALL", "name": "s1", "step_id": "s1",
             "target": {"input_dependencies": ["ghost_step"]}}]
    assert not no_dangling_step_dependencies(plan).passed


def test_step_dep_to_existing_step_passes() -> None:
    plan = [
        {"type": "TOOL_CALL", "name": "s1", "step_id": "s1", "target": {}},
        {"type": "TOOL_CALL", "name": "s2", "step_id": "s2",
         "target": {"input_dependencies": ["s1"]}},
    ]
    assert no_dangling_step_dependencies(plan).passed


# ---------------------------------------------------------------------------
# 5. Cost estimate vs budget
# ---------------------------------------------------------------------------


def test_cost_above_budget_fails() -> None:
    entity = _entity(governance={"max_cost_usd": 0.01})
    # 5 image_generation steps × 0.04 = 0.20 > 0.01
    plan = [{"type": "TOOL_CALL", "name": f"s{i}", "step_id": f"s{i}",
             "target": {"tool_id": "image_generation"}}
            for i in range(5)]
    assert not cost_estimate_within_budget(plan, entity).passed


def test_cost_under_budget_passes() -> None:
    entity = _entity(governance={"max_cost_usd": 5.0})
    plan = [{"type": "TOOL_CALL", "name": "s1", "step_id": "s1",
             "target": {"tool_id": "web_search"}}]
    assert cost_estimate_within_budget(plan, entity).passed


def test_no_cap_means_pass() -> None:
    plan = [{"type": "TOOL_CALL", "name": "s1", "step_id": "s1",
             "target": {"tool_id": "image_generation"}}]
    assert cost_estimate_within_budget(plan, _entity()).passed


# ---------------------------------------------------------------------------
# 6. Orphaned outputs
# ---------------------------------------------------------------------------


def test_unused_output_flagged() -> None:
    plan = [
        {"type": "TOOL_CALL", "name": "s1", "step_id": "s1",
         "target": {"tool_id": "web_search", "output_slot": "results"}},
        {"type": "THOUGHT", "name": "s2", "step_id": "s2",
         "target": {"prompt_template": "no reference"}},
    ]
    assert not no_orphaned_outputs(plan).passed


def test_referenced_output_passes() -> None:
    plan = [
        {"type": "TOOL_CALL", "name": "s1", "step_id": "s1",
         "target": {"tool_id": "web_search", "output_slot": "results"}},
        {"type": "THOUGHT", "name": "s2", "step_id": "s2",
         "target": {"prompt_template": "use {{s1}}"}},
    ]
    assert no_orphaned_outputs(plan).passed


# ---------------------------------------------------------------------------
# 7. CHILD_ENTITY_INVOCATION must carry entity_id or name_hint
# ---------------------------------------------------------------------------


def test_child_invocation_missing_id_and_hint_fails() -> None:
    plan = [{"type": "CHILD_ENTITY_INVOCATION", "name": "x", "target": {}}]
    assert not child_invocations_have_entity_id(plan, _entity()).passed


def test_child_invocation_with_name_hint_passes() -> None:
    plan = [{"type": "CHILD_ENTITY_INVOCATION", "name": "x",
             "target": {"entity_name_hint": "Other Agent"}}]
    assert child_invocations_have_entity_id(plan, _entity()).passed


# ---------------------------------------------------------------------------
# 8. Prompt templates must be strings
# ---------------------------------------------------------------------------


def test_non_string_prompt_template_fails() -> None:
    plan = [{"type": "THOUGHT", "name": "s1", "step_id": "s1",
             "target": {"prompt_template": {"complex": "object"}}}]
    assert not prompt_templates_are_strings(plan).passed


# ---------------------------------------------------------------------------
# validate_plan suite
# ---------------------------------------------------------------------------


def test_validate_plan_returns_eight_checks() -> None:
    invs = validate_plan([], _entity(), None)
    assert len(invs) == 8


def test_validate_plan_clean_plan_all_pass() -> None:
    entity = _entity(tools=["web_search"], governance={"max_cost_usd": 1.0})
    plan = [
        {"type": "TOOL_CALL", "name": "s1", "step_id": "s1",
         "target": {"tool_id": "web_search", "output_slot": "out"}},
        {"type": "THOUGHT", "name": "s2", "step_id": "s2",
         "target": {"prompt_template": "use {{s1}}"}},
    ]
    invs = validate_plan(plan, entity, None)
    failed = [i for i in invs if not i.passed]
    assert not failed, [f.name for f in failed]


# ---------------------------------------------------------------------------
# authored_steps_covered (D-2 binding invariant)
# ---------------------------------------------------------------------------


def test_authored_steps_covered_passes_when_not_strict():
    from src.ai.planning.plan_invariants import authored_steps_covered
    static = {"fallback_behavior": "ADAPTIVE",
              "steps": [{"step_id": "audit", "name": "audit_log"}]}
    plan = [{"step_id": "s1", "name": "search"}]  # does NOT cover 'audit'
    inv = authored_steps_covered(plan, static)
    assert inv.passed  # ADAPTIVE → advisory, always passes


def test_authored_steps_covered_fails_when_strict_and_missing():
    from src.ai.planning.plan_invariants import authored_steps_covered
    static = {"fallback_behavior": "STRICT",
              "steps": [{"step_id": "audit", "name": "audit_log"}]}
    plan = [{"step_id": "s1", "name": "search"}]
    inv = authored_steps_covered(plan, static)
    assert not inv.passed
    assert "audit" in (inv.detail or "")


def test_authored_steps_covered_passes_when_strict_and_present_by_id():
    from src.ai.planning.plan_invariants import authored_steps_covered
    static = {"fallback_behavior": "STRICT",
              "steps": [{"step_id": "audit", "name": "audit_log"}]}
    plan = [{"step_id": "s1", "name": "search"},
            {"step_id": "audit", "name": "renamed_but_same_id"}]
    assert authored_steps_covered(plan, static).passed


def test_authored_steps_covered_matches_by_name_case_insensitive():
    from src.ai.planning.plan_invariants import authored_steps_covered
    static = {"fallback_behavior": "STRICT",
              "steps": [{"name": "Audit_Log"}]}  # no step_id
    plan = [{"step_id": "x1", "name": "audit_log"}]
    assert authored_steps_covered(plan, static).passed
