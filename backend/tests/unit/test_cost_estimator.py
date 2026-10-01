"""Phase 11 Track 7 — cost / latency estimator tests."""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.ai.planning.cost_estimator import (
    MODEL_PRICE_FACTOR,
    TOOL_BASELINE_COST,
    estimate_latency_s,
    estimate_plan_cost,
    estimate_step_cost,
)


def _entity(model_name: str = "gemini-2.5-flash"):
    return SimpleNamespace(
        logic_gate={"reasoning_config": {"model_name": model_name}},
    )


# ---------------------------------------------------------------------------
# Per-step
# ---------------------------------------------------------------------------


def test_tool_call_uses_baseline_table() -> None:
    step = {"type": "TOOL_CALL", "target": {"tool_id": "web_search"}}
    assert estimate_step_cost(step) == TOOL_BASELINE_COST["web_search"]


def test_unknown_tool_uses_default() -> None:
    step = {"type": "TOOL_CALL", "target": {"tool_id": "ghost_tool"}}
    assert estimate_step_cost(step) == Decimal("0.01")


def test_thought_step_scales_by_model_factor() -> None:
    base_cost = estimate_step_cost(
        {"type": "THOUGHT", "target": {"model_name": "gemini-2.5-flash"}},
    )
    pro_cost = estimate_step_cost(
        {"type": "THOUGHT", "target": {"model_name": "gemini-2.5-pro"}},
    )
    assert pro_cost == base_cost * MODEL_PRICE_FACTOR["gemini-2.5-pro"]


def test_child_invocation_has_higher_base_cost() -> None:
    c = estimate_step_cost({"type": "CHILD_ENTITY_INVOCATION", "target": {}})
    assert c >= Decimal("0.05")


def test_cortex_op_step_is_cheap() -> None:
    for stype in ("READ", "NAVIGATE", "WRITE"):
        c = estimate_step_cost({"type": stype, "target": {}})
        assert c <= Decimal("0.001")


# ---------------------------------------------------------------------------
# Plan-level aggregation
# ---------------------------------------------------------------------------


def test_estimate_plan_cost_sums_steps() -> None:
    plan = [
        {"type": "TOOL_CALL", "target": {"tool_id": "web_search"}},
        {"type": "TOOL_CALL", "target": {"tool_id": "scraper_tool"}},
    ]
    expected = TOOL_BASELINE_COST["web_search"] + TOOL_BASELINE_COST["scraper_tool"]
    assert estimate_plan_cost(plan) == expected


def test_estimate_plan_cost_uses_entity_default_model() -> None:
    plan = [{"type": "THOUGHT", "target": {}}]
    cheap = estimate_plan_cost(plan, _entity(model_name="gemini-2.5-flash"))
    expensive = estimate_plan_cost(plan, _entity(model_name="claude-opus-4-1"))
    assert expensive > cheap


# ---------------------------------------------------------------------------
# Latency
# ---------------------------------------------------------------------------


def test_estimate_latency_sums_table() -> None:
    plan = [
        {"type": "TOOL_CALL", "target": {"tool_id": "web_search"}},
        {"type": "TOOL_CALL", "target": {"tool_id": "image_generation"}},
    ]
    # web_search 3s + image_generation 15s = 18s
    assert estimate_latency_s(plan) == 18


def test_estimate_latency_unknown_step_default() -> None:
    plan = [{"type": "TOOL_CALL", "target": {"tool_id": "ghost"}}]
    assert estimate_latency_s(plan) >= 1


def test_every_baseline_names_a_registered_tool() -> None:
    """TL-64: keys like ``excel``, ``sandbox_executor`` and ``browser_tool``
    matched no tool, so their estimates silently fell back to the default."""
    import src.ai.tools  # noqa: F401 — registers every tool
    from src.ai.tools.base import ToolRegistry

    unknown = sorted(set(TOOL_BASELINE_COST) - set(ToolRegistry._tools))
    assert not unknown, f"baselines for tools the registry does not know: {unknown}"


def test_the_broken_estimator_refresh_cron_is_gone() -> None:
    """PC-26: the nightly refresh read tool_interaction_logs.cost_usd, which
    never existed, so every run errored and refreshed nothing."""
    from src.ai import worker
    from src.ai.core import arq_jobs

    assert not hasattr(arq_jobs, "cost_estimator_refresh")
    names = [getattr(getattr(c, "coroutine", None), "__name__", "") for c in worker.WorkerSettings.cron_jobs]
    assert not any("cost_estimator" in n for n in names)
