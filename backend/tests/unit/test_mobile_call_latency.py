"""Dead air on mobile-dialer calls: the noise gate, the pre-rolled greeting, and app signals."""
import asyncio
import audioop
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.common.config import settings
from src.mobile import push_gateway
from src.mobile.stream_controller import MobileCallController


class FakeGemini:
    def __init__(self):
        self.texts = []
        self.chunks = []

    async def send_realtime_input(self, text=None, audio=None):
        if text:
            self.texts.append(text)
        if audio is not None:
            self.chunks.append(audio.data)


class FakeSocket:
    async def send_text(self, text):
        pass


def frame(amplitude: int) -> bytes:
    """One 20 ms μ-law frame of a square wave at ``amplitude``."""
    pcm = b"".join(int(v).to_bytes(2, "little", signed=True) for v in [amplitude, -amplitude] * 80)
    return audioop.lin2ulaw(pcm, 2)


# ── noise gate ──────────────────────────────────────────────────────────────

async def run_inbound(frames):
    from src.voice.websocket_handler import BaseStreamHandler

    handler = BaseStreamHandler(FakeSocket(), db=None)
    handler.gemini_session = FakeGemini()
    handler.is_running = True
    handler.mobile = SimpleNamespace(merged=True)
    handler._first_audio_received = True  # past the greeting protection
    handler.incoming_audio_buffer.extend(frames)
    task = asyncio.create_task(handler._process_incoming_audio())
    for _ in range(100):
        if len(handler.gemini_session.chunks) == len(frames):
            break
        await asyncio.sleep(0.01)
    handler.is_running = False
    await asyncio.wait_for(task, 2)
    return [any(c) for c in handler.gemini_session.chunks]  # True = audio, False = silence


async def test_line_hiss_reaches_the_model_as_silence():
    assert settings.VOICE_NOISE_GATE_RMS == 40
    sent = await run_inbound([frame(20)] * 5)
    assert sent == [False] * 5


async def test_speech_opens_the_gate_and_its_tail_is_kept():
    hangover = settings.VOICE_NOISE_GATE_HANGOVER_FRAMES
    sent = await run_inbound([frame(20), frame(2000)] + [frame(20)] * (hangover + 2))
    assert sent == [False, True] + [True] * hangover + [False, False]


# ── pre-rolled greeting ─────────────────────────────────────────────────────

class StubHandler:
    def __init__(self):
        self.voice_session = SimpleNamespace(session_metadata={"contact_data": {"name": "Asha"}})
        self.session_id = uuid4()
        self.is_running = True
        self.gemini_session = FakeGemini()
        self.incoming_audio_buffer = []
        self.played = []
        self._last_lead_speech_at = self._last_strong_speech_at = None
        self._last_lead_transcript_at = self._user_speech_end_time = None
        self._pipeline_started_at = self._greeting_sent_at = None

    async def _play_model_audio(self, audio):
        self.played.append(audio)


def controller():
    handler = StubHandler()
    ctl = MobileCallController(handler)
    return handler, ctl


async def test_greeting_is_pre_rolled_when_the_lead_answers_and_played_on_merge():
    handler, ctl = controller()
    await ctl.on_lead_answered()
    assert len(handler.gemini_session.texts) == 1 and "(Asha)" in handler.gemini_session.texts[0]

    ctl.hold_model_audio(b"a1")
    ctl.hold_model_audio(b"a2")
    assert handler.played == []  # the lead is not on the line yet

    await ctl.on_merged("ws")
    assert handler.played == [b"a1", b"a2"]
    assert ctl.merged and handler._greeting_sent_at == ctl.merged_at
    assert len(handler.gemini_session.texts) == 1  # no second greeting
    ctl._lead_audio_task.cancel()


async def test_without_a_pre_roll_merge_triggers_the_greeting():
    handler, ctl = controller()
    ctl.hold_model_audio(b"stray")  # pre-merge audio that is not a greeting is dropped
    await ctl.on_merged("api")
    assert handler.played == []
    assert len(handler.gemini_session.texts) == 1
    ctl._lead_audio_task.cancel()


async def test_lead_answered_after_the_merge_does_nothing():
    handler, ctl = controller()
    await ctl.on_merged("api")
    await ctl.on_lead_answered()
    await ctl.on_lead_answered()
    assert len(handler.gemini_session.texts) == 1
    ctl._lead_audio_task.cancel()


async def test_second_merge_signal_is_ignored():
    handler, ctl = controller()
    await ctl.on_lead_answered()
    ctl.hold_model_audio(b"a1")
    await ctl.on_merged("ws")
    await ctl.on_merged("api")
    assert handler.played == [b"a1"]
    ctl._lead_audio_task.cancel()


async def test_held_greeting_is_bounded():
    from src.mobile.stream_controller import MAX_HELD_AUDIO_BYTES

    handler, ctl = controller()
    await ctl.on_lead_answered()
    chunk = b"x" * 48_000
    for _ in range(MAX_HELD_AUDIO_BYTES // len(chunk) + 5):
        ctl.hold_model_audio(chunk)
    assert ctl._held_bytes <= MAX_HELD_AUDIO_BYTES


# ── app signals over the push socket ───────────────────────────────────────

class FakeDb:
    def __init__(self, session_id):
        self.session_id = session_id
        self.queries = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        self.queries.append(str(stmt))
        return SimpleNamespace(scalar_one_or_none=lambda: self.session_id)


@pytest.fixture
def relay(monkeypatch):
    published = []

    async def publish(session_id, msg_type, **fields):
        published.append((session_id, msg_type, fields))
        return 1

    monkeypatch.setattr(push_gateway.realtime, "publish_session_control", publish)

    def with_session(session_id):
        db = FakeDb(session_id)
        monkeypatch.setattr("src.common.database.AsyncSessionLocal", lambda: db)
        return db

    return published, with_session


async def test_signal_is_relayed_to_the_attempts_ai_leg(relay):
    published, with_session = relay
    sid, aid = uuid4(), uuid4()
    db = with_session(sid)
    user = SimpleNamespace(id=uuid4(), company_id=uuid4())
    await push_gateway._relay_signal(user, {"type": "signal", "signal": "merged", "attempt_id": str(aid)})
    assert published == [(sid, "merged", {"attempt_id": aid, "via": "ws"})]
    # scoped to the user's own attempts
    assert "user_id" in db.queries[0] and "company_id" in db.queries[0]


async def test_signal_for_someone_elses_attempt_is_dropped(relay):
    published, with_session = relay
    with_session(None)
    user = SimpleNamespace(id=uuid4(), company_id=uuid4())
    await push_gateway._relay_signal(user, {"signal": "merged", "attempt_id": str(uuid4())})
    assert published == []


@pytest.mark.parametrize("msg", [
    {"signal": "abort", "attempt_id": str(uuid4())},      # only lead_answered / merged
    {"signal": "merged", "attempt_id": "not-a-uuid"},
    {"signal": "merged"},
])
async def test_bad_signals_are_ignored(relay, msg):
    published, with_session = relay
    with_session(uuid4())
    await push_gateway._relay_signal(SimpleNamespace(id=uuid4(), company_id=uuid4()), msg)
    assert published == []


def test_merge_requested_is_a_known_event():
    from src.mobile.service import KNOWN_EVENTS

    assert "merge_requested" in KNOWN_EVENTS
