"""
WebSocket Stream Handler for Twilio / Tata Tele Media Streams.

Architecture:
  BaseStreamHandler  ← shared state, audio pipeline, transcript, cleanup
    ├── TwilioStreamHandler  ← Twilio-specific session lookup + handle()
    └── TataStreamHandler    ← Tata-specific start-event parsing + handle_direct()

Fixes applied (Architectural Evolution Report):
  P0.1  Eliminated 300-line duplication via BaseStreamHandler
  P0.4  Audio recording streamed to temp disk file, not in-memory bytearray
  P1.5  _send_to_twilio no longer busy-loops with 10 ms timeout
  P1.6  incoming_audio_buffer capped at maxlen=200 (~1 sec backpressure)
"""
import logging
import time
import asyncio
import json
import base64
import os
import tempfile
import wave
from collections import deque
from typing import Optional, Dict, Any
from uuid import UUID
from datetime import datetime

from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from src.voice.audio_processor import AudioProcessor
from src.voice.session_manager import SessionManager
from src.voice.agent_loader import AgentContextLoader
from src.voice.live_client_factory import LiveClientFactory
from src.voice.conversation_logger import ConversationLogger
from src.voice.models import ConversationHistory, VoiceSession
from src.voice.number_router import NumberRouter
from src.voice.usage_logger import VoiceUsageLogger
from src.voice.call_guards import (
    ActivityState,
    END_CALL_SYSTEM_SUFFIX,
    END_CALL_TOOL,
    detect_voicemail_phrase,
    effective_agent_audio_at,
    evaluate_activity,
    parse_disposition,
    parse_not_interested_reason,
)
from src.billing.credit_service import CreditService
from src.billing.billing_service import BillingService
from src.common.config import settings
from src.common.database import AsyncSessionLocal
from decimal import Decimal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BaseStreamHandler — shared pipeline for all providers
# ---------------------------------------------------------------------------

