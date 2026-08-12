"""
C4 gate — resumability chaos (G2) and cost/amplification guard (G3).

Both are awaited from inside the aggregated parity test's event loop (the
global ``AsyncSessionLocal`` engine binds to one loop; see
``test_async_child_parity`` for why). Each returns a list of violation
strings (empty == pass).

G2 (resumability): drive a PROCESS to ``WAITING_ON_CHILDREN``, drop the
``resume_parent_run`` job (simulate a worker dying after the child finished
but before the parent resumed), assert the parent is durably WAITING, then
fire the resume as a fresh worker would and assert it recovers and
COMPLETES. Also asserts ``resume_parent_run`` is idempotent.

G3 (amplification): the historical failure mode was a child becoming a full
retry loop, amplifying cost ~$11/child. Under the hermetic mock cost is $0,
so the faithful signal is *child-execution work*: the async path must spawn
the same number of child runs and do ~the same child-level LLM work as the
inline path. We drive both and compare.
"""
from __future__ import annotations

from uuid import UUID

from src.ai.schemas.enums import RunStatus
from tests.parity.hermetic import seed_parity_run
from tests.parity.worker_sim import (
    capture_enqueued_jobs,
    drive_run_to_completion,
)

_PROCESS_KW = dict(
    entity_fixture="research_process",
    input_data={"topic": "lattice cryptography in 2025"},
    child_fixtures={"test_research_agent": "research_agent"},
)


async def _seed(governance_overrides: dict | None = None) -> str:
    from src.common.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        return await seed_parity_run(
            db, governance_overrides=governance_overrides, **_PROCESS_KW
        )


async def _run_status(run_id: str) -> str:
    from sqlalchemy import select
    from src.common.database import AsyncSessionLocal
    from src.ai.orm.execution import ExecutionRun
    async with AsyncSessionLocal() as db:
        return str((await db.execute(
            select(ExecutionRun.status).where(ExecutionRun.id == UUID(run_id))
        )).scalar_one())


async def _child_work(parent_id: str) -> tuple[int, int]:
    """(child_run_count, llm_calls_on_child_runs) for a parent — the
    child-execution work that amplification would inflate."""
    from sqlalchemy import select, func
    from src.common.database import AsyncSessionLocal
    from src.ai.orm.execution import ExecutionRun, LLMInteractionLog
    async with AsyncSessionLocal() as db:
        child_ids = (await db.execute(
            select(ExecutionRun.id).where(ExecutionRun.parent_run_id == UUID(parent_id))
        )).scalars().all()
        if not child_ids:
            return 0, 0
        n_llm = (await db.execute(
            select(func.count()).select_from(LLMInteractionLog)
            .where(LLMInteractionLog.run_id.in_(child_ids))
        )).scalar() or 0
        return len(child_ids), int(n_llm)


async def check_resumability_chaos() -> list[str]:
    """G2 — crash between child-done and parent-resume; recover on a fresh
    worker. Returns violation strings."""
    from src.ai.core.arq_jobs import run_execution_recursive, resume_parent_run

    violations: list[str] = []
    parent_id = await _seed({"async_child_dispatch": True})

    async with capture_enqueued_jobs() as captured:
        # 1. Parent runs, dispatches child #1, suspends.
        await run_execution_recursive({}, parent_id)
        child_jobs = [a for (n, a) in captured if n == "run_execution_recursive"]
        captured.clear()
        if not child_jobs:
            return ["chaos: parent did not dispatch a child (no suspend)"]

        # 2. Child #1 runs to completion (it enqueues resume_parent_run).
        await run_execution_recursive({}, str(child_jobs[0][0]))
        resume_jobs = [a for (n, a) in captured if n == "resume_parent_run"]
        captured.clear()
        if not resume_jobs:
            violations.append("chaos: finished child did not enqueue a parent resume")

        # 3. CRASH: the resume job is dropped (worker dies here). The parent
        #    must be durably parked, not lost.
        status = await _run_status(parent_id)
        if status != RunStatus.WAITING_ON_CHILDREN.value:
            violations.append(
                f"chaos: after crash parent status={status}, expected "
                f"{RunStatus.WAITING_ON_CHILDREN.value} (run not durably parked)"
            )

        # 4. Fresh worker picks up the (re-enqueued/swept) resume and drives
        #    the rest — including the second child + its resume.
        await resume_parent_run({}, parent_id)
        while captured:
            name, args = captured.pop(0)
            if name == "run_execution_recursive":
                await run_execution_recursive({}, str(args[0]))
            elif name == "resume_parent_run":
                await resume_parent_run({}, str(args[0]))

    final = await _run_status(parent_id)
    if final != RunStatus.COMPLETED.value:
        violations.append(f"chaos: parent did not recover (final status={final})")

    # 5. Idempotency: a duplicate resume on a non-WAITING parent is a no-op.
    n_steps_before, _ = await _child_work(parent_id)
    await resume_parent_run({}, parent_id)
    if await _run_status(parent_id) != RunStatus.COMPLETED.value:
        violations.append("chaos: duplicate resume_parent_run disturbed a completed run")
    n_steps_after, _ = await _child_work(parent_id)
    if n_steps_after != n_steps_before:
        violations.append(
            f"chaos: duplicate resume spawned children ({n_steps_before} -> {n_steps_after})"
        )

    return violations


async def check_cost_amplification_guard() -> list[str]:
    """G3 — async child execution must not amplify vs inline. Returns
    violation strings."""
    violations: list[str] = []

    inline_id = await _seed(None)                       # flag OFF
    await drive_run_to_completion(inline_id)
    inline_runs, inline_llm = await _child_work(inline_id)

    async_id = await _seed({"async_child_dispatch": True})
    await drive_run_to_completion(async_id)
    async_runs, async_llm = await _child_work(async_id)

    if inline_runs == 0:
        violations.append("cost_guard: inline path spawned no child runs (setup error)")
        return violations

    if async_runs != inline_runs:
        violations.append(
            f"cost_guard: async spawned {async_runs} child runs vs inline "
            f"{inline_runs} (amplification)"
        )
    # Child-level LLM work should match closely; allow a little slack but
    # catch the gross (retry-loop) amplification the design warns about.
    if inline_llm and async_llm > inline_llm * 1.5:
        violations.append(
            f"cost_guard: async did {async_llm} child LLM calls vs inline "
            f"{inline_llm} (>1.5x — possible per-child amplification)"
        )

    return violations
