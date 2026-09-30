"""SA-20: POST /internal/event is disabled until INTERNAL_TOKEN is a real secret.

INTERNAL_TOKEN defaulted to ``change-me-in-production`` in code, in
.env.example and in docker-compose, and the local .env still held it. The
endpoint it guards creates executions for any tenant, so a deployment that
never set the token accepted a secret published in the repository. Now an
empty or placeholder token disables the endpoint (503), the comparison is
constant-time, and /health reports which it is.
"""
import httpx
import pytest

from src.common.config import Settings, settings
from src.gateway import envelope as envelope_module
from src.main import app

EVENT = {"event_type": "doc_indexed", "client_id": "company-1", "source": "vector_db"}


@pytest.fixture(autouse=True)
def no_real_queue(monkeypatch):
    async def fake_enqueue(function, *args, **kwargs):
        return object()

    monkeypatch.setattr(envelope_module, "enqueue_job", fake_enqueue)


async def _call(method: str, path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def test_the_shipped_default_is_empty():
    assert Settings.model_fields["INTERNAL_TOKEN"].default == ""


@pytest.mark.parametrize("configured", ["", "   ", "change-me-in-production", "CHANGEME"])
async def test_a_placeholder_token_disables_the_endpoint(monkeypatch, configured):
    monkeypatch.setattr(settings, "INTERNAL_TOKEN", configured)
    # Even a caller who sends the placeholder itself is refused.
    resp = await _call("POST", "/internal/event", json=EVENT,
                       headers={"X-Internal-Token": configured})
    assert resp.status_code == 503
    health = (await _call("GET", "/api/v1/health")).json()
    assert health["internal_events"] == "disabled"


async def test_a_real_token_is_required_and_checked(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_TOKEN", "3hX9-real-secret")
    assert (await _call("POST", "/internal/event", json=EVENT)).status_code == 401
    wrong = await _call("POST", "/internal/event", json=EVENT, headers={"X-Internal-Token": "nope"})
    assert wrong.status_code == 401
    right = await _call("POST", "/internal/event", json=EVENT,
                        headers={"X-Internal-Token": "3hX9-real-secret"})
    assert right.status_code == 202
    assert (await _call("GET", "/api/v1/health")).json()["internal_events"] == "enabled"
