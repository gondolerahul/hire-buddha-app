"""GW-10, GW-06, GW-13: a video call's pipeline works once its media arrives (HD11: fix it).

``/stream/video`` could never carry a call. ``aiortc`` was not a dependency;
behind that, the audio pipeline iterated over a class (the ``__mro__`` line)
and aborted, connected the model the way the factory stopped supporting with
VT-02, and fed it WebRTC's 48 kHz audio unconverted. The frame descriptions
went only into the system instruction, sent once when there were none; the
TURN credentials were never read; and the call's live audio was not billed.
These tests drive the pipeline with fakes; a scripted aiortc peer drives it in
``tests/integration/test_video_webrtc.py`` where aiortc is installed.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.common.config import settings
from src.gateway import video_gateway
from src.gateway.video_gateway import LIVE_INPUT_MIME, VideoSession


def _session(**kw) -> VideoSession:
    agent = {"company_id": str(uuid.uuid4()), "agent_id": str(uuid.uuid4())}
    return VideoSession(session_id=str(uuid.uuid4()), client_id=agent["company_id"], agent_info=agent,
                        provider="web", ws=kw.get("ws", _WS()), ice_servers=[])


class _WS:
    def __init__(self, messages=()):
        self.messages = list(messages)
        self.sent: list = []
        self.closed = None
        self.client = SimpleNamespace(host="192.0.2.1")
        self.url = SimpleNamespace(path="/stream/video")

    async def accept(self):
        pass

    async def receive_text(self):
        if not self.messages:
            raise RuntimeError("no more messages")
        return self.messages.pop(0)

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    async def send_bytes(self, data):
        self.sent.append(data)

    async def close(self, code=1000, reason=""):
        if self.closed is None:
            self.closed = (code, reason)


class _Track:
    """Gives its frames, then ends as an aiortc track does (MediaStreamError)."""

    def __init__(self, frames):
        self.frames = list(frames)

    async def recv(self):
        if not self.frames:
            raise RuntimeError("track ended")
        await asyncio.sleep(0)
        return self.frames.pop(0)


class _LiveSession:
    def __init__(self, replies=()):
        self.audio: list = []
        self.context: list = []
        self.replies = list(replies)

    async def send_realtime_input(self, *, audio=None, text=None):
        self.audio.append(audio)

    async def send_client_content(self, *, turns=None, turn_complete=True):
        self.context.append((turns, turn_complete))

    async def receive(self):
        while self.replies:
            yield self.replies.pop(0)
        await asyncio.sleep(3600)


# --- ICE (GW-06) --------------------------------------------------------------

def test_turn_is_offered_with_its_credentials(monkeypatch):
    monkeypatch.setattr(settings, "STUN_SERVERS", "stun:a.example:3478")
    monkeypatch.setattr(settings, "TURN_SERVER_URL", "turn:relay.example:3478")
    monkeypatch.setattr(settings, "TURN_USERNAME", "hb")
    monkeypatch.setattr(settings, "TURN_CREDENTIAL", "s3cret")
    assert video_gateway.ice_servers() == [
        {"urls": "stun:a.example:3478"},
        {"urls": "turn:relay.example:3478", "username": "hb", "credential": "s3cret"},
    ]


def test_without_turn_only_stun(monkeypatch):
    monkeypatch.setattr(settings, "STUN_SERVERS", "stun:a.example:3478")
    monkeypatch.setattr(settings, "TURN_SERVER_URL", "")
    assert video_gateway.ice_servers() == [{"urls": "stun:a.example:3478"}]


# --- audio --------------------------------------------------------------------

class _Resampler:
    """48 kHz in, 16 kHz PCM16 out: a third of the samples."""

    def resample(self, frame):
        return [SimpleNamespace(to_ndarray=lambda f=frame: SimpleNamespace(tobytes=lambda: f[: len(f) // 3]))]


def test_a_frame_becomes_16k_pcm16():
    assert list(video_gateway.pcm16_chunks(_Resampler(), b"x" * 960)) == [b"x" * 320]


@pytest.mark.asyncio
async def test_received_audio_reaches_the_model_converted(monkeypatch):
    session = _session()
    live = _LiveSession()

    async def _connect():
        session.live_session = live
        return live

    monkeypatch.setattr(session, "_connect_live", _connect)
    monkeypatch.setattr(video_gateway, "audio_resampler", lambda: _Resampler())
    await session._process_audio_track(_Track([b"a" * 960, b"b" * 960]))
    assert live.audio == [{"data": b"a" * 320, "mime_type": LIVE_INPUT_MIME},
                          {"data": b"b" * 320, "mime_type": LIVE_INPUT_MIME}]
    assert LIVE_INPUT_MIME == "audio/pcm;rate=16000"
    assert session.usage.audio_in_bytes == 640
    for task in list(session._tasks):
        task.cancel()


@pytest.mark.asyncio
async def test_the_models_audio_goes_back_and_is_counted():
    ws = _WS()
    session = _session(ws=ws)
    usage = SimpleNamespace(prompt_token_count=40, response_token_count=60, tool_use_prompt_token_count=0,
                            thoughts_token_count=0, prompt_tokens_details=[], response_tokens_details=[])
    live = _LiveSession(replies=[SimpleNamespace(data=b"\x01\x02" * 100, usage_metadata=usage)])
    task = asyncio.create_task(session._receive_ai_audio(live))
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert ws.sent == [b"\x01\x02" * 100]
    assert session.usage.audio_out_bytes == 200 and session.usage.prompt_tokens == 40


# --- video --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_video_frames_are_described_before_the_audio_connects(monkeypatch):
    """The session runs from the start: it used to wait for audio, and end at once."""
    session = _session()
    described = []

    async def _describe(jpeg):
        described.append(jpeg[:3])

    monkeypatch.setattr(session, "_analyze_video_frame", _describe)
    image = SimpleNamespace(save=lambda buf, **kw: buf.write(b"\xff\xd8jpeg"))
    await session._process_video_track(_Track([SimpleNamespace(to_image=lambda: image)]))
    await asyncio.gather(*session._frame_tasks)
    assert described == [b"\xff\xd8j"]


@pytest.mark.asyncio
async def test_the_model_is_told_what_the_camera_shows():
    session = _session()
    live = _LiveSession()
    session.live_session, session.vision_context = live, "One person, smiling, at a desk."
    assert await session.share_vision_context()
    [(turns, complete)] = live.context
    assert complete is False                     # context, not a turn to answer
    assert "One person, smiling" in turns["parts"][0]["text"]


@pytest.mark.asyncio
async def test_a_session_without_client_content_keeps_the_instruction_context():
    session = _session()
    session.live_session = SimpleNamespace(send_realtime_input=None)   # Azure Realtime's shape
    session.vision_context = "A whiteboard."
    assert await session.share_vision_context() is False


# --- the bill -----------------------------------------------------------------

class _NoDB:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *_):
        return False


@pytest.mark.asyncio
async def test_closing_bills_the_live_audio_and_settles(monkeypatch):
    monkeypatch.setattr("src.common.database.AsyncSessionLocal", _NoDB)
    session = _session()
    session.usage.sent(32_000 * 3)
    calls = []

    async def _audio(db, usage):
        calls.append(("audio", usage.seconds_in))
        return Decimal("0.01")

    async def _finish(db, error=None):
        calls.append(("finish",))
        return Decimal("0.01")

    monkeypatch.setattr(session.spend, "record_live_audio", _audio)
    monkeypatch.setattr(session.spend, "finish", _finish)
    await session.close()
    assert calls == [("audio", 3), ("finish",)]


@pytest.mark.asyncio
async def test_nothing_moved_nothing_billed():
    from src.gateway.call_spend import CallSpend
    from src.voice.live_usage import LiveUsage

    spend = CallSpend(company_id=uuid.uuid4(), agent_id=uuid.uuid4(), channel="video", session_id="s")
    assert await spend.record_live_audio(object(), LiveUsage()) == Decimal("0")
    assert spend.run_id is None


# --- the endpoint ---------------------------------------------------------------

@pytest.fixture
def handshake(monkeypatch):
    company = str(uuid.uuid4())

    async def _company(ws, hs):
        return company

    class _Dispatcher:
        async def resolve_agent_for_client(self, client_id, channel, agent_id=None):
            return {"company_id": company, "agent_id": str(uuid.uuid4())}

    monkeypatch.setattr(video_gateway, "stream_company", _company)
    monkeypatch.setattr(video_gateway, "get_dispatcher", lambda: _Dispatcher())
    monkeypatch.setattr(video_gateway, "handshake_allowed", lambda ws: True)
    monkeypatch.setattr(video_gateway.asyncio, "sleep", _no_sleep)
    return company


async def _no_sleep(*_a, **_k):
    return None


@pytest.mark.asyncio
async def test_without_aiortc_the_client_is_told(monkeypatch, handshake):
    monkeypatch.setattr(video_gateway, "AIORTC_AVAILABLE", False)
    ws = _WS([json.dumps({"event": "connect", "token": "t"})])
    await video_gateway.unified_video_streaming(ws)
    assert ws.sent[0]["event"] == "connected" and ws.sent[0]["webrtc_enabled"] is False
    assert "aiortc is not installed" in ws.sent[1]["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("refusal, code", [("Cannot start execution: no free credit", 4002), (None, 4429)])
async def test_a_video_call_is_admitted_like_any_call(monkeypatch, handshake, refusal, code):
    from src.voice import live_sessions

    monkeypatch.setattr(video_gateway, "AIORTC_AVAILABLE", True)
    monkeypatch.setattr(settings, "VIDEO_STREAMING_ENABLED", True)
    monkeypatch.setattr(settings, "LIVE_SESSIONS_PER_COMPANY", 1)
    monkeypatch.setattr(live_sessions, "_open", live_sessions.Counter())
    monkeypatch.setattr("src.common.database.AsyncSessionLocal", _NoDB)
    if refusal is None:
        live_sessions.acquire(handshake, kind="call")       # the company's one place is taken

    async def _rule(db, company_id, *, direction, checkpoint):
        assert checkpoint == "video"
        return refusal

    monkeypatch.setattr("src.voice.call_admission.call_refusal", _rule)
    ws = _WS([json.dumps({"event": "connect", "token": "t"})])
    await video_gateway.unified_video_streaming(ws)
    assert ws.closed[0] == code
    assert not any(isinstance(m, dict) and m.get("event") == "connected" for m in ws.sent)
