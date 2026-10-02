"""Authoring versions through the API: draft, files, test run, publish, roll back (P5.6, R2).

Real Postgres, rolled back; the app is the versions router with the caller and
the session overridden. A test run is enqueued nowhere and the credit gate is
stubbed — what is checked is the run row the API writes.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select

from src.ai.api.versions import router
from src.ai.governance.entity_versions import capture_head, run_entity
from src.ai.models import ExecutionRun, HierarchicalEntity

pytestmark = pytest.mark.needs_db


@pytest_asyncio.fixture
async def world(db, monkeypatch):
    from src.auth.models import Company
    import src.ai.service as service_mod
    from src.billing.credit_service import CreditService

    monkeypatch.setattr(service_mod, "enqueue_job", AsyncMock())
    monkeypatch.setattr(CreditService, "require_credits", AsyncMock())
    mine = Company(name=f"p56-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    other = Company(name=f"p56o-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add_all([mine, other])
    await db.flush()
    ent = HierarchicalEntity(company_id=mine.id, type="ACTION", status="ACTIVE", name="authored", goal="v1 goal")
    db.add(ent)
    await db.flush()
    head = await capture_head(db, ent.id)
    return SimpleNamespace(mine=mine, other=other, entity=ent, entity_id=ent.id, head=head)


def _client(db, role, company) -> httpx.AsyncClient:
    from src.auth.dependencies import get_current_user
    from src.common.database import get_db

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    actor = SimpleNamespace(id=None, role=role, company_id=company.id)

    async def _user():
        return actor

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def _url(world, tail=""):
    return f"/api/v1/ai/entities/{world.entity_id}/versions{tail}"


@pytest.mark.asyncio
async def test_draft_files_test_run_publish_and_roll_back(db, world):
    async with _client(db, "tenant_admin", world.mine) as c:
        r = await c.post(_url(world), json={"changes": {"goal": "v2 goal"}})
        assert r.status_code == 201, r.text
        draft = r.json()
        assert (draft["version_number"], draft["published"], draft["is_head"]) == (2, False, False)
        assert draft["snapshot"]["goal"] == "v2 goal"

        r = await c.put(_url(world, f"/{draft['id']}/assets/scripts/run.py"), json={"body": "print(2)"})
        assert r.status_code == 200 and r.json()["language"] == "python"
        assert (await c.get(_url(world, f"/{draft['id']}/assets/scripts/run.py"))).json()["body"] == "print(2)"

        r = await c.post(_url(world, f"/{draft['id']}/test-run"), json={"input_data": {"input": "hi"}})
        assert r.status_code == 200, r.text
        run = (await db.execute(select(ExecutionRun).where(ExecutionRun.id == uuid.UUID(r.json()["id"])))).scalar_one()
        assert str(run.entity_version_id) == draft["id"]
        await db.refresh(run, ["entity"])
        assert (await run_entity(db, run)).goal == "v2 goal"
        assert world.entity.goal == "v1 goal"                      # the head is untouched

        r = await c.post(_url(world, f"/{draft['id']}/publish"))
        assert r.status_code == 200, r.text
        assert (r.json()["id"], r.json()["published"], r.json()["is_head"]) == (draft["id"], True, True)
        await db.refresh(world.entity)
        assert world.entity.goal == "v2 goal"
        fresh = ExecutionRun(entity_id=world.entity.id, company_id=world.mine.id, status="PENDING", input_data={})
        db.add(fresh)
        await db.flush()
        assert str(fresh.entity_version_id) == draft["id"]         # new runs execute it

        r = await c.post(_url(world, f"/{world.head}/publish"))  # roll back to version 1
        assert r.status_code == 200 and r.json()["version_number"] == 1
        await db.refresh(world.entity)
        assert world.entity.goal == "v1 goal"
        listed = (await c.get(_url(world))).json()
        assert [(v["version_number"], v["is_head"], v["asset_count"]) for v in listed] == [(2, False, 1), (1, True, 0)]


@pytest.mark.asyncio
async def test_what_a_draft_refuses(db, world):
    async with _client(db, "tenant_admin", world.mine) as c:
        assert (await c.post(_url(world), json={"changes": {"status": "ARCHIVED"}})).status_code == 422
        assert (await c.post(_url(world), json={"changes": {"bogus": 1}})).status_code == 422
        copy = await c.post(_url(world), json={"changes": {}})                     # a draft may start as v1's copy
        assert copy.status_code == 201
        assert (await c.post(_url(world, f"/{copy.json()['id']}/publish"))).status_code == 409   # but not be published
        assert (await c.put(_url(world, f"/{world.head}/assets/a.py"), json={"body": "x"})).status_code == 409
        draft = (await c.post(_url(world), json={"changes": {"goal": "other"}})).json()
        assert (await c.put(_url(world, f"/{draft['id']}/assets/../a.py"), json={"body": "x"})).status_code in (404, 422)
        assert (await c.put(_url(world, f"/{draft['id']}/assets/.env"), json={"body": "x"})).status_code == 422
        assert (await c.delete(_url(world, f"/{draft['id']}/assets/none.py"))).status_code == 404


@pytest.mark.asyncio
async def test_who_may_do_what(db, world):
    async with _client(db, "tenant_user", world.mine) as c:
        draft = await c.post(_url(world), json={"changes": {"goal": "by a user"}})
        assert draft.status_code == 201                                   # a member drafts and tests
        assert (await c.post(_url(world, f"/{draft.json()['id']}/publish"))).status_code == 403
    async with _client(db, "tenant_admin", world.other) as c:
        assert (await c.get(_url(world))).status_code == 404               # another company sees nothing
