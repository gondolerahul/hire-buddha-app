"""Tenant apps end to end (Phase 14 WS6 6.6–6.12; tech spec §11.4–§11.7; plan M6).

A throwaway business database, the built-in Git in a temporary folder, storage
in memory, a builder and a runtime that record what they are asked (the
Docker and ACR Tasks builders and the Kubernetes runtime have their own tests):

* an owner creates a CRM from the template for their objects: a repository
  with the first commit, default roles, a build; publishing runs it at
  ``crm-<slug>.<APPS_DOMAIN>`` (recorded for the edge); a second version is
  published and rolled back in one step; stop and start;
* a custom domain is served only once its DNS records are right, and the
  edge's ``ask`` answers for it from then on; previews expire;
* a website's form gets a public key that can only create its one object;
* app users sign in at the Data API and see only their own rows where their
  role says so; refresh tokens rotate; disabling a user ends their tokens; a
  magic link signs in once;
* an hour of hosting is metered once.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.needs_db


class FakeBuilder:
    name = "docker"

    def __init__(self):
        self.contexts = []

    async def build(self, context, *, repository, tag, labels):
        from src.apps.build import BuildResult

        self.contexts.append((repository, tag, context))
        return BuildResult(image=f"{repository}:{tag}", digest=f"sha256:{tag}", log=f"built {tag}",
                           scan={"tool": "trivy", "critical": 0, "high": 0})


class FakeRuntime:
    name = "fake"

    def __init__(self):
        self.applied, self.calls = [], []

    async def apply(self, spec):
        self.applied.append(spec)
        return {"ref": spec.instance, "url": f"https://{spec.hostnames[0]}" if spec.hostnames else None}

    async def stop(self, namespace, instance):
        self.calls.append(("stop", instance))

    async def start(self, namespace, instance):
        self.calls.append(("start", instance))

    async def restart(self, namespace, instance):
        self.calls.append(("restart", instance))

    async def delete(self, namespace, instance):
        self.calls.append(("delete", instance))

    async def status(self, namespace, instance):
        return {"phase": "Running"}

    async def logs(self, namespace, instance, *, tail=200, since_seconds=None):
        return f"log of {instance}"

    async def metrics(self, namespace, instance):
        return {"source": "fake"}


@pytest_asyncio.fixture
async def biz(monkeypatch, tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import src.common.orm_models  # noqa: F401
    from src.apps.build import set_builder
    from src.apps.runtime import set_runtime
    from src.automation import store
    from src.code_lanes.git import LocalGitProvider, set_builtin_provider
    from src.common import database
    from src.common.config import settings
    from src.common.platform.kek import set_kek
    from src.common.platform.kek.local import LocalKeyEncryption
    from src.common.platform.storage import set_storage
    from src.connections import crypto
    from src.data_api import app_users
    from tests.harness.storage import MemoryStorage
    from tests.harness.tenant_db import scratch_tenant

    control = create_async_engine(settings.CONTROL_DATABASE_URL, poolclass=NullPool,
                                  json_serializer=database.json_serializer)
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(control, expire_on_commit=False))
    monkeypatch.setattr(database, "engine", control)
    monkeypatch.setattr(settings, "APPS_DOMAIN", "apps.example.test")

    async def _nudge(company_id, event_id, **kw):
        return None

    async def _enqueue(function, *args, **kwargs):
        return None

    monkeypatch.setattr(store, "nudge", _nudge)
    monkeypatch.setattr("src.common.job_queue.enqueue_job", _enqueue)
    set_kek(LocalKeyEncryption(tmp_path / "keys"))
    crypto.forget_cached()
    app_users.forget_keys()
    set_storage(MemoryStorage())
    set_builtin_provider(LocalGitProvider(tmp_path / "git"))
    builder, runtime = FakeBuilder(), FakeRuntime()
    set_builder(builder)
    set_runtime(runtime)
    try:
        async with scratch_tenant("apps") as t:
            t.builder, t.runtime = builder, runtime
            t.owner = SimpleNamespace(id=uuid.uuid4(), role="tenant_admin", email="owner@acme.test")
            yield t
    finally:
        for reset in (set_storage, set_builtin_provider, set_builder, set_runtime, set_kek):
            reset(None)
        crypto.forget_cached()
        app_users.forget_keys()
        await control.dispose()


async def _build(biz, app_id):
    from src.apps import service as apps
    from src.apps.db import app_session
    from src.apps.models import AppBuild

    queued = await apps.start_build(biz.company_id, app_id)
    built = await apps.run_build(biz.company_id, queued["id"])
    assert built["status"] == "succeeded", built
    async with app_session(biz.company_id) as db:
        return await db.get(AppBuild, uuid.UUID(built["id"]))


async def _events(biz, prefix):
    from src.automation.models import Event
    from src.common.tenancy.session import tenant_session

    async with tenant_session(biz.company_id) as db:
        rows = (await db.execute(select(Event).where(Event.company_id == biz.company_id,
                                                     Event.type.like(f"{prefix}%")))).scalars().all()
    return [r.type for r in rows]


async def test_a_crm_is_created_built_published_rolled_back_and_operated(biz):
    from src.apps import service as apps
    from src.apps.models import CustomDomain
    from src.common.tenancy.session import control_session

    with pytest.raises(apps.AppProblem, match="name the objects"):
        await apps.create_app(biz.company_id, biz.owner, name="crm", display_name="Sales", template="crm_admin")
    with pytest.raises(apps.AppProblem, match="no such object"):
        await apps.create_app(biz.company_id, biz.owner, name="crm", display_name="Sales", template="crm_admin",
                              objects=["nonsense"])
    app = await apps.create_app(biz.company_id, biz.owner, name="crm", display_name="Sales", template="crm_admin",
                                objects=["contact", "account"])
    assert app["status"] == "building" and app["objects"] == ["contact", "account"] and app["commit_sha"]
    detail = await apps.get_app(biz.company_id, app["id"])
    assert {r["name"] for r in detail["roles"]} == {"admin", "staff"}
    with pytest.raises(apps.AppProblem, match="exists"):
        await apps.create_app(biz.company_id, biz.owner, name="crm", display_name="Again", template="crm_admin",
                              objects=["contact"])

    first = await apps.run_build(biz.company_id, app["build"]["id"])
    assert first["status"] == "succeeded" and first["log_key"] and first["cost"] is not None
    repository, tag, _ = biz.builder.contexts[0]
    assert repository == f"hb-apps/t-{biz.key}/crm" and tag == app["commit_sha"][:12]
    assert (await apps.get_app(biz.company_id, app["id"]))["status"] == "ready"
    assert "built" in await apps.build_log(biz.company_id, app["id"], first["id"])

    published = await apps.publish(biz.company_id, app["id"], user_id=biz.owner.id)
    host = published["hostnames"][0]
    assert host.startswith("crm-") and host.endswith(".apps.example.test") and published["status"] == "active"
    spec = biz.runtime.applied[-1]
    assert spec.instance == "crm" and spec.mode == "always_on" and spec.app_key is None
    assert spec.env["HB_TENANT_KEY"] == biz.key and spec.env["HB_APP"] == "crm"
    async with control_session() as cdb:
        row = await cdb.get(CustomDomain, host)
    assert row.kind == "platform" and row.status == "verified" and row.upstream.startswith(f"crm.t-{biz.key}.svc")
    view = await apps.get_app(biz.company_id, app["id"])
    assert view["status"] == "published" and view["url"] == f"https://{host}"

    second = await _build(biz, app["id"])
    again = await apps.publish(biz.company_id, app["id"], build_id=second.id)
    assert again["build_id"] == str(second.id)
    back = await apps.rollback(biz.company_id, app["id"])
    assert back["build_id"] == first["id"] and biz.runtime.applied[-1].image.endswith(first["commit_sha"][:12])
    deployments = await apps.list_deployments(biz.company_id, app["id"])
    assert [d["status"] for d in deployments][:3] == ["active", "superseded", "superseded"]

    stopped = await apps.operate(biz.company_id, app["id"], "stop")
    assert stopped["status"] == "stopped" and biz.runtime.calls[-1] == ("stop", "crm")
    assert (await apps.operate(biz.company_id, app["id"], "start"))["status"] == "published"
    assert await apps.logs(biz.company_id, app["id"]) == "log of crm"
    with pytest.raises(apps.AppProblem):
        await apps.logs(biz.company_id, app["id"], instance="other-app")
    types = await _events(biz, "app.")
    assert types.count("app.build.succeeded") == 2 and types.count("app.deployed") == 3

    changed = await apps.update_settings(biz.company_id, app["id"], mode="sleep", outbound_allowlist=["Api.Stripe.com"],
                                         resources={"cpu": "500m", "memory": "512Mi"}, env={"GREETING": "hi"})
    assert changed["mode"] == "sleep" and changed["outbound_allowlist"] == ["api.stripe.com"]
    spec = biz.runtime.applied[-1]
    assert spec.mode == "sleep" and spec.egress == ["api.stripe.com"] and spec.env["GREETING"] == "hi"
    for bad in ({"resources": {"cpu": "64"}}, {"env": {"HB_APP": "x"}}, {"outbound_allowlist": ["not a host"]}):
        with pytest.raises(apps.AppProblem):
            await apps.update_settings(biz.company_id, app["id"], **bad)


async def test_a_custom_domain_is_served_once_its_dns_is_right(biz):
    from src.apps import domains, service as apps

    app = await apps.create_app(biz.company_id, biz.owner, name="site", display_name="Acme", template="static_site")
    await apps.run_build(biz.company_id, app["build"]["id"])
    await apps.publish(biz.company_id, app["id"])
    added = await domains.add(biz.company_id, app["id"], "WWW.Acme-Test.com")
    assert added["hostname"] == "www.acme-test.com" and added["status"] == "pending"
    records = {r["type"]: r for r in added["dns_records"]}
    target, token = records["CNAME"]["value"], records["TXT"]["value"]
    assert target.startswith("site-") and records["TXT"]["name"] == "_hb-verify.www.acme-test.com"
    assert not await domains.may_serve("www.acme-test.com")

    async def wrong(name, kind):
        return []

    pending = await domains.verify(biz.company_id, app["id"], "www.acme-test.com", resolver=wrong)
    assert pending["status"] == "pending" and "does not point" in pending["last_error"]

    async def right(name, kind):
        return {"TXT": [token], "CNAME": [target]}.get(kind, [])

    verified = await domains.verify(biz.company_id, app["id"], "www.acme-test.com", resolver=right)
    assert verified["status"] == "verified" and verified["cert_status"] == "pending"
    assert "www.acme-test.com" in biz.runtime.applied[-1].hostnames   # the published app now answers to it
    assert await domains.may_serve("www.acme-test.com")
    assert not await domains.may_serve("someone-else.com")
    with pytest.raises(apps.AppProblem, match="already used"):
        other = await apps.create_app(biz.company_id, biz.owner, name="blog", display_name="Blog",
                                      template="static_site")
        await domains.add(biz.company_id, other["id"], "www.acme-test.com")

    from src.apps.api import edge_ask, edge_token

    assert (await edge_ask(domain="www.acme-test.com", token=edge_token())).status_code == 200
    assert (await edge_ask(domain="www.acme-test.com", token="wrong")).status_code == 403
    await domains.remove(biz.company_id, app["id"], "www.acme-test.com")
    assert not await domains.may_serve("www.acme-test.com")

    preview = await apps.preview(biz.company_id, app["id"])
    assert preview["kind"] == "preview" and preview["hostnames"][0].startswith("site-")
    assert await apps.expire_previews(biz.company_id, app["id"]) == 0
    assert await apps.expire_previews(biz.company_id, app["id"], now=datetime.utcnow() + timedelta(days=8)) == 1
    assert biz.runtime.calls[-1] == ("delete", "site-preview")


async def test_a_forms_public_key_only_creates_its_one_object(biz):
    from src.apps import service as apps

    app = await apps.create_app(biz.company_id, biz.owner, name="enquiries", display_name="Acme",
                                template="site_forms", params={"form_object": "contact"})
    await apps.run_build(biz.company_id, app["build"]["id"])
    await apps.publish(biz.company_id, app["id"])
    key = biz.runtime.applied[-1].env["HB_PUBLIC_KEY"]
    assert key.startswith(f"hbk_dev_{biz.key}_")
    from src.main import app as platform

    from src.schema_engine import approvals
    from src.schema_engine import engine as schema

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=platform), base_url="http://t") as client:
        auth = {"Authorization": f"Bearer {key}"}
        visitor = {"first_name": "Visitor", "email": "v@example.com"}
        off = await client.post("/data/v1/contact", headers=auth, json=visitor)
        assert off.status_code == 401 and "public API access is off" in off.json()["detail"]   # off by default
        engine, _ = await schema.business_engine(biz.company_id)
        await approvals.save_settings(engine, biz.company_id, public_api_access=True, updated_by="user:owner")
        created = await client.post("/data/v1/contact", headers=auth, json=visitor)
        assert created.status_code == 201
        assert (await client.get("/data/v1/contact", headers=auth)).status_code == 403
        assert (await client.post("/data/v1/account", headers=auth, json={"name": "x"})).status_code == 403
        preflight = await client.options("/data/v1/contact", headers={
            "Origin": "https://enquiries-x.apps.example.test", "Access-Control-Request-Method": "POST"})
        assert preflight.status_code == 204 and preflight.headers["access-control-allow-origin"] == "*"


async def _deal_object(biz):
    from src.schema_engine import engine as schema

    engine, _ = await schema.business_engine(biz.company_id)
    change = await schema.propose(engine, biz.company_id, [
        {"op": "add_object", "object": "deal", "definition": {"fields": {
            "title": {"type": "text", "required": True}, "owner_email": {"type": "email"},
            "amount": {"type": "integer"}}, "row_policy": {"owner_field": "owner_email"}}}],
        actor_kind="user", actor_id=f"user:{biz.owner.id}")
    assert change["status"] == "applied", change


async def test_app_users_sign_in_and_see_only_their_own_rows(biz, monkeypatch):
    from src.apps import service as apps
    from src.data_api import app_users
    from src.main import app as platform

    await _deal_object(biz)
    app = await apps.create_app(biz.company_id, biz.owner, name="sales", display_name="Sales", template="crm_admin",
                                objects=["deal", "contact"])
    await apps.save_user(biz.company_id, app["id"], email="Alice@Acme.test", roles=["staff"], password="alice-pass-1")
    await apps.save_user(biz.company_id, app["id"], email="bob@acme.test", roles=["staff"], password="bob-pass-12")
    boss = await apps.save_user(biz.company_id, app["id"], email="boss@acme.test", roles=["admin"],
                                password="boss-pass-1")
    assert boss["status"] == "active" and boss["roles"] == ["admin"]
    invited = await apps.save_user(biz.company_id, app["id"], email="new@acme.test", roles=["staff"])
    assert invited["status"] == "invited" and not invited["has_password"]
    with pytest.raises(apps.AppProblem, match="no such role"):
        await apps.save_user(biz.company_id, app["id"], email="x@acme.test", roles=["ghost"])

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=platform), base_url="http://t") as client:
        async def login(email, password):
            return await client.post("/data/v1/auth/login", json={"tenant": biz.key, "app": "sales", "email": email,
                                                                   "password": password})

        assert (await login("alice@acme.test", "wrong")).status_code == 401
        assert (await login("new@acme.test", "anything")).status_code == 401
        alice, bob, chief = [(await login(e, p)).json() for e, p in (
            ("alice@acme.test", "alice-pass-1"), ("bob@acme.test", "bob-pass-12"), ("boss@acme.test", "boss-pass-1"))]
        h = {name: {"Authorization": f"Bearer {tokens['access_token']}"}
             for name, tokens in (("alice", alice), ("bob", bob), ("boss", chief))}
        me = (await client.get("/data/v1/auth/me", headers=h["alice"])).json()
        assert me["email"] == "alice@acme.test" and me["roles"] == ["staff"] and "deal" in me["own_rows"]

        mine = await client.post("/data/v1/deal", headers=h["alice"], json={"title": "A", "owner_email": "bob@acme.test"})
        assert mine.status_code == 201 and mine.json()["owner_email"] == "alice@acme.test"   # a row is its creator's
        theirs = (await client.post("/data/v1/deal", headers=h["bob"], json={"title": "B"})).json()
        listed = (await client.get("/data/v1/deal", headers=h["alice"])).json()["items"]
        assert [d["title"] for d in listed] == ["A"]
        assert len((await client.get("/data/v1/deal", headers=h["boss"])).json()["items"]) == 2
        assert (await client.get(f"/data/v1/deal/{theirs['id']}", headers=h["alice"])).status_code == 404
        patched = await client.patch(f"/data/v1/deal/{theirs['id']}", headers={**h["alice"], "If-Match": '"1"'},
                                     json={"title": "mine now"})
        assert patched.status_code == 404
        assert (await client.delete(f"/data/v1/deal/{theirs['id']}", headers=h["alice"])).status_code == 403  # staff never archive
        assert (await client.delete(f"/data/v1/deal/{theirs['id']}", headers=h["boss"])).status_code == 200
        assert (await client.post("/data/v1/batch", headers=h["alice"], json={"operations": [
            {"op": "create", "object": "deal", "values": {"title": "x"}}]})).status_code == 403
        # contact names no owner field: a role limited to its own rows sees none and creates none
        assert (await client.get("/data/v1/contact", headers=h["alice"])).json()["items"] == []
        assert (await client.post("/data/v1/contact", headers=h["alice"], json={"first_name": "X"})).status_code == 403
        assert (await client.get("/data/v1/account", headers=h["alice"])).status_code == 403   # not in the app

        rotated = await client.post("/data/v1/auth/refresh", json={"refresh_token": alice["refresh_token"]})
        assert rotated.status_code == 200
        assert (await client.post("/data/v1/auth/refresh", json={"refresh_token": alice["refresh_token"]})).status_code \
            == 401
        users = await apps.list_users(biz.company_id, app["id"])
        alice_id = next(u["id"] for u in users if u["email"] == "alice@acme.test")
        await apps.save_user(biz.company_id, app["id"], email="", status="disabled", user_id=alice_id)
        fresh = {"Authorization": f"Bearer {rotated.json()['access_token']}"}
        assert (await client.get("/data/v1/deal", headers=fresh)).status_code == 401

        sent = []

        async def capture(email, app_name, link):
            sent.append(link)

        monkeypatch.setattr(app_users, "_send_link", capture)
        bad = await client.post("/data/v1/auth/magic-link", json={"tenant": biz.key, "app": "sales",
                                                                  "email": "new@acme.test",
                                                                  "return_url": "https://evil.example.com/"})
        assert bad.status_code == 400 and not sent
        ok = await client.post("/data/v1/auth/magic-link", json={"tenant": biz.key, "app": "sales",
                                                                 "email": "new@acme.test",
                                                                 "return_url": "http://localhost:5173/"})
        assert ok.status_code == 202 and len(sent) == 1
        token = parse_qs(urlparse(sent[0]).query)["hb_magic"][0]
        signed = await client.post("/data/v1/auth/magic-link/verify", json={"token": token})
        assert signed.status_code == 200 and signed.json()["access_token"]
        replay = await client.post("/data/v1/auth/magic-link/verify", json={"token": token})
        assert replay.status_code == 401
    users = {u["email"]: u for u in await apps.list_users(biz.company_id, app["id"])}
    assert users["new@acme.test"]["status"] == "active"


async def test_an_hour_of_hosting_is_metered_once(biz):
    from src.apps import service as apps
    from src.apps.metering import meter_hour
    from src.apps.models import AppUsage
    from src.apps.db import app_session

    app = await apps.create_app(biz.company_id, biz.owner, name="meter", display_name="Meter", template="static_site")
    await apps.run_build(biz.company_id, app["build"]["id"])
    await apps.publish(biz.company_id, app["id"])
    hour = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    first = await meter_hour(biz.company_id, hour, source="requests")
    assert [m["app"] for m in first] == ["meter"] and first[0]["vcpu_hours"] > 0 and first[0]["gb_hours"] > 0
    assert await meter_hour(biz.company_id, hour, source="requests") == []
    async with app_session(biz.company_id) as db:
        rows = (await db.execute(select(AppUsage).where(AppUsage.app_id == uuid.UUID(app["id"])))).scalars().all()
    assert len(rows) == 1 and rows[0].source == "requests"
    metrics = await apps.metrics(biz.company_id, app["id"])
    assert metrics["now"] == {"source": "fake"} and len(metrics["hourly"]) == 1
