"""Every Smartflo reply uses one success key (VT-15).

The key is a setting, ``TATA_STREAM_SUCCESS_KEY`` (historically ``"sucess"``;
Smartflo's docs say ``"success"``), but the two refusals hard-coded
``"sucess"``, so flipping the setting would have answered calls under one key
and declined them under another. The default stays until a live Smartflo call
confirms the spelling.
"""
from __future__ import annotations

import uuid

import pytest

from tests.unit.test_inbound_call_admission import _JsonRequest, _Numbers, _Sessions, refused  # noqa: F401

CALL = {"callId": "T1", "fromNumber": "+15550002", "toNumber": "+15550001"}


@pytest.mark.asyncio
async def test_a_refusal_uses_the_configured_key(refused, monkeypatch):  # noqa: F811
    from src.voice.webhook_router import tata_incoming_call

    monkeypatch.setattr("src.common.config.settings.TATA_STREAM_SUCCESS_KEY", "success")
    res = await tata_incoming_call(_JsonRequest(CALL), session_manager=_Sessions(),
                                   number_router=_Numbers(uuid.uuid4()))
    assert res == {"success": False, "error": "This service is temporarily unavailable"}


@pytest.mark.asyncio
async def test_an_unknown_number_is_declined_under_the_same_key(refused, monkeypatch):  # noqa: F811
    from src.voice.webhook_router import tata_incoming_call

    class _NoNumber(_Numbers):
        async def find_customer_by_number(self, _number):
            return None

    monkeypatch.setattr("src.common.config.settings.TATA_STREAM_SUCCESS_KEY", "success")
    res = await tata_incoming_call(_JsonRequest(CALL), session_manager=_Sessions(),
                                   number_router=_NoNumber(uuid.uuid4()))
    assert res == {"success": False, "error": "Number not configured"}


def test_the_default_is_unchanged_until_a_live_check():
    from src.common.config import Settings
    assert Settings.model_fields["TATA_STREAM_SUCCESS_KEY"].default == "sucess"
