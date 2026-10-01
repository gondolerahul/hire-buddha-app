"""SA-07: child runs have their own queue and their own worker.

CHILD_RUN_QUEUE was declared with a comment saying "NOT routed yet": every
child run went on the default queue, so a fan-out could take every job slot
top-level runs, documents and events needed. (The per-parent bound,
governance.max_concurrent_children, caps a parent's batch — AK-07.)
"""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from arq import ArqRedis
from arq.constants import default_queue_name

from src.ai.schemas import StepType
from src.common import job_queue, worker_health
from src.common.config import settings
from src.common.job_queue import CHILD_RUN_QUEUE, enqueue_child_run

REPO = Path(__file__).resolve().parents[3]


class RecordingArqRedis:
    """Stands in for the ArqRedis enqueue_child_run builds from a plain client."""
    jobs: list = []

    def __init__(self, pool):
        self.pool = pool

    async def enqueue_job(self, function, *args, **kwargs):
        RecordingArqRedis.jobs.append((function, args, kwargs.get("_queue_name")))


@pytest.fixture
def recorded(monkeypatch):
    RecordingArqRedis.jobs = []
    monkeypatch.setattr(job_queue, "ArqRedis", RecordingArqRedis)
    return RecordingArqRedis.jobs


async def test_a_child_run_goes_on_the_child_queue(recorded):
    run_id = uuid4()
    await enqueue_child_run(SimpleNamespace(connection_pool=object()), run_id)
    assert recorded == [("run_execution_recursive", (str(run_id),), CHILD_RUN_QUEUE)]


async def test_an_arq_pool_is_used_as_is_and_its_default_queue_ignored():
    pool = ArqRedis(default_queue_name="somewhere-else")
    pool.enqueue_job = AsyncMock()
    await enqueue_child_run(pool, "run-1")
    assert pool.enqueue_job.call_args.kwargs["_queue_name"] == CHILD_RUN_QUEUE
    await pool.aclose()


async def test_a_cortex_recurse_child_is_enqueued_on_the_child_queue(recorded):
    """It used to build ArqRedis from the client's .client method and raise every time."""
    from src.ai.memory.cortex_bridge import CortexBridge

    child_run_id, node_id = uuid4(), uuid4()
    cortex = SimpleNamespace(recurse=AsyncMock(return_value=(uuid4(), child_run_id)))
    bridge = CortexBridge(db=None, company_id=uuid4(), redis=SimpleNamespace(connection_pool=object()))
    step = SimpleNamespace(type=StepType.RECURSE, name="sub", step_id="s1", description="research",
                           target=SimpleNamespace(node_id=node_id, result_slot="sub"))
    result = await bridge.execute_cortex_step(SimpleNamespace(id=uuid4()), None, step, cortex, None, {})

    assert json.loads(result["output"])["child_run_id"] == str(child_run_id)
    assert recorded == [("run_execution_recursive", (str(child_run_id),), CHILD_RUN_QUEUE)]


def test_the_child_worker_consumes_the_child_queue_only():
    from src.ai.worker import ChildWorkerSettings, WorkerSettings

    assert ChildWorkerSettings.queue_name == CHILD_RUN_QUEUE
    assert getattr(WorkerSettings, "queue_name", default_queue_name) == default_queue_name
    assert "run_execution_recursive" in {f.__qualname__ for f in ChildWorkerSettings.functions}
    assert not getattr(ChildWorkerSettings, "cron_jobs", None)      # crons run once, on the main worker
    assert ChildWorkerSettings.max_jobs == settings.CHILD_WORKER_MAX_JOBS


async def test_the_child_worker_beats_for_the_child_queue(monkeypatch):
    from src.ai import worker

    monkeypatch.setattr(worker, "setup_tracing", lambda name: None)
    beats = []
    monkeypatch.setattr(worker, "start_heartbeat", lambda ctx, queue: beats.append(queue))
    await worker.ChildWorkerSettings.on_startup({})
    assert beats == [CHILD_RUN_QUEUE]


async def test_health_is_down_without_a_child_worker(monkeypatch):
    live = {default_queue_name: 1, CHILD_RUN_QUEUE: 0}

    async def queue_status(client, queue, now=None):
        return {"workers": live[queue], "due_jobs": 0, "oldest_due_seconds": 0}

    monkeypatch.setattr(worker_health, "queue_status", queue_status)
    monkeypatch.setattr(worker_health.redis, "from_url", lambda *a, **k: SimpleNamespace(aclose=AsyncMock()))
    status = await worker_health.worker_status()
    assert (status["status"], set(status["queues"])) == ("down", {default_queue_name, CHILD_RUN_QUEUE})


def test_the_service_scripts_start_and_stop_the_child_worker():
    start = (REPO / "start_services.sh").read_text(encoding="utf-8")
    stop = (REPO / "stop_services.sh").read_text(encoding="utf-8")
    assert "-m arq src.ai.worker.ChildWorkerSettings" in start
    assert 'pkill -f "arq src.ai.worker.ChildWorkerSettings"' in stop


def test_no_child_run_is_enqueued_on_the_default_queue():
    for path in ("src/ai/core/executors/child_entity.py", "src/ai/memory/cortex_bridge.py"):
        source = (REPO / "backend" / path).read_text(encoding="utf-8")
        assert 'enqueue_job("run_execution_recursive"' not in source, path
        assert "enqueue_child_run(" in source, path
