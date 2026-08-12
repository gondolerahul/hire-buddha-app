"""
tests/harness/run_result.py — RunResult dataclass + tolerance comparator.

A ``RunResult`` is the post-hoc, serialisable summary of an
``ExecutionRun``. It is the unit of comparison used by:

  * ``backend/tests/parity/`` — compare legacy ExecutionEngine vs new
    AgentLoop on the same fixture (Phase 11 Tracks 2-8).
  * ``backend/tests/regression/`` — assert pass/fail and cost bands
    against expected_* YAML fields (nightly).
  * ``backend/scripts/record_golden_runs.py`` — record snapshots before
    Track 2 begins.

The shape was chosen to be:

  * Cheap to serialise to JSON (no UUIDs except as strings).
  * Sufficient to support the §4.3 acceptance contract:
      - final status equality
      - total cost ±X%
      - output cosine similarity ≥ Y
      - iterations / steps count ±N
      - wall time ±Z%
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class StepSummary:
    """Per-step shape captured from a run."""
    step_id: str
    name: str
    type: str
    status: str                     # "success" | "fail" | "skipped" | ...
    cost_usd: float = 0.0
    latency_ms: int = 0
    tool_id: Optional[str] = None
    output_len: int = 0


@dataclass
class RunResult:
    """Post-hoc snapshot of an ExecutionRun.

    All fields are JSON-serialisable. UUIDs are stored as their string
    forms. Output text is captured verbatim (potentially large) so that
    output-similarity checks can hash or embed it.
    """
    run_id: str
    entity_id: str
    status: str
    total_cost_usd: float
    total_tokens: int
    execution_time_ms: int
    iterations: int                 # iterations the agent loop ran (legacy: == step count)
    step_count: int
    error_message: Optional[str] = None
    output_text: str = ""
    plan_step_types: list[str] = field(default_factory=list)
    steps: list[StepSummary] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RunResult":
        steps_data = payload.get("steps", []) or []
        steps = [StepSummary(**s) for s in steps_data]
        return cls(
            run_id=payload["run_id"],
            entity_id=payload["entity_id"],
            status=payload["status"],
            total_cost_usd=float(payload.get("total_cost_usd", 0.0)),
            total_tokens=int(payload.get("total_tokens", 0)),
            execution_time_ms=int(payload.get("execution_time_ms", 0)),
            iterations=int(payload.get("iterations", payload.get("step_count", 0))),
            step_count=int(payload.get("step_count", 0)),
            error_message=payload.get("error_message"),
            output_text=payload.get("output_text", ""),
            plan_step_types=list(payload.get("plan_step_types", [])),
            steps=steps,
            meta=dict(payload.get("meta", {})),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str))

    @classmethod
    def load(cls, path: Path) -> "RunResult":
        return cls.from_dict(json.loads(path.read_text()))


@dataclass
class ParityTolerance:
    """Per-Track parity tolerance budget.

    Mirrors §4.3 of `14_test_strategy.md`. Cost tolerance is the only
    thing that meaningfully varies by Track; defaults are Track-2 values.
    """
    cost_pct: float = 0.05
    output_similarity_min: float = 0.85
    step_count_delta: int = 2
    wall_time_pct: float = 0.25
    # Wall-clock parity is only meaningful when the LLM/tooling cost real
    # time. Under the hermetic parity gate (deterministic mock LLM, stubbed
    # tools) both engines finish sub-second, so timing is infra-noise rather
    # than an engine signal — set this False there.
    check_wall_time: bool = True

    @classmethod
    def for_track(cls, track: int) -> "ParityTolerance":
        # Per §4.3.
        if track in (2, 6):
            return cls(cost_pct=0.05)
        if track == 3:
            return cls(cost_pct=0.15)
        if track == 7:
            return cls(cost_pct=0.10)
        return cls()

    @classmethod
    def hermetic(cls, track: int = 2) -> "ParityTolerance":
        """Tolerance for the key-free hermetic gate: real status/cost/step/
        output checks, but wall-time disabled (mock timing is meaningless)."""
        base = cls.for_track(track)
        base.check_wall_time = False
        return base


@dataclass
class ParityViolation:
    metric: str
    expected: Any
    actual: Any
    detail: str

    def __str__(self) -> str:
        return (
            f"PARITY({self.metric}): expected={self.expected!r} "
            f"actual={self.actual!r} — {self.detail}"
        )


def compare_run_results(
    baseline: RunResult,
    candidate: RunResult,
    tolerance: ParityTolerance,
    *,
    similarity_fn=None,
) -> list[ParityViolation]:
    """Return a list of parity violations (empty list ⇒ pass).

    ``similarity_fn`` MUST be passed when an output-text comparison is
    desired; the harness has no implicit dependency on real embeddings.
    Pass ``tests.harness.embeddings.deterministic_cosine_similarity``
    for offline runs, or a real embedding-backed cosine for online.
    """
    violations: list[ParityViolation] = []

    # 1. Final status MUST match exactly.
    if baseline.status != candidate.status:
        violations.append(
            ParityViolation(
                metric="status",
                expected=baseline.status,
                actual=candidate.status,
                detail="status MUST match",
            )
        )

    # 2. Cost — multiplicative band.
    if baseline.total_cost_usd > 0:
        ratio = abs(candidate.total_cost_usd - baseline.total_cost_usd) / baseline.total_cost_usd
        if ratio > tolerance.cost_pct:
            violations.append(
                ParityViolation(
                    metric="cost_usd",
                    expected=baseline.total_cost_usd,
                    actual=candidate.total_cost_usd,
                    detail=(
                        f"deviation {ratio:.2%} exceeds tolerance "
                        f"{tolerance.cost_pct:.0%}"
                    ),
                )
            )
    else:
        # Baseline cost is zero — any non-zero candidate cost is a violation
        # only if it's not trivially small (e.g. $0.001).
        if candidate.total_cost_usd > 0.005:
            violations.append(
                ParityViolation(
                    metric="cost_usd",
                    expected=baseline.total_cost_usd,
                    actual=candidate.total_cost_usd,
                    detail="baseline zero-cost, candidate above floor",
                )
            )

    # 3. Step count — additive delta.
    if abs(candidate.step_count - baseline.step_count) > tolerance.step_count_delta:
        violations.append(
            ParityViolation(
                metric="step_count",
                expected=baseline.step_count,
                actual=candidate.step_count,
                detail=f"|Δ| > {tolerance.step_count_delta}",
            )
        )

    # 4. Wall time — multiplicative band (skipped when disabled).
    if tolerance.check_wall_time and baseline.execution_time_ms > 0:
        wall_ratio = abs(
            candidate.execution_time_ms - baseline.execution_time_ms
        ) / baseline.execution_time_ms
        if wall_ratio > tolerance.wall_time_pct:
            violations.append(
                ParityViolation(
                    metric="execution_time_ms",
                    expected=baseline.execution_time_ms,
                    actual=candidate.execution_time_ms,
                    detail=(
                        f"deviation {wall_ratio:.2%} exceeds tolerance "
                        f"{tolerance.wall_time_pct:.0%}"
                    ),
                )
            )

    # 5. Output similarity — only if both have non-empty output and a
    #    similarity_fn was supplied.
    if (
        similarity_fn is not None
        and baseline.output_text
        and candidate.output_text
    ):
        sim = similarity_fn(baseline.output_text, candidate.output_text)
        if sim < tolerance.output_similarity_min:
            violations.append(
                ParityViolation(
                    metric="output_similarity",
                    expected=tolerance.output_similarity_min,
                    actual=sim,
                    detail=f"cosine {sim:.3f} below floor",
                )
            )

    return violations
