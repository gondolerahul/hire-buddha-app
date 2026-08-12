"""tests/eval/runner.py — replay a corpus through a config (`07` §5).

The runner is the DB/LLM-touching half of the eval harness; the metrics math
(:mod:`tests.eval.metrics`) is pure and tested separately. A run is graded into
a :class:`RunMetrics`:

  * ``goal_hit``    — terminal status matched the case's ``expected_status`` and
    every ``expected_must_mention`` appeared (and none of ``must_not``);
  * ``cost_usd``    — the run's attributed total cost;
  * ``latency_ms``  — wall-clock for the replay;
  * ``false_pass``  — the run was graded a pass by its own critic but failed the
    corpus acceptance check (the critic-calibration signal).

It reuses the regression case schema + the parity hermetic seeding so a corpus
case is just a ``RegressionCase``. Running the AgentLoop needs Postgres + Redis;
without them the harness skips (mirrors ``tests/parity``). The ``grade``
function is pure and unit-tested.
"""
from __future__ import annotations

import time
from typing import Any, List, Optional, Sequence

from tests.eval.config import EvalConfig
from tests.eval.metrics import RunMetrics
from tests.regression.case_schema import RegressionCase


def grade(
    case: RegressionCase,
    *,
    status: str,
    output_text: str,
    cost_usd: float,
    latency_ms: int,
    critic_passed: Optional[bool] = None,
) -> RunMetrics:
    """Pure grader: turn a finished run into RunMetrics against the case."""
    text = (output_text or "").lower()
    status_ok = status == case.expected_status
    mentions_ok = all(m.lower() in text for m in case.expected_must_mention)
    forbidden_ok = all(m.lower() not in text for m in case.expected_must_not_mention)
    goal_hit = bool(status_ok and mentions_ok and forbidden_ok)

    # A false pass: the run's own critic said "good" but the corpus check fails.
    false_pass = bool(critic_passed) and not goal_hit

    return RunMetrics(
        case_id=case.case_id,
        goal_hit=goal_hit,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        false_pass=false_pass,
    )


async def _apply_config(db: Any, config: EvalConfig) -> None:
    from src.ai.core.feature_flags import FeatureFlags

    ff = FeatureFlags(db)
    for key, val in config.bool_flags.items():
        await ff.set(key, enabled=val)
    for key, num in config.numeric_flags.items():
        await ff.set(key, value_json=num)


async def run_case(
    db: Any,
    redis: Any,
    case: RegressionCase,
    config: EvalConfig,
    *,
    run_fn: Any,
) -> RunMetrics:
    """Replay one case under ``config`` and grade it.

    ``run_fn(db, redis, case) -> (status, output_text, cost_usd, critic_passed)``
    is injected so unit tests can drive the grader without a live loop, while
    the integration path passes the real AgentLoop-backed runner.
    """
    await _apply_config(db, config)
    start = time.monotonic()
    status, output_text, cost_usd, critic_passed = await run_fn(db, redis, case)
    latency_ms = int((time.monotonic() - start) * 1000)
    return grade(
        case,
        status=status,
        output_text=output_text,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        critic_passed=critic_passed,
    )


async def run_corpus(
    db: Any,
    redis: Any,
    corpus: Sequence[RegressionCase],
    config: EvalConfig,
    *,
    run_fn: Any,
) -> List[RunMetrics]:
    return [await run_case(db, redis, case, config, run_fn=run_fn) for case in corpus]
