"""IN-23: spans are exported only to a configured collector, and an absent one
costs a batch one bounded attempt — not a minute of retries."""
from __future__ import annotations

import time

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExportResult

from src.common import telemetry


@pytest.fixture
def installed(monkeypatch):
    providers: list = []
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", providers.append)
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    return providers


def _processors(provider: TracerProvider) -> list:
    return list(provider._active_span_processor._span_processors)


def test_no_endpoint_no_exporter(installed) -> None:
    telemetry.setup_tracing("svc")
    [provider] = installed
    assert _processors(provider) == []


def test_an_endpoint_gets_the_bounded_exporter(installed, monkeypatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
    telemetry.setup_tracing("svc")
    [processor] = _processors(installed[0])
    assert isinstance(processor, BatchSpanProcessor)
    assert isinstance(processor.span_exporter, telemetry.BoundedOTLPSpanExporter)
    processor.span_exporter.shutdown()


def test_sdk_disabled_installs_nothing(installed, monkeypatch) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
    telemetry.setup_tracing("svc")
    assert installed == []


def test_an_unreachable_collector_fails_the_batch_at_once() -> None:
    from opentelemetry.sdk.trace import TracerProvider as _TP

    span = _TP().get_tracer("t").start_span("s")
    span.end()
    exporter = telemetry.BoundedOTLPSpanExporter(
        endpoint="http://127.0.0.1:1", insecure=True, timeout=telemetry.OTLP_TIMEOUT_SECONDS,
    )
    started = time.monotonic()
    assert exporter.export([span]) == SpanExportResult.FAILURE
    assert time.monotonic() - started < telemetry.OTLP_TIMEOUT_SECONDS + 1
    exporter.shutdown()
