"""LP-01, Phase 15 T1-2…T1-4 — a price's unit is a code, and the meter says what it measured.

The unit was free text, matched by substring (LP-01: ``per_1k_tokens`` priced
each token 1000× over) and then parsed (``parse_cost_unit``). Now it is one of
``src.billing.units.CostUnit``: a registry write names a code or is refused;
a quantity is priced only by a unit of the dimension it was measured in; calls
are priced per second, never per started minute.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.ai.usage_service import price_at
from src.billing.units import Dimension


def _row(code: str, cost: str, **extra) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), internal_cost=Decimal(cost), cost_unit_code=code, service_metadata=None,
                           **extra)


def test_a_registry_write_names_a_known_code():
    from src.config.schemas import IntegrationRegistryCreate, IntegrationRegistryUpdate

    base = dict(provider_name="openai", service_sku="gpt-x-in", component_type="LLM",
                internal_cost=Decimal("0.5"), company_id=uuid4(), api_key="k")
    assert IntegrationRegistryCreate(**base, cost_unit_code="PER_1K_TOKENS").cost_unit_code == "PER_1K_TOKENS"
    with pytest.raises(ValidationError, match="cost_unit_code"):
        IntegrationRegistryCreate(**base, cost_unit_code="per_1k_tokens")       # text is not a code
    with pytest.raises(ValidationError, match="cost_unit_code"):
        IntegrationRegistryCreate(**base)                                         # the unit is required
    with pytest.raises(ValidationError, match="cost_unit_code"):
        IntegrationRegistryUpdate(cost_unit_code="PER_BANANA")
    with pytest.raises(ValidationError, match="internal_cost"):
        IntegrationRegistryCreate(**{**base, "internal_cost": Decimal("-1")}, cost_unit_code="PER_1K_TOKENS")
    assert IntegrationRegistryUpdate(status="inactive").cost_unit_code is None


def test_a_quantity_is_priced_only_in_its_own_dimension():
    tokens = _row("PER_1M_TOKENS", "0.30")
    assert price_at(tokens, 1500, Dimension.TOKEN).cost == Decimal("0.00045")
    assert price_at(tokens, 1500, Dimension.TOKEN).cost_source == "registry"
    # A per-minute price applied to tokens used to be divided anyway.
    assert price_at(_row("PER_MINUTE", "0.60"), 1500, Dimension.TOKEN).cost_source == "unit_mismatch"
    assert price_at(_row("PER_MINUTE", "0.60"), 1500, Dimension.TOKEN).cost == 0
    assert price_at(None, 1500, Dimension.TOKEN).cost_source == "missing"
    assert price_at(_row("PER_1K_QUERIES", "5"), 2, [Dimension.REQUEST, Dimension.QUERY]).cost == Decimal("0.01")


@pytest.mark.asyncio
async def test_a_call_is_billed_per_second_not_per_started_minute():
    from src.voice.usage_logger import VoiceUsageLogger

    db = MagicMock(commit=AsyncMock())
    meter = VoiceUsageLogger(db)
    meter._get_sku = AsyncMock(return_value=_row("PER_MINUTE", "0.60"))
    assert await meter._log_telephony_usage(uuid4(), "twilio", duration_seconds=125) == Decimal("1.25")
    assert await meter._log_telephony_usage(uuid4(), "twilio", duration_seconds=Decimal("2.5")) == Decimal("0.025")
    row = db.add.call_args.args[0]
    assert row.raw_quantity == Decimal("2.5") and row.log_metadata["duration_seconds"] == 2.5


@pytest.mark.asyncio
async def test_voice_audio_is_priced_by_its_sku_unit():
    from src.voice.usage_logger import VoiceUsageLogger

    db = MagicMock(commit=AsyncMock())
    meter = VoiceUsageLogger(db)
    # Per token, no count from the provider: 60 s × 167 tokens/s at $1 per 1M tokens.
    meter._get_sku = AsyncMock(return_value=_row("PER_1M_TOKENS", "1.0"))
    cost = await meter._log_llm_audio_usage(uuid4(), "audio-in", audio_seconds=60, usage_type="input")
    assert cost == Decimal(10020) / Decimal(1_000_000)
    # The SKU's own tokens-per-second when it gives one.
    meter._get_sku = AsyncMock(return_value=SimpleNamespace(
        id=uuid4(), internal_cost=Decimal("1.0"), cost_unit_code="PER_1M_TOKENS",
        service_metadata={"tokens_per_second": 25}))
    assert await meter._log_llm_audio_usage(uuid4(), "audio-in", audio_seconds=60,
                                            usage_type="input") == Decimal(1500) / Decimal(1_000_000)
    # Per minute: the audio's exact seconds ÷ 60 — 90 s is 1.5 minutes, not 2.
    meter._get_sku = AsyncMock(return_value=_row("PER_MINUTE", "0.10"))
    assert await meter._log_llm_audio_usage(uuid4(), "audio-in", audio_seconds=90,
                                            usage_type="input") == Decimal("0.15")
