"""The Data API through the real app (WS4 4.5–4.7, 4.9; tech spec §9), in a
throwaway business database: who may call, records with ETag / If-Match,
filters and paging, idempotent creates, reports, app keys, an agent's run
token proposing a schema change a person approves, and a data trigger
started by a record change — the ``record.*`` event committed with the row.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from src.automation import store
from src.data_api import tokens
from src.schema_engine import engine as schema

pytestmark = pytest.mark.needs_db


@pytest_asyncio.fixture
async def biz(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import src.common.orm_models  # noqa: F401
    from src.auth.models import User
    from src.common import database
    from src.common.config import settings
    from tests.harness.tenant_db import scratch_tenant

    control = create_async_engine(settings.CONTROL_DATABASE_URL, poolclass=NullPool,
                                  json_serializer=database.json_serializer)
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(control, expire_on_commit=False))
    monkeypatch.setattr(database, "engine", control)  # a split tenant session's control tables
    nudged = []

    async def _nudge(company_id, event_id, *, attempt=""):
        nudged.append(event_id)

    monkeypatch.setattr(store, "nudge", _nudge)
    async with scratch_tenant("dataapi") as t:
        async with database.AsyncSessionLocal() as db:
            owner = User(email=f"ws4-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="Owner",
                         role="tenant_admin", company_id=t.company_id, is_active=True, is_verified=True)
            staff = User(email=f"ws4-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="Staff",
                         role="tenant_user", company_id=t.company_id, is_active=True, is_verified=True)
            db.add_all([owner, staff])
            await db.commit()
        t.owner, t.staff, t.nudged = owner, staff, nudged
        t.engine, _ = await schema.business_engine(t.company_id)
        try:
            yield t
        finally:
            async with database.AsyncSessionLocal() as db:
                from sqlalchemy import delete

                await db.execute(delete(User).where(User.company_id == t.company_id))
                await db.commit()
    await control.dispose()


def _client():
    from src.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _user(biz, who="owner"):
    return _bearer(tokens.mint_user_token(getattr(biz, who), biz.company_id, biz.key))


async def test_only_a_valid_credential_for_this_business_gets_in(biz):
    async with _client() as client:
        assert (await client.get("/data/v1/contact")).status_code == 401
        bad = await client.get("/data/v1/contact", headers=_bearer("not-a-token"))
        assert bad.status_code == 401 and bad.json()["code"] == "unauthorized"
        other = tokens.mint_user_token(biz.owner, biz.company_id, "zzzzzzzzzz")
        assert (await client.get("/data/v1/contact", headers=_bearer(other))).status_code == 401
        schema_view = (await client.get("/data/v1/schema", headers=_user(biz))).json()
    assert set(schema_view["objects"]) == {"account", "contact", "activity", "consent"}


async def test_records_with_etag_and_if_match_and_their_events(biz):
    async with _client() as client:
        bad = await client.post("/data/v1/contact", headers=_user(biz), json={"email": "not an address"})
        assert bad.status_code == 422 and bad.json()["code"] == "invalid_value"
        assert (await client.post("/data/v1/contact", headers=_user(biz), json={"tier": 1})).json()["code"] \
            == "unknown_field"
        assert (await client.post("/data/v1/account", headers=_user(biz), json={})).json()["code"] == "required"

        created = await client.post("/data/v1/contact", headers=_user(biz, "staff"), json={
            "first_name": "Priya", "email": "Priya@Example.com", "phone": "+91 98765 43210"})
        assert created.status_code == 201 and created.headers["etag"] == '"1"'
        contact = created.json()
        assert contact["email"] == "priya@example.com" and contact["lifecycle_stage"] == "lead"
        assert contact["created_by"] == f"user:{biz.staff.id}"

        url = f"/data/v1/contact/{contact['id']}"
        assert (await client.patch(url, headers=_user(biz), json={"lifecycle_stage": "customer"})).status_code == 428
        stale = await client.patch(url, headers={**_user(biz), "If-Match": '"7"'}, json={"lifecycle_stage": "customer"})
        assert stale.status_code == 412 and stale.json()["code"] == "stale"
        updated = await client.patch(url, headers={**_user(biz), "If-Match": created.headers["etag"]},
                                     json={"lifecycle_stage": "customer"})
        assert updated.status_code == 200 and updated.headers["etag"] == '"2"'
        assert (await client.get(url, headers=_user(biz))).headers["etag"] == '"2"'

    from src.automation.models import Event
    from src.schema_engine.models import AuditLog

    async with schema.session(biz.engine) as db:
        events = (await db.execute(select(Event).where(Event.type.like("record.%")).order_by(Event.received_at))
                  ).scalars().all()
        audit = (await db.execute(select(AuditLog.action, AuditLog.changed_fields))).all()
    assert [e.type for e in events] == ["record.contact.created", "record.contact.updated"]
    assert events[1].data["changed"] == ["lifecycle_stage"]
    assert "email" not in events[1].data["after"] and "phone" not in events[1].data["after"]  # pii stays in the row
    assert events[1].data["after"]["lifecycle_stage"] == "customer"
    assert sorted(a.action for a in audit) == ["created", "updated"]
    assert {e.id for e in events} <= set(biz.nudged)  # with the base pack's schema.version.activated


async def test_filters_sort_paging_fields_and_archive(biz):
    async with _client() as client:
        for n, stage in enumerate(["lead", "customer", "customer", "lead", "customer"]):
            await client.post("/data/v1/contact", headers=_user(biz),
                              json={"first_name": f"P{n}", "lifecycle_stage": stage})
        page = (await client.get("/data/v1/contact?filter[lifecycle_stage][eq]=customer&sort=first_name"
                                 "&page[size]=2&fields=first_name", headers=_user(biz))).json()
        assert [r["first_name"] for r in page["items"]] == ["P1", "P2"] and set(page["items"][0]) == \
            {"id", "row_version", "first_name"}
        rest = (await client.get(f"/data/v1/contact?filter[lifecycle_stage][eq]=customer&sort=first_name"
                                 f"&page[size]=2&page[after]={page['next']}", headers=_user(biz))).json()
        assert [r["first_name"] for r in rest["items"]] == ["P4"] and rest["next"] is None
        names = (await client.get("/data/v1/contact?filter[first_name][in]=P0,P3&sort=-first_name",
                                  headers=_user(biz))).json()
        assert [r["first_name"] for r in names["items"]] == ["P3", "P0"]
        assert (await client.get("/data/v1/contact?filter[first_name][like]=P", headers=_user(biz))).status_code == 422

        target = names["items"][0]
        archived = await client.delete(f"/data/v1/contact/{target['id']}", headers=_user(biz))
        assert archived.status_code == 200 and archived.json()["archived_at"]
        left = (await client.get("/data/v1/contact?filter[first_name][in]=P0,P3", headers=_user(biz))).json()
        assert [r["first_name"] for r in left["items"]] == ["P0"]
        again = await client.patch(f"/data/v1/contact/{target['id']}", headers={**_user(biz), "If-Match": '"2"'},
                                   json={"first_name": "x"})
        assert again.status_code == 409


async def test_a_create_with_an_idempotency_key_happens_once(biz):
    headers = {**_user(biz), "Idempotency-Key": uuid.uuid4().hex}
    async with _client() as client:
        first = await client.post("/data/v1/account", headers=headers, json={"name": "Acme"})
        again = await client.post("/data/v1/account", headers=headers, json={"name": "Acme"})
        listed = (await client.get("/data/v1/account", headers=_user(biz))).json()
    assert first.json()["id"] == again.json()["id"] and again.headers.get("idempotent-replayed") == "true"
    assert len(listed["items"]) == 1


async def test_reports_group_and_count(biz):
    async with _client() as client:
        for stage in ["lead", "customer", "customer"]:
            await client.post("/data/v1/contact", headers=_user(biz), json={"lifecycle_stage": stage})
        r = await client.post("/data/v1/reports", headers=_user(biz), json={
            "object": "contact", "group_by": ["lifecycle_stage"], "measures": [{"fn": "count"}]})
    assert r.status_code == 200, r.text
    assert {row["lifecycle_stage"]: row["count"] for row in r.json()["rows"]} == {"customer": 2, "lead": 1}


async def test_an_app_key_may_do_what_its_scopes_say(biz):
    from src.auth import service

    login = {"Authorization": f"Bearer {service.issue_access_token(biz.owner)}"}
    async with _client() as client:
        staff = {"Authorization": f"Bearer {service.issue_access_token(biz.staff)}"}
        assert (await client.post("/api/v1/data-keys", headers=staff, json={
            "name": "x", "scopes": {"objects": {"contact": ["create"]}}})).status_code == 403
        made = await client.post("/api/v1/data-keys", headers=login, json={
            "name": "Website form", "scopes": {"objects": {"contact": ["create"]}}})
        assert made.status_code == 201, made.text
        key = made.json()["key"]
        assert key.startswith(f"hbk_dev_{biz.key}_") and "key" not in (await client.get(
            "/api/v1/data-keys", headers=login)).json()[0]
        assert (await client.post("/data/v1/contact", headers=_bearer(key), json={"first_name": "Web"})).status_code == 201
        assert (await client.get("/data/v1/contact", headers=_bearer(key))).status_code == 403
        token = (await client.post("/api/v1/records/token", headers=login)).json()
        assert token["tenant"] == biz.key and token["base_url"] == "/data/v1"
        await client.delete(f"/api/v1/data-keys/{made.json()['id']}", headers=login)
        assert (await client.post("/data/v1/contact", headers=_bearer(key), json={})).status_code == 401


async def test_an_agent_proposes_a_new_object_and_a_person_approves_it(biz):
    agent = SimpleNamespace(id=uuid.uuid4(), capabilities={"records": {
        "objects": {"contact": ["read"]}, "schema_changes": "propose"}})
    run = _bearer(tokens.mint_run_token(uuid.uuid4(), agent, biz.company_id, biz.key))
    async with _client() as client:
        assert (await client.get("/data/v1/contact", headers=run)).status_code == 200
        assert (await client.post("/data/v1/contact", headers=run, json={})).status_code == 403
        proposed = await client.post("/data/v1/schema/changes", headers=run, json={
            "reason": "track deliveries", "operations": [{"op": "add_object", "object": "shipment",
                                                          "definition": {"fields": {"carrier": {"type": "text"}}}}]})
        assert proposed.status_code == 201 and proposed.json()["status"] == "awaiting_approval"
        change_id = proposed.json()["id"]
        assert (await client.post(f"/data/v1/schema/changes/{change_id}/approve", headers=run)).status_code == 403
        assert (await client.post(f"/data/v1/schema/changes/{change_id}/approve",
                                  headers=_user(biz, "staff"))).status_code == 403
        approved = await client.post(f"/data/v1/schema/changes/{change_id}/approve", headers=_user(biz))
        assert approved.json()["status"] == "applied" and approved.json()["result_version"] == 2
        made = await client.post("/data/v1/shipment", headers=_user(biz), json={"carrier": "DHL"})
        assert made.status_code == 201 and made.json()["carrier"] == "DHL"
        # The change review list (WS8 8.2): people of the business see it; keys do not.
        listed = (await client.get("/data/v1/schema/changes", headers=_user(biz, "staff"))).json()["items"]
        assert listed[0]["id"] == change_id and listed[0]["status"] == "applied"
        assert (await client.get("/data/v1/schema/changes?status=awaiting_approval",
                                 headers=_user(biz))).json()["items"] == []


async def test_a_records_history_says_who_changed_what(biz):
    async with _client() as client:
        made = (await client.post("/data/v1/contact", headers=_user(biz, "staff"),
                                  json={"first_name": "Asha", "email": "asha@example.com"})).json()
        url = f"/data/v1/contact/{made['id']}"
        await client.patch(url, headers={**_user(biz), "If-Match": '"1"'}, json={"lifecycle_stage": "customer"})
        history = (await client.get(f"{url}/history", headers=_user(biz))).json()["items"]
        assert [h["action"] for h in history] == ["updated", "created"]
        assert history[0]["actor"] == f"user:{biz.owner.id}" and history[0]["changed"] == ["lifecycle_stage"]
        assert history[1]["actor"] == f"user:{biz.staff.id}"
        missing = await client.get(f"/data/v1/contact/{uuid.uuid4()}/history", headers=_user(biz))
        assert missing.status_code == 404


async def test_a_record_change_starts_the_data_trigger(biz, monkeypatch):
    """M4: updating an order to paid fires the invoice trigger."""
    from src.ai.orm import HierarchicalEntity
    from src.automation import router, triggers
    from src.billing.billing_models import CreditWallet
    from src.common import database
    from src.common.config import settings
    from src.common.tenancy.session import tenant_session

    monkeypatch.setattr(settings, "TENANCY_MODE", "split")
    monkeypatch.setattr("src.ai.service.enqueue_job", lambda *a, **k: _none())
    later = datetime.utcnow() + timedelta(days=1)
    async with database.AsyncSessionLocal() as db:
        db.add(CreditWallet(company_id=biz.company_id, daily_credits=Decimal("0"), daily_expires_at=later,
                            wallet_balance=Decimal("100"), wallet_expires_at=later))
        await db.commit()
    async with _client() as client:
        await client.post("/data/v1/schema/changes", headers=_user(biz), json={"operations": [
            {"op": "add_object", "object": "order", "definition": {"fields": {
                "number": {"type": "text"}, "status": {"type": "enum", "values": ["new", "paid"], "default": "new"}}}}]})
        async with tenant_session(biz.company_id) as db:
            invoicer = HierarchicalEntity(company_id=biz.company_id, type="AGENT", status="ACTIVE", name="Invoicer")
            db.add(invoicer)
            await db.commit()
            trigger = await triggers.create(db, db, biz.company_id, {
                "name": "Invoice paid orders", "kind": "data", "entity_id": invoicer.id, "event_type": "record.order.*",
                "filter": {"all": [{"path": "data.changed", "op": "contains", "value": "status"},
                                   {"path": "data.after.status", "op": "eq", "value": "paid"}]},
                "input_template": {"input": "Invoice order {{ event.data.after.number }}"}},
                triggers.Actor("user", biz.owner.id))
            await db.commit()
        order = (await client.post("/data/v1/order", headers=_user(biz), json={"number": "A-7"})).json()
        await client.patch(f"/data/v1/order/{order['id']}", headers={**_user(biz), "If-Match": '"1"'},
                           json={"status": "paid"})

    decisions = []
    async with tenant_session(biz.company_id) as db:
        for event_id in biz.nudged:
            decisions += (await router.route(db, biz.company_id, event_id)).get("decisions", [])
        from src.ai.orm import ExecutionRun

        [decision] = decisions
        run = await db.get(ExecutionRun, uuid.UUID(decision["run"]))
    assert decision["trigger"] == str(trigger.id) and decision["outcome"] == "started"
    assert run.input_data["input"] == "Invoice order A-7"


async def test_a_condition_trigger_runs_its_agent_only_when_the_condition_holds(biz, monkeypatch):
    """4.10: "every hour, if stock < 10 → the re-order agent", checked without a model."""
    from src.ai.orm import ExecutionRun, HierarchicalEntity
    from src.automation import router, triggers
    from src.automation.models import TriggerFiring
    from src.automation.scheduler import _envelope
    from src.billing.billing_models import CreditWallet
    from src.common import database
    from src.common.config import settings
    from src.common.tenancy.session import tenant_session

    monkeypatch.setattr(settings, "TENANCY_MODE", "split")
    monkeypatch.setattr("src.ai.service.enqueue_job", lambda *a, **k: _none())
    later = datetime.utcnow() + timedelta(days=1)
    async with database.AsyncSessionLocal() as db:
        db.add(CreditWallet(company_id=biz.company_id, daily_credits=Decimal("0"), daily_expires_at=later,
                            wallet_balance=Decimal("100"), wallet_expires_at=later))
        await db.commit()
    async with _client() as client:
        await client.post("/data/v1/schema/changes", headers=_user(biz), json={"operations": [
            {"op": "add_object", "object": "product", "definition": {"fields": {
                "sku": {"type": "text"}, "stock": {"type": "integer"}}}}]})
        await client.post("/data/v1/product", headers=_user(biz), json={"sku": "TEA-1", "stock": 40})
        async with tenant_session(biz.company_id) as db:
            reorder = HierarchicalEntity(company_id=biz.company_id, type="AGENT", status="ACTIVE", name="Re-order")
            db.add(reorder)
            await db.commit()
            trigger = await triggers.create(db, db, biz.company_id, {
                "name": "Low stock", "kind": "condition", "entity_id": reorder.id, "cron": "0 * * * *",
                "condition": {"object": "product", "filter": [{"field": "stock", "op": "lt", "value": 10}]},
                "input_template": {"input": "{{ trigger.condition.value }} products are low on stock"}},
                triggers.Actor("user", biz.owner.id))
            await db.commit()

        async def hour(moment):
            from src.automation import store

            async with tenant_session(biz.company_id) as db:
                row, _ = await store.record(db, biz.company_id, _envelope(trigger, moment, "Asia/Kolkata", moment))
                await db.commit()
                return (await router.route(db, biz.company_id, row.id))["decisions"]

        [quiet] = await hour(datetime(2026, 10, 18, 9))
        await client.post("/data/v1/product", headers=_user(biz), json={"sku": "TEA-2", "stock": 3})
        [low] = await hour(datetime(2026, 10, 18, 10))

    assert quiet["outcome"] == "skipped_condition_false" and quiet["run"] is None
    assert quiet["reason"] == "condition false: count of product where stock lt 10 is 0 (> 0)"
    assert low["outcome"] == "started"
    async with tenant_session(biz.company_id) as db:
        run = await db.get(ExecutionRun, uuid.UUID(low["run"]))
        assert (await db.get(type(trigger), trigger.id)).firings == 1   # runs started, not checks made
        assert len((await db.execute(select(TriggerFiring).where(TriggerFiring.trigger_id == trigger.id))
                    ).scalars().all()) == 2
    assert run.input_data["input"] == "1 products are low on stock"
    assert run.input_data["condition"] == {"holds": True, "value": 1,
                                           "summary": "count of product where stock lt 10 is 1 (> 0)"}


async def test_links_include_and_batch(biz):
    """An order's account and its shipments; a batch that fails changes nothing."""
    async with _client() as client:
        await client.post("/data/v1/schema/changes", headers=_user(biz), json={"operations": [
            {"op": "add_object", "object": "order", "definition": {"fields": {
                "number": {"type": "text"}, "account": {"type": "ref", "to": "account"}}}},
            {"op": "add_object", "object": "shipment", "definition": {"fields": {
                "carrier": {"type": "text"}, "order": {"type": "ref", "to": "order"}}}}]})
        acme = (await client.post("/data/v1/account", headers=_user(biz), json={"name": "Acme"})).json()
        made = (await client.post("/data/v1/batch", headers=_user(biz), json={"operations": [
            {"op": "create", "object": "order", "values": {"number": "A-1"}},
            {"op": "create", "object": "shipment", "values": {"carrier": "DTDC"}},
            {"op": "create", "object": "shipment", "values": {"carrier": "BlueDart"}}]})).json()["results"]
        order, s1, s2 = made
        base = f"/data/v1/order/{order['id']}/links"

        linked = await client.post(f"{base}/account", headers=_user(biz), json={"id": acme["id"]})
        assert linked.status_code == 200 and linked.json()["changed"][0]["account"] == acme["id"]
        both = (await client.post(f"{base}/shipment", headers=_user(biz), json={"ids": [s1["id"], s2["id"]]})).json()
        assert {r["order"] for r in both["changed"]} == {order["id"]}
        shipments = (await client.get(f"{base}/shipment?sort=carrier", headers=_user(biz))).json()
        assert [r["carrier"] for r in shipments["items"]] == ["BlueDart", "DTDC"]
        assert (await client.get(f"{base}/account", headers=_user(biz))).json()["items"][0]["name"] == "Acme"
        await client.post(f"{base}/shipment", headers=_user(biz), json={"unlink": [s2["id"]]})
        assert len((await client.get(f"{base}/shipment", headers=_user(biz))).json()["items"]) == 1
        other = (await client.post("/data/v1/order", headers=_user(biz), json={"number": "B-1"})).json()
        stays = await client.post(f"/data/v1/order/{other['id']}/links/shipment", headers=_user(biz),
                                  json={"unlink": [s1["id"]]})                # s1 is A-1's, not B-1's
        assert stays.json()["changed"] == []
        assert (await client.get(f"{base}/carrier", headers=_user(biz))).status_code == 404

        one = (await client.get(f"/data/v1/order/{order['id']}?include=account", headers=_user(biz))).json()
        assert one["_included"]["account"]["name"] == "Acme"
        listed = (await client.get("/data/v1/shipment?include=order&sort=carrier", headers=_user(biz))).json()
        assert [i["_included"]["order"] and i["_included"]["order"]["number"] for i in listed["items"]] ==             [None, "A-1"]
        assert (await client.get("/data/v1/order?include=shipment", headers=_user(biz))).status_code == 422

        failed = await client.post("/data/v1/batch", headers=_user(biz), json={"operations": [
            {"op": "create", "object": "order", "values": {"number": "A-2"}},
            {"op": "update", "object": "order", "id": order["id"], "row_version": 99, "values": {"number": "x"}}]})
        assert failed.status_code == 412 and "operation 1" in failed.json()["detail"]
        numbers = [r["number"] for r in (await client.get("/data/v1/order", headers=_user(biz))).json()["items"]]
        assert sorted(numbers) == ["A-1", "B-1"]                         # the batch changed nothing
        assert (await client.post("/data/v1/batch", headers=_user(biz), json={"operations": [
            {"op": "create", "object": "order", "values": {}}] * 101})).status_code == 422


