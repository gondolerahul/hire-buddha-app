"""tests/eval/metrics.py — A/B eval metrics + statistical delta report.

Phase 12 `07` §5: turn "we think config B is better" into "+6pp goal-hit at
−9% cost, p<0.05". This module is pure (no I/O, no DB, no LLM) so the delta
math is unit-testable; :mod:`tests.eval.runner` produces the ``RunMetrics`` it
consumes by replaying a corpus through the AgentLoop.

A "config" is a named bundle of feature-flag / numeric overrides (e.g.
deterministic-vs-LLM Strategist, critic model A-vs-B, task-classifier v1-vs-v2).
We replay the same corpus under each and compare:

  * goal_hit_rate        — fraction of cases that reached the expected outcome
  * cost_per_success     — total USD / successful cases (the efficiency lever)
  * false_pass_rate      — graded-pass but actually-wrong (critic calibration)
  * mean_latency_ms      — wall-clock per case

Rate deltas use a two-proportion z-test; continuous deltas (cost, latency) use
Welch's t-test. p-values come from the normal-approximation via ``math.erfc``
(normal/t approximation) so we need no scipy.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import Dict, List, Optional

__all__ = [
    "RunMetrics",
    "aggregate",
    "MetricDelta",
    "delta_report",
]


@dataclass
class RunMetrics:
    """Outcome of one corpus case under one config."""

    case_id: str
    goal_hit: bool
    cost_usd: float
    latency_ms: int
    false_pass: bool = False


def _normal_sf(z: float) -> float:
    """One-sided survival function of the standard normal (P(Z > z))."""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def two_sided_p_from_z(z: float) -> float:
    """Two-sided p-value for a z statistic."""
    return min(1.0, 2.0 * _normal_sf(abs(z)))


def two_proportion_p(succ_a: int, n_a: int, succ_b: int, n_b: int) -> Optional[float]:
    """Two-proportion z-test p-value, or None if undefined (empty group)."""
    if n_a == 0 or n_b == 0:
        return None
    p_a, p_b = succ_a / n_a, succ_b / n_b
    p_pool = (succ_a + succ_b) / (n_a + n_b)
    denom = p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b)
    if denom <= 0:
        # No variance (both 0% or both 100%): difference is significant only if
        # the point estimates differ, which here they don't.
        return 1.0 if p_a == p_b else 0.0
    z = (p_b - p_a) / math.sqrt(denom)
    return two_sided_p_from_z(z)


def welch_p(a: List[float], b: List[float]) -> Optional[float]:
    """Welch's t-test p-value (unequal variance), normal-approximated."""
    if len(a) < 2 or len(b) < 2:
        return None
    # Sample variance (n-1).
    va = pstdev(a) ** 2 * len(a) / (len(a) - 1) if len(a) > 1 else 0.0
    vb = pstdev(b) ** 2 * len(b) / (len(b) - 1) if len(b) > 1 else 0.0
    se = math.sqrt(va / len(a) + vb / len(b))
    if se == 0:
        return 1.0 if mean(a) == mean(b) else 0.0
    t = (mean(b) - mean(a)) / se
    # Approximate the t distribution by the normal for df not tiny; corpora
    # here are small but this is a directional indicator, not a clinical trial.
    return two_sided_p_from_z(t)


@dataclass
class ConfigAggregate:
    name: str
    n: int
    goal_hits: int
    goal_hit_rate: float
    total_cost_usd: float
    cost_per_success: Optional[float]
    false_passes: int
    false_pass_rate: float
    mean_latency_ms: float
    _costs: List[float] = field(default_factory=list, repr=False)
    _latencies: List[float] = field(default_factory=list, repr=False)


def aggregate(name: str, runs: List[RunMetrics]) -> ConfigAggregate:
    """Roll up per-case ``RunMetrics`` into one config's summary."""
    n = len(runs)
    goal_hits = sum(1 for r in runs if r.goal_hit)
    false_passes = sum(1 for r in runs if r.false_pass)
    total_cost = sum(r.cost_usd for r in runs)
    costs = [r.cost_usd for r in runs]
    latencies = [float(r.latency_ms) for r in runs]
    return ConfigAggregate(
        name=name,
        n=n,
        goal_hits=goal_hits,
        goal_hit_rate=(goal_hits / n) if n else 0.0,
        total_cost_usd=total_cost,
        cost_per_success=(total_cost / goal_hits) if goal_hits else None,
        false_passes=false_passes,
        false_pass_rate=(false_passes / n) if n else 0.0,
        mean_latency_ms=(mean(latencies) if latencies else 0.0),
        _costs=costs,
        _latencies=latencies,
    )


@dataclass
class MetricDelta:
    metric: str
    a: float
    b: float
    delta: float
    pct_change: Optional[float]
    p_value: Optional[float]

    @property
    def significant(self) -> bool:
        return self.p_value is not None and self.p_value < 0.05


def _pct_change(a: float, b: float) -> Optional[float]:
    if a == 0:
        return None
    return (b - a) / a


def delta_report(
    a: ConfigAggregate, b: ConfigAggregate
) -> Dict[str, MetricDelta]:
    """Compare config B against baseline A across the four headline metrics."""
    report: Dict[str, MetricDelta] = {}

    report["goal_hit_rate"] = MetricDelta(
        metric="goal_hit_rate",
        a=a.goal_hit_rate,
        b=b.goal_hit_rate,
        delta=b.goal_hit_rate - a.goal_hit_rate,
        pct_change=_pct_change(a.goal_hit_rate, b.goal_hit_rate),
        p_value=two_proportion_p(a.goal_hits, a.n, b.goal_hits, b.n),
    )
    report["false_pass_rate"] = MetricDelta(
        metric="false_pass_rate",
        a=a.false_pass_rate,
        b=b.false_pass_rate,
        delta=b.false_pass_rate - a.false_pass_rate,
        pct_change=_pct_change(a.false_pass_rate, b.false_pass_rate),
        p_value=two_proportion_p(a.false_passes, a.n, b.false_passes, b.n),
    )
    report["mean_latency_ms"] = MetricDelta(
        metric="mean_latency_ms",
        a=a.mean_latency_ms,
        b=b.mean_latency_ms,
        delta=b.mean_latency_ms - a.mean_latency_ms,
        pct_change=_pct_change(a.mean_latency_ms, b.mean_latency_ms),
        p_value=welch_p(a._latencies, b._latencies),
    )
    cps_a = a.cost_per_success or 0.0
    cps_b = b.cost_per_success or 0.0
    report["cost_per_success"] = MetricDelta(
        metric="cost_per_success",
        a=cps_a,
        b=cps_b,
        delta=cps_b - cps_a,
        pct_change=_pct_change(cps_a, cps_b),
        p_value=welch_p(a._costs, b._costs),
    )
    return report


def render_report(
    a: ConfigAggregate, b: ConfigAggregate, deltas: Dict[str, MetricDelta]
) -> str:
    """Human-readable one-screen summary of an A/B eval."""
    lines = [
        f"Eval: {b.name} vs {a.name}  (n={a.n} each)",
        "-" * 60,
    ]
    for key in ("goal_hit_rate", "cost_per_success", "false_pass_rate", "mean_latency_ms"):
        d = deltas[key]
        pct = f"{d.pct_change:+.1%}" if d.pct_change is not None else "n/a"
        p = f"p={d.p_value:.3f}" if d.p_value is not None else "p=n/a"
        sig = " *" if d.significant else ""
        lines.append(f"{key:>18}: {d.a:.4g} -> {d.b:.4g} ({pct}, {p}){sig}")
    return "\n".join(lines)
