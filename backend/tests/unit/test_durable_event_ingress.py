"""SA-09: an inbound event is acknowledged only once it is on the arq queue.

Before, POST /webhook/inbound and POST /internal/event returned 202 and then
published the envelope to an in-process asyncio.Queue from a background task.
A restart between the 202 and the dispatcher's enqueue lost the event with no
record, an event published while no consumer was registered was counted as
"dropped", and when arq was unreachable the dispatcher ran a whole AgentLoop
inside the API process instead.

Now the endpoint enqueues ``process_gateway_event`` itself and answers 202 only
after Redis has the job; if it cannot, it answers 503 so the provider retries.
Webhooks arrive at a registered, signed endpoint since GW-01
(``webhook_endpoint_double`` stands one in).
"""
import importlib.util

import httpx
import pytest

from src.common.config import settings
from src.gateway import envelope as envelope_module
from src.main import app
from tests.unit.webhook_endpoint_double import bind_endpoint, signed_json

TOKEN = "sa-09-test-token-not-a-placeholder"


@pytest.fixture
def queued(monkeypatch):
    """Capture enqueue_job calls made through the envelope module."""
    calls = []

    async def fake_enqueue(function, *args, **kwargs):
        calls.append((function, args, kwargs))
        return object()

    monkeypatch.setattr(envelope_module, "enqueue_job", fake_enqueue)
    return calls


@pytest.fixture
def redis_down(monkeypatch):
    async def failing_enqueue(function, *args, **kwargs):
        raise ConnectionError("Redis is unreachable")

    monkeypatch.setattr(envelope_module, "enqueue_job", failing_enqueue)


@pytest.fixture(autouse=True)
def internal_token(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_TOKEN", TOKEN)


async def _post(path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, **kwargs)


async def test_webhook_is_queued_before_the_202(queued, monkeypatch):
    endpoint = bind_endpoint(monkeypatch, source="crm")
    body, headers = signed_json({"crm_event": "lead.created", "properties": {"phone": "+911234567890"}})
    resp = await _post(f"/webhook/inbound/{endpoint.id}", content=body, headers=headers)
    assert resp.status_code == 202
    data = resp.json()
    assert len(queued) == 1
    function, args, _ = queued[0]
    assert function == "process_gateway_event"
    envelope = args[0]
    assert envelope["id"] == data["correlation_id"]
    assert envelope["channel"] == "webhook"
    assert envelope["client_id"] == str(endpoint.company_id)
    assert envelope["event_type"] == "lead.created"


async def test_webhook_is_refused_when_it_cannot_be_queued(redis_down, monkeypatch):
    endpoint = bind_endpoint(monkeypatch, source="generic")
    body, headers = signed_json({"type": "x"})
    resp = await _post(f"/webhook/inbound/{endpoint.id}", content=body, headers=headers)
    assert resp.status_code == 503
    assert resp.json()["status"] == "unavailable"
    assert "correlation_id" in resp.json()


async def test_internal_event_is_queued_before_the_202(queued):
    resp = await _post(
        "/internal/event",
        json={"event_type": "doc_indexed", "client_id": "company-2", "source": "vector_db",
              "payload": {"document_id": "d1"}, "correlation_id": "corr-1"},
        headers={"X-Internal-Token": TOKEN},
    )
    assert resp.status_code == 202
    assert resp.json()["queued"] is True
    function, args, _ = queued[0]
    assert function == "process_gateway_event"
    assert args[0]["channel"] == "internal"
    assert args[0]["id"] == "corr-1"
    assert args[0]["raw_data"] == {"document_id": "d1"}


async def test_internal_event_is_refused_when_it_cannot_be_queued(redis_down):
    resp = await _post(
        "/internal/event",
        json={"event_type": "doc_indexed", "client_id": "company-2", "source": "vector_db"},
        headers={"X-Internal-Token": TOKEN},
    )
    assert resp.status_code == 503


@pytest.mark.parametrize("module", ["src.gateway.event_bus"])
def test_the_in_process_bus_is_gone(module):
    assert importlib.util.find_spec(module) is None


def test_the_dispatcher_no_longer_runs_agent_loops():
    from src.gateway.dispatcher import CentralDispatcher

    for name in ("dispatch", "_dispatch_async", "_execute_in_process", "_consume_event_bus"):
        assert not hasattr(CentralDispatcher, name), name


@pytest.fixture(autouse=True)
def _direct_queue_path(monkeypatch):
    """These check the direct queue path (AUTOMATION_GATEWAY_EVENTS off, the rollback
    setting); the event path is tests/integration/test_automation_gateway.py."""
    monkeypatch.setattr("src.common.config.settings.AUTOMATION_GATEWAY_EVENTS", False)
