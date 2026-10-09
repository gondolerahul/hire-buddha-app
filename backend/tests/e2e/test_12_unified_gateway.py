"""
E2E Tests: the webhook, internal-event and streaming interfaces.

These were the Unified Gateway's (:8001); the gateway is merged into the API,
so they are exercised on the API app (port 8000) through the ASGI transport
(no actual port binding required).

Run:
    cd backend
    python -m pytest tests/e2e/test_12_unified_gateway.py -v
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import pytest
import pytest_asyncio
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.main import app
from src.gateway import envelope as envelope_module
from src.gateway.envelope import EventEnvelope
from src.common.config import settings
from src.common import router_mounts
from tests.unit.webhook_endpoint_double import SECRET, bind_endpoint, signed_json

TEST_INTERNAL_TOKEN = "e2e-internal-token"


# ---------------------------------------------------------------------------
# Test client fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="module")
async def gateway_client():
    """Async HTTP client bound to the API app.

    Events are queued on arq before the endpoint answers; the enqueue is
    replaced so these tests put nothing on the real queue.
    """
    queued = []

    async def fake_enqueue(function, *args, **kwargs):
        queued.append((function, args, kwargs))
        return MagicMock(job_id="e2e")

    with patch.object(envelope_module, "enqueue_job", fake_enqueue),          patch.object(settings, "INTERNAL_TOKEN", TEST_INTERNAL_TOKEN), \
         patch.object(router_mounts, "worker_status", AsyncMock(return_value={"status": "ok", "queues": {}})):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as c:
            yield c


# ===========================================================================
# Health Endpoints
# ===========================================================================

@pytest.mark.asyncio
async def test_gateway_health(gateway_client):
    """GET /health answers like GET /api/v1/health."""
    resp = await gateway_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["unmounted_routers"] == []


@pytest.mark.asyncio
async def test_gateway_metrics(gateway_client):
    """GET /metrics/gateway returns the active video sessions."""
    resp = await gateway_client.get("/metrics/gateway")
    assert resp.status_code == 200
    data = resp.json()
    assert "active_video_sessions" in data


# ===========================================================================
# Interface 2: Unified Webhook Endpoint
# ===========================================================================

# A webhook arrives at a registered endpoint and is signed (GW-01);
# ``bind_endpoint`` stands an endpoint in without a database.


@pytest.mark.asyncio
async def test_webhook_inbound_returns_202(gateway_client, monkeypatch):
    """A signed POST to an endpoint returns 202 Accepted."""
    endpoint = bind_endpoint(monkeypatch, source="email")
    body, headers = signed_json({"from": "test@example.com", "subject": "Hello", "body": "Test email"})
    resp = await gateway_client.post(f"/webhook/inbound/{endpoint.id}", content=body, headers=headers)
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "accepted"
    assert "correlation_id" in data


@pytest.mark.asyncio
async def test_the_endpoints_source_picks_the_normaliser(gateway_client, monkeypatch):
    """An email endpoint normalises as email whatever headers the request carries."""
    endpoint = bind_endpoint(monkeypatch, source="email")
    body, headers = signed_json({"from": "sender@mailgun.com", "subject": "Test", "body-plain": "Hello"})
    headers["X-Li-Signature"] = "would-have-picked-linkedin"
    resp = await gateway_client.post(f"/webhook/inbound/{endpoint.id}", content=body, headers=headers)
    assert resp.status_code == 202
    data = resp.json()
    assert data["source"] == "email"
    assert data["event_type"] == "new_email"


@pytest.mark.asyncio
async def test_webhook_linkedin_native_signature(gateway_client, monkeypatch):
    """LinkedIn's own X-LI-Signature is accepted for a LinkedIn endpoint."""
    endpoint = bind_endpoint(monkeypatch, source="linkedin")
    body = json.dumps({"type": "linkedin.connection_request", "actor": "urn:li:person:abc"}).encode()
    sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    resp = await gateway_client.post(f"/webhook/inbound/{endpoint.id}", content=body,
                                     headers={"X-LI-Signature": sig, "Content-Type": "application/json"})
    assert resp.status_code == 202
    assert resp.json()["source"] == "linkedin"


@pytest.mark.asyncio
async def test_webhook_generic_source(gateway_client, monkeypatch):
    """A generic endpoint takes its event type from the query string."""
    endpoint = bind_endpoint(monkeypatch, source="generic")
    body, headers = signed_json({"record_id": "123", "type": "record_created"})
    resp = await gateway_client.post(
        f"/webhook/inbound/{endpoint.id}?source=custom_app&event_type=record_created",
        content=body, headers=headers)
    assert resp.status_code == 202
    data = resp.json()
    assert data["source"] == "generic"
    assert data["event_type"] == "record_created"


