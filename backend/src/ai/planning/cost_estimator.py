"""
ai.planning.cost_estimator — Phase 11 Track 7 deterministic cost & latency
estimation for plan steps.

Pure functions over plan-step dicts. The numbers here are conservative
seed values harvested from the last 30 days of telemetry at the time
Track 7 shipped. A nightly cron (``cost_estimator_refresh``) is
specified in the plan but deferred to Track 9; until then these
baselines drive the ``cost_estimate_within_budget`` invariant.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, cast


# ---------------------------------------------------------------------------
# Baseline tables — keep alphabetised; missing entries fall back to default.
# ---------------------------------------------------------------------------


TOOL_BASELINE_COST: dict[str, Decimal] = {
    "batch_web_search": Decimal("0.015"),
    "browser_tool":     Decimal("0.05"),
    "calculator":       Decimal("0.001"),
    "docx_tool":        Decimal("0.01"),
    "email_classify":   Decimal("0.002"),
    "email_draft":      Decimal("0.01"),
    "email_ingest":     Decimal("0.001"),
    "excel":            Decimal("0.005"),
    "file_writer":      Decimal("0.001"),
    "headless_browser": Decimal("0.05"),
    "image_generation": Decimal("0.04"),
    "pdf_generator":    Decimal("0.01"),
    "pptx_tool":        Decimal("0.01"),
    "sandbox_executor": Decimal("0.02"),
    "scraper_tool":     Decimal("0.02"),
    "video_generation": Decimal("0.10"),
    "video_generate":   Decimal("0.10"),
    "video_edit":       Decimal("0.01"),
    "video_add_sound":  Decimal("0.01"),
    "web_search":       Decimal("0.005"),
    "xlsx_engine":      Decimal("0.01"),
}

_DEFAULT_TOOL_COST: Decimal = Decimal("0.01")


# Approximate USD-per-1k-output-tokens factor relative to Flash baseline.
# Used as a multiplier on the model's typical "thinking" step cost.
MODEL_PRICE_FACTOR: dict[str, Decimal] = {
    "gemini-2.5-flash":      Decimal("1.0"),
    "gemini-2.5-flash-lite": Decimal("0.5"),
    "gemini-2.5-pro":        Decimal("3.0"),
    "gemini-3.1-pro-preview": Decimal("4.0"),
    "claude-haiku":          Decimal("1.0"),
    "claude-haiku-4-5":      Decimal("1.0"),
    "claude-sonnet":         Decimal("2.5"),
    "claude-sonnet-4-5":     Decimal("2.5"),
    "claude-opus":           Decimal("8.0"),
    "claude-opus-4-1":       Decimal("8.0"),
    "gpt-4o":                Decimal("2.0"),
    "gpt-4o-mini":           Decimal("0.5"),
    "gpt-5":                 Decimal("5.0"),
}

_DEFAULT_MODEL_FACTOR: Decimal = Decimal("1.0")
# Base USD cost for a single thinking-style step on the Flash baseline.
_BASE_THINKING_COST: Decimal = Decimal("0.005")
# Base USD cost when we know nothing.
_FALLBACK_STEP_COST: Decimal = Decimal("0.01")
# Child-entity invocation: budget for one nested run by default.
_CHILD_INVOCATION_COST: Decimal = Decimal("0.10")


# Latency seed values (seconds).
_TOOL_LATENCY_S = {
    "web_search":       3,
    "batch_web_search": 8,
    "scraper_tool":     6,
    "headless_browser": 10,
    "image_generation": 15,
    "video_generation": 60,
    "video_generate":   60,
    "video_edit":       10,
    "video_add_sound":  10,
    "pdf_generator":    4,
}
_DEFAULT_TOOL_LATENCY_S = 4
_DEFAULT_THINKING_LATENCY_S = 6
_DEFAULT_CHILD_LATENCY_S = 30


__all__ = [
    "TOOL_BASELINE_COST",
    "MODEL_PRICE_FACTOR",
    "estimate_step_cost",
    "estimate_plan_cost",
    "estimate_latency_s",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def estimate_step_cost(step: Any, entity: Any = None) -> Decimal:
    """Best-effort USD cost estimate for one plan step."""
    s = _to_dict(step)
    stype = str(s.get("type", "")).upper()
    target = s.get("target") or {}
    if stype == "TOOL_CALL":
        tool_id = str(target.get("tool_id") or s.get("tool_id") or "")
        return TOOL_BASELINE_COST.get(tool_id, _DEFAULT_TOOL_COST)
    if stype == "CHILD_ENTITY_INVOCATION":
        return _CHILD_INVOCATION_COST
    if stype in ("THOUGHT", "ACTION", "RECURSE"):
        model = str(target.get("model_name") or _default_model(entity))
        factor = MODEL_PRICE_FACTOR.get(model, _DEFAULT_MODEL_FACTOR)
        return _BASE_THINKING_COST * factor
    if stype in ("READ", "NAVIGATE", "WRITE"):
        # CORTEX ops — negligible cost; embeddings dominate elsewhere.
        return Decimal("0.001")
    return _FALLBACK_STEP_COST


def estimate_plan_cost(plan: list[Any], entity: Any = None) -> Decimal:
    total = Decimal("0")
    for step in plan:
        total += estimate_step_cost(step, entity)
    return total


def estimate_latency_s(plan: list[Any]) -> int:
    """Best-effort wall-clock estimate (seconds), assuming sequential."""
    total = 0
    for step in plan:
        s = _to_dict(step)
        stype = str(s.get("type", "")).upper()
        target = s.get("target") or {}
        if stype == "TOOL_CALL":
            tool_id = str(target.get("tool_id") or "")
            total += _TOOL_LATENCY_S.get(tool_id, _DEFAULT_TOOL_LATENCY_S)
        elif stype == "CHILD_ENTITY_INVOCATION":
            total += _DEFAULT_CHILD_LATENCY_S
        elif stype in ("THOUGHT", "ACTION", "RECURSE"):
            total += _DEFAULT_THINKING_LATENCY_S
        else:
            total += 1
    return total


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _to_dict(step: Any) -> dict[str, Any]:
    if isinstance(step, dict):
        return step
    if hasattr(step, "model_dump"):
        try:
            return cast("dict[str, Any]", step.model_dump())
        except Exception:                                                   # pragma: no cover
            pass
    out: dict[str, Any] = {}
    for attr in ("step_id", "name", "type", "target"):
        v = getattr(step, attr, None)
        if v is not None:
            out[attr] = v
    return out


def _default_model(entity: Any) -> str:
    if entity is None:
        return "gemini-2.5-flash"
    lg = getattr(entity, "logic_gate", None)
    if isinstance(entity, dict):
        lg = entity.get("logic_gate")
    if isinstance(lg, dict):
        rc = lg.get("reasoning_config") or {}
        m = rc.get("model_name") or rc.get("model_override")
        if isinstance(m, str) and m:
            return m
    return "gemini-2.5-flash"
