"""
Mobile-conference behaviour for a live AI leg (docs 04 §8, ADR-001 §5).

``BaseStreamHandler`` owns the audio pipeline; for sessions whose
``session_metadata.mode == "mobile_conference"`` it delegates to this
controller at a handful of hooks:

  pre_model_phase()   read provider events before the model exists: collect
                      DTMF tokens / verification codes, wait for binding
  on_model_connected() push ai_ready / unidentified to the rep's app
  control_listener()  Redis subscriber: lead_answered / merged / abort / rep_takeover
  on_dtmf()           late DTMF after the model is connected
  on_lead_answered()  pre-roll the greeting while the phone merges the calls
  on_merged()         lift the audio gate and play (or trigger) the greeting
  on_cleanup()        attempt + campaign-call bookkeeping, push ai_ended

The handler keeps the model muted (zeros in, audio out dropped) until merged,
except for a pre-rolled greeting, which is held and played the moment the lead joins.
"""
import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import and_, select, update

from src.common.config import settings
from src.common.database import AsyncSessionLocal
from src.mobile import realtime
from src.mobile.dtmf import (
    KIND_ATTEMPT_TOKEN, KIND_MERGE_SIGNAL, KIND_VERIFICATION_CODE, DtmfCollector,
)
from src.mobile.identification import (
    bind_session_by_token, complete_device_verification, verify_device_by_cli,
)
from src.mobile.models import (
    ATTEMPT_ABANDONED, ATTEMPT_AI_READY, ATTEMPT_COMPLETED, ATTEMPT_COMPLETED_VOICEMAIL,
    ATTEMPT_MERGED, ATTEMPT_UNIDENTIFIED_READY, IDENT_UNIDENTIFIED, OPEN_ATTEMPT_STATUSES,
    SESSION_MODE_MOBILE, MobileCallAttempt, UserDevice,
)

logger = logging.getLogger(__name__)

CONFERENCE_PROMPT_ADDENDUM = """

## Live conference call context
You are joining a live phone call that {rep} from {company} placed to the lead. The representative is on the line and may be listening; they may unmute and speak.
- Address the lead by name if you know it, and introduce yourself as an AI assistant calling on behalf of {company}.
- Mention early that the call may be recorded.
- If the representative starts speaking to the lead, stop talking and let them lead the conversation.
- Stay silent until you are told the lead has joined."""


def conference_prompt_addendum(session_metadata: Optional[Dict[str, Any]]) -> str:
    meta = session_metadata or {}
    return CONFERENCE_PROMPT_ADDENDUM.format(
        rep=meta.get("rep_name") or "a sales representative",
        company=meta.get("company_name") or "the company",
    )


class PreModelOutcome:
    CONTINUE = "continue"          # run the mobile pipeline
    FALLBACK_INBOUND = "fallback"  # not a mobile call after all: normal inbound flow
    END = "end"                    # verification done / caller hung up


# Take over: time for the model to start the hand-over line, and the most we wait for
# it to finish playing before the agent leaves anyway.
HANDOVER_START_SECONDS = 1.5
HANDOVER_MAX_SECONDS = 10
# A lead who can hear the agent answers its greeting within a few seconds.
LEAD_AUDIO_GRACE_SECONDS = 8
# The most pre-rolled greeting kept for the merge: 24 kHz 16-bit PCM, 20 s.
MAX_HELD_AUDIO_BYTES = 24_000 * 2 * 20


