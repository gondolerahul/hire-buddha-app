"""Every endpoint is served by the API on port 8000.

The Unified Gateway (:8001) reverse-proxied REST to the API and served the
webhook, internal-event and media-stream endpoints itself; the voice service
(:8002) was retired but still the STREAMING_HOST default. The gateway is merged
into the API: one app, one CORS list, one rate limit, no proxy.

Also covers SA-01 (the stream-URL default), SA-11/SA-12 (the superseded apps are
deleted), SA-16/SA-17 (no catch-all proxy) and SA-19 (one CORS list).
"""
import importlib.util
import re
from pathlib import Path

import httpx
import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.middleware.cors import CORSMiddleware

from src.common import router_mounts
from src.common.config import Settings, settings
from src.main import app
from src.voice import public_urls

SRC = Path(__file__).resolve().parents[2] / "src"


@pytest.fixture(autouse=True)
def worker_consuming(monkeypatch):
    """Health reads the worker heartbeat from Redis; these tests are not about it."""
    async def ok():
        return {"status": "ok", "queues": {}}

    monkeypatch.setattr(router_mounts, "worker_status", ok)


def _http_routes() -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in app.routes if isinstance(route, APIRoute)
        for method in route.methods
    }


def _ws_paths() -> set[str]:
    return {route.path for route in app.routes if isinstance(route, APIWebSocketRoute)}


def _middleware(cls):
    found = [m for m in app.user_middleware if m.cls is cls]
    assert found, f"{cls.__name__} is not installed"
    return getattr(found[0], "kwargs", None) or found[0].options


async def _request(method: str, path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def test_the_gateway_endpoints_are_served_by_the_api():
    http = _http_routes()
    for route in [
        ("POST", "/webhook/inbound"),
        ("POST", "/internal/event"),
        ("GET", "/metrics/gateway"),
        ("GET", "/health"),
        ("GET", "/api/v1/health"),
        ("POST", "/webhooks/voice/tata/incoming"),   # the HTTP webhook on the Tata stream path
    ]:
        assert route in http, route

    assert {
        "/stream/audio",
        "/stream/video",
        "/stream/twilio/{session_id}",
        "/stream/tata/{session_id}",
        "/webhooks/voice/tata/incoming",
        "/mobile/ws",
    } <= _ws_paths()
    assert app.state.unmounted_routers == []


def test_there_is_no_catch_all_proxy():
    # SA-16/SA-17: the gateway's /{path:path} proxy swallowed any route declared
    # after it and buffered SSE unless the path ended in /stream.
    assert "/{path:path}" not in {getattr(r, "path", "") for r in app.routes}


@pytest.mark.parametrize("module", [
    "src.gateway.app",             # the :8001 app and its reverse proxy
    "src.gateway.main",            # the superseded pure-proxy gateway (SA-11)
    "src.gateway.config",
    "src.gateway.gateway_config",  # a second settings class with its own defaults
    "src.gateway.auth_middleware",
    "src.voice.main",              # the retired :8002 service (SA-12)
    "src.voice.transcript_api",    # unauthenticated, only mounted on :8002
])
def test_the_superseded_apps_are_gone(module):
    assert importlib.util.find_spec(module) is None


async def test_health_is_the_same_on_both_paths():
    old, new = await _request("GET", "/health"), await _request("GET", "/api/v1/health")
    assert old.status_code == new.status_code == 200
    assert old.json() == new.json()


def test_one_cors_list_from_settings():
    assert _middleware(CORSMiddleware)["allow_origins"] == settings.cors_origins_list


def test_stream_urls_default_to_this_api():
    # SA-01: the default was localhost:8002, the retired voice service.
    assert Settings.model_fields["STREAMING_HOST"].default == "localhost:8000"
    offenders = [
        f"{path.relative_to(SRC)}:{n}"
        for path in SRC.rglob("*.py")
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"localhost:800[12]", line)
    ]
    assert offenders == []


def test_stream_and_callback_urls_follow_the_protocol(monkeypatch):
    monkeypatch.setattr(settings, "STREAMING_HOST", "gateway.example.com")
    monkeypatch.setattr(settings, "STREAMING_PROTOCOL", "wss")
    assert public_urls.stream_url("/stream/tata/abc") == "wss://gateway.example.com/stream/tata/abc"
    assert public_urls.callback_url("/webhooks/voice/twilio/status") == (
        "https://gateway.example.com/webhooks/voice/twilio/status"
    )
    monkeypatch.setattr(settings, "STREAMING_HOST", "localhost:8000")
    monkeypatch.setattr(settings, "STREAMING_PROTOCOL", "ws")
    assert public_urls.stream_url("/stream/twilio/x") == "ws://localhost:8000/stream/twilio/x"
    assert public_urls.callback_url("/y") == "http://localhost:8000/y"


def test_websockets_are_not_traced():
    from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware

    excluded = _middleware(OpenTelemetryMiddleware)["excluded_urls"]
    assert excluded.url_disabled("ws://127.0.0.1:8000/stream/twilio/abc")
    assert excluded.url_disabled("wss://gateway.hirebuddha.com/stream/audio")
    assert not excluded.url_disabled("http://127.0.0.1:8000/api/v1/health")


async def test_rest_is_rate_limited_and_webhooks_are_not(monkeypatch):
    real = app.state.limiter
    tight = Limiter(key_func=get_remote_address, default_limits=["2/minute"])
    tight._exempt_routes = set(real._exempt_routes)
    monkeypatch.setattr(app.state, "limiter", tight)

    statuses = [(await _request("GET", "/")).status_code for _ in range(3)]
    assert statuses == [200, 200, 429]

    origin = settings.cors_origins_list[0]
    limited = await _request("GET", "/", headers={"Origin": origin})
    assert limited.status_code == 429
    assert limited.headers["access-control-allow-origin"] == origin   # CORS is outermost

    for _ in range(3):
        resp = await _request("POST", "/webhook/inbound?client_id=c1", json={"type": "x"})
        assert resp.status_code == 202
