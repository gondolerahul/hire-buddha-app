import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import Pool
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


# ── Timestamps: stored as timestamptz, naive UTC in Python (DM-12) ─────────
# Every column is ``timestamp with time zone``. The code's contract stays what
# it was — naive datetimes meaning UTC (``datetime.utcnow``) — so on every
# asyncpg connection, whichever engine made it, the session time zone is UTC
# (``now()``, ``date_trunc`` and ``::date`` work in UTC) and this codec converts
# at the driver: a naive value is written as UTC, an aware one is converted, and
# reads come back naive UTC — raw SQL included.
_PG_EPOCH = datetime(2000, 1, 1)
_PG_INFINITY, _PG_NEG_INFINITY = 2**63 - 1, -(2**63)


def _encode_utc(value: datetime) -> tuple[int]:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    if value == datetime.max:
        return (_PG_INFINITY,)
    if value == datetime.min:
        return (_PG_NEG_INFINITY,)
    delta = value - _PG_EPOCH
    return ((delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds,)


def _decode_utc(value: tuple[int]) -> datetime:
    micros = value[0]
    if micros == _PG_INFINITY:
        return datetime.max
    if micros == _PG_NEG_INFINITY:
        return datetime.min
    return _PG_EPOCH + timedelta(microseconds=micros)


@event.listens_for(Pool, "connect")
def _utc_session(dbapi_connection: Any, connection_record: Any) -> None:
    run_async = getattr(dbapi_connection, "run_async", None)
    if run_async is None:  # not asyncpg
        return

    async def setup(conn: Any) -> None:
        await conn.execute("SET TIME ZONE 'UTC'")
        await conn.set_type_codec("timestamptz", schema="pg_catalog", encoder=_encode_utc,
                                  decoder=_decode_utc, format="tuple")

    run_async(setup)


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

