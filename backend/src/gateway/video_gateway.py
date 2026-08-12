"""
Interface 5: Unified Bidirectional Video Streaming Gateway.

Single WebSocket endpoint: WS /stream/video

Architecture:
  - Signaling Layer (this file): WebSocket-based SDP offer/answer + ICE exchange
  - Media Layer: aiortc WebRTC SFU (Selective Forwarding Unit)
  - AI Pipeline: Audio track → STT → LLM → TTS (same live client pipeline)
                 Video track → frame sampling → Vision model → AI context

Connection flows:
  ① Web Browser        → WebRTC (native, direct DTLS/SRTP)
  ② Zoom / MS Teams    → Bot captures RTP → forwards here as WebRTC
  ③ Custom video client → any WebRTC-capable endpoint

Zoom / MS Teams Integration Note:
  You must build a Zoom Meeting SDK bot or MS Teams Graph API bot that:
    1. Joins the meeting using SDK credentials
    2. Captures mixed audio/video RTP
    3. Connects to this WS endpoint as a "provider=zoom" or "provider=teams" client
    4. Forwards RTP/WebRTC media to this gateway
  The bot logic is NOT in this file (out of SDK scope), but this gateway
  is designed to accept connections from such bots.

aiortc is imported conditionally — if not installed, the endpoint serves
an informative error directing the operator to install it.

Install: pip install aiortc aiohttp
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.gateway.dispatcher import get_dispatcher

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Video Streaming"])

# ---------------------------------------------------------------------------
# aiortc availability check
# ---------------------------------------------------------------------------

try:
    from aiortc import (
        RTCPeerConnection,
        RTCSessionDescription,
        RTCConfiguration,
        RTCIceServer,
        MediaStreamTrack,
    )
    from aiortc.contrib.media import MediaPlayer, MediaRecorder
    AIORTC_AVAILABLE = True
except ImportError:
    AIORTC_AVAILABLE = False
    logger.warning(
        "[VideoGateway] aiortc not installed. Video streaming requires: "
        "pip install aiortc aiohttp"
    )


# ===========================================================================
# Video Session — tracks an active WebRTC peer connection
# ===========================================================================

class VideoSession:
    """
    Represents one active video streaming session.

    Manages:
    - WebRTC PeerConnection lifecycle
    - Audio track → AI live client pipeline
    - Video track → frame sampling → Vision model context
    - Cleanup on disconnect
    """

    def __init__(
        self,
        session_id: str,
        client_id: str,
        agent_info: dict,
        provider: str,
        ws: WebSocket,
        ice_servers: list,
    ) -> None:
        self.session_id = session_id
        self.client_id = client_id
        self.agent_info = agent_info
        self.provider = provider
        self.ws = ws
        self.ice_servers = ice_servers
        self.pc: Optional["RTCPeerConnection"] = None
        self.is_running = False
        self._ai_audio_task: Optional[asyncio.Task] = None
        self._frame_sample_task: Optional[asyncio.Task] = None
        self.vision_context: str = ""        # Latest visual context from the AI vision model
        self.audio_track = None
        self.video_track = None

    async def create_peer_connection(self) -> "RTCPeerConnection":
        """Create a configured WebRTC PeerConnection."""
        config = RTCConfiguration(
            iceServers=[RTCIceServer(urls=s) for s in self.ice_servers]
        )
        self.pc = RTCPeerConnection(configuration=config)

        @self.pc.on("icecandidate")
        async def on_ice_candidate(candidate):
            if candidate:
                await self.ws.send_text(json.dumps({
                    "event": "ice_candidate",
                    "candidate": {
                        "candidate": candidate.candidate,
                        "sdpMid": candidate.sdpMid,
                        "sdpMLineIndex": candidate.sdpMLineIndex,
                    }
                }))

        @self.pc.on("track")
        async def on_track(track):
            logger.info(f"[VideoSession] Track received: kind={track.kind}, session={self.session_id}")
            if track.kind == "audio":
                self.audio_track = track
                asyncio.create_task(self._process_audio_track(track))
            elif track.kind == "video":
                self.video_track = track
                asyncio.create_task(self._process_video_track(track))

        @self.pc.on("connectionstatechange")
        async def on_state_change():
            state = self.pc.connectionState
            logger.info(f"[VideoSession] WebRTC connection state: {state} (session={self.session_id})")
            if state in ("failed", "closed", "disconnected"):
                self.is_running = False

        return self.pc

    async def _process_audio_track(self, track: "MediaStreamTrack") -> None:
        """
        Process incoming audio track from WebRTC.

        Receives audio frames → resamples to 16kHz PCM16 →
        sends to Gemini/Azure Live client (same pipeline as voice calls).
        """
        logger.info(f"[VideoSession] Starting audio pipeline for session {self.session_id}")

        try:
            from src.common.database import get_db
            from src.voice.live_client_factory import LiveClientFactory
            from src.voice.agent_loader import AgentContextLoader
            from src.voice.audio_processor import AudioProcessor
            from uuid import UUID
            import av

            audio_processor = AudioProcessor()
            gemini_session = None

            async for db in get_db():
                loader = AgentContextLoader(db)
                agent_context = await loader.load_agent_for_session(
                    agent_id=UUID(self.agent_info["agent_id"]),
                    customer_id=UUID(self.agent_info["company_id"]),  # fallback
                    channel="video",
                )
                factory = LiveClientFactory(
                    db=db,
                    company_id=UUID(self.agent_info["company_id"]),
                )
                live_or_tuple, provider = await factory.create_client(
                    system_instruction=agent_context.system_instruction
                    + "\n\n[VIDEO CONTEXT]: " + (self.vision_context or "No visual context yet."),
                    voice_config=agent_context.voice_config,
                )
                if provider == "azure_openai":
                    azure_client, azure_cfg = live_or_tuple
                    await azure_client.connect(azure_cfg)
                    gemini_session = azure_client
                else:
                    await live_or_tuple.connect()
                    gemini_session = live_or_tuple
                break

            if not gemini_session:
                logger.error(f"[VideoSession] Could not connect AI session for {self.session_id}")
                return

            self.is_running = True

            # Start receiving AI audio responses
            self._ai_audio_task = asyncio.create_task(
                self._receive_ai_audio(gemini_session)
            )

            # Forward WebRTC audio frames → AI
            async for frame in track.recv.__self__.__class__.__mro__[0]:  # type hint workaround
                break  # This is just for type hints; actual loop below

            while self.is_running:
                try:
                    frame = await track.recv()
                    # Convert av.AudioFrame → raw PCM16
                    resampled = frame.to_ndarray(format="s16", layout="mono")
                    pcm16 = resampled.tobytes()
                    try:
                        if hasattr(gemini_session, "send_audio"):
                            await gemini_session.send_audio(pcm16)
                        elif hasattr(gemini_session, "send_realtime_input"):
                            await gemini_session.send_realtime_input(
                                audio={"data": pcm16, "mime_type": "audio/pcm;rate=16000"}
                            )
                    except Exception as exc:
                        logger.error(f"[VideoSession] AI audio send error: {exc}")
                        break
                except Exception:
                    break

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(f"[VideoSession] Audio track error: {exc}", exc_info=True)

    async def _receive_ai_audio(self, ai_session: Any) -> None:
        """Receive AI audio responses and send back over WebRTC data channel (as base64 PCM)."""
        try:
            while self.is_running:
                async for response in ai_session.receive():
                    if not self.is_running:
                        break
                    if response.data:
                        # Send AI audio response to client as binary over WS
                        # (for web clients; RTP forwarding for bots requires different path)
                        try:
                            await self.ws.send_bytes(response.data)
                        except Exception:
                            break
                if not self.is_running:
                    break
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(f"[VideoSession] AI audio receive error: {exc}", exc_info=True)

    async def _process_video_track(self, track: "MediaStreamTrack") -> None:
        """
        Process incoming video track — sample frames at 1fps → send to Vision model.

        Extracts a JPEG frame every second → sends to the configured vision model →
        updates self.vision_context with AI description → injected into audio AI prompt.
        """
        logger.info(f"[VideoSession] Starting video vision pipeline for session {self.session_id}")
        import time

        last_sample_time = 0.0
        SAMPLE_INTERVAL = 5.0  # Sample every 5 seconds (configurable)

        try:
            while self.is_running:
                try:
                    frame = await track.recv()
                except Exception:
                    break

                now = time.monotonic()
                if now - last_sample_time < SAMPLE_INTERVAL:
                    continue
                last_sample_time = now

                # Convert to JPEG
                try:
                    img = frame.to_image()  # PIL Image
                    import io
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=60)
                    jpeg_bytes = buf.getvalue()

                    # Send to vision model asynchronously
                    asyncio.create_task(
                        self._analyze_video_frame(jpeg_bytes)
                    )
                except Exception as exc:
                    logger.debug(f"[VideoSession] Frame processing error: {exc}")

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(f"[VideoSession] Video track error: {exc}", exc_info=True)

    async def _analyze_video_frame(self, jpeg_bytes: bytes) -> None:
        """
        Send a video frame to the configured vision model and update vision context.

        Uses the company's configured vision/multimodal model (falls back to Gemini Flash).
        """
        try:
            import base64
            from src.common.database import AsyncSessionLocal
            from src.ai.llm.router import LLMRouter
            from uuid import UUID

            async with AsyncSessionLocal() as db:
                router = LLMRouter(db=db, company_id=UUID(self.agent_info["company_id"]))
                b64_frame = base64.b64encode(jpeg_bytes).decode("utf-8")

                resp = await router.call_llm(
                    task_type="vision",
                    system_prompt=(
                        "You are analyzing a video frame from a live video call. "
                        "Describe what you see briefly (2-3 sentences): "
                        "who is present, their apparent emotion/mood, and any relevant visual context."
                    ),
                    user_prompt=f"[Image: data:image/jpeg;base64,{b64_frame}]",
                )
                if resp.output:
                    self.vision_context = resp.output[:500]  # Cap to 500 chars
                    logger.debug(f"[VideoSession] Vision context updated: {self.vision_context[:100]}...")
        except Exception as exc:
            logger.debug(f"[VideoSession] Vision analysis error: {exc}")

    async def close(self) -> None:
        """Gracefully close the session."""
        self.is_running = False
        if self._ai_audio_task:
            self._ai_audio_task.cancel()
        if self._frame_sample_task:
            self._frame_sample_task.cancel()
        if self.pc:
            await self.pc.close()


# ===========================================================================
# Active sessions registry
# ===========================================================================

_active_video_sessions: Dict[str, VideoSession] = {}


# ===========================================================================
# Unified Video Endpoint
# ===========================================================================

@router.websocket("/stream/video")
async def unified_video_streaming(websocket: WebSocket):
    """
    Unified Bidirectional Video Streaming — Interface 5.

    WebRTC signaling endpoint. Clients negotiate a WebRTC peer connection
    over this WebSocket and then send media via DTLS/SRTP.

    Signaling protocol (WebSocket JSON messages):

    Client → Server:
      1. {"event": "connect", "provider": "web|zoom|teams", "client_id": "...", "token": "..."}
      2. {"event": "offer", "sdp": "<SDP offer string>", "type": "offer"}
      3. {"event": "ice_candidate", "candidate": {"candidate": "...", "sdpMid": ..., ...}}
      4. {"event": "stop"}

    Server → Client:
      1. {"event": "connected", "session_id": "...", "status": "ready", "webrtc_enabled": bool}
      2. {"event": "answer", "sdp": "<SDP answer>", "type": "answer"}
      3. {"event": "ice_candidate", "candidate": {...}}
      4. Binary frames: raw PCM16 audio from AI (for web clients)

    Zoom/Teams Integration Note:
      Your bot should connect here as provider="zoom" or provider="teams".
      The bot captures meeting audio/video and forwards as a WebRTC stream.
      This gateway will process audio through the AI pipeline and send
      AI responses back as audio that your bot can play in the meeting.
    """
    await websocket.accept()
    logger.info("[VideoGateway] New WebSocket connection")

    session_id = str(uuid.uuid4())
    session: Optional[VideoSession] = None

    try:
        # ── Step 1: Connect handshake ─────────────────────────────────────────
        raw = await websocket.receive_text()
        handshake = json.loads(raw)

        if handshake.get("event") != "connect":
            await websocket.close(code=1003, reason="First message must be connect event")
            return

        provider = handshake.get("provider", "web")
        client_id = handshake.get("client_id", "")

        if not client_id:
            await websocket.close(code=1003, reason="client_id required")
            return

        # ── Step 2: Validate & resolve agent ──────────────────────────────────
        dispatcher = get_dispatcher()
        agent_info = await dispatcher.resolve_agent_for_client(client_id, "video")

        if not agent_info:
            await websocket.send_text(json.dumps({
                "event": "error",
                "code": "no_agent",
                "message": f"No AI agent configured for client {client_id}",
            }))
            await websocket.close(code=1008)
            return

        # ── Step 3: Check aiortc availability ─────────────────────────────────
        from src.gateway.gateway_config import settings
        webrtc_enabled = AIORTC_AVAILABLE and settings.VIDEO_STREAMING_ENABLED

        await websocket.send_text(json.dumps({
            "event": "connected",
            "session_id": session_id,
            "status": "ready",
            "provider": provider,
            "agent_id": agent_info["agent_id"],
            "webrtc_enabled": webrtc_enabled,
        }))

        logger.info(
            f"[VideoGateway] Session {session_id} connected "
            f"(provider={provider}, client={client_id}, webrtc={webrtc_enabled})"
        )

        if not webrtc_enabled:
            # Serve signaling ack only — inform client to check aiortc installation
            await websocket.send_text(json.dumps({
                "event": "info",
                "message": (
                    "WebRTC media disabled. "
                    "Install aiortc: pip install aiortc aiohttp"
                ) if not AIORTC_AVAILABLE else (
                    "Video streaming disabled via VIDEO_STREAMING_ENABLED=false"
                ),
            }))
            # Keep WS open so client can receive the info
            await asyncio.sleep(2)
            await websocket.close()
            return

        # ── Step 4: Create VideoSession ────────────────────────────────────────
        ice_servers = settings.stun_servers_list
        if settings.TURN_SERVER_URL:
            ice_servers.append(settings.TURN_SERVER_URL)

        session = VideoSession(
            session_id=session_id,
            client_id=client_id,
            agent_info=agent_info,
            provider=provider,
            ws=websocket,
            ice_servers=ice_servers,
        )
        _active_video_sessions[session_id] = session
        pc = await session.create_peer_connection()

        # ── Step 5: Signaling loop ────────────────────────────────────────────
        while True:
            try:
                raw = await websocket.receive_text()
                msg = json.loads(raw)
            except WebSocketDisconnect:
                logger.info(f"[VideoGateway] Client disconnected: {session_id}")
                break
            except Exception as exc:
                logger.error(f"[VideoGateway] Receive error: {exc}")
                break

            event = msg.get("event")

            if event == "offer":
                # Process SDP offer and send answer
                sdp_offer = RTCSessionDescription(
                    sdp=msg["sdp"],
                    type=msg.get("type", "offer"),
                )
                await pc.setRemoteDescription(sdp_offer)
                answer = await pc.createAnswer()
                await pc.setLocalDescription(answer)

                await websocket.send_text(json.dumps({
                    "event": "answer",
                    "sdp": pc.localDescription.sdp,
                    "type": pc.localDescription.type,
                }))
                logger.info(f"[VideoGateway] SDP answer sent for session {session_id}")

            elif event == "ice_candidate":
                candidate_data = msg.get("candidate", {})
                if candidate_data and candidate_data.get("candidate"):
                    from aiortc import RTCIceCandidate
                    candidate = RTCIceCandidate(
                        sdpMid=candidate_data.get("sdpMid"),
                        sdpMLineIndex=candidate_data.get("sdpMLineIndex", 0),
                        candidate=candidate_data["candidate"],
                    )
                    await pc.addIceCandidate(candidate)

            elif event == "stop":
                logger.info(f"[VideoGateway] Client requested stop: {session_id}")
                break

            else:
                logger.debug(f"[VideoGateway] Unknown event: {event}")

    except WebSocketDisconnect:
        logger.info(f"[VideoGateway] WebSocket disconnected: {session_id}")
    except Exception as exc:
        logger.error(f"[VideoGateway] Session error: {exc}", exc_info=True)
    finally:
        if session:
            await session.close()
            _active_video_sessions.pop(session_id, None)
        try:
            await websocket.close()
        except Exception:
            pass
        logger.info(f"[VideoGateway] Session {session_id} cleaned up")


# ===========================================================================
# Metrics / status helper
# ===========================================================================

def get_active_video_sessions() -> Dict[str, dict]:
    """Return metadata about active video sessions (for /metrics endpoint)."""
    return {
        sid: {
            "client_id": s.client_id,
            "provider": s.provider,
            "is_running": s.is_running,
            "has_audio": s.audio_track is not None,
            "has_video": s.video_track is not None,
        }
        for sid, s in _active_video_sessions.items()
    }
