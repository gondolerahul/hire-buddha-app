"""Connections end to end (Phase 14 WS5; functional spec §6; E09-S07 … E09-S10).

Real Postgres and Redis, a played provider (httpx MockTransport) and a local
KEK in a temporary directory; the rows this module commits are purged with
its companies.

* An owner connects Gmail through Google's sign-in: the browser leaves with a
  PKCE challenge, returns to the callback, chooses the account; the token is
  sealed (never in a listing or a row's plain text), only the agent granted it
  receives it, it is refreshed when about to expire, every issue is audited.
* One business per account: a second business is refused with a neutral message.
* Disconnecting revokes at the provider, deletes the secret, removes the route,
  pauses the trigger listening to it and emits ``connection.revoked``.
* A mailbox is connected with a form and tested.
* A signed Meta delivery for a connected Page becomes the owner's event; one
  for an unknown Page is kept (hashed) for staff; a bad signature is refused.
* Secrets are sealed per row; rotating the DEK re-seals them; shredding the
  KEK makes them unreadable.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text, update

import src.main  # noqa: F401  (every model mapped)

pytestmark = [pytest.mark.needs_db]


@pytest_asyncio.fixture
async def world(monkeypatch, tmp_path):
    """Two businesses with an owner each; a local KEK; this test's own control engine."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from src.auth.models import Company, User
    from src.common import database
    from src.common.config import settings
    from src.common.platform.kek import set_kek
    from src.common.platform.kek.local import LocalKeyEncryption
    from src.common.tenancy.session import control_session
    from src.connections import crypto
    from tests.harness.infra import infra_unavailable

    engine = create_async_engine(settings.CONTROL_DATABASE_URL, poolclass=NullPool,
                                 json_serializer=database.json_serializer)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        await engine.dispose()
        infra_unavailable(f"Postgres unreachable ({exc})")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(settings, "TENANCY_MODE", "single")
    set_kek(LocalKeyEncryption(tmp_path / "keys"))
    crypto.forget_cached()

    nudged = []

    async def _nudge(company_id, event_id, **kw):
        nudged.append(event_id)

    monkeypatch.setattr("src.automation.store.nudge", _nudge)
    companies, users = [], []
    async with control_session() as db:
        for name in ("conn-acme", "conn-beta"):
            company = Company(id=uuid.uuid4(), name=f"{name}-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
            db.add(company)
            await db.flush()
            user = User(id=uuid.uuid4(), email=f"{name}-{uuid.uuid4().hex[:8]}@test.local", full_name="Owner",
                        hashed_password="x", company_id=company.id, role="tenant_admin", is_active=True,
                        is_verified=True)
            db.add(user)
            companies.append(company.id)
            users.append(SimpleNamespace(id=user.id, company_id=company.id, role="tenant_admin", email=user.email))
        await db.commit()
    try:
        yield SimpleNamespace(acme=users[0], beta=users[1], nudged=nudged)
    finally:
        set_kek(None)
        crypto.forget_cached()
        from src.connections.providers import base as provider_base
        from tests.harness.purge import purge_companies

        provider_base.set_transport(None)
        async with control_session() as db:
            await db.execute(text("DELETE FROM connection_audit WHERE company_id = ANY(:c)"), {"c": companies})
            await purge_companies(await db.connection(), companies)
            await db.commit()
        await engine.dispose()


@pytest_asyncio.fixture
async def connectable(world):
    """Gmail and Facebook Pages switched on for the test (staff override), then back."""
    from src.common.tenancy.session import control_session
    from src.connections.catalog import sync_catalog
    from src.connections.models import ConnectorCatalogEntry

    async with control_session() as db:
        await sync_catalog(db)
        before = {row.id: row.status_override for row in (await db.execute(select(ConnectorCatalogEntry).where(
            ConnectorCatalogEntry.id.in_(["gmail", "facebook_pages"])))).scalars().all()}
        await db.execute(update(ConnectorCatalogEntry).where(ConnectorCatalogEntry.id.in_(list(before)))
                         .values(status_override="available"))
        await db.commit()
    yield
    async with control_session() as db:
        for connector_id, override in before.items():
            await db.execute(update(ConnectorCatalogEntry).where(ConnectorCatalogEntry.id == connector_id)
                             .values(status_override=override))
        await db.commit()


def _app(user):
    from fastapi import FastAPI

    from src.auth.dependencies import get_current_user
    from src.common.tenancy.errors import install_tenancy_error_handlers
    from src.connections import api

    app = FastAPI()
    app.include_router(api.router)
    install_tenancy_error_handlers(app)

    async def _user():
        return user["user"]

    app.dependency_overrides[get_current_user] = _user
    return app


class Google:
    """Google's token and userinfo endpoints, played."""

    def __init__(self, sub="g-acme"):
        self.sub, self.requests, self.issued = sub, [], 0

    def __call__(self, request):
        self.requests.append(request)
        if str(request.url).startswith("https://oauth2.googleapis.com/token"):
            self.issued += 1
            return httpx.Response(200, json={"access_token": f"google-token-{self.issued}",
                                             "refresh_token": "google-refresh", "expires_in": 3600,
                                             "scope": "openid email https://www.googleapis.com/auth/gmail.modify"})
        if str(request.url).startswith("https://oauth2.googleapis.com/revoke"):
            return httpx.Response(200, json={})
        if "userinfo" in str(request.url):
            return httpx.Response(200, json={"sub": self.sub, "email": "sales@acme.test"})
        return httpx.Response(404, json={})


async def _sign_in(client, google_sub="g-acme"):
    """start → the provider → callback; returns the pending id."""
    start = await client.post("/api/v1/connections/start", json={"connector_id": "gmail",
                                                                  "return_path": "/connections"})
    assert start.status_code == 200, start.text
    query = parse_qs(urlparse(start.json()["url"]).query)
    assert query["code_challenge_method"] == ["S256"]
    back = await client.get(f"/oauth/callback/google?code=code-1&state={query['state'][0]}", follow_redirects=False)
    assert back.status_code == 302, back.text
    landing = parse_qs(urlparse(back.headers["location"]).query)
    assert "pending" in landing, back.headers["location"]
    return landing["pending"][0]


async def test_an_owner_connects_gmail_and_only_the_granted_agent_uses_it(world, connectable, monkeypatch):
    from src.automation.models import Event, Trigger
    from src.common.tenancy.session import control_session, tenant_session
    from src.connections import service
    from src.connections.apps import ProviderApp, set_app
    from src.connections.models import Connection, ConnectionAudit, ConnectionSecret, ExternalAccountRoute
    from src.connections.providers import base as provider_base

    from src.ai.orm.entity import HierarchicalEntity

    google = Google()
    provider_base.set_transport(httpx.MockTransport(google))
    set_app(ProviderApp(ref="oauth-app-google", client_id="cid", client_secret="csecret"))
    stranger = uuid.uuid4()
    async with tenant_session(world.acme.company_id) as db:
        entity = HierarchicalEntity(company_id=world.acme.company_id, type="AGENT", status="ACTIVE",
                                    name="Inbox agent")
        db.add(entity)
        await db.commit()
        agent = entity.id
    caller = {"user": world.acme}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(caller)), base_url="http://t") as client:
            pending_id = await _sign_in(client)
            choose = await client.get(f"/api/v1/connections/pending/{pending_id}")
            assert [a["name"] for a in choose.json()["accounts"]] == ["sales@acme.test"]
            assert choose.json()["accounts"][0]["available"] is True
            done = await client.post(f"/api/v1/connections/pending/{pending_id}/finalize", json={
                "accounts": ["g-acme"], "grants": [{"principal_kind": "entity", "principal_id": str(agent)}]})
            assert done.status_code == 200, done.text
            [made] = done.json()["connections"]
            connection_id = uuid.UUID(made["id"])
            assert made["status"] == "active" and made["test"]["ok"] is True
            listed = (await client.get("/api/v1/connections")).json()
            assert "google-token" not in json.dumps(listed)

        # The secret is sealed: not in the row's bytes, and only for this row.
        async with tenant_session(world.acme.company_id) as db:
            row = await db.get(ConnectionSecret, connection_id)
            assert b"google-token" not in bytes(row.ciphertext) and b"google-refresh" not in bytes(row.ciphertext)

        # The token broker: the granted agent gets it, another agent does not.
        token = await service.issue_token(world.acme.company_id, connection_id, principal_kind="entity",
                                          principal_id=agent, action="read_mail")
        assert token.access_token == "google-token-1"
        with pytest.raises(service.NotGranted):
            await service.issue_token(world.acme.company_id, connection_id, principal_kind="entity",
                                      principal_id=stranger)
        # About to expire: refreshed first.
        async with tenant_session(world.acme.company_id) as db:
            await db.execute(update(Connection).where(Connection.id == connection_id)
                             .values(token_expires_at=datetime.utcnow() + timedelta(seconds=30)))
            await db.commit()
        refreshed = await service.issue_token(world.acme.company_id, connection_id, principal_kind="entity",
                                              principal_id=agent)
        assert refreshed.access_token == "google-token-2"
        async with tenant_session(world.acme.company_id) as db:
            actions = (await db.execute(select(ConnectionAudit.action).where(
                ConnectionAudit.connection_id == connection_id).order_by(ConnectionAudit.at))).scalars().all()
        assert {"connected", "test_ok", "token_issued", "refused", "refreshed"} <= set(actions)

        # One business per account: Beta signing in to the same Google account is refused.
        caller["user"] = world.beta
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(caller)), base_url="http://t") as client:
            pending_id = await _sign_in(client)
            assert (await client.get(f"/api/v1/connections/pending/{pending_id}")).json()["accounts"][0]["available"] is False
            refused = await client.post(f"/api/v1/connections/pending/{pending_id}/finalize",
                                        json={"accounts": ["g-acme"]})
            assert refused.json() == {"connections": [], "refused": [
                {"external_id": "g-acme", "name": "sales@acme.test", "reason": service.ACCOUNT_TAKEN}]}

        # Disconnect: the trigger listening to it pauses; the route and the secret go.
        async with tenant_session(world.acme.company_id) as db:
            trigger = Trigger(company_id=world.acme.company_id, name="New mail", kind="event", entity_id=agent,
                              event_type="email.received",
                              filter={"path": "subject", "op": "eq", "value": f"connection:{connection_id}"},
                              created_by_kind="user")
            db.add(trigger)
            await db.commit()
            trigger_id = trigger.id
        caller["user"] = world.acme
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(caller)), base_url="http://t") as client:
            impact = (await client.get(f"/api/v1/connections/{connection_id}/impact")).json()
            assert [t["name"] for t in impact["triggers"]] == ["New mail"] and impact["agents"][0]["id"] == str(agent)
            gone = await client.delete(f"/api/v1/connections/{connection_id}")
            assert gone.json()["triggers_paused"] == ["New mail"], gone.text
        assert any(str(r.url).startswith("https://oauth2.googleapis.com/revoke") for r in google.requests)
        async with tenant_session(world.acme.company_id) as db:
            assert (await db.get(Trigger, trigger_id)).enabled is False
            assert await db.get(ConnectionSecret, connection_id) is None
            assert (await db.get(Connection, connection_id)).status == "revoked"
            types = (await db.execute(select(Event.type).where(Event.company_id == world.acme.company_id))
                     ).scalars().all()
            assert {"connection.connected", "connection.revoked"} <= set(types)
            await db.execute(delete(Trigger).where(Trigger.id == trigger_id))
            await db.commit()
        async with control_session() as db:
            assert await db.get(ExternalAccountRoute, ("google", "g-acme")) is None
        with pytest.raises(service.ConnectionProblem):
            await service.issue_token(world.acme.company_id, connection_id, principal_kind="entity",
                                      principal_id=agent)
    finally:
        set_app(None, "oauth-app-google")