class BaseStreamHandler:
    """
    Provider-agnostic bidirectional audio streaming handler.

    Subclasses supply provider-specific session discovery and call the
    shared _setup_live_and_run() once a VoiceSession is resolved.
    """

    def __init__(self, websocket: WebSocket, db: AsyncSession):
        self.websocket = websocket
        self.db = db

        self.session_manager = SessionManager(db)
        self.agent_loader = AgentContextLoader(db)
        self.audio_processor = AudioProcessor()
        self.conversation_logger = ConversationLogger(db)

        # Identity — resolved by subclasses before _setup_live_and_run
        self.session_id: Optional[UUID] = None
        self.stream_sid: Optional[str] = None
        self.call_sid: Optional[str] = None
        self.voice_session: Optional[VoiceSession] = None
        self.gemini_session = None
        self.is_running = False
        self.call_ended_at: Optional[datetime] = None
        self.started_at: Optional[datetime] = None

        # Audio — P1.6: cap incoming buffer to prevent unbounded growth
        # 100 packets ≈ 500ms at 8kHz / 20ms packets — favors responsiveness
        self.incoming_audio_buffer: deque = deque(maxlen=100)
        self.outgoing_audio_queue: asyncio.Queue = asyncio.Queue(maxsize=500)  # ~2.5s at 20ms/frame

        # Conversation tracking
        self.turn_number = 0
        self.outbound_chunk_counter = 0  # Required by Tata Tele spec: media.chunk counter
        self._agent_transcript_buffer = ""
        self._customer_transcript_buffer = ""
        self._last_transcript_time = 0.0

        # Phase 4: Telemetry — TTFB and interruption tracking
        self._user_speech_end_time: Optional[float] = None
        self._ttfb_logged = False

        # P0.4: Recording — streamed to a temp file not a bytearray
        # A 10-min 8k PCM call ≈ 9.6 MB; held entirely in RAM was an OOM risk
        self._recording_tmp_path: Optional[str] = None
        self._recording_tmp_file = None          # raw binary file handle
        self._outbound_recording_buffer = bytearray()   # small rolling buffer for mix

        # Issue #7: Configurable call duration limit
        self.max_call_duration_seconds: int = 300  # Default 5 min, overridden by agent config

        # Call guardrails — activity timestamps (time.time()) + termination state
        self._pipeline_started_at: Optional[float] = None
        self._greeting_sent_at: Optional[float] = None
        self._first_audio_received = False
        self._first_agent_audio_sent_at: Optional[float] = None
        self._last_agent_audio_at: Optional[float] = None
        # Playback horizon: audio is sent to the provider in fast bursts but
        # plays out in real time from the provider's buffer (8kHz μ-law).
        self._agent_playback_until: float = 0.0
        # Rolling loudness of the agent's own audio — the echo gate threshold
        # scales with it (echo is an attenuated copy of the agent's voice).
        self._agent_audio_rms_ema: Optional[float] = None
        self._last_lead_speech_at: Optional[float] = None      # RMS energy VAD
        self._last_strong_speech_at: Optional[float] = None    # barge-in-loud audio
        self._last_lead_transcript_at: Optional[float] = None  # model transcription
        self._provider_stopped = False  # provider sent 'stop' — call already dead
        self._silence_winddown_at: Optional[float] = None
        self._agent_stall_nudge_at: Optional[float] = None
        self._termination_reason: Optional[str] = None
        self._voicemail_detected = False
        self._llm_disposition: Optional[str] = None
        self._llm_disposition_reason: Optional[str] = None
        self._vm_phrase_window = ""
        self._end_call_pushback_sent = False
        self._ringback_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Recording helpers (P0.4)
    # ------------------------------------------------------------------

    def _open_recording_file(self):
        """Open a temp file that receives mixed PCM16 (8KHz mono) chunks."""
        try:
            fd, path = tempfile.mkstemp(suffix="_recording.pcm")
            self._recording_tmp_path = path
            self._recording_tmp_file = os.fdopen(fd, "wb")
            logger.info(f"Opened recording temp file: {path}")
        except Exception as e:
            logger.warning(f"Could not open recording temp file: {e}")

    def _write_recording_chunk(self, pcm_chunk: bytes):
        """Append a PCM chunk to the temp file (non-blocking best-effort)."""
        if self._recording_tmp_file:
            try:
                self._recording_tmp_file.write(pcm_chunk)
            except Exception:
                pass

    def _close_recording_file(self) -> Optional[str]:
        """Flush + close the temp file. Returns path, or None on failure."""
        if self._recording_tmp_file:
            try:
                self._recording_tmp_file.flush()
                self._recording_tmp_file.close()
                self._recording_tmp_file = None
            except Exception as e:
                logger.warning(f"Error closing recording file: {e}")
        return self._recording_tmp_path

    async def _save_recording_artifact(self, session: AsyncSession):
        """Convert raw PCM temp file to WAV and persist as an Artifact."""
        pcm_path = self._close_recording_file()
        if not pcm_path:
            return

        wav_path = pcm_path.replace(".pcm", ".wav")
        try:
            with open(pcm_path, "rb") as pcm_f:
                pcm_data = pcm_f.read()

            if not pcm_data:
                return

            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(8000)
                wf.writeframes(pcm_data)

            from src.ai.artifact_service import ArtifactService
            art_svc = ArtifactService(session)
            with open(wav_path, "rb") as f:
                await art_svc.save_artifact(
                    company_id=self.voice_session.company_id,
                    file_name=f"recording_{self.session_id}.wav",
                    file_bytes=f.read(),
                    mime_type="audio/wav",
                    file_category="recordings",
                    origin="system-generated",
                    purpose="Call Voice Recording",
                    generated_by="system",
                    extra_metadata={
                        "session_id": str(self.session_id),
                        "call_sid": str(self.call_sid),
                    },
                )
            logger.info(f"Saved recording artifact for session {self.session_id}")
        except Exception as e:
            logger.error(f"Failed to save recording for session {self.session_id}: {e}")
        finally:
            for p in (pcm_path, wav_path):
                try:
                    os.unlink(p)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Core pipeline — runs once VoiceSession is resolved
    # ------------------------------------------------------------------

    async def _setup_live_and_run(self):
        """
        Load agent context, resolve the configured speech_to_speech model via
        LiveClientFactory, connect to the live session, and launch the pipeline.
        Supports both Gemini Live and Azure OpenAI Realtime providers.
        """
        # ── Credit gate-check ─────────────────────────────────────────
        # Block outbound calls when credits are exhausted.
        # Inbound calls are allowed through with a warning (so users
        # don't miss important calls), but we still deduct at end.
        # Runs concurrently with the agent load (call-setup hot path); uses
        # its own DB session because self.db can't serve parallel queries.
        async def _credit_gate():
            from src.billing.credit_service import CreditService, InsufficientCreditsError
            try:
                async with AsyncSessionLocal() as _credit_db:
                    await CreditService(_credit_db).check_sufficient_for_execution(
                        company_id=self.voice_session.company_id,
                        entity_type="AGENT",
                    )
            except InsufficientCreditsError as e:
                return e
            except Exception as e:
                # Don't block calls if the credit check itself fails
                logger.error(f"Credit check error (non-blocking): {e}")
            return None

        credit_task = asyncio.create_task(_credit_gate())

        # Open recording temp file before audio starts flowing
        self._open_recording_file()

        agent_context = await self.agent_loader.load_agent_for_session(
            agent_id=self.voice_session.agent_id,
            customer_id=self.voice_session.customer_id,
            channel="voice",
            session_metadata=self.voice_session.session_metadata,
        )

        credit_error = await credit_task
        if credit_error is not None:
            direction = getattr(self.voice_session, 'direction', 'unknown')
            if direction == "outbound":
                logger.warning(
                    f"Blocking outbound call {self.session_id} — insufficient credits: {credit_error}"
                )
                try:
                    await self.websocket.send_json({
                        "event": "error",
                        "error": "insufficient_credits",
                        "message": str(credit_error),
                    })
                    await self.websocket.close(code=4002, reason="Insufficient credits")
                except Exception:
                    pass
                return
            else:
                # Allow inbound calls through with a warning
                logger.warning(
                    f"Inbound call {self.session_id} proceeding with $0 balance: {credit_error}"
                )

        # Resolve the correct live streaming client from task defaults
        factory = LiveClientFactory(
            db=self.db,
            company_id=self.voice_session.company_id,
        )
        system_instruction = agent_context.system_instruction
        if settings.VOICEMAIL_DETECTION_ENABLED:
            system_instruction = system_instruction + END_CALL_SYSTEM_SUFFIX
        live_client_or_tuple, provider = await factory.create_client(
            system_instruction=system_instruction,
            voice_config=agent_context.voice_config,
            generation_config=agent_context.llm_config.get("parameters", {}),
            conversation_history=agent_context.conversation_history,
        )

        logger.info(f"[{provider}] Connecting live session for session {self.session_id}")

        if provider == "azure_openai":
            # Azure Realtime returns (client, config) tuple
            azure_client, azure_config = live_client_or_tuple
            await azure_client.connect(azure_config)
            self.gemini_session = azure_client
        else:
            gemini_client = live_client_or_tuple
            # connect() returns an async context manager; we must enter it
            # to get the actual live session with .receive()/.send_realtime_input()
            # Phase 3: Pass loaded tools into the Gemini session config
            voice_tools = list(agent_context.tools or [])
            if settings.VOICEMAIL_DETECTION_ENABLED:
                voice_tools.append(END_CALL_TOOL)
            session_cm = await gemini_client.connect(tools=voice_tools)
            self._live_session_cm = session_cm
            self.gemini_session = await session_cm.__aenter__()

        self.started_at = self.voice_session.started_at

        # Issue #7: Read max call duration from agent config
        self.max_call_duration_seconds = getattr(
            agent_context, 'max_call_duration_seconds', 300
        )
            
        # Send greeting trigger immediately
        greeting = (
            "[Call connected. Greet the customer to begin the conversation.]"
            if self.voice_session.direction == "outbound"
            else "[Call connected. Greet the caller to begin the conversation.]"
        )
        try:
            # For gemini-3.1-flash-live-preview, send_client_content is only for
            # seeding history. Must use send_realtime_input for live messages.
            await self.gemini_session.send_realtime_input(text=greeting)
            self._greeting_sent_at = time.time()
            logger.info(f"Sent greeting trigger for session {self.session_id}")
        except Exception as _ge:
            logger.warning(f"Greeting trigger failed (non-fatal): {_ge}")

        self._pipeline_started_at = time.time()

        tasks = [
            asyncio.create_task(self._receive_from_provider()),
            asyncio.create_task(self._process_incoming_audio()),
            asyncio.create_task(self._receive_from_live_client()),
            asyncio.create_task(self._send_to_provider()),
            asyncio.create_task(self._flush_transcripts()),
            asyncio.create_task(self._call_duration_watchdog()),
            asyncio.create_task(self._activity_watchdog()),
        ]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        except Exception as _te:
            logger.warning(f"Task error during streaming: {_te}")
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            # Close the Gemini Live session context manager
            if hasattr(self, '_live_session_cm') and self._live_session_cm:
                try:
                    await self._live_session_cm.__aexit__(None, None, None)
                except Exception:
                    pass

    # Legacy Azure block removed - using generic BaseLiveClient flow


    # ------------------------------------------------------------------
    # Abstract-ish: provider event reception (overridden by subclasses)
    # ------------------------------------------------------------------

    async def _receive_from_provider(self):
        """
        Receive events from the telephony provider WebSocket.
        Default implementation handles Twilio Media Stream protocol.
        Override for Tata Tele or other providers if protocol differs.
        """
        try:
            while self.is_running:
                message = await self.websocket.receive_text()
                event = json.loads(message)
                event_type = event.get("event")

                if event_type == "connected":
                    logger.info(f"Provider connected: {event}")

                elif event_type == "start":
                    await self._handle_start_event(event)

                elif event_type == "media":
                    await self._handle_media_event(event)

                elif event_type == "stop":
                    logger.info(f"Provider call stopped: {event}")
                    self._provider_stopped = True
                    self.call_ended_at = datetime.utcnow()
                    self.is_running = False
                    break

                else:
                    logger.warning(f"Unknown provider event: {event_type}")

        except Exception as e:
            logger.error(f"Error receiving from provider: {e}")
            self.is_running = False

    async def _handle_start_event(self, event: Dict[str, Any]):
        """Handle provider 'start' event — update stream_sid and play ringback."""
        start_data = event.get("start", {})
        self.stream_sid = start_data.get("streamSid")
        self.call_sid = start_data.get("callSid")
        logger.info(f"Call started: stream_sid={self.stream_sid}, call_sid={self.call_sid}")

        await self.session_manager.update_voice_session(
            self.session_id,
            {"stream_sid": self.stream_sid, "status": "active"},
        )
        self._start_ringback()

    async def _handle_media_event(self, event: Dict[str, Any]):
        """Decode base64 mulaw payload and push to incoming buffer."""
        payload = event.get("media", {}).get("payload")
        if payload:
            mulaw_bytes = base64.b64decode(payload)
            self.incoming_audio_buffer.append(mulaw_bytes)

    # ------------------------------------------------------------------
    # Audio pipeline
    # ------------------------------------------------------------------

    def _start_ringback(self):
        """Launch the ringback loop that masks setup latency until first audio."""
        if self._ringback_task is None or self._ringback_task.done():
            self._ringback_task = asyncio.create_task(self._play_ringback_until_first_audio())

    def _stop_ringback(self):
        if self._ringback_task and not self._ringback_task.done():
            self._ringback_task.cancel()
        self._ringback_task = None

    async def _play_ringback_until_first_audio(self):
        """Stream ringback tone until the model produces audio.

        Setup latency under concurrent dialing was observed at 5-27s; a fixed
        4s burst left leads listening to dead air and hanging up. Frames are
        paced at real time (20ms) so ringback stops as soon as the agent
        speaks instead of sitting pre-buffered at the provider.
        """
        try:
            ringback_mulaw = self.audio_processor.generate_ringback_tone(4)
            chunks = self.audio_processor.ensure_chunk_size(ringback_mulaw)
            if not chunks:
                return
            i = 0
            while self.is_running and not self._first_audio_received:
                if self.stream_sid:
                    chunk = chunks[i % len(chunks)]
                    i += 1
                    b64_chunk = base64.b64encode(chunk).decode("ascii")
                    await self.websocket.send_text(json.dumps({
                        "event": "media",
                        "streamSid": self.stream_sid,
                        "media": {"payload": b64_chunk},
                    }))
                await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Failed to send ringback: {e}")

    async def _process_incoming_audio(self):
        """
        Drain incoming buffer → convert mulaw→PCM16 → send to Gemini.
        Also mixes inbound + outbound audio into the recording file (P0.4).
        """
        try:
            while self.is_running:
                if self.incoming_audio_buffer:
                    mulaw_chunk = self.incoming_audio_buffer.popleft()
                    forward_to_model = True

                    # Recording mix: inbound linear + outbound linear → write to file
                    try:
                        import audioop
                        inbound_lin = audioop.ulaw2lin(mulaw_chunk, 2)
                        # Energy VAD: μ-law frames flow continuously even in
                        # silence, so lead activity = frames with real energy
                        _rms = audioop.rms(inbound_lin, 2)
                        if _rms > settings.VOICE_VAD_RMS_THRESHOLD:
                            if self._last_lead_speech_at is None:
                                logger.info(
                                    f"[GUARD] First lead speech energy "
                                    f"(rms={_rms}) for session {self.session_id}"
                                )
                            self._last_lead_speech_at = time.time()
                        if _rms > settings.VOICE_BARGE_IN_RMS_THRESHOLD:
                            self._last_strong_speech_at = time.time()
                        # Echo gate: while the agent is audibly playing, the
                        # PSTN feeds an attenuated echo of the agent's own
                        # voice back to us. Forwarding it made Gemini's VAD
                        # fire spurious interruptions and produce gibberish
                        # "lead" transcripts. Scope is deliberately narrow —
                        # a flat threshold muted a real lead speaking at
                        # rms~400 for 26s ("main sun nahi paa rahi thi"):
                        #   * greeting phase only (off after the first real
                        #     lead transcript)
                        #   * threshold adapts to the agent's own loudness
                        #     (echo is an attenuated copy of it), capped by
                        #     VOICE_ECHO_SUPPRESS_RMS, floor 300
                        if (
                            settings.VOICE_ECHO_SUPPRESS_RMS > 0
                            and self._last_lead_transcript_at is None
                            and time.time() < self._agent_playback_until
                        ):
                            _gate = min(
                                settings.VOICE_ECHO_SUPPRESS_RMS,
                                max(300, int(0.2 * (self._agent_audio_rms_ema or 0))),
                            )
                            if _rms < _gate:
                                forward_to_model = False
                        # Outbound greeting protection: the lead's pickup
                        # "Hello?" reaching Gemini while it is still
                        # generating the greeting barged in and cancelled the
                        # greeting before a single word played (and left the
                        # session mute). Hold inbound audio until the model's
                        # first audio exists — the greeting talks over the
                        # pickup-hello, which is normal for outbound calls.
                        if (
                            not self._first_audio_received
                            and getattr(self.voice_session, "direction", "") == "outbound"
                        ):
                            forward_to_model = False
                        mix_len = len(inbound_lin)
                        out_chunk = self._outbound_recording_buffer[:mix_len]
                        del self._outbound_recording_buffer[:mix_len]
                        if len(out_chunk) < mix_len:
                            out_chunk += b"\x00" * (mix_len - len(out_chunk))
                        mixed_chunk = audioop.add(inbound_lin, out_chunk, 2)
                        # P0.4: write to disk, not memory
                        self._write_recording_chunk(mixed_chunk)
                    except Exception:
                        pass

                    # Gated frames become SILENCE, not gaps: dropping frames
                    # outright fed Gemini choppy speech fragments and its VAD
                    # never saw a clean end-of-turn (one giant delayed
                    # transcript). PCM16@16k is 4 bytes per μ-law byte.
                    if forward_to_model:
                        pcm16_chunk = self.audio_processor.mulaw_to_pcm16(mulaw_chunk)
                    else:
                        pcm16_chunk = b"\x00" * (len(mulaw_chunk) * 4)
                    if pcm16_chunk and self.gemini_session:
                        try:
                            # google-genai SDK v1.71.0+ — use send_realtime_input
                            from google.genai import types as genai_types
                            await self.gemini_session.send_realtime_input(
                                audio=genai_types.Blob(
                                    data=pcm16_chunk,
                                    mime_type="audio/pcm;rate=16000",
                                )
                            )
                        except Exception as e:
                            logger.error(f"Error sending audio to upstream provider: {e}")
                            break
                else:
                    await asyncio.sleep(0.005)

        except Exception as e:
            logger.error(f"Error processing incoming audio: {e}")

    async def _receive_from_live_client(self):
        """
        Receive audio + transcripts from the Live Client.
        Audio goes to outgoing_audio_queue; transcripts go to buffers.
        """
        try:
            if not self.gemini_session:
                return

            while self.is_running:
                async for response in self.gemini_session.receive():
                    if not self.is_running:
                        break

                    # ── 1. Audio PCM from model ──────────────────────────────
                    audio_data = response.data
                    if audio_data:
                        if not self._first_audio_received:
                            self._first_audio_received = True
                            self._stop_ringback()
                            if self._greeting_sent_at:
                                logger.info(
                                    f"[GUARD] First model audio "
                                    f"{time.time() - self._greeting_sent_at:.1f}s "
                                    f"after greeting for session {self.session_id}"
                                )
                            # Drain leftover ringback from queue
                            while not self.outgoing_audio_queue.empty():
                                try:
                                    self.outgoing_audio_queue.get_nowait()
                                except asyncio.QueueEmpty:
                                    break
                            # Tell Twilio/Tata to stop playing buffered ringback
                            if self.stream_sid:
                                try:
                                    await self.websocket.send_text(
                                        json.dumps({"event": "clear", "streamSid": self.stream_sid})
                                    )
                                except Exception:
                                    pass

                        mulaw_audio = self.audio_processor.pcm24_to_mulaw(audio_data)
                        if mulaw_audio:
                            self.outgoing_audio_queue.put_nowait(mulaw_audio)
                            # Track outbound audio for recording mix
                            try:
                                import audioop
                                self._outbound_recording_buffer.extend(
                                    audioop.ulaw2lin(mulaw_audio, 2)
                                )
                            except Exception:
                                pass

                    # ── 2. Transcription & Interruption ───────────────────────
                    if response.server_content:
                        sc = response.server_content

                        # ── 2a. Interruption signal ─────────────────────────
                        # When the user speaks while the model is generating,
                        # Gemini cancels generation and sends interrupted=True.
                        # Flush the playback buffers ONLY when loud inbound
                        # speech corroborates a real barge-in — line echo and
                        # noise also trip Gemini's VAD, and an uncorroborated
                        # flush wipes the agent's buffered sentence at the
                        # provider (heard as the agent stopping mid-word).
                        if getattr(sc, 'interrupted', False):
                            now = time.time()
                            strong_speech_recent = (
                                self._last_strong_speech_at is not None
                                and now - self._last_strong_speech_at < 1.5
                            )
                            if strong_speech_recent:
                                logger.info(f"[INTERRUPT] Gemini signaled interruption for session {self.session_id}")
                                await self._handle_interruption()
                            else:
                                logger.info(
                                    f"[INTERRUPT] Ignoring uncorroborated interruption "
                                    f"(no strong inbound speech) for session {self.session_id}"
                                )

                        output_transcript = getattr(sc, "output_transcription", None)
                        if output_transcript and getattr(output_transcript, "text", None):
                            text = output_transcript.text.strip()
                            if text:
                                self._agent_transcript_buffer += text + " "
                                self._last_transcript_time = time.time()

                        input_transcript = getattr(sc, "input_transcription", None)
                        if input_transcript and getattr(input_transcript, "text", None):
                            text = input_transcript.text.strip()
                            if text:
                                self._customer_transcript_buffer += text + " "
                                self._last_transcript_time = time.time()
                                # Phase 4: Track when user stops speaking for TTFB
                                self._user_speech_end_time = time.time()
                                self._ttfb_logged = False
                                # Guardrails: inbound speech signals + voicemail
                                # greeting phrases ("please leave a message...").
                                # Phrase scan only near call start — later
                                # mentions are normal conversation.
                                now = time.time()
                                if self._last_lead_transcript_at is None:
                                    logger.info(
                                        f"[GUARD] First lead transcript for "
                                        f"session {self.session_id}: {text[:60]!r}"
                                    )
                                self._last_lead_transcript_at = now
                                self._last_lead_speech_at = now
                                in_phrase_window = (
                                    self._pipeline_started_at is not None
                                    and now - self._pipeline_started_at
                                    < settings.VOICEMAIL_PHRASE_WINDOW_SECONDS
                                )
                                if (
                                    settings.VOICEMAIL_DETECTION_ENABLED
                                    and not self._voicemail_detected
                                    and in_phrase_window
                                ):
                                    self._vm_phrase_window = (
                                        self._vm_phrase_window + " " + text.lower()
                                    )[-300:]
                                    phrase = detect_voicemail_phrase(self._vm_phrase_window)
                                    if phrase:
                                        self._terminate_call(
                                            f"voicemail_phrase:{phrase}", "voicemail"
                                        )

                        if response.text:
                            logger.info(f"Gemini text response: {response.text}")

                    # ── 3. Tool / Function Calls ──────────────────────────────
                    if hasattr(response, 'tool_call') and response.tool_call:
                        asyncio.create_task(self._handle_tool_call(response.tool_call))

                if not self.is_running:
                    break

        except asyncio.CancelledError:
            logger.info(f"Live client receive task cancelled for session {self.session_id}")
        except Exception as e:
            logger.error(f"Error receiving from Live client: {e}", exc_info=True)
            self.is_running = False

    async def _handle_interruption(self):
        """
        React to Gemini's interruption signal.

        1. Drain the outgoing audio queue (discard stale audio)
        2. Send a Twilio/Tata 'clear' event to flush their playback buffer
        3. Clear the outbound recording buffer

        This eliminates the "ghost speaking" effect where the agent
        continues playing pre-buffered audio after being interrupted.
        """
        # 1. Drain outgoing audio queue
        drained = 0
        while not self.outgoing_audio_queue.empty():
            try:
                self.outgoing_audio_queue.get_nowait()
                drained += 1
            except asyncio.QueueEmpty:
                break

        # 2. Send 'clear' to telephony provider to flush their playback buffer
        if self.stream_sid:
            try:
                await self.websocket.send_text(
                    json.dumps({"event": "clear", "streamSid": self.stream_sid})
                )
            except Exception as e:
                logger.warning(f"Failed to send clear event: {e}")

        # 3. Clear outbound recording buffer
        self._outbound_recording_buffer.clear()

        # 4. The provider's playback buffer was flushed — the agent is no
        # longer audible from this moment.
        self._agent_playback_until = time.time()

        # Phase 4: Log interrupt latency
        if self._last_transcript_time > 0:
            interrupt_latency_ms = int((time.time() - self._last_transcript_time) * 1000)
            logger.info(f"[PERF] Interrupt response time: {interrupt_latency_ms}ms, "
                        f"drained {drained} audio chunks")
        else:
            logger.info(f"[INTERRUPT] Drained {drained} audio chunks, sent clear to provider")

    def _terminate_call(self, reason: str, disposition: Optional[str] = None):
        """Stop the pipeline; asyncio.wait(FIRST_COMPLETED) unwinds into _cleanup().

        The activity watchdog exits within a second of is_running flipping,
        which completes the task group and cancels the blocking readers.
        """
        if not self.is_running:
            return
        logger.info(
            f"[GUARD] Terminating call {self.session_id}: {reason} "
            f"(disposition={disposition})"
        )
        self._termination_reason = reason
        if disposition == "voicemail":
            self._voicemail_detected = True
        self.call_ended_at = datetime.utcnow()
        self.is_running = False

    async def _activity_watchdog(self):
        """Silence/stall/voicemail guardrails, evaluated once per second.

        Decision logic lives in call_guards.evaluate_activity(); this task
        owns the timestamps and side effects (nudges, wind-down, disconnect).
        """
        try:
            while self.is_running:
                await asyncio.sleep(1)
                if not self.is_running:
                    break

                now = time.time()

                # Perceived agent speech time: the lead keeps hearing the
                # agent until the provider's playback buffer drains.
                agent_audio_at = effective_agent_audio_at(
                    now, self._last_agent_audio_at, self._agent_playback_until
                )

                # Lead speech after a wind-down means the call resumed
                if (
                    self._silence_winddown_at
                    and (self._last_lead_speech_at or 0) > self._silence_winddown_at
                ):
                    self._silence_winddown_at = None
                # Agent audio after a nudge means the stall resolved
                if (
                    self._agent_stall_nudge_at
                    and (agent_audio_at or 0) > self._agent_stall_nudge_at
                ):
                    self._agent_stall_nudge_at = None

                state = ActivityState(
                    now=now,
                    direction=getattr(self.voice_session, "direction", "inbound"),
                    pipeline_started_at=self._pipeline_started_at,
                    greeting_sent_at=self._greeting_sent_at,
                    first_audio_received=self._first_audio_received,
                    first_agent_audio_sent_at=self._first_agent_audio_sent_at,
                    last_agent_audio_at=agent_audio_at,
                    last_lead_speech_at=self._last_lead_speech_at,
                    last_lead_transcript_at=self._last_lead_transcript_at,
                    user_speech_end_time=self._user_speech_end_time,
                    silence_winddown_at=self._silence_winddown_at,
                    agent_stall_nudge_at=self._agent_stall_nudge_at,
                    voicemail_detection_enabled=settings.VOICEMAIL_DETECTION_ENABLED,
                )
                action = evaluate_activity(state, settings)
                if action is None:
                    continue

                logger.info(f"[GUARD] Activity watchdog action: {action} "
                            f"for session {self.session_id}")

                if action == "pipeline_stall":
                    self._terminate_call("pipeline_stall")
                elif action == "voicemail_no_speech":
                    self._terminate_call("voicemail_no_speech", "voicemail")
                elif action == "silence_winddown":
                    self._silence_winddown_at = now
                    await self._send_system_text(
                        "[SYSTEM: The line has been silent for a while. "
                        "Politely say goodbye and end the conversation.]"
                    )
                elif action == "silence_disconnect":
                    await self._wait_for_playback_drain(max_wait_seconds=15)
                    self._terminate_call("silence_timeout")
                elif action == "agent_stall_nudge":
                    self._agent_stall_nudge_at = now
                    await self._send_system_text(
                        "[SYSTEM: You have not responded to the caller. "
                        "Reply now or briefly say you are still there.]"
                    )
                elif action == "agent_stall_disconnect":
                    self._terminate_call("agent_stall")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"[GUARD] Error in activity watchdog: {e}")

    async def _send_system_text(self, text: str):
        """Best-effort system prompt injection into the live session."""
        try:
            if self.gemini_session:
                await self.gemini_session.send_realtime_input(text=text)
        except Exception as e:
            logger.warning(f"[GUARD] Failed to send system text: {e}")

    async def _wait_for_playback_drain(self, max_wait_seconds: float = 15.0):
        """Wait until the provider's playback buffer finishes playing.

        Audio reaches the provider in fast bursts, so terminating right after
        the last send cuts the lead off mid-sentence.
        """
        deadline = time.time() + max_wait_seconds
        while self.is_running and time.time() < min(self._agent_playback_until, deadline):
            await asyncio.sleep(0.2)

    async def _handle_tool_call(self, tool_call):
        """
        Execute a tool call from Gemini and return the result to the session.

        Gemini Live API supports function calling: the model can invoke tools
        registered in the session config, and this handler executes them
        via the existing ToolRegistry/ToolExecutor infrastructure.

        CRITICAL: Each FunctionResponse MUST include the `id` from the
        corresponding FunctionCall — otherwise the API rejects it and
        Gemini hangs waiting for the response (causing long silences).
        """
        from src.ai.tool_executor import ToolExecutor

        # Preserve original FunctionCall objects for their `id` field
        original_fcs = list(tool_call.function_calls)

        # end_call is synthetic (not in ToolRegistry): acknowledge it so the
        # model isn't left hanging, give the goodbye a moment to flush, then
        # tear the call down.
        end_call_fc = next((fc for fc in original_fcs if fc.name == "end_call"), None)
        if end_call_fc:
            reason = (dict(end_call_fc.args or {})).get("reason", "conversation_complete")
            logger.info(f"[GUARD] Model requested end_call (reason={reason}) "
                        f"for session {self.session_id}")

            # Corroboration gate: the model has claimed voicemail on live
            # conversations. Accept a voicemail claim only when our own
            # signals agree (no lead transcript yet, or a greeting phrase
            # matched); otherwise push back once before accepting a repeat.
            if reason == "voicemail":
                corroborated = (
                    self._last_lead_transcript_at is None
                    or detect_voicemail_phrase(self._vm_phrase_window) is not None
                )
                if not corroborated and not self._end_call_pushback_sent:
                    self._end_call_pushback_sent = True
                    logger.info(
                        f"[GUARD] Rejecting uncorroborated voicemail end_call "
                        f"for session {self.session_id} — lead has spoken"
                    )
                    try:
                        from google.genai import types as genai_types
                        await self.gemini_session.send_tool_response(
                            function_responses=[
                                genai_types.FunctionResponse(
                                    id=getattr(end_call_fc, 'id', None),
                                    name="end_call",
                                    response={
                                        "output": (
                                            "A live person appears to be on the "
                                            "line — they have spoken during this "
                                            "call. Do not end the call. Continue "
                                            "the conversation; ask 'Can you hear "
                                            "me?' if unsure."
                                        ),
                                        "success": False,
                                    },
                                )
                            ],
                        )
                    except Exception as e:
                        logger.warning(f"[GUARD] Failed to push back on end_call: {e}")
                    return

            try:
                from google.genai import types as genai_types
                await self.gemini_session.send_tool_response(
                    function_responses=[
                        genai_types.FunctionResponse(
                            id=getattr(end_call_fc, 'id', None),
                            name="end_call",
                            response={"output": "Call will now end.", "success": True},
                        )
                    ],
                )
            except Exception as e:
                logger.warning(f"[GUARD] Failed to ack end_call: {e}")
            # Let the goodbye actually reach the lead: give the model a
            # moment to emit it, then wait for the provider's playback
            # buffer to drain (audio is sent in fast bursts).
            await asyncio.sleep(1.5)
            await self._wait_for_playback_drain(max_wait_seconds=15)
            self._terminate_call(
                f"model_end_call:{reason}",
                "voicemail" if reason == "voicemail" else None,
            )
            return

        function_calls = []
        for fc in original_fcs:
            args = dict(fc.args) if fc.args else {}

            # Voice context: strip email_address from email tools.
            # The LLM often invents fake sender addresses (e.g. "customer.email@example.com")
            # which causes the connection lookup to fail. Removing it forces the
            # tool to use the company's default email connection.
            if fc.name in ("email_send", "email_draft") and "email_address" in args:
                logger.info(f"[TOOL] Stripping LLM-provided email_address='{args['email_address']}' "
                            f"from {fc.name} — will use company default")
                del args["email_address"]

            function_calls.append({
                "name": fc.name,
                "args": args,
            })

        logger.info(f"Executing {len(function_calls)} tool call(s): "
                    f"{[c['name'] for c in function_calls]}")

        extra_context = {
            "company_id": str(self.voice_session.company_id),
            "user_id": str(self.voice_session.customer_id),
        }

        results = await ToolExecutor.execute_from_function_calls(
            function_calls, extra_context=extra_context
        )

        # Log tool results for observability
        for fc_dict, result in zip(function_calls, results):
            status = "SUCCESS" if result.success else "FAILED"
            logger.info(f"[TOOL] {fc_dict['name']} → {status} ({result.latency_ms}ms)")

        # Send results back to Gemini so it can continue the conversation
        try:
            from google.genai import types as genai_types

            function_responses = []
            for orig_fc, fc_dict, result in zip(original_fcs, function_calls, results):
                # The `id` from the original FunctionCall MUST be included
                # in the FunctionResponse — this is how Gemini correlates
                # the response with the request.
                fc_id = getattr(orig_fc, 'id', None)
                function_responses.append(
                    genai_types.FunctionResponse(
                        id=fc_id,
                        name=fc_dict["name"],
                        response={"output": result.output, "success": result.success},
                    )
                )

            # Use send_tool_response() — the dedicated SDK method for
            # returning function call results.
            await self.gemini_session.send_tool_response(
                function_responses=function_responses,
            )
            logger.info(f"Sent {len(function_responses)} tool response(s) back to Gemini "
                        f"(ids={[getattr(fc, 'id', None) for fc in original_fcs]})")
        except Exception as e:
            logger.error(f"Failed to send tool response to Gemini: {e}")

    async def _send_to_provider(self):
        """
        Send audio to telephony provider.

        Sends mulaw chunks directly as they arrive from the outgoing queue.
        The queue itself provides sufficient buffering; an additional jitter
        buffer was removed because it introduced audio gaps after interruption
        flushes and at the start of each new agent response.
        Phase 4: Added TTFB tracking.
        """
        try:
            while self.is_running:
                try:
                    # Block until audio is enqueued; wake on cancellation
                    mulaw_chunk = await self.outgoing_audio_queue.get()
                except asyncio.CancelledError:
                    break

                # Phase 4: TTFB tracking — time from user speech end to first audio out
                if self._user_speech_end_time and not self._ttfb_logged:
                    ttfb_ms = int((time.time() - self._user_speech_end_time) * 1000)
                    logger.info(f"[PERF] TTFB: {ttfb_ms}ms for session {self.session_id}")
                    self._ttfb_logged = True

                # Guardrails: agent audio activity (queue carries model audio
                # only; ringback bypasses it). Track the playback horizon —
                # μ-law at 8kHz is 1 byte/sample, so this chunk occupies
                # len/8000 seconds of the lead's ear once it plays out.
                _now = time.time()
                self._last_agent_audio_at = _now
                if self._first_agent_audio_sent_at is None:
                    self._first_agent_audio_sent_at = _now
                self._agent_playback_until = (
                    max(_now, self._agent_playback_until) + len(mulaw_chunk) / 8000.0
                )
                try:
                    import audioop
                    _rms_out = audioop.rms(audioop.ulaw2lin(mulaw_chunk, 2), 2)
                    self._agent_audio_rms_ema = (
                        _rms_out
                        if self._agent_audio_rms_ema is None
                        else 0.9 * self._agent_audio_rms_ema + 0.1 * _rms_out
                    )
                except Exception:
                    pass

                self.outbound_chunk_counter += 1
                payload = base64.b64encode(mulaw_chunk).decode("utf-8")
                await self.websocket.send_text(json.dumps({
                    "event": "media",
                    "streamSid": self.stream_sid,
                    "media": {
                        "payload": payload,
                        "chunk": self.outbound_chunk_counter,
                    },
                }))

        except Exception as e:
            logger.error(f"Error sending to provider: {e}")

    async def _flush_transcripts(self):
        """Flush transcript buffers every 0.5s after 1s of silence."""
        try:
            while self.is_running:
                await asyncio.sleep(0.5)
                if time.time() - self._last_transcript_time > 1.0:
                    if self._agent_transcript_buffer:
                        t = self._agent_transcript_buffer.strip()
                        self._agent_transcript_buffer = ""
                        asyncio.create_task(
                            self._log_conversation_turn("agent", t, "transcription")
                        )
                    if self._customer_transcript_buffer:
                        t = self._customer_transcript_buffer.strip()
                        self._customer_transcript_buffer = ""
                        asyncio.create_task(
                            self._log_conversation_turn("customer", t, "transcription")
                        )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error flushing transcripts: {e}")

    async def _call_duration_watchdog(self):
        """
        Auto-disconnect after max_call_duration_seconds.

        Issue #7: Sends a wind-down prompt to Gemini 15s before the hard
        cut so the agent can say goodbye gracefully.
        """
        try:
            limit = self.max_call_duration_seconds
            if limit <= 0:
                return  # 0 = no limit

            # Phase 1: wait until (limit - 15) seconds, then send wind-down
            warn_at = max(limit - 15, 0)
            await asyncio.sleep(warn_at)

            if not self.is_running:
                return

            logger.info(
                f"[WATCHDOG] Call approaching duration limit ({limit}s) "
                f"for session {self.session_id} — sending wind-down prompt"
            )

            # Ask the agent to wrap up naturally
            try:
                if self.gemini_session:
                    await self.gemini_session.send_realtime_input(
                        text=(
                            "[SYSTEM: This call has reached its maximum duration. "
                            "Politely wrap up the conversation now. Thank the caller "
                            "and say goodbye.]"
                        )
                    )
            except Exception as e:
                logger.warning(f"[WATCHDOG] Failed to send wind-down: {e}")

            # Phase 2: give 15s for goodbye, then force-disconnect
            remaining = limit - warn_at
            await asyncio.sleep(remaining)

            if self.is_running:
                logger.info(
                    f"[WATCHDOG] Hard disconnect after {limit}s "
                    f"for session {self.session_id}"
                )
                self.call_ended_at = datetime.utcnow()
                self.is_running = False

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"[WATCHDOG] Error in duration watchdog: {e}")

    async def _generate_call_summary(self, transcript: list, db_session) -> Optional[str]:
        """
        Generate an AI call summary from the transcript and persist it.

        Uses the same Vertex AI client factory as the rest of the codebase
        (build_vertex_genai_client) instead of raw API keys. Falls back to
        AI Studio with API key if Vertex AI is not configured.

        Also extracts and persists next_action alongside the summary.
        """
        if not transcript or len(transcript) < 2:
            return None

        try:
            formatted = "\n".join(
                f"{t.get('speaker', 'unknown').capitalize()}: {t.get('content', '')}"
                for t in transcript
                if t.get('content')
            )

            if not formatted.strip():
                return None

            prompt = (
                "Analyze this phone call transcript and provide:\n\n"
                "SUMMARY:\n"
                "A concise summary of the call in 3-5 sentences covering: "
                "purpose of the call, key discussion points, outcome, and "
                "any agreements or commitments made.\n\n"
                "NEXT ACTIONS:\n"
                "List specific follow-up actions as bullet points. If no "
                "actions were agreed upon, write 'No follow-up actions identified.'\n\n"
                "DISPOSITION:\n"
                "Exactly one word from this list describing the customer's "
                "buying interest: interested | not_interested | voicemail | "
                "neutral. Use 'voicemail' only if the call reached an "
                "answering machine; 'neutral' if interest is unclear.\n\n"
                "REASON:\n"
                "Only if the disposition is not_interested, exactly one word "
                "from this list describing why: budget_low | not_suitable | "
                "not_investing | already_bought | other. Use 'not_suitable' "
                "when the project/product does not fit the customer's needs. "
                "For any other disposition write 'none'.\n\n"
                f"Transcript:\n{formatted[:8000]}"
            )

            # Try multiple strategies — each includes client creation AND model call
            # so that if one fails, we fall through to the next.
            summary = None
            SUMMARY_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash-001", "gemini-2.0-flash"]

            import asyncio
            import functools

            # Strategy 1: Vertex AI (same path as all other LLM calls)
            try:
                from src.common.genai_factory import build_vertex_genai_client
                vertex_client = await build_vertex_genai_client(db_session, self.voice_session.company_id)
                logger.info(f"Using Vertex AI client for summary generation (session {self.session_id})")

                for model_name in SUMMARY_MODELS:
                    try:
                        response = await asyncio.get_event_loop().run_in_executor(
                            None,
                            functools.partial(
                                vertex_client.models.generate_content,
                                model=model_name,
                                contents=prompt,
                            ),
                        )
                        summary = response.text if response else None
                        if summary:
                            logger.info(f"Vertex AI summary generated with model {model_name}")
                            break
                    except Exception as model_err:
                        logger.info(f"Vertex AI model {model_name} failed: {model_err}")
                        continue
            except Exception as vertex_err:
                logger.info(f"Vertex AI not available for summary: {vertex_err}")

            # Strategy 2: Fall back to AI Studio with API key
            if not summary:
                try:
                    from src.config.service import ConfigService
                    config_svc = ConfigService(db_session)
                    api_key = await config_svc.resolve_api_key(
                        company_id=self.voice_session.company_id,
                        provider="google",
                    )
                    if api_key:
                        from src.common.genai_factory import build_ai_studio_genai_client_sync
                        studio_client = build_ai_studio_genai_client_sync(api_key=api_key)
                        logger.info(f"Using AI Studio client for summary generation (session {self.session_id})")

                        for model_name in SUMMARY_MODELS:
                            try:
                                response = await asyncio.get_event_loop().run_in_executor(
                                    None,
                                    functools.partial(
                                        studio_client.models.generate_content,
                                        model=model_name,
                                        contents=prompt,
                                    ),
                                )
                                summary = response.text if response else None
                                if summary:
                                    logger.info(f"AI Studio summary generated with model {model_name}")
                                    break
                            except Exception as model_err:
                                logger.info(f"AI Studio model {model_name} failed: {model_err}")
                                continue
                    else:
                        logger.warning(f"No API key available for AI Studio fallback (session {self.session_id})")
                except Exception as key_err:
                    logger.warning(f"API key fallback also failed: {key_err}")

            if not summary:
                logger.warning(f"All summary generation strategies failed for session {self.session_id}")
                return None

            # Extract next_action from the structured summary
            next_action = None
            if "NEXT ACTIONS:" in summary:
                actions_part = summary.split("NEXT ACTIONS:")[-1].strip()
                # The DISPOSITION section follows NEXT ACTIONS in the output
                if "DISPOSITION" in actions_part:
                    actions_part = actions_part.split("DISPOSITION")[0].strip()
                # Filter out the "no actions" placeholder
                if "no follow-up" not in actions_part.lower():
                    next_action = actions_part
            elif "NEXT ACTION:" in summary:
                next_action = summary.split("NEXT ACTION:")[-1].strip()

            # Structured disposition for campaign reporting (Item 5)
            disposition = parse_disposition(summary)
            if disposition:
                self._llm_disposition = disposition
            disposition_reason = None
            if disposition == "not_interested":
                disposition_reason = parse_not_interested_reason(summary)
                self._llm_disposition_reason = disposition_reason

            # Persist in context_state
            from sqlalchemy import update as sa_update
            from src.voice.models import VoiceSession as VS

            existing_ctx = self.voice_session.context_state or {}
            existing_ctx["call_summary"] = summary
            if next_action:
                existing_ctx["next_action"] = next_action
            if disposition:
                existing_ctx["disposition"] = disposition
            if disposition_reason:
                existing_ctx["disposition_reason"] = disposition_reason

            await db_session.execute(
                sa_update(VS)
                .where(VS.id == self.session_id)
                .values(context_state=existing_ctx)
            )
            await db_session.commit()

            logger.info(f"Persisted call summary for session {self.session_id} ({len(summary)} chars)")

            return summary

        except Exception as e:
            logger.warning(f"Failed to generate call summary for {self.session_id}: {e}")
            return None

    # ------------------------------------------------------------------
    # Logging — isolated sessions to avoid concurrent-commit errors
    # ------------------------------------------------------------------

    async def _log_conversation_turn(self, speaker: str, content: str, msg_type: str = "text"):
        """
        Log one conversation turn in an isolated DB session.
        (Shared self.db causes PendingRollbackError under concurrent async tasks.)
        """
        self.turn_number += 1
        turn = self.turn_number
        try:
            async with AsyncSessionLocal() as _session:
                _logger = ConversationLogger(_session)
                await _logger.log_turn(
                    company_id=self.voice_session.company_id,
                    customer_id=self.voice_session.customer_id,
                    agent_id=self.voice_session.agent_id,
                    session_id=self.session_id,
                    channel="voice",
                    turn_number=turn,
                    speaker=speaker,
                    content=content,
                    message_type=msg_type,
                )
        except Exception as _e:
            logger.warning(f"Failed to log turn {turn} for session {self.session_id}: {_e}")

    # ------------------------------------------------------------------
    # Cleanup — shared across both providers
    # ------------------------------------------------------------------

    async def _cleanup(self):
        """End session, persist recording, log usage, deduct credits."""
        logger.info(f"Cleaning up session {self.session_id}")
        self._stop_ringback()

        if self.voice_session and self.started_at:
            end_time = self.call_ended_at or datetime.utcnow()
            duration = int((end_time - self.started_at).total_seconds())

            try:
                async with AsyncSessionLocal() as session:
                    # Export transcript
                    try:
                        convo_log = await ConversationLogger(session).export_transcript_json(
                            self.session_id
                        )
                    except Exception:
                        convo_log = []

                    # End session
                    await SessionManager(session).end_voice_session(
                        self.session_id,
                        duration_seconds=duration,
                        conversation_log=convo_log,
                    )

                    # Persist recording artifact (P0.4)
                    await self._save_recording_artifact(session)

                    # Issue #2: Generate and persist AI call summary
                    try:
                        await self._generate_call_summary(convo_log, session)
                    except Exception as _sum_err:
                        logger.warning(f"Post-call summary generation failed: {_sum_err}")

                    # Usage + billing
                    usage_logger = VoiceUsageLogger(session)
                    total_cost = await usage_logger.log_voice_session_usage(
                        session_id=self.session_id,
                        company_id=self.voice_session.company_id,
                        provider=self.voice_session.provider,
                        duration_seconds=duration,
                        metadata={
                            "agent_id": str(self.voice_session.agent_id),
                            "customer_id": str(self.voice_session.customer_id),
                            "phone_number": self.voice_session.phone_number,
                            "turn_count": self.turn_number,
                        },
                    )
                    logger.info(f"Session {self.session_id} total cost: ${total_cost}")

                    if total_cost and total_cost > 0:
                        cost_decimal = Decimal(str(total_cost))

                        # Fix #1: Apply TB formula before credit deduction
                        # (matches the pattern in worker.py execute_run)
                        try:
                            from src.billing.billing_service import calculate_tb
                            billing_svc = BillingService(session)
                            config = await billing_svc.get_billing_config(
                                self.voice_session.company_id
                            )
                            if not config:
                                mf, pf, spf, d = Decimal("1"), Decimal("0"), Decimal("0"), Decimal("0")
                            else:
                                mf = Decimal(str(config.multiplier_factor))
                                pf = Decimal(str(config.platform_fee_pct))
                                spf = Decimal(str(config.sales_partner_fee_pct))
                                d = Decimal(str(config.discount_pct))

                            tb_result = calculate_tb(cost_decimal, mf, pf, spf, d)
                            billed_amount = tb_result["total_billing"]
                            logger.info(
                                f"Voice TB formula: raw=${cost_decimal} → billed=${billed_amount} "
                                f"(mf={mf}, pf={pf}, spf={spf}, d={d})"
                            )
                        except Exception as tb_err:
                            logger.warning(f"TB formula failed, falling back to raw cost: {tb_err}")
                            billed_amount = cost_decimal

                        try:
                            await CreditService(session).consume(
                                company_id=self.voice_session.company_id,
                                amount=billed_amount,
                            )
                            logger.info(
                                f"Voice credits deducted: ${billed_amount} "
                                f"(raw: ${cost_decimal})"
                            )
                        except Exception as ce:
                            logger.warning(f"Credit deduction failed: {ce}")

                        # Fix #7: Pass event_category="telephony" so charges
                        # appear in the correct report column
                        try:
                            duration_minutes = Decimal(str(duration)) / Decimal("60")
                            await BillingService(session).record_billing_event(
                                company_id=self.voice_session.company_id,
                                base_cost=cost_decimal,
                                grouping_type="agent",
                                grouping_value=str(self.voice_session.agent_id),
                                telephony_out_minutes=(
                                    duration_minutes
                                    if self.voice_session.direction == "outbound"
                                    else Decimal("0")
                                ),
                                telephony_in_minutes=(
                                    duration_minutes
                                    if self.voice_session.direction == "inbound"
                                    else Decimal("0")
                                ),
                                event_category="telephony",
                            )
                        except Exception as be:
                            logger.warning(f"Billing event recording failed: {be}")

                # --- Post-call: update lead queue if this was a CRM-driven call ---
                try:
                    if self.voice_session and self.session_id:
                        await self._update_lead_queue_post_call(session, duration)
                except Exception as lq_err:
                    logger.warning(f"Lead queue post-call update failed: {lq_err}")

                # --- Post-call: update CampaignCall if this was a campaign call ---
                try:
                    if self.voice_session and self.session_id:
                        await self._update_campaign_call_post_cleanup(session, duration)
                except Exception as cc_err:
                    logger.warning(f"Campaign call post-cleanup update failed: {cc_err}")

            except Exception as e:
                logger.error(f"Error during cleanup DB update: {e}")

        # Close WebSocket
        try:
            await self.websocket.close()
        except Exception:
            pass

    async def _update_lead_queue_post_call(self, db_session, duration: int) -> None:
        """
        Update the lead_queue entry linked to this voice session.

        Called after call cleanup. Marks the lead as completed with
        call outcome data so the CRM can be updated.
        """
        try:
            from src.ai.lead_queue_service import LeadQueueService

            queue_svc = LeadQueueService(db_session)
            entry = await queue_svc.get_by_voice_session(self.session_id)

            if not entry:
                return  # Not a CRM-driven call, nothing to do

            # Build call outcome from session data
            call_outcome = {
                "status": "completed",
                "duration_seconds": duration,
                "turn_count": self.turn_number,
                "phone": self.voice_session.phone_number if self.voice_session else "",
            }

            # Extract transcript if available
            if hasattr(self, 'conversation_logger') and self.conversation_logger:
                try:
                    transcript = self.conversation_logger.get_transcript_text()
                    if transcript:
                        call_outcome["transcript_preview"] = transcript[:2000]
                except Exception:
                    pass

            await queue_svc.mark_completed(entry.id, call_outcome)
            logger.info(
                f"[LeadQueue] Post-call update: lead {entry.lead_id} "
                f"completed (duration={duration}s, turns={self.turn_number})"
            )

        except ImportError:
            pass  # lead_queue_model not available — skip silently
        except Exception as e:
            logger.warning(f"[LeadQueue] Post-call update error: {e}")

    async def _update_campaign_call_post_cleanup(self, db_session, duration: int) -> None:
        """
        Update the CampaignCall linked to this voice session after cleanup.

        Belt-and-suspenders: the primary update path is via provider status
        webhooks (Twilio/Tata). This method acts as a fallback to ensure
        CampaignCall records are updated even if the webhook is delayed or
        fails.

        Uses conditional UPDATE (WHERE status = 'calling') so that if the
        webhook already updated the record, this is a no-op.
        """
        try:
            from src.ai.campaign_models import Campaign, CampaignCall
            from sqlalchemy import select, update as sa_update

            # Find CampaignCall linked to this voice session
            cc_result = await db_session.execute(
                select(CampaignCall).where(
                    CampaignCall.voice_session_id == self.session_id
                )
            )
            campaign_call = cc_result.scalar_one_or_none()

            if not campaign_call:
                return  # Not a campaign call

            # The LLM-classified disposition applies even when the webhook
            # already finalized the status; never overwrite an existing one.
            if self._llm_disposition and not self._voicemail_detected:
                await db_session.execute(
                    sa_update(CampaignCall)
                    .where(
                        CampaignCall.id == campaign_call.id,
                        CampaignCall.disposition.is_(None),
                    )
                    .values(
                        disposition=self._llm_disposition,
                        disposition_reason=self._llm_disposition_reason,
                    )
                )

            # In-call voicemail detection wins over webhook data: the webhook
            # only sees a "completed" call, not why it ended.
            if self._voicemail_detected:
                await db_session.execute(
                    sa_update(CampaignCall)
                    .where(CampaignCall.id == campaign_call.id)
                    .values(
                        status="completed-voicemail",
                        outcome="voicemail",
                        disposition="voicemail",
                        outcome_notes=f"updated_by={self._termination_reason or 'voicemail_detection'}",
                        completed_at=datetime.utcnow(),
                        duration_seconds=duration if duration > 0 else None,
                    )
                )
                if campaign_call.campaign_id and campaign_call.status == "calling":
                    await self._increment_campaign_counter(
                        db_session, campaign_call.campaign_id, "calls_completed"
                    )
                await db_session.commit()
                logger.info(
                    f"[Campaign] Cleanup updated CampaignCall {campaign_call.id}: "
                    f"{campaign_call.status} → completed-voicemail "
                    f"({self._termination_reason}, duration={duration}s)"
                )
                return

            # Only update if status is still "calling" (webhook hasn't arrived yet)
            if campaign_call.status != "calling":
                logger.debug(
                    f"[Campaign] CampaignCall {campaign_call.id} already updated "
                    f"(status={campaign_call.status}), skipping cleanup update"
                )
                await db_session.commit()  # persist the disposition update above
                return

            if self._termination_reason == "pipeline_stall":
                call_outcome, outcome_detail = "failed", "no_media"
            else:
                call_outcome = "completed" if duration > 0 else "failed"
                outcome_detail = "answered" if duration > 0 else "no_media"

            notes = f"updated_by={self._termination_reason or 'websocket_cleanup'}"

            await db_session.execute(
                sa_update(CampaignCall)
                .where(
                    CampaignCall.id == campaign_call.id,
                    CampaignCall.status == "calling",  # Conditional: don't overwrite webhook data
                )
                .values(
                    status=call_outcome,
                    outcome=outcome_detail,
                    outcome_notes=notes,
                    completed_at=datetime.utcnow(),
                    duration_seconds=duration if duration > 0 else None,
                    **(
                        {"disposition": "failed"}
                        if call_outcome == "failed"
                        else {}
                    ),
                )
            )

            # Increment campaign counter
            if campaign_call.campaign_id:
                stat_field = "calls_completed" if call_outcome == "completed" else "calls_failed"
                await self._increment_campaign_counter(
                    db_session, campaign_call.campaign_id, stat_field
                )

            await db_session.commit()
            logger.info(
                f"[Campaign] Cleanup updated CampaignCall {campaign_call.id}: "
                f"calling → {call_outcome} ({outcome_detail}, duration={duration}s)"
            )

        except ImportError:
            pass  # campaign_models not available — skip silently
        except Exception as e:
            logger.warning(f"[Campaign] Post-cleanup update error: {e}")

    @staticmethod
    async def _increment_campaign_counter(db_session, campaign_id, stat_field: str):
        from src.ai.campaign_models import Campaign
        from sqlalchemy import select, update as sa_update

        camp_result = await db_session.execute(
            select(Campaign).where(Campaign.id == campaign_id)
        )
        campaign = camp_result.scalar_one_or_none()
        if campaign:
            current_val = getattr(campaign, stat_field, 0) or 0
            await db_session.execute(
                sa_update(Campaign)
                .where(Campaign.id == campaign.id)
                .values({stat_field: current_val + 1})
            )


