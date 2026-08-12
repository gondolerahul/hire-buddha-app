"""
Test fixtures for the cortex_memory package.

Pure-logic tests need nothing. The integration tests need a Postgres with the
``vector`` extension; they are skipped unless ``CORTEX_TEST_DATABASE_URL`` (or
``DATABASE_URL``) points at one. The schema is bootstrapped via the package's
own ``create_all_schema_async`` (idempotent), and each test uses throwaway
UUIDs so it never collides with existing rows.
"""
from __future__ import annotations

import os
from typing import Any, AsyncIterator

import pytest
import pytest_asyncio


def _db_url() -> str | None:
    url = os.environ.get("CORTEX_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        return None
    # Normalise to the asyncpg driver.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[Any]:
    # Function-scoped + NullPool: pytest-asyncio gives each test its own event
    # loop, and an asyncpg connection cannot cross loops. A fresh engine per
    # test (no pooled connections) avoids "another operation is in progress".
    url = _db_url()
    if not url:
        pytest.skip("No CORTEX_TEST_DATABASE_URL / DATABASE_URL — integration tests skipped.")
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from cortex_memory.schema import create_all_schema_async

    eng = create_async_engine(url, future=True, poolclass=NullPool)
    try:
        from sqlalchemy import text

        async with eng.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        await eng.dispose()
        pytest.skip(f"Postgres unreachable — integration tests skipped ({exc}).")
    await create_all_schema_async(eng)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def db(engine: Any) -> AsyncIterator[Any]:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
