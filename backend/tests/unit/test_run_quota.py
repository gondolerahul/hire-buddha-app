"""A company may start so many runs a minute, and the quota fails closed (GH-03, HD17).

There was no per-tenant quota anywhere. Now a company may start
``RUNS_STARTED_PER_MINUTE`` top-level runs a minute: the API answers 429 with
``Retry-After``, and the gateway job defers itself so a webhook's run is
postponed, not lost. The window refuses when Redis is down (GH-21). The API
side on Postgres is in tests/integration/test_run_quota.py.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from src.ai.governance import run_quota
from src.ai.governance.run_quota import RunQuotaExceeded, require_run_slot


@pytest.fixture
def limiter(monkeypatch):
    """A limiter that allows ``budget`` starts, then refuses; records its calls."""
    state = SimpleNamespace(budget=2, calls=[])

    class _Limiter:
        def __init__(self, _redis):
            pass

        async def check_and_consume(self, key, limit, window_seconds, fail_open=False):
            state.calls.append((key, limit, window_seconds, fail_open))
            state.budget -= 1
            return state.budget >= 0

    monkeypatch.setattr("src.ai.governance.rate_limiter.RedisRateLimiter", _Limiter)
    monkeypatch.setattr("src.common.redis_client.shared_redis", lambda: None)
    return state


@pytest.mark.asyncio
async def test_past_the_quota_a_start_is_refused(limiter, monkeypatch):
    monkeypatch.setattr("src.common.config.settings.RUNS_STARTED_PER_MINUTE", 2)
    company = uuid.uuid4()
    await require_run_slot(company)
    await require_run_slot(company)
    with pytest.raises(RunQuotaExceeded, match="2 runs a minute"):
        await require_run_slot(company)
    assert limiter.calls[0] == (f"runs_started:{company}", 2, 60, False)   # fails closed


@pytest.mark.asyncio
async def test_zero_turns_it_off(limiter, monkeypatch):
    monkeypatch.setattr("src.common.config.settings.RUNS_STARTED_PER_MINUTE", 0)
    for _ in range(5):
        await require_run_slot(uuid.uuid4())
    assert limiter.calls == []


@pytest.mark.asyncio
async def test_the_api_answers_429_with_retry_after(monkeypatch):
    from fastapi import HTTPException
    from src.ai import service

    async def _full(_company):
        raise RunQuotaExceeded("This company may start 60 runs a minute")

    monkeypatch.setattr(run_quota, "require_run_slot", _full)
    with pytest.raises(HTTPException) as refused:
        await service._take_run_slot(uuid.uuid4())
    assert refused.value.status_code == 429 and refused.value.headers == {"Retry-After": "60"}


# ── the gateway job defers, then refuses ────────────────────────────────────


class _Session:
    def __init__(self):
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def add(self, obj):
        self.added.append(obj)


@pytest.fixture
def gateway(monkeypatch):
    from src.ai.core import arq_jobs
    from src.gateway import agent_choice
    from src.gateway.agent_choice import AgentChoice

    session = _Session()

    async def _choose(db, company_id, named=()):
        return AgentChoice(entity=SimpleNamespace(id=uuid.uuid4(), name="agent"))

    async def _full(_company):
        raise RunQuotaExceeded("This company may start 60 runs a minute")

    monkeypatch.setattr("src.common.database.AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(agent_choice, "choose_agent", _choose)
    monkeypatch.setattr(run_quota, "require_run_slot", _full)
    envelope = {"client_id": str(uuid.uuid4()), "event_type": "lead.created", "source": "crm",
                "raw_data": {"raw": {}}, "id": "evt-1"}
    return arq_jobs, session, envelope


@pytest.mark.asyncio
async def test_a_webhooks_run_is_deferred_a_minute_not_dropped(gateway):
    from arq.worker import Retry

    arq_jobs, session, envelope = gateway
    with pytest.raises(Retry) as deferred:
        await arq_jobs.process_gateway_event({"job_try": 1}, envelope)
    assert deferred.value.defer_score == 60_000
    assert session.added == []


@pytest.mark.asyncio
async def test_on_its_last_try_it_is_refused(gateway):
    arq_jobs, session, envelope = gateway
    assert await arq_jobs.process_gateway_event({"job_try": arq_jobs._GATEWAY_RUN_TRIES}, envelope) is None
    assert session.added == []
