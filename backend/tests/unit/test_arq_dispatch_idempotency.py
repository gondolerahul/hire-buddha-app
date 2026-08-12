"""Phase 11 Track 2 — run_execution_recursive dispatch idempotency.

Regression for the runaway-billing bug: an already-settled run got
re-dispatched 6 times (arq retries / double-enqueue), re-settling billing
each time on the SAME run_id. The dispatch path must now short-circuit when
the run is already in a terminal state, never reaching the engine/loop (and
thus never re-billing). A still-startable run must NOT be short-circuited.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

import src.ai.core.arq_jobs as arq_jobs
import src.ai.core.feature_flags as feature_flags_mod
from src.ai.schemas.enums import RunStatus


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    def __init__(self, run):
        self.run = run

    async def execute(self, *_a, **_k):
        return _FakeResult(self.run)

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False


class _FakeRedis:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class _FakeFlags:
    def __init__(self, *_a, **_k):
        pass

    async def is_on(self, *_a, **_k):
        return False


class _ExplodingEngine:
    """Stand-in for the AgentLoop that proves it was never constructed when
    the idempotency guard should have short-circuited."""
    def __init__(self, *_a, **_k):
        raise AssertionError("AgentLoop must not run for a terminal run")

    async def run(self, *_a, **_k):  # pragma: no cover
        raise AssertionError("AgentLoop.run must not be reached")


def _make_run(status: str):
    return SimpleNamespace(
        id=uuid4(),
        entity_id=uuid4(),
        company_id=uuid4(),
        status=status,
        input_data={},
        entity=SimpleNamespace(id=uuid4(), status="ACTIVE", metadata_extensions={}),
    )


def _patch(monkeypatch, run, engine_cls=_ExplodingEngine):
    monkeypatch.setattr(arq_jobs, "AsyncSessionLocal", lambda: _FakeSession(run))
    monkeypatch.setattr("src.ai.core.agent_loop.AgentLoop", engine_cls)
    monkeypatch.setattr(feature_flags_mod, "FeatureFlags", _FakeFlags)
    fake_redis = _FakeRedis()
    monkeypatch.setattr("redis.asyncio.from_url", lambda *_a, **_k: fake_redis)
    return fake_redis


@pytest.mark.parametrize(
    "status",
    [
        RunStatus.COMPLETED.value,
        RunStatus.FAILED.value,
        RunStatus.PARTIAL_COMPLETE.value,
        RunStatus.CANCELLED.value,
    ],
)
@pytest.mark.asyncio
async def test_terminal_run_is_not_redispatched(monkeypatch, status):
    run = _make_run(status)
    fake_redis = _patch(monkeypatch, run)

    # Must return cleanly (no exception) — the ExplodingEngine guarantees the
    # engine was never constructed, so no re-billing happens.
    result = await arq_jobs.run_execution_recursive({}, str(run.id))
    assert result is None
    assert fake_redis.closed is True


@pytest.mark.asyncio
async def test_startable_run_is_dispatched(monkeypatch):
    """A PENDING run is NOT short-circuited — it reaches the engine. We prove
    that by letting the engine constructor raise a sentinel and catching it."""
    run = _make_run(RunStatus.PENDING.value)

    class _SentinelEngine:
        def __init__(self, *_a, **_k):
            raise RuntimeError("reached-engine-sentinel")

    _patch(monkeypatch, run, engine_cls=_SentinelEngine)

    with pytest.raises(RuntimeError, match="reached-engine-sentinel"):
        await arq_jobs.run_execution_recursive({}, str(run.id))