async def test_a_mailbox_is_connected_with_a_form(world, monkeypatch):
    from src.connections import service
    from src.connections.providers import PROVIDERS

    async def _test(app, connector, settings, secret):
        assert secret == {"password": "app-pass"}
        return {"ok": True, "detail": f"signed in to {settings['imap_host']}"}

    monkeypatch.setattr(PROVIDERS["mailbox"], "test", _test)
    caller = {"user": world.acme}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(caller)), base_url="http://t") as client:
        form = (await client.post("/api/v1/connections/start", json={"connector_id": "imap_mailbox"})).json()
        assert form["kind"] == "form" and form["form"][1] == {
            "name": "password", "label": "App password", "kind": "secret", "required": True, "default": None}
        made = await client.post("/api/v1/connections/form", json={
            "connector_id": "imap_mailbox", "fields": {"email_address": "ops@acme.test", "password": "app-pass"}})
        assert made.status_code == 200, made.text
        assert made.json()["test"] == {"ok": True, "detail": "signed in to imap.gmail.com"}
        assert "password" not in made.json()["settings"]
        missing = await client.post("/api/v1/connections/form", json={
            "connector_id": "imap_mailbox", "fields": {"email_address": "x@acme.test"}})
        assert missing.status_code == 409 and "App password is required" in missing.text
        caller["user"] = SimpleNamespace(**{**vars(world.acme), "role": "tenant_user"})
        assert (await client.post("/api/v1/connections/form", json={
            "connector_id": "imap_mailbox", "fields": {}})).status_code == 403
    # The e-mail tools now read it through the broker (all agents by default).
    from src.connections.client import email_credentials

    creds = await email_credentials({"company_id": str(world.acme.company_id), "entity_id": str(uuid.uuid4())})
    assert (creds["email_address"], creds["password"]) == ("ops@acme.test", "app-pass")


