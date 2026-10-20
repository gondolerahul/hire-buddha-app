"""ToolCostResolver — the one tool price lookup (BC-07, BC-10, BC-11, BC-29)."""
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


def _registry_row(*, internal_cost=Decimal("0.012"), sku="custom-sku", cost_unit="per_request"):
    return SimpleNamespace(
        id=uuid4(),
        internal_cost=internal_cost,
        service_sku=sku,
        provider_name="test-provider",
        cost_unit=cost_unit,
    )


def _db_with_rows(company_row=None, platform_row=None, platform_id=None) -> MagicMock:
    """Registry lookups answer ``company_row`` then ``platform_row``; the APP
    company lookup answers ``platform_id``."""
    db = MagicMock()
    answers = iter([company_row, platform_id, platform_row])

    async def execute(_stmt, *args, **kwargs):
        result = MagicMock()
        value = next(answers, None)
        result.scalar_one_or_none = lambda: value
        return result

    db.execute = AsyncMock(side_effect=execute)
    db.add = MagicMock()
    return db


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


@pytest.mark.asyncio
async def test_platform_row_prices_a_tenant_without_its_own() -> None:
    """BC-10: a tenant with no registry row of its own used to be charged $0."""
    platform = _registry_row(internal_cost=Decimal("0.02"))
    db = _db_with_rows(company_row=None, platform_row=platform, platform_id=uuid4())
    amount, source, sku_id = await ToolCostResolver(db, uuid4()).resolve("web_search")
    assert (amount, source, sku_id) == (Decimal("0.02"), "platform", platform.id)


@pytest.mark.asyncio
async def test_a_per_thousand_price_is_divided_per_call() -> None:
    """BC-10: cost_unit was ignored, so a per-1000 price was charged per call."""
    row = _registry_row(internal_cost=Decimal("5.00"), cost_unit="per_1000_requests")
    amount, _, _ = await ToolCostResolver(_db_with_registry_row(row), uuid4()).resolve("web_search")
    assert amount == Decimal("0.005")


@pytest.mark.asyncio
async def test_the_query_matches_only_the_tools_own_skus() -> None:
    """BC-29: any CUSTOM_API registry row used to price every tool."""
    db = _db_with_registry_row(None)
    await ToolCostResolver(db, uuid4()).resolve("web_search")
    sql = str(db.execute.call_args_list[0].args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "CUSTOM_API" not in sql
    assert "'web_search'" in sql and "'serp-api-key'" in sql


@pytest.mark.asyncio
@pytest.mark.parametrize("tool, category", [
    ("video_generate", "VIDEO_GENERATION"),
    ("text_to_speech", "SPEECH_GENERATION"),
    ("music_generation", "MUSIC_GENERATION"),
])
async def test_a_media_tool_is_priced_by_its_models_category(tool, category) -> None:
    """The configured model's row prices the call, whatever its SKU is called
    (a veo-3.1-generate-001 row used to leave video_generate at its fixed cost)."""
    db = _db_with_registry_row(None)
    await ToolCostResolver(db, uuid4()).resolve(tool)
    sql = str(db.execute.call_args_list[0].args[0].compile(compile_kwargs={"literal_binds": True}))
    assert f"service_category = '{category}'" in sql
    assert "ORDER BY integration_registry.created_at" in sql


@pytest.mark.asyncio
async def test_an_ordinary_tool_is_not_priced_by_category() -> None:
    db = _db_with_registry_row(None)
    await ToolCostResolver(db, uuid4()).resolve("web_search")
    sql = str(db.execute.call_args_list[0].args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "service_category = '" not in sql


# ---------------------------------------------------------------------------
# charge() — writes the ledger row; the caller adds the amount to the run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_charge_writes_a_ledger_row_and_leaves_the_run_to_the_caller() -> None:
    row = _registry_row(internal_cost=Decimal("0.030"))
    db = _db_with_registry_row(row)
    db.add = MagicMock()
    resolver = ToolCostResolver(db, uuid4())
    run = SimpleNamespace(
        id=uuid4(), company_id=uuid4(), total_cost_usd=Decimal("0.10"),
    )
    charge = await resolver.charge(run=run, tool_id="web_search",
                                    latency_ms=42)
    assert charge.amount == Decimal("0.030")
    assert run.total_cost_usd == Decimal("0.10")   # the run total is the sum of rows (AK-02)
    ledger_row = db.add.call_args.args[0]
    assert (ledger_row.calculated_cost, ledger_row.sku_id, ledger_row.attribution) == (
        Decimal("0.030"), row.id, "tool")


@pytest.mark.asyncio
async def test_a_fixed_cost_charge_has_a_ledger_row_too() -> None:
    """BC-07: a fixed-cost tool used to have no usage_logs row (no SKU)."""
    db = _db_with_registry_row(None)
    db.add = MagicMock()
    run = SimpleNamespace(id=uuid4(), company_id=uuid4(), total_cost_usd=Decimal("0"))
    await ToolCostResolver(db, uuid4()).charge(run=run, tool_id="image_generation")
    ledger_row = db.add.call_args.args[0]
    assert ledger_row.sku_id is None
    assert ledger_row.calculated_cost == Decimal("0.04")
    assert ledger_row.log_metadata["tool"] == "image_generation"


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
    # Per unit: a second of video or speech, a piece of music.
    assert TOOL_FIXED_COST["video_generate"] == Decimal("0.40")
    assert TOOL_FIXED_COST["text_to_speech"] == Decimal("0.00045")
    assert TOOL_FIXED_COST["music_generation"] == Decimal("0.08")
    assert "video_generation" not in TOOL_FIXED_COST


# ---------------------------------------------------------------------------
# TX-I1 / TL-33 (P4.6): one price cache per run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolvers_of_one_run_share_its_price_cache() -> None:
    """A step's service, and its resolver, is rebuilt every iteration; the
    price was looked up again every time."""
    run_id, company = uuid4(), uuid4()
    db = _db_with_registry_row(_registry_row(internal_cost=Decimal("0.030")))
    first = await ToolCostResolver(db, company, run_id=run_id).resolve("web_search")
    queries = db.execute.await_count
    second = await ToolCostResolver(db, company, run_id=run_id).resolve("web_search")
    assert first == second and db.execute.await_count == queries      # no new lookup
    await ToolCostResolver(db, company, run_id=uuid4()).resolve("web_search")
    assert db.execute.await_count > queries                            # another run looks up


@pytest.mark.asyncio
async def test_a_run_keeps_its_price_when_the_registry_changes() -> None:
    run_id, company = uuid4(), uuid4()
    await ToolCostResolver(_db_with_registry_row(_registry_row(internal_cost=Decimal("0.03"))),
                           company, run_id=run_id).resolve("web_search")
    later = await ToolCostResolver(_db_with_registry_row(_registry_row(internal_cost=Decimal("9.99"))),
                                   company, run_id=run_id).resolve("web_search")
    assert later[0] == Decimal("0.03")


def test_the_run_caches_are_bounded() -> None:
    from src.ai.governance import tool_cost_resolver as tcr
    for _ in range(tcr._RUN_CACHE_LIMIT + 5):
        tcr._run_price_cache(uuid4())
    assert len(tcr._RUN_PRICE_CACHES) == tcr._RUN_CACHE_LIMIT
