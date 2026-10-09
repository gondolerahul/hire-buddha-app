"""GH-14: every way a flag changes reaches every process.

The experimental-tool toggle upserted with raw SQL and announced nothing; a
change made with SQL had no way to be announced; the workers listened to
nothing. Each now goes through ``FeatureFlags.set`` / ``publish_invalidation``,
and each worker starts the listener.
"""
from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from src.ai.core import feature_flags as ff


class _DB:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_the_experimental_toggle_writes_through_set(monkeypatch):
    from src.ai.api import admin

    calls = []

    async def _set(self, flag_key, **kw):
        calls.append((flag_key, kw))

    monkeypatch.setattr(ff.FeatureFlags, "set", _set)
    company, db = uuid.uuid4(), _DB()
    user = SimpleNamespace(company_id=company, role="tenant_admin")
    out = await admin.toggle_experimental_tool("social_api", enabled=True, db=db, user=user)
    assert calls == [("tools.experimental.social_api", {"enabled": True, "company_id": company})]
    assert db.commits == 1 and out["enabled"] is True


@pytest.mark.asyncio
async def test_an_operator_can_announce_a_change_made_with_sql(monkeypatch):
    from src.ai.api import admin

    published = []

    class _Redis:
        async def publish(self, channel, body):
            published.append((channel, body))

    monkeypatch.setattr("src.common.redis_client.shared_redis", lambda: _Redis())
    ff._process_cache_put("bandit.enabled", None, None, ff._Resolution(True, "global", "bandit.enabled"))
    out = await admin.invalidate_feature_flags(flag_key=None, user=SimpleNamespace(role="app_admin"))
    assert out == {"invalidated": "*", "announced": True}
    assert not ff._PROCESS_CACHE                                    # this process too
    assert published and published[0][0] == ff._REDIS_INVALIDATION_CHANNEL


def test_only_app_admin_may_announce():
    from src.ai.api import admin
    from src.main import app

    route = next(r for r in app.routes if getattr(r, "path", "").endswith("/feature_flags/invalidate"))
    assert route.path == "/api/v1/ai/admin/feature_flags/invalidate"
    guard = next(d.call for d in route.dependant.dependencies if d.call.__class__.__name__ == "RoleChecker")
    assert list(guard.allowed_roles) == ["app_admin"]
    assert admin.invalidate_feature_flags


@pytest.mark.asyncio
@pytest.mark.parametrize("hook", ["startup", "child_startup"])
async def test_each_worker_listens_for_flag_changes(monkeypatch, hook):
    from src.ai import worker

    started = []

    async def _listen(url):
        started.append(url)
        await asyncio.sleep(3600)

    monkeypatch.setattr(ff, "listen_for_invalidations", _listen)
    monkeypatch.setattr(worker, "setup_tracing", lambda *_: None)
    monkeypatch.setattr(worker, "start_heartbeat", lambda *_: None)
    ctx: dict = {}
    await getattr(worker, hook)(ctx)
    await asyncio.sleep(0)
    assert started and isinstance(ctx["flag_listener"], asyncio.Task)

    async def _stop(_ctx):
        return None

    monkeypatch.setattr(worker, "stop_heartbeat", _stop)
    monkeypatch.setattr(worker, "shutdown_tracing", lambda: None)
    task = ctx["flag_listener"]
    await worker.shutdown(ctx)
    await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled() and "flag_listener" not in ctx
