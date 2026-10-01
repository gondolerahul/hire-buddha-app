"""LP-01 — ``cost_unit`` is parsed, not substring-matched.

The divisor was picked by substring: ``per_1k_tokens`` (the form the
credentials guide uses) matched nothing and priced each token at the
per-thousand rate, 1000× over; ``per_1M_tokens`` priced it 1,000,000× over.
Nothing stopped such a unit from being written.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.ai.usage_service import parse_cost_unit, unit_divisor


@pytest.mark.parametrize("unit,quantity,noun", [
    ("per_1k_tokens", 1000, "token"),
    ("per_1K_tokens", 1000, "token"),
    ("per-1k-tokens", 1000, "token"),
    ("per_1M_tokens", 1_000_000, "token"),
    ("per_1m_tokens", 1_000_000, "token"),
    ("1M Tokens", 1_000_000, "token"),
    ("per_million_tokens", 1_000_000, "token"),
    ("per 1,000,000 tokens", 1_000_000, "token"),
    ("per_1000_characters", 1000, "character"),
    ("per_minute", 1, "minute"),
    ("second", 1, "second"),
    ("per_call", 1, "call"),
    ("flat_fee", 1, "call"),
    ("per_image", 1, "image"),
    ("per token", 1, "token"),
])
def test_known_units_parse(unit, quantity, noun):
    parsed = parse_cost_unit(unit)
    assert parsed.quantity == Decimal(quantity)
    assert parsed.noun == noun
    assert unit_divisor(unit) == Decimal(quantity)


@pytest.mark.parametrize("unit", ["", "per_1k", "per_banana", "tokens per 1k", "1kk tokens"])
def test_unknown_units_are_rejected(unit):
    with pytest.raises(ValueError):
        parse_cost_unit(unit)


def test_a_registry_write_with_an_unknown_unit_is_refused():
    from src.config.schemas import IntegrationRegistryCreate, IntegrationRegistryUpdate

    base = dict(provider_name="openai", service_sku="gpt-x-in", component_type="LLM",
                internal_cost=Decimal("0.5"), company_id=uuid4(), api_key="k")
    assert IntegrationRegistryCreate(**base, cost_unit="per_1k_tokens").cost_unit == "per_1k_tokens"
    with pytest.raises(ValidationError, match="cost_unit"):
        IntegrationRegistryCreate(**base, cost_unit="per thousandish tokens")
    with pytest.raises(ValidationError, match="cost_unit"):
        IntegrationRegistryUpdate(cost_unit="per_banana")
    assert IntegrationRegistryUpdate(status="inactive").cost_unit is None


@pytest.mark.asyncio
async def test_voice_audio_tokens_use_the_parsed_divisor():
    from src.voice.usage_logger import VoiceUsageLogger

    db = MagicMock(commit=AsyncMock())
    logger = VoiceUsageLogger(db)
    logger._get_sku = AsyncMock(return_value=SimpleNamespace(
        id=uuid4(), internal_cost=Decimal("1.0"), cost_unit="per_1m_tokens"))
    cost = await logger._log_llm_audio_usage(uuid4(), "audio-in", audio_seconds=60, usage_type="input")
    # 60 s × 167 tokens/s = 10,020 tokens at $1 per 1M tokens.
    assert cost == Decimal("1.0") * Decimal(10020) / Decimal(1_000_000)
