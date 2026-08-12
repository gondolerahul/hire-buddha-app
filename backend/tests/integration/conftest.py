"""
tests/integration/conftest.py — shared fixtures for Phase 11 integration tests.

These tests:
  * Hit a real Postgres (``DATABASE_URL`` from env, same as the app).
  * Use the MockLLMRouter fixture so no live LLM calls are made.
  * Each test runs in its own SAVEPOINT and rolls back at teardown so
    the DB stays clean across the suite.

Marker convention:
  * ``@pytest.mark.needs_db`` — skipped when there's no DB.
  * ``@pytest.mark.slow``     — excluded from PR-fast CI lane.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, AsyncIterator
from uuid import UUID

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# DB session
# ---------------------------------------------------------------------------


def _db_url() -> str | None:
    """Resolve the DB URL the same way the app does.

    Returns None when no DB is reachable so the whole suite skips
    gracefully (CI without a Postgres sidecar).
    """
    try:
        from src.common.config import settings
        url = getattr(settings, "DATABASE_URL", None)
    except Exception:
        url = None
    return url or os.environ.get("DATABASE_URL")


@pytest_asyncio.fixture
async def _engine():
    """Function-scoped async engine.

    asyncpg can't share connections across event loops, and
    pytest-asyncio gives each test its own loop. A new engine per test
    is the price of clean isolation; the reconnect overhead is
    negligible against the DB ops the tests do.
    """
    url = _db_url()
    if not url:
        pytest.skip("DATABASE_URL not set; integration suite skipped")
    from sqlalchemy.ext.asyncio import create_async_engine
    eng = create_async_engine(url, pool_pre_ping=True, future=True)
    try:
        async with eng.connect() as conn:
            from sqlalchemy import text
            await conn.execute(text("SELECT 1"))
    except Exception as exc:                                                  # noqa: BLE001
        await eng.dispose()
        pytest.skip(f"Postgres unreachable; integration suite skipped ({exc})")
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def db(_engine) -> AsyncIterator[Any]:
    """Per-test async session wrapped in a SAVEPOINT.

    Every write the test does is rolled back at teardown, so the
    suite is order-independent and doesn't leak fixture rows.
    """
    from sqlalchemy.ext.asyncio import AsyncSession
    async with _engine.connect() as conn:
        trans = await conn.begin()
        async_session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield async_session
        finally:
            await async_session.close()
            await trans.rollback()


# ---------------------------------------------------------------------------
# Test-tenant scope
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def test_company_id(db) -> UUID:
    """Find or create a throwaway company row for the test session."""
    from sqlalchemy import text
    cid = uuid.uuid4()
    await db.execute(
        text(
            """
            INSERT INTO companies (id, name, type, status, created_at, updated_at)
            VALUES (:id, :name, 'TENANT', 'active', now(), now())
            """
        ),
        {"id": str(cid), "name": f"integration-test-{cid.hex[:8]}"},
    )
    await db.flush()
    return cid


# ---------------------------------------------------------------------------
# Shared LLM + embedding doubles — see tests/fixtures/llm_fixture.py
# ---------------------------------------------------------------------------


from tests.fixtures.llm_fixture import (  # noqa: E402 (after pytest imports)
    MockLLMRouter, deterministic_embedding, cosine_similarity,
)


@pytest.fixture
def mock_llm() -> MockLLMRouter:
    return MockLLMRouter()