async def test_a_signed_meta_delivery_reaches_the_page_owner(world):
    from src.automation.models import Event
    from src.common.tenancy.session import control_session, tenant_session
    from src.connections.apps import ProviderApp, set_app
    from src.connections.models import Connection, ExternalAccountRoute, UnroutedEvent
    from src.connections.webhooks import router

    page = f"page-{uuid.uuid4().hex[:8]}"
    set_app(ProviderApp(ref="oauth-app-meta", client_id="111", client_secret="appsecret"))
    connection_id = uuid.uuid4()
    async with tenant_session(world.acme.company_id) as db:
        db.add(Connection(id=connection_id, company_id=world.acme.company_id, connector_id="facebook_pages",
                          display_name="Acme Store", external_account_id=page, status="active"))
        await db.commit()
    async with control_session() as db:
        db.add(ExternalAccountRoute(provider="meta", external_account_id=page, company_id=world.acme.company_id,
                                    connection_id=connection_id))
        await db.commit()
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    def signed(payload, secret=b"appsecret"):
        body = json.dumps(payload).encode()
        return body, {"x-hub-signature-256": "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest(),
                      "content-type": "application/json"}

    delivery = {"object": "page", "entry": [{"id": page, "time": 1, "changes": [
        {"field": "feed", "value": {"item": "comment", "message": "Is this in stock?"}}]}]}
    stranger = {"object": "page", "entry": [{"id": "page-nobody", "changes": [{"field": "feed", "value": {}}]}]}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            body, headers = signed(delivery)
            ok = await client.post("/webhook/provider/meta", content=body, headers=headers)
            assert ok.json() == {"status": "ok", "delivered": 1, "unrouted": 0}, ok.text
            again = await client.post("/webhook/provider/meta", content=body, headers=headers)  # a retry
            assert again.json()["delivered"] == 1
            body, headers = signed(stranger)
            assert (await client.post("/webhook/provider/meta", content=body, headers=headers)).json()["unrouted"] == 1
            body, headers = signed(delivery, secret=b"wrong")
            assert (await client.post("/webhook/provider/meta", content=body, headers=headers)).status_code == 401
        async with tenant_session(world.acme.company_id) as db:
            [event] = (await db.execute(select(Event).where(Event.company_id == world.acme.company_id,
                                                            Event.type == "social.comment.created"))).scalars().all()
            assert event.subject == f"connection:{connection_id}" and event.trust == "verified"
            assert event.data["value"]["message"] == "Is this in stock?"
        async with control_session() as db:
            assert (await db.execute(select(UnroutedEvent).where(
                UnroutedEvent.external_account_id == "page-nobody"))).scalars().first() is not None
            await db.execute(delete(UnroutedEvent).where(UnroutedEvent.external_account_id == "page-nobody"))
            await db.commit()
    finally:
        set_app(None, "oauth-app-meta")


