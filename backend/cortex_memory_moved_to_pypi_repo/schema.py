"""
cortex_memory.schema — standalone schema bootstrap.

For ``pip install cortex-memory`` users who want the CORTEX tables in their own
Postgres without the host's Alembic. Creates the ``vector`` extension (pgvector)
and all package-owned tables/enums/indexes from the package ``Base``.

Within the host, the tables are managed by the host's Alembic (whose
``target_metadata`` includes ``cortex_memory.metadata``); this helper is for
independent installs and tests.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from cortex_memory.db import Base


def create_all_schema(engine: Any, *, with_pgvector: bool = True) -> None:
    """Create the pgvector extension + all CORTEX tables on a sync ``Engine``."""
    with engine.begin() as conn:
        if with_pgvector:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(conn)


async def create_all_schema_async(engine: Any, *, with_pgvector: bool = True) -> None:
    """Create the pgvector extension + all CORTEX tables on an ``AsyncEngine``."""
    async with engine.begin() as conn:
        if with_pgvector:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)


def drop_all_schema(engine: Any) -> None:
    """Drop all CORTEX tables (sync ``Engine``). For test teardown."""
    with engine.begin() as conn:
        Base.metadata.drop_all(conn)


__all__ = ["create_all_schema", "create_all_schema_async", "drop_all_schema"]
