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
    """Start the dispatcher (the agent cache for the audio/video WebSockets),
    the listener that drops an edited agent from this process's cache (VT-16)
    and the one that drops a changed feature flag (GH-14)."""
    import asyncio
    import contextlib

    from src.gateway.dispatcher import get_dispatcher
    from src.voice import agent_cache_bus

    if not settings.internal_events_enabled:
        logging.getLogger(__name__).warning(
            "INTERNAL_TOKEN is empty or a placeholder: POST /internal/event answers 503"
        )
    from src.common.config import warn_unknown_env_keys

    warn_unknown_env_keys(logging.getLogger(__name__))  # a misspelt setting is otherwise ignored (C-8)
    from src.ai.core.feature_flags import listen_for_invalidations, warn_if_table_missing

    await warn_if_table_missing()
    dispatcher = get_dispatcher()
    await dispatcher.start()
    agent_changes = asyncio.create_task(agent_cache_bus.listen(settings.REDIS_URL))
    flag_changes = asyncio.create_task(listen_for_invalidations(settings.REDIS_URL))
    listeners = [agent_changes, flag_changes]
    try:  # the connector catalog follows its YAML (WS5); the migrations Job also syncs it
        from src.common.tenancy.session import control_session
        from src.connections.catalog import sync_catalog
        async with control_session() as db:
            await sync_catalog(db)
    except Exception:  # noqa: BLE001 - a missing table before migrations must not stop the API
        logging.getLogger(__name__).warning("connector catalog not synced", exc_info=True)
    from src.connections.api_versions import warn_if_stale
    warn_if_stale()  # a provider API version near its sunset (LI-E1, GADS-E2)
    from src.common.tenancy.session import is_split
    if is_split():  # a moved or suspended tenant is seen at once (Phase 14 WS2)
        from src.common.tenancy.directory import listen_for_changes
        listeners.append(asyncio.create_task(listen_for_changes(settings.REDIS_URL)))
    yield
    for listener in listeners:
        listener.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await listener
    await dispatcher.stop()


app = FastAPI(title="HireBuddha Platform", version="0.2.0", lifespan=lifespan)

# Middleware runs outermost-last-added: CORS answers preflights and decorates
# every response (a 429 included) before the limiter sees it. A suspended
# company is refused by get_current_user (auth/dependencies.py), not here (SA-18).
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
# Tenants and partners see billed amounts only, in their currency (Phase 15 T9-3).
from src.billing.money_view import MoneyViewMiddleware  # noqa: E402

app.add_middleware(MoneyViewMiddleware)

# Split tenancy: a company whose database is not ready yet (being provisioned,
# or never requested) gets a 503 that says so, not a 500 (Phase 14 WS2 2.9).
from src.common.tenancy.errors import install_tenancy_error_handlers  # noqa: E402

install_tenancy_error_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Outermost: HSTS, nosniff, framing and a content policy on every answer (SH-E5).
from src.common.security_headers import SecurityHeadersMiddleware  # noqa: E402

app.add_middleware(SecurityHeadersMiddleware)



# What a plan includes (Phase 15 T6-2): router-level feature gates below.
from fastapi import Depends  # noqa: E402

from src.billing.features import require_feature  # noqa: E402

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

from src.common.platform import adapter_name

# ── Static file mounts: local-disk storage only (Phase 14 WS1 1.3) ─────────────
# Files are opened through GET /api/v1/files/{id} (authorised; a signed storage
# URL on Azure). These mounts only keep links stored before it working on a
# local-disk deployment; with Blob storage there is no local directory to serve.
if adapter_name("storage") == "local_disk":
    reports_dir = Path("/tmp/research_reports")
    reports_dir.mkdir(parents=True, exist_ok=True)

    # backend/artifact/ — local-disk storage's root; before storage keys:
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
from src.ai.api.versions import router as entity_versions_router
app.include_router(entity_versions_router, prefix="/api/v1")
from src.ai.campaign_router import router as campaign_router
app.include_router(campaign_router, prefix="/api/v1",
                   dependencies=[Depends(require_feature("feature.voice.outbound_campaigns"))])
# Mobile dialer app API (docs/mobile-dialer-app)
from src.mobile.router import router as mobile_router
app.include_router(mobile_router, prefix="/api/v1",
                   dependencies=[Depends(require_feature("feature.voice.mobile_dialer"))])
from src.mobile.analytics_router import router as mobile_analytics_router
app.include_router(mobile_analytics_router, prefix="/api/v1")
# Mobile dialer app push socket (WS /mobile/ws)
from src.mobile.push_gateway import router as mobile_push_router
app.include_router(mobile_push_router)

# CORTEX Memory Architecture
from src.ai.memory.cortex_router import router as cortex_router
app.include_router(cortex_router, dependencies=[Depends(require_feature("feature.knowledge.cortex_explorer"))])

# Artifact management (the legacy /assets routes and their redirects are gone, API-11)
from src.ai.artifact_router import files_router, router as artifact_router
app.include_router(artifact_router)
app.include_router(files_router)  # GET /api/v1/files/{id} — signed file links

