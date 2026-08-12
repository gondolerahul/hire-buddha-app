"""Phase 11 Track 5 — TestDriver suite logic tests (no live runner)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.ai.meta.board.test_driver import (
    SuiteResult,
    TestCaseResult,
    TestDriver,
)


def _make_runner(*, cost_per_case: Decimal = Decimal("0.10"),
                 pass_predicate=lambda name: True):
    async def runner(name, payload, remaining):
        return TestCaseResult(
            name=name,
            passed=pass_predicate(name),
            output=f"ran {name}",
            cost_usd=cost_per_case,
        )
    return runner


# ---------------------------------------------------------------------------
# Smoke gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_smoke_failure_stops_suite() -> None:
    runner = _make_runner(pass_predicate=lambda name: name != "smoke")
    suite = await TestDriver(runner, budget_usd=Decimal("3.0")).run(
        draft_entity={"name": "x"},
    )
    assert suite.cases[0].name == "smoke"
    assert not suite.cases[0].passed
    assert len(suite.cases) == 1
    assert not suite.passed


# ---------------------------------------------------------------------------
# Budget exhaustion path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_exhausted_marks_remaining_skipped() -> None:
    # Budget of 0.20 → smoke (0.10) passes, second case (0.10) lands at exactly
    # the budget so the next ones are skipped.
    runner = _make_runner(cost_per_case=Decimal("0.10"))
    suite = await TestDriver(runner, budget_usd=Decimal("0.20")).run(
        draft_entity={"name": "x"},
    )
    skipped = [c for c in suite.cases if c.skipped]
    assert len(skipped) >= 1
    assert suite.budget_exhausted
    # Smoke + at least one boundary attempted, rest skipped.
    assert suite.cases[0].name == "smoke" and suite.cases[0].passed


# ---------------------------------------------------------------------------
# Regression path (ADAPT only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_runs_when_source_entity_present() -> None:
    runner = _make_runner()
    suite = await TestDriver(runner, budget_usd=Decimal("3.0")).run(
        draft_entity={"name": "x"},
        source_entity="src-1",
    )
    names = [c.name for c in suite.cases]
    assert "smoke" in names
    assert "regression" in names


@pytest.mark.asyncio
async def test_no_regression_when_source_absent() -> None:
    runner = _make_runner()
    suite = await TestDriver(runner, budget_usd=Decimal("3.0")).run(
        draft_entity={"name": "x"},
    )
    names = [c.name for c in suite.cases]
    assert "regression" not in names


# ---------------------------------------------------------------------------
# Comparative — only when candidate present + budget remaining
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_comparative_runs_with_candidate() -> None:
    runner = _make_runner()
    suite = await TestDriver(runner, budget_usd=Decimal("3.0")).run(
        draft_entity={"name": "x"},
        comparative_candidate="other-entity",
    )
    names = [c.name for c in suite.cases]
    assert "comparative" in names


# ---------------------------------------------------------------------------
# Runner exception is caught
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_exception_marks_case_failed() -> None:
    async def runner(name, payload, remaining):
        raise RuntimeError("boom")
    suite = await TestDriver(runner).run(draft_entity={"name": "x"})
    assert not suite.passed
    assert suite.cases[0].notes.startswith("runner error: RuntimeError")
