"""GW-18: a run's stream replays what a client missed.

The run page's frames went out on Redis pub/sub: no ``id:``, no buffer, so a
reconnecting ``EventSource`` lost everything published while it was away and
the page polled every 3 s to make up for it. Frames are now appended to a Redis
stream per run (``XADD … MAXLEN ~ 1000``); the endpoint sends each with its
stream id and resumes after ``Last-Event-ID`` (header or ``?last_event_id=``).
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.ai.core.run_stream import MAXLEN, TTL_SECONDS, publish_run_event, start_id, stream_key
from tests.harness.run_stream import FakeStreamRedis


async def _open(monkeypatch, redis, run_id, *, header=None, query=None, status="RUNNING"):
    """The endpoint's SSE records as (id, frame) pairs; comments as ('#', text)."""
    from src.ai import router as ai_router

    class _Service:
        def __init__(self, db):
            pass

        async def get_execution(self, *args, **kwargs):
            return None

    statuses = iter(status if isinstance(status, list) else [status] * 100)

    async def _stored(_run_id):
        return next(statuses)

    monkeypatch.setattr(ai_router, "AIService", _Service)
    monkeypatch.setattr(ai_router, "_stored_run_status", _stored)
    monkeypatch.setattr("redis.asyncio.from_url", lambda *a, **k: redis)
    headers = {"last-event-id": header} if header else {}
    user = SimpleNamespace(company_id=uuid4(), role="admin")
    response = await ai_router.stream_execution(run_id, request=SimpleNamespace(headers=headers),
                                                last_event_id=query, db=None, current_user=user)
    records = []
    async for chunk in response.body_iterator:
        text = chunk if isinstance(chunk, str) else chunk.decode()
        for record in text.split("\n\n"):
            if not record:
                continue
            if record.startswith(":"):
                records.append(("#", record[1:].strip()))
                continue
            fields = dict(line.split(": ", 1) for line in record.split("\n"))
            records.append((fields.get("id"), json.loads(fields["data"])))
    return records


def _frames(records):
    return [(i, f) for i, f in records if i != "#" and f.get("status") != "connected"]


@pytest.mark.asyncio
async def test_publishing_appends_to_a_capped_stream_that_expires():
    redis, run_id = FakeStreamRedis(), uuid4()
    entry = await publish_run_event(redis, run_id, {"type": "iteration_start", "iteration": 1})
    key = stream_key(run_id)
    assert [i for i, _ in redis.entries[key]] == [entry]
    assert redis.maxlen[key] == (MAXLEN, True)
    assert redis.ttl[key] == TTL_SECONDS


@pytest.mark.asyncio
async def test_every_frame_carries_its_stream_id(monkeypatch):
    redis, run_id = FakeStreamRedis(), uuid4()
    ids = [redis.add(stream_key(run_id), {"type": "iteration_start", "iteration": 1}),
           redis.add(stream_key(run_id), {"type": "run_end", "outcome": "COMPLETED", "terminal": True})]
    frames = _frames(await _open(monkeypatch, redis, run_id))
    assert [i for i, _ in frames] == ids


@pytest.mark.asyncio
@pytest.mark.parametrize("via", ["header", "query"])
async def test_a_reconnect_gets_what_came_after_its_last_frame(monkeypatch, via):
    redis, run_id = FakeStreamRedis(), uuid4()
    key = stream_key(run_id)
    seen = redis.add(key, {"type": "iteration_start", "iteration": 1})
    redis.add(key, {"type": "iteration_end", "iteration": 1})   # sent while the client was away
    redis.add(key, {"type": "run_end", "outcome": "COMPLETED", "terminal": True})
    kwargs = {"header": seen} if via == "header" else {"query": seen}
    frames = _frames(await _open(monkeypatch, redis, run_id, **kwargs))
    assert [f["type"] for _, f in frames] == ["iteration_end", "run_end"]


@pytest.mark.asyncio
async def test_a_stream_opened_mid_run_starts_from_the_first_frame(monkeypatch):
    redis, run_id = FakeStreamRedis(), uuid4()
    key = stream_key(run_id)
    redis.add(key, {"type": "task_class_classified", "task_class": "research"})
    redis.add(key, {"type": "run_end", "outcome": "FAILED", "terminal": True})
    frames = _frames(await _open(monkeypatch, redis, run_id))
    assert [f["type"] for _, f in frames] == ["task_class_classified", "run_end"]


@pytest.mark.asyncio
async def test_a_finished_run_with_no_frames_left_ends_at_once(monkeypatch):
    """Its frames expired: the stream ends with the stored status, without waiting."""
    redis, run_id = FakeStreamRedis(), uuid4()
    records = await _open(monkeypatch, redis, run_id, status="PARTIAL_COMPLETE")
    assert _frames(records) == [(None, {"type": "run_end", "outcome": "PARTIAL_COMPLETE", "terminal": True})]
    assert redis.blocks == [None]  # one read, and it did not wait


@pytest.mark.asyncio
async def test_an_idle_stream_keeps_alive_until_the_run_publishes(monkeypatch):
    redis, run_id = FakeStreamRedis(), uuid4()
    waits = []

    def _publish_on_second_wait():
        waits.append(1)
        if len(waits) == 2:
            redis.add(stream_key(run_id), {"type": "run_end", "outcome": "COMPLETED", "terminal": True})

    redis.on_block = _publish_on_second_wait
    records = await _open(monkeypatch, redis, run_id)
    assert ("#", "keep-alive") in records
    assert [f["type"] for _, f in _frames(records)] == ["run_end"]


def test_a_garbled_last_event_id_replays_from_the_start():
    assert start_id(None) == "0-0"
    assert start_id("1700000000001-0") == "1700000000001-0"
    assert start_id("not-an-id") == "0-0"
