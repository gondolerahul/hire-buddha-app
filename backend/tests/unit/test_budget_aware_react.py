"""Budget-aware REACT — Phase 12 `07` §2.

The step executor threads budget pressure into the prompt as a soft constraint
and, past a threshold, an explicit "finish, don't expand" directive. The
directive computation is a pure helper (``budget_prompt_lines``); here we lock
in its behavior and the flag defaults that gate it.
"""
from __future__ import annotations

import pytest

from src.ai.core.budget import Budget, budget_prompt_lines
from src.ai.core.feature_flags import DEFAULTS, NUMERIC_DEFAULTS, FeatureFlags


def test_below_threshold_surfaces_pressure_only() -> None:
    lines = budget_prompt_lines(0.40, 0.70)
    assert "Budget pressure" in lines
    assert "40%" in lines["Budget pressure"]
    assert "Budget directive" not in lines


def test_at_or_above_threshold_adds_directive() -> None:
    lines = budget_prompt_lines(0.70, 0.70)
    assert "Budget directive" in lines
    assert "finish" in lines["Budget directive"].lower()
    assert "do not expand" in lines["Budget directive"].lower()


def test_high_pressure_directive() -> None:
    lines = budget_prompt_lines(0.95, 0.70)
    assert "95%" in lines["Budget pressure"]
    assert "Budget directive" in lines


def test_pressure_line_tracks_budget_object() -> None:
    b = Budget(usd_max=10, usd_used=8)  # type: ignore[arg-type]
    lines = budget_prompt_lines(b.pressure, 0.70)
    assert lines["Budget pressure"] == "80% of budget consumed"
    assert "Budget directive" in lines  # 0.8 >= 0.7


def test_flag_defaults_enable_budget_aware_react() -> None:
    assert DEFAULTS["agent_loop.budget_aware_react"] is True
    assert NUMERIC_DEFAULTS["agent_loop.budget_pressure_threshold"] == 0.70


@pytest.mark.asyncio
async def test_flag_resolves_to_defaults_without_db() -> None:
    ff = FeatureFlags(None)
    assert await ff.is_on("agent_loop.budget_aware_react") is True
    assert await ff.get_float("agent_loop.budget_pressure_threshold") == pytest.approx(0.70)
