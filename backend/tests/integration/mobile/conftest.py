"""
Fixtures for mobile-dialer integration tests.

These tests COMMIT (the services under test commit), so they only run against
a disposable database whose name ends in ``_test`` — never the live
``hirebuddha`` DB. The schema is rebuilt once per session: ORM ``create_all``
for the pre-existing tables, then the mobile tables/columns are dropped and
recreated by running ``db-scripts/mobile_dialer_001.sql`` twice (which also
proves the script is idempotent against an existing schema).
"""
import asyncio
import uuid
from datetime import datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from src.common.config import settings

DB_NAME = settings.DATABASE_URL.rsplit("/", 1)[-1]
if not DB_NAME.endswith("_test"):
    pytest.skip(
        f"mobile integration tests need a disposable *_test database (DATABASE_URL points at '{DB_NAME}')",
        allow_module_level=True,
    )

SQL_SCRIPTS = [
    Path(__file__).resolve().parents[3] / "db-scripts" / "mobile_dialer_001.sql",
    Path(__file__).resolve().parents[3] / "db-scripts" / "mobile_dialer_002_logs.sql",
]
MOBILE_TABLES = [
    "mobile_client_logs", "mobile_call_events", "mobile_call_attempts", "mobile_campaign_runs",
    "campaign_assignees", "contact_uploads", "user_devices",
]
TRUNCATE_TABLES = MOBILE_TABLES + [
    "conversation_history", "voice_sessions", "campaign_calls", "campaigns",
    "phone_numbers", "hierarchical_entities", "users", "companies",
]
DID = "+918065251146"


def _build_schema():
    import src.main  # noqa: F401 — registers every model on Base.metadata
    from src.common.database import Base

    async def run():
        eng = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        async with eng.begin() as conn:
            name = await conn.scalar(text("select current_database()"))
            assert name.endswith("_test"), name
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
            await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
            try:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            except Exception:
                pass
        # Only the pre-existing tables this flow touches (the full metadata
        # references CORTEX tables owned by another package's metadata).
        needed = ["companies", "users", "hierarchical_entities", "phone_numbers", "voice_sessions",
                  "conversation_history", "campaigns", "campaign_calls"]
        async with eng.begin() as conn:
            await conn.run_sync(lambda c: Base.metadata.create_all(
                c, tables=[Base.metadata.tables[t] for t in needed]))
        # Simulate the production DB *before* the mobile migration, then apply it twice.
        async with eng.begin() as conn:
            await conn.execute(text("DROP INDEX IF EXISTS ix_campaign_calls_lease"))
            for col in ("execution_mode", "contact_upload_id"):
                await conn.execute(text(f"ALTER TABLE campaigns DROP COLUMN {col}"))
            for col in ("leased_by_user_id", "leased_by_device_id", "lease_expires_at"):
                await conn.execute(text(f"ALTER TABLE campaign_calls DROP COLUMN {col}"))
        import asyncpg  # multi-statement scripts: run them the way psql would
        dsn = settings.DATABASE_URL.replace("postgresql+asyncpg", "postgresql")
        conn = await asyncpg.connect(dsn)
        try:
            for script in SQL_SCRIPTS:
                sql = script.read_text()
                await conn.execute(sql)
                await conn.execute(sql)  # idempotency check
        finally:
            await conn.close()
        await eng.dispose()

    asyncio.run(run())


@pytest.fixture(scope="session", autouse=True)
def mobile_schema():
    _build_schema()
    yield


@pytest_asyncio.fixture(autouse=True)
async def _isolated_engine(mobile_schema, monkeypatch):
    """Bind the app's global session factory to a NullPool engine on this
    test's event loop, and reset the per-process Redis client."""
    from src.common import database
    from src.mobile import realtime

    eng = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    database.AsyncSessionLocal.configure(bind=eng)
    monkeypatch.setattr(database, "engine", eng)
    realtime._redis = None
    async with eng.begin() as conn:
        await conn.execute(text("TRUNCATE " + ", ".join(TRUNCATE_TABLES) + " CASCADE"))
    try:
        yield eng
    finally:
        if realtime._redis is not None:
            await realtime._redis.aclose()
            realtime._redis = None
        await eng.dispose()


@pytest_asyncio.fixture
async def db(_isolated_engine):
    from src.common.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture(autouse=True)
def _no_credit_gate(monkeypatch):
    from src.mobile import service

    async def ok(db, company_id):
        return None

    monkeypatch.setattr(service, "_check_credits", ok)
    monkeypatch.setattr(settings, "MOBILE_CALLING_HOURS_ENFORCED", False)


class World:
    """Seeded tenant: company, admin, two reps, an outsider, agent, DID."""


@pytest_asyncio.fixture
async def world(db):
    from src.ai.models import HierarchicalEntity
    from src.auth.models import Company, User
    from src.voice.phone_pool_models import PhoneNumber

    w = World()
    w.company = Company(id=uuid.uuid4(), name="Acme Realty", type="TENANT", status="active")
    w.other_company = Company(id=uuid.uuid4(), name="Other Co", type="TENANT", status="active")
    db.add_all([w.company, w.other_company])
    await db.flush()

    def user(name, role, company):
        return User(id=uuid.uuid4(), email=f"{name}-{uuid.uuid4().hex[:6]}@example.com", full_name=name.title(),
                    hashed_password="x", company_id=company.id, role=role, is_active=True)

    w.admin = user("anita", "tenant_admin", w.company)
    w.rep = user("ravi", "tenant_user", w.company)
    w.rep2 = user("sunita", "tenant_user", w.company)
    w.outsider = user("otto", "tenant_admin", w.other_company)
    w.app_admin = user("root", "app_admin", w.company)
    db.add_all([w.admin, w.rep, w.rep2, w.outsider, w.app_admin])
    await db.flush()

    w.agent = HierarchicalEntity(id=uuid.uuid4(), company_id=w.company.id, type="AGENT", status="ACTIVE",
                                 name="sales-agent", display_name="Priya (AI)",
                                 identity={"voice": {"voice_name": "Aoede"}})
    db.add(w.agent)
    await db.flush()
    db.add(PhoneNumber(phone_number=DID.lstrip("+"), provider="tata_tele", status="assigned", is_active=True,
                       company_id=w.company.id, agent_id=w.agent.id, assigned_at=datetime.utcnow()))
    await db.commit()
    for u in (w.admin, w.rep, w.rep2, w.outsider, w.app_admin, w.company, w.other_company, w.agent):
        await db.refresh(u)
    w.did = DID
    return w


@pytest.fixture
def api(world, _isolated_engine):
    """httpx client over a minimal app (campaign + mobile routers) with a
    switchable authenticated user: ``api.as_user(world.rep)``."""
    import httpx
    from fastapi import FastAPI

    from src.ai.campaign_router import router as campaign_router
    from src.auth.dependencies import get_current_user
    from src.mobile.router import router as mobile_router

    app = FastAPI()
    app.include_router(campaign_router, prefix="/api/v1")
    app.include_router(mobile_router, prefix="/api/v1")
    state = {"user": world.rep}

    async def current_user():
        from sqlalchemy.orm import selectinload
        from sqlalchemy import select
        from src.auth.models import User
        from src.common.database import AsyncSessionLocal

        async with AsyncSessionLocal() as s:
            return (await s.execute(
                select(User).options(selectinload(User.company)).where(User.id == state["user"].id)
            )).scalar_one()

    app.dependency_overrides[get_current_user] = current_user
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    def as_user(u):
        state["user"] = u
        return client

    client.as_user = as_user
    return client
