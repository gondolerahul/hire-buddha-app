"""SA-I4: a dead or stalled worker shows on /api/v1/health.

When the arq worker died the API kept accepting executions, every run sat in
PENDING, and nothing reported an error — health said "ok".
"""
import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from arq.constants import default_queue_name

from src.common import router_mounts, worker_health
from src.common.config import settings
from src.common.worker_health import beat, heartbeat_key, queue_status

NOW = 1_800_000_000.0


class FakeRedis:
    """The sorted-set commands the heartbeat and the status read use."""

    def __init__(self):
        self.sets: dict[str, dict[str, float]] = {}
        self.closed = False

    def pipeline(self, transaction=True):
        return _Pipeline(self)

    async def zadd(self, key, mapping):
        self.sets.setdefault(key, {}).update(mapping)

    async def zrem(self, key, member):
        self.sets.get(key, {}).pop(member, None)

    async def zremrangebyscore(self, key, low, high):
        high = float(high)
        for member, score in list(self.sets.get(key, {}).items()):
            if score <= high:
                del self.sets[key][member]

    def _range(self, key, low, high):
        low = float("-inf") if low == "-inf" else float(low)
        high = float("inf") if high == "+inf" else float(high)
        return sorted((s, m) for m, s in self.sets.get(key, {}).items() if low <= s <= high)

    async def zcount(self, key, low, high):
        return len(self._range(key, low, high))

    async def zrangebyscore(self, key, low, high, start=0, num=None, withscores=False):
        items = self._range(key, low, high)[start:None if num is None else start + num]
        return [(m, s) for s, m in items] if withscores else [m for _, m in items]

    async def aclose(self):
        self.closed = True


class _Pipeline:
    def __init__(self, redis):
        self.redis, self.calls = redis, []

    def __getattr__(self, name):
        return lambda *a, **k: self.calls.append((name, a, k))

    async def execute(self):
        for name, a, k in self.calls:
            await getattr(self.redis, name)(*a, **k)


async def test_a_beating_worker_is_live_and_a_silent_one_is_not():
    r = FakeRedis()
    await beat(r, "arq:queue", "vm:101", now=NOW - 5)
    await beat(r, "arq:queue", "vm:102", now=NOW - 3 * settings.WORKER_HEARTBEAT_SECONDS - 1)
    await beat(r, "arq:queue", "vm:103", now=NOW - 7200)        # pruned by the next beat
    await beat(r, "arq:queue", "vm:101", now=NOW)
    assert (await queue_status(r, "arq:queue", now=NOW))["workers"] == 1
    assert set(r.sets[heartbeat_key("arq:queue")]) == {"vm:101", "vm:102"}


async def test_the_queue_reports_due_jobs_and_how_long_the_oldest_has_waited():
    r = FakeRedis()
    # arq scores are milliseconds: two due jobs, one deferred into the future.
    r.sets["arq:queue"] = {"j1": (NOW - 90) * 1000, "j2": (NOW - 10) * 1000, "j3": (NOW + 600) * 1000}
    assert await queue_status(r, "arq:queue", now=NOW) == {"workers": 0, "due_jobs": 2, "oldest_due_seconds": 90}


@pytest.mark.parametrize("workers, oldest_age, expected", [
    (0, 0, "down"),
    (1, settings.WORKER_BACKLOG_ALERT_SECONDS + 1, "backlogged"),
    (1, 30, "ok"),
])
async def test_worker_status(monkeypatch, workers, oldest_age, expected):
    import time
    now = time.time()
    r = FakeRedis()
    if workers:
        for queue in worker_health.EXPECTED_QUEUES:
            await beat(r, queue, "vm:1", now=now)
    r.sets[default_queue_name] = {"j1": (now - oldest_age) * 1000}
    monkeypatch.setattr(worker_health.redis, "from_url", lambda *a, **k: r)
    status = await worker_health.worker_status()
    assert status["status"] == expected
    assert status["queues"][default_queue_name]["workers"] == workers
    assert r.closed


async def test_worker_status_is_unknown_when_redis_is_unreachable(monkeypatch):
    r = FakeRedis()
    r.zcount = AsyncMock(side_effect=ConnectionError("refused"))
    monkeypatch.setattr(worker_health.redis, "from_url", lambda *a, **k: r)
    assert await worker_health.worker_status() == {"status": "unknown", "queues": {}}


@pytest.mark.parametrize("worker, status", [("ok", "ok"), ("down", "degraded"), ("unknown", "degraded")])
async def test_health_is_degraded_unless_the_worker_is_ok(monkeypatch, worker, status):
    from src.main import app

    block = {"status": worker, "queues": {}}
    monkeypatch.setattr(router_mounts, "worker_status", AsyncMock(return_value=block))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")
    body = response.json()
    assert (response.status_code, body["status"], body["worker"]) == (200, status, block)


async def test_the_worker_beats_from_startup_and_leaves_on_shutdown(monkeypatch):
    from src.ai import worker

    monkeypatch.setattr(worker, "setup_tracing", lambda name: None)
    monkeypatch.setattr(worker, "shutdown_tracing", lambda: None)
    r = FakeRedis()
    ctx = {"redis": r}
    await worker.WorkerSettings.on_startup(ctx)
    await asyncio.sleep(0.01)
    members = r.sets[heartbeat_key(default_queue_name)]
    assert list(members) == [worker_health.worker_id()]
    await worker.WorkerSettings.on_shutdown(ctx)
    assert r.sets[heartbeat_key(default_queue_name)] == {}


async def test_a_failed_beat_does_not_stop_the_heartbeat(monkeypatch):
    calls = []

    async def flaky_beat(client, queue, member):
        calls.append(member)
        if len(calls) == 1:
            raise ConnectionError("redis blip")

    monkeypatch.setattr(worker_health, "beat", flaky_beat)
    monkeypatch.setattr(settings, "WORKER_HEARTBEAT_SECONDS", 0.01)
    task = asyncio.create_task(worker_health._heartbeat_forever(FakeRedis(), "arq:queue", "vm:1"))
    await asyncio.sleep(0.1)
    task.cancel()
    assert len(calls) >= 3
