"""
Interface 5: Unified Bidirectional Video Streaming Gateway.

Single WebSocket endpoint: WS /stream/video

Architecture:
  - Signaling Layer (this file): WebSocket-based SDP offer/answer + ICE exchange
  - Media Layer: aiortc WebRTC peer connection
  - AI Pipeline: Audio track → 16 kHz PCM16 → the agent's live model session
                 (the same one connect path as a phone call, VT-02); its audio
                 replies go back to the client as binary frames (PCM16, 24 kHz)
                 Video track → a frame every 5 s → the vision model → a short
                 description, added to the live session as context (GW-10)

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

A video call is a live session like a phone call: it is admitted by the one
call rule (credit, spend cap, the company's live-session cap —
``voice.call_admission``), holds one of the company's live-session places
while it lasts (GW-02), and its model use — the live audio each way and every
frame description — is billed to one run for the call (LP-26).

ICE servers: ``STUN_SERVERS`` and, when set, ``TURN_SERVER_URL`` with
``TURN_USERNAME`` / ``TURN_CREDENTIAL`` (GW-06). The same list is sent to the
client in the ``connected`` message, so a browser behind a symmetric NAT can
reach the relay too.

``aiortc`` is a declared dependency. If an install lacks it, the endpoint
answers the handshake, says so, and closes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Iterator, List, Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.gateway.dispatcher import get_dispatcher
from src.gateway.socket_limits import TOO_MANY, handshake_allowed
from src.gateway.stream_auth import stream_company

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
    AIORTC_AVAILABLE = True
except ImportError:
    AIORTC_AVAILABLE = False
    logger.warning("[VideoGateway] aiortc is not installed; /stream/video answers the handshake only")

# What the live model is sent: PCM16 mono at 16 kHz.
LIVE_INPUT_RATE = 16000
LIVE_INPUT_MIME = f"audio/pcm;rate={LIVE_INPUT_RATE}"
# A frame is described every this many seconds.
FRAME_SAMPLE_SECONDS = 5.0


def ice_servers() -> List[Dict[str, Any]]:
    """STUN, and TURN with its credentials when configured (GW-06)."""
    from src.common.config import settings

    servers: List[Dict[str, Any]] = [{"urls": url} for url in settings.stun_servers_list]
    if settings.TURN_SERVER_URL:
        turn: Dict[str, Any] = {"urls": settings.TURN_SERVER_URL}
        if settings.TURN_USERNAME:
            turn["username"] = settings.TURN_USERNAME
        if settings.TURN_CREDENTIAL:
            turn["credential"] = settings.TURN_CREDENTIAL
        servers.append(turn)
    return servers


def audio_resampler() -> Any:
    """Turns WebRTC's audio (48 kHz Opus, often stereo) into what the model takes."""
    import av

    return av.AudioResampler(format="s16", layout="mono", rate=LIVE_INPUT_RATE)


