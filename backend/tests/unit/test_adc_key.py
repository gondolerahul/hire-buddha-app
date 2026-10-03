"""A Vertex-backed integration needs no stored key (P9.5 — LP-12).

Vertex AI authenticates with Application Default Credentials and ignores a
stored key, but the create schema required one and the router raised without
one, so every guide told admins to store the placeholder
``vertex-ai-service-account`` — which looks exactly like a misconfiguration.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.config.schemas import IntegrationRegistryCreate


def _create(provider: str, **kw) -> IntegrationRegistryCreate:
    return IntegrationRegistryCreate(
        company_id=uuid.uuid4(), provider_name=provider, model_name="m", service_sku="m-in",
        component_type="input_token", internal_cost=Decimal("0.3"), cost_unit="per_million_tokens", **kw)


@pytest.mark.parametrize("provider", ["google", "gemini", "anthropic", "anthropic_vertex"])
def test_an_adc_provider_is_created_without_a_key(provider):
    assert _create(provider).api_key is None


def test_a_key_provider_still_needs_one():
    with pytest.raises(ValidationError, match="api_key is required"):
        _create("azure_openai")
    assert _create("azure_openai", api_key="k").api_key == "k"


@pytest.mark.asyncio
async def test_no_key_is_stored_for_it(monkeypatch):
    from src.config import service as config_service

    class _Db:
        def add(self, row):
            self.row = row

        async def commit(self):
            pass

        async def refresh(self, _row):
            pass

    monkeypatch.setattr(config_service, "encrypt_api_key", lambda k: pytest.fail("nothing to encrypt"))
    db = _Db()
    await config_service.ConfigService(db).create_registry_entry(_create("google"))
    assert db.row.encrypted_api_key is None


def _resolving(monkeypatch, provider: str, key):
    from src.config import service as config_service

    integration = SimpleNamespace(provider_name=provider, model_name="gemini-2.5-flash",
                                  service_metadata={"project_id": "p"})

    async def resolve(self, company_id, task_type):
        return integration, key

    monkeypatch.setattr(config_service.ConfigService, "resolve_model_for_task", resolve)


@pytest.mark.asyncio
async def test_the_router_calls_an_adc_provider_without_a_key(monkeypatch):
    from src.ai.llm.gemini_adapter import GeminiAdapter
    from src.ai.llm.router import LLMRouter

    _resolving(monkeypatch, "google", None)
    adapter = await LLMRouter(db=None, company_id=uuid.uuid4())._resolve_adapter("text_generation")
    assert isinstance(adapter, GeminiAdapter)


@pytest.mark.asyncio
async def test_the_router_refuses_a_key_provider_without_one(monkeypatch):
    from src.ai.llm.router import LLMRouter

    _resolving(monkeypatch, "azure_openai", None)
    with pytest.raises(RuntimeError, match="No API key"):
        await LLMRouter(db=None, company_id=uuid.uuid4())._resolve_adapter("text_generation")
