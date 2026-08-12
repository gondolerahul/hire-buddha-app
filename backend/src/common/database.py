from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from src.common.config import settings

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
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