@pytest.mark.asyncio
async def test_webhook_twilio_form_post(gateway_client, monkeypatch):
    """A form-encoded Twilio callback with Twilio's own signature is accepted."""
    endpoint = bind_endpoint(monkeypatch, source="twilio")
    form = {"EventType": "status_update", "CallSid": "CA123"}
    url = f"http://test/webhook/inbound/{endpoint.id}"
    data = (url + "".join(k + form[k] for k in sorted(form))).encode()
    sig = base64.b64encode(hmac.new(SECRET.encode(), data, hashlib.sha1).digest()).decode()
    resp = await gateway_client.post(
        f"/webhook/inbound/{endpoint.id}", data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded", "X-Twilio-Signature": sig},
    )
    assert resp.status_code == 202
    assert resp.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_an_unsigned_webhook_is_refused(gateway_client, monkeypatch):
    """The header a provider would send, without a valid value, is a 401."""
    endpoint = bind_endpoint(monkeypatch, source="twilio")
    resp = await gateway_client.post(
        f"/webhook/inbound/{endpoint.id}", data={"EventType": "status_update"},
        headers={"X-Twilio-Signature": "twilio_sig"},
    )
    assert resp.status_code == 401


# ===========================================================================
# Interface 3: Internal Event Endpoint
# ===========================================================================

@pytest.mark.asyncio
async def test_internal_event_returns_202(gateway_client):
    """POST /internal/event with valid token returns 202."""
    resp = await gateway_client.post(
        "/internal/event",
        json={
            "event_type": "doc_indexed",
            "client_id": "company-uuid-123",
            "source": "vector_db",
            "payload": {"document_id": "doc-456", "chunk_count": 42},
        },
        headers={"X-Internal-Token": TEST_INTERNAL_TOKEN},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["event_type"] == "doc_indexed"
    assert "correlation_id" in data


@pytest.mark.asyncio
async def test_internal_event_rejects_missing_token(gateway_client):
    """POST /internal/event without token returns 401."""
    resp = await gateway_client.post(
        "/internal/event",
        json={
            "event_type": "doc_indexed",
            "client_id": "company-uuid-123",
            "source": "vector_db",
            "payload": {},
        },
        # No X-Internal-Token header
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_internal_event_rejects_wrong_token(gateway_client):
    """POST /internal/event with wrong token returns 401."""
    resp = await gateway_client.post(
        "/internal/event",
        json={
            "event_type": "timer.daily_summary",
            "client_id": "company-uuid-123",
            "source": "cron",
            "payload": {},
        },
        headers={"X-Internal-Token": "wrong-token-abc"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_internal_event_schema_validation(gateway_client):
    """POST /internal/event without its event_type returns 422."""
    resp = await gateway_client.post(
        "/internal/event",
        json={
            "client_id": "company-uuid-123",
            "source": "vector_db",
            "payload": {},
        },
        headers={"X-Internal-Token": TEST_INTERNAL_TOKEN},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_internal_event_custom_correlation_id(gateway_client):
    """POST /internal/event with pre-set correlation_id echoes it back."""
    my_corr_id = "my-custom-correlation-id-001"
    resp = await gateway_client.post(
        "/internal/event",
        json={
            "event_type": "agent.signal",
            "client_id": "company-uuid-456",
            "source": "agent:agent-001",
            "payload": {"signal": "complete"},
            "correlation_id": my_corr_id,
        },
        headers={"X-Internal-Token": TEST_INTERNAL_TOKEN},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["correlation_id"] == my_corr_id


# ===========================================================================
# Envelope
# ===========================================================================

@pytest.mark.asyncio
async def test_event_envelope_serialization():
    """EventEnvelope serializes/deserializes correctly."""
    env = EventEnvelope(
        channel="internal",
        source="cron",
        client_id="company-abc",
        event_type="timer.daily_summary",
        raw_data={"count": 42},
        metadata={"priority": 3},
    )
    d = env.to_dict()
    assert d["channel"] == "internal"
    assert d["event_type"] == "timer.daily_summary"
    assert d["raw_data"]["count"] == 42

    restored = EventEnvelope.from_dict(d)
    assert restored.client_id == env.client_id
    assert restored.id == env.id


@pytest.mark.asyncio
async def test_the_unbound_webhook_route_is_refused(gateway_client):
    """No endpoint, no signature: 401, whatever ``client_id`` says (GW-01)."""
    resp = await gateway_client.post("/webhook/inbound?client_id=company-abc", json={"type": "x"})
    assert resp.status_code == 401


# ===========================================================================
# Webhook Strategy Unit Tests
# ===========================================================================

def test_every_source_has_a_normaliser():
    """The endpoint's source picks the normaliser; no header is consulted (GW-01)."""
    from src.gateway.models import WEBHOOK_SOURCES
    from src.gateway.webhook_inbound import STRATEGIES

    assert set(STRATEGIES) == set(WEBHOOK_SOURCES)
