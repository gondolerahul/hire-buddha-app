"""Keypad input is declared unsupported on AI calls, and counted (VT-13, HD13).

Only the mobile dialer reads DTMF. On any other call a digit was logged as
"unused" and nothing else; now it is a ``voice.dtmf.unsupported`` event, so
the demand for an IVR shows, and the builder says callers cannot use the keypad.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from src.ai.core.events import capture_test_events
from src.voice.websocket_handler import BaseStreamHandler


class _Provider:
    def __init__(self, *events):
        self.events = [json.dumps(e) for e in events]

    async def receive_text(self):
        return self.events.pop(0)


async def _run(handler):
    with capture_test_events() as events:
        await handler._receive_from_provider()
    return [e for e in events if e.name.startswith("voice.dtmf")]


@pytest.mark.asyncio
async def test_a_digit_on_an_ai_call_is_counted_as_unsupported():
    handler = BaseStreamHandler(websocket=_Provider({"event": "dtmf", "dtmf": {"digit": "1"}},
                                                    {"event": "stop"}), db=None)
    handler.session_id, handler.is_running = uuid.uuid4(), True
    handler.voice_session = SimpleNamespace(company_id=uuid.uuid4())

    [unsupported] = await _run(handler)
    assert unsupported.name == "voice.dtmf.unsupported"
    assert unsupported.payload["session_id"] == str(handler.session_id)
    assert handler.is_running is False                     # the stop that followed was handled


@pytest.mark.asyncio
async def test_a_digit_on_a_mobile_dialer_leg_goes_to_the_dialer():
    digits = []

    async def _on_dtmf(key):
        digits.append(key)

    handler = BaseStreamHandler(websocket=_Provider({"event": "dtmf", "dtmf": {"digit": "#"}},
                                                    {"event": "stop"}), db=None)
    handler.session_id, handler.is_running = uuid.uuid4(), True
    handler.mobile = SimpleNamespace(on_dtmf=_on_dtmf)

    assert await _run(handler) == [] and digits == ["#"]
