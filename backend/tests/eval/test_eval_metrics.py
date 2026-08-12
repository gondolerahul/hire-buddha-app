"""Eval-harness metrics + grader — Phase 12 `07` §5.

Pure unit tests (no DB/LLM) for the statistical delta report and the run
grader. The corpus-replay runner is exercised by the DB-gated integration path.
"""
from __future__ import annotations

import pytest

from tests.eval.config import BASELINE, EvalConfig
from tests.eval.metrics import (
    RunMetrics,
    aggregate,
    delta_report,
    render_report,
    two_proportion_p,
    welch_p,
)
from tests.eval.runner import grade
from tests.regression.case_schema import RegressionCase


def _runs(goal_hits: int, n: int, *, cost: float = 0.1, latency: int = 100,
          false_passes: int = 0) -> list[RunMetrics]:
    runs = []
    for i in range(n):
        runs.append(
            RunMetrics(
                case_id=f"c{i}",
                goal_hit=i < goal_hits,
                cost_usd=cost,
                latency_ms=latency,
                false_pass=i < false_passes,
            )
        )
    return runs


def test_aggregate_basic() -> None:
    agg = aggregate("a", _runs(8, 10, cost=0.2))
    assert agg.n == 10
    assert agg.goal_hit_rate == 0.8
    assert agg.total_cost_usd == 2.0
    assert agg.cost_per_success == 0.25  # 2.0 / 8


def test_aggregate_no_success_cost_per_success_none() -> None:
    agg = aggregate("a", _runs(0, 5))
    assert agg.goal_hit_rate == 0.0
    assert agg.cost_per_success is None


def test_delta_report_directions() -> None:
    a = aggregate("baseline", _runs(5, 10, cost=0.2, latency=200))
    b = aggregate("candidate", _runs(8, 10, cost=0.1, latency=120))
    rep = delta_report(a, b)
    # B improves goal-hit (+0.3) and reduces latency.
    assert rep["goal_hit_rate"].delta == pytest.approx(0.3)
    assert rep["mean_latency_ms"].delta == pytest.approx(-80.0)
    assert rep["mean_latency_ms"].pct_change is not None
    # render_report doesn't raise and includes the headline metrics.
    text = render_report(a, b, rep)
    assert "goal_hit_rate" in text and "cost_per_success" in text


def test_two_proportion_p_detects_large_difference() -> None:
    # 1/100 vs 60/100 is wildly significant.
    p = two_proportion_p(1, 100, 60, 100)
    assert p is not None and p < 0.001


def test_two_proportion_p_no_difference() -> None:
    p = two_proportion_p(50, 100, 50, 100)
    assert p == 1.0 or (p is not None and p > 0.5)


def test_two_proportion_p_empty_group() -> None:
    assert two_proportion_p(0, 0, 1, 5) is None


def test_welch_p_separated_means_significant() -> None:
    a = [1.0, 1.1, 0.9, 1.05, 0.95]
    b = [5.0, 5.1, 4.9, 5.05, 4.95]
    p = welch_p(a, b)
    assert p is not None and p < 0.001


def test_welch_p_too_few_samples() -> None:
    assert welch_p([1.0], [2.0]) is None


def test_significant_flag() -> None:
    a = aggregate("a", _runs(1, 50))
    b = aggregate("b", _runs(45, 50))
    rep = delta_report(a, b)
    assert rep["goal_hit_rate"].significant is True


# --------------------------------------------------------------------------- #
# grader
# --------------------------------------------------------------------------- #
def _case(**kw) -> RegressionCase:
    base = dict(case_id="t1", entity_fixture="fx", expected_status="COMPLETED")
    base.update(kw)
    return RegressionCase(**base)


def test_grade_goal_hit() -> None:
    case = _case(expected_must_mention=["revenue"], expected_must_not_mention=["error"])
    m = grade(case, status="COMPLETED", output_text="Total revenue is up",
              cost_usd=0.3, latency_ms=500)
    assert m.goal_hit is True
    assert m.false_pass is False


def test_grade_status_mismatch_fails() -> None:
    case = _case()
    m = grade(case, status="FAILED", output_text="x", cost_usd=0.1, latency_ms=10)
    assert m.goal_hit is False


def test_grade_missing_mention_fails() -> None:
    case = _case(expected_must_mention=["revenue"])
    m = grade(case, status="COMPLETED", output_text="nothing here",
              cost_usd=0.1, latency_ms=10)
    assert m.goal_hit is False


def test_grade_false_pass_when_critic_passed_but_wrong() -> None:
    case = _case(expected_must_mention=["revenue"])
    m = grade(case, status="COMPLETED", output_text="nothing here",
              cost_usd=0.1, latency_ms=10, critic_passed=True)
    assert m.goal_hit is False
    assert m.false_pass is True


def test_config_describe() -> None:
    cfg = EvalConfig(name="llm_strategist", bool_flags={"agent_loop.llm_strategist_enabled": True})
    assert "llm_strategist" in cfg.describe()
    assert "agent_loop.llm_strategist_enabled=True" in cfg.describe()
    assert BASELINE.describe() == "baseline(defaults)"