# ---------------------------------------------------------------------------
# TwilioStreamHandler — provider-specific session discovery
# ---------------------------------------------------------------------------

class TwilioStreamHandler(BaseStreamHandler):
    """
    Handles Twilio Media Stream WebSocket protocol.

    Resolves VoiceSession from session_id passed via URL parameter,
    then delegates the full audio pipeline to BaseStreamHandler.
    """

    def __init__(self, websocket: WebSocket, session_id: UUID, db: AsyncSession):
        super().__init__(websocket, db)
        self.session_id = session_id

    async def _cleanup(self):
        """Twilio-specific cleanup — force-complete the PSTN leg first.

        Closing the media WebSocket alone doesn't end the phone call, so
        agent-initiated terminations (voicemail, silence, duration) need the
        REST hangup.
        """
        if self.call_sid and self.voice_session and not self._provider_stopped:
            try:
                from src.voice.twilio_api import hangup_twilio_call

                async with AsyncSessionLocal() as db_session:
                    await hangup_twilio_call(
                        db_session, self.voice_session.company_id, self.call_sid
                    )
            except Exception as e:
                logger.error(f"Error during Twilio hangup execution: {e}", exc_info=True)

        await super()._cleanup()

    async def handle(self):
        """Main entry-point for Twilio WebSocket connections."""
        try:
            self.voice_session = await self.session_manager.get_voice_session(self.session_id)
            if not self.voice_session:
                logger.error(f"Voice session not found: {self.session_id}")
                await self.websocket.close()
                return

            self.is_running = True
            await self._setup_live_and_run()

        except Exception as e:
            logger.error(f"Error in Twilio stream handler: {e}", exc_info=True)
        finally:
            self.is_running = False
            await self._cleanup()


