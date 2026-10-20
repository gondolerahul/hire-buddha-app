"""Connections without a database (Phase 14 WS5): the local KEK, the catalog,
the provider adapters against a played provider, Meta deliveries, the client.

The flows through the API, the sealed secrets in a database and the provider
webhooks end to end are in ``tests/integration/test_connections.py``.
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

from src.connections.apps import ProviderApp
from src.connections.providers import base as provider_base


# ── KEK ─────────────────────────────────────────────────────────────────────

async def test_a_local_kek_wraps_and_a_destroyed_one_opens_nothing(tmp_path):
    from src.common.platform.kek import KeyDestroyed, tenant_kek_name
    from src.common.platform.kek.local import LocalKeyEncryption

    kek = LocalKeyEncryption(tmp_path)
    name = tenant_kek_name("abc0123456")
    dek = b"\x01" * 32
    wrapped, key_id = await kek.wrap(name, dek)
    assert wrapped != dek and await kek.unwrap(key_id, wrapped) == dek
    assert await kek.ensure_key(name) == key_id                       # the same key, not a new one
    other_wrapped, other_id = await kek.wrap(tenant_kek_name("xyz0123456"), dek)
    with pytest.raises(KeyDestroyed):                                  # another tenant's key does not open it
        await kek.unwrap(other_id, wrapped)
    await kek.destroy(name)
    with pytest.raises(KeyDestroyed):
        await kek.unwrap(key_id, wrapped)


def test_the_kek_adapter_follows_the_profile(monkeypatch):
    from src.common.config import settings
    from src.common.platform import adapter_name

    monkeypatch.setattr(settings, "PLATFORM_PROFILE", "local")
    monkeypatch.setattr(settings, "KEK_BACKEND", "")
    assert adapter_name("kek") == "local"
    monkeypatch.setattr(settings, "PLATFORM_PROFILE", "azure")
    assert adapter_name("kek") == "azure_keyvault"


# ── Catalog ─────────────────────────────────────────────────────────────────

def test_the_catalog_yaml_is_valid_and_oauth_connectors_name_their_app():
    from src.connections.catalog import load_specs

    specs = load_specs()
    assert {"facebook_pages", "instagram_business", "whatsapp_business", "linkedin_org", "github", "gmail",
            "imap_mailbox", "mcp_server"} <= set(specs)
    for item in specs.values():
        if item.auth_type in ("oauth2", "github_app", "meta_embedded_signup"):
            assert item.oauth_app_ref, item.id
    assert [f.name for f in specs["imap_mailbox"].form][:2] == ["email_address", "password"]
    # Every form parses (an unquoted label with a comma once split into a stray key and broke /connectors).
    for item in specs.values():
        assert all(f.name and f.label for f in item.form), item.id
    assert [f.label for f in specs["provider_api_key"].form if f.name == "provider"] == [
        "Provider (as in the registry, e.g. serpapi)"]


def test_a_catalog_file_whose_id_is_not_its_name_is_refused(tmp_path):
    from src.connections.catalog import load_specs

    (tmp_path / "wrong.yaml").write_text("id: other\nprovider: x\ndisplay_name: X\ncategory: social\n"
                                         "auth_type: api_key\nstatus: available\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be the file's name"):
        load_specs(tmp_path)


# ── Providers against a played provider ─────────────────────────────────────

class Played:
    """The provider: answers by URL, records each request."""

    def __init__(self, routes):
        self.routes, self.requests = routes, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for (method, prefix), answer in self.routes.items():
            if request.method == method and str(request.url).startswith(prefix):
                status, body = answer(request) if callable(answer) else answer
                return httpx.Response(status, json=body)
        return httpx.Response(404, json={"error": {"message": f"unplayed {request.method} {request.url}"}})


@pytest.fixture
def played():
    holder = {}

    def use(routes):
        holder["provider"] = Played(routes)
        provider_base.set_transport(httpx.MockTransport(holder["provider"]))
        return holder["provider"]

    yield use
    provider_base.set_transport(None)


def _connector(**kw):
    return SimpleNamespace(**{"id": "gmail", "auth_type": "oauth2", "scopes": ["openid", "email"],
                              "capabilities": {}, "display_name": "Gmail", **kw})


APP = ProviderApp(ref="oauth-app-google", client_id="cid", client_secret="csecret")


async def test_google_signs_in_with_pkce_and_refreshes(played):
    from src.connections.providers.oauth import GoogleProvider

    google = GoogleProvider()
    verifier, challenge = provider_base.pkce_pair()
    url = await google.authorize_url(APP, _connector(), state="s1", redirect_uri="https://connect.x/cb",
                                     code_challenge=challenge)
    query = parse_qs(urlparse(url).query)
    assert query["code_challenge_method"] == ["S256"] and query["access_type"] == ["offline"]
    assert query["state"] == ["s1"] and query["client_id"] == ["cid"]

    provider = played({
        ("POST", "https://oauth2.googleapis.com/token"): lambda r: (200, {
            "access_token": "at1" if b"authorization_code" in r.content else "at2",
            "refresh_token": "rt1", "expires_in": 3600, "scope": "openid email"}),
        ("GET", "https://openidconnect.googleapis.com/v1/userinfo"): (200, {"sub": "g-1", "email": "a@b.co"}),
    })
    [account] = await google.exchange(APP, _connector(), {"code": "c1", "state": "s1"},
                                      redirect_uri="https://connect.x/cb", code_verifier=verifier)
    assert (account.external_id, account.name) == ("g-1", "a@b.co")
    assert account.secret == {"access_token": "at1", "refresh_token": "rt1"}
    sent = parse_qs(provider.requests[0].content.decode())
    assert sent["code_verifier"] == [verifier] and sent["client_secret"] == ["csecret"]
    secret, expires = await google.refresh(APP, _connector(), {}, account.secret)
    assert secret == {"access_token": "at2", "refresh_token": "rt1"} and expires > datetime.utcnow()


async def test_a_provider_refusal_is_a_readable_error(played):
    from src.connections.providers import ProviderError
    from src.connections.providers.oauth import GoogleProvider

    played({("POST", "https://oauth2.googleapis.com/token"): (400, {"error": "invalid_grant",
                                                                    "error_description": "Bad code"})})
    with pytest.raises(ProviderError, match="code exchange failed \\(400\\): Bad code"):
        await GoogleProvider().exchange(APP, _connector(), {"code": "x"}, redirect_uri="r", code_verifier="v")


async def test_x_sends_client_credentials_in_a_basic_header(played):
    from src.connections.providers.oauth import XProvider

    provider = played({
        ("POST", "https://api.x.com/2/oauth2/token"): (200, {"access_token": "xt", "refresh_token": "xr"}),
        ("GET", "https://api.x.com/2/users/me"): (200, {"data": {"id": "42", "username": "acme"}}),
    })
    [account] = await XProvider().exchange(APP, _connector(id="x_account"), {"code": "c"}, redirect_uri="r",
                                           code_verifier="v")
    assert account.name == "@acme" and provider.requests[0].headers["authorization"].startswith("Basic ")
    assert "client_secret" not in provider.requests[0].content.decode()


async def test_meta_lists_pages_and_instagram_accounts(played):
    from src.connections.providers.meta import MetaProvider

    meta_app = ProviderApp(ref="oauth-app-meta", client_id="111", client_secret="appsecret")
    played({
        ("GET", "https://graph.facebook.com/v26.0/oauth/access_token"): lambda r: (200, {
            "access_token": "long" if "fb_exchange_token" in str(r.url) else "short"}),
        ("GET", "https://graph.facebook.com/v26.0/me/accounts"): (200, {"data": [
            {"id": "p1", "name": "Acme Store", "access_token": "pt1",
             "instagram_business_account": {"id": "ig1", "username": "acmestore"}},
            {"id": "p2", "name": "Acme Jobs", "access_token": "pt2"}]}),
    })
    pages = await MetaProvider().exchange(meta_app, _connector(id="facebook_pages"), {"code": "c"},
                                          redirect_uri="r", code_verifier=None)
    assert [(a.external_id, a.secret["access_token"]) for a in pages] == [("p1", "pt1"), ("p2", "pt2")]
    [instagram] = await MetaProvider().exchange(meta_app, _connector(id="instagram_business"), {"code": "c"},
                                                redirect_uri="r", code_verifier=None)
    assert (instagram.external_id, instagram.name, instagram.settings["page_id"]) == ("ig1", "@acmestore", "p1")


async def test_whatsapp_embedded_signup_lists_the_shared_numbers(played):
    from src.connections.providers.meta import MetaProvider

    meta_app = ProviderApp(ref="oauth-app-meta", client_id="111", client_secret="appsecret",
                           settings={"config_id": "cfg"})
    played({
        ("GET", "https://graph.facebook.com/v26.0/oauth/access_token"): (200, {"access_token": "biz"}),
        ("GET", "https://graph.facebook.com/v26.0/debug_token"): (200, {"data": {"granular_scopes": [
            {"scope": "whatsapp_business_management", "target_ids": ["waba1"]}]}}),
        ("GET", "https://graph.facebook.com/v26.0/waba1/phone_numbers"): (200, {"data": [
            {"id": "pn1", "display_phone_number": "+91 98000 00010", "verified_name": "Acme"}]}),
    })
    [number] = await MetaProvider().exchange(meta_app, _connector(id="whatsapp_business",
                                                                  auth_type="meta_embedded_signup"),
                                             {"code": "c"}, redirect_uri="r", code_verifier=None)
    assert number.external_id == "pn1" and number.settings == {
        "waba_id": "waba1", "phone_number_id": "pn1", "display_phone_number": "+91 98000 00010"}


def test_embedded_signup_carries_the_partner_solution():
    """With Tata as Solution Partner (Multi-Partner Solution), the solution id
    goes into extras.setup.solutionID; without one, setup stays empty."""
    from src.connections.providers.meta import embedded_signup_params

    tata = ProviderApp(ref="oauth-app-meta", client_id="111", client_secret="s",
                       settings={"config_id": "cfg", "solution_id": "795033096057724"})
    params = embedded_signup_params(tata, "st")
    assert params["extras"]["setup"] == {"solutionID": "795033096057724"}
    assert (params["app_id"], params["config_id"], params["graph_version"]) == ("111", "cfg", "v26.0")
    alone = ProviderApp(ref="oauth-app-meta", client_id="111", client_secret="s", settings={"config_id": "cfg"})
    assert embedded_signup_params(alone, "st")["extras"]["setup"] == {}


def test_register_app_builds_the_row_from_names_only():
    from src.connections.register_app import row_values

    row = row_values("meta", {"client_id": "111", "config_id": "cfg", "solution_id": "sol"},
                     {"verify_token": "oauth-meta-verify-token"}, "oauth-meta-app-secret")
    assert (row["service_sku"], row["service_category"], row["secret_ref"]) == (
        "oauth-app-meta", "OAUTH_APP", "oauth-meta-app-secret")
    assert row["service_metadata"] == {"client_id": "111", "config_id": "cfg", "solution_id": "sol",
                                       "verify_token_ref": "oauth-meta-verify-token"}
    with pytest.raises(ValueError, match="app_id"):
        row_values("github", {"client_id": "Iv1"}, {}, None)
    with pytest.raises(ValueError, match="private_key"):
        row_values("github", {"client_id": "Iv1", "app_id": "9", "app_slug": "hb"}, {}, None)
    with pytest.raises(ValueError, match="--ref"):
        row_values("x", {"client_id": "c", "secret_ref": "oops"}, {}, None)
    with pytest.raises(ValueError, match="letters, digits and hyphens"):
        row_values("x", {"client_id": "c"}, {}, "not a/vault name")


def _rsa_pem() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()


async def test_github_reads_the_installation_and_mints_cached_tokens(played):
    from jose import jwt

    from src.connections.providers import github

    pem = _rsa_pem()
    gh_app = ProviderApp(ref="oauth-app-github-test", client_id="Iv1", client_secret=None,
                         settings={"app_id": "777", "app_slug": "hirebuddha-dev"}, secrets={"private_key": pem})
    provider = played({
        ("GET", "https://api.github.com/app/installations/99"): (200, {
            "account": {"login": "acme", "type": "Organization"}, "permissions": {"contents": "write"},
            "repository_selection": "selected"}),
        ("POST", "https://api.github.com/app/installations/99/access_tokens"): (201, {
            "token": "ghs_x", "expires_at": (datetime.utcnow() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}),
    })
    url = await github.GitHubAppProvider().authorize_url(gh_app, None, state="st", redirect_uri="r",
                                                         code_challenge=None)
    assert url == "https://github.com/apps/hirebuddha-dev/installations/new?state=st"
    [account] = await github.GitHubAppProvider().exchange(gh_app, None, {"installation_id": "99"}, redirect_uri="r",
                                                          code_verifier=None)
    assert (account.external_id, account.name, account.secret) == ("99", "acme", {})
    claims = jwt.get_unverified_claims(provider.requests[0].headers["authorization"].split()[1])
    assert claims["iss"] == "777" and claims["exp"] - claims["iat"] == 540
    first = await github.GitHubAppProvider().access(gh_app, None, account.settings, {})
    again = await github.GitHubAppProvider().access(gh_app, None, account.settings, {})
    assert first.access_token == again.access_token == "ghs_x"
    assert sum(1 for r in provider.requests if r.url.path.endswith("access_tokens")) == 1


async def test_a_mailbox_form_seals_only_the_password():
    from src.connections.providers.forms import MailboxProvider

    account = await MailboxProvider().from_form(SimpleNamespace(id="imap_mailbox"), {
        "email_address": "Sales@Acme.co", "password": "app-pass", "imap_port": "993"})
    assert account.secret == {"password": "app-pass"}
    assert account.settings["email_address"] == "sales@acme.co" and account.settings["imap_port"] == 993
    assert "password" not in account.settings


# ── Meta deliveries ─────────────────────────────────────────────────────────

def test_meta_deliveries_name_their_account_and_type():
    from src.connections.webhooks import meta_deliveries

    page = meta_deliveries({"object": "page", "entry": [{"id": "p1", "time": 1, "changes": [
        {"field": "feed", "value": {"item": "comment", "message": "hi"}}],
        "messaging": [{"sender": {"id": "u"}, "message": {"text": "hello"}}]}]})
    assert [(a, t) for a, t, _ in page] == [("p1", "social.comment.created"), ("p1", "social.message.received")]
    assert page[0][2]["platform"] == "facebook"
    wa = meta_deliveries({"object": "whatsapp_business_account", "entry": [{"id": "waba1", "changes": [
        {"field": "messages", "value": {"metadata": {"phone_number_id": "pn1"}, "messages": [{"id": "m"}],
                                        "statuses": [{"id": "m0", "status": "read"}]}}]}]})
    assert [(a, t) for a, t, _ in wa] == [("pn1", "whatsapp.message.received"), ("pn1", "whatsapp.status.updated")]
    ig = meta_deliveries({"object": "instagram", "entry": [{"id": "ig1", "changes": [
        {"field": "comments", "value": {"text": "nice"}}, {"field": "mentions", "value": {}}]}]})
    assert [t for _, t, _ in ig] == ["social.comment.created", "social.mention.created"]
    assert meta_deliveries({"object": "user", "entry": []}) == []


def test_github_events_get_appendix_b_names():
    from src.connections.webhooks import github_event_type

    assert github_event_type("pull_request", {"action": "closed", "pull_request": {"merged": True}}) == \
        "github.pull_request.merged"
    assert github_event_type("pull_request", {"action": "closed", "pull_request": {"merged": False}}) == \
        "github.pull_request.closed"
    assert github_event_type("pull_request", {"action": "opened"}) == "github.pull_request.opened"
    assert github_event_type("issues", {"action": "opened"}) == "github.issue.opened"
    assert github_event_type("check_suite", {"action": "completed"}) == "github.check.completed"
    assert github_event_type("push", {}) == "github.push"


def test_a_meta_signature_is_checked_against_the_app_secret():
    from src.connections.webhooks import _signed

    body = json.dumps({"object": "page"}).encode()
    good = "sha256=" + hmac.new(b"appsecret", body, hashlib.sha256).hexdigest()
    assert _signed("appsecret", body, good)
    assert not _signed("appsecret", body, "sha256=" + "0" * 64)
    assert not _signed(None, body, good) and not _signed("appsecret", body, None)


# ── The tools' client ──────────────────────────────────────────────────────

async def test_without_an_agent_the_client_goes_straight_to_the_old_rows(monkeypatch):
    from src.connections import client, service

    async def _never(*a, **k):
        raise AssertionError("connections were looked up without an agent")

    async def _legacy(company_id, platform, account):
        return {"access_token": "old", "platform": platform}

    monkeypatch.setattr(service, "connections_for", _never)
    monkeypatch.setattr(client, "_legacy", _legacy)
    found = await client.credentials_for({"company_id": str(uuid.uuid4())}, "facebook")
    assert found == {"access_token": "old", "platform": "facebook"}


async def test_the_client_uses_the_agents_granted_connection(monkeypatch):
    from src.connections import client, service
    from src.connections.providers import AccessToken

    company, agent, run = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    asked = {}

    async def _for(company_id, connectors, **kw):
        asked["for"] = (company_id, list(connectors), kw)
        return [{"id": "c1", "connector_id": "facebook_pages", "external_account_id": "p1",
                 "external_account_name": "Acme Store", "settings": {"page_id": "p1"}, "scopes": ["x"]}]

    async def _issue(company_id, connection_id, **kw):
        asked["issue"] = kw
        return AccessToken(access_token="pt1", extra={"page_id": "p1"})

    monkeypatch.setattr(service, "connections_for", _for)
    monkeypatch.setattr(service, "issue_token", _issue)
    found = await client.credentials_for({"company_id": str(company), "entity_id": str(agent),
                                          "run_id": str(run)}, "facebook", action="post")
    assert found["access_token"] == "pt1" and found["platform_page_id"] == "p1" and found["source"] == "connections"
    assert asked["for"][1] == ["facebook_pages"]
    assert asked["issue"] == {"principal_kind": "entity", "principal_id": str(agent), "action": "post",
                              "run_id": str(run)}
