"""
Unified AI Gateway — Main Application.

Replaces the existing thin proxy gateway (port 8001) with a full multi-protocol
gateway that handles all 5 interface types:

  1. /api/v1/*            Domain REST API (proxied to backend:8000)
  2. /webhook/inbound     Unified Webhook Receiver (all external systems)
  3. /internal/event      Internal Event Endpoint (microservices)
  4. /stream/audio        Bidirectional Audio Streaming (Twilio/Tata/Exotel/Web)
  5. /stream/video        Bidirectional Video Streaming (WebRTC SFU)

Additionally:
  /stream/twilio/{session_id}   ← backward-compat audio (Twilio)
  /stream/tata/{session_id}     ← backward-compat audio (Tata Tele)
  /webhooks/voice/*             ← backward-compat voice webhook router

Port: 8001 (merging with existing proxy gateway)
"""
import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from src.gateway.gateway_config import settings
from src.gateway.event_bus import get_event_bus
from src.gateway.dispatcher import get_dispatcher
from src.gateway.auth_middleware import GatewayAuthMiddleware

# Interface routers
from src.gateway.webhook_inbound import router as webhook_router
from src.gateway.internal_event import router as internal_event_router
from src.gateway.audio_gateway import router as audio_router
from src.gateway.video_gateway import router as video_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the event bus and dispatcher on startup."""
    logger.info("Unified Gateway starting up...")

    # Initialize event bus
    bus = get_event_bus()
    logger.info(f"[Startup] Event bus ready (type=memory, maxsize={bus._maxsize})")

    # Initialize and start the Central AI Dispatcher
    dispatcher = get_dispatcher()
    await dispatcher.start()
    logger.info("[Startup] Central AI Dispatcher ready")

    yield  # App is running

    # Shutdown
    logger.info("Unified Gateway shutting down...")
    await dispatcher.stop()
    logger.info("[Shutdown] Dispatcher stopped")


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMIT],
    storage_uri=settings.REDIS_URL,
)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="HireBuddha Unified AI Gateway",
    description=(
        "Multi-protocol AI gateway handling REST, Webhooks, Internal Events, "
        "Audio Streaming (WebSocket), and Video Streaming (WebRTC)."
    ),
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Rate limiter ──────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth middleware ───────────────────────────────────────────────────────────
app.add_middleware(GatewayAuthMiddleware)


# ---------------------------------------------------------------------------
# Include Interface Routers
# ---------------------------------------------------------------------------

# Interface 2: Unified Webhook Endpoint
app.include_router(webhook_router)

# Interface 3: Internal Event Endpoint
app.include_router(internal_event_router)

# Interface 4: Unified Audio Streaming
app.include_router(audio_router)

# Interface 5: Unified Video Streaming (WebRTC)
app.include_router(video_router)

# NOTE: The standalone streaming service (port 8002) has been retired.
# All audio/video streaming is served natively by this gateway via:
#   /stream/audio   — unified audio WebSocket (twilio, tata_tele, exotel, web)
#   /stream/video   — unified video WebSocket (WebRTC)
# Voice HTTP webhooks (/webhooks/voice/*) are served by the main backend (port 8000).


# ---------------------------------------------------------------------------
# Interface 1: REST API Passthrough Proxy
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Gateway-specific endpoints (MUST be defined before the catch-all proxy)
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=True)
async def root():
    return {
        "service": "HireBuddha Unified AI Gateway",
        "version": "2.0.0",
        "interfaces": {
            "rest": "/api/v1/* → backend:8000",
            "webhook": "POST /webhook/inbound",
            "internal_event": "POST /internal/event",
            "audio_stream": "WS /stream/audio",
            "video_stream": "WS /stream/video",
        },
    }


@app.get("/health", include_in_schema=True)
async def health_check():
    from src.gateway.event_bus import get_event_bus
    bus = get_event_bus()
    return {
        "status": "healthy",
        "service": "unified-gateway",
        "version": "2.0.0",
        "interfaces": ["rest", "webhook", "internal_event", "audio", "video"],
        "event_bus": bus.stats,
    }


@app.get("/metrics/gateway", include_in_schema=True)
async def gateway_metrics():
    """Gateway-level metrics (event bus, active sessions)."""
    from src.gateway.event_bus import get_event_bus
    from src.gateway.video_gateway import get_active_video_sessions

    bus = get_event_bus()

    return {
        "event_bus": bus.stats,
        "active_video_sessions": len(get_active_video_sessions()),
        "video_sessions": get_active_video_sessions(),
    }


# ---------------------------------------------------------------------------
# Tata Tele WebSocket — Direct audio streaming endpoint
# ---------------------------------------------------------------------------
# Tata Tele connects via WebSocket to this path after click-to-call initiates.
# Their protocol: connected → start → media (loop) → stop

@app.websocket("/webhooks/voice/tata/incoming")
async def tata_websocket_incoming(websocket: WebSocket):
    """
    WebSocket endpoint for Tata Tele bidirectional audio streaming.
    
    After click-to-call-support places a call and the customer answers,
    Tata Tele opens a WebSocket connection here to stream audio.
    """
    from src.common.database import get_db
    from src.voice.websocket_handler import TataStreamHandler

    await websocket.accept()
    logger.info("[Gateway] Tata Tele WebSocket connection accepted")

    try:
        async for db in get_db():
            handler = TataStreamHandler(
                websocket=websocket,
                db=db
            )
            await handler.handle_direct()
            break
    except Exception as e:
        logger.error(f"[Gateway] Tata Tele WebSocket error: {e}", exc_info=True)
        try:
            await websocket.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Backward-compat: /stream/twilio/{session_id} and /stream/tata/{session_id}
# ---------------------------------------------------------------------------
# The webhook router returns these URLs to Twilio/Tata after the HTTP webhook.
# The telephony provider then opens a WebSocket to stream bidirectional audio.
# These endpoints previously lived on the retired port-8002 streaming service.

@app.websocket("/stream/twilio/{session_id}")
async def twilio_stream_websocket(websocket: WebSocket, session_id: str):
    """
    Backward-compatible Twilio Media Stream WebSocket endpoint.

    Twilio connects here after the /webhooks/voice/twilio/incoming HTTP
    webhook returns TwiML with <Connect><Stream url="wss://…/stream/twilio/…"/>.
    """
    from uuid import UUID
    from src.common.database import get_db
    from src.voice.websocket_handler import TwilioStreamHandler

    await websocket.accept()
    logger.info(f"[Gateway] Twilio WebSocket connected: session_id={session_id}")

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
        logger.error(f"[Gateway] Invalid Twilio session ID: {session_id}")
        await websocket.close()
    except Exception as e:
        logger.error(f"[Gateway] Twilio WebSocket error: {e}", exc_info=True)
        try:
            await websocket.close()
        except Exception:
            pass


@app.websocket("/stream/tata/{session_id}")
async def tata_stream_websocket(websocket: WebSocket, session_id: str):
    """
    Backward-compatible Tata Tele Media Stream WebSocket endpoint.

    Tata Tele connects here after the /webhooks/voice/tata/incoming HTTP
    webhook returns {"wss_url": "wss://…/stream/tata/…"}.
    Uses TwilioStreamHandler since Tata's wire protocol is Twilio-compatible.
    """
    from uuid import UUID
    from src.common.database import get_db
    from src.voice.websocket_handler import TwilioStreamHandler

    await websocket.accept()
    logger.info(f"[Gateway] Tata Tele WebSocket connected: session_id={session_id}")

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
        logger.error(f"[Gateway] Invalid Tata session ID: {session_id}")
        await websocket.close()
    except Exception as e:
        logger.error(f"[Gateway] Tata Tele WebSocket error: {e}", exc_info=True)
        try:
            await websocket.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Interface 1: REST API Passthrough Proxy (catch-all — MUST be last)
# ---------------------------------------------------------------------------

_proxy_client: httpx.AsyncClient = None


def _get_proxy_client() -> httpx.AsyncClient:
    """Lazily initialize proxy client (works in both ASGI tests and production)."""
    global _proxy_client
    if _proxy_client is None:
        _proxy_client = httpx.AsyncClient(
            base_url=settings.BACKEND_URL,
            timeout=httpx.Timeout(60.0, connect=10.0),
            follow_redirects=True,
        )
        logger.info(f"[Proxy] HTTP client lazily initialized → {settings.BACKEND_URL}")
    return _proxy_client


@app.on_event("shutdown")
async def close_proxy_client():
    if _proxy_client:
        await _proxy_client.aclose()


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
@limiter.limit(settings.RATE_LIMIT)
async def proxy_to_backend(request: Request, path: str):
    """
    Interface 1: Domain REST API — transparent reverse proxy to backend.

    All /api/v1/* and other REST paths are forwarded to the main FastAPI
    backend on port 8000. This preserves all existing REST endpoints.
    """
    url = f"/{path}"
    if request.query_params:
        url += f"?{request.query_params}"

    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)

    content = await request.body()
    proxy = _get_proxy_client()

    # Server-Sent Events (e.g. execution event streams) are open-ended — they
    # never "complete", so buffering them with proxy.request() blocks until the
    # read timeout fires and the client gets a 503. Relay these as a live
    # stream with no read timeout instead.
    wants_sse = (
        path.endswith("/stream")
        or "text/event-stream" in headers.get("accept", "")
    )
    if wants_sse:
        try:
            req = proxy.build_request(
                method=request.method, url=url, headers=headers, content=content,
                timeout=httpx.Timeout(None, connect=10.0),  # no read timeout for SSE
            )
            upstream = await proxy.send(req, stream=True)
        except httpx.RequestError as exc:
            logger.error(f"[Proxy] SSE backend unreachable: {exc}")
            return Response(
                content=f'{{"error": "Backend unavailable", "detail": "{exc}"}}',
                status_code=503, media_type="application/json",
            )
        if upstream.status_code != 200:
            body = await upstream.aread()
            await upstream.aclose()
            return Response(
                content=body, status_code=upstream.status_code,
                headers=dict(upstream.headers),
            )

        async def _relay_sse():
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()

        return StreamingResponse(
            _relay_sse(),
            status_code=200,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # disable proxy buffering (nginx/apache)
            },
        )

    try:
        response = await proxy.request(
            method=request.method,
            url=url,
            headers=headers,
            content=content,
        )
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=dict(response.headers),
        )
    except httpx.RequestError as exc:
        logger.error(f"[Proxy] Backend unreachable: {exc}")
        return Response(
            content=f'{{"error": "Backend unavailable", "detail": "{exc}"}}',
            status_code=503,
            media_type="application/json",
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.gateway.app:app",
        host="0.0.0.0",
        port=int(os.getenv("GATEWAY_PORT", 8001)),
        log_level="info",
        reload=True,
    )
