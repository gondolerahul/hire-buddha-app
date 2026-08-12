from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.auth.router import router as auth_router
from src.common.database import engine, Base

app = FastAPI(title="HireBuddha Platform", version="0.2.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://34.100.230.121:3000",
        "https://dev.hirebuddha.com",
        "https://app.hirebuddha.com",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "https://gateway.hirebuddha.com"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from src.common.middleware import CompanySuspensionMiddleware
app.add_middleware(CompanySuspensionMiddleware)



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

# Partner management
try:
    from src.auth.partner_router import router as partner_router
    app.include_router(partner_router, prefix="/api/v1")
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"Could not import partner router: {e}")

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

# CORTEX Memory Architecture
from src.ai.memory.cortex_router import router as cortex_router
app.include_router(cortex_router)

# Artifact management (replaces legacy /assets routes)
from src.ai.artifact_router import router as artifact_router
app.include_router(artifact_router)

# Legacy /assets → /artifacts redirect support (kept for backwards compatibility)
from fastapi.responses import RedirectResponse
from fastapi import Request
@app.get("/api/v1/assets", include_in_schema=False)
async def legacy_assets_list():
    return RedirectResponse(url="/api/v1/artifacts")
@app.get("/api/v1/assets/{path:path}", include_in_schema=False)
async def legacy_assets_path(path: str):
    return RedirectResponse(url=f"/api/v1/artifacts/{path}")

# Kernel admin de-prefix compat shim. The router moved from
# /api/v1/ai/phase11/* to /api/v1/ai/admin/*; this redirect keeps old
# bookmarks and the unmigrated frontend working. Remove after 2026-09-01.
@app.api_route(
    "/api/v1/ai/phase11/{subpath:path}",
    methods=["GET", "POST"],
    include_in_schema=False,
)
async def legacy_kernel_admin_redirect(subpath: str, request: Request):
    target = f"/api/v1/ai/admin/{subpath}"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return RedirectResponse(url=target, status_code=307)

# Billing, reports, credits, and cron jobs
try:
    from src.billing.billing_router import router as billing_router
    app.include_router(billing_router)
    from src.billing.credits_router import router as credits_router
    app.include_router(credits_router)
    from src.billing.cron_router import router as cron_router
    app.include_router(cron_router)
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"Could not import billing routers: {e}")

# Analytics & Reports
try:
    from src.ai.reports_router import router as reports_analytics_router
    app.include_router(reports_analytics_router)
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"Could not import analytics reports router: {e}")

# Email connection management
try:
    from src.ai.email_router import router as email_router
    app.include_router(email_router, prefix="/api/v1")
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"Could not import email router: {e}")

# Social media connection management
try:
    from src.ai.social_router import router as social_router
    app.include_router(social_router)
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"Could not import social router: {e}")

# Tool Registry Management
try:
    from src.ai.tool_management_router import router as tool_mgmt_router
    app.include_router(tool_mgmt_router)
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"Could not import tool management router: {e}")

# Voice and WhatsApp webhook routers
try:
    from src.voice.webhook_router import router as webhook_router
    app.include_router(webhook_router)  # No prefix - webhooks are at /webhooks/voice/*
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"Could not import voice webhook router: {e}")

try:
    from src.voice.phone_number_router import router as phone_number_router
    app.include_router(phone_number_router)
    from src.voice.sessions_router import router as sessions_router
    app.include_router(sessions_router)
    from src.voice.messaging_router import router as messaging_router
    app.include_router(messaging_router)
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"Could not import voice routers: {e}")


# Phone Number Pool is now unified into phone_number_router (no separate router)




@app.get("/")
async def root():
    return {"message": "Welcome to HireBuddha Platform v2.0"}

from src.common.telemetry import setup_telemetry
setup_telemetry(app)
