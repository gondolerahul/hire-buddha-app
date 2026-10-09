"""GW-21, HD12: the API is one instance by decision, and health says which one answered.

A call's live state is in the process that holds its socket — the model
connection, the buffers, a video peer connection, the company's live-session
count (GW-02). Nothing gave a reconnect affinity to that process. Decision
HD12 is one instance, sticky by ``session_id`` when a second is needed;
``GET /api/v1/health`` reports the instance so two answers can be told apart.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI

from src.common import instance, router_mounts
from src.voice import live_sessions


@pytest.fixture(autouse=True)
def quiet_checks(monkeypatch):
    async def ok():
        return {"status": "ok", "queues": {}}

    async def models_ok():
        return {"status": "ok", "missing": []}

    monkeypatch.setattr(router_mounts, "worker_status", ok)
    monkeypatch.setattr(router_mounts, "model_status", models_ok)
    monkeypatch.setattr(live_sessions, "_open", live_sessions.Counter())


async def _health() -> dict:
    app = FastAPI()
    app.include_router(router_mounts.health_router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return (await client.get("/api/v1/health")).json()


async def test_health_names_the_instance_and_its_live_sessions():
    slot = live_sessions.acquire(uuid.uuid4(), kind="call")
    body = await _health()
    assert body["instance"]["id"] == instance.INSTANCE_ID
    assert body["instance"]["started_at"].endswith("Z")
    assert body["instance"]["live_sessions"] == 1
    slot.release()
    assert (await _health())["instance"]["live_sessions"] == 0


def test_a_deployed_instance_can_be_named(monkeypatch):
    import importlib

    monkeypatch.setenv("INSTANCE_ID", "api-a")
    try:
        assert importlib.reload(instance).INSTANCE_ID == "api-a"
    finally:
        monkeypatch.delenv("INSTANCE_ID")
        importlib.reload(instance)