async def test_secrets_are_sealed_per_row_rotated_and_shredded(world):
    from src.common.tenancy.session import tenant_session
    from src.connections import crypto
    from src.connections.models import Connection, ConnectionSecret, TenantKey

    company = world.acme.company_id
    first, second = uuid.uuid4(), uuid.uuid4()
    async with tenant_session(company) as db:
        for connection_id in (first, second):
            db.add(Connection(id=connection_id, company_id=company, connector_id="api_key", display_name="k",
                              status="active"))
        await db.flush()
        version, nonce, ciphertext = await crypto.seal_secret(db, company, first, {"api_key": "s3cret"})
        db.add(ConnectionSecret(connection_id=first, dek_version=version, nonce=nonce, ciphertext=ciphertext))
        await db.commit()
        assert await crypto.open_secret(db, company, first, version, nonce, ciphertext) == {"api_key": "s3cret"}
        with pytest.raises(crypto.SecretUnreadable):          # moved to another row, it does not open
            await crypto.open_secret(db, company, second, version, nonce, ciphertext)

        rotated = await crypto.rotate_dek(db, company)
        await db.commit()
        assert rotated == {"version": 2, "resealed": 1}
        row = await db.get(ConnectionSecret, first)
        assert row.dek_version == 2
        assert await crypto.open_secret(db, company, first, 2, row.nonce, row.ciphertext) == {"api_key": "s3cret"}
        assert (await db.get(TenantKey, (company, 1))).retired_at is not None

        await crypto.shred(company)
        with pytest.raises(crypto.SecretUnreadable):
            await crypto.open_secret(db, company, first, 2, row.nonce, row.ciphertext)


