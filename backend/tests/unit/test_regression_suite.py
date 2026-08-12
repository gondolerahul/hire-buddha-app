"""Phase 11 — Self-tests for the regression suite scaffolding.

These tests verify the loader, judge, and runner without actually
running an entity. The regression suite proper
(``tests/regression/test_regression_cases.py`` — added at Track 2) will
parametrise over the YAML cases and call an end-to-end runner.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.harness import RunResult, StepSummary
from tests.regression.case_schema import RegressionCase
from tests.regression.judge import DeterministicJudge, JudgeVerdict
from tests.regression.loader import (
    discover_case_files,
    load_all_cases,
    load_case,
)
from tests.regression.runner import evaluate


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def test_seed_cases_present() -> None:
    files = discover_case_files()
    names = {p.stem for p in files}
    for required in (
        "simple_skill_topic_easy",
        "research_agent_brief",
        "research_process_pipeline",
    ):
        assert required in names


def test_every_case_validates() -> None:
    cases = load_all_cases()
    assert len(cases) >= 3
    for case in cases:
        # Sanity: case_id matches filename (operator hygiene).
        assert case.case_id


def test_case_cost_bounds_validated() -> None:
    """A case with min > max MUST fail to load."""
    import tempfile
    bad = (
        "case_id: bad\n"
        "entity_fixture: simple_skill\n"
        "expected_min_cost_usd: 5\n"
        "expected_max_cost_usd: 1\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(bad)
        p = Path(f.name)
    with pytest.raises(Exception):
        load_case(p)


# ---------------------------------------------------------------------------
# DeterministicJudge
# ---------------------------------------------------------------------------


def _case(**overrides) -> RegressionCase:
    base = dict(
        case_id="t",
        entity_fixture="simple_skill",
        expected_must_mention=["nist", "lattice"],
        expected_must_not_mention=["asset management"],
    )
    base.update(overrides)
    base.setdefault("acceptance", {})
    return RegressionCase.model_validate(base)


def test_judge_passes_on_clean_output() -> None:
    case = _case()
    judge = DeterministicJudge()
    v = judge.grade(case, "NIST published lattice-based FIPS-203 in 2024.")
    assert v.passed
    assert v.score == pytest.approx(1.0)


def test_judge_fails_when_required_mention_missing() -> None:
    case = _case()
    judge = DeterministicJudge()
    v = judge.grade(case, "FIPS-203 was finalised — see the related docs.")  # no 'nist' or 'lattice'
    assert not v.passed
    assert any("nist" in r for r in v.reasons)


def test_judge_fails_on_forbidden_mention() -> None:
    case = _case()
    judge = DeterministicJudge()
    v = judge.grade(
        case,
        "NIST published lattice-based crypto — useful for asset management firms.",
    )
    assert not v.passed
    assert any("forbidden" in r for r in v.reasons)


def test_judge_handles_empty_lists() -> None:
    case = _case(expected_must_mention=[], expected_must_not_mention=[])
    judge = DeterministicJudge()
    v = judge.grade(case, "any output at all")
    assert v.passed


def test_judge_respects_min_chars() -> None:
    case = _case(
        expected_must_mention=[], expected_must_not_mention=[],
        acceptance={"llm_judge_threshold": 0.7, "output_min_chars": 100},
    )
    judge = DeterministicJudge()
    v = judge.grade(case, "tiny")
    assert not v.passed


# ---------------------------------------------------------------------------
# evaluate() combines structural + judge
# ---------------------------------------------------------------------------


def _run(**overrides) -> RunResult:
    base = dict(
        run_id="r",
        entity_id="e",
        status="COMPLETED",
        total_cost_usd=0.10,
        total_tokens=500,
        execution_time_ms=2000,
        iterations=2,
        step_count=2,
        output_text="NIST published lattice-based crypto FIPS-203.",
    )
    base.update(overrides)
    return RunResult(**base)


def test_evaluate_passing_case() -> None:
    case = _case()
    run = _run()
    res = evaluate(case, run)
    assert res.passed
    assert "PASS" in res.summary()


def test_evaluate_fails_on_status_mismatch() -> None:
    case = _case(expected_status="COMPLETED")
    run = _run(status="FAILED")
    res = evaluate(case, run)
    assert not res.passed
    assert any("status" in f for f in res.structural_failures)


def test_evaluate_fails_when_cost_exceeds_max() -> None:
    case = _case(expected_max_cost_usd=0.05)
    run = _run(total_cost_usd=0.10)
    res = evaluate(case, run)
    assert not res.passed
    assert any("cost" in f for f in res.structural_failures)


def test_evaluate_fails_when_cost_below_min() -> None:
    case = _case(expected_min_cost_usd=0.50)
    run = _run(total_cost_usd=0.10)
    res = evaluate(case, run)
    assert not res.passed
    assert any("below" in f for f in res.structural_failures)


def test_evaluate_fails_on_timeout() -> None:
    case = _case(timeout_seconds=1)
    run = _run(execution_time_ms=10_000)
    res = evaluate(case, run)
    assert not res.passed
    assert any("wall time" in f for f in res.structural_failures)


def test_evaluate_fails_on_judge_verdict() -> None:
    case = _case(expected_must_mention=["nist", "lattice"])
    run = _run(output_text="A short summary with no required tokens.")
    res = evaluate(case, run)
    assert not res.passed


def test_judge_verdict_summary_formats_reasons() -> None:
    v = JudgeVerdict(passed=False, score=0.2,
                     reasons=["missing nist", "missing lattice"],
                     grader="deterministic")
    s = v.summary()
    assert "FAIL" in s and "missing nist" in s and "missing lattice" in s


# ---------------------------------------------------------------------------
# Sanity: every seeded YAML's entity_fixture resolves
# ---------------------------------------------------------------------------


def test_every_case_fixture_is_loadable() -> None:
    from tests.harness import load_entity_fixture

    for case in load_all_cases():
        # Will raise on a typo'd fixture name.
        load_entity_fixture(case.entity_fixture)
