"""Decision D47 through the real app on Postgres: a business sets its own
automation limits on screen (none by default), platform staff set defaults a
business's values win over, and anyone running the business may pause it;
staff can stop everyone's automation at once.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio

from src.auth import service
from src.automation import limits as limits_mod
from src.common.database import get_db
from src.main import app

pytestmark = pytest.mark.needs_db


@pytest_asyncio.fixture
async def people(db):
    from src.auth.models import Company, User
    from src.auth.platform import platform_company_id

    company = Company(name=f"d47-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(company)
    await db.flush()

    def make(role, company_id):
        user = User(email=f"d47-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="D47",
                    role=role, company_id=company_id, is_active=True, is_verified=True)
        db.add(user)
        return user

    admin, operator = make("tenant_admin", company.id), make("tenant_user", company.id)
    staff = make("app_admin", await platform_company_id(db))
    await db.flush()
    limits_mod.forget()
    limits_mod.forget_state()
    yield type("People", (), {"company": company.id, "admin": admin, "operator": operator, "staff": staff})
    limits_mod.forget()
    limits_mod.forget_state()


@pytest_asyncio.fixture
async def client(db):
    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


def _as(user):
    return {"Authorization": f"Bearer {service.issue_access_token(user)}"}


async def test_a_business_has_no_limits_until_it_sets_some(client, people):
    r = await client.get("/api/v1/automation/settings", headers=_as(people.admin))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["automation_state"] == "running" and body["business"] == {}
    assert body["timezone"] == "Asia/Kolkata"
    assert body["effective"]["max_chain_depth"] is None and body["effective"]["overlap"] == "allow"
    assert {item["key"] for item in body["catalogue"]} >= {"max_chain_depth", "trigger_rate_per_hour", "overlap"}


async def test_the_business_sets_limits_and_its_values_win(client, people, db):
    staff = await client.put("/api/v1/admin/automation/limits", headers=_as(people.staff),
                             json={"limits": {"max_chain_depth": 5, "trigger_rate_per_hour": 60}})
    assert staff.status_code == 200, staff.text

    r = await client.put("/api/v1/automation/settings/limits", headers=_as(people.admin),
                         json={"limits": {"max_chain_depth": 8, "trigger_rate_per_hour": None}})
    assert r.status_code == 200, r.text
    effective = r.json()["effective"]
    assert effective["max_chain_depth"] == 8            # the business's value
    assert effective["trigger_rate_per_hour"] is None   # null: no limit, though the platform has 60
    assert (await limits_mod.limits_for(people.company, db)).max_chain_depth == 8


async def test_bad_values_and_the_wrong_people_are_refused(client, people):
    bad = await client.put("/api/v1/automation/settings/limits", headers=_as(people.admin),
                           json={"limits": {"max_chain_depth": 0}})
    assert bad.status_code == 422 and "max_chain_depth" in bad.text
    operator = await client.put("/api/v1/automation/settings/limits", headers=_as(people.operator),
                                json={"limits": {"max_chain_depth": 3}})
    assert operator.status_code == 403
    assert (await client.get("/api/v1/admin/automation/limits", headers=_as(people.admin))).status_code == 403


async def test_an_operator_may_pause_and_resume(client, people, db):
    paused = await client.post("/api/v1/automation/pause", headers=_as(people.operator), json={"reason": "audit"})
    assert paused.status_code == 200, paused.text
    assert paused.json()["automation_state"] == "paused" and paused.json()["paused_reason"] == "audit"
    assert await limits_mod.automation_state_for(people.company, db) == "paused"
    resumed = await client.post("/api/v1/automation/resume", headers=_as(people.operator))
    assert resumed.json()["automation_state"] == "running"
    assert await limits_mod.automation_state_for(people.company, db) == "running"


async def test_the_emergency_stop_pauses_every_business(client, people, db):
    stop = await client.post("/api/v1/admin/automation/pause", headers=_as(people.staff), json={})
    assert stop.status_code == 200 and stop.json()["automation_state"] == "paused"
    assert await limits_mod.automation_state_for(people.company, db) == "paused"
    assert await limits_mod.automation_state_for(uuid.uuid4(), db) == "paused"
    await client.post("/api/v1/admin/automation/resume", headers=_as(people.staff))
    assert await limits_mod.automation_state_for(people.company, db) == "running"


async def test_every_endpoint_carries_its_capability(client):
    spec = (await client.get("/openapi.json")).json()
    for path, operations in spec["paths"].items():
        if "/automation" not in path:
            continue
        for method, operation in operations.items():
            assert operation.get("x-hb-summary") and operation.get("x-hb-effect"), (method, path)
            assert operation.get("x-hb-scope") in ("tenant", "platform"), (method, path)
