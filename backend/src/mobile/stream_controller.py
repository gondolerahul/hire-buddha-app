"""
Mobile-conference behaviour for a live AI leg (docs 04 §8, ADR-001 §5).

``BaseStreamHandler`` owns the audio pipeline; for sessions whose
``session_metadata.mode == "mobile_conference"`` it delegates to this
controller at a handful of hooks:

  pre_model_phase()   read provider events before the model exists: collect
                      DTMF tokens / verification codes, wait for binding
  on_model_connected() push ai_ready / unidentified to the rep's app
  control_listener()  Redis subscriber: merged / abort / rep_takeover
  on_dtmf()           late DTMF after the model is connected
  on_merged()         lift the audio gate and trigger the greeting
  on_cleanup()        attempt + campaign-call bookkeeping, push ai_ended

The handler keeps the model muted (zeros in, audio out dropped) until merged.
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
from src.mobile.identification import bind_session_by_token, complete_device_verification
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
                await realtime.publish_user_push(
                    result.user_id, "device.verified", device_id=result.device_id,
                    verified_cli=result.verified_cli, cli_available=result.cli_available,
                )
                await self._end_session("device_verified")
                return PreModelOutcome.END
        else:
            logger.info(f"[Mobile] Ignoring pre-model DTMF {seq.kind} on session {self.h.session_id}")
        return None

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
            await self.on_merged("api")
        elif mtype == "abort":
            self.h._terminate_call(f"abort:{msg.get('reason') or 'app'}")
        elif mtype == "rep_takeover":
            self.h._terminate_call("rep_takeover")

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
                            lease_expires_at=None)
                )
            await db.commit()

    async def on_merged(self, source: str):
        if self.merged:
            return
        h = self.h
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

        contact = self.meta.get("contact_data") or {}
        name = contact.get("name") or contact.get("Name")
        who = f"The lead{f' ({name})' if name else ''}"
        greeting = (
            f"[{who} has now joined the call. Greet them"
            f"{' by name' if name else ''}, introduce yourself, and begin the conversation.]"
        )
        try:
            await h.gemini_session.send_realtime_input(text=greeting)
            h._greeting_sent_at = time.time()
        except Exception as e:
            logger.warning(f"[Mobile] Greeting trigger failed for {h.session_id}: {e}")
        logger.info(f"[Mobile] Merged ({source}) — greeting sent for session {h.session_id}")

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