async def test_an_app_key_is_rate_limited(biz, monkeypatch):
    import time

    from src.auth import service
    from src.common.config import settings

    monkeypatch.setattr(settings, "DATA_API_KEY_BURST", 3)
    login = {"Authorization": f"Bearer {service.issue_access_token(biz.owner)}"}
    async with _client() as client:
        key = (await client.post("/api/v1/data-keys", headers=login, json={
            "name": "Busy app", "scopes": {"objects": {"contact": ["read"]}}})).json()["key"]
        frozen = float(int(time.time()) + 3600) + 0.25           # one second of its own, for this key
        monkeypatch.setattr(time, "time", lambda: frozen)
        codes = [(await client.get("/data/v1/contact", headers=_bearer(key))).status_code for _ in range(5)]
        limited = await client.get("/data/v1/contact", headers=_bearer(key))
    assert codes == [200, 200, 200, 429, 429]
    assert limited.headers["retry-after"] == "1" and limited.json()["code"] == "rate_limited"


async def _agent_run(biz, records):
    """An agent with ``capabilities.records`` and a run of it, in the business's database."""
    from src.ai.orm import ExecutionRun, HierarchicalEntity
    from src.common.tenancy.session import tenant_session

    async with tenant_session(biz.company_id) as db:
        agent = HierarchicalEntity(company_id=biz.company_id, type="AGENT", status="ACTIVE", name="Ops Agent",
                                   capabilities={"records": records})
        db.add(agent)
        await db.flush()
        run = ExecutionRun(company_id=biz.company_id, entity_id=agent.id, status="RUNNING", input_data={})
        db.add(run)
        await db.commit()
    return agent, run