class MobileCallController:
    def __init__(self, handler):
        self.h = handler
        self.collector = DtmfCollector()
        self.merged = False
        self.merged_at: Optional[float] = None
        self.ai_ready_at: Optional[float] = None
        self.stream_started_at: Optional[float] = None
        self.dtmf_confirmed = False
        self._merged_event = asyncio.Event()
        self._last_error_push = 0.0
        self._handover_task: Optional[asyncio.Task] = None
        self._lead_audio_task: Optional[asyncio.Task] = None
        # Greeting started when the lead answered; its audio waits here for the merge.
        self.greeting_prerolled_at: Optional[float] = None
        self._held_audio: list = []
        self._held_bytes = 0
        self._merging = False

    # ── metadata helpers ────────────────────────────────────────────────

    @property
    def meta(self) -> Dict[str, Any]:
        return self.h.voice_session.session_metadata or {}

    @property
    def bound(self) -> bool:
        return bool(self.meta.get("bound"))

    @property
    def attempt_id(self) -> Optional[UUID]:
        value = self.meta.get("attempt_id")
        return UUID(value) if value else None

    @property
    def user_id(self) -> Optional[str]:
        return self.meta.get("user_id")

    async def _reload_session(self):
        from src.voice.models import VoiceSession

        async with AsyncSessionLocal() as db:
            fresh = await db.get(VoiceSession, self.h.session_id)
            if fresh is not None:
                self.h.voice_session = fresh

    async def _fcm_token(self) -> Optional[str]:
        device_id = self.meta.get("device_id")
        if not device_id:
            return None
        async with AsyncSessionLocal() as db:
            return (await db.execute(
                select(UserDevice.fcm_token).where(UserDevice.id == UUID(device_id))
            )).scalar_one_or_none()

    async def _push(self, msg_type: str, user_id: Optional[str] = None, **fields):
        uid = user_id or self.user_id
        if not uid:
            return
        await realtime.publish_user_push(uid, msg_type, fcm_token=await self._fcm_token(),
                                         session_id=self.h.session_id, **fields)

    async def on_transcript(self, speaker: str, text: str):
        """Stream a finished transcript turn to the rep's run screen (docs 11 §3, screen 16).

        Best effort and deliberately silent on failure: the rep reading along must
        never be able to affect the call. No FCM — this is only useful to someone
        with the screen open, and waking the phone per turn would be noisy."""
        if not self.bound or not self.merged:
            return
        try:
            uid = self.user_id
            if not uid:
                return
            await realtime.publish_user_push(
                uid, "attempt.transcript",
                session_id=self.h.session_id,
                attempt_id=str(self.attempt_id) if self.attempt_id else None,
                speaker="agent" if speaker == "agent" else "lead",
                text=text[:1000],
                at=datetime.utcnow(),
            )
        except Exception:  # noqa: BLE001 - never let a UI nicety touch the call
            logger.debug("[Mobile] transcript push failed", exc_info=True)

    # ── pre-model phase ─────────────────────────────────────────────────

    async def pre_model_phase(self) -> str:
        """Read provider events until the session is identified or times out."""
        h = self.h
        if h.stream_sid:  # Tata direct path already consumed 'start'
            self.stream_started_at = time.time()
        overall_deadline = time.time() + max(settings.MOBILE_IDENT_TIMEOUT_SECONDS,
                                             settings.MOBILE_VERIFICATION_MAX_CALL_SECONDS) + 5

        while h.is_running:
            now = time.time()
            decision = self._pre_model_decision(now)
            if decision:
                return await self._finish_pre_model(decision)
            if now > overall_deadline:
                return await self._finish_pre_model("timeout")

            try:
                raw = await asyncio.wait_for(h.websocket.receive_text(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.info(f"[Mobile] Provider socket closed before identification: {e}")
                h._provider_stopped = True
                await self._end_session("socket_closed")
                return PreModelOutcome.END

            event = json.loads(raw)
            etype = event.get("event")
            if etype == "start":
                await self._on_start(event)
            elif etype == "dtmf":
                outcome = await self._on_pre_model_dtmf(event)
                if outcome:
                    return outcome
            elif etype == "stop":
                h._provider_stopped = True
                await self._end_session("caller_hung_up")
                return PreModelOutcome.END
            # media before the model exists is discarded (hold tones, DTMF audio)
        return PreModelOutcome.END

    def _pre_model_decision(self, now: float) -> Optional[str]:
        if self.stream_started_at is None:
            return None
        elapsed = now - self.stream_started_at
        if self.bound:
            method = (self.meta.get("identification") or {}).get("method")
            if self.dtmf_confirmed or method != "cli" or elapsed >= settings.MOBILE_DTMF_CONFIRM_WAIT_SECONDS:
                return "bound"
            return None
        if self.collector.in_sequence:
            return None  # a code is mid-entry; don't cut it off
        if self.meta.get("expects_verification") and not self.meta.get("expects_attempt"):
            limit = settings.MOBILE_VERIFICATION_MAX_CALL_SECONDS
        else:
            limit = settings.MOBILE_IDENT_TIMEOUT_SECONDS
        return "timeout" if elapsed >= limit else None

    async def _on_start(self, event: Dict[str, Any]):
        h = self.h
        start = event.get("start", {})
        h.stream_sid = start.get("streamSid")
        h.call_sid = start.get("callSid") or h.call_sid
        self.stream_started_at = time.time()
        updates = {"stream_sid": h.stream_sid, "status": "active"}
        if h.call_sid and (h.voice_session.call_sid or "").startswith("pending_"):
            updates["call_sid"] = h.call_sid
        async with AsyncSessionLocal() as db:
            from src.voice.session_manager import SessionManager
            await SessionManager(db).update_voice_session(h.session_id, updates)

    async def _on_pre_model_dtmf(self, event: Dict[str, Any]) -> Optional[str]:
        digit = (event.get("dtmf") or {}).get("digit")
        seq = self.collector.feed(digit, time.time())
        if seq is None:
            return None
        if seq.kind == KIND_ATTEMPT_TOKEN:
            await self._apply_token(seq.value, model_connected=False)
        elif seq.kind == KIND_VERIFICATION_CODE and self.meta.get("expects_verification"):
            async with AsyncSessionLocal() as db:
                result = await complete_device_verification(db, self.h.session_id, seq.value)
            if result:
                await self._announce_verified(result)
                await self._end_session("device_verified")
                return PreModelOutcome.END
        else:
            logger.info(f"[Mobile] Ignoring pre-model DTMF {seq.kind} on session {self.h.session_id}")
        return None

    async def _announce_verified(self, result):
        await realtime.publish_user_push(
            result.user_id, "device.verified", device_id=result.device_id,
            verified_cli=result.verified_cli, cli_available=result.cli_available,
        )

    async def _apply_token(self, token: str, model_connected: bool):
        async with AsyncSessionLocal() as db:
            result = await bind_session_by_token(db, self.h.session_id, token)
        if result.status == "no_match":
            return
        was_bound_attempt = self.attempt_id
        await self._reload_session()
        if result.status == "confirmed":
            self.dtmf_confirmed = True
            return
        self.dtmf_confirmed = True
        if not model_connected:
            return
        if result.status == "rebound" or (was_bound_attempt and was_bound_attempt != result.attempt_id):
            # The agent was loaded with the wrong lead's context: never let it
            # greet the wrong person. End this leg; the app retries the lead.
            logger.warning(f"[Mobile] Late identification conflict on {self.h.session_id}; ending AI leg")
            self.h._terminate_call("identification_conflict")
            return
        # Late bind of a session that started unidentified: brief the model.
        contact = self.meta.get("contact_data") or {}
        details = "; ".join(f"{k}: {v}" for k, v in contact.items() if k.lower() != "phone" and v)
        await self.h._send_system_text(
            f"[SYSTEM: The lead for this call has been identified. Lead details — {details}. "
            f"Stay silent until the lead joins.]"
        )
        await self._mark_ready()

    async def _finish_pre_model(self, decision: str) -> str:
        if decision == "bound":
            return PreModelOutcome.CONTINUE
        # A verification call whose keypad tones never reached us: the caller ID
        # is the thing the call was placed to capture anyway (ADR-001 §1).
        if self.meta.get("expects_verification") and not self.meta.get("expects_attempt"):
            async with AsyncSessionLocal() as db:
                result = await verify_device_by_cli(db, self.h.session_id)
            if result:
                await self._announce_verified(result)
                await self._end_session("device_verified_cli")
                return PreModelOutcome.END
        # timeout without binding
        if self.meta.get("fallback_inbound"):
            logger.info(f"[Mobile] No mobile code on {self.h.session_id}; continuing as a normal inbound call")
            meta = dict(self.meta)
            meta.update({"mode": None, "mobile_fallback": True})
            async with AsyncSessionLocal() as db:
                from src.voice.session_manager import SessionManager
                await SessionManager(db).update_voice_session(self.h.session_id, {"session_metadata": meta})
            self.h.voice_session.session_metadata = meta
            return PreModelOutcome.FALLBACK_INBOUND
        if self.meta.get("expects_attempt"):
            meta = dict(self.meta)
            meta["identification"] = {"method": IDENT_UNIDENTIFIED, "at": datetime.utcnow().isoformat() + "Z"}
            async with AsyncSessionLocal() as db:
                from src.voice.session_manager import SessionManager
                await SessionManager(db).update_voice_session(self.h.session_id, {"session_metadata": meta})
            self.h.voice_session.session_metadata = meta
            logger.warning(f"[Mobile] Session {self.h.session_id} unidentified after timeout; starting agent without lead context")
            return PreModelOutcome.CONTINUE
        await self._end_session("verification_timeout")
        return PreModelOutcome.END

    async def _end_session(self, reason: str):
        h = self.h
        h.call_ended_at = datetime.utcnow()
        started = h.voice_session.started_at or h.call_ended_at
        async with AsyncSessionLocal() as db:
            from src.voice.session_manager import SessionManager
            meta = dict(self.meta)
            meta["end_reason"] = reason
            await SessionManager(db).update_voice_session(h.session_id, {"session_metadata": meta})
            await SessionManager(db).end_voice_session(
                h.session_id, duration_seconds=max(int((h.call_ended_at - started).total_seconds()), 0)
            )
        logger.info(f"[Mobile] Session {h.session_id} ended before the model started: {reason}")

    # ── model connected ─────────────────────────────────────────────────

    async def on_model_connected(self):
        self.ai_ready_at = time.time()
        await self._mark_ready()

    async def _known_user_for_unbound(self) -> Optional[str]:
        caller = self.meta.get("caller")
        if not caller:
            return None
        async with AsyncSessionLocal() as db:
            return (await db.execute(
                select(UserDevice.user_id).where(and_(
                    UserDevice.company_id == self.h.voice_session.company_id,
                    UserDevice.verified_cli == caller,
                )).limit(1)
            )).scalar_one_or_none()

    async def _mark_ready(self):
        attempt_id = self.attempt_id
        if attempt_id is None:
            user_id = await self._known_user_for_unbound()
            if user_id:
                await self._push("attempt.unidentified", user_id=str(user_id))
            return
        identified = self.bound
        now = datetime.utcnow()
        async with AsyncSessionLocal() as db:
            attempt = (await db.execute(
                update(MobileCallAttempt)
                .where(and_(MobileCallAttempt.id == attempt_id,
                            MobileCallAttempt.status.in_(("pending", "ai_connected", "unidentified_ready"))))
                .values(status=ATTEMPT_AI_READY if identified else ATTEMPT_UNIDENTIFIED_READY,
                        ai_ready_at=now, updated_at=now)
                .returning(MobileCallAttempt.status)
            )).scalar_one_or_none()
            await db.commit()
            current = attempt or (await db.execute(
                select(MobileCallAttempt.status).where(MobileCallAttempt.id == attempt_id)
            )).scalar_one_or_none()
        ident = (self.meta.get("identification") or {}).get("method")
        contact = self.meta.get("contact_data") or {}
        await self._push("attempt.ai_ready", attempt_id=attempt_id, identification=ident,
                         lead_name=contact.get("name") or contact.get("Name"))
        if current == ATTEMPT_MERGED:
            await self.on_merged("db")

    # ── control channel ─────────────────────────────────────────────────

    async def control_listener(self):
        """Runs as a pipeline task for the whole call. Must not return early:
        the handler tears the call down when any task finishes."""
        channel = realtime.session_control_channel(self.h.session_id)
        try:
            await self._check_db_merged()
            async for msg in realtime.subscribe(channel):
                if not self.h.is_running:
                    break
                await self._on_control(msg)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"[Mobile] Control channel failed for {self.h.session_id} ({e}); polling the DB")
            while self.h.is_running:
                await asyncio.sleep(1.0)
                await self._check_db_merged()
        # Keep the task alive until the call ends for another reason.
        while self.h.is_running:
            await asyncio.sleep(1.0)

    async def _check_db_merged(self):
        if self.merged or self.attempt_id is None:
            return
        async with AsyncSessionLocal() as db:
            status = (await db.execute(
                select(MobileCallAttempt.status).where(MobileCallAttempt.id == self.attempt_id)
            )).scalar_one_or_none()
        if status == ATTEMPT_MERGED:
            await self.on_merged("db")
        elif status is not None and status not in OPEN_ATTEMPT_STATUSES:
            self.h._terminate_call(f"attempt_{status}")

    async def _on_control(self, msg: Dict[str, Any]):
        mtype = msg.get("type")
        logger.info(f"[Mobile] Control '{mtype}' for session {self.h.session_id}")
        if mtype == "merged":
            await self.on_merged(msg.get("via") or "api")
        elif mtype == "lead_answered":
            await self.on_lead_answered()
        elif mtype == "abort":
            self.h._terminate_call(f"abort:{msg.get('reason') or 'app'}")
        elif mtype == "rep_takeover":
            if self._handover_task is None:
                self._handover_task = asyncio.create_task(self._hand_over_to_rep())

    async def _hand_over_to_rep(self):
        """The rep pressed Take over (wireframe 16).

        The lead must not hear the agent simply vanish mid-sentence: the model says one
        short hand-over line in the language of the call, the provider plays it out,
        and only then does the agent leave. The app keeps the rep muted until the
        ai_ended push (reason rep_takeover) arrives, so the two never talk over each other.
        """
        h = self.h
        if not self.merged or not h.is_running:
            h._terminate_call("rep_takeover")
            return
        try:
            await h.gemini_session.send_realtime_input(text=(
                "[The rep, your senior colleague, is taking over this call now. Stop what you "
                "were saying. In one short, polite sentence, in the language you have been "
                "speaking with the lead, tell them you are transferring the call to your senior "
                "colleague who will take it from here. Say nothing after that.]"
            ))
            logger.info(f"[Mobile] Hand-over line requested for session {h.session_id}")
            # Give the model a moment to start, then let the provider's buffer drain.
            await asyncio.sleep(HANDOVER_START_SECONDS)
            await h._wait_for_playback_drain(max_wait_seconds=HANDOVER_MAX_SECONDS)
        except Exception as e:
            logger.warning(f"[Mobile] Hand-over line failed for {h.session_id}: {e}")
        h._terminate_call("rep_takeover")

    async def _watch_lead_audio(self):
        """No sound from the lead after the merge means the network conference is not
        carrying audio to or from the agent's line (seen on Jio IMS merges): the agent
        talks into silence and the lead hears nothing. The rep's phone is still bridged to
        the lead, so tell the app at once rather than let the agent call it voicemail."""
        h = self.h
        await asyncio.sleep(LEAD_AUDIO_GRACE_SECONDS)
        if not h.is_running or not self.merged:
            return
        if h._last_lead_speech_at is None and h._last_lead_transcript_at is None:
            logger.warning(f"[Mobile] No lead audio {LEAD_AUDIO_GRACE_SECONDS}s after merge "
                           f"for session {h.session_id}")
            await self._push("attempt.no_lead_audio", attempt_id=self.attempt_id,
                             seconds=str(LEAD_AUDIO_GRACE_SECONDS))

    # ── in-call hooks ───────────────────────────────────────────────────

    async def on_dtmf(self, digit: str):
        seq = self.collector.feed(digit, time.time())
        if seq is None:
            return
        if seq.kind == KIND_ATTEMPT_TOKEN:
            await self._apply_token(seq.value, model_connected=True)
        elif seq.kind == KIND_MERGE_SIGNAL and settings.MOBILE_DTMF_MERGE_FALLBACK and not self.merged:
            if self.ai_ready_at is not None:
                await self._persist_dtmf_merge()
                await self.on_merged("dtmf")

    async def _persist_dtmf_merge(self):
        from src.ai.campaign_models import CampaignCall

        attempt_id = self.attempt_id
        if attempt_id is None:
            return
        now = datetime.utcnow()
        async with AsyncSessionLocal() as db:
            attempt = (await db.execute(
                update(MobileCallAttempt)
                .where(and_(MobileCallAttempt.id == attempt_id,
                            MobileCallAttempt.status.in_((ATTEMPT_AI_READY, ATTEMPT_UNIDENTIFIED_READY))))
                .values(status=ATTEMPT_MERGED, merged_at=now, updated_at=now)
                .returning(MobileCallAttempt.campaign_call_id, MobileCallAttempt.device_id)
            )).first()
            if attempt:
                await db.execute(
                    update(CampaignCall)
                    .where(and_(CampaignCall.id == attempt.campaign_call_id, CampaignCall.status == "leased",
                                CampaignCall.leased_by_device_id == attempt.device_id))
                    .values(status="calling", leased_by_user_id=None, leased_by_device_id=None,
                            lease_expires_at=None, voice_session_id=self.h.session_id, called_at=now)
                )
            await db.commit()

    def _greeting_prompt(self) -> str:
        contact = self.meta.get("contact_data") or {}
        name = contact.get("name") or contact.get("Name")
        who = f"The lead{f' ({name})' if name else ''}"
        return (
            f"[{who} has now joined the call. Greet them"
            f"{' by name' if name else ''}, introduce yourself, and begin the conversation.]"
        )

    async def on_lead_answered(self):
        """The lead picked up and the phone is merging the calls (1-3 s on IMS).

        Generating the greeting costs ~0.7 s on top of that, all of it dead air for
        someone who just said "hello". Start it now: hold_model_audio() keeps its
        audio and on_merged() plays it the moment the lead can hear it.
        """
        h = self.h
        if self.merged or self._merging or self.greeting_prerolled_at or not h.gemini_session:
            return
        try:
            await h.gemini_session.send_realtime_input(text=self._greeting_prompt())
        except Exception as e:
            logger.warning(f"[Mobile] Greeting pre-roll failed for {h.session_id}: {e}")
            return
        self.greeting_prerolled_at = time.time()
        logger.info(f"[Mobile] Lead answered — greeting pre-rolled for session {h.session_id}")

    def hold_model_audio(self, audio: bytes):
        """Model audio produced before the merge: keep the pre-rolled greeting, drop the rest."""
        if self.greeting_prerolled_at is None or self._held_bytes + len(audio) > MAX_HELD_AUDIO_BYTES:
            return
        self._held_audio.append(audio)
        self._held_bytes += len(audio)

    async def on_merged(self, source: str):
        if self.merged or self._merging:
            return
        self._merging = True
        h = self.h
        prerolled = self.greeting_prerolled_at is not None
        if prerolled:
            # Play what the model already said, oldest first. Audio arriving meanwhile
            # is still pre-merge, so it lands at the end of the same list; nothing
            # awaits between the last pop and opening the gate below.
            while self._held_audio:
                await h._play_model_audio(self._held_audio.pop(0))
            self._held_bytes = 0
        self.merged = True
        self.merged_at = time.time()
        self._merged_event.set()
        # Pre-merge audio (hold tones, the rep) must not look like lead activity.
        h.incoming_audio_buffer.clear()
        h._last_lead_speech_at = None
        h._last_strong_speech_at = None
        h._last_lead_transcript_at = None
        h._user_speech_end_time = None
        h._pipeline_started_at = self.merged_at

        if prerolled:
            # The activity guards time the greeting from when the lead could hear it.
            h._greeting_sent_at = self.merged_at
            logger.info(
                f"[Mobile] Merged ({source}) — pre-rolled greeting playing "
                f"(started {self.merged_at - self.greeting_prerolled_at:.1f}s earlier) "
                f"for session {h.session_id}"
            )
        else:
            try:
                await h.gemini_session.send_realtime_input(text=self._greeting_prompt())
                h._greeting_sent_at = time.time()
            except Exception as e:
                logger.warning(f"[Mobile] Greeting trigger failed for {h.session_id}: {e}")
            logger.info(f"[Mobile] Merged ({source}) — greeting sent for session {h.session_id}")
        self._lead_audio_task = asyncio.create_task(self._watch_lead_audio())

    async def wait_merged(self):
        await self._merged_event.wait()

    def merge_wait_expired(self, now: float) -> bool:
        start = self.ai_ready_at or self.stream_started_at
        return bool(start and not self.merged and now - start > settings.MOBILE_MERGE_WAIT_SECONDS)

    # ── cleanup ─────────────────────────────────────────────────────────

    async def on_cleanup(self):
        from src.ai.campaign_models import CampaignCall

        h = self.h
        reason = h._termination_reason or ("provider_stop" if h._provider_stopped else "ended")
        attempt_id = self.attempt_id
        now = datetime.utcnow()
        if attempt_id is not None:
            async with AsyncSessionLocal() as db:
                attempt = await db.get(MobileCallAttempt, attempt_id, with_for_update=True)
                if attempt is not None and attempt.voice_session_id == h.session_id:
                    if attempt.status == ATTEMPT_MERGED or (self.merged and attempt.status in OPEN_ATTEMPT_STATUSES):
                        attempt.status = ATTEMPT_COMPLETED_VOICEMAIL if h._voicemail_detected else ATTEMPT_COMPLETED
                        attempt.ended_at = attempt.ended_at or now
                        start = attempt.merged_at or now
                        attempt.conversation_seconds = max(int((attempt.ended_at - start).total_seconds()), 0)
                        attempt.end_reason = attempt.end_reason or reason[:50]
                        from src.mobile.service import finish_merged_campaign_call
                        await finish_merged_campaign_call(
                            db, attempt.campaign_call_id, h.session_id, attempt.ended_at,
                            attempt.conversation_seconds, voicemail=h._voicemail_detected,
                        )
                    elif attempt.status in OPEN_ATTEMPT_STATUSES:
                        # AI leg ended before the lead joined: give the lead back.
                        attempt.status = ATTEMPT_ABANDONED
                        attempt.ended_at = now
                        attempt.end_reason = reason[:50]
                        await db.execute(
                            update(CampaignCall)
                            .where(and_(CampaignCall.id == attempt.campaign_call_id,
                                        CampaignCall.status == "leased",
                                        CampaignCall.leased_by_device_id == attempt.device_id))
                            .values(status="pending", leased_by_user_id=None, leased_by_device_id=None,
                                    lease_expires_at=None, retry_count=CampaignCall.retry_count + 1)
                        )
                    elif attempt.status in (ATTEMPT_COMPLETED, ATTEMPT_COMPLETED_VOICEMAIL):
                        if attempt.conversation_seconds is None and attempt.merged_at and attempt.ended_at:
                            attempt.conversation_seconds = int((attempt.ended_at - attempt.merged_at).total_seconds())
                        if h._voicemail_detected:
                            attempt.status = ATTEMPT_COMPLETED_VOICEMAIL
                    attempt.updated_at = now
                    await db.commit()

    async def notify_ended(self):
        """Tell the app immediately (before summaries/billing) so it drops the legs."""
        h = self.h
        if getattr(self, "_ended_notified", False):
            return
        self._ended_notified = True
        reason = h._termination_reason or ("provider_stop" if h._provider_stopped else "ended")
        user_id = self.user_id
        if user_id is None:
            known = await self._known_user_for_unbound()
            user_id = str(known) if known else None
        await self._push(
            "attempt.ai_ended",
            user_id=user_id,
            attempt_id=self.attempt_id,
            reason="voicemail" if h._voicemail_detected else reason,
        )
