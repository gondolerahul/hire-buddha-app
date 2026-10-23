"""A call's model cost is what the provider reported, or the audio each way (VT-05).

Voice tokens were estimated at a flat 167 a second, and both the audio-in and
the audio-out rows billed the whole call. Now the call sums the Live API's
``usage_metadata`` messages and bills those tokens; when the provider sends
none, each direction is billed for the audio it carried.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.voice.live_usage import IN_BYTES_PER_SECOND, OUT_BYTES_PER_SECOND, LiveUsage
from src.voice.usage_logger import VoiceUsageLogger


def _detail(modality, count):
    return SimpleNamespace(modality=SimpleNamespace(value=modality), token_count=count)


def _turn(prompt, response, audio_in, text_in, audio_out, thoughts=0):
    return SimpleNamespace(
        prompt_token_count=prompt, response_token_count=response, thoughts_token_count=thoughts,
        tool_use_prompt_token_count=0,
        prompt_tokens_details=[_detail("AUDIO", audio_in), _detail("TEXT", text_in)],
        response_tokens_details=[_detail("AUDIO", audio_out)])


def test_the_calls_usage_is_the_sum_of_its_turns():
    usage = LiveUsage()
    usage.add(None)                                         # most messages carry none
    usage.add(_turn(1200, 300, 900, 300, 300))
    usage.add(_turn(2600, 500, 1900, 700, 500, thoughts=40))
    assert usage.reported and usage.messages == 2
    assert (usage.prompt_tokens, usage.response_tokens) == (3800, 840)
    assert usage.prompt_by_modality == {"AUDIO": 2800, "TEXT": 1000}
    assert usage.response_by_modality == {"AUDIO": 800}


def test_the_audio_each_way_is_counted_in_seconds():
    usage = LiveUsage()
    usage.sent(IN_BYTES_PER_SECOND * 90)
    usage.received(OUT_BYTES_PER_SECOND * 12)
    assert (usage.seconds_in, usage.seconds_out, usage.reported) == (90, 12, False)


# ── the bill ────────────────────────────────────────────────────────────────


@pytest.fixture
def logger_and_rows():
    rows: list = []
    db = MagicMock(commit=AsyncMock(), execute=AsyncMock())
    db.add = rows.append
    usage_logger = VoiceUsageLogger(db)
    usage_logger._get_sku = AsyncMock(return_value=SimpleNamespace(
        id=uuid4(), internal_cost=Decimal("2.0"), cost_unit_code="PER_1M_TOKENS"))
    return usage_logger, rows


async def _bill(usage_logger, live_usage, duration=90):
    return await usage_logger.log_voice_session_usage(
        session_id=uuid4(), company_id=uuid4(), provider="none", duration_seconds=duration,
        live_usage=live_usage)


@pytest.mark.asyncio
async def test_reported_tokens_are_billed(logger_and_rows):
    usage_logger, rows = logger_and_rows
    live = LiveUsage()
    live.add(_turn(3800, 800, 2800, 1000, 800))
    usage = await _bill(usage_logger, live)

    input_row, output_row = rows
    assert input_row.log_metadata["billing_mode"] == "reported_tokens"
    assert input_row.raw_quantity == Decimal(3800)
    assert input_row.log_metadata["tokens_by_modality"] == {"AUDIO": 2800, "TEXT": 1000}
    assert output_row.raw_quantity == Decimal(800)
    assert usage.total_cost == Decimal("2.0") * Decimal(4600) / Decimal(1_000_000)


@pytest.mark.asyncio
async def test_without_a_report_each_direction_bills_its_own_audio(logger_and_rows):
    usage_logger, rows = logger_and_rows
    live = LiveUsage()
    live.sent(IN_BYTES_PER_SECOND * 90)                     # the caller's line, the whole call
    live.received(OUT_BYTES_PER_SECOND * 12)                # the agent spoke for 12 s
    await _bill(usage_logger, live, duration=90)

    input_row, output_row = rows
    assert input_row.log_metadata["billing_mode"] == "estimated_from_audio"
    assert input_row.log_metadata["audio_seconds"] == 90
    assert output_row.log_metadata["audio_seconds"] == 12   # not the 90 s it used to be
