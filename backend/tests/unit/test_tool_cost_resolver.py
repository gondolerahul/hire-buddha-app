"""Phase 11 Track 8 — ToolCostResolver lookup priority + cache."""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.ai.governance.tool_cost_resolver import (
    TOOL_FIXED_COST,
    TOOL_SKU_MAP,
    ToolCostResolver,
)


def _db_with_registry_row(row=None) -> MagicMock:
    db = MagicMock()
    db.commit = AsyncMock()

    async def execute(_stmt, *args, **kwargs):
        result = MagicMock()
        result.scalar_one_or_none = lambda: row
        return result

    db.execute = AsyncMock(side_effect=execute)
    return db


def _registry_row(*, internal_cost=Decimal("0.012"), sku="custom-sku"):
    return SimpleNamespace(
        id=uuid4(),
        internal_cost=internal_cost,
        service_sku=sku,
        provider_name="test-provider",
    )


# ---------------------------------------------------------------------------
# Lookup priority
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_match_wins() -> None:
    row = _registry_row(internal_cost=Decimal("0.025"))
    resolver = ToolCostResolver(_db_with_registry_row(row), uuid4())
    amount, source, sku_id = await resolver.resolve("web_search")
    assert source == "registry"
    assert amount == Decimal("0.025")
    assert sku_id == row.id


@pytest.mark.asyncio
async def test_fixed_fallback_when_no_registry() -> None:
    resolver = ToolCostResolver(_db_with_registry_row(None), uuid4())
    amount, source, sku_id = await resolver.resolve("image_generation")
    assert source == "fixed"
    assert amount == TOOL_FIXED_COST["image_generation"]
    assert sku_id is None


@pytest.mark.asyncio
async def test_missing_tool_warns_and_returns_zero() -> None:
    resolver = ToolCostResolver(_db_with_registry_row(None), uuid4())
    amount, source, _ = await resolver.resolve("definitely-not-a-tool")
    assert source == "missing"
    assert amount == Decimal("0")


# ---------------------------------------------------------------------------
# Cache — second call doesn't re-query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_short_circuits_second_lookup() -> None:
    row = _registry_row()
    db = _db_with_registry_row(row)
    resolver = ToolCostResolver(db, uuid4())
    await resolver.resolve("web_search")
    initial_calls = db.execute.call_count
    await resolver.resolve("web_search")
    assert db.execute.call_count == initial_calls


@pytest.mark.asyncio
async def test_invalidate_drops_cache() -> None:
    row = _registry_row()
    db = _db_with_registry_row(row)
    resolver = ToolCostResolver(db, uuid4())
    await resolver.resolve("web_search")
    resolver.invalidate("web_search")
    initial_calls = db.execute.call_count
    await resolver.resolve("web_search")
    assert db.execute.call_count > initial_calls


# ---------------------------------------------------------------------------
# charge() — mutates run.total_cost_usd + writes ledger row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_charge_updates_run_total() -> None:
    row = _registry_row(internal_cost=Decimal("0.030"))
    db = _db_with_registry_row(row)
    resolver = ToolCostResolver(db, uuid4())
    run = SimpleNamespace(
        id=uuid4(), company_id=uuid4(), total_cost_usd=Decimal("0.10"),
    )
    charge = await resolver.charge(run=run, tool_id="web_search",
                                    latency_ms=42)
    assert charge.amount == Decimal("0.030")
    assert run.total_cost_usd == Decimal("0.130")


@pytest.mark.asyncio
async def test_zero_amount_charge_is_noop() -> None:
    db = _db_with_registry_row(None)
    resolver = ToolCostResolver(db, uuid4())
    run = SimpleNamespace(id=uuid4(), company_id=uuid4(),
                          total_cost_usd=Decimal("0.50"))
    await resolver.charge(run=run, tool_id="definitely-not-a-tool")
    assert run.total_cost_usd == Decimal("0.50")


# ---------------------------------------------------------------------------
# Lookup tables: pin the canonical map
# ---------------------------------------------------------------------------


def test_canonical_sku_map_present() -> None:
    assert "web_search" in TOOL_SKU_MAP
    assert "serp-api-key" in TOOL_SKU_MAP["web_search"]


def test_canonical_fixed_costs() -> None:
    assert TOOL_FIXED_COST["image_generation"] == Decimal("0.04")
    assert TOOL_FIXED_COST["video_generation"] == Decimal("0.05")
