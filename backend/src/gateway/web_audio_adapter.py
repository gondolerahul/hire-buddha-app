"""
Web Audio Adapter — Interface 4 helper for browser-based audio clients.

Handles raw PCM16 audio from browser web clients (WebAudio API output).
Acts as a thin adapter between the browser and the existing BaseStreamHandler
audio pipeline (Gemini Live / Azure Realtime).

Wire protocol:
  Client → Server:  binary frames = raw PCM16 LE @ 16kHz mono
  Server → Client:  binary frames = raw PCM16 LE @ 24kHz mono (AI TTS output)

Control messages (JSON text frames):
  {"event": "stop"}   — client wants to end the session
  {"event": "ping"}   — keepalive
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Optional
from uuid import UUID

from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from src.voice.session_manager import SessionManager
from src.voice.agent_loader import AgentContextLoader
from src.voice.audio_processor import AudioProcessor
from src.voice.live_client_factory import LiveClientFactory
from src.voice.conversation_logger import ConversationLogger
from src.voice.models import VoiceSession
from src.common.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


class WebAudioAdapter:
    """
    Handles bidirectional PCM16 audio streaming from browser web clients.

    Browser sends raw PCM16 binary frames.
    Gateway feeds them to the AI live session and sends back TTS audio.
    """

    def __init__(
        self,
        websocket: WebSocket,
        voice_session: VoiceSession,
        db: AsyncSession,
    ) -> None:
        self.websocket = websocket
        self.voice_session = voice_session
        self.db = db
        self.session_id = voice_session.id

        self.agent_loader = AgentContextLoader(db)
        self.audio_processor = AudioProcessor()
        self.conversation_logger = ConversationLogger(db)
        self.session_manager = SessionManager(db)

        self.is_running = False
        self.gemini_session = None
        self.outgoing_audio_queue: asyncio.Queue = asyncio.Queue()

        self._agent_transcript_buffer = ""
        self._customer_transcript_buffer = ""
        self._last_transcript_time = 0.0
        self.turn_number = 0

    async def handle(self) -> None:
        """Main entry-point for web audio sessions."""
        try:
            self.is_running = True
            await self._setup_and_run()
        except Exception as exc:
            logger.error(f"[WebAudioAdapter] Error: {exc}", exc_info=True)
        finally:
            self.is_running = False
            await self._cleanup()

    async def _setup_and_run(self) -> None:
        """Set up Gemini/Azure live session and start the audio pipeline."""
        agent_context = await self.agent_loader.load_agent_for_session(
            agent_id=self.voice_session.agent_id,
            customer_id=self.voice_session.customer_id,
            channel="web_audio",
        )

        factory = LiveClientFactory(db=self.db, company_id=self.voice_session.company_id)
        live_client_or_tuple, provider = await factory.create_client(
            system_instruction=agent_context.system_instruction,
            voice_config=agent_context.voice_config,
            generation_config=agent_context.llm_config.get("parameters", {}),
            conversation_history=agent_context.conversation_history,
        )

        if provider == "azure_openai":
            azure_client, azure_config = live_client_or_tuple
            await azure_client.connect(azure_config)
            self.gemini_session = azure_client
        else:
            await live_client_or_tuple.connect()
            self.gemini_session = live_client_or_tuple

        logger.info(f"[WebAudioAdapter] Connected to {provider} for session {self.session_id}")

        tasks = [
            asyncio.create_task(self._receive_from_browser()),
            asyncio.create_task(self._receive_from_ai()),
            asyncio.create_task(self._send_to_browser()),
            asyncio.create_task(self._flush_transcripts()),
        ]

        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    async def _receive_from_browser(self) -> None:
        """Receive PCM16 binary frames (and JSON control messages) from browser."""
        try:
            while self.is_running:
                message = await self.websocket.receive()

                if "bytes" in message and message["bytes"]:
                    # Raw PCM16 from browser — forward directly to AI
                    pcm16 = message["bytes"]
                    if self.gemini_session:
                        try:
                            if hasattr(self.gemini_session, "send_audio"):
                                await self.gemini_session.send_audio(pcm16)
                            elif hasattr(self.gemini_session, "send_realtime_input"):
                                await self.gemini_session.send_realtime_input(
                                    audio={"data": pcm16, "mime_type": "audio/pcm;rate=16000"}
                                )
                        except Exception as exc:
                            logger.error(f"[WebAudioAdapter] Error sending audio to AI: {exc}")
                            break

                elif "text" in message and message["text"]:
                    try:
                        ctrl = json.loads(message["text"])
                        if ctrl.get("event") == "stop":
                            logger.info(f"[WebAudioAdapter] Client requested stop for {self.session_id}")
                            self.is_running = False
                            break
                        elif ctrl.get("event") == "ping":
                            await self.websocket.send_text(json.dumps({"event": "pong"}))
                    except json.JSONDecodeError:
                        pass

        except Exception as exc:
            logger.error(f"[WebAudioAdapter] Receive error: {exc}")
            self.is_running = False

    async def _receive_from_ai(self) -> None:
        """Receive audio and transcripts from the AI live session."""
        try:
            if not self.gemini_session:
                return

            while self.is_running:
                async for response in self.gemini_session.receive():
                    if not self.is_running:
                        break

                    audio_data = response.data
                    if audio_data:
                        # AI returns PCM24 — convert to PCM16 for browser
                        pcm16 = self.audio_processor.pcm24_to_pcm16(audio_data)
                        if pcm16:
                            await self.outgoing_audio_queue.put(pcm16)

                    if response.server_content:
                        import time
                        sc = response.server_content
                        out_t = getattr(sc, "output_transcription", None)
                        if out_t and getattr(out_t, "text", None):
                            self._agent_transcript_buffer += out_t.text.strip() + " "
                            self._last_transcript_time = time.time()
                        in_t = getattr(sc, "input_transcription", None)
                        if in_t and getattr(in_t, "text", None):
                            self._customer_transcript_buffer += in_t.text.strip() + " "
                            self._last_transcript_time = time.time()

                if not self.is_running:
                    break

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(f"[WebAudioAdapter] AI receive error: {exc}", exc_info=True)
            self.is_running = False

    async def _send_to_browser(self) -> None:
        """Send PCM16 audio from the queue back to the browser as binary frames."""
        try:
            while self.is_running:
                try:
                    pcm16 = await self.outgoing_audio_queue.get()
                    await self.websocket.send_bytes(pcm16)
                except asyncio.CancelledError:
                    break
        except Exception as exc:
            logger.error(f"[WebAudioAdapter] Send error: {exc}")

    async def _flush_transcripts(self) -> None:
        """Flush transcript buffers every 0.5s after 1s of silence."""
        import time
        try:
            while self.is_running:
                await asyncio.sleep(0.5)
                if time.time() - self._last_transcript_time > 1.0:
                    if self._agent_transcript_buffer:
                        t = self._agent_transcript_buffer.strip()
                        self._agent_transcript_buffer = ""
                        asyncio.create_task(self._log_turn("agent", t))
                    if self._customer_transcript_buffer:
                        t = self._customer_transcript_buffer.strip()
                        self._customer_transcript_buffer = ""
                        asyncio.create_task(self._log_turn("customer", t))
        except asyncio.CancelledError:
            pass

    async def _log_turn(self, speaker: str, content: str) -> None:
        self.turn_number += 1
        try:
            async with AsyncSessionLocal() as session:
                _logger = ConversationLogger(session)
                await _logger.log_turn(
                    company_id=self.voice_session.company_id,
                    customer_id=self.voice_session.customer_id,
                    agent_id=self.voice_session.agent_id,
                    session_id=self.session_id,
                    channel="web_audio",
                    turn_number=self.turn_number,
                    speaker=speaker,
                    content=content,
                    message_type="transcription",
                )
        except Exception as exc:
            logger.warning(f"[WebAudioAdapter] Failed to log turn: {exc}")

    async def _cleanup(self) -> None:
        try:
            async with AsyncSessionLocal() as session:
                await SessionManager(session).end_voice_session(self.session_id)
        except Exception:
            pass
        try:
            await self.websocket.close()
        except Exception:
            pass
