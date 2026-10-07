"""GW-04: a live audio or video socket opens only with a stream token.

The handshake named the company in ``client_id`` and carried a ``token`` that was
read into a variable and never checked, so a company's UUID was enough to open a
live AI session billed to it.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.auth import dependencies
from src.gateway import audio_gateway, video_gateway
from src.main import app

COMPANY = str(uuid.uuid4())


@pytest.fixture
def resolved(monkeypatch):
    """Record which company the gateways go on to resolve an agent for."""
    asked: list[str] = []

    async def resolve(client_id, channel, agent_id=None):
        asked.append(client_id)
        return None                       # no agent: the socket answers "no_agent"

    fake = SimpleNamespace(resolve_agent_for_client=resolve)
    monkeypatch.setattr(audio_gateway, "get_dispatcher", lambda: fake)
    monkeypatch.setattr(video_gateway, "get_dispatcher", lambda: fake)
    return asked


@pytest.fixture
def tokens(monkeypatch):
    """``good`` belongs to COMPANY for any /stream/ path; anything else is refused."""
    async def authenticate(token, path):
        if token == "good" and path.startswith("/stream/"):
            return SimpleNamespace(company_id=uuid.UUID(COMPANY))
        raise HTTPException(status_code=401, detail="Could not validate credentials")

    monkeypatch.setattr(dependencies, "authenticate_stream_token", authenticate)


async def _handshake(path: str, **fields) -> tuple[dict, int]:
    """Open the socket over ASGI, send the handshake; the first reply and the close code."""
    incoming = [
        {"type": "websocket.connect"},
        {"type": "websocket.receive", "text": json.dumps({"event": "connect", "provider": "web", **fields})},
    ]
    sent: list[dict] = []

    async def receive():
        return incoming.pop(0) if incoming else {"type": "websocket.disconnect", "code": 1000}

    async def send(message):
        sent.append(message)

    scope = {"type": "websocket", "asgi": {"version": "3.0"}, "scheme": "ws", "path": path,
             "raw_path": path.encode(), "root_path": "", "query_string": b"",
             "headers": [(b"host", b"test")], "client": ("127.0.0.1", 1), "server": ("test", 80),
             "subprotocols": []}
    await app(scope, receive, send)
    replies = [json.loads(m["text"]) for m in sent if m["type"] == "websocket.send"]
    closes = [m.get("code") for m in sent if m["type"] == "websocket.close"]
    return replies[0], closes[0]


@pytest.mark.parametrize("path", ["/stream/audio", "/stream/video"])
async def test_no_token_is_refused_before_anything_runs(path, resolved, tokens):
    first, code = await _handshake(path, client_id=COMPANY)
    assert (first["code"], code) == ("unauthorized", 4401)
    assert resolved == []


@pytest.mark.parametrize("path", ["/stream/audio", "/stream/video"])
async def test_a_bad_token_is_refused(path, resolved, tokens):
    first, code = await _handshake(path, client_id=COMPANY, token="forged")
    assert (first["code"], code) == ("unauthorized", 4401)
    assert resolved == []


@pytest.mark.parametrize("path", ["/stream/audio", "/stream/video"])
async def test_another_companys_client_id_is_refused(path, resolved, tokens):
    first, code = await _handshake(path, client_id=str(uuid.uuid4()), token="good")
    assert (first["code"], code) == ("forbidden", 4403)
    assert resolved == []


@pytest.mark.parametrize("path", ["/stream/audio", "/stream/video"])
async def test_the_company_is_the_tokens(path, resolved, tokens):
    first, _ = await _handshake(path, token="good")      # no client_id at all
    assert first["code"] == "no_agent"
    assert resolved == [COMPANY]
