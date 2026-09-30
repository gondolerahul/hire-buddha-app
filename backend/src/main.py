"""The HireBuddha API — every HTTP and WebSocket endpoint, on one port (8000).

This process also serves what the Unified Gateway on :8001 used to: the inbound
webhook and internal-event endpoints, the audio/video and telephony media-stream
WebSockets, and the mobile push socket. The gateway's reverse proxy, CORS list
and rate limit are gone or folded in here.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from src.auth.router import router as auth_router
from src.common.config import settings
from src.common.database import engine, Base
from src.common.rate_limit import limiter


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the dispatcher: the agent cache for the audio/video WebSockets."""
    from src.gateway.dispatcher import get_dispatcher

    if not settings.internal_events_enabled:
        logging.getLogger(__name__).warning(
            "INTERNAL_TOKEN is empty or a placeholder: POST /internal/event answers 503"
        )
    dispatcher = get_dispatcher()
    await dispatcher.start()
    yield
    await dispatcher.stop()


app = FastAPI(title="HireBuddha Platform", version="0.2.0", lifespan=lifespan)

# Middleware runs outermost-last-added: CORS answers preflights and decorates
# every response (a 429 included) before the limiter sees it. A suspended
# company is refused by get_current_user (auth/dependencies.py), not here (SA-18).
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



app.include_router(auth_router, prefix="/api/v1")
from src.auth.company_router import router as company_router
app.include_router(company_router, prefix="/api/v1")
from src.auth.profile_router import router as profile_router
app.include_router(profile_router, prefix="/api/v1")
from src.auth.user_router import router as user_router
app.include_router(user_router, prefix="/api/v1")

# Onboarding wizard
from src.auth.onboarding_router import router as onboarding_router
app.include_router(onboarding_router, prefix="/api/v1")

# Optional routers: a failed import leaves that router out and is reported by
# GET /api/v1/health instead of crashing the boot (PO-10).
from src.common.router_mounts import health_router, mount_optional
app.include_router(health_router)

# Partner management
mount_optional(app, "src.auth.partner_router", prefix="/api/v1")

from fastapi.staticfiles import StaticFiles
from pathlib import Path

# Ensure reports directory exists
reports_dir = Path("/tmp/research_reports")
reports_dir.mkdir(parents=True, exist_ok=True)

# ── Unified artifact directory ──────────────────────────────────────────────────
# All platform-managed files live under backend/artifact/
#   user-uploads/      — files uploaded by human users
#   system-generated/  — files produced by AI agents / tools
# Derive from this file's location so it works regardless of CWD.
_backend_dir = Path(__file__).resolve().parents[1]   # …/backend/src -> …/backend
artifact_dir = _backend_dir / "artifact"
(artifact_dir / "user-uploads").mkdir(parents=True, exist_ok=True)
(artifact_dir / "system-generated").mkdir(parents=True, exist_ok=True)

# Legacy uploads dir (profile pictures stored here until migrated)
uploads_dir = _backend_dir / "uploads"
uploads_dir.mkdir(parents=True, exist_ok=True)

app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")
app.mount("/reports", StaticFiles(directory=str(reports_dir)), name="reports")
app.mount("/artifact", StaticFiles(directory=str(artifact_dir)), name="artifact")

from src.config.router import router as config_router
app.include_router(config_router, prefix="/api/v1")
from src.ai.router import router as ai_router
app.include_router(ai_router, prefix="/api/v1")
from src.ai.api.admin import router as kernel_admin_router
app.include_router(kernel_admin_router, prefix="/api/v1")
from src.ai.campaign_router import router as campaign_router
app.include_router(campaign_router, prefix="/api/v1")
# Mobile dialer app API (docs/mobile-dialer-app)
from src.mobile.router import router as mobile_router
app.include_router(mobile_router, prefix="/api/v1")
from src.mobile.analytics_router import router as mobile_analytics_router
app.include_router(mobile_analytics_router, prefix="/api/v1")
# Mobile dialer app push socket (WS /mobile/ws)
from src.mobile.push_gateway import router as mobile_push_router
app.include_router(mobile_push_router)

# CORTEX Memory Architecture
from src.ai.memory.cortex_router import router as cortex_router
app.include_router(cortex_router)

# Artifact management (replaces legacy /assets routes)
from src.ai.artifact_router import router as artifact_router
app.include_router(artifact_router)

# Legacy /assets → /artifacts redirect support (kept for backwards compatibility)
from fastapi.responses import RedirectResponse
@app.get("/api/v1/assets", include_in_schema=False)
async def legacy_assets_list():
    return RedirectResponse(url="/api/v1/artifacts")
@app.get("/api/v1/assets/{path:path}", include_in_schema=False)
async def legacy_assets_path(path: str):
    return RedirectResponse(url=f"/api/v1/artifacts/{path}")

# Billing, reports, credits, and cron jobs
mount_optional(app, "src.billing.billing_router")
mount_optional(app, "src.billing.credits_router")
mount_optional(app, "src.billing.cron_router")

# Analytics & Reports
mount_optional(app, "src.ai.reports_router")

# Email connection management
mount_optional(app, "src.ai.email_router", prefix="/api/v1")

# Social media connection management
mount_optional(app, "src.ai.social_router")

# Tool Registry Management
mount_optional(app, "src.ai.tool_management_router")

# Voice and WhatsApp webhook routers
mount_optional(app, "src.voice.webhook_router")  # No prefix - webhooks are at /webhooks/voice/*
mount_optional(app, "src.voice.phone_number_router")
mount_optional(app, "src.voice.sessions_router")
mount_optional(app, "src.voice.messaging_router")

# Inbound events and real-time media (formerly the gateway on :8001)
mount_optional(app, "src.gateway.webhook_inbound")      # POST /webhook/inbound
mount_optional(app, "src.gateway.internal_event")       # POST /internal/event
mount_optional(app, "src.gateway.telephony_streams")    # WS /stream/twilio|tata/{id}, /webhooks/voice/tata/incoming
mount_optional(app, "src.gateway.audio_gateway")        # WS /stream/audio
mount_optional(app, "src.gateway.video_gateway")        # WS /stream/video
mount_optional(app, "src.gateway.status")               # GET /metrics/gateway


@app.get("/")
async def root():
    return {"message": "Welcome to HireBuddha Platform v2.0"}

from src.common.telemetry import setup_telemetry
setup_telemetry(app)
