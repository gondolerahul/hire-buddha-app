"""SA-04, SA-05: every arq connection is built from all of REDIS_URL.

Before, three enqueue sites in ai/service.py called ``RedisSettings()`` with no
arguments (arq's localhost:6379, whatever REDIS_URL said), and the worker and
the campaign routes parsed REDIS_URL by hand, keeping only host and port — a
``rediss://:secret@host:6380/2`` became a plaintext, passwordless connection to
database 0.
"""
import importlib
import re
from pathlib import Path

import pytest

from src.common import job_queue
from src.common.config import settings

DSN = "rediss://:secret@redis.internal:6380/2"
SRC = Path(__file__).resolve().parents[2] / "src"


def _assert_full_dsn(redis_settings) -> None:
    assert redis_settings.host == "redis.internal"
    assert redis_settings.port == 6380
    assert redis_settings.password == "secret"
    assert redis_settings.ssl is True
    assert redis_settings.database == 2


def test_helper_keeps_password_tls_and_database(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", DSN)
    _assert_full_dsn(job_queue.arq_redis_settings())


def test_worker_connects_with_the_whole_url(monkeypatch):
    import src.ai.worker as worker

    monkeypatch.setattr(settings, "REDIS_URL", DSN)
    try:
        reloaded = importlib.reload(worker)
        _assert_full_dsn(reloaded.WorkerSettings.redis_settings)
    finally:
        monkeypatch.undo()
        importlib.reload(worker)


async def test_enqueue_uses_the_configured_redis(monkeypatch):
    seen = {}

    class FakePool:
        async def enqueue_job(self, function, *args, **kwargs):
            seen["job"] = (function, args, kwargs)
            return "job"

        async def aclose(self):
            seen["closed"] = True

    async def fake_create_pool(redis_settings):
        seen["settings"] = redis_settings
        return FakePool()

    monkeypatch.setattr(settings, "REDIS_URL", DSN)
    monkeypatch.setattr(job_queue, "create_pool", fake_create_pool)

    assert await job_queue.enqueue_job("run_execution_recursive", "abc", _job_id="j1") == "job"
    _assert_full_dsn(seen["settings"])
    assert seen["job"] == ("run_execution_recursive", ("abc",), {"_job_id": "j1"})
    assert seen["closed"] is True


@pytest.mark.parametrize("pattern", [
    r"RedisSettings\(",                      # hand-built settings
    r"urlparse\([^)]*REDIS_URL",             # hand-parsed REDIS_URL
])
def test_no_arq_settings_are_built_outside_the_helper(pattern):
    offenders = [
        f"{path.relative_to(SRC)}:{number}"
        for path in SRC.rglob("*.py")
        if path.name != "job_queue.py"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(pattern, line)
    ]
    assert offenders == []
