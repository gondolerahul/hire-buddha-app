"""Phase 11 Track 2 — FeatureFlags unit tests."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

from src.ai.core.feature_flags import DEFAULTS, FeatureFlags


@pytest.mark.asyncio
async def test_default_when_no_db_no_env() -> None:
    f = FeatureFlags(db=None)
    # A representative ON-by-default agent_loop.* flag.
    assert await f.is_on("agent_loop.snapshot_every_iteration") is True
    assert DEFAULTS["agent_loop.snapshot_every_iteration"] is True


@pytest.mark.asyncio
async def test_env_override_truthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_FLAG_AGENT_LOOP_SNAPSHOT_EVERY_ITERATION", "true")
    f = FeatureFlags(db=None)
    assert await f.is_on("agent_loop.snapshot_every_iteration") is True


@pytest.mark.asyncio
async def test_env_override_falsy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_FLAG_MEMORY_V2_CANONICAL", "no")
    f = FeatureFlags(db=None)
    assert await f.is_on("memory_v2.canonical") is False


@pytest.mark.asyncio
async def test_entity_override_flat_key_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_FLAG_AGENT_LOOP_SNAPSHOT_EVERY_ITERATION", raising=False)
    f = FeatureFlags(db=None)
    extras = {"feature_flags": {"agent_loop.snapshot_every_iteration": True}}
    assert await f.is_on("agent_loop.snapshot_every_iteration", entity_extras=extras) is True


@pytest.mark.asyncio
async def test_entity_override_namespaced_form(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_FLAG_AGENT_LOOP_SNAPSHOT_EVERY_ITERATION", raising=False)
    f = FeatureFlags(db=None)
    extras = {"feature_flags": {"agent_loop": {"snapshot_every_iteration": True}}}
    assert await f.is_on("agent_loop.snapshot_every_iteration", entity_extras=extras) is True


@pytest.mark.asyncio
async def test_resolve_returns_source() -> None:
    f = FeatureFlags(db=None)
    res = await f.resolve("agent_loop.snapshot_every_iteration")
    assert res.source == "default"
    assert res.value is DEFAULTS["agent_loop.snapshot_every_iteration"]


@pytest.mark.asyncio
async def test_db_lookup_safe_degraded_when_table_missing() -> None:
    """If the table doesn't exist (or any SQL error), the lookup MUST
    fall through to env + default rather than raising."""
    class _RaisingDB:
        async def execute(self, *args, **kwargs):
            raise RuntimeError("relation feature_flags does not exist")
    f = FeatureFlags(db=_RaisingDB())
    # Should not raise; falls through to the hard default.
    assert (
        await f.is_on("agent_loop.snapshot_every_iteration", company_id=uuid4())
        is DEFAULTS["agent_loop.snapshot_every_iteration"]
    )


@pytest.mark.asyncio
async def test_unknown_flag_returns_false() -> None:
    f = FeatureFlags(db=None)
    assert await f.is_on("totally.fake.flag") is False