# ---------------------------------------------------------------------------
# TataStreamHandler — Tata Tele-specific session discovery
# ---------------------------------------------------------------------------

class TataStreamHandler(BaseStreamHandler):
    """
    Handles Tata Tele Media Stream WebSocket protocol.

    Tata Tele uses an identical wire protocol to Twilio's Media Streams,
    but the VoiceSession is resolved from the 'start' event payload rather
    than a URL parameter. Everything else is inherited from BaseStreamHandler.
    """

    def __init__(self, websocket: WebSocket, db: AsyncSession):
        super().__init__(websocket, db)
        self.number_router = NumberRouter(db)

    async def handle_direct(self):
        """Main entry-point for Tata Tele WebSocket connections."""
        try:
            self.is_running = True

            # Wait for 'start' event to discover/create VoiceSession
            while self.is_running and not self.session_id:
                message = await self.websocket.receive_text()
                event = json.loads(message)
                event_type = event.get("event")

                if event_type == "connected":
                    logger.info("Tata Tele connected")
                elif event_type == "start":
                    await self._handle_tata_start_event(event)
                elif event_type == "stop":
                    logger.info("Tata Tele call stopped before start")
                    self.is_running = False
                    return

            if not self.session_id:
                logger.error("Failed to establish session for Tata Tele call")
                await self.websocket.close()
                return

            self._start_ringback()
            await self._setup_live_and_run()

        except Exception as e:
            logger.error(f"Error in Tata stream handler: {e}", exc_info=True)
        finally:
            self.is_running = False
            await self._cleanup()

    async def _handle_tata_start_event(self, event: Dict[str, Any]):
        """
        Extract metadata from Tata Tele 'start' event and resolve/create a VoiceSession.

        For OUTBOUND calls (campaigns): The campaign executor already created a VoiceSession
        with direction='outbound' and status='initiated'. We look it up by matching the DID
        (from_number) and resume it — this preserves the campaign's agent_id.

        For INBOUND calls: We look up the DID in customer_phone_numbers and create a session.
        """
        start_data = event.get("start", {})
        self.stream_sid = start_data.get("streamSid")
        self.call_sid = start_data.get("callSid")
        from_number = start_data.get("from")
        to_number = start_data.get("to")
        custom_identifier = (
            start_data.get("customParameters", {}).get("custom_identifier")
            if start_data.get("customParameters")
            else None
        )

        logger.info(
            f"Tata start event: call_sid={self.call_sid}, from={from_number}, "
            f"to={to_number}, custom_id={custom_identifier}"
        )

        # ── Strategy 1: Resume via custom_identifier (campaign flow) ─────────
        if custom_identifier:
            try:
                from uuid import UUID as _UUID
                session_id = _UUID(custom_identifier)
                existing_session = await self.session_manager.get_voice_session(session_id)
                if existing_session:
                    logger.info(f"Resuming outbound session via custom_identifier: {session_id}")
                    self.voice_session = existing_session
                    self.session_id = existing_session.id
                    await self.session_manager.update_voice_session(
                        self.session_id,
                        {"call_sid": self.call_sid, "stream_sid": self.stream_sid, "status": "active"},
                    )
                    return
            except Exception as e:
                logger.warning(f"Could not resume via custom_identifier: {e}")

        # ── Strategy 2: Resume pending outbound by DID ────────────────────────
        result = await self.db.execute(
            select(VoiceSession).where(
                and_(
                    VoiceSession.phone_number == from_number,
                    VoiceSession.provider == "tata_tele",
                    VoiceSession.direction == "outbound",
                    VoiceSession.status == "initiated",
                    VoiceSession.call_sid.like("pending_%"),
                )
            ).order_by(VoiceSession.started_at.desc()).limit(1)
        )
        existing_session = result.scalar_one_or_none()

        if existing_session:
            logger.info(f"Found pending outbound session: {existing_session.id}")
            self.voice_session = existing_session
            self.session_id = existing_session.id
            await self.session_manager.update_voice_session(
                self.session_id,
                {"call_sid": self.call_sid, "stream_sid": self.stream_sid, "status": "active"},
            )
            return

        # ── Strategy 3: Inbound call — resolve DID → customer assignment ─────
        customer_assignment = await self.number_router.find_customer_by_number(to_number)
        if not customer_assignment:
            customer_assignment = await self.number_router.find_customer_by_number(from_number)

        if not customer_assignment:
            logger.error(
                f"No session or customer for Tata call: from={from_number}, to={to_number}"
            )
            return

        # If the phone number is assigned to an agent but not a specific customer
        # (customer_id is NULL), generate a deterministic UUID from the caller's
        # phone number so the NOT NULL constraint on voice_sessions is satisfied.
        from uuid import uuid5, NAMESPACE_DNS as _NS
        resolved_customer_id = (
            customer_assignment.customer_id
            or uuid5(_NS, f"caller:{from_number}")
        )

        self.voice_session = await self.session_manager.create_voice_session(
            company_id=customer_assignment.company_id,
            customer_id=resolved_customer_id,
            agent_id=customer_assignment.agent_id,
            phone_number=(
                from_number
                if customer_assignment.phone_number == to_number
                else to_number
            ),
            provider="tata_tele",
            call_sid=self.call_sid,
            direction="inbound",
            metadata=start_data,
        )
        self.session_id = self.voice_session.id
        await self.session_manager.update_voice_session(
            self.session_id,
            {"stream_sid": self.stream_sid, "status": "active"},
        )
        logger.info(f"Created inbound Tata session: {self.session_id}")

    async def _cleanup(self):
        """Tata-specific cleanup — stop stream and call hangup API first."""
        # 1. Send WebSocket stop event
        if self.stream_sid:
            try:
                await self.websocket.send_text(
                    json.dumps({"event": "stop", "streamSid": self.stream_sid})
                )
                logger.info(f"Sent stop event to Tata for stream {self.stream_sid}")
            except Exception as e:
                logger.debug(f"Failed to send stop event to Tata: {e}")

        # 2. Hang up telephone call (skip when the provider already reported
        # the call over — hangup then just 422s with "Invalid Call ID")
        if self.call_sid and self.voice_session and not self._provider_stopped:
            try:
                from src.common.database import AsyncSessionLocal
                from src.voice.tata_auth import (
                    get_smartflo_auth_token,
                    SMARTFLO_BASE_URL,
                )
                import httpx

                async with AsyncSessionLocal() as db_session:
                    auth_token = await get_smartflo_auth_token(
                        db_session, self.voice_session.company_id
                    )

                    if auth_token:
                        api_url = f"{SMARTFLO_BASE_URL}/v1/call/hangup"
                        payload = {"call_id": self.call_sid}

                        logger.info(f"Calling Tata hangup API for call: {self.call_sid}")
                        async with httpx.AsyncClient() as client:
                            for attempt in ("cached", "refreshed"):
                                headers = {
                                    "Authorization": auth_token,
                                    "Content-Type": "application/json",
                                    "accept": "application/json"
                                }
                                resp = await client.post(
                                    api_url,
                                    json=payload,
                                    headers=headers,
                                    timeout=10.0
                                )
                                logger.info(
                                    f"Tata hangup API response ({attempt} token) "
                                    f"status={resp.status_code}: {resp.text}"
                                )
                                token_rejected = (
                                    resp.status_code in (401, 403)
                                    or "blacklisted" in resp.text.lower()
                                )
                                if not token_rejected or attempt == "refreshed":
                                    break
                                auth_token = await get_smartflo_auth_token(
                                    db_session,
                                    self.voice_session.company_id,
                                    force_refresh=True,
                                )
                                if not auth_token:
                                    break
                    else:
                        logger.warning(
                            f"Could not retrieve Tata Tele auth token for company {self.voice_session.company_id}"
                        )
            except Exception as e:
                logger.error(f"Error during Tata hangup execution: {e}", exc_info=True)

        # 3. Call base cleanup
        await super()._cleanup()

