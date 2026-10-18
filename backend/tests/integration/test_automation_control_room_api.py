"""The automation control room through the real app on Postgres (tech spec
§7.12): triggers saved without running anything, previews of the next fire
times, "run now" through the router, the event log with each decision and
run, replay of dead events, scope pauses, health — and one business never
sees another's. Rolled back per test; nudges and run jobs are not sent.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from src.auth import service
from src.automation import limits as limits_mod
from src.automation import router, store
from src.automation.events import Envelope
from src.automation.models import Event, TimeIndexEntry
from src.common.database import get_db
from src.main import app

pytestmark = pytest.mark.needs_db


@pytest_asyncio.fixture
async def biz(db, monkeypatch):
    from src.ai.orm import HierarchicalEntity
    from src.auth.models import Company, User
    from src.billing.credit_service import CreditService

    nudged = []

    async def _nudge(company_id, event_id, *, attempt=""):
        nudged.append(event_id)

    monkeypatch.setattr(store, "nudge", _nudge)
    monkeypatch.setattr("src.ai.service.enqueue_job", AsyncMock())
    monkeypatch.setattr(CreditService, "require_credits", AsyncMock())

    def company(name):
        row = Company(name=f"{name}-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
        db.add(row)
        return row

    mine, theirs = company("ws3-room"), company("ws3-other")
    await db.flush()

    def user(role, company_id):
        row = User(email=f"ws3-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="WS3",
                   role=role, company_id=company_id, is_active=True, is_verified=True)
        db.add(row)
        return row

    admin, operator, stranger = user("tenant_admin", mine.id), user("tenant_user", mine.id), \
        user("tenant_admin", theirs.id)
    agent = HierarchicalEntity(company_id=mine.id, type="AGENT", status="ACTIVE", name="room agent")
    db.add(agent)
    await db.flush()
    limits_mod.forget()
    limits_mod.forget_state()
    yield type("Biz", (), {"company": mine.id, "admin": admin, "operator": operator, "stranger": stranger,
                           "agent": agent.id, "nudged": nudged})
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


async def _create(client, biz, **fields):
    body = {"name": "Morning report", "kind": "schedule", "entity_id": str(biz.agent), "cron": "0 9 * * 1-5",
            **fields}
    r = await client.post("/api/v1/automation/triggers", headers=_as(biz.admin), json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_a_schedule_is_saved_with_its_next_time_and_nothing_runs(client, biz, db):
    trigger = await _create(client, biz, scope="sales")
    assert trigger["status"] == "active" and trigger["next_fire_at"] and trigger["created_by_kind"] == "user"
    assert trigger["timezone"] is None  # the business time zone applies
    row = await db.get(TimeIndexEntry, (biz.company, "trigger", uuid.UUID(trigger["id"])))
    assert row is not None and row.due_at.isoformat() == trigger["next_fire_at"]
    assert biz.nudged == []

    listed = await client.get("/api/v1/automation/triggers", headers=_as(biz.operator))
    assert [t["id"] for t in listed.json()] == [trigger["id"]]


async def test_who_may_change_triggers_and_what_is_refused(client, biz):
    body = {"name": "x", "kind": "schedule", "entity_id": str(biz.agent), "cron": "0 9 * * *"}
    r = await client.post("/api/v1/automation/triggers", headers=_as(biz.operator), json=body)
    assert r.status_code == 403
    bad = await client.post("/api/v1/automation/triggers", headers=_as(biz.admin), json={**body, "cron": "every day"})
    assert bad.status_code == 422 and "cron" in bad.json()["detail"]
    other = await client.post("/api/v1/automation/triggers", headers=_as(biz.stranger), json=body)
    assert other.status_code == 422 and "not an agent of this business" in other.json()["detail"]


async def test_the_preview_shows_the_next_times_in_the_business_time_zone(client, biz):
    r = await client.post("/api/v1/automation/triggers/preview", headers=_as(biz.operator),
                          json={"kind": "schedule", "cron": "30 9 * * *", "count": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["timezone"] == "Asia/Kolkata" and len(body["times"]) == 3
    assert all(t.endswith("04:00:00") for t in body["times"])  # 09:30 IST is 04:00 UTC


async def test_turning_a_trigger_off_takes_it_out_of_the_schedule(client, biz, db):
    trigger = await _create(client, biz)
    key = (biz.company, "trigger", uuid.UUID(trigger["id"]))
    off = await client.patch(f"/api/v1/automation/triggers/{trigger['id']}", headers=_as(biz.admin),
                             json={"enabled": False})
    assert off.status_code == 200 and off.json()["status"] == "off" and off.json()["next_fire_at"] is None
    assert await db.get(TimeIndexEntry, key) is None
    on = await client.patch(f"/api/v1/automation/triggers/{trigger['id']}", headers=_as(biz.admin),
                            json={"enabled": True, "cron": "0 10 * * *"})
    assert on.json()["status"] == "active" and on.json()["version"] == 3
    db.expire_all()
    assert (await db.get(TimeIndexEntry, key)).due_at.isoformat() == on.json()["next_fire_at"]


async def test_run_now_goes_through_the_router_and_the_event_shows_its_decision_and_run(client, biz, db):
    trigger = await _create(client, biz, kind="manual", cron=None, input_template={"input": "Run by {{ trigger.name }}"})
    r = await client.post(f"/api/v1/automation/triggers/{trigger['id']}/run", headers=_as(biz.operator))
    assert r.status_code == 202, r.text
    event = r.json()
    assert event["type"] == "manual.fired" and biz.nudged == [uuid.UUID(event["id"])]

    decided = await router.route(db, biz.company, uuid.UUID(event["id"]))
    assert [d["outcome"] for d in decided["decisions"]] == ["started"]

    firings = await client.get(f"/api/v1/automation/triggers/{trigger['id']}/firings", headers=_as(biz.operator))
    assert [f["outcome"] for f in firings.json()] == ["started"]
    detail = (await client.get(f"/api/v1/automation/events/{event['id']}", headers=_as(biz.operator))).json()
    assert detail["status"] == "routed" and detail["data"]["trigger_id"] == trigger["id"]
    assert [run["id"] for run in detail["runs"]] == [firings.json()[0]["run_id"]]


async def test_the_event_log_filters_and_a_dead_event_can_be_replayed(client, biz, db):
    for kind in ("custom.order.paid", "custom.order.refunded", "custom.invoice.sent"):
        await store.record(db, biz.company, Envelope(type=kind, source="test", trust="internal",
                                                     dedupe_key=uuid.uuid4().hex))
    await db.flush()
    orders = await client.get("/api/v1/automation/events?type=custom.order.*", headers=_as(biz.operator))
    assert sorted(e["type"] for e in orders.json()) == ["custom.order.paid", "custom.order.refunded"]

    dead = (await db.execute(select(Event).where(Event.company_id == biz.company,
                                                 Event.type == "custom.invoice.sent"))).scalar_one()
    dead.status = "dead"
    await db.flush()
    r = await client.post(f"/api/v1/automation/events/{dead.id}/replay", headers=_as(biz.operator))
    assert r.status_code == 202 and r.json()["status"] == "received" and biz.nudged[-1] == dead.id
    again = await client.post(f"/api/v1/automation/events/{dead.id}/replay", headers=_as(biz.operator))
    assert again.status_code == 409

    hidden = await client.get(f"/api/v1/automation/events/{dead.id}", headers=_as(biz.stranger))
    assert hidden.status_code == 404


async def test_a_filter_is_tested_against_recent_real_events_before_saving(client, biz, db):
    for text in ("what is the price?", "love it", "price please", "shipping?"):
        await store.record(db, biz.company, Envelope(type="social.comment.created", source="test", trust="verified",
                                                     data={"text": text}, dedupe_key=uuid.uuid4().hex))
    await db.flush()
    r = await client.post("/api/v1/automation/triggers/test-filter", headers=_as(biz.operator), json={
        "event_type": "social.comment.*",
        "filter": {"path": "data.text", "op": "contains", "value": "price"}})
    assert r.status_code == 200, r.text
    assert (r.json()["checked"], r.json()["matched"]) == (4, 2)
    bad = await client.post("/api/v1/automation/triggers/test-filter", headers=_as(biz.operator),
                            json={"event_type": "social.comment.*", "filter": {"path": "data.text", "op": "like"}})
    assert bad.status_code == 422


async def test_a_scope_pause_turns_off_only_its_triggers_and_resume_only_those(client, biz):
    sales = await _create(client, biz, scope="sales")
    by_hand = await _create(client, biz, scope="sales", name="Off by hand")
    await client.patch(f"/api/v1/automation/triggers/{by_hand['id']}", headers=_as(biz.admin), json={"enabled": False})
    other = await _create(client, biz, scope="support")

    paused = await client.post("/api/v1/automation/scopes/sales/pause", headers=_as(biz.operator))
    assert paused.json() == {"scope": "sales", "changed": 1}
    resumed = await client.post("/api/v1/automation/scopes/sales/resume", headers=_as(biz.operator))
    assert resumed.json() == {"scope": "sales", "changed": 1}
    states = {t["id"]: t["status"] for t in
              (await client.get("/api/v1/automation/triggers", headers=_as(biz.operator))).json()}
    assert states == {sales["id"]: "active", by_hand["id"]: "off", other["id"]: "active"}


async def test_health_and_one_business_never_sees_anothers_triggers(client, biz, db):
    trigger = await _create(client, biz)
    await store.record(db, biz.company, Envelope(type="custom.x.y", source="test", trust="internal",
                                                 dedupe_key=uuid.uuid4().hex))
    await db.flush()
    health = (await client.get("/api/v1/automation/health", headers=_as(biz.operator))).json()
    assert health["automation_state"] == "running"
    assert (health["triggers_enabled"], health["triggers_total"], health["dead_events"]) == (1, 1, 0)
    assert [u["trigger_id"] for u in health["upcoming"]] == [trigger["id"]] and health["started_24h"] == 0

    assert (await client.get(f"/api/v1/automation/triggers/{trigger['id']}", headers=_as(biz.stranger))).status_code == 404
    assert (await client.get("/api/v1/automation/triggers", headers=_as(biz.stranger))).json() == []
    removed = await client.delete(f"/api/v1/automation/triggers/{trigger['id']}", headers=_as(biz.admin))
    assert removed.status_code == 204
    assert (await client.get(f"/api/v1/automation/triggers/{trigger['id']}", headers=_as(biz.admin))).status_code == 404


async def test_every_control_room_endpoint_carries_its_capability_annotations():
    spec = app.openapi()
    for path, methods in spec["paths"].items():
        if not path.startswith("/api/v1/automation"):
            continue
        for method, operation in methods.items():
            assert {"x-hb-summary", "x-hb-effect", "x-hb-permission", "x-hb-approval", "x-hb-idempotent",
                    "x-hb-scope"} <= set(operation), f"{method.upper()} {path}"
