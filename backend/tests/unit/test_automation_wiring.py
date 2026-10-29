"""The WS3 processes are wired everywhere they run: the event worker (queue
``events``) and the tenant scheduler, in the local service scripts, the image
and the Helm chart — automation silently stops if either is missing."""
from __future__ import annotations

import inspect
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _read(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


def test_the_event_worker_consumes_the_events_queue_and_sweeps():
    from src.ai.worker import EventWorkerSettings
    from src.common.job_queue import EVENT_QUEUE
    from src.common.worker_health import EXPECTED_QUEUES

    assert EventWorkerSettings.queue_name == EVENT_QUEUE == "events"
    names = {f.__qualname__ for f in EventWorkerSettings.functions}
    assert {"route_event", "release_parked", "automation_sweep", "prune_event_history",
            "redact_connector_data"} <= names
    assert [c.name for c in EventWorkerSettings.cron_jobs] == [
        "cron:automation_sweep", "cron:prune_event_history",
        # Connections, their providers' limits on what runs read (SH-E2), and pollers (WS5, WS3 3.13).
        "cron:connection_refresh", "cron:prune_unrouted_events", "cron:redact_connector_data", "cron:run_pollers"]
    assert EVENT_QUEUE in EXPECTED_QUEUES  # /api/v1/health reports a missing event worker


def test_nudges_and_resumes_go_to_the_events_queue():
    from src.automation import api, store

    assert "_queue_name=EVENT_QUEUE" in inspect.getsource(store.nudge)
    assert "_queue_name=EVENT_QUEUE" in inspect.getsource(api._release)


def test_the_scheduler_process_registers_every_mapper():
    # A trigger refers to its agent: without every model the first tick fails.
    from src.automation import scheduler

    assert "import_all_models()" in inspect.getsource(scheduler._main)


def test_the_service_scripts_start_and_stop_both():
    for name in ("start_services.ps1", "stop_services.ps1", "start_services.sh", "stop_services.sh"):
        text = _read(name)
        assert "EventWorkerSettings" in text and "src" in text and "automation" in text, name
        assert "scheduler" in text, name
    assert '"arq_event_worker"' in _read("start_services.ps1")
    assert "$LOG_DIR/arq_event_worker.log" in _read("start_services.sh")


def test_the_image_and_chart_run_both():
    dockerfile = _read("backend/Dockerfile")
    assert "FROM runtime AS event-worker" in dockerfile and "src.ai.worker.EventWorkerSettings" in dockerfile
    values = _read("infra/k8s/charts/hb-platform/values.yaml")
    assert "- name: event-worker" in values and "EVENT_WORKER_METRICS_PORT" in values
    assert "scheduler:\n  enabled: true" in values.replace("\r\n", "\n")
    assert "target: event-worker" in _read(".github/workflows/deploy-azure.yml")