# Billing, reports, credits, and cron jobs
mount_optional(app, "src.billing.billing_router")
mount_optional(app, "src.billing.credits_router")
mount_optional(app, "src.billing.razorpay_webhook")  # POST /api/v1/credits/razorpay/webhook
mount_optional(app, "src.billing.currency_router")  # /api/v1/admin/currencies, fx-rates … (Phase 15 T2-4)
mount_optional(app, "src.billing.shadow_router")  # /api/v1/admin/billing-shadow (Phase 15 T3-7)
mount_optional(app, "src.billing.settings_router")  # /api/v1/admin/billing-settings (Phase 15 T5-1)
mount_optional(app, "src.billing.wallet_router")  # /api/v1/admin/wallets, /api/v1/credits/ledger (Phase 15 T4-1, T2-7)
mount_optional(app, "src.billing.daily_credits_router")  # /api/v1/admin/daily-credits (Phase 15 T5-5)
mount_optional(app, "src.billing.price_items_router")  # /api/v1/admin/price-items (Phase 15 T5-3)
mount_optional(app, "src.billing.locks")  # /api/v1/companies/{id}/locks (Phase 15 T5-4)
mount_optional(app, "src.billing.plans_router")  # /api/v1/plans, /api/v1/me/entitlements, /api/v1/admin/plans (Phase 15 T6-1, T6-2)
mount_optional(app, "src.billing.invoices_router")  # /api/v1/billing/invoices, /billing/profile, /admin/payments (Phase 15 T6-5, T6-6)
mount_optional(app, "src.partners.portal_router")  # /api/v1/partner/* — the Partner Portal (Phase 15 WS15-8)
mount_optional(app, "src.partners.tenant_router")  # /api/v1/charges, /settings/partner-access, /partners/apply
mount_optional(app, "src.partners.admin_router")  # /api/v1/admin/partners/* — the programme for staff
mount_optional(app, "src.offboarding.router")  # closing and erasing businesses; deleting test ones (Phase 15, docs 13)
mount_optional(app, "src.auth.support_access")  # /api/v1/support-access — staff and connected-account content (SH-E6)
mount_optional(app, "src.messaging.api")  # /api/v1/conversations, /api/v1/whatsapp/opt-ins (META-E4, META-E5)
mount_optional(app, "src.reports.router")  # /api/v1/reports, /api/v1/reports/{id} — the report library (Phase 15 T9-4)
mount_optional(app, "src.billing.cron_router")

# Analytics & Reports
mount_optional(app, "src.ai.reports_router")

# Email connection management
mount_optional(app, "src.ai.email_router", prefix="/api/v1", feature="feature.messaging.email")

# Social media connection management
mount_optional(app, "src.ai.social_router", feature="feature.messaging.social")

# Tool Registry Management
mount_optional(app, "src.ai.tool_management_router")

# Voice and WhatsApp webhook routers
mount_optional(app, "src.voice.webhook_router")  # No prefix - webhooks are at /webhooks/voice/*
mount_optional(app, "src.voice.phone_number_router")
mount_optional(app, "src.voice.sessions_router")
mount_optional(app, "src.voice.messaging_router")

# Inbound events and real-time media (formerly the gateway on :8001)
mount_optional(app, "src.gateway.webhook_inbound")      # POST /webhook/inbound/{endpoint_id}
mount_optional(app, "src.gateway.webhook_endpoints_router", feature="feature.automation.webhooks_inbound")  # /api/v1/webhook-endpoints
mount_optional(app, "src.gateway.internal_event")       # POST /internal/event
mount_optional(app, "src.gateway.telephony_streams")    # WS /stream/twilio|tata/{id}, /webhooks/voice/tata/incoming
mount_optional(app, "src.gateway.audio_gateway")        # WS /stream/audio
mount_optional(app, "src.gateway.video_gateway")        # WS /stream/video
mount_optional(app, "src.gateway.status")               # GET /metrics/gateway

# Event-driven automation (Phase 14 WS3): settings, and the control room as it grows
mount_optional(app, "src.automation.api")                # /api/v1/automation/*, /api/v1/admin/automation/*
mount_optional(app, "src.notifications.router")         # /api/v1/notifications
mount_optional(app, "src.data_api.platform_router")     # /api/v1/records/token, /api/v1/data-keys
# Tenant databases (Phase 14 WS2): the caller's workspace, and provisioning for staff
mount_optional(app, "src.common.tenancy.api")             # /api/v1/workspace, /api/v1/admin/tenants*
# Connections (Phase 14 WS5): connectors, connect flow, token broker, provider webhooks
mount_optional(app, "src.connections.api")              # /api/v1/connect*, /oauth/callback/*, /webhook/provider/*

# The Data API (WS4, tech spec §9): a business's records at /data/v1/…; it also
# runs on its own (src.data_api.main), one per business in Kubernetes.
from src.data_api.app import DataApiPreflight, create_app as _create_data_api  # noqa: E402

app.mount("/data", _create_data_api())
# Tenant apps' preflights to /data/* are answered before the platform's CORS list refuses them.
app.add_middleware(DataApiPreflight)

# Code lanes, Git and tenant apps (Phase 14 WS6): /api/v1/code-items, /api/v1/apps, the edge's ask
mount_optional(app, "src.apps.api")


@app.get("/")
async def root():
    return {"message": "Welcome to HireBuddha Platform v2.0"}

from src.common.telemetry import setup_telemetry
setup_telemetry(app)
