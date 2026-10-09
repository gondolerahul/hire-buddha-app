"""VT-22: a browser audio session's live model use is counted and billed.

``/stream/audio`` with provider ``web`` ran a live model session for as long
as the browser held it open and wrote no usage row, opened no run and settled
nothing. It now counts the audio each way and the provider's usage, and
settles them on one run at the end — the video call's shape (GW-10).
"""
from __future__ import annotations

import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.gateway import web_audio_adapter
from src.gateway.web_audio_adapter import WebAudioAdapter


class _Socket:
    def __init__(self, messages=()):
        self.messages = list(messages)

    async def receive(self):
        return self.messages.pop(0)

    async def send_text(self, _text):
        pass

    async def close(self, *_a, **_k):
        pass


class _Live:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.sent = 0

    async def send_realtime_input(self, audio):
        self.sent += len(audio["data"])

    async def receive(self):
        for response in self.responses:
            yield response


def _adapter(ws=None, *, agent=True) -> WebAudioAdapter:
    session = SimpleNamespace(id=uuid.uuid4(), company_id=uuid.uuid4(), direction="inbound",
                              agent_id=uuid.uuid4() if agent else None, customer_id=None)
    return WebAudioAdapter(ws or _Socket(), session, db=object())


@pytest.mark.asyncio
async def test_audio_sent_to_the_model_is_counted() -> None:
    adapter = _adapter(_Socket([{"bytes": b"\x00" * 32_000 * 2}, {"text": json.dumps({"event": "stop"})}]))
    adapter.gemini_session = _Live()
    adapter.is_running = True
    await adapter._receive_from_browser()
    assert adapter.usage.seconds_in == 2


@pytest.mark.asyncio
async def test_the_models_usage_and_audio_are_counted() -> None:
    adapter = _adapter()
    usage = SimpleNamespace(prompt_token_count=120, response_token_count=40,
                            prompt_tokens_details=[], response_tokens_details=[])
    adapter.gemini_session = _Live([
        SimpleNamespace(data=b"\x00" * 48_000, server_content=None, usage_metadata=usage),
        SimpleNamespace(data=None, server_content=None, usage_metadata=None),
    ])
    adapter.is_running = True

    async def _stop_after_one_pass(_pcm):
        adapter.is_running = False

    adapter.outgoing_audio_queue.put = _stop_after_one_pass
    await adapter._receive_from_ai()
    assert (adapter.usage.prompt_tokens, adapter.usage.response_tokens) == (120, 40)
    assert adapter.usage.seconds_out == 1 and adapter.usage.reported


class _NoDB:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *_):
        return False


@pytest.mark.asyncio
async def test_the_end_of_a_session_bills_and_settles_its_run(monkeypatch) -> None:
    monkeypatch.setattr(web_audio_adapter, "AsyncSessionLocal", _NoDB)

    class _Sessions:
        def __init__(self, _db):
            pass

        async def end_voice_session(self, _sid):
            return None

    monkeypatch.setattr(web_audio_adapter, "SessionManager", _Sessions)
    adapter = _adapter()
    adapter.usage.sent(32_000 * 3)
    calls = []

    async def _audio(db, usage):
        calls.append(("audio", usage.seconds_in))
        return Decimal("0.01")

    async def _finish(db, error=None):
        calls.append(("finish",))
        return Decimal("0.01")

    monkeypatch.setattr(adapter.spend, "record_live_audio", _audio)
    monkeypatch.setattr(adapter.spend, "finish", _finish)
    await adapter._cleanup()
    assert calls == [("audio", 3), ("finish",)]
    assert (adapter.spend.channel, adapter.spend.session_id) == ("web_audio", str(adapter.session_id))


def test_a_session_with_no_agent_has_nothing_to_bill_to() -> None:
    assert _adapter(agent=False).spend is None
