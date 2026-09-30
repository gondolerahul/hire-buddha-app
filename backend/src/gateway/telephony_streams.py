"""
Telephony media-stream WebSockets (Twilio / Tata Tele).

The voice webhooks (``/webhooks/voice/*``) hand the provider one of these URLs,
built by ``voice.public_urls.stream_url``; the provider then opens a WebSocket
here for bidirectional audio:

  WS /stream/twilio/{session_id}      Twilio Media Streams (TwiML <Stream>)
  WS /stream/tata/{session_id}        Tata Tele (Twilio-compatible wire format)
  WS /webhooks/voice/tata/incoming    Tata Tele direct stream after click-to-call

These served on the gateway (:8001), and before that on the retired voice
service (:8002). They are now mounted by the API on port 8000.
"""
import logging
from uuid import UUID

from fastapi import APIRouter, WebSocket

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Telephony Streams"])


@router.websocket("/webhooks/voice/tata/incoming")
async def tata_websocket_incoming(websocket: WebSocket):
    """
    WebSocket endpoint for Tata Tele bidirectional audio streaming.

    After click-to-call-support places a call and the customer answers,
    Tata Tele opens a WebSocket connection here to stream audio. Their
    protocol: connected → start → media (loop) → stop. The HTTP webhook on the
    same path is served by voice/webhook_router.py.
    """
    from src.common.database import get_db
    from src.voice.websocket_handler import TataStreamHandler

    await websocket.accept()
    logger.info("[Streams] Tata Tele WebSocket connection accepted")

    try:
        async for db in get_db():
            handler = TataStreamHandler(websocket=websocket, db=db)
            await handler.handle_direct()
            break
    except Exception as e:
        logger.error(f"[Streams] Tata Tele WebSocket error: {e}", exc_info=True)
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/stream/twilio/{session_id}")
async def twilio_stream_websocket(websocket: WebSocket, session_id: str):
    """
    Twilio Media Stream WebSocket endpoint.

    Twilio connects here after the /webhooks/voice/twilio/incoming HTTP
    webhook returns TwiML with <Connect><Stream url="wss://…/stream/twilio/…"/>.
    """
    await _twilio_compatible_stream(websocket, session_id, "Twilio")


@router.websocket("/stream/tata/{session_id}")
async def tata_stream_websocket(websocket: WebSocket, session_id: str):
    """
    Tata Tele Media Stream WebSocket endpoint.

    Tata Tele connects here after the /webhooks/voice/tata/incoming HTTP
    webhook returns {"wss_url": "wss://…/stream/tata/…"}.
    Uses TwilioStreamHandler since Tata's wire protocol is Twilio-compatible.
    """
    await _twilio_compatible_stream(websocket, session_id, "Tata Tele")


async def _twilio_compatible_stream(websocket: WebSocket, session_id: str, provider: str) -> None:
    from src.common.database import get_db
    from src.voice.websocket_handler import TwilioStreamHandler

    await websocket.accept()
    logger.info(f"[Streams] {provider} WebSocket connected: session_id={session_id}")

    try:
        session_uuid = UUID(session_id)
        async for db in get_db():
            handler = TwilioStreamHandler(
                websocket=websocket,
                session_id=session_uuid,
                db=db,
            )
            await handler.handle()
            break
    except ValueError:
        logger.error(f"[Streams] Invalid {provider} session ID: {session_id}")
        await websocket.close()
    except Exception as e:
        logger.error(f"[Streams] {provider} WebSocket error: {e}", exc_info=True)
        try:
            await websocket.close()
        except Exception:
            pass
