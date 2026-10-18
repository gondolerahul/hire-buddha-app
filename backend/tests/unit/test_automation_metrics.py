"""Automation metrics (WS3 3.12): decisions by outcome, scheduler lag, held,
failed and unrouted events and open waits — and the scheduler serves them, which
is also its liveness probe."""
from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from src.automation import metrics

REPO = Path(__file__).resolve().parents[3]


def _value(metric, **labels):
    return metric.labels(**labels)._value.get() if labels else metric._value.get()


def test_decisions_are_counted_by_outcome():
    before = _value(metrics.FIRINGS, outcome="blocked_budget")
    metrics.firing("blocked_budget")
    assert _value(metrics.FIRINGS, outcome="blocked_budget") == before + 1


class _Result:
    def __init__(self, rows=None, scalar=None):
        self.rows, self.value = rows or [], scalar

    def all(self):
        return self.rows

    def scalar(self):
        return self.value


class _Session:
    def __init__(self, statuses, waiting):
        self.calls = [_Result(rows=statuses), _Result(scalar=waiting)]

    async def execute(self, _statement):
        return self.calls.pop(0)


@pytest.mark.asyncio
async def test_held_failed_and_waiting_are_summed_over_databases():
    def database(statuses, waiting):
        @asynccontextmanager
        async def open_session():
            yield _Session(statuses, waiting)
        return open_session

    sampled = await metrics.sample([database([("parked", 2), ("dead", 1)], 3),
                                    database([("dead", 4), ("received", 5)], 0)])
    assert sampled == {"received": 5, "parked": 2, "dead": 5, "waiting_runs": 3}
    assert _value(metrics.EVENTS, status="dead") == 5 and _value(metrics.WAITING_RUNS) == 3


def test_the_scheduler_serves_metrics_and_the_chart_probes_them():
    from src.automation import scheduler

    assert "SCHEDULER_METRICS_PORT" in inspect.getsource(scheduler._main)
    template = (REPO / "infra/k8s/charts/hb-platform/templates/scheduler.yaml").read_text(encoding="utf-8")
    assert "livenessProbe" in template and "metricsPort" in template
