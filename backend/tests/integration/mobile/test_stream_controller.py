"""Stream-handler behaviour for mobile AI legs, with a fake provider socket and fake Gemini session."""
import asyncio
import json
from collections import deque
from uuid import UUID, uuid4

import pytest

from src.ai.campaign_models import CampaignCall
from src.common.config import settings
from src.mobile import realtime
from src.mobile.identification import resolve_mobile_inbound
from src.mobile.models import MobileCallAttempt, UserDevice
from src.mobile.stream_controller import MobileCallController, PreModelOutcome
from src.voice.models import VoiceSession
from tests.integration.mobile.test_mobile_flow import (
    REP_CLI, create_campaign, new_attempt, start_and_lease, verified_device,
)


class FakeProviderSocket:
    def __init__(self, events=()):
        self.inbox = asyncio.Queue()
        self.sent = []
        for e in events:
            self.feed(e)

    def feed(self, event):
        self.inbox.put_nowait(json.dumps(event))

    async def receive_text(self):
        return await self.inbox.get()

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    async def close(self, *a, **k):
        pass


class FakeGemini:
    def __init__(self):
        self.texts = []
        self.audio_bytes = 0

    async def send_realtime_input(self, text=None, audio=None):
        if text:
            self.texts.append(text)
        if audio is not None:
            self.audio_bytes += len(audio.data)


class StubHandler:
    """The attributes MobileCallController touches on BaseStreamHandler."""

    def __init__(self, session, socket):
        self.voice_session = session
        self.session_id = session.id
        self.websocket = socket
        self.is_running = True
        self.stream_sid = None
        self.call_sid = session.call_sid
        self._provider_stopped = False
        self.gemini_session = FakeGemini()
        self.incoming_audio_buffer = deque()
        self._termination_reason = None
        self._voicemail_detected = False
        self._llm_disposition = None
        self.call_ended_at = None
        self._last_lead_speech_at = self._last_strong_speech_at = None
        self._last_lead_transcript_at = self._user_speech_end_time = None
        self._pipeline_started_at = self._greeting_sent_at = None

        self.played = []

    async def _play_model_audio(self, audio):
        self.played.append(audio)

    def _terminate_call(self, reason, disposition=None):
        self._termination_reason = reason
        self.is_running = False

    async def _send_system_text(self, text):
        await self.gemini_session.send_realtime_input(text=text)


def start_event():
    return {"event": "start", "start": {"streamSid": f"MZ{uuid4().hex}", "callSid": f"CA{uuid4().hex}"}}


def dtmf_events(sequence):
    return [{"event": "dtmf", "dtmf": {"digit": d}} for d in sequence]


