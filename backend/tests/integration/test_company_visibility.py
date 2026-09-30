"""One visibility rule for every company-scoped read (AU-20).

"Own company plus child tenants" was written out five times — users,
companies, entity create/list/read, phone-number assignment — and the entity
list ran one query per tenant. ``auth.visibility`` is the one rule now:
app_admin every company, partners their own and their tenants', everyone else
their own.

Real Postgres, rolled back: a partner P with tenant T, and an unrelated
tenant O.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import event

pytestmark = pytest.mark.needs_db


@pytest_asyncio.fixture
async def world(db):
    from src.ai.orm.entity import HierarchicalEntity
    from src.auth.models import Company, User

    P = Company(name=f"vis-partner-{uuid.uuid4().hex[:6]}", type="PARTNER", status="active")
    db.add(P)
    await db.flush()
    T = Company(name=f"vis-tenant-{uuid.uuid4().hex[:6]}", type="TENANT", status="active", parent_id=P.id)
    O = Company(name=f"vis-other-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add_all([T, O])
    await db.flush()
    entities, users = {}, {}
    for key, company in (("P", P), ("T", T), ("O", O)):
        e = HierarchicalEntity(company_id=company.id, type="AGENT", status="ACTIVE", name=f"vis-{key}-{uuid.uuid4().hex[:6]}")
        u = User(email=f"vis-{key.lower()}-{uuid.uuid4().hex[:6]}@example.com", full_name=key, hashed_password="x",
                 company_id=company.id, role="tenant_user", is_verified=True)
        db.add_all([e, u])
        entities[key], users[key] = e, u
    await db.flush()
    return SimpleNamespace(P=P, T=T, O=O, entities=entities, users=users)


def _actor(role, company):
    return SimpleNamespace(id=uuid.uuid4(), role=role, company_id=company.id)


def _client(db, actor, *routers) -> httpx.AsyncClient:
    from src.auth.dependencies import get_current_user
    from src.common.database import get_db

    app = FastAPI()
    for router in routers:
        app.include_router(router, prefix="/api/v1")

    async def _user():
        return actor

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
@pytest.mark.parametrize("role,company,expected", [
    ("app_admin", "O", None),               # None: at least all three
    ("partner_admin", "P", {"P", "T"}),
    ("partner_user", "P", {"P", "T"}),
    ("tenant_admin", "T", {"T"}),
])
async def test_the_rule(db, world, role, company, expected):
    from src.auth.visibility import visible_company_ids

    scope = await visible_company_ids(db, _actor(role, getattr(world, company)))
    if expected is None:
        assert scope is None
    else:
        assert scope == {getattr(world, k).id for k in expected}


@pytest.mark.asyncio
async def test_partner_sees_own_and_tenant_entities_in_one_query(db, world):
    from src.ai.router import router as ai_router

    statements: list[str] = []
    conn = await db.connection()
    event.listen(conn.sync_connection, "before_cursor_execute",
                 lambda *a: statements.append(a[2]) if "hierarchical_entities" in a[2] else None)
    async with _client(db, _actor("partner_user", world.P), ai_router) as c:
        res = await c.get("/api/v1/ai/entities")
    assert res.status_code == 200
    ids = {e["id"] for e in res.json()}
    assert {str(world.entities["P"].id), str(world.entities["T"].id)} <= ids
    assert str(world.entities["O"].id) not in ids
    assert len([s for s in statements if s.lstrip().upper().startswith("SELECT")
                and "FROM hierarchical_entities" in s and "execution_runs" not in s]) == 1


@pytest.mark.asyncio
async def test_partner_reads_a_tenant_entity_but_not_anothers(db, world):
    from src.ai.service import AIService

    svc = AIService(db)
    assert (await svc.get_entity(world.entities["T"].id, world.P.id, "partner_admin")).id == world.entities["T"].id
    with pytest.raises(Exception) as exc:
        await svc.get_entity(world.entities["O"].id, world.P.id, "partner_admin")
    assert getattr(exc.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_partner_admin_lists_its_and_its_tenants_users(db, world):
    from src.auth.user_router import router as user_router

    async with _client(db, _actor("partner_admin", world.P), user_router) as c:
        emails = {u["email"] for u in (await c.get("/api/v1/users")).json()}
    assert {world.users["P"].email, world.users["T"].email} <= emails
    assert world.users["O"].email not in emails


@pytest.mark.asyncio
async def test_partner_user_may_see_tenants_but_not_list_users(db, world):
    from src.auth.company_router import router as company_router
    from src.auth.user_router import router as user_router

    async with _client(db, _actor("partner_user", world.P), company_router, user_router) as c:
        names = {co["name"] for co in (await c.get("/api/v1/companies")).json()}
        users = await c.get("/api/v1/users")
    assert names == {world.P.name, world.T.name}
    assert users.status_code == 403


@pytest.mark.asyncio
async def test_entity_creation_for_a_visible_company_only(db, world):
    from src.ai.router import router as ai_router

    body = {"type": "AGENT", "name": "vis-created", "status": "DRAFT"}
    actor = SimpleNamespace(id=world.users["P"].id, role="partner_admin", company_id=world.P.id)
    async with _client(db, actor, ai_router) as c:
        ok = await c.post(f"/api/v1/ai/entities?target_company_id={world.T.id}", json=body)
        no = await c.post(f"/api/v1/ai/entities?target_company_id={world.O.id}", json=body)
    assert ok.status_code == 200 and ok.json()["company_id"] == str(world.T.id)
    assert no.status_code == 403
