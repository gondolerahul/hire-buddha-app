"""
Parity gate — legacy ExecutionEngine vs. the new AgentLoop.

For each recorded golden snapshot (produced by
``python -m scripts.record_golden_runs``), this test:

  1. seeds a fresh tenant + entity + run from the same fixture,
  2. runs the **candidate** (AgentLoop) under the deterministic hermetic
     patches (mock LLM + stubbed web_search — see ``hermetic.py``),
  3. extracts a ``RunResult`` and compares it to the golden with
     ``ParityTolerance.hermetic`` (status exact, cost band, step delta,
     output cosine ≥ floor; wall-time disabled because mock timing is
     infra-noise).

Because the LLM is held constant, any violation is attributable to the
engine — which is exactly the evidence required before deleting the
legacy engine (plan ``01`` C4 / risk R1 in ``08``).

SKIP conditions (so the suite stays green where infra is absent):
  * no golden snapshots on disk, OR
  * DATABASE_URL unset / Postgres unreachable / Redis unreachable
    (handled by the ``db`` / ``redis_client`` fixtures in conftest).

The map ``case_id -> regression-case fixture/input`` is derived from the
YAML cases the goldens were recorded from.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.harness import ParityTolerance, RunResult
from tests.parity.harness import ParityCase, run_parity_case


GOLDENS_DIR = Path(__file__).resolve().parent / "goldens"
CASES_DIR = Path(__file__).resolve().parents[1] / "regression" / "cases"


def _available_goldens() -> list[Path]:
    if not GOLDENS_DIR.exists():
        return []
    return [p for p in GOLDENS_DIR.glob("*.json") if p.name != ".gitkeep"]


def _case_for(golden: Path) -> ParityCase:
    """Build a ParityCase from the regression YAML the golden mirrors."""
    from tests.regression.loader import load_case
    case = load_case(CASES_DIR / f"{golden.stem}.yaml")
    return ParityCase(
        case_id=golden.stem,
        fixture_name=case.entity_fixture,
        input_data=case.input,
        track=2,
        child_fixtures=case.child_fixtures,
    )


pytestmark = pytest.mark.parity


def test_parity_conftest_registers_engines() -> None:
    """Sanity: both engine adapters are registered so the harness runs."""
    from tests.parity.harness import ENGINE_ADAPTERS
    assert "legacy" in ENGINE_ADAPTERS
    assert "candidate" in ENGINE_ADAPTERS


@pytest.mark.skipif(
    not _available_goldens(),
    reason="No golden snapshots — run `python -m scripts.record_golden_runs`.",
)
@pytest.mark.asyncio
async def test_agent_loop_parity(db, redis_client) -> None:
    """The AgentLoop matches every recorded legacy golden within tolerance.

    All cases run inside a **single event loop** on purpose: the kernel's
    global ``AsyncSessionLocal`` engine binds to the loop it is first used
    on, and asyncpg connections cannot cross event loops. Parametrising
    one-test-per-loop trips that, so we iterate here instead and aggregate
    per-case results.
    """
    goldens = _available_goldens()
    failures: list[str] = []
    ran = 0

    for golden_path in goldens:
        baseline = RunResult.load(golden_path)
        case = _case_for(golden_path)
        report = await run_parity_case(
            db,
            redis_client,
            case,
            golden_path=golden_path,
            tolerance=ParityTolerance.hermetic(track=case.track),
        )
        ran += 1
        head = (
            f"[{case.case_id}] golden(status={baseline.status} "
            f"cost=${baseline.total_cost_usd:.4f} steps={baseline.step_count}) "
            f"vs loop(status={report.candidate.status} "
            f"cost=${report.candidate.total_cost_usd:.4f} "
            f"steps={report.candidate.step_count})"
        )
        if not report.passed:
            failures.append(head + "\n" + report.summary())

    # C4 gate checks that drive their own runs — kept in THIS loop so the
    # global AsyncSessionLocal engine stays bound to one event loop.
    from tests.parity.test_async_child_parity import (
        check_async_child_dispatch_parity,
    )
    from tests.parity.c4_resumability import (
        check_resumability_chaos,
        check_cost_amplification_guard,
    )
    failures.extend(await check_async_child_dispatch_parity())   # G1 (async)
    failures.extend(await check_resumability_chaos())            # G2
    failures.extend(await check_cost_amplification_guard())      # G3

    assert ran > 0, "No parity cases executed."
    assert not failures, "Parity violations:\n" + "\n".join(failures)
