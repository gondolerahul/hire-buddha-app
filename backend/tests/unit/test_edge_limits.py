"""GW-02: the edge past the REST routes is limited.

Only REST routes were rate limited. A webhook endpoint took any number of
signed deliveries, an address could open live sockets without end, and a
company could hold any number of live model sessions — each one billed. Now:
signed deliveries per endpoint (``WEBHOOK_RATE_LIMIT``), live-socket handshakes
per address (``WS_HANDSHAKE_RATE_LIMIT``), live sessions per company
(``LIVE_SESSIONS_PER_COMPANY``, at admission and as each session connects).
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter

from src.common.config import settings
from src.gateway import envelope as envelope_module
from src.gateway import socket_limits
from src.voice import live_sessions
from tests.unit.webhook_endpoint_double import bind_endpoint, signed_json


@pytest.fixture
def memory_limits(monkeypatch):
    """The edge limits counted in memory, fresh for each test."""
    monkeypatch.setattr(socket_limits, "limiter", SimpleNamespace(limiter=FixedWindowRateLimiter(MemoryStorage())))


@pytest.fixture
def no_live_sessions(monkeypatch):
    monkeypatch.setattr(live_sessions, "_open", live_sessions.Counter())


# --- webhooks ---------------------------------------------------------------

@pytest.fixture
def queued(monkeypatch):
    calls = []

    async def fake_enqueue(function, *args, **kwargs):
        calls.append(args[0])
        return object()

    monkeypatch.setattr(envelope_module, "enqueue_job", fake_enqueue)
    return calls


async def _post(path: str, **kwargs) -> httpx.Response:
    from src.main import app
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, **kwargs)


async def test_an_endpoint_takes_so_many_signed_deliveries(queued, monkeypatch, memory_limits):
    monkeypatch.setattr(settings, "WEBHOOK_RATE_LIMIT", "2/minute")
    endpoint = bind_endpoint(monkeypatch, source="generic")
    answers = []
    for n in range(3):
        body, headers = signed_json({"type": "lead.created", "id": n})
        answers.append(await _post(f"/webhook/inbound/{endpoint.id}", content=body, headers=headers))
    assert [a.status_code for a in answers] == [202, 202, 429]
    assert answers[2].headers["Retry-After"] == "60"
    assert len(queued) == 2


async def test_a_limited_delivery_is_taken_when_retried(queued, monkeypatch, memory_limits):
    """It was refused before it was claimed, so the retry is not a 'duplicate'."""
    allowed = iter([False, True])
    monkeypatch.setattr("src.gateway.webhook_inbound.webhook_allowed", lambda _id: next(allowed))
    endpoint = bind_endpoint(monkeypatch, source="generic")
    body, headers = signed_json({"type": "lead.created", "id": 1})
    first = await _post(f"/webhook/inbound/{endpoint.id}", content=body, headers=headers)
    retry = await _post(f"/webhook/inbound/{endpoint.id}", content=body, headers=headers)
    assert (first.status_code, retry.status_code) == (429, 202)
    assert len(queued) == 1


async def test_unsigned_requests_do_not_use_up_an_endpoint(queued, monkeypatch, memory_limits):
    monkeypatch.setattr(settings, "WEBHOOK_RATE_LIMIT", "1/minute")
    endpoint = bind_endpoint(monkeypatch, source="generic")
    for _ in range(3):
        resp = await _post(f"/webhook/inbound/{endpoint.id}", json={"type": "x"})
        assert resp.status_code == 401
    body, headers = signed_json({"type": "lead.created"})
    assert (await _post(f"/webhook/inbound/{endpoint.id}", content=body, headers=headers)).status_code == 202


# --- live-socket handshakes -------------------------------------------------

class _Socket:
    def __init__(self, host="203.0.113.7", messages=()):
        self.client = SimpleNamespace(host=host)
        self.url = SimpleNamespace(path="/stream/audio")
        self.messages = list(messages)
        self.sent: list[str] = []
        self.closed = None

    async def accept(self):
        pass

    async def receive_text(self):
        return self.messages.pop(0)

    async def send_text(self, text):
        self.sent.append(text)

    async def send_json(self, data):
        self.sent.append(json.dumps(data))

    async def close(self, code=1000, reason=""):
        self.closed = (code, reason)


def test_an_address_opens_so_many_sockets_a_minute(monkeypatch, memory_limits):
    monkeypatch.setattr(settings, "WS_HANDSHAKE_RATE_LIMIT", "2/minute")
    one, other = _Socket("203.0.113.7"), _Socket("203.0.113.8")
    assert [socket_limits.handshake_allowed(one) for _ in range(3)] == [True, True, False]
    assert socket_limits.handshake_allowed(other)


@pytest.mark.asyncio
async def test_the_audio_socket_closes_over_the_limit(monkeypatch, memory_limits):
    from src.gateway import audio_gateway

    monkeypatch.setattr(settings, "WS_HANDSHAKE_RATE_LIMIT", "1/minute")
    first = _Socket(messages=["not json"])
    await audio_gateway.unified_audio_streaming(first)
    assert first.closed[0] == 1003            # through to the handshake
    second = _Socket(messages=["not json"])
    await audio_gateway.unified_audio_streaming(second)
    assert second.closed == (socket_limits.TOO_MANY, "rate_limited")


def test_counts_survive_redis_being_down(monkeypatch):
    class _Down:
        def hit(self, *_a):
            raise ConnectionError("redis down")

    failures = []
    monkeypatch.setattr(socket_limits, "limiter", SimpleNamespace(limiter=_Down()))
    monkeypatch.setattr(socket_limits, "_fallback", FixedWindowRateLimiter(MemoryStorage()))
    monkeypatch.setattr("src.common.gates.gate_failed", lambda gate, *_a, **_k: failures.append(gate))
    monkeypatch.setattr(settings, "WS_HANDSHAKE_RATE_LIMIT", "1/minute")
    sock = _Socket("198.51.100.1")
    assert [socket_limits.handshake_allowed(sock) for _ in range(2)] == [True, False]
    assert failures == ["edge_rate_limit", "edge_rate_limit"]


# --- live sessions per company ----------------------------------------------

def test_a_company_holds_so_many_live_sessions(monkeypatch, no_live_sessions):
    monkeypatch.setattr(settings, "LIVE_SESSIONS_PER_COMPANY", 2)
    company, other = uuid.uuid4(), uuid.uuid4()
    first = live_sessions.acquire(company, kind="call")
    second = live_sessions.acquire(company, kind="call")
    assert first and second
    assert live_sessions.acquire(company, kind="call") is None
    assert live_sessions.acquire(other, kind="call") is not None
    first.release()
    first.release()                           # once only
    assert live_sessions.open_count(company) == 1
    assert live_sessions.acquire(company, kind="call") is not None


@pytest.mark.asyncio
async def test_a_call_is_refused_at_admission_at_the_cap(monkeypatch, no_live_sessions):
    from src.voice.call_admission import call_refusal

    monkeypatch.setattr(settings, "LIVE_SESSIONS_PER_COMPANY", 1)
    company = uuid.uuid4()
    live_sessions.acquire(company, kind="call")
    refusal = await call_refusal(object(), company, direction="inbound", checkpoint="twilio_webhook")
    assert refusal == live_sessions.cap_message()


@pytest.mark.asyncio
async def test_a_browser_session_at_the_cap_never_reaches_the_model(monkeypatch, no_live_sessions):
    from src.gateway import web_audio_adapter

    monkeypatch.setattr(settings, "LIVE_SESSIONS_PER_COMPANY", 1)
    company = uuid.uuid4()
    live_sessions.acquire(company, kind="call")

    async def _admitted(*_a, **_k):
        return None

    monkeypatch.setattr("src.voice.call_admission.call_refusal", _admitted)
    adapter = web_audio_adapter.WebAudioAdapter.__new__(web_audio_adapter.WebAudioAdapter)
    adapter.websocket, adapter.db, adapter.session_id = _Socket(), object(), uuid.uuid4()
    adapter.voice_session = SimpleNamespace(company_id=company, direction="inbound")

    async def _connect():
        raise AssertionError("connected a session past the cap")

    adapter._connect_and_stream = _connect
    await adapter._setup_and_run()
    assert adapter.websocket.closed == (4429, "too_many_live_sessions")


@pytest.mark.asyncio
async def test_a_browser_session_short_of_credit_is_refused(monkeypatch, no_live_sessions):
    """It was never admitted at all before."""
    from src.gateway import web_audio_adapter

    async def _short(*_a, **_k):
        return "Cannot start execution: no free credit"

    monkeypatch.setattr("src.voice.call_admission.call_refusal", _short)
    adapter = web_audio_adapter.WebAudioAdapter.__new__(web_audio_adapter.WebAudioAdapter)
    adapter.websocket, adapter.db, adapter.session_id = _Socket(), object(), uuid.uuid4()
    adapter.voice_session = SimpleNamespace(company_id=uuid.uuid4(), direction="inbound")

    async def _connect():
        raise AssertionError("connected a session short of credit")

    adapter._connect_and_stream = _connect
    await adapter._setup_and_run()
    assert adapter.websocket.closed == (4002, "insufficient_credits")


@pytest.mark.asyncio
async def test_a_session_gives_its_place_back_when_it_ends(monkeypatch, no_live_sessions):
    from src.gateway import web_audio_adapter

    company = uuid.uuid4()

    async def _admitted(*_a, **_k):
        return None

    monkeypatch.setattr("src.voice.call_admission.call_refusal", _admitted)
    adapter = web_audio_adapter.WebAudioAdapter.__new__(web_audio_adapter.WebAudioAdapter)
    adapter.websocket, adapter.db, adapter.session_id = _Socket(), object(), uuid.uuid4()
    adapter.voice_session = SimpleNamespace(company_id=company, direction="inbound")
    held = []

    async def _connect():
        held.append(live_sessions.open_count(company))
        raise RuntimeError("the model hung up")

    adapter._connect_and_stream = _connect
    with pytest.raises(RuntimeError):
        await adapter._setup_and_run()
    assert held == [1]
    assert live_sessions.open_count(company) == 0


class _NoSession:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *_):
        return False


@pytest.mark.asyncio
@pytest.mark.parametrize("at_cap", [True, False])
async def test_a_phone_call_at_the_cap_is_not_connected(monkeypatch, no_live_sessions, at_cap):
    """Two calls admitted together for the last place: the media socket refuses the second."""
    from src.voice import websocket_handler

    monkeypatch.setattr(settings, "LIVE_SESSIONS_PER_COMPANY", 1)
    company = uuid.uuid4()

    async def _admitted(*_a, **_k):
        return None

    async def _agent(**_k):
        return SimpleNamespace()

    monkeypatch.setattr("src.voice.call_admission.call_refusal", _admitted)
    monkeypatch.setattr("src.common.database.AsyncSessionLocal", _NoSession)  # through tenant_session
    handler = websocket_handler.BaseStreamHandler.__new__(websocket_handler.BaseStreamHandler)
    handler.websocket, handler.session_id = _Socket(), uuid.uuid4()
    handler.voice_session = SimpleNamespace(company_id=company, direction="inbound", agent_id=uuid.uuid4(),
                                            customer_id=uuid.uuid4(), session_metadata={})
    handler.agent_loader = SimpleNamespace(load_agent_for_session=_agent)
    handler._open_recording_file = lambda: None
    connected = []

    async def _connect(agent_context):
        connected.append(live_sessions.open_count(company))

    handler._connect_and_stream = _connect
    if at_cap:
        live_sessions.acquire(company, kind="call")    # the other call took the place
    await handler._setup_live_and_run()
    if at_cap:
        assert connected == [] and handler.websocket.closed == (4429, "Too many live sessions")
    else:
        assert connected == [1] and live_sessions.open_count(company) == 0
