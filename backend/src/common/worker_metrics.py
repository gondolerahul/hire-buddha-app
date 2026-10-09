"""Prometheus metrics for the arq workers (IN-20).

The worker is where every run executes, and it exposed no metrics: the API's
``/metrics`` counted HTTP requests, so a worker failing every job, or a queue
growing, showed nowhere a scrape could see. Each worker now serves its own
``/metrics`` on ``WORKER_METRICS_PORT`` (the child worker on
``CHILD_WORKER_METRICS_PORT``; 0 turns either off):

* ``hb_worker_jobs_total{function, outcome}`` — jobs finished, ``success`` or
  ``failure``, counted by ``telemetry.traced_job``, which wraps every job;
* ``hb_worker_job_duration_seconds{function}`` — how long each took;
* ``hb_worker_jobs_in_progress{function}`` — what is running now;
* ``hb_worker_queue_due_jobs{queue}`` / ``hb_worker_queue_oldest_due_seconds{queue}``
  — the backlog, sampled by the heartbeat (``worker_health``).
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator

from prometheus_client import Counter, Gauge, Histogram, start_http_server

logger = logging.getLogger(__name__)

JOBS = Counter("hb_worker_jobs_total", "arq jobs finished", ["function", "outcome"])
DURATION = Histogram(
    "hb_worker_job_duration_seconds", "arq job duration", ["function"],
    buckets=(0.1, 0.5, 1, 5, 15, 60, 300, 900, 1800, 3600, 7200),
)
IN_PROGRESS = Gauge("hb_worker_jobs_in_progress", "arq jobs running", ["function"])
DUE_JOBS = Gauge("hb_worker_queue_due_jobs", "jobs due on the queue and not yet taken", ["queue"])
OLDEST_DUE = Gauge("hb_worker_queue_oldest_due_seconds", "how long the oldest due job has waited", ["queue"])


@contextmanager
def observe_job(function: str) -> Iterator[None]:
    """Count one job: in progress while it runs, then its outcome and duration."""
    started = time.monotonic()
    IN_PROGRESS.labels(function).inc()
    outcome = "failure"
    try:
        yield
        outcome = "success"
    finally:
        IN_PROGRESS.labels(function).dec()
        JOBS.labels(function, outcome).inc()
        DURATION.labels(function).observe(time.monotonic() - started)


def record_queue(queue: str, due_jobs: int, oldest_due_seconds: float) -> None:
    DUE_JOBS.labels(queue).set(due_jobs)
    OLDEST_DUE.labels(queue).set(oldest_due_seconds)


def serve_metrics(port: int, addr: str = "127.0.0.1") -> bool:
    """Serve ``/metrics`` on ``addr:port`` (port 0: off). A port already taken —
    a second worker of the same kind on the host — is logged, not fatal."""
    if not port:
        return False
    try:
        start_http_server(port, addr=addr)
    except OSError as exc:
        logger.warning("worker metrics not served on port %s: %s", port, exc)
        return False
    logger.info("worker metrics on :%s/metrics", port)
    return True