def pcm16_chunks(resampler: Any, frame: Any) -> Iterator[bytes]:
    """One received audio frame as PCM16 mono 16 kHz byte strings."""
    for out in resampler.resample(frame) or []:
        data = out.to_ndarray().tobytes()
        if data:
            yield data


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
        # Running from the start: the video track can arrive before the audio
        # track has connected the model, and its loop must not end at once.
        self.is_running = True
        self.vision_context: str = ""        # Latest visual context from the AI vision model
        self.live_session: Any = None        # the model's live session, once audio connects
        self._live_cm: Any = None
        # The run the call's model use is billed to (LP-26).
        from src.gateway.call_spend import CallSpend
        from src.voice.live_usage import LiveUsage
        self.spend = CallSpend(company_id=agent_info["company_id"], agent_id=agent_info["agent_id"],
                               channel="video", session_id=session_id)
        self.usage = LiveUsage()
        self._frame_tasks: Set[asyncio.Task] = set()
        self._tasks: Set[asyncio.Task] = set()
        self.audio_track = None
        self.video_track = None

    def _start(self, coro: Any) -> asyncio.Task:
        """A pipeline task the session's close cancels."""
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def create_peer_connection(self) -> "RTCPeerConnection":
        """Create a configured WebRTC PeerConnection."""
        config = RTCConfiguration(iceServers=[
            RTCIceServer(urls=s["urls"], username=s.get("username"), credential=s.get("credential"))
            for s in self.ice_servers
        ])
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
        def on_track(track):
            logger.info(f"[VideoSession] Track received: kind={track.kind}, session={self.session_id}")
            if track.kind == "audio":
                self.audio_track = track
                self._start(self._process_audio_track(track))
            elif track.kind == "video":
                self.video_track = track
                self._start(self._process_video_track(track))

        @self.pc.on("connectionstatechange")
        async def on_state_change():
            state = self.pc.connectionState
            logger.info(f"[VideoSession] WebRTC connection state: {state} (session={self.session_id})")
            if state in ("failed", "closed"):
                self.is_running = False

        return self.pc

    async def _connect_live(self) -> Any:
        """The agent's live model session — the one connect path (VT-02)."""
        from uuid import UUID

        from src.common.tenancy.session import tenant_session
        from src.voice.agent_loader import AgentContextLoader
        from src.voice.live_client_factory import LiveClientFactory

        # The agent is in its company's tenant database (Phase 14 WS2).
        async with tenant_session(UUID(self.agent_info["company_id"])) as db:
            agent_context = await AgentContextLoader(db).load_agent_for_session(
                agent_id=UUID(self.agent_info["agent_id"]),
                customer_id=UUID(self.agent_info["company_id"]),
                channel="video",
            )
            live_client, provider = await LiveClientFactory(
                db=db, company_id=UUID(self.agent_info["company_id"]),
            ).create_client(
                system_instruction=agent_context.system_instruction
                + "\n\n[VIDEO CONTEXT]: " + (self.vision_context or "No visual context yet."),
                voice_config=agent_context.voice_config,
                generation_config=agent_context.llm_config.get("parameters", {}),
            )
        self._live_cm = await live_client.connect()
        self.live_session = await self._live_cm.__aenter__()
        logger.info(f"[VideoSession] Connected {provider} for session {self.session_id}")
        return self.live_session

    async def _process_audio_track(self, track: "MediaStreamTrack") -> None:
        """
        Process incoming audio track from WebRTC.

        Connects the live model, then resamples each received frame to 16 kHz
        PCM16 mono and sends it on — the same input a phone call gives it.
        """
        logger.info(f"[VideoSession] Starting audio pipeline for session {self.session_id}")
        try:
            session = await self._connect_live()
            self._start(self._receive_ai_audio(session))
            resampler = audio_resampler()
            while self.is_running:
                try:
                    frame = await track.recv()
                except Exception:          # the track ended (MediaStreamError)
                    break
                for pcm16 in pcm16_chunks(resampler, frame):
                    self.usage.sent(len(pcm16))
                    await session.send_realtime_input(audio={"data": pcm16, "mime_type": LIVE_INPUT_MIME})
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(f"[VideoSession] Audio track error: {exc}", exc_info=True)

    async def _receive_ai_audio(self, ai_session: Any) -> None:
        """Receive AI audio responses and send them to the client as binary frames."""
        try:
            while self.is_running:
                async for response in ai_session.receive():
                    if not self.is_running:
                        break
                    # The provider's usage for this turn, summed for the bill (VT-05).
                    self.usage.add(getattr(response, "usage_metadata", None))
                    data = getattr(response, "data", None)
                    if data:
                        self.usage.received(len(data))
                        # (for web clients; RTP forwarding for bots requires a different path)
                        try:
                            await self.ws.send_bytes(data)
                        except Exception:
                            self.is_running = False
                            break
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(f"[VideoSession] AI audio receive error: {exc}", exc_info=True)

    async def _process_video_track(self, track: "MediaStreamTrack") -> None:
        """
        Process incoming video track — a frame every ``FRAME_SAMPLE_SECONDS`` →
        the vision model → its description, added to the live session.
        """
        logger.info(f"[VideoSession] Starting video vision pipeline for session {self.session_id}")
        import time

        last_sample_time = 0.0
        try:
            while self.is_running:
                try:
                    frame = await track.recv()
                except Exception:
                    break

                now = time.monotonic()
                if now - last_sample_time < FRAME_SAMPLE_SECONDS:
                    continue
                last_sample_time = now

                # Convert to JPEG
                try:
                    img = frame.to_image()  # PIL Image
                    import io
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=60)
                    jpeg_bytes = buf.getvalue()

                    # Send to vision model asynchronously; kept, so the call's
                    # end waits for it before settling what it cost (LP-26).
                    task = asyncio.create_task(self._analyze_video_frame(jpeg_bytes))
                    self._frame_tasks.add(task)
                    task.add_done_callback(self._frame_tasks.discard)
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
            from src.common.tenancy.session import tenant_session
            from src.ai.llm.router import LLMRouter
            from src.ai.llm.types import Attachment
            from uuid import UUID

            system_prompt = (
                "You are analyzing a video frame from a live video call. "
                "Describe what you see briefly (2-3 sentences): "
                "who is present, their apparent emotion/mood, and any relevant visual context."
            )
            # The call's run is in the company's tenant database.
            async with tenant_session(UUID(self.agent_info["company_id"])) as db:
                router = LLMRouter(db=db, company_id=UUID(self.agent_info["company_id"]))
                # The frame is an image part, not base64 text in the prompt (LP-24).
                resp = await router.call_llm(
                    task_type="vision",
                    system_prompt=system_prompt,
                    user_prompt="Describe this frame.",
                    attachments=[Attachment(mime_type="image/jpeg", data=jpeg_bytes)],
                )
                if resp.output:
                    self.vision_context = resp.output[:500]  # Cap to 500 chars
                    logger.debug(f"[VideoSession] Vision context updated: {self.vision_context[:100]}...")
                # Billed to the call's run; it used to be free (LP-26). A
                # billing failure is logged, and never costs the call its context.
                try:
                    await self.spend.record(db, resp, attribution="video_frame",
                                            system_prompt=system_prompt, user_prompt="Describe this frame.")
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"[VideoSession] Could not bill a frame description: {exc}")
            if resp.output:
                await self.share_vision_context()
        except Exception as exc:
            logger.debug(f"[VideoSession] Vision analysis error: {exc}")

    async def share_vision_context(self) -> bool:
        """Give the live model what the camera shows now (GW-10).

        The description used to go only into the system instruction, which is
        sent once when the audio connects — when there is no description yet —
        so the model never saw one. It is added as context without a turn
        (``turn_complete=False``): the model reads it and answers only when the
        caller speaks. A provider whose session cannot take that (Azure
        Realtime) keeps the instruction-time context only.
        """
        session = self.live_session
        if session is None or not self.vision_context or not hasattr(session, "send_client_content"):
            return False
        try:
            await session.send_client_content(
                turns={"role": "user", "parts": [{"text": f"[What the camera shows now] {self.vision_context}"}]},
                turn_complete=False,
            )
            return True
        except Exception as exc:  # noqa: BLE001 - the call goes on without it
            logger.warning(f"[VideoSession] Could not share the camera context: {exc}")
            return False

    async def close(self) -> None:
        """Gracefully close the session, and settle what its model calls cost."""
        self.is_running = False
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.pc:
            await self.pc.close()
        if self._live_cm is not None:
            try:
                await self._live_cm.__aexit__(None, None, None)
            except Exception:
                pass
        if self._frame_tasks:
            await asyncio.wait(set(self._frame_tasks), timeout=30)
        try:
            from src.common.tenancy.session import tenant_session

            async with tenant_session(self.spend.company_id) as db:
                await self.spend.record_live_audio(db, self.usage)
                await self.spend.finish(db)
        except Exception as exc:  # noqa: BLE001 - a billing hiccup must not break teardown
            logger.warning(f"[VideoSession] Could not settle the call's model use: {exc}")


