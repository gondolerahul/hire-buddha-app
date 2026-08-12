"""Phase 11 Track 13 §7.2 chaos case — feature_flags table briefly unavailable.

When the table is unreachable (rolling deploy, network blip, DB
failover), every flag read MUST fall through to the env / code default
rather than raise. The worker keeps going; on-call sees a degraded
log line, not a 500.

This is the chaos counterpart to ``test_degraded_when_table_query_fails``
in the integration suite — same guarantee, dramatised by simulating a
realistic failure mode (a DB pool that has lost its connection).
"""
from __future__ import annotations

from typing import Any

import pytest


@pytest.mark.asyncio
async def test_pool_exhaustion_falls_through_to_default() -> None:
    """Simulate a connection-pool exhaustion: ``db.execute`` raises a
    SQLAlchemy ``InvalidRequestError``. FeatureFlags must catch it and
    return the code default."""
    from sqlalchemy.exc import InvalidRequestError
    from src.ai.core.feature_flags import (
        DEFAULTS, FeatureFlags, invalidate_process_cache,
    )

    class _ExhaustedPool:
        async def execute(self, *_a, **_k):
            raise InvalidRequestError("connection pool exhausted")

    invalidate_process_cache()
    ff = FeatureFlags(_ExhaustedPool())
    res = await ff.resolve("agent_loop.enabled")
    assert res.source == "default"
    assert res.value == DEFAULTS["agent_loop.enabled"]


@pytest.mark.asyncio
async def test_undefined_table_falls_through_to_default() -> None:
    """Simulate the table being entirely absent (a rolled-back migration
    or a fresh DB with the canary deploy ahead of the schema)."""
    from src.ai.core.feature_flags import (
        DEFAULTS, FeatureFlags, invalidate_process_cache,
    )

    class _MissingTable:
        async def execute(self, *_a, **_k):
            raise RuntimeError(
                'relation "feature_flags" does not exist'
            )

    invalidate_process_cache()
    ff = FeatureFlags(_MissingTable())
    res = await ff.resolve("critic_pipeline.v2_enabled")
    assert res.source == "default"
    assert res.value == DEFAULTS["critic_pipeline.v2_enabled"]


@pytest.mark.asyncio
async def test_dozens_of_flag_reads_under_chaos_do_not_raise() -> None:
    """Hot loop — every read against the broken pool must stay quiet."""
    from src.ai.core.feature_flags import (
        DEFAULTS, FeatureFlags, invalidate_process_cache,
    )

    class _Boom:
        async def execute(self, *_a, **_k):
            raise OSError("connection reset")

    invalidate_process_cache()
    ff = FeatureFlags(_Boom())
    sample = list(DEFAULTS.keys())[:25]
    # No exception escapes.
    results = [await ff.resolve(k) for k in sample]
    assert all(r.source in {"default", "env"} for r in results)
