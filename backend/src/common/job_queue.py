"""Arq connection settings and enqueueing, built from ``settings.REDIS_URL``.

Every job producer and the worker take their Redis settings from here (SA-04,
SA-05). Before, three enqueue sites called ``RedisSettings()`` with no
arguments — arq's ``localhost:6379`` whatever ``REDIS_URL`` said — and the
worker and the campaign routes parsed ``REDIS_URL`` by hand, keeping host and
port and dropping the password, TLS and database index.

Enqueueing through here also leaves the caller's trace context in Redis
under the job id, so the worker's span for the job joins the trace of the
request that queued it (SA-10).

Child runs go on their own queue, ``CHILD_RUN_QUEUE``, consumed by a second
worker (``ai.worker.ChildWorkerSettings``), so a fan-out cannot take every job
slot the top-level runs need (SA-07).
"""
import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional
from uuid import uuid4

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings
from arq.jobs import Job

from src.common.config import settings
from src.common.telemetry import TRACE_KEY_TTL_SECONDS, current_trace_carrier, trace_key

CHILD_RUN_QUEUE = "children"


def arq_redis_settings() -> RedisSettings:
    """``REDIS_URL`` as arq settings: host, port, password, TLS and database index."""
    return RedisSettings.from_dsn(settings.REDIS_URL)


@asynccontextmanager
async def arq_pool() -> AsyncIterator[ArqRedis]:
    """A short-lived arq pool for enqueueing several jobs."""
    pool = await create_pool(arq_redis_settings())
    try:
        yield pool
    finally:
        await pool.aclose()


async def enqueue_on(pool: ArqRedis, function: str, *args: Any, **kwargs: Any) -> Optional[Job]:
    """Enqueue on an open pool. ``None`` means a job with the same ``_job_id`` already exists."""
    carrier = current_trace_carrier()
    if carrier:
        # arq's own default job id, chosen here so the trace can be keyed by it.
        job_id = kwargs.setdefault("_job_id", uuid4().hex)
        await pool.set(trace_key(job_id), json.dumps(carrier), ex=TRACE_KEY_TTL_SECONDS, nx=True)
    return await pool.enqueue_job(function, *args, **kwargs)


async def enqueue_job(function: str, *args: Any, **kwargs: Any) -> Optional[Job]:
    """Enqueue one job. ``None`` means a job with the same ``_job_id`` already exists."""
    async with arq_pool() as pool:
        return await enqueue_on(pool, function, *args, **kwargs)


async def enqueue_child_run(redis: Any, run_id: Any) -> Optional[Job]:
    """Queue a child run on ``CHILD_RUN_QUEUE``, in the current (parent's) trace.

    ``redis`` is any redis-py asyncio client; the job goes on the children
    queue whatever that client's default queue is.
    """
    pool = redis if isinstance(redis, ArqRedis) else ArqRedis(redis.connection_pool)
    return await enqueue_on(pool, "run_execution_recursive", str(run_id), _queue_name=CHILD_RUN_QUEUE)