# ===========================================================================
# Active sessions registry
# ===========================================================================

_active_video_sessions: Dict[str, VideoSession] = {}


async def _admit(websocket: WebSocket, company_id: str) -> Any:
    """The call's admission and its live-session place, or ``None`` once refused."""
    from src.common.tenancy.session import control_session
    from src.voice import live_sessions
    from src.voice.call_admission import call_refusal

    async with control_session() as db:  # the wallet is a control row
        refusal = await call_refusal(db, company_id, direction="inbound", checkpoint="video")
    slot = None if refusal else live_sessions.acquire(company_id, kind="video")
    if slot is not None:
        return slot
    over_cap = refusal is None or live_sessions.at_cap(company_id)
    code, reason = (TOO_MANY, "too_many_live_sessions") if over_cap else (4002, "insufficient_credits")
    await websocket.send_text(json.dumps({
        "event": "error", "code": reason, "message": refusal or live_sessions.cap_message(),
    }))
    await websocket.close(code=code, reason=reason)
    return None


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
      1. {"event": "connected", "session_id": "...", "status": "ready", "webrtc_enabled": bool,
          "ice_servers": [{"urls": ..., "username"?: ..., "credential"?: ...}]}
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
    if not handshake_allowed(websocket):
        # GW-02: so many handshakes from one address a minute.
        await websocket.close(code=TOO_MANY, reason="rate_limited")
        return

    session_id = str(uuid.uuid4())
    session: Optional[VideoSession] = None
    slot: Any = None

    try:
        # ── Step 1: Connect handshake ─────────────────────────────────────────
        raw = await websocket.receive_text()
        handshake = json.loads(raw)

        if handshake.get("event") != "connect":
            await websocket.close(code=1003, reason="First message must be connect event")
            return

        provider = handshake.get("provider", "web")
        # The company is the stream token's, never the handshake's word (GW-04).
        client_id = await stream_company(websocket, handshake)
        if client_id is None:
            return

        # ── Step 2: Validate & resolve agent ──────────────────────────────────
        dispatcher = get_dispatcher()
        agent_info = await dispatcher.resolve_agent_for_client(client_id, "video", handshake.get("agent_id"))

        if agent_info and agent_info.get("error"):
            # An unknown agent, or several to choose from (GW-17).
            await websocket.send_text(json.dumps({
                "event": "error", "code": agent_info["error"], "message": agent_info["message"],
            }))
            await websocket.close(code=1008)
            return
        if not agent_info:
            await websocket.send_text(json.dumps({
                "event": "error",
                "code": "no_agent",
                "message": f"No AI agent configured for client {client_id}",
            }))
            await websocket.close(code=1008)
            return

        # ── Step 3: Check aiortc availability ─────────────────────────────────
        from src.common.config import settings
        webrtc_enabled = AIORTC_AVAILABLE and settings.VIDEO_STREAMING_ENABLED

        if not webrtc_enabled:
            await websocket.send_text(json.dumps({
                "event": "connected", "session_id": session_id, "status": "ready",
                "provider": provider, "agent_id": agent_info["agent_id"], "webrtc_enabled": False,
            }))
            # Serve signaling ack only — say why there is no media.
            await websocket.send_text(json.dumps({
                "event": "info",
                "message": (
                    "WebRTC media is unavailable: aiortc is not installed on this server"
                ) if not AIORTC_AVAILABLE else (
                    "Video streaming disabled via VIDEO_STREAMING_ENABLED=false"
                ),
            }))
            # Keep WS open so client can receive the info
            await asyncio.sleep(2)
            await websocket.close()
            return

        # ── Step 4: Admit the call and hold its place (GW-02) ─────────────────
        slot = await _admit(websocket, client_id)
        if slot is None:
            return

        servers = ice_servers()
        await websocket.send_text(json.dumps({
            "event": "connected",
            "session_id": session_id,
            "status": "ready",
            "provider": provider,
            "agent_id": agent_info["agent_id"],
            "webrtc_enabled": True,
            "ice_servers": servers,
        }))
        logger.info(
            f"[VideoGateway] Session {session_id} connected "
            f"(provider={provider}, client={client_id})"
        )

        # ── Step 5: Create VideoSession ────────────────────────────────────────
        session = VideoSession(
            session_id=session_id,
            client_id=client_id,
            agent_info=agent_info,
            provider=provider,
            ws=websocket,
            ice_servers=servers,
        )
        _active_video_sessions[session_id] = session
        pc = await session.create_peer_connection()

        # ── Step 6: Signaling loop ────────────────────────────────────────────
        while session.is_running:
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
                    from aiortc.sdp import candidate_from_sdp
                    sdp = candidate_data["candidate"]
                    candidate = candidate_from_sdp(sdp.split(":", 1)[1] if sdp.startswith("candidate:") else sdp)
                    candidate.sdpMid = candidate_data.get("sdpMid")
                    candidate.sdpMLineIndex = candidate_data.get("sdpMLineIndex", 0)
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
        if slot is not None:
            slot.release()
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
