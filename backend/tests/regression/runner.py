"""
tests/regression/runner.py — Glue between RunResult, case, and judge.

A regression "result" is the verdict you get by:

  1. Running an entity (or loading a recorded RunResult).
  2. Checking status, cost band, and timeout against the case.
  3. Asking a Judge to grade the output text.

Used by:
  * ``test_regression_cases.py`` — the pytest entry point that
    parametrises over every case YAML.
  * ``backend/scripts/replay_regression_against_goldens.py`` (future) —
    grades pre-recorded RunResults without re-running the kernel.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from tests.harness import RunResult
from tests.regression.case_schema import RegressionCase
from tests.regression.judge import DeterministicJudge, Judge, JudgeVerdict


@dataclass
class RegressionResult:
    case: RegressionCase
    run: RunResult
    judge_verdict: JudgeVerdict
    structural_failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.structural_failures and self.judge_verdict.passed

    def summary(self) -> str:
        head = f"[{self.case.case_id} {'PASS' if self.passed else 'FAIL'}] "
        if self.structural_failures:
            return head + "structural: " + "; ".join(self.structural_failures)
        return head + self.judge_verdict.summary()


def evaluate(
    case: RegressionCase,
    run: RunResult,
    judge: Optional[Judge] = None,
) -> RegressionResult:
    """Compose structural checks + judge verdict into a RegressionResult."""
    judge = judge or DeterministicJudge()
    failures: list[str] = []

    # Status
    if run.status != case.expected_status:
        failures.append(
            f"status {run.status!r} != expected {case.expected_status!r}"
        )

    # Cost band
    if case.expected_min_cost_usd is not None and run.total_cost_usd < case.expected_min_cost_usd:
        failures.append(
            f"cost ${run.total_cost_usd:.4f} below expected_min "
            f"${case.expected_min_cost_usd:.4f}"
        )
    if case.expected_max_cost_usd is not None and run.total_cost_usd > case.expected_max_cost_usd:
        failures.append(
            f"cost ${run.total_cost_usd:.4f} above expected_max "
            f"${case.expected_max_cost_usd:.4f}"
        )

    # Wall-clock timeout — if the case bounds it.
    if case.timeout_seconds and run.execution_time_ms > case.timeout_seconds * 1000:
        failures.append(
            f"wall time {run.execution_time_ms}ms exceeded "
            f"{case.timeout_seconds * 1000}ms"
        )

    verdict = judge.grade(case, run.output_text, meta={"run_id": run.run_id})
    return RegressionResult(
        case=case,
        run=run,
        judge_verdict=verdict,
        structural_failures=failures,
    )
