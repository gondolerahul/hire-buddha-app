"""GET /metrics/gateway — live counters for the webhook and streaming edge."""
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/metrics/gateway")
async def gateway_metrics() -> dict:
    """Event bus and active video sessions. Declared before the ``/metrics``
    Prometheus mount (``setup_telemetry``), which would otherwise match first."""
    from src.gateway.event_bus import get_event_bus
    from src.gateway.video_gateway import get_active_video_sessions

    return {
        "event_bus": get_event_bus().stats,
        "active_video_sessions": len(get_active_video_sessions()),
        "video_sessions": get_active_video_sessions(),
    }
