"""
Async child-dispatch parity (C4 gate G1, async path).

PR-1 proved the multi-child PROCESS completes with children run *inline*
(``async_child_dispatch`` OFF) and matches the legacy golden. This module
proves the **suspend/resume** path (flag ON) reaches the same result:

  seed the PROCESS with the flag ON → drive it with the in-process arq
  drainer (``worker_sim``) which runs the suspended parent, its child runs,
  and the ``resume_parent_run`` jobs in-process → assert the parent
  COMPLETES and matches the same ``research_process_pipeline`` golden the
  inline path matched.

This is the first end-to-end exercise of the suspend → child → resume →
complete cycle (units only covered the pieces). It must be green before
``async_child_dispatch`` flips ON and before the C4 deletions.

**Why a helper, not its own test:** the kernel's global ``AsyncSessionLocal``
engine binds to the first event loop it is used on, and asyncpg connections
cannot cross loops. A standalone ``@pytest.mark.asyncio`` test gets its own
loop and would skip with "attached to a different loop" once another parity
test has bound the engine. So this runs *inside* the single aggregated
``test_agent_loop_parity`` loop — the same one-loop discipline the parity
README documents. ``check_async_child_dispatch_parity`` returns a list of
violation strings (empty == pass).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.harness import (
    ParityTolerance,
    RunResult,
    compare_run_results,
    deterministic_cosine_similarity,
)
from tests.parity.extract import extract_run_result
from tests.parity.hermetic import seed_parity_run
from tests.parity.worker_sim import drive_run_to_completion


GOLDEN = Path(__file__).resolve().parent / "goldens" / "research_process_pipeline.json"


async def check_async_child_dispatch_parity() -> list[str]:
    """Drive the PROCESS with async_child_dispatch ON and compare to the
    golden. Returns violation strings (empty == pass). Must be awaited from
    inside the aggregated parity test's event loop."""
    if not GOLDEN.exists():
        return []
    from src.common.database import AsyncSessionLocal

    golden = RunResult.load(GOLDEN)

    async with AsyncSessionLocal() as seed_db:
        run_id = await seed_parity_run(
            seed_db,
            entity_fixture="research_process",
            input_data={"topic": "lattice cryptography in 2025"},
            child_fixtures={"test_research_agent": "research_agent"},
            governance_overrides={"async_child_dispatch": True},
        )

    processed = await drive_run_to_completion(run_id)

    violations: list[str] = []
    if processed < 3:
        violations.append(
            f"async_child: expected suspend/resume fan-out, processed={processed} "
            "(child dispatch likely fell back to inline)"
        )

    async with AsyncSessionLocal() as ex_db:
        candidate = await extract_run_result(ex_db, str(run_id))

    if candidate.status != "COMPLETED":
        violations.append(
            f"async_child: parent did not complete (status={candidate.status})"
        )

    for v in compare_run_results(
        golden, candidate,
        ParityTolerance.hermetic(track=2),
        similarity_fn=deterministic_cosine_similarity,
    ):
        violations.append(f"async_child: {v}")

    return violations
