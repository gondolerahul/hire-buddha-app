"""IN-20: each arq worker exposes Prometheus metrics — jobs, durations,
failures, what is running and the queue's backlog."""
from __future__ import annotations

import asyncio
import socket
import urllib.request
import uuid

import pytest
from prometheus_client import REGISTRY

from src.common import worker_health, worker_metrics
from src.common.telemetry import traced_job


def _sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


@pytest.mark.asyncio
async def test_a_job_is_counted_with_its_outcome_and_duration() -> None:
    name = f"in20_ok_{uuid.uuid4().hex[:6]}"

    async def job(ctx):
        assert _sample("hb_worker_jobs_in_progress", function=name) == 1
        return "done"

    job.__qualname__ = name
    assert await traced_job(job)({}) == "done"
    assert _sample("hb_worker_jobs_total", function=name, outcome="success") == 1
    assert _sample("hb_worker_job_duration_seconds_count", function=name) == 1
    assert _sample("hb_worker_jobs_in_progress", function=name) == 0


@pytest.mark.asyncio
async def test_a_failed_job_is_counted_as_a_failure_and_still_raises() -> None:
    name = f"in20_boom_{uuid.uuid4().hex[:6]}"

    async def job(ctx):
        raise RuntimeError("boom")

    job.__qualname__ = name
    with pytest.raises(RuntimeError):
        await traced_job(job)({})
    assert _sample("hb_worker_jobs_total", function=name, outcome="failure") == 1
    assert _sample("hb_worker_jobs_total", function=name, outcome="success") == 0
    assert _sample("hb_worker_jobs_in_progress", function=name) == 0


class _Pipe:
    def __init__(self):
        self.calls = []

    def zadd(self, *a):
        self.calls.append("zadd")

    def zremrangebyscore(self, *a):
        self.calls.append("zrem")

    async def execute(self):
        return []


class _Redis:
    def pipeline(self, transaction=False):
        return _Pipe()

    async def zcount(self, key, lo, hi):
        return 1 if key.startswith(worker_health.HEARTBEAT_KEY_PREFIX) else 4

    async def zrangebyscore(self, key, lo, hi, start=0, num=1, withscores=True):
        return [("job", float(hi) - 30_000)]          # due 30 s ago


@pytest.mark.asyncio
async def test_the_heartbeat_samples_the_queues_backlog(monkeypatch) -> None:
    queue = f"in20-queue-{uuid.uuid4().hex[:6]}"

    async def _stop(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(worker_health.asyncio, "sleep", _stop)
    with pytest.raises(asyncio.CancelledError):
        await worker_health._heartbeat_forever(_Redis(), queue, "host:1")
    assert _sample("hb_worker_queue_due_jobs", queue=queue) == 4
    assert _sample("hb_worker_queue_oldest_due_seconds", queue=queue) == 30


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_the_worker_serves_its_metrics() -> None:
    port = _free_port()
    assert worker_metrics.serve_metrics(port)
    body = urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5).read().decode()
    assert "hb_worker_jobs_total" in body and "hb_worker_queue_due_jobs" in body


def test_a_port_already_taken_is_logged_not_fatal(monkeypatch) -> None:
    """A second worker of the same kind on the host (on Windows the second bind
    succeeds — SO_REUSEADDR — so the refusal is simulated)."""
    def _taken(*_a, **_k):
        raise OSError("address already in use")

    monkeypatch.setattr(worker_metrics, "start_http_server", _taken)
    assert worker_metrics.serve_metrics(_free_port()) is False


def test_port_zero_serves_nothing() -> None:
    assert worker_metrics.serve_metrics(0) is False
