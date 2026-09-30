"""Arq connection settings and enqueueing, built from ``settings.REDIS_URL``.

Every job producer and the worker take their Redis settings from here (SA-04,
SA-05). Before, three enqueue sites called ``RedisSettings()`` with no
arguments — arq's ``localhost:6379`` whatever ``REDIS_URL`` said — and the
worker and the campaign routes parsed ``REDIS_URL`` by hand, keeping host and
port and dropping the password, TLS and database index.
"""
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings
from arq.jobs import Job

from src.common.config import settings


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


async def enqueue_job(function: str, *args: Any, **kwargs: Any) -> Optional[Job]:
    """Enqueue one job. ``None`` means a job with the same ``_job_id`` already exists."""
    async with arq_pool() as pool:
        return await pool.enqueue_job(function, *args, **kwargs)