async def test_a_registry_secret_is_read_from_the_vault_by_name(monkeypatch):
    from src.common.platform.secrets import set_secrets
    from src.common.platform.secrets.env import EnvSecrets
    from src.config.registry_secrets import registry_secret
    from src.common.security import encrypt_api_key

    set_secrets(EnvSecrets())
    monkeypatch.setenv("TWILIO_AUTH_TOKEN_TEST", "from-the-vault")
    try:
        assert await registry_secret(SimpleNamespace(secret_ref="twilio-auth-token-test",
                                                     encrypted_api_key=encrypt_api_key("stored"))) == "from-the-vault"
        assert await registry_secret(SimpleNamespace(secret_ref=None,
                                                     encrypted_api_key=encrypt_api_key("stored"))) == "stored"
        assert await registry_secret(SimpleNamespace(secret_ref=None, encrypted_api_key=None)) is None
    finally:
        set_secrets(None)


async def test_platform_secrets_move_into_the_vault_and_keep_working(world, monkeypatch):
    """5.7: a platform integration's key is written to the vault, read back,
    and the row then names it instead of holding it."""
    import os

    from src.auth.platform import platform_company_id
    from src.common.platform.secrets import set_secrets
    from src.common.platform.secrets.env import EnvSecrets, env_name
    from src.common.security import encrypt_api_key
    from src.common.tenancy.session import control_session
    from src.config.models import IntegrationRegistry
    from src.config.move_secrets import move_secrets, vault_name
    from src.config.registry_secrets import registry_secret

    class Vault:
        async def set(self, name, value):
            monkeypatch.setenv(env_name(name), value)

    sku = f"test-move-{uuid.uuid4().hex[:8]}"
    set_secrets(EnvSecrets())
    try:
        async with control_session() as db:
            platform = await platform_company_id(db)
            row = IntegrationRegistry(company_id=platform, provider_name="serpapi", service_sku=sku,
                                      service_category="API_TOOL", component_type="flat_fee", internal_cost=0,
                                      cost_unit="per 1", encrypted_api_key=encrypt_api_key("serp-key"))
            db.add(row)
            await db.commit()
            dry = await move_secrets(db, Vault(), apply=False)
            assert {"service_sku": sku, "secret_ref": vault_name(sku)} in dry["would_move"]
            assert os.environ.get(env_name(vault_name(sku))) is None          # nothing written on a dry run
            done = await move_secrets(db, Vault(), apply=True)
            assert {"service_sku": sku, "secret_ref": vault_name(sku)} in done["moved"] and not done["failed"]
            await db.refresh(row)
            assert (row.secret_ref, row.encrypted_api_key) == (vault_name(sku), None)
            assert await registry_secret(row) == "serp-key"
    finally:
        set_secrets(None)
        async with control_session() as db:
            await db.execute(delete(IntegrationRegistry).where(IntegrationRegistry.service_sku == sku))
            await db.commit()


