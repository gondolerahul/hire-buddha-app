"""
tests/parity/worker_sim.py — in-process arq drainer for the async child path.

The suspend/resume child dispatch (``governance.async_child_dispatch``) runs
children as their own enqueued jobs and resumes the parent via a
``resume_parent_run`` job. The hermetic parity gate has **no live arq
worker**, so a parent driven with the flag ON would simply suspend
(``WAITING_ON_CHILDREN``) and never complete.

This module simulates the worker deterministically, in the test's own event
loop: it captures every ``ArqRedis.enqueue_job`` call and runs the
corresponding job function (``run_execution_recursive`` for a child,
``resume_parent_run`` for a parent resume) in-process until the queue is
quiescent. Both job functions open their own ``AsyncSessionLocal`` + Redis
and commit, so the final state is durably visible to a fresh extraction
session — exactly as it would be with a real worker.

Reused by the async-parity proof (PR-2) and the resumability chaos test
(PR-3).
"""
from __future__ import annotations

import contextlib
from typing import Any, AsyncIterator, Callable, Optional


@contextlib.asynccontextmanager
async def capture_enqueued_jobs() -> AsyncIterator[list[tuple[str, tuple]]]:
    """Patch ``ArqRedis.enqueue_job`` to record (name, args) instead of
    dispatching to Redis. Restores the original on exit."""
    from arq.connections import ArqRedis

    captured: list[tuple[str, tuple]] = []
    orig = ArqRedis.enqueue_job

    async def _capture(self, function: str, *args: Any, **kwargs: Any):  # noqa: ANN001
        captured.append((function, args))
        return None

    ArqRedis.enqueue_job = _capture            # type: ignore[assignment]
    try:
        yield captured
    finally:
        ArqRedis.enqueue_job = orig            # type: ignore[assignment]


async def drive_run_to_completion(
    run_id: str,
    *,
    max_jobs: int = 64,
    on_job: Optional[Callable[[str, str], None]] = None,
) -> int:
    """Drive a top-level run plus all child/resume jobs it enqueues.

    Runs ``run_execution_recursive`` for ``run_id`` (which may suspend on
    async children), then drains the captured queue in FIFO order, invoking
    each job in-process. Returns the number of jobs processed (including the
    initial run).

    ``on_job(name, arg)`` is an optional hook fired before each *drained*
    job — the chaos test uses it to inject a crash.
    """
    from src.ai.core.arq_jobs import run_execution_recursive, resume_parent_run

    _HANDLERS = {
        "run_execution_recursive": run_execution_recursive,
        "resume_parent_run": resume_parent_run,
    }

    processed = 0
    async with capture_enqueued_jobs() as captured:
        await run_execution_recursive({}, str(run_id))
        processed += 1
        while captured and processed < max_jobs:
            name, args = captured.pop(0)
            handler = _HANDLERS.get(name)
            if handler is None:
                continue  # ignore unrelated jobs (dreaming, kpi, ...)
            arg0 = str(args[0]) if args else ""
            if on_job is not None:
                on_job(name, arg0)
            await handler({}, arg0)
            processed += 1
    return processed
