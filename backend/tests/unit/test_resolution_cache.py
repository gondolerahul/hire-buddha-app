"""A run resolves its model once, and a key rotation reaches every process
(P9.11 — LP-I5, LP-22).

Every call site built its own ``LLMRouter`` and each router its own cache, so a
run resolved its model through the database on almost every call. The one
process-wide cache (voice key lookups, 60 s) was cleared only in the process
that rotated the key.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from src.config import resolution_cache as rc


class _Redis:
    """One Redis shared by every simulated process."""

    def __init__(self):
        self.value = 0

    async def get(self, _key):
        return str(self.value).encode()

    async def incr(self, _key):
        self.value += 1
        return self.value


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def shared(monkeypatch):
    redis, clock = _Redis(), _Clock()
    monkeypatch.setattr(rc, "_client", lambda: redis)
    monkeypatch.setattr(rc, "_monotonic", clock)
    return redis, clock


def _counting_resolver(monkeypatch):
    from src.config import service as config_service

    calls = []

    async def resolve(self, company_id, task_type):
        calls.append(task_type)
        return SimpleNamespace(provider_name="google", model_name="gemini-2.5-flash",
                               service_metadata={"project_id": "p"}), None

    monkeypatch.setattr(config_service.ConfigService, "resolve_model_for_task", resolve)
    return calls


@pytest.mark.asyncio
async def test_a_run_resolves_its_model_once(shared, monkeypatch):
    from src.ai.llm.router import LLMRouter

    calls = _counting_resolver(monkeypatch)
    company = uuid.uuid4()
    for _ in range(100):  # a router per call site, as in a run
        await LLMRouter(db=None, company_id=company)._resolve_adapter("text_generation")
    assert calls == ["text_generation"]


@pytest.mark.asyncio
async def test_a_change_anywhere_is_seen_within_a_second(shared, monkeypatch):
    from src.ai.llm.router import LLMRouter

    redis, clock = shared
    calls = _counting_resolver(monkeypatch)
    company = uuid.uuid4()
    await LLMRouter(db=None, company_id=company)._resolve_adapter("text_generation")

    redis.value += 1          # another process rotated a key
    clock.now += 0.5
    await LLMRouter(db=None, company_id=company)._resolve_adapter("text_generation")
    assert len(calls) == 1    # within the refresh second
    clock.now += 0.6
    await LLMRouter(db=None, company_id=company)._resolve_adapter("text_generation")
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_without_redis_an_entry_lives_a_minute(monkeypatch):
    from src.ai.llm.router import LLMRouter

    clock = _Clock()

    def broken():
        raise ConnectionError("no redis")

    monkeypatch.setattr(rc, "_client", broken)
    monkeypatch.setattr(rc, "_monotonic", clock)
    calls = _counting_resolver(monkeypatch)
    company = uuid.uuid4()
    await LLMRouter(db=None, company_id=company)._resolve_adapter("text_generation")
    clock.now += 59
    await LLMRouter(db=None, company_id=company)._resolve_adapter("text_generation")
    assert len(calls) == 1
    clock.now += 2
    await LLMRouter(db=None, company_id=company)._resolve_adapter("text_generation")
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_a_registry_write_publishes_the_change(shared):
    from src.config.service import ConfigService

    redis, _ = shared
    entry = SimpleNamespace(provider_name="google", service_metadata=None, company_id=uuid.uuid4())

    class _Db:
        async def execute(self, _q):
            return SimpleNamespace(scalar_one_or_none=lambda: entry)

        async def commit(self):
            pass

        async def refresh(self, _row):
            pass

    from src.config.schemas import IntegrationRegistryUpdate
    await ConfigService(_Db()).update_registry_entry(uuid.uuid4(), IntegrationRegistryUpdate(status="inactive"))
    assert redis.value == 1


@pytest.mark.asyncio
async def test_a_rotated_key_is_not_served_by_another_process(shared, monkeypatch):
    """The voice path's key lookup: the old cache was cleared only locally."""
    from src.config import service as config_service

    redis, clock = shared
    keys = iter(["old-key", "new-key"])

    async def by_sku(self, company_id, sku):
        return next(keys)

    monkeypatch.setattr(config_service.ConfigService, "get_api_key_by_sku", by_sku)
    company = uuid.uuid4()
    svc = config_service.ConfigService(db=None)
    assert await svc.resolve_api_key(company, "azure_openai", "gpt-4o") == "old-key"
    redis.value += 1            # the rotation happened in another process
    clock.now += 1.1
    assert await svc.resolve_api_key(company, "azure_openai", "gpt-4o") == "new-key"
