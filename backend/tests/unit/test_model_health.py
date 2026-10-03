"""A fresh install is told how to get a model (P9.7 — LP-10).

``model_task_defaults`` starts empty, so every run failed with "No model
configured … Please configure a default in the AI Model Configuration page",
and nothing on the health endpoint or in the error named the page's address or
the seed that fills it.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from src.common import router_mounts
from src.config import model_health


async def _health(monkeypatch, configured):
    monkeypatch.setattr(router_mounts, "worker_status", AsyncMock(return_value={"status": "ok", "queues": {}}))
    monkeypatch.setattr(model_health, "_configured", AsyncMock(return_value=configured))
    app = FastAPI()
    app.include_router(router_mounts.health_router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        return (await client.get("/api/v1/health")).json()


@pytest.mark.asyncio
async def test_health_says_which_defaults_are_missing(monkeypatch):
    body = await _health(monkeypatch, {"thinking"})
    assert body["status"] == "degraded"
    assert body["models"]["missing"] == ["text_generation"]
    assert "/ai-config" in body["models"]["fix"] and "seed_integration_registry" in body["models"]["fix"]


@pytest.mark.asyncio
async def test_health_is_ok_with_both(monkeypatch):
    body = await _health(monkeypatch, {"text_generation", "thinking"})
    assert (body["status"], body["models"]) == ("ok", {"status": "ok", "missing": []})


@pytest.mark.asyncio
async def test_an_unreadable_database_is_unknown_not_degraded(monkeypatch):
    monkeypatch.setattr(model_health, "_configured", AsyncMock(side_effect=OSError("down")))
    assert await model_health.model_status() == {"status": "unknown", "missing": []}


@pytest.mark.asyncio
async def test_the_error_names_the_page_and_the_seed(monkeypatch):
    from src.ai.llm.router import LLMRouter
    from src.config import service as config_service

    async def unresolved(self, company_id, task_type):
        return None, None

    monkeypatch.setattr(config_service.ConfigService, "resolve_model_for_task", unresolved)
    with pytest.raises(RuntimeError) as err:
        await LLMRouter(db=SimpleNamespace(), company_id=uuid.uuid4())._resolve_adapter("text_generation")
    assert "/ai-config" in str(err.value) and "seed_integration_registry.py" in str(err.value)
