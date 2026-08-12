"""
Unified Gateway Configuration.

Extends the original GatewaySettings with all new interface settings.
The gateway merges the existing HTTP proxy (port 8001) with:
  - Unified Webhook endpoint
  - Internal Event endpoint
  - Bidirectional Audio WebSocket
  - Bidirectional Video WebSocket (WebRTC)
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class UnifiedGatewaySettings(BaseSettings):
    # ── Existing proxy settings ──────────────────────────────────────────────
    BACKEND_URL: str = "http://localhost:8000"   # Main FastAPI app
    REDIS_URL: str = "redis://localhost:6379"
    RATE_LIMIT: str = "200/minute"

    # ── Port ─────────────────────────────────────────────────────────────────
    GATEWAY_PORT: int = 8001

    # ── Streaming host (for constructing WebSocket URLs passed to telephony) ─
    STREAMING_HOST: str = "localhost:8001"
    STREAMING_PROTOCOL: str = "wss"

    # ── Database (needed for Dispatcher + SessionManager) ────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/hirebuddha"

    # ── Internal event auth ──────────────────────────────────────────────────
    # Shared secret used by microservices to authenticate on /internal/event
    INTERNAL_TOKEN: str = "change-me-in-production"

    # ── JWT for gateway-level auth (audio/video handshake) ───────────────────
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"

    # ── Event bus ────────────────────────────────────────────────────────────
    # "memory" = in-process asyncio.Queue (default)
    # "kafka"  = Apache Kafka (future)
    EVENT_BUS_TYPE: str = "memory"
    EVENT_BUS_MAXSIZE: int = 1000  # Max queued events before backpressure

    # ── Video streaming ──────────────────────────────────────────────────────
    VIDEO_STREAMING_ENABLED: bool = True
    # STUN/TURN servers for WebRTC ICE negotiation
    STUN_SERVERS: str = "stun:stun.l.google.com:19302"
    TURN_SERVER_URL: str = ""
    TURN_USERNAME: str = ""
    TURN_CREDENTIAL: str = ""

    # ── CORS ─────────────────────────────────────────────────────────────────
    CORS_ORIGINS: str = (
        "http://localhost:3000,"
        "http://127.0.0.1:3000,"
        "http://34.100.230.121:3000,"
        "https://dev.hirebuddha.com,"
        "https://app.hirebuddha.com,"
        "https://gateway.hirebuddha.com"
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def stun_servers_list(self) -> list[str]:
        return [s.strip() for s in self.STUN_SERVERS.split(",") if s.strip()]


settings = UnifiedGatewaySettings()
