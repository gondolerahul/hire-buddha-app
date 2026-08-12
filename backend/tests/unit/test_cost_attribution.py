"""Phase 11 Track 8 — CostLedger attribution whitelist + behaviour."""
from __future__ import annotations

import logging
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.ai.services.cost_attribution import (
    VALID_ATTRIBUTIONS,
    CostAttribution,
    CostLedger,
)


def _db_stub() -> MagicMock:
    db = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Whitelist surface
# ---------------------------------------------------------------------------


def test_valid_attributions_complete() -> None:
    expected = {
        "planner", "actor_step", "critic_pre", "critic_post",
        "critic_align", "critic_super", "reformat_retry",
        "meta_review", "dreaming", "tool", "child_run",
        "embedding", "meta_spec_critic", "test_driver",
    }
    assert expected.issubset(VALID_ATTRIBUTIONS)


def test_cost_attribution_enum_values_unique() -> None:
    values = [a.value for a in CostAttribution]
    assert len(values) == len(set(values))


# ---------------------------------------------------------------------------
# add() — unknown attribution falls back to "tool" with warning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_attribution_falls_back_to_tool(caplog) -> None:
    db = _db_stub()
    ledger = CostLedger(db)
    sku_id = uuid4()
    with caplog.at_level(logging.WARNING):
        row = await ledger.add(
            run_id=uuid4(), company_id=uuid4(),
            amount=Decimal("0.05"), attribution="not_real",
            sku_id=sku_id,
        )
    assert row is not None
    assert row.attribution == "tool"
    assert any("unknown attribution" in r.message.lower() for r in caplog.records)


@pytest.mark.asyncio
async def test_known_attribution_persisted() -> None:
    db = _db_stub()
    ledger = CostLedger(db)
    sku_id = uuid4()
    row = await ledger.add(
        run_id=uuid4(), company_id=uuid4(),
        amount=Decimal("0.10"), attribution="critic_post",
        sku_id=sku_id,
    )
    assert row.attribution == "critic_post"
    assert db.add.called


# ---------------------------------------------------------------------------
# Zero / negative cost is a no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_amount_short_circuits() -> None:
    db = _db_stub()
    row = await CostLedger(db).add(
        run_id=uuid4(), company_id=uuid4(),
        amount=Decimal("0"), attribution="tool",
        sku_id=uuid4(),
    )
    assert row is None
    db.add.assert_not_called()


# ---------------------------------------------------------------------------
# Missing sku_id → telemetry-only, no SQL insert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_sku_id_skips_insert() -> None:
    db = _db_stub()
    row = await CostLedger(db).add(
        run_id=uuid4(), company_id=uuid4(),
        amount=Decimal("0.05"), attribution="critic_super",
        sku_id=None,
    )
    assert row is None
    db.add.assert_not_called()


# ---------------------------------------------------------------------------
# Metadata stitching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_latency_ms_added_to_log_metadata() -> None:
    db = _db_stub()
    sku_id = uuid4()
    captured: list = []
    db.add.side_effect = lambda row: captured.append(row)
    await CostLedger(db).add(
        run_id=uuid4(), company_id=uuid4(),
        amount=Decimal("0.02"), attribution="actor_step",
        sku_id=sku_id, latency_ms=125,
        log_metadata={"caller": "step_executor"},
    )
    assert len(captured) == 1
    meta = captured[0].log_metadata
    assert meta["latency_ms"] == 125
    assert meta["caller"] == "step_executor"
