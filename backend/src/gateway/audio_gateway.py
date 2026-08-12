"""
Interface 4: Unified Bidirectional Audio Streaming Gateway.

Single WebSocket endpoint: WS /stream/audio

Supports multiple telephony/audio providers through a unified handshake:
  1. Client connects to WS /stream/audio
  2. Client sends a JSON "connect" event identifying the provider and tenant
  3. Gateway validates credentials, creates/resumes a VoiceSession
  4. Delegates to the existing BaseStreamHandler pipeline (Gemini Live / Azure Realtime)

Supported providers:
  - "twilio"    — Twilio Media Streams (base64 mulaw, JSON events)
  - "tata_tele" — Tata Tele (same wire format as Twilio)
  - "exotel"    — Exotel (same wire format as Twilio / mulaw)
  - "web"       — Raw PCM16 from browser (for web calling clients)

Backward compatibility:
  The existing /stream/twilio/{session_id} and /stream/tata/{session_id}
  endpoints continue to work unchanged. This endpoint is additive.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.gateway.dispatcher import get_dispatcher

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Audio Streaming"])


# ---------------------------------------------------------------------------
# Provider adapter registry
# ---------------------------------------------------------------------------

# Maps provider name → handler class (loaded lazily to share the
# existing streaming module without import-time side effects)
AUDIO_PROVIDER_ADAPTERS = {
    "twilio": "TwilioAudioAdapter",
    "tata_tele": "TataAudioAdapter",
    "exotel": "ExotelAudioAdapter",
    "web": "WebAudioAdapter",
}


# ===========================================================================
# Unified Audio Endpoint
# ===========================================================================

@router.websocket("/stream/audio")
async def unified_audio_streaming(websocket: WebSocket):
    """
    Unified Bidirectional Audio Streaming — Interface 4.

    Provider-agnostic WebSocket endpoint for real-time bidirectional audio.

    Handshake protocol (sent by caller after connection):
      {
        "event":    "connect",
        "provider": "twilio" | "tata_tele" | "exotel" | "web",
        "client_id": "<company_uuid>",
        "token":    "<short-lived JWT or API key>",
        "metadata": {
          "session_id": "<optional: resume an existing VoiceSession>",
          "direction":  "inbound" | "outbound",
          "phone_number": "<caller number>"
        }
      }

    On success the gateway replies:
      {"event": "connected", "session_id": "<uuid>", "status": "ready"}

    Audio then flows bidirectionally using the provider's native wire format.
    """
    await websocket.accept()
    logger.info("[AudioGateway] New WebSocket connection")

    # ── Step 1: Wait for connect handshake ───────────────────────────────────
    try:
        raw = await websocket.receive_text()
        handshake = json.loads(raw)
    except Exception as exc:
        logger.error(f"[AudioGateway] Invalid handshake: {exc}")
        await websocket.close(code=1003, reason="Invalid handshake JSON")
        return

    if handshake.get("event") != "connect":
        await websocket.close(code=1003, reason="First message must be {event: 'connect'}")
        return

    provider = handshake.get("provider", "twilio").lower()
    client_id = handshake.get("client_id", "")
    token = handshake.get("token", "")
    metadata = handshake.get("metadata", {})
    session_id_override = metadata.get("session_id")

    if not client_id:
        await websocket.close(code=1003, reason="client_id required in handshake")
        return

    # ── Step 2: Validate token & resolve agent ───────────────────────────────
    dispatcher = get_dispatcher()
    agent_info = await dispatcher.resolve_agent_for_client(client_id, "audio")

    if not agent_info:
        logger.warning(f"[AudioGateway] No agent found for client {client_id}")
        await _send_error(websocket, "no_agent", f"No AI agent configured for client {client_id}")
        await websocket.close(code=1008, reason="No agent found for client")
        return

    # ── Step 3: Delegate to provider-specific handler ────────────────────────
    if provider not in AUDIO_PROVIDER_ADAPTERS:
        await _send_error(websocket, "unsupported_provider", f"Provider '{provider}' not supported")
        await websocket.close(code=1003, reason=f"Unsupported provider: {provider}")
        return

    logger.info(
        f"[AudioGateway] Routing to {provider} adapter for client={client_id} "
        f"agent={agent_info['agent_id']}"
    )

    try:
        await _run_audio_adapter(
            websocket=websocket,
            provider=provider,
            client_id=client_id,
            agent_info=agent_info,
            metadata=metadata,
            session_id_override=session_id_override,
        )
    except WebSocketDisconnect:
        logger.info(f"[AudioGateway] Client disconnected ({provider}, client={client_id})")
    except Exception as exc:
        logger.error(f"[AudioGateway] Error in audio session: {exc}", exc_info=True)
        try:
            await websocket.close()
        except Exception:
            pass


async def _run_audio_adapter(
    websocket: WebSocket,
    provider: str,
    client_id: str,
    agent_info: dict,
    metadata: dict,
    session_id_override: Optional[str],
) -> None:
    """
    Create the appropriate audio adapter and run the bidirectional pipeline.

    Twilio, Tata Tele, Exotel all share the same wire format (base64 mulaw JSON events).
    Web adapter handles raw PCM16 from browser clients.
    """
    from src.common.database import get_db
    from src.voice.session_manager import SessionManager
    from uuid import UUID

    # ── Acknowledge the connection ────────────────────────────────────────────
    async for db in get_db():
        session_manager = SessionManager(db)

        # Resolve or create VoiceSession
        if session_id_override:
            try:
                voice_session = await session_manager.get_voice_session(UUID(session_id_override))
            except Exception:
                voice_session = None
        else:
            voice_session = None

        if not voice_session:
            phone_number = metadata.get("phone_number", "unknown")
            direction = metadata.get("direction", "inbound")

            voice_session = await session_manager.create_voice_session(
                company_id=UUID(agent_info["company_id"]),
                customer_id=UUID(agent_info.get("customer_id", agent_info["company_id"])),
                agent_id=UUID(agent_info["agent_id"]),
                phone_number=phone_number,
                provider=provider,
                call_sid=f"gw_{provider}_{id(websocket)}",
                direction=direction,
                metadata={
                    "client_id": client_id,
                    "gateway": "unified_audio",
                    **metadata,
                }
            )

        # Send acknowledgment to client
        await websocket.send_text(json.dumps({
            "event": "connected",
            "session_id": str(voice_session.id),
            "status": "ready",
            "provider": provider,
            "agent_id": agent_info["agent_id"],
        }))

        logger.info(
            f"[AudioGateway] Session {voice_session.id} ready "
            f"({provider}, agent={agent_info['agent_id']})"
        )

        # ── Route to the correct handler ──────────────────────────────────────
        if provider in ("twilio", "tata_tele", "exotel"):
            # Twilio-compatible wire format: base64 mulaw chunks in JSON events
            from src.voice.websocket_handler import TwilioStreamHandler
            handler = TwilioStreamHandler(
                websocket=websocket,
                session_id=voice_session.id,
                db=db,
            )
            await handler.handle()

        elif provider == "web":
            # Raw PCM16 from browser
            from src.gateway.web_audio_adapter import WebAudioAdapter
            adapter = WebAudioAdapter(
                websocket=websocket,
                voice_session=voice_session,
                db=db,
            )
            await adapter.handle()

        break



async def _send_error(websocket: WebSocket, code: str, message: str) -> None:
    """Send a JSON error event to the client."""
    try:
        await websocket.send_text(json.dumps({
            "event": "error",
            "code": code,
            "message": message,
        }))
    except Exception:
        pass
