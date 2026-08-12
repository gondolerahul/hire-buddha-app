"""
tests/parity/harness.py — Run legacy vs. new agent kernel and compare.

Used by Track 2+ to assert ``agent_loop.enabled=ON`` produces output
within tolerance of ``agent_loop.enabled=OFF`` on the same fixture
input. Not invoked yet — Track 2 wires up the actual feature flag and
agent loop.

Public surface:

    @dataclass
    class ParityCase:
        case_id: str
        fixture_name: str
        input_data: dict
        track: int = 2

    async def run_parity_case(db, redis, case, *, golden_path=None) -> ParityReport
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from tests.harness import (
    ParityTolerance,
    ParityViolation,
    RunResult,
    compare_run_results,
    deterministic_cosine_similarity,
    load_entity_fixture,
)
from tests.parity.extract import extract_run_result

# How to invoke the legacy vs. new engine is intentionally pluggable —
# the wiring lands in Track 2. For now, parity tests are SKIPPED when
# this module is imported but no engine adapter has been registered.
ENGINE_ADAPTERS: dict[str, Any] = {}


def register_engine_adapter(name: str, adapter: Any) -> None:
    """Register an engine adapter. Called by Track 2 setup.

    The adapter must expose: ``await adapter.run(db, redis, run_id) -> None``.
    """
    ENGINE_ADAPTERS[name] = adapter


@dataclass
class ParityCase:
    case_id: str
    fixture_name: str
    input_data: dict[str, Any]
    track: int = 2
    company_id: Optional[str] = None       # if None, harness creates a tenant
    user_id: Optional[str] = None
    child_fixtures: dict[str, str] = field(default_factory=dict)


@dataclass
class ParityReport:
    case: ParityCase
    baseline: RunResult
    candidate: RunResult
    violations: list[ParityViolation] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.violations

    def summary(self) -> str:
        head = (
            f"[parity {'PASS' if self.passed else 'FAIL'}] "
            f"case={self.case.case_id} "
            f"track={self.case.track} fixture={self.case.fixture_name}"
        )
        if self.passed:
            return head
        body = "\n".join(f"  - {v}" for v in self.violations)
        return f"{head}\n{body}"


async def run_parity_case(
    db: Any,
    redis: Any,
    case: ParityCase,
    *,
    golden_path: Optional[Path] = None,
    tolerance: Optional[ParityTolerance] = None,
) -> ParityReport:
    """Execute the case against legacy + candidate, return a report.

    If ``golden_path`` is provided, the baseline is loaded from disk
    instead of running the legacy engine. This is how Track 2+ should
    use the harness in CI: pre-recorded goldens stay in the repo, and
    only the candidate engine actually executes per PR.

    Raises ``RuntimeError`` if engine adapters are not yet registered
    AND no golden_path is provided.
    """
    # 1. Load fixture (validates against the schemas package — sanity check
    #    that the harness sees the same shapes the kernel uses).
    load_entity_fixture(case.fixture_name)

    # 2. Baseline: load golden snapshot OR run legacy engine.
    if golden_path is not None:
        baseline = RunResult.load(Path(golden_path))
    else:
        if "legacy" not in ENGINE_ADAPTERS:
            raise RuntimeError(
                "No legacy engine adapter registered AND no golden_path "
                "supplied — cannot establish a parity baseline."
            )
        baseline_run_id = await _seed_run(db, case, flag="legacy")
        await ENGINE_ADAPTERS["legacy"].run(db, redis, baseline_run_id)
        baseline = await extract_run_result(db, baseline_run_id)

    # 3. Candidate: run the new engine.
    if "candidate" not in ENGINE_ADAPTERS:
        raise RuntimeError(
            "No candidate engine adapter registered — Track 2 must "
            "register one before parity tests can execute."
        )
    candidate_run_id = await _seed_run(db, case, flag="candidate")
    await ENGINE_ADAPTERS["candidate"].run(db, redis, candidate_run_id)
    # The candidate is driven through the in-process drainer, which writes via
    # its own committed sessions. Extract on a fresh session so the read sees
    # the durable final state, not this fixture session's stale identity map.
    from src.common.database import AsyncSessionLocal
    async with AsyncSessionLocal() as _ex_db:
        candidate = await extract_run_result(_ex_db, candidate_run_id)

    violations = compare_run_results(
        baseline,
        candidate,
        tolerance or ParityTolerance.for_track(case.track),
        similarity_fn=deterministic_cosine_similarity,
    )
    return ParityReport(case=case, baseline=baseline, candidate=candidate,
                        violations=violations)


async def _seed_run(db: Any, case: ParityCase, *, flag: str) -> str:
    """Insert a fresh company + entity + PENDING run for the case.

    ``flag`` is informational only ("legacy"/"candidate"); the engine
    choice is made by the caller via the registered adapter. Both engines
    receive an identically-seeded run so any divergence is the engine's.
    """
    import uuid as _uuid
    from tests.parity.hermetic import seed_parity_run

    company_id = _uuid.UUID(case.company_id) if case.company_id else None
    return await seed_parity_run(
        db,
        entity_fixture=case.fixture_name,
        input_data=case.input_data,
        company_id=company_id,
        child_fixtures=case.child_fixtures,
    )
