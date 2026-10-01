import json
from typing import Any

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from src.common.config import settings


def _without_nul(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {_without_nul(k): _without_nul(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_without_nul(v) for v in value]
    return value


def json_serializer(value: Any) -> str:
    """JSON for the driver, with NUL characters dropped (DM-13).

    ``jsonb`` rejects the ``\\u0000`` escape ``json.dumps`` writes for a NUL,
    and one in a tool's output would fail the whole flush. The common case
    pays one substring check.
    """
    text = json.dumps(value)
    if "\\u0000" not in text:
        return text
    return json.dumps(_without_nul(value))


# ── Connection Pool Configuration ──────────────────────────────────────────
# Deep Research spawns recursive parallel child sessions:
#   1 process + 2 agents + up to 4 skills + isolated parallel steps = ~15-20
#   concurrent connections per run, plus API server and voice services.
#
# Postgres max_connections = 100 (as configured).
# We allocate up to 60 for the worker pool, leaving ~40 for the API server.
#
# pool_size=20    : persistent connections kept open (warm)
# max_overflow=40 : extra connections allowed under load (total cap = 60)
# pool_timeout=60 : wait up to 60s for a free connection before raising
# pool_recycle=1800: recycle connections every 30min to avoid stale TCP
# pool_pre_ping=True: test connection health before use (prevents dead-conn errors)
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,           # Was True — disabled to stop logging every SQL statement
    pool_size=20,
    max_overflow=40,
    pool_timeout=60,      # Up from default 30s — give parallel steps more time
    pool_recycle=1800,
    pool_pre_ping=True,
    json_serializer=json_serializer,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

