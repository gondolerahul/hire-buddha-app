"""GW-03: a webhook delivery runs once, however often the provider retries it.

Before, every POST built a fresh correlation id and queued a fresh job: a
provider's retry ran the event — and charged for it — a second time, and one
captured body could be replayed at will.
"""
from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest

from src.gateway import envelope as envelope_module
from src.gateway import webhook_inbound
from src.gateway.webhook_inbound import delivery_id
from src.main import app
from tests.unit.webhook_endpoint_double import SECRET, bind_endpoint, signed_json


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


async def test_a_retried_delivery_is_acknowledged_and_not_run_again(queued, monkeypatch):
    endpoint = bind_endpoint(monkeypatch, source="generic")
    body, headers = signed_json({"type": "lead.created", "id": 7})
    first = await _post(f"/webhook/inbound/{endpoint.id}", content=body, headers=headers)
    again = await _post(f"/webhook/inbound/{endpoint.id}", content=body, headers=headers)
    assert first.status_code == 202
    assert again.status_code == 200
    assert again.json()["status"] == "duplicate"
    assert len(queued) == 1


async def test_the_providers_delivery_id_decides(queued, monkeypatch):
    endpoint = bind_endpoint(monkeypatch, source="github")
    body = json.dumps({"action": "opened"}).encode()
    sig = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()

    async def deliver(delivery: str) -> httpx.Response:
        return await _post(f"/webhook/inbound/{endpoint.id}", content=body, headers={
            "X-Hub-Signature-256": sig, "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": delivery, "Content-Type": "application/json"})

    assert (await deliver("d-1")).status_code == 202
    assert (await deliver("d-1")).status_code == 200          # GitHub's redelivery
    assert (await deliver("d-2")).status_code == 202          # a new event with the same body
    assert len(queued) == 2


async def test_a_delivery_that_was_not_queued_runs_on_retry(monkeypatch):
    endpoint = bind_endpoint(monkeypatch, source="generic")
    body, headers = signed_json({"type": "x"})

    async def redis_down(function, *args, **kwargs):
        raise ConnectionError("Redis is unreachable")

    monkeypatch.setattr(envelope_module, "enqueue_job", redis_down)
    assert (await _post(f"/webhook/inbound/{endpoint.id}", content=body, headers=headers)).status_code == 503

    calls = []

    async def ok(function, *args, **kwargs):
        calls.append(args[0])
        return object()

    monkeypatch.setattr(envelope_module, "enqueue_job", ok)
    assert (await _post(f"/webhook/inbound/{endpoint.id}", content=body, headers=headers)).status_code == 202
    assert len(calls) == 1


async def test_no_duplicate_check_means_no_run(queued, monkeypatch):
    endpoint = bind_endpoint(monkeypatch, source="generic")

    class Down:
        async def set(self, *args, **kwargs):
            raise ConnectionError("Redis is unreachable")

    monkeypatch.setattr(webhook_inbound, "shared_redis", lambda: Down())
    body, headers = signed_json({"type": "x"})
    resp = await _post(f"/webhook/inbound/{endpoint.id}", content=body, headers=headers)
    assert resp.status_code == 503
    assert queued == []


async def test_a_bad_signature_does_not_use_up_the_delivery(queued, monkeypatch):
    endpoint = bind_endpoint(monkeypatch, source="generic")
    body, headers = signed_json({"type": "x"})
    forged = {**headers, "X-HB-Signature": "sha256=" + "0" * 64}
    assert (await _post(f"/webhook/inbound/{endpoint.id}", content=body, headers=forged)).status_code == 401
    assert (await _post(f"/webhook/inbound/{endpoint.id}", content=body, headers=headers)).status_code == 202
    assert len(queued) == 1


def test_delivery_id_prefers_the_providers_header() -> None:
    body = b'{"a": 1}'
    assert delivery_id("github", {"x-github-delivery": "g1"}, body) == "id:g1"
    assert delivery_id("twilio", {"i-twilio-idempotency-token": "t1"}, body) == "id:t1"
    assert delivery_id("generic", {"x-hb-delivery": "r1"}, body) == "id:r1"
    assert delivery_id("generic", {}, body) == "body:" + hashlib.sha256(body).hexdigest()
    # Another provider's header name does not count for this source.
    assert delivery_id("crm", {"x-github-delivery": "g1"}, body).startswith("body:")
