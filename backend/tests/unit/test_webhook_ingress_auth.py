"""GW-01 / API-03: a webhook creates work only at its endpoint, and only signed.

Before, ``POST /webhook/inbound`` took the tenant from ``?client_id=``, picked the
signature scheme from the request's own headers, ran checks that all returned
True, and processed the event even when one returned False. Anyone who could
reach the URL could run any tenant's agents on that tenant's credit.
"""
from __future__ import annotations

import uuid

import httpx
import pytest

from src.gateway import envelope as envelope_module
from src.main import app
from tests.unit.webhook_endpoint_double import bind_endpoint, relay_headers, signed_json


@pytest.fixture
def queued(monkeypatch):
    calls = []

    async def fake_enqueue(function, *args, **kwargs):
        calls.append(args[0])
        return object()

    monkeypatch.setattr(envelope_module, "enqueue_job", fake_enqueue)
    return calls


async def _post(path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, **kwargs)


async def test_the_unbound_route_refuses_everything(queued):
    resp = await _post("/webhook/inbound?client_id=" + str(uuid.uuid4()),
                       json={"crm_event": "lead.created"}, headers={"X-HubSpot-Signature": "x"})
    assert resp.status_code == 401
    assert "/webhook/inbound/{endpoint_id}" in resp.json()["detail"]
    assert queued == []


async def test_an_unknown_endpoint_is_404(queued, monkeypatch):
    bind_endpoint(monkeypatch)
    body, headers = signed_json({"type": "x"})
    for path in (f"/webhook/inbound/{uuid.uuid4()}", "/webhook/inbound/not-a-uuid"):
        resp = await _post(path, content=body, headers=headers)
        assert resp.status_code == 404
    assert queued == []


async def test_an_unsigned_webhook_is_refused(queued, monkeypatch):
    endpoint = bind_endpoint(monkeypatch, source="crm")
    resp = await _post(f"/webhook/inbound/{endpoint.id}", json={"crm_event": "lead.created"})
    assert resp.status_code == 401
    assert queued == []


async def test_a_wrong_secret_is_refused(queued, monkeypatch):
    endpoint = bind_endpoint(monkeypatch, source="generic")
    body, headers = signed_json({"type": "x"}, secret="someone-elses-secret-000000")
    resp = await _post(f"/webhook/inbound/{endpoint.id}", content=body, headers=headers)
    assert resp.status_code == 401
    assert queued == []


async def test_a_tampered_body_is_refused(queued, monkeypatch):
    endpoint = bind_endpoint(monkeypatch, source="generic")
    _, headers = signed_json({"type": "x", "amount": 1})
    resp = await _post(f"/webhook/inbound/{endpoint.id}",
                       content=b'{"type": "x", "amount": 1000}', headers=headers)
    assert resp.status_code == 401
    assert queued == []


async def test_a_header_cannot_choose_a_weaker_scheme(queued, monkeypatch):
    # A GitHub endpoint checks GitHub's signature (or the relay's). Sending
    # another provider's headers, or none, does not fall through to a scheme
    # that lets the request in.
    endpoint = bind_endpoint(monkeypatch, source="github")
    resp = await _post(f"/webhook/inbound/{endpoint.id}", json={"object": "page"},
                       headers={"X-Mailgun-Signature": "x", "X-Twilio-Signature": "x"})
    assert resp.status_code == 401
    assert queued == []


async def test_a_signed_webhook_runs_for_the_endpoints_company(queued, monkeypatch):
    company, agent = uuid.uuid4(), uuid.uuid4()
    endpoint = bind_endpoint(monkeypatch, source="crm", company_id=company, entity_id=agent)
    body, headers = signed_json({"crm_event": "lead.created"})
    # A client_id in the query string names nothing any more.
    resp = await _post(f"/webhook/inbound/{endpoint.id}?client_id={uuid.uuid4()}",
                       content=body, headers=headers)
    assert resp.status_code == 202, resp.text
    [envelope] = queued
    assert envelope["client_id"] == str(company)
    assert envelope["source"] == "crm"
    assert envelope["event_type"] == "lead.created"
    assert envelope["metadata"]["endpoint_id"] == str(endpoint.id)
    assert envelope["metadata"]["entity_id"] == str(agent)


async def test_github_native_signature_is_accepted(queued, monkeypatch):
    import hashlib
    import hmac
    import json

    from tests.unit.webhook_endpoint_double import SECRET

    endpoint = bind_endpoint(monkeypatch, source="github")
    body = json.dumps({"action": "opened", "repository": {"full_name": "o/r"}}).encode()
    sig = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    resp = await _post(f"/webhook/inbound/{endpoint.id}", content=body,
                       headers={"X-Hub-Signature-256": sig, "X-GitHub-Event": "pull_request",
                                "Content-Type": "application/json"})
    assert resp.status_code == 202, resp.text
    assert queued[0]["event_type"] == "github.pull_request"


async def test_a_signed_form_post_is_accepted(queued, monkeypatch):
    endpoint = bind_endpoint(monkeypatch, source="generic")
    body = b"EventType=status_update&CallSid=CA1"
    headers = relay_headers(body)
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    resp = await _post(f"/webhook/inbound/{endpoint.id}", content=body, headers=headers)
    assert resp.status_code == 202, resp.text
    assert queued[0]["raw_data"]["raw"] == {"EventType": "status_update", "CallSid": "CA1"}


@pytest.fixture(autouse=True)
def _direct_queue_path(monkeypatch):
    """These check the direct queue path (AUTOMATION_GATEWAY_EVENTS off, the rollback
    setting); the event path is tests/integration/test_automation_gateway.py."""
    monkeypatch.setattr("src.common.config.settings.AUTOMATION_GATEWAY_EVENTS", False)