class _Inbox:
    """An IMAP server's INBOX, played: UIDs and raw messages."""

    def __init__(self, uid_validity=7):
        self.messages, self.uid_validity, self.logins = {}, uid_validity, 0
        self.untagged_responses = {}

    def add(self, uid, subject):
        self.messages[uid] = (f"Message-ID: <{uid}@acme.test>\r\nFrom: lead@cust.test\r\nTo: ops@acme.test\r\n"
                              f"Subject: {subject}\r\n\r\nPlease call me back.\r\n").encode()

    def select(self, folder, readonly=False):
        self.untagged_responses = {"UIDVALIDITY": [str(self.uid_validity).encode()]}
        return "OK", [b"1"]

    def uid(self, command, *args):
        if command == "SEARCH":
            return "OK", [b" ".join(str(u).encode() for u in sorted(self.messages))]
        uid = int(args[0])
        return "OK", [(b"1 (BODY[] {1}", self.messages[uid])]

    def logout(self):
        pass


async def test_the_mailbox_poller_turns_new_mail_into_events(world, monkeypatch):
    """WS3 3.13: polled only while a trigger listens; the first poll marks where
    the inbox stands; then each new message is one email.received event."""
    from src.ai.orm.entity import HierarchicalEntity
    from src.automation import pollers
    from src.automation.models import Event, Trigger
    from src.automation.pollers.mailbox import MailboxPoller
    from src.common.tenancy.session import tenant_session
    from src.connections import service
    from src.connections.models import Connection
    from src.connections.providers import PROVIDERS

    async def _ok(app, connector, settings, secret):
        return {"ok": True, "detail": "ok"}

    inbox = _Inbox()
    inbox.add(1, "Old mail")
    seen_logins = []

    def _login(self, credential):
        seen_logins.append((credential.extra.get("email_address"), credential.extra.get("password")))
        return inbox

    monkeypatch.setattr(PROVIDERS["mailbox"], "test", _ok)
    monkeypatch.setattr(MailboxPoller, "_login", _login)
    company = world.acme.company_id
    made = await service.create_from_form(company, world.acme.id, "imap_mailbox",
                                          {"email_address": "ops@acme.test", "password": "app-pass"})
    connection_id = uuid.UUID(made["id"])

    await pollers.poll_scope(None)                                       # no trigger listens: not polled
    assert seen_logins == []
    async with tenant_session(company) as db:
        assert "poll" not in ((await db.get(Connection, connection_id)).settings or {})   # nobody listens yet
        agent = HierarchicalEntity(company_id=company, type="AGENT", status="ACTIVE", name="Mail agent")
        db.add(agent)
        await db.flush()
        db.add(Trigger(company_id=company, name="New mail", kind="event", entity_id=agent.id,
                       event_type="email.received", created_by_kind="user"))
        await db.commit()

    await pollers.poll_scope(None)                                       # first poll: where it stands
    async with tenant_session(company) as db:
        cursor = (await db.get(Connection, connection_id)).settings["poll"]
        assert (cursor["uid_validity"], cursor["last_uid"]) == (7, 1)
        assert not (await db.execute(select(Event).where(Event.company_id == company,
                                                         Event.type == "email.received"))).first()
    inbox.add(2, "Quote please")
    inbox.add(3, "Call me")
    await pollers.poll_scope(None)
    await pollers.poll_scope(None)                                       # nothing new: nothing twice
    async with tenant_session(company) as db:
        events = (await db.execute(select(Event).where(Event.company_id == company, Event.type == "email.received")
                                   .order_by(Event.received_at))).scalars().all()
        assert [e.data["subject"] for e in events] == ["Quote please", "Call me"]
        assert events[0].subject == f"connection:{connection_id}" and events[0].data["mailbox"] == "ops@acme.test"
        assert (await db.get(Connection, connection_id)).settings["poll"]["last_uid"] == 3
    assert ("ops@acme.test", "app-pass") in seen_logins