async def _inbox(biz):
    from src.ai.orm import HumanApproval
    from src.common.tenancy.session import tenant_session

    async with tenant_session(biz.company_id) as db:
        return (await db.execute(select(HumanApproval).where(HumanApproval.company_id == biz.company_id)
                                 .order_by(HumanApproval.requested_at))).scalars().all()


async def test_an_agents_change_waits_in_the_approvals_inbox(biz, monkeypatch):
    """D20: the change is in the inbox; answering it there applies it; deciding it elsewhere closes it."""
    from src.auth import service
    from src.common.config import settings

    monkeypatch.setattr(settings, "TENANCY_MODE", "split")
    agent, run = await _agent_run(biz, {"objects": {"*": ["read"]}, "schema_changes": "propose"})
    as_run = _bearer(tokens.mint_run_token(run.id, agent, biz.company_id, biz.key))
    owner = {"Authorization": f"Bearer {service.issue_access_token(biz.owner)}"}
    staff = {"Authorization": f"Bearer {service.issue_access_token(biz.staff)}"}
    shipment = {"op": "add_object", "object": "shipment", "definition": {"fields": {"carrier": {"type": "text"}}}}
    async with _client() as client:
        first = (await client.post("/data/v1/schema/changes", headers=as_run, json={
            "reason": "track deliveries", "operations": [shipment]})).json()
        [approval] = await _inbox(biz)
        assert approval.status == "PENDING" and approval.run_id == run.id
        assert approval.checkpoint_trigger == "SCHEMA_CHANGE: add object shipment"
        assert approval.context_snapshot["change_id"] == first["id"]
        assert "Ops Agent proposes a change" in approval.context_snapshot["message"]
        assert (await client.get("/api/v1/ai/approvals/pending", headers=owner)).json()[0]["id"] == str(approval.id)

        url = f"/api/v1/ai/approvals/{approval.id}/respond"
        assert (await client.post(url, headers=staff, json={"status": "APPROVED"})).status_code == 403
        answered = (await client.post(url, headers=owner, json={"status": "APPROVED"})).json()
        assert answered["schema_change"]["status"] == "applied"
        assert answered["schema_change"]["decided_by"] == f"user:{biz.owner.id}"
        assert (await client.post("/data/v1/shipment", headers=_user(biz), json={"carrier": "DTDC"})).status_code             == 201

        second = (await client.post("/data/v1/schema/changes", headers=as_run, json={"operations": [
            {"op": "add_field", "object": "shipment", "field": "eta", "definition": {"type": "date"}}]})).json()
        await client.post(f"/data/v1/schema/changes/{second['id']}/reject", headers=_user(biz))
    closed = [a for a in await _inbox(biz) if a.context_snapshot["change_id"] == second["id"]]
    assert [a.status for a in closed] == ["REJECTED"]


