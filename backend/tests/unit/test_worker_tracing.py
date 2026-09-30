"""SA-10: the worker reports traces, joined to the request that queued the job.

setup_telemetry was called by the API only, so the process that runs every
agent execution, document embed and cron emitted no spans at all.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.common import job_queue, telemetry
from src.common.telemetry import current_trace_carrier, trace_key, traced_job

received: dict = {}


async def process_gateway_event(ctx, envelope):
    received["envelope"] = envelope
    return "done"


async def process_document(ctx):
    raise RuntimeError("embed failed")


class FakeRedis:
    def __init__(self, values=None):
        self.values = dict(values or {})

    async def get(self, key):
        return self.values.get(key)


@pytest.fixture
def provider(monkeypatch):
    provider = TracerProvider()
    provider.exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(provider.exporter))
    monkeypatch.setattr(telemetry, "_job_tracer", lambda: provider.get_tracer("test"))
    return provider


def _job_spans(provider):
    return [s for s in provider.exporter.get_finished_spans() if s.name.startswith("arq ")]


async def test_a_job_runs_in_a_span_that_continues_the_producers_trace(provider):
    with provider.get_tracer("api").start_as_current_span("POST /webhooks/inbound") as request:
        carrier = current_trace_carrier()
    redis = FakeRedis({trace_key("j1"): json.dumps(carrier)})

    job = traced_job(process_gateway_event)
    assert await job({"redis": redis, "job_id": "j1", "job_try": 2}, {"a": 1}) == "done"

    assert received["envelope"] == {"a": 1}
    [span] = _job_spans(provider)
    assert span.name == "arq process_gateway_event"
    assert span.kind == trace.SpanKind.CONSUMER
    assert span.context.trace_id == request.get_span_context().trace_id
    assert span.parent.span_id == request.get_span_context().span_id
    assert (span.attributes["arq.job_id"], span.attributes["arq.job_try"]) == ("j1", 2)


async def test_a_failing_job_is_an_error_span_and_still_raises(provider):
    with pytest.raises(RuntimeError):
        await traced_job(process_document)({"redis": FakeRedis(), "job_id": "j2"})
    [span] = _job_spans(provider)
    assert span.status.status_code == trace.StatusCode.ERROR
    assert span.parent is None                                  # queued outside any trace


async def test_an_unreadable_trace_key_does_not_fail_the_job(provider):
    redis = MagicMock(get=AsyncMock(side_effect=ConnectionError("redis gone")))
    received.clear()
    await traced_job(process_gateway_event)({"redis": redis, "job_id": "j3"}, {"b": 2})
    assert received["envelope"] == {"b": 2}
    assert _job_spans(provider)[0].parent is None


async def test_enqueue_leaves_the_callers_trace_under_the_job_id(monkeypatch, provider):
    pool = MagicMock(enqueue_job=AsyncMock(return_value="job"), set=AsyncMock(), aclose=AsyncMock())
    monkeypatch.setattr(job_queue, "create_pool", AsyncMock(return_value=pool))

    with provider.get_tracer("api").start_as_current_span("POST /api/v1/executions") as request:
        await job_queue.enqueue_job("run_execution_recursive", "run-1")

    (function, run_id), kwargs = pool.enqueue_job.call_args
    assert (function, run_id) == ("run_execution_recursive", "run-1")
    assert set(kwargs) == {"_job_id"}          # nothing a pre-SA-10 worker would choke on
    (key, value), options = pool.set.call_args
    assert key == trace_key(kwargs["_job_id"])
    assert format(request.get_span_context().trace_id, "032x") in json.loads(value)["traceparent"]
    assert options == {"ex": telemetry.TRACE_KEY_TTL_SECONDS, "nx": True}


async def test_outside_a_span_enqueue_is_unchanged(monkeypatch):
    pool = MagicMock(enqueue_job=AsyncMock(return_value="job"), set=AsyncMock(), aclose=AsyncMock())
    monkeypatch.setattr(job_queue, "create_pool", AsyncMock(return_value=pool))
    await job_queue.enqueue_job("process_document", "doc-1", _job_id="doc-1")
    pool.set.assert_not_called()
    assert pool.enqueue_job.call_args.kwargs == {"_job_id": "doc-1"}


def test_every_job_and_cron_is_registered_traced():
    from src.ai.worker import WorkerSettings

    untraced = [f.__name__ for f in WorkerSettings.functions if not hasattr(f, "__wrapped__")]
    untraced += [c.name for c in WorkerSettings.cron_jobs if not hasattr(c.coroutine, "__wrapped__")]
    assert untraced == []
    # arq names jobs by __qualname__: the wrapper must not rename them.
    assert "run_execution_recursive" in {f.__qualname__ for f in WorkerSettings.functions}
    assert "cron:kpi_rollup_refresh" in {c.name for c in WorkerSettings.cron_jobs}


async def test_the_worker_installs_its_own_tracer_provider(monkeypatch):
    from src.ai import worker

    calls = []
    monkeypatch.setattr(worker, "setup_tracing", calls.append)
    await worker.WorkerSettings.on_startup({})
    assert calls == ["hirebuddha-worker"]
