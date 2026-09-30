"""GET /metrics/gateway — live counters for the streaming edge."""
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/metrics/gateway")
async def gateway_metrics() -> dict:
    """Active video sessions. Declared before the ``/metrics`` Prometheus mount
    (``setup_telemetry``), which would otherwise match first.

    The in-process event-bus counters that used to be here went with the bus
    (SA-09): webhook and internal events go straight onto the arq queue.
    """
    from src.gateway.video_gateway import get_active_video_sessions

    return {
        "active_video_sessions": len(get_active_video_sessions()),
        "video_sessions": get_active_video_sessions(),
    }
