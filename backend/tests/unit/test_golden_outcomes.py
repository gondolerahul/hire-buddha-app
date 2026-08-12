"""TestDriver golden outcomes — Phase 12 `06` §4.4.

Hermetic: pure capture/compare over SuiteResult. Locks in that goldens snapshot
only passed cases, regressions are detected (changed output / now-failing /
missing), whitespace is normalised, and an empty golden set passes.
"""
from __future__ import annotations

from decimal import Decimal

from src.ai.meta.board.golden_outcomes import (
    capture_goldens,
    goldens_passed,
    regression_against_goldens,
)
from src.ai.meta.board.test_driver import SuiteResult, TestCaseResult


def _suite(*cases):
    s = SuiteResult()
    s.cases.extend(cases)
    return s


def test_capture_only_passed_cases() -> None:
    suite = _suite(
        TestCaseResult(name="smoke", passed=True, output="pong"),
        TestCaseResult(name="boundary:empty", passed=False, output="err"),
        TestCaseResult(name="hostile:x", passed=True, skipped=True, output="skip"),
    )
    g = capture_goldens(suite)
    assert g == {"smoke": "pong"}


def test_no_diff_when_outputs_match() -> None:
    goldens = {"smoke": "pong"}
    suite = _suite(TestCaseResult(name="smoke", passed=True, output="pong"))
    assert regression_against_goldens(suite, goldens).ok
    assert goldens_passed(suite, goldens)


def test_regressed_output_detected() -> None:
    goldens = {"smoke": "pong"}
    suite = _suite(TestCaseResult(name="smoke", passed=True, output="DIFFERENT"))
    cmp = regression_against_goldens(suite, goldens)
    assert not cmp.ok
    assert cmp.diffs[0].kind == "regressed"


def test_now_failing_detected() -> None:
    goldens = {"smoke": "pong"}
    suite = _suite(TestCaseResult(name="smoke", passed=False, output="pong"))
    assert regression_against_goldens(suite, goldens).diffs[0].kind == "now_failing"


def test_missing_case_detected() -> None:
    goldens = {"smoke": "pong"}
    suite = _suite(TestCaseResult(name="other", passed=True, output="x"))
    assert regression_against_goldens(suite, goldens).diffs[0].kind == "missing"


def test_whitespace_normalised() -> None:
    goldens = {"smoke": "a b c"}
    suite = _suite(TestCaseResult(name="smoke", passed=True, output="a   b\n c"))
    assert regression_against_goldens(suite, goldens).ok


def test_empty_goldens_pass() -> None:
    assert goldens_passed(_suite(), {})
