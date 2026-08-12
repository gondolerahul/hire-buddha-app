"""Phase 11 Track 5 — Validator deterministic checks."""
from __future__ import annotations

import pytest

from src.ai.meta.board.validator import ValidatorRole


def _spec(**overrides):
    base = {
        "name": "Test Agent",
        "type": "SKILL",
        "goal": "Do a thing",
        "capabilities": {"tools": ["web_search"]},
        "planning": {
            "static_plan": {
                "steps": [
                    {"step_id": "s1", "type": "TOOL_CALL",
                     "target": {"tool_id": "web_search"}},
                ]
            }
        },
        "logic_gate": {},
        "governance": {"max_cost_usd": 1.0, "timeout_ms": 60000},
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_clean_spec_passes_all_checks() -> None:
    report = await ValidatorRole().check(_spec())
    assert report.passed, [f.name for f in report.failed]


@pytest.mark.asyncio
async def test_missing_required_field_fails() -> None:
    report = await ValidatorRole().check(_spec(name=""))
    assert not report.passed
    assert any(c.name == "json_shape_ok" for c in report.failed)


@pytest.mark.asyncio
async def test_unknown_entity_type_fails() -> None:
    report = await ValidatorRole().check(_spec(type="BANANA"))
    assert any(c.name == "entity_type_valid" for c in report.failed)


@pytest.mark.asyncio
async def test_tool_used_not_in_capabilities_fails() -> None:
    spec = _spec()
    spec["planning"]["static_plan"]["steps"][0]["target"]["tool_id"] = "ghost_tool"
    report = await ValidatorRole().check(spec)
    failed = {c.name for c in report.failed}
    assert "all_tools_listed_in_capabilities" in failed


@pytest.mark.asyncio
async def test_duplicate_step_ids_fail() -> None:
    spec = _spec()
    spec["planning"]["static_plan"]["steps"].append(
        {"step_id": "s1", "type": "TOOL_CALL", "target": {"tool_id": "web_search"}}
    )
    report = await ValidatorRole().check(spec)
    assert any(c.name == "plan_step_ids_unique" for c in report.failed)


@pytest.mark.asyncio
async def test_missing_governance_caps_fail() -> None:
    report = await ValidatorRole().check(_spec(governance={}))
    failed = {c.name for c in report.failed}
    assert "governance_caps_set" in failed


@pytest.mark.asyncio
async def test_cost_estimate_above_cap_fails() -> None:
    spec = _spec(governance={"max_cost_usd": 0.05, "timeout_ms": 60000})
    # Add 10 steps → estimate = 0.05 + 0.10 = 0.15 > cap 0.05.
    spec["planning"]["static_plan"]["steps"] = [
        {"step_id": f"s{i}", "type": "TOOL_CALL",
         "target": {"tool_id": "web_search"}}
        for i in range(10)
    ]
    report = await ValidatorRole().check(spec)
    failed = {c.name for c in report.failed}
    assert "cost_estimate_under_cap" in failed


@pytest.mark.asyncio
async def test_review_enabled_without_prompt_fails() -> None:
    spec = _spec(logic_gate={
        "review_mechanism": {"enabled": True, "review_prompt": ""},
    })
    report = await ValidatorRole().check(spec)
    assert any(c.name == "review_mechanism_consistent" for c in report.failed)
