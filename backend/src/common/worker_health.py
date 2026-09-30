"""Worker heartbeat, and what /api/v1/health reports about the queues (SA-I4).

When the arq worker died the API kept accepting executions and every run sat
in PENDING with nothing reporting an error. Each worker now writes a heartbeat
into a per-queue sorted set (member ``host:pid``, score the time) every
``WORKER_HEARTBEAT_SECONDS``, from its own task: arq's own health key is only
written between jobs, so a worker with every slot busy on long runs would look
dead. The API counts the members seen in the last three intervals and reads
the queue itself — how many due jobs wait, and for how long — so a worker that
is alive but not taking jobs shows too.
"""
import asyncio
import logging
import os
import socket
import time
from typing import Any, Optional

import redis.asyncio as redis
from arq.constants import default_queue_name

from src.common.config import settings
from src.common.job_queue import CHILD_RUN_QUEUE

logger = logging.getLogger(__name__)

# The queues a worker must be consuming for the platform to work: top-level
# jobs, and child runs (SA-07), each with its own worker.
EXPECTED_QUEUES = (default_queue_name, CHILD_RUN_QUEUE)

HEARTBEAT_KEY_PREFIX = "hb:workers:"


def heartbeat_key(queue: str) -> str:
    return HEARTBEAT_KEY_PREFIX + queue


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _live_window() -> float:
    return 3 * settings.WORKER_HEARTBEAT_SECONDS


async def beat(client: Any, queue: str, member: str, now: Optional[float] = None) -> None:
    """Record ``member`` as alive on ``queue``; forget members silent for an hour."""
    now = time.time() if now is None else now
    pipe = client.pipeline(transaction=False)
    pipe.zadd(heartbeat_key(queue), {member: now})
    pipe.zremrangebyscore(heartbeat_key(queue), "-inf", now - 3600)
    await pipe.execute()


async def _heartbeat_forever(client: Any, queue: str, member: str) -> None:
    while True:
        try:
            await beat(client, queue, member)
        except Exception:  # Redis blips must not end the heartbeat
            logger.warning("worker heartbeat on %s failed", queue, exc_info=True)
        await asyncio.sleep(settings.WORKER_HEARTBEAT_SECONDS)


def start_heartbeat(ctx: dict, queue: str) -> None:
    """Start beating for ``queue`` on the worker's own Redis connection (on_startup)."""
    member = worker_id()
    task = asyncio.create_task(_heartbeat_forever(ctx["redis"], queue, member))
    ctx["heartbeat"] = (queue, member, task)


async def stop_heartbeat(ctx: dict) -> None:
    """Stop beating and leave the set at once, rather than aging out (on_shutdown)."""
    queue, member, task = ctx.pop("heartbeat", (None, None, None))
    if task is None:
        return
    task.cancel()
    try:
        await ctx["redis"].zrem(heartbeat_key(queue), member)
    except Exception:
        logger.warning("could not remove heartbeat for %s", member, exc_info=True)


async def queue_status(client: Any, queue: str, now: Optional[float] = None) -> dict:
    """Live workers on ``queue``, and how many due jobs wait there and for how long."""
    now = time.time() if now is None else now
    now_ms = now * 1000
    workers = await client.zcount(heartbeat_key(queue), now - _live_window(), "+inf")
    due = await client.zcount(queue, "-inf", now_ms)          # arq scores are ms
    oldest = await client.zrangebyscore(queue, "-inf", now_ms, start=0, num=1, withscores=True)
    oldest_due_seconds = round((now_ms - oldest[0][1]) / 1000) if oldest else 0
    return {"workers": workers, "due_jobs": due, "oldest_due_seconds": oldest_due_seconds}


async def worker_status() -> dict:
    """The ``worker`` block of /api/v1/health.

    ``status`` is ``down`` when an expected queue has no live worker,
    ``backlogged`` when a due job has waited longer than
    ``WORKER_BACKLOG_ALERT_SECONDS``, ``unknown`` when Redis cannot be read.
    """
    client = redis.from_url(settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1)
    try:
        queues = {queue: await queue_status(client, queue) for queue in EXPECTED_QUEUES}
    except Exception as exc:
        logger.warning("worker status unavailable: %s", exc)
        return {"status": "unknown", "queues": {}}
    finally:
        await client.aclose()
    if any(q["workers"] == 0 for q in queues.values()):
        status = "down"
    elif any(q["oldest_due_seconds"] > settings.WORKER_BACKLOG_ALERT_SECONDS for q in queues.values()):
        status = "backlogged"
    else:
        status = "ok"
    return {"status": status, "queues": queues}