async def test_old_credentials_become_connections_once(world):
    """WS7 7.2: a business's social, e-mail and own registry keys become sealed
    connections with routes; one that relied on its own developer app needs a
    reconnect; the registry row goes; running it again changes nothing."""
    from src.ai.email_models import EmailConnection
    from src.ai.social_connection_service import seal_oauth_metadata
    from src.ai.social_models import SocialConnection
    from src.common.security import encrypt_api_key
    from src.common.tenancy.session import control_session, tenant_session
    from src.config.models import IntegrationRegistry
    from src.config.service import ConfigService
    from src.connections import service
    from src.connections.migrate import convert_company
    from src.connections.models import Connection, ExternalAccountRoute

    company = world.acme.company_id
    page = f"page-{uuid.uuid4().hex[:8]}"
    async with tenant_session(company) as db:
        db.add_all([
            SocialConnection(company_id=company, platform="facebook", account_name="Acme Store",
                             encrypted_access_token=encrypt_api_key("page-token"), platform_page_id=page,
                             scopes=["pages_manage_posts"]),
            SocialConnection(company_id=company, platform="linkedin", account_name="Acme Pvt Ltd",
                             encrypted_access_token=encrypt_api_key("li-token"),
                             encrypted_refresh_token=encrypt_api_key("li-refresh"),
                             platform_user_id="urn:li:organization:9",
                             oauth_metadata=seal_oauth_metadata({"client_id": "their-app",
                                                                 "client_secret": "their-secret"})),
            SocialConnection(company_id=company, platform="tiktok", account_name="acme",
                             encrypted_access_token=encrypt_api_key("tt")),
            EmailConnection(company_id=company, email_address="sales@acme.test",
                            encrypted_app_password=encrypt_api_key("mail-pass")),
        ])
        await db.commit()
    async with control_session() as db:
        db.add(IntegrationRegistry(company_id=company, provider_name="serpapi", service_sku=f"serp-{company.hex[:6]}",
                                   service_category="API_TOOL", component_type="flat_fee", internal_cost=0,
                                   cost_unit="per 1", encrypted_api_key=encrypt_api_key("their-serp-key")))
        await db.commit()

    dry = await convert_company(company, apply=False)
    assert len(dry["converted"]) == 4 and [k["platform"] for k in dry["kept"]] == ["tiktok"]
    async with tenant_session(company) as db:
        assert not (await db.execute(select(Connection).where(Connection.company_id == company))).first()

    done = await convert_company(company, apply=True, remove_registry_rows=True)
    assert len(done["converted"]) == 4 and not done["failed"] and done["registry_removed"] == 1
    assert [n["platform"] for n in done["needs_reconnect"]] == ["linkedin"]
    async with tenant_session(company) as db:
        rows = {c.connector_id: c for c in (await db.execute(select(Connection).where(
            Connection.company_id == company))).scalars().all()}
    assert set(rows) == {"facebook_pages", "linkedin_org", "imap_mailbox", "provider_api_key"}
    assert rows["facebook_pages"].status == "active" and rows["linkedin_org"].status == "needs_reconnect"
    assert "client_secret" not in json.dumps(rows["linkedin_org"].settings)
    async with control_session() as db:
        route = await db.get(ExternalAccountRoute, ("meta", page))
        assert route.company_id == company and route.connection_id == rows["facebook_pages"].id
        assert not (await db.execute(select(IntegrationRegistry).where(
            IntegrationRegistry.company_id == company))).first()
        # The business's own key is still the one its tools use.
        assert await ConfigService(db).get_api_key_by_provider(company, "serpapi") == "their-serp-key"

    agent = uuid.uuid4()
    page_token = await service.issue_token(company, rows["facebook_pages"].id, principal_kind="entity",
                                           principal_id=agent)
    assert page_token.access_token == "page-token"
    again = await convert_company(company, apply=True)
    assert again["converted"] == [] and len(again["skipped"]) == 3       # the registry row is gone already
