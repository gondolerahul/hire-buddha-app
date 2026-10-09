import functools
import json
import logging
import os
from typing import Any, Awaitable, Callable

from grpc import RpcError
from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import make_asgi_app
from fastapi import FastAPI

logger = logging.getLogger(__name__)

# OpenTelemetry exclusion pattern matching every WebSocket scope's URL.
WEBSOCKET_URLS = "^wss?://"

# A job's producer leaves its trace context in Redis under the job id, and
# traced_job() picks it up in the worker (SA-10). Out of band rather than a job
# argument, so a worker started before this change still runs the job.
TRACE_KEY_PREFIX = "hb:trace:"
TRACE_KEY_TTL_SECONDS = 86400

# An unreachable collector costs a batch at most this long, not a minute of
# backoff (IN-23).
OTLP_TIMEOUT_SECONDS = 2


class BoundedOTLPSpanExporter(OTLPSpanExporter):
    """One export attempt per batch, bounded by the exporter's timeout.

    The 1.22 exporter retries an unavailable collector with backoff up to a
    hard-coded 64 s, holding its lock — and a process's shutdown waits on that
    lock (IN-23). A span batch is not worth a minute: a failed one is dropped
    with one warning.
    """

    def _export(self, data):  # type: ignore[override]
        if self._shutdown:
            return self._result.FAILURE
        with self._export_lock:
            try:
                self._client.Export(
                    request=self._translate_data(data), metadata=self._headers, timeout=self._timeout,
                )
                return self._result.SUCCESS
            except RpcError as error:
                logger.warning("Span export to %s failed (%s); batch dropped", self._endpoint, error.code())
                return self._result.FAILURE


def _sdk_disabled() -> bool:
    return os.getenv("OTEL_SDK_DISABLED", "").strip().lower() == "true"


def setup_tracing(service_name: str) -> None:
    """Install the process-wide tracer provider, exporting spans over OTLP
    only when ``OTEL_EXPORTER_OTLP_ENDPOINT`` names a collector (IN-23).

    With no endpoint the spans are made (trace context still crosses into
    jobs) and dropped; there is no exporter retrying an absent ``:4317``
    for a minute on every reload and shutdown. ``OTEL_SDK_DISABLED=true``
    installs nothing.
    """
    if _sdk_disabled():
        return
    provider = TracerProvider(resource=Resource.create(attributes={"service.name": service_name}))
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if otlp_endpoint:
        exporter = BoundedOTLPSpanExporter(endpoint=otlp_endpoint, insecure=True, timeout=OTLP_TIMEOUT_SECONDS)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def shutdown_tracing() -> None:
    """Flush buffered spans; the worker calls this on shutdown."""
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.shutdown()


def setup_telemetry(app: FastAPI):
    setup_tracing("hirebuddha-backend")

    # Instrument FastAPI — HTTP only. WebSocket scopes (ws:// / wss:// URLs)
    # are excluded: the ASGI instrumentation opens a child span per message,
    # which on a call's audio stream is ~100 spans a second for its whole length.
    FastAPIInstrumentor.instrument_app(app, excluded_urls=WEBSOCKET_URLS)

    # Add Prometheus metrics endpoint
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)


def current_trace_carrier() -> dict[str, str]:
    """The current trace context as W3C headers; empty outside a span."""
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier


def trace_key(job_id: str) -> str:
    return TRACE_KEY_PREFIX + job_id


async def _producer_context(ctx: dict):
    """The trace context the job's producer left in Redis, if any."""
    redis, job_id = ctx.get("redis"), ctx.get("job_id")
    if redis is None or not job_id:
        return None
    try:
        raw = await redis.get(trace_key(job_id))
        return propagate.extract(json.loads(raw)) if raw else None
    except Exception:  # tracing never fails a job
        logger.debug("trace context for job %s unreadable", job_id, exc_info=True)
        return None


def _job_tracer() -> trace.Tracer:
    return trace.get_tracer(__name__)


def traced_job(job: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Run an arq job (or cron) inside a span, continuing its producer's trace.

    The wrapper keeps the job's name, so arq registers it — and cron ids and
    enqueue-by-name keep working — exactly as before.
    """
    @functools.wraps(job)
    async def run(ctx: dict, *args: Any, **kwargs: Any) -> Any:
        attributes = {"messaging.system": "arq", "arq.function": job.__qualname__}
        if "job_id" in ctx:
            attributes.update({"arq.job_id": ctx["job_id"], "arq.job_try": ctx.get("job_try", 1)})
        with _job_tracer().start_as_current_span(
            f"arq {job.__qualname__}", context=await _producer_context(ctx),
            kind=trace.SpanKind.CONSUMER, attributes=attributes,
        ):
            return await job(ctx, *args, **kwargs)

    return run