@pytest.fixture
def fast_timeouts(monkeypatch):
    monkeypatch.setattr(settings, "MOBILE_IDENT_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(settings, "MOBILE_DTMF_CONFIRM_WAIT_SECONDS", 1)
    monkeypatch.setattr(settings, "MOBILE_VERIFICATION_MAX_CALL_SECONDS", 2)


async def bound_call(api, world, db):
    campaign_id, _ = await create_campaign(api, world, world.admin, assignees=[world.rep])
    device_id = await verified_device(api, db, world, world.rep, REP_CLI)
    run_id, lease = await start_and_lease(api, world.rep, campaign_id, device_id)
    attempt = await new_attempt(api, world.rep, run_id, lease, device_id)
    session = await resolve_mobile_inbound(db, from_number=REP_CLI, to_number=world.did,
                                           call_sid=f"pending_{uuid4().hex}", provider="tata_tele")
    return attempt, lease, session


async def collect_push(user_id, count=1):
    got = []

    async def run():
        async for msg in realtime.subscribe(realtime.user_push_channel(user_id)):
            got.append(msg)
            if len(got) >= count:
                return

    task = asyncio.create_task(run())
    await asyncio.sleep(0.3)
    return got, task


async def test_pre_model_confirms_cli_binding_with_dtmf(api, world, db, fast_timeouts):
    attempt, _, session = await bound_call(api, world, db)
    sock = FakeProviderSocket([start_event(), *dtmf_events(f"*{attempt['dtmf_token']}#")])
    ctl = MobileCallController(StubHandler(session, sock))
    assert await ctl.pre_model_phase() == PreModelOutcome.CONTINUE
    assert ctl.dtmf_confirmed and ctl.meta["identification"]["method"] == "cli+dtmf"


async def test_pre_model_device_verification_ends_call(api, world, db, fast_timeouts):
    r = await api.as_user(world.rep).post("/api/v1/mobile/devices", json={"install_id": uuid4().hex})
    verification = r.json()["verification"]
    session = await resolve_mobile_inbound(db, from_number=REP_CLI, to_number=world.did,
                                           call_sid="CA-v", provider="tata_tele")
    pushes, task = await collect_push(world.rep.id)
    sock = FakeProviderSocket([start_event(), *dtmf_events(verification["dtmf_sequence"])])
    ctl = MobileCallController(StubHandler(session, sock))
    assert await ctl.pre_model_phase() == PreModelOutcome.END
    await asyncio.wait_for(task, 5)
    assert pushes[0]["type"] == "device.verified" and pushes[0]["verified_cli"] == REP_CLI
    ended = await db.get(VoiceSession, session.id, populate_existing=True)
    assert ended.status == "ended"


async def test_pre_model_verifies_by_caller_id_when_the_tones_are_lost(api, world, db, fast_timeouts):
    """Carriers do drop DTMF on the AI leg; the announced dial makes the caller
    ID enough on its own."""
    rep = api.as_user(world.rep)
    device_id = (await rep.post("/api/v1/mobile/devices", json={"install_id": uuid4().hex})).json()["device_id"]
    r = await rep.post(f"/api/v1/mobile/devices/{device_id}/verification/dialing",
                       json={"sim_number": REP_CLI})
    assert r.status_code == 200 and r.json()["recorded"], r.text
    try:
        session = await resolve_mobile_inbound(db, from_number=REP_CLI, to_number=world.did,
                                               call_sid="CA-no-dtmf", provider="tata_tele")
        pushes, task = await collect_push(world.rep.id)
        ctl = MobileCallController(StubHandler(session, FakeProviderSocket([start_event()])))
        assert await ctl.pre_model_phase() == PreModelOutcome.END  # no dtmf events at all
        await asyncio.wait_for(task, 5)
        assert pushes[0]["type"] == "device.verified" and pushes[0]["verified_cli"] == REP_CLI
        device = await db.get(UserDevice, UUID(device_id), populate_existing=True)
        assert device.status == "verified" and device.verified_cli == REP_CLI
    finally:
        await realtime.clear_verification_dial(world.did)


async def test_pre_model_will_not_verify_a_different_caller(api, world, db, fast_timeouts):
    rep = api.as_user(world.rep)
    device_id = (await rep.post("/api/v1/mobile/devices", json={"install_id": uuid4().hex})).json()["device_id"]
    await rep.post(f"/api/v1/mobile/devices/{device_id}/verification/dialing", json={"sim_number": REP_CLI})
    try:
        session = await resolve_mobile_inbound(db, from_number="+919000000123", to_number=world.did,
                                               call_sid="CA-stranger", provider="tata_tele")
        ctl = MobileCallController(StubHandler(session, FakeProviderSocket([start_event()])))
        await ctl.pre_model_phase()
        device = await db.get(UserDevice, UUID(device_id), populate_existing=True)
        assert device.status == "unverified" and device.verified_cli is None
    finally:
        await realtime.clear_verification_dial(world.did)


async def test_pre_model_unknown_caller_falls_back_to_inbound(api, world, db, fast_timeouts):
    await api.as_user(world.rep).post("/api/v1/mobile/devices", json={"install_id": uuid4().hex})
    session = await resolve_mobile_inbound(db, from_number="+919000000000", to_number=world.did,
                                           call_sid="CA-cust", provider="tata_tele")
    assert session.session_metadata["fallback_inbound"]
    ctl = MobileCallController(StubHandler(session, FakeProviderSocket([start_event()])))
    assert await ctl.pre_model_phase() == PreModelOutcome.FALLBACK_INBOUND
    fresh = await db.get(VoiceSession, session.id, populate_existing=True)
    assert fresh.session_metadata["mode"] is None and fresh.session_metadata["mobile_fallback"]


async def test_pre_model_caller_hangs_up(api, world, db, fast_timeouts):
    _, _, session = await bound_call(api, world, db)
    ctl = MobileCallController(StubHandler(session, FakeProviderSocket([start_event(), {"event": "stop"}])))
    # bound by CLI: still waiting for DTMF confirmation when the stop arrives
    assert await ctl.pre_model_phase() == PreModelOutcome.END
    ended = await db.get(VoiceSession, session.id, populate_existing=True)
    assert ended.status == "ended" and ended.session_metadata["end_reason"] == "caller_hung_up"


async def test_ready_merge_greeting_and_cleanup(api, world, db, fast_timeouts):
    attempt, lease, session = await bound_call(api, world, db)
    handler = StubHandler(session, FakeProviderSocket([start_event()]))
    ctl = MobileCallController(handler)
    assert await ctl.pre_model_phase() == PreModelOutcome.CONTINUE

    pushes, task = await collect_push(world.rep.id)
    await ctl.on_model_connected()
    await asyncio.wait_for(task, 5)
    assert pushes[0]["type"] == "attempt.ai_ready" and pushes[0]["identification"] == "cli"
    row = await db.get(MobileCallAttempt, attempt["attempt_id"], populate_existing=True)
    assert row.status == "ai_ready"

    listener = asyncio.create_task(ctl.control_listener())
    await asyncio.sleep(0.3)
    r = await api.as_user(world.rep).post(f"/api/v1/mobile/call-attempts/{attempt['attempt_id']}/events",
                                          json={"events": [{"seq": 1, "type": "merged"}]})
    assert r.status_code == 200
    for _ in range(50):
        if ctl.merged:
            break
        await asyncio.sleep(0.1)
    assert ctl.merged
    assert handler.gemini_session.texts and "has now joined the call" in handler.gemini_session.texts[-1]
    assert "(Asha)" in handler.gemini_session.texts[-1] or "(Ravi)" in handler.gemini_session.texts[-1]

    handler.is_running = False
    handler._termination_reason = "model_end_call:conversation_complete"
    listener.cancel()
    await ctl.on_cleanup()
    row = await db.get(MobileCallAttempt, attempt["attempt_id"], populate_existing=True)
    assert row.status == "completed" and row.conversation_seconds is not None


async def test_lead_answered_event_pre_rolls_the_greeting(api, world, db, fast_timeouts):
    attempt, lease, session = await bound_call(api, world, db)
    handler = StubHandler(session, FakeProviderSocket([start_event()]))
    ctl = MobileCallController(handler)
    await ctl.pre_model_phase()
    await ctl.on_model_connected()
    listener = asyncio.create_task(ctl.control_listener())
    await asyncio.sleep(0.3)

    url = f"/api/v1/mobile/call-attempts/{attempt['attempt_id']}/events"
    r = await api.as_user(world.rep).post(url, json={"events": [
        {"seq": 1, "type": "lead_answered"}, {"seq": 2, "type": "merge_requested", "payload": {"attempt": "1"}},
    ]})
    assert r.status_code == 200 and r.json()["accepted"] == [1, 2]
    for _ in range(50):
        if ctl.greeting_prerolled_at:
            break
        await asyncio.sleep(0.1)
    assert ctl.greeting_prerolled_at and not ctl.merged
    ctl.hold_model_audio(b"greeting")

    r = await api.as_user(world.rep).post(url, json={"events": [{"seq": 3, "type": "merged"}]})
    assert r.status_code == 200
    for _ in range(50):
        if ctl.merged:
            break
        await asyncio.sleep(0.1)
    assert handler.played == [b"greeting"]
    assert len(handler.gemini_session.texts) == 1  # greeted once, before the merge
    handler.is_running = False
    listener.cancel()
    ctl._lead_audio_task.cancel()


async def test_cleanup_before_merge_returns_lead(api, world, db, fast_timeouts):
    attempt, lease, session = await bound_call(api, world, db)
    handler = StubHandler(session, FakeProviderSocket([start_event()]))
    ctl = MobileCallController(handler)
    await ctl.pre_model_phase()
    await ctl.on_model_connected()
    handler._termination_reason = "merge_timeout"
    await ctl.on_cleanup()
    row = await db.get(MobileCallAttempt, attempt["attempt_id"], populate_existing=True)
    call = await db.get(CampaignCall, lease["campaign_call_id"], populate_existing=True)
    assert row.status == "abandoned" and row.end_reason == "merge_timeout"
    assert call.status == "pending" and call.retry_count == 1


async def test_dtmf_hash_merge_fallback(api, world, db, fast_timeouts):
    attempt, lease, session = await bound_call(api, world, db)
    handler = StubHandler(session, FakeProviderSocket([start_event()]))
    ctl = MobileCallController(handler)
    await ctl.pre_model_phase()
    await ctl.on_model_connected()
    await ctl.on_dtmf("#")
    assert ctl.merged
    row = await db.get(MobileCallAttempt, attempt["attempt_id"], populate_existing=True)
    call = await db.get(CampaignCall, lease["campaign_call_id"], populate_existing=True)
    assert row.status == "merged" and call.status == "calling"


async def test_late_conflicting_token_ends_leg(api, world, db, fast_timeouts):
    from tests.integration.mobile.test_mobile_flow import REP2_CLI

    campaign_id, _ = await create_campaign(api, world, world.admin, assignees=[world.rep, world.rep2])
    d1 = await verified_device(api, db, world, world.rep, REP_CLI)
    d2 = await verified_device(api, db, world, world.rep2, REP2_CLI)
    run1, lease1 = await start_and_lease(api, world.rep, campaign_id, d1)
    run2, lease2 = await start_and_lease(api, world.rep2, campaign_id, d2)
    await new_attempt(api, world.rep, run1, lease1, d1)
    a2 = await new_attempt(api, world.rep2, run2, lease2, d2)
    session = await resolve_mobile_inbound(db, from_number=REP_CLI, to_number=world.did,
                                           call_sid="CA-late-conflict", provider="tata_tele")
    handler = StubHandler(session, FakeProviderSocket([start_event()]))
    ctl = MobileCallController(handler)
    await ctl.pre_model_phase()  # no DTMF in time: proceeds on CLI
    for d in f"*{a2['dtmf_token']}#":
        await ctl.on_dtmf(d)
    assert handler._termination_reason == "identification_conflict"


async def test_handler_feeds_silence_before_merge():
    """BaseStreamHandler gate: pre-merge inbound audio reaches the model as zeros only."""
    from src.voice.websocket_handler import BaseStreamHandler

    handler = BaseStreamHandler(FakeProviderSocket(), db=None)
    handler.gemini_session = FakeGemini()
    handler.is_running = True

    class NotMerged:
        merged = False

    handler.mobile = NotMerged()
    loud = bytes([0x00, 0x10] * 80)  # loud μ-law frame
    handler.incoming_audio_buffer.append(loud)
    task = asyncio.create_task(handler._process_incoming_audio())
    await asyncio.sleep(0.1)
    handler.is_running = False
    await asyncio.wait_for(task, 2)
    assert handler.gemini_session.audio_bytes == len(loud) * 4
    assert handler._last_lead_speech_at is None  # guards never saw the pre-merge audio
