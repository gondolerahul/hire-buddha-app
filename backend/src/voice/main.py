"""
FastAPI app for Voice and WhatsApp streaming service.

This application runs on Port 8002 and handles WebSocket connections
for real-time bidirectional audio streaming with Twilio, Tata Tele,
and Gemini Live API.
"""
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import os

# Import routers (after app initialization)
# from src.voice.webhook_router import router as webhook_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="HireBuddha Streaming Service",
    description="Real-time voice and WhatsApp streaming",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure based on environment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
# Note: Import here to avoid circular dependencies
try:
    from src.voice.webhook_router import router as webhook_router
    app.include_router(webhook_router)
    logger.info("Webhook router included")
except Exception as e:
    logger.warning(f"Could not include webhook router: {e}")

try:
    from src.voice.transcript_api import router as transcript_router
    app.include_router(transcript_router)
    logger.info("Transcript API router included")
except Exception as e:
    logger.warning(f"Could not include transcript router: {e}")

try:
    from src.voice.messaging_router import router as messaging_router
    app.include_router(messaging_router)
    logger.info("Messaging router included")
except Exception as e:
    logger.warning(f"Could not include messaging router: {e}")


@app.on_event("startup")
async def startup_event():
    """Initialize resources on startup."""
    logger.info("Streaming service starting up...")
    logger.info(f"Running in {os.getenv('ENVIRONMENT', 'development')} mode")


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources on shutdown."""
    logger.info("Streaming service shutting down...")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "HireBuddha Streaming Service",
        "version": "1.0.0",
        "status": "active"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "service": "streaming",
        "timestamp": str(__import__('datetime').datetime.utcnow())
    }


@app.get("/metrics")
async def metrics():
    """
    Metrics endpoint (to be extended with Prometheus).
    Returns current streaming statistics.
    """
    # TODO: Implement actual metrics collection
    return {
        "active_voice_calls": 0,
        "active_whatsapp_sessions": 0,
        "total_calls_today": 0,
        "total_messages_today": 0
    }


# Diagnostic HTTP endpoint for WebSocket paths
# When Twilio can't establish a WebSocket (e.g., proxy not forwarding Upgrade headers),
# it falls back to a regular HTTP GET which would return 404. This endpoint catches
# those requests and provides a helpful diagnostic message.
@app.get("/stream/twilio/{session_id}")
async def twilio_stream_diagnostic(session_id: str):
    """
    Diagnostic endpoint for Twilio WebSocket connections.
    
    If you're seeing this response, it means the reverse proxy (Apache/Nginx)
    is NOT forwarding WebSocket upgrade headers to this server.
    
    This is the root cause of Twilio Error 31920 (WebSocket Handshake Error).
    """
    return JSONResponse(
        status_code=426,  # 426 Upgrade Required
        content={
            "error": "WebSocket Upgrade Required",
            "message": (
                "This endpoint requires a WebSocket connection. "
                "If you see this from Twilio, your reverse proxy (Apache) is not "
                "forwarding WebSocket upgrade headers. Enable mod_proxy_wstunnel."
            ),
            "session_id": session_id,
            "expected_protocol": "wss://",
            "documentation": "See docs/apache_websocket_config.md for Apache config",
            "fix": (
                "Add to Apache config: RewriteEngine On; "
                "RewriteCond %{HTTP:Upgrade} =websocket [NC]; "
                "RewriteRule /stream/(.*) ws://127.0.0.1:8002/stream/$1 [P,L]"
            )
        }
    )


# WebSocket endpoints
@app.websocket("/stream/twilio/{session_id}")
async def twilio_websocket(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for Twilio Media Streams.
    
    Handles bidirectional audio streaming:
    - Receives audio from Twilio
    - Processes through Gemini Live API
    - Sends AI responses back to Twilio
    """
    from uuid import UUID
    from src.common.database import get_db
    from src.voice.websocket_handler import TwilioStreamHandler
    
    await websocket.accept()
    logger.info(f"Twilio WebSocket connected: session_id={session_id}")
    
    try:
        # Convert session_id to UUID
        session_uuid = UUID(session_id)
        
        # Get database session
        async for db in get_db():
            # Create handler and process stream
            handler = TwilioStreamHandler(
                websocket=websocket,
                session_id=session_uuid,
                db=db
            )
            
            await handler.handle()
            break
            
    except ValueError as e:
        logger.error(f"Invalid session ID: {session_id}")
        await websocket.close()
    except Exception as e:
        logger.error(f"Twilio WebSocket error: {e}", exc_info=True)
        try:
            await websocket.close()
        except:
            pass


@app.websocket("/webhooks/voice/tata/incoming")
async def tata_main_websocket(websocket: WebSocket):
    """Main endpoint for Tata Tele WebSocket connection."""
    from src.common.database import get_db
    from src.voice.websocket_handler import TataStreamHandler
    
    await websocket.accept()
    logger.info("Tata Tele WebSocket connection accepted")
    
    try:
        async for db in get_db():
            handler = TataStreamHandler(
                websocket=websocket,
                db=db
            )
            await handler.handle_direct()
            break
    except Exception as e:
        logger.error(f"Tata Tele main WebSocket error: {e}", exc_info=True)
        try:
            await websocket.close()
        except:
            pass

@app.websocket("/stream/tata/{session_id}")
async def tata_websocket(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for Tata Tele audio streams.
    
    Similar to Twilio but handles Tata Tele specific protocol.
    Uses TwilioStreamHandler as the protocols are compatible.
    """
    from uuid import UUID
    from src.common.database import get_db
    from src.voice.websocket_handler import TwilioStreamHandler
    
    await websocket.accept()
    logger.info(f"Tata Tele WebSocket connected: session_id={session_id}")
    
    try:
        # Convert session_id to UUID
        session_uuid = UUID(session_id)
        
        # Get database session
        async for db in get_db():
            # Create handler and process stream
            handler = TwilioStreamHandler(
                websocket=websocket,
                session_id=session_uuid,
                db=db
            )
            
            await handler.handle()
            break
            
    except ValueError as e:
        logger.error(f"Invalid session ID: {session_id}")
        await websocket.close()
    except Exception as e:
        logger.error(f"Tata Tele WebSocket error: {e}", exc_info=True)
        try:
            await websocket.close()
        except:
            pass


# Error handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("STREAMING_PORT", 8002)),
        log_level="info"
    )