async def test_the_owner_may_let_agents_simple_additions_through(biz, monkeypatch):
    from src.auth import service
    from src.common.config import settings

    monkeypatch.setattr(settings, "TENANCY_MODE", "split")
    agent, run = await _agent_run(biz, {"objects": {"*": ["read"]}, "schema_changes": "propose"})
    as_run = _bearer(tokens.mint_run_token(run.id, agent, biz.company_id, biz.key))
    owner = {"Authorization": f"Bearer {service.issue_access_token(biz.owner)}"}
    staff = {"Authorization": f"Bearer {service.issue_access_token(biz.staff)}"}
    async with _client() as client:
        assert (await client.get("/api/v1/records/settings", headers=owner)).json()[
            "agents_auto_approve_additive"] is False
        assert (await client.put("/api/v1/records/settings", headers=staff,
                                 json={"agents_auto_approve_additive": True})).status_code == 403
        saved = (await client.put("/api/v1/records/settings", headers=owner,
                                  json={"agents_auto_approve_additive": True})).json()
        assert saved["agents_auto_approve_additive"] is True and saved["updated_by"] == f"user:{biz.owner.id}"

        added = (await client.post("/data/v1/schema/changes", headers=as_run, json={"operations": [
            {"op": "add_field", "object": "contact", "field": "x_tier", "definition": {"type": "text"}}]})).json()
        narrowed = (await client.post("/data/v1/schema/changes", headers=as_run, json={"operations": [
            {"op": "make_required", "object": "contact", "field": "x_tier"}]})).json()
    assert added["status"] == "applied"
    assert narrowed["status"] == "awaiting_approval"
    assert [a.context_snapshot["change_id"] for a in await _inbox(biz)] == [narrowed["id"]]


async def _none():
    return None
