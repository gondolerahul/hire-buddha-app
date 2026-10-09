"""A run's frames on the local Redis: appended, capped, kept a day, read back
after an id, and a waiting reader woken by the next frame (GW-18)."""
from __future__ import annotations

import asyncio
import uuid

import pytest

from src.ai.core.run_stream import MAXLEN, publish_run_event, read_run_events, stream_key

pytestmark = pytest.mark.needs_db


@pytest.fixture
async def redis():
    import redis.asyncio as redis_lib

    from src.common.config import settings

    client = redis_lib.from_url(settings.REDIS_URL or "redis://localhost:6379")
    try:
        await client.ping()
    except Exception:
        pytest.skip("Redis is not reachable")
    yield client
    await client.aclose()


@pytest.fixture
async def run_id(redis):
    run = uuid.uuid4()
    yield run
    await redis.delete(stream_key(run))


@pytest.mark.asyncio
async def test_frames_are_read_back_after_an_id(redis, run_id):
    ids = [await publish_run_event(redis, run_id, {"type": "iteration_start", "iteration": n})
           for n in (1, 2, 3)]
    everything = await read_run_events(redis, run_id, "0-0")
    assert [i for i, _ in everything] == ids
    after_first = await read_run_events(redis, run_id, ids[0])
    assert [i for i, _ in after_first] == ids[1:]
    assert await read_run_events(redis, run_id, ids[-1]) == []
    assert 0 < await redis.ttl(stream_key(run_id)) <= 24 * 3600


@pytest.mark.asyncio
async def test_a_waiting_reader_is_woken_by_the_next_frame(redis, run_id):
    first = await publish_run_event(redis, run_id, {"type": "iteration_start", "iteration": 1})
    reader = asyncio.create_task(read_run_events(redis, run_id, first, block_ms=5000))
    await asyncio.sleep(0.2)
    second = await publish_run_event(redis, run_id, {"type": "run_end", "outcome": "COMPLETED"},
                                     terminal=True)
    frames = await asyncio.wait_for(reader, 5)
    assert [i for i, _ in frames] == [second]
    assert '"terminal": true' in frames[0][1]


@pytest.mark.asyncio
async def test_the_stream_is_capped(redis, run_id):
    for n in range(MAXLEN + 300):
        await publish_run_event(redis, run_id, {"type": "step_delta", "step": "s", "text": str(n)})
    length = await redis.xlen(stream_key(run_id))
    # Approximate trimming keeps at least MAXLEN and drops whole nodes past it.
    assert MAXLEN <= length < MAXLEN + 300
