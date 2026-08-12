"""
tests/parity/conftest.py — fixtures + engine adapters for the parity gate.

Provides:
  * engine adapters (legacy ExecutionEngine, candidate AgentLoop),
  * a real DB session + Redis client (skips cleanly when unreachable),
  * the hermetic LLM/tool patches so the gate needs no API keys or network.

The gate compares a recorded golden (legacy engine) against a fresh
AgentLoop run on the same entity fixture. Both are produced under the
deterministic ``hermetic_llm_and_tools`` patches, so any parity violation
is attributable to the engine — which is what gates the C4 deletion.
"""
from __future__ import annotations

import os
from typing import Any, AsyncIterator

import pytest
import pytest_asyncio

from tests.parity.harness import register_engine_adapter


# ---------------------------------------------------------------------------
# Engine adapters
# ---------------------------------------------------------------------------


class LegacyAdapter:
    """The legacy ExecutionEngine.execute_run path was deleted (C4). Goldens are
    now frozen, loop-recorded regression baselines; this adapter stays
    registered (the harness expects a "legacy" key) but is never invoked by the
    parity test, which always loads a golden from disk."""
    async def run(self, db: Any, redis: Any, run_id: Any) -> None:
        raise NotImplementedError(
            "legacy ExecutionEngine.execute_run was deleted (C4); "
            "goldens are recorded from the AgentLoop"
        )


class CandidateAdapter:
    """Drives the AgentLoop the way the worker does — through
    ``run_execution_recursive`` plus the in-process arq drainer
    (``worker_sim``). Async child dispatch is the loop's sole child path, so a
    multi-child PROCESS suspends (WAITING_ON_CHILDREN) and must be resumed by
    draining the child + ``resume_parent_run`` jobs to completion. The drainer
    opens its own sessions and commits durably, mirroring a real worker."""
    async def run(self, db: Any, redis: Any, run_id: Any) -> None:
        from tests.parity.worker_sim import drive_run_to_completion
        await drive_run_to_completion(str(run_id))


register_engine_adapter("legacy", LegacyAdapter())
register_engine_adapter("candidate", CandidateAdapter())


# ---------------------------------------------------------------------------
# Live-service gating
# ---------------------------------------------------------------------------


def _db_url() -> str | None:
    try:
        from src.common.config import settings
        url = getattr(settings, "DATABASE_URL", None)
    except Exception:
        url = None
    return url or os.environ.get("DATABASE_URL")


def _redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://localhost:6379")


@pytest_asyncio.fixture
async def db() -> AsyncIterator[Any]:
    """A real, committing AsyncSession.

    Parity runs cannot use the rolled-back-savepoint pattern: the engines
    open their own ``AsyncSessionLocal`` sessions for final persistence, so
    writes must actually commit. Seeded rows use uniquely-named,
    ``parity-*`` throwaway entities; the configured DB is expected to be a
    local/test Postgres.
    """
    url = _db_url()
    if not url:
        pytest.skip("DATABASE_URL not set — parity gate needs a Postgres.")
    from sqlalchemy import text
    from src.common.database import AsyncSessionLocal
    # Connectivity probe so an unreachable DB skips rather than errors.
    try:
        async with AsyncSessionLocal() as probe:
            await probe.execute(text("SELECT 1"))
    except Exception as exc:                                            # noqa: BLE001
        pytest.skip(f"Postgres unreachable — parity gate skipped ({exc}).")
    async with AsyncSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[Any]:
    import redis.asyncio as aioredis
    try:
        client = await aioredis.from_url(_redis_url())
        await client.ping()
    except Exception as exc:                                            # noqa: BLE001
        pytest.skip(f"Redis unreachable — parity gate skipped ({exc}).")
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture(autouse=True)
def parity_patches() -> Any:
    """Apply the deterministic LLM + tool patches for every parity test.

    Autouse so candidates always run hermetically, matching how goldens
    were recorded.
    """
    from tests.parity.hermetic import hermetic_llm_and_tools
    with hermetic_llm_and_tools():
        yield
