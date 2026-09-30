"""
E2E Tests: the webhook, internal-event and streaming interfaces.

These were the Unified Gateway's (:8001); the gateway is merged into the API,
so they are exercised on the API app (port 8000) through the ASGI transport
(no actual port binding required).

Run:
    cd backend
    python -m pytest tests/e2e/test_12_unified_gateway.py -v
"""
import json
import os
import sys
import pytest
import pytest_asyncio
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.main import app
from src.gateway.event_bus import EventEnvelope, get_event_bus, _bus
from src.common.config import settings


# ---------------------------------------------------------------------------
# Test client fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="module")
async def gateway_client():
    """Async HTTP client bound to the API app."""
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
    """GET /metrics/gateway returns event bus stats."""
    resp = await gateway_client.get("/metrics/gateway")
    assert resp.status_code == 200
    data = resp.json()
    assert "event_bus" in data
    assert "active_video_sessions" in data


# ===========================================================================
# Interface 2: Unified Webhook Endpoint
# ===========================================================================

@pytest.mark.asyncio
async def test_webhook_inbound_returns_202(gateway_client):
    """POST /webhook/inbound with JSON payload returns 202 Accepted."""
    resp = await gateway_client.post(
        "/webhook/inbound?client_id=test-company-123",
        json={"from": "test@example.com", "subject": "Hello", "body": "Test email"},
        headers={"X-Source": "email"},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "accepted"
    assert "correlation_id" in data


@pytest.mark.asyncio
async def test_webhook_detects_email_source(gateway_client):
    """Mailgun X-Mailgun-* header triggers EmailWebhookStrategy."""
    resp = await gateway_client.post(
        "/webhook/inbound?client_id=company-abc",
        json={"from": "sender@mailgun.com", "subject": "Test", "body-plain": "Hello"},
        headers={"X-Mailgun-Signature": "sig123"},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["source"] == "email"
    assert data["event_type"] == "new_email"


@pytest.mark.asyncio
async def test_webhook_detects_linkedin_source(gateway_client):
    """X-Li-Signature header triggers LinkedInWebhookStrategy."""
    resp = await gateway_client.post(
        "/webhook/inbound?client_id=company-abc",
        json={"type": "linkedin.connection_request", "actor": "urn:li:person:abc"},
        headers={"X-Li-Signature": "li_sig"},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["source"] == "linkedin"


@pytest.mark.asyncio
async def test_webhook_generic_fallback(gateway_client):
    """Unknown source falls through to GenericWebhookStrategy."""
    resp = await gateway_client.post(
        "/webhook/inbound?client_id=company-xyz&source=custom_app&event_type=record_created",
        json={"record_id": "123", "type": "record_created"},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["source"] == "generic"


@pytest.mark.asyncio
async def test_webhook_with_form_data(gateway_client):
    """POST /webhook/inbound with form-encoded body (Twilio-style) works."""
    resp = await gateway_client.post(
        "/webhook/inbound?client_id=twilio-client",
        data={"EventType": "status_update", "CallSid": "CA123"},
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Twilio-Signature": "twilio_sig",
        },
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "accepted"


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
        headers={"X-Internal-Token": settings.INTERNAL_TOKEN},
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
    """POST /internal/event with invalid priority returns 422."""
    resp = await gateway_client.post(
        "/internal/event",
        json={
            "event_type": "doc_indexed",
            "client_id": "company-uuid-123",
            "source": "vector_db",
            "payload": {},
            "priority": 99,  # Out of range (1-10)
        },
        headers={"X-Internal-Token": settings.INTERNAL_TOKEN},
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
        headers={"X-Internal-Token": settings.INTERNAL_TOKEN},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["correlation_id"] == my_corr_id


# ===========================================================================
# Event Bus Unit Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_event_bus_publish_and_subscribe():
    """In-memory event bus publishes and consumer receives events."""
    from src.gateway.event_bus import InMemoryEventBus

    bus = InMemoryEventBus(maxsize=10)
    received = []

    async def consumer():
        async with bus.subscribe() as sub:
            envelope = await sub._queue.get()
            received.append(envelope)

    import asyncio
    consumer_task = asyncio.create_task(consumer())

    await asyncio.sleep(0.01)  # let consumer register

    envelope = EventEnvelope(
        channel="webhook",
        source="email",
        client_id="company-123",
        event_type="new_email",
        raw_data={"from": "test@test.com"},
    )
    await bus.publish(envelope)
    await consumer_task

    assert len(received) == 1
    assert received[0].event_type == "new_email"
    assert received[0].client_id == "company-123"


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


# ===========================================================================
# Dispatcher Unit Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_dispatcher_rejects_envelope_without_client_id():
    """CentralDispatcher.dispatch() rejects envelopes with no client_id."""
    from src.gateway.dispatcher import CentralDispatcher

    dispatcher = CentralDispatcher()
    envelope = EventEnvelope(
        channel="webhook",
        source="email",
        client_id="",   # No client_id
        event_type="new_email",
        raw_data={},
    )
    result = await dispatcher.dispatch(envelope)
    assert result.accepted is False
    assert result.error == "no_client_id"


@pytest.mark.asyncio
async def test_dispatcher_accepts_streaming_channels():
    """CentralDispatcher marks audio/video as streaming mode (no DB needed)."""
    from src.gateway.dispatcher import CentralDispatcher

    dispatcher = CentralDispatcher()
    envelope = EventEnvelope(
        channel="audio",
        source="twilio",
        client_id="company-uuid-123",
        event_type="call_started",
        raw_data={},
    )
    result = await dispatcher.dispatch(envelope)
    assert result.accepted is True
    assert result.mode == "streaming"


# ===========================================================================
# Webhook Strategy Unit Tests
# ===========================================================================

def test_webhook_strategy_detection():
    """Strategy detection selects correct handler for known providers."""
    from src.gateway.webhook_inbound import (
        detect_strategy, EmailWebhookStrategy, LinkedInWebhookStrategy,
        GitHubWebhookStrategy, CRMWebhookStrategy, GenericWebhookStrategy,
    )

    # Email
    s = detect_strategy({"X-Mailgun-Signature": "sig"}, {})
    assert isinstance(s, EmailWebhookStrategy)

    # LinkedIn
    s = detect_strategy({"X-Li-Signature": "sig"}, {})
    assert isinstance(s, LinkedInWebhookStrategy)

    # GitHub
    s = detect_strategy({"X-GitHub-Event": "push"}, {})
    assert isinstance(s, GitHubWebhookStrategy)

    # CRM (HubSpot)
    s = detect_strategy({"X-HubSpot-Signature": "sig"}, {})
    assert isinstance(s, CRMWebhookStrategy)

    # Generic fallback
    s = detect_strategy({}, {"some": "unknown payload"})
    assert isinstance(s, GenericWebhookStrategy)
