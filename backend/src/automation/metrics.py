"""Automation's Prometheus metrics (plan WS3 3.12), next to the workers' own
(``common/worker_metrics``; the router's backlog is the ``events`` queue there):

* ``hb_automation_firings_total{outcome}`` — trigger decisions (started, queued,
  skipped_*, blocked_*, failed), counted by the router;
* ``hb_automation_scheduler_lag_seconds`` — how late a due trigger or wait was
  when the scheduler fired it;
* ``hb_automation_scheduler_ticks_total{outcome}`` — scheduler passes, ``ok`` or ``error``;
* ``hb_automation_events{status}`` — events held (``parked``), failed (``dead``)
  or not yet routed (``received``), and ``hb_automation_waiting_runs``, sampled
  by the event worker's sweep.

The event worker serves them on its ``/metrics``; the scheduler on
``SCHEDULER_METRICS_PORT``.
"""
from __future__ import annotations

from typing import Any, Dict

from prometheus_client import Counter, Gauge, Histogram
from sqlalchemy import func, select

FIRINGS = Counter("hb_automation_firings_total", "trigger decisions by outcome", ["outcome"])
SCHEDULER_LAG = Histogram("hb_automation_scheduler_lag_seconds", "how late a due item was when fired",
                          buckets=(0.5, 1, 5, 10, 30, 60, 300, 900, 3600, 86400))
SCHEDULER_TICKS = Counter("hb_automation_scheduler_ticks_total", "scheduler passes", ["outcome"])
EVENTS = Gauge("hb_automation_events", "events by status (sampled)", ["status"])
WAITING_RUNS = Gauge("hb_automation_waiting_runs", "runs waiting for an event (sampled)")

SAMPLED = ("received", "parked", "dead")


def firing(outcome: str) -> None:
    FIRINGS.labels(outcome).inc()


def lag(seconds: float) -> None:
    SCHEDULER_LAG.observe(max(0.0, seconds))


async def sample(databases: Any) -> Dict[str, int]:
    """Count held, failed and unrouted events and open waits across ``databases``
    (async context managers yielding sessions); sets the gauges."""
    from src.automation.models import Event, Wait

    totals = {status: 0 for status in SAMPLED}
    waiting = 0
    for open_session in databases:
        async with open_session() as db:
            for status, count in (await db.execute(select(Event.status, func.count()).where(
                    Event.status.in_(SAMPLED)).group_by(Event.status))).all():
                totals[status] += count
            waiting += (await db.execute(select(func.count()).select_from(Wait).where(
                Wait.status == "waiting"))).scalar() or 0
    for status, count in totals.items():
        EVENTS.labels(status).set(count)
    WAITING_RUNS.set(waiting)
    return {**totals, "waiting_runs": waiting}
