"""Phase 11 Track 14 — feature_flags table integration tests.

Validates the end-to-end behaviour of the FeatureFlags service against
the live ``feature_flags`` table created by ``p11t02_feature_flags``:

  * ``set`` upsert at all three scope tiers (global / company / entity).
  * Resolution chain (entity → company → global → default).
  * ``get_float`` returns ``value_json`` at the right tier.
  * ``delete`` removes the row at the exact scope only.
  * Graceful degrade when the table is unreachable (chaos case for the
    "table briefly unavailable" scenario in Track 13 §7.2).
"""
from __future__ import annotations

import uuid

import pytest


pytestmark = pytest.mark.needs_db


async def test_set_get_global_scope(db) -> None:
    from src.ai.core.feature_flags import FeatureFlags, invalidate_process_cache
    flag = f"itest.global.{uuid.uuid4().hex[:8]}"
    invalidate_process_cache()
    ff = FeatureFlags(db)
    await ff.set(flag, enabled=True)
    res = await ff.resolve(flag)
    assert res.value is True
    assert res.source == "global"


async def test_company_overrides_global(db, test_company_id) -> None:
    from src.ai.core.feature_flags import FeatureFlags, invalidate_process_cache
    flag = f"itest.company.{uuid.uuid4().hex[:8]}"
    invalidate_process_cache()
    ff = FeatureFlags(db)
    await ff.set(flag, enabled=True)                          # global = ON
    await ff.set(flag, enabled=False, company_id=test_company_id)  # company = OFF

    res = await ff.resolve(flag, company_id=test_company_id)
    assert res.source == "company"
    assert res.value is False

    res = await ff.resolve(flag)                               # no company → global
    assert res.source == "global"
    assert res.value is True


async def test_entity_overrides_company(db, test_company_id) -> None:
    from src.ai.core.feature_flags import FeatureFlags, invalidate_process_cache
    flag = f"itest.entity.{uuid.uuid4().hex[:8]}"
    entity_id = uuid.uuid4()
    invalidate_process_cache()
    ff = FeatureFlags(db)
    await ff.set(flag, enabled=False, company_id=test_company_id)
    await ff.set(
        flag, enabled=True,
        company_id=test_company_id, entity_id=entity_id,
    )

    res = await ff.resolve(
        flag, company_id=test_company_id, entity_id=entity_id,
    )
    assert res.source == "entity_row"
    assert res.value is True


async def test_get_float_reads_value_json(db, test_company_id) -> None:
    from src.ai.core.feature_flags import FeatureFlags, invalidate_process_cache
    flag = f"itest.float.{uuid.uuid4().hex[:8]}"
    invalidate_process_cache()
    ff = FeatureFlags(db)
    await ff.set(flag, value_json=0.42, company_id=test_company_id)
    v = await ff.get_float(flag, company_id=test_company_id)
    assert v == pytest.approx(0.42)


async def test_delete_scope_isolated(db, test_company_id) -> None:
    """Delete at company scope must not touch the global row."""
    from src.ai.core.feature_flags import FeatureFlags, invalidate_process_cache
    flag = f"itest.del.{uuid.uuid4().hex[:8]}"
    invalidate_process_cache()
    ff = FeatureFlags(db)
    await ff.set(flag, enabled=True)
    await ff.set(flag, enabled=False, company_id=test_company_id)

    deleted = await ff.delete(flag, company_id=test_company_id)
    assert deleted is True

    res = await ff.resolve(flag, company_id=test_company_id)
    # Falls back to the global row.
    assert res.source == "global"
    assert res.value is True


async def test_process_cache_hits_within_ttl(db, test_company_id, monkeypatch) -> None:
    from src.ai.core import feature_flags as ff_mod
    from src.ai.core.feature_flags import FeatureFlags, invalidate_process_cache
    flag = f"itest.cache.{uuid.uuid4().hex[:8]}"
    invalidate_process_cache()
    ff = FeatureFlags(db)
    await ff.set(flag, enabled=True, company_id=test_company_id)

    calls = {"n": 0}
    real_lookup = FeatureFlags._db_lookup

    async def counting_lookup(self, flag_key, company_id, entity_id=None):
        if flag_key == flag:
            calls["n"] += 1
        return await real_lookup(self, flag_key, company_id, entity_id)

    monkeypatch.setattr(FeatureFlags, "_db_lookup", counting_lookup)
    # Hit it three times — only the first should go to DB.
    for _ in range(3):
        await ff.resolve(flag, company_id=test_company_id)
    assert calls["n"] == 1, "process cache should serve subsequent reads"

    invalidate_process_cache(flag)
    await ff.resolve(flag, company_id=test_company_id)
    assert calls["n"] == 2


async def test_degraded_when_table_query_fails(monkeypatch) -> None:
    """Even when the DB lookup raises, ``resolve()`` returns the code default
    rather than blowing up the worker (chaos: table briefly unavailable)."""
    from src.ai.core.feature_flags import (
        DEFAULTS, FeatureFlags, invalidate_process_cache,
    )

    class _BoomDB:
        async def execute(self, *_a, **_k):
            raise RuntimeError("relation does not exist")

    invalidate_process_cache()
    ff = FeatureFlags(_BoomDB())
    # Pick a flag with a deterministic default.
    flag = "critic_pipeline.v2_enabled"
    res = await ff.resolve(flag)
    assert res.source == "default"
    assert res.value == DEFAULTS[flag]
