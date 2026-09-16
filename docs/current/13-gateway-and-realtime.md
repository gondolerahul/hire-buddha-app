# 13. The Unified Gateway & Real-Time Transport

> **What this document covers:** the separate gateway process on port 8001 — how it routes REST, webhooks, internal events, WebSocket audio, WebRTC video and Server-Sent Events, and how each transport behaves end to end.
> **Who should read it:** anyone touching an endpoint the browser or an external system talks to, anyone debugging "the stream died", and anyone adding a new webhook provider or real-time channel.
> **Prerequisites:** [02 — System architecture](02-system-architecture.md) for the process topology, [04 — Auth, RBAC & tenancy](04-auth-rbac-tenancy.md) for how the *backend* authenticates. Voice semantics (what happens to the audio once it arrives) live in [12 — Voice & telephony](12-voice-and-telephony.md).

---

## Table of contents

1. [The 60-second version](#1-the-60-second-version)
2. [The gateway FastAPI app](#2-the-gateway-fastapi-app)
3. [Configuration](#3-configuration)
4. [Auth middleware — who gets in](#4-auth-middleware--who-gets-in)
5. [The REST passthrough proxy](#5-the-rest-passthrough-proxy)
6. [The dispatcher](#6-the-dispatcher)
7. [The event bus and internal events](#7-the-event-bus-and-internal-events)
8. [Inbound webhooks](#8-inbound-webhooks)
9. [Browser audio over WebSocket](#9-browser-audio-over-websocket)
10. [Video and WebRTC](#10-video-and-webrtc)
11. [Server-Sent Events for execution traces](#11-server-sent-events-for-execution-traces)
12. [Transport comparison](#12-transport-comparison)
13. [Reverse proxy — Apache](#13-reverse-proxy--apache)
14. [Scaling and state](#14-scaling-and-state)
15. [Operational runbook](#15-operational-runbook)

---

## 1. The 60-second version

There are two FastAPI processes. The **backend** ([`src/main.py`](../../backend/src/main.py)) on
port 8000 holds all the business logic, the database session, auth, RBAC and
every `/api/v1/*` route. The **gateway** ([`src/gateway/app.py`](../../backend/src/gateway/app.py))
on port 8001 sits in front of it and is the only thing the outside world talks to.

Why split them at all? Three reasons that show up in the code:

1. **Long-lived connections do not mix well with a request/response app.** Twilio
   media streams, browser microphone streams and WebRTC signalling hold a socket
   open for the length of a phone call. Keeping them in a separate process means a
   backend deploy or a slow database query does not drop live calls.
2. **One public surface, many protocols.** External systems (Twilio, HubSpot,
   GitHub, Mailgun) need a stable public hostname. Everything lands on
   `gateway.hirebuddha.com` and the gateway decides whether it is a proxied REST
   call, a webhook, an internal event or a stream.
3. **Rate limiting and CORS at the edge.** The gateway owns the shared Redis-backed
   rate limiter so limits are enforced before a request costs the backend anything.

The gateway's own docstring calls these "the 5 interfaces":

```python
# backend/src/gateway/app.py
"""
Unified AI Gateway — Main Application.
...
  1. /api/v1/*            Domain REST API (proxied to backend:8000)
  2. /webhook/inbound     Unified Webhook Receiver (all external systems)
  3. /internal/event      Internal Event Endpoint (microservices)
  4. /stream/audio        Bidirectional Audio Streaming (Twilio/Tata/Exotel/Web)
  5. /stream/video        Bidirectional Video Streaming (WebRTC SFU)
"""
```

### Master diagram — everything that flows through the gateway

```mermaid
graph TB
    subgraph Outside["Outside world"]
        BR["Browser - React app"]
        TEL["Telephony - Twilio, Tata, Exotel"]
        EXT["External SaaS - CRM, email, GitHub, social"]
        SVC["Internal microservices, cron"]
    end

    subgraph Edge["Apache 443 - TLS termination"]
        AP["mod_proxy + mod_proxy_wstunnel"]
    end

    subgraph GW["Unified Gateway - uvicorn 8001"]
        MW["GatewayAuthMiddleware -> CORS"]
        R1["Catch-all REST proxy"]
        R2["POST /webhook/inbound"]
        R3["POST /internal/event"]
        R4["WS /stream/audio"]
        R5["WS /stream/video"]
        R6["WS /stream/twilio and /stream/tata"]
        BUS["InMemoryEventBus - asyncio.Queue"]
        DISP["CentralDispatcher"]
    end

    subgraph Back["Backend - uvicorn 8000"]
        API["FastAPI /api/v1 routers"]
        SSE["GET /ai/executions/id/stream"]
    end

    subgraph State["Shared state"]
        RD["Redis - pub/sub, arq queue, rate limits"]
        PG["PostgreSQL"]
    end

    WK["Arq worker - AgentLoop"]

    BR --> AP
    TEL --> AP
    EXT --> AP
    SVC --> AP
    AP --> MW
    MW --> R1
    MW --> R2
    MW --> R3
    AP -.websocket upgrade.-> R4
    AP -.websocket upgrade.-> R5
    AP -.websocket upgrade.-> R6

    R1 --> API
    R1 -.SSE relay.-> SSE
    R2 --> BUS
    R3 --> BUS
    BUS --> DISP
    DISP -->|arq enqueue| RD
    RD --> WK
    WK --> PG
    WK -->|publish execution:run_id| RD
    RD --> SSE
    SSE -.text/event-stream.-> R1
    API --> PG
    R4 --> PG
    R5 --> PG
```

Read that diagram twice. The single most important thing it shows is that the
gateway is a **fan-in point, not a brain**. Business logic is elsewhere. The
gateway normalises, authenticates lightly, and hands off.

---

## 2. The gateway FastAPI app

### 2.1 Two apps named "gateway"

There are two gateway modules and only one of them runs:

| Module | Lines | Status |
|--------|-------|--------|
| [`src/gateway/main.py`](../../backend/src/gateway/main.py) | 73 | **Legacy.** The original thin HTTP proxy. Nothing starts it. Kept for reference. |
| [`src/gateway/app.py`](../../backend/src/gateway/app.py) | 436 | **Live.** The unified multi-protocol gateway. This is what `uvicorn src.gateway.app:app` serves. |

Both are launched the same way in principle, but only `app.py` appears in
[`start_services.sh:108`](../../start_services.sh:108) and
[`backend/docker-compose.yml`](../../backend/docker-compose.yml):

```bash
# start_services.sh:108
nohup "$BACKEND_DIR/.venv/bin/python" -m uvicorn src.gateway.app:app \
    --host 0.0.0.0 --port 8001 --reload > "$LOG_DIR/unified_gateway.log" 2>&1 &
```

If you find yourself editing `main.py`, stop — you are editing dead code.

### 2.2 App assembly, in order

The order below is exactly the order the statements appear in `app.py`, and the
order matters for middleware.

```python
# backend/src/gateway/app.py:80-134
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMIT],
    storage_uri=settings.REDIS_URL,
)

app = FastAPI(
    title="HireBuddha Unified AI Gateway",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins_list, ...)
app.add_middleware(GatewayAuthMiddleware)

app.include_router(webhook_router)         # Interface 2
app.include_router(internal_event_router)  # Interface 3
app.include_router(audio_router)           # Interface 4
app.include_router(video_router)           # Interface 5
```

### 2.3 Middleware stack — the ordering trap

Starlette's `add_middleware` **prepends**. The middleware added *last* is the
*outermost* layer and runs *first*. So the effective request path is:

```mermaid
flowchart LR
    REQ["Incoming HTTP request"] --> AUTH["GatewayAuthMiddleware - added last, runs first"]
    AUTH --> CORS["CORSMiddleware"]
    CORS --> RL["slowapi limiter - decorator only, proxy route"]
    RL --> ROUTE["Matched route handler"]
    ROUTE --> RESP["Response"]
    AUTH -->|401 short-circuit| RESP401["JSONResponse 401 - no CORS headers"]
```

That short-circuit branch is a real trap: when `GatewayAuthMiddleware` rejects a
request to `/internal/event`, it returns a `JSONResponse` *before*
`CORSMiddleware` ever sees it, so the 401 carries no `Access-Control-Allow-Origin`
header. A browser calling that endpoint sees an opaque CORS failure rather than a
clean 401. Server-to-server callers (the actual intended users of that endpoint)
are unaffected.

WebSocket connections skip the stack entirely — see [section 4.3](#43-the-websocket-blind-spot).

### 2.4 Startup and shutdown lifecycle

```python
# backend/src/gateway/app.py:54-73
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Unified Gateway starting up...")
    bus = get_event_bus()
    logger.info(f"[Startup] Event bus ready (type=memory, maxsize={bus._maxsize})")
    dispatcher = get_dispatcher()
    await dispatcher.start()
    logger.info("[Startup] Central AI Dispatcher ready")
    yield  # App is running
    logger.info("Unified Gateway shutting down...")
    await dispatcher.stop()
    logger.info("[Shutdown] Dispatcher stopped")
```

```mermaid
sequenceDiagram
    participant U as uvicorn
    participant A as gateway app
    participant B as InMemoryEventBus
    participant D as CentralDispatcher
    participant R as Redis

    U->>A: ASGI lifespan startup
    A->>B: get_event_bus - lazily construct singleton
    B-->>A: bus with maxsize from EVENT_BUS_MAXSIZE
    A->>D: get_dispatcher then start
    D->>R: aioredis.from_url REDIS_URL
    alt Redis reachable
        R-->>D: connection
        D->>D: log "Redis connection established"
    else Redis down
        D->>D: log warning, session cache disabled, keep going
    end
    D->>B: subscribe and spawn dispatcher-event-consumer task
    A-->>U: ready, serving traffic

    Note over U,R: ... requests served ...

    U->>A: ASGI lifespan shutdown
    A->>D: stop
    D->>D: cancel consumer task
    D->>R: aclose
```

Two details worth knowing:

- **Redis is optional at startup.** [`dispatcher.py:79`](../../backend/src/gateway/dispatcher.py:79)
  swallows the connection error and logs a warning. The gateway boots without
  Redis; you only discover the problem when the agent cache and arq enqueue fail
  later.
- **`@app.on_event("shutdown")` is silently ignored.** [`app.py:330`](../../backend/src/gateway/app.py:330)
  registers `close_proxy_client` with the deprecated decorator, but because a
  custom `lifespan` was passed to `FastAPI(...)`, Starlette 0.36 never calls
  `Router.shutdown()`. The proxy `httpx.AsyncClient` is therefore never closed.
  Harmless at process exit, but do not add cleanup logic there expecting it to run.

### 2.5 Route table

Routes are matched in registration order, and the catch-all proxy is registered
**last** on purpose.

| Method | Path | Handler | Purpose |
|--------|------|---------|---------|
| `GET` | `/` | [`root`](../../backend/src/gateway/app.py:151) | Service banner listing the five interfaces. |
| `GET` | `/health` | [`health_check`](../../backend/src/gateway/app.py:166) | Liveness + event bus stats. |
| `GET` | `/metrics/gateway` | [`gateway_metrics`](../../backend/src/gateway/app.py:179) | Event bus stats + active video sessions. |
| `GET` | `/docs`, `/redoc`, `/openapi.json` | FastAPI built-ins | Gateway's own OpenAPI (not the backend's). |
| `POST` | `/webhook/inbound` | [`unified_webhook_inbound`](../../backend/src/gateway/webhook_inbound.py:522) | Interface 2. |
| `POST` | `/internal/event` | [`unified_internal_event`](../../backend/src/gateway/internal_event.py:95) | Interface 3. |
| `WS` | `/stream/audio` | [`unified_audio_streaming`](../../backend/src/gateway/audio_gateway.py:55) | Interface 4. |
| `WS` | `/stream/video` | [`unified_video_streaming`](../../backend/src/gateway/video_gateway.py:348) | Interface 5. |
| `WS` | `/webhooks/voice/tata/incoming` | [`tata_websocket_incoming`](../../backend/src/gateway/app.py:200) | Tata Tele direct media stream. |
| `WS` | `/stream/twilio/{session_id}` | [`twilio_stream_websocket`](../../backend/src/gateway/app.py:237) | Back-compat Twilio media stream. |
| `WS` | `/stream/tata/{session_id}` | [`tata_stream_websocket`](../../backend/src/gateway/app.py:273) | Back-compat Tata media stream. |
| `*` | `/{path:path}` | [`proxy_to_backend`](../../backend/src/gateway/app.py:342) | Interface 1. Everything else → backend:8000. |

The `/health` response is worth memorising because it is the first thing you curl:

```json
{
  "status": "healthy",
  "service": "unified-gateway",
  "version": "2.0.0",
  "interfaces": ["rest", "webhook", "internal_event", "audio", "video"],
  "event_bus": {"consumer_count": 1, "total_published": 12, "total_dropped": 0}
}
```

`consumer_count` should be `1` — the dispatcher. If it is `0`, the dispatcher's
consumer task died and every webhook you receive will be dropped.

---

## 3. Configuration

### 3.1 `config.py` versus `gateway_config.py`

| File | Class | Used by | Notes |
|------|-------|---------|-------|
| [`config.py`](../../backend/src/gateway/config.py) | `GatewaySettings` | Only the legacy [`main.py`](../../backend/src/gateway/main.py) | 3 settings. Dead alongside `main.py`. |
| [`gateway_config.py`](../../backend/src/gateway/gateway_config.py) | `UnifiedGatewaySettings` | The live app and every gateway module | 17 settings. **This is the one you edit.** |

Both are pydantic-settings classes reading from the process environment and
`backend/.env`, with `extra="ignore"` so unrelated backend variables do not
break startup.

### 3.2 Every setting in `UnifiedGatewaySettings`

| Setting | Default | Purpose |
|---------|---------|---------|
| `BACKEND_URL` | `http://localhost:8000` | Base URL of the main FastAPI app. The REST proxy's `httpx` base_url. In Docker this becomes `http://app:8000`. |
| `REDIS_URL` | `redis://localhost:6379` | Three jobs: slowapi rate-limit storage, the dispatcher's agent cache, and the arq queue DSN. |
| `RATE_LIMIT` | `200/minute` | slowapi limit string. Applied per client IP on the REST proxy route only. |
| `GATEWAY_PORT` | `8001` | Only read by the `__main__` block at [`app.py:433`](../../backend/src/gateway/app.py:433). uvicorn is normally given `--port` explicitly. |
| `STREAMING_HOST` | `localhost:8001` | Public host used to build `wss://` URLs handed to telephony providers. Set to `gateway.hirebuddha.com` in production. |
| `STREAMING_PROTOCOL` | `wss` | Scheme for those URLs. |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/hirebuddha` | Needed because the audio/video handlers open real DB sessions in-process. |
| `INTERNAL_TOKEN` | `change-me-in-production` | Shared secret for `X-Internal-Token` on `/internal/event`. |
| `JWT_SECRET` | `change-me-in-production` | Used to *decode* (not enforce) bearer tokens for logging. Must equal the backend's `SECRET_KEY` for decoding to succeed. |
| `JWT_ALGORITHM` | `HS256` | Matches the backend. |
| `EVENT_BUS_TYPE` | `memory` | Declared but **never read anywhere**. `get_event_bus()` always builds `InMemoryEventBus`. Kafka is aspirational. |
| `EVENT_BUS_MAXSIZE` | `1000` | Per-consumer `asyncio.Queue` bound. Beyond it, events are dropped with a warning. |
| `VIDEO_STREAMING_ENABLED` | `True` | Kill switch for `/stream/video` media (signalling still answers). |
| `STUN_SERVERS` | `stun:stun.l.google.com:19302` | Comma-separated; exposed as `stun_servers_list`. |
| `TURN_SERVER_URL` | `""` | Appended to the ICE server list when set. |
| `TURN_USERNAME` | `""` | Declared but **never used** — `RTCIceServer` is built with `urls` only. |
| `TURN_CREDENTIAL` | `""` | Same: declared, never used. Authenticated TURN will not work as written. |
| `CORS_ORIGINS` | 6 origins incl. `localhost:3000`, `dev/app/gateway.hirebuddha.com` | Comma-separated; exposed as `cors_origins_list`. |

Two derived properties do the splitting:

```python
# backend/src/gateway/gateway_config.py:64-70
@property
def cors_origins_list(self) -> list[str]:
    return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

@property
def stun_servers_list(self) -> list[str]:
    return [s.strip() for s in self.STUN_SERVERS.split(",") if s.strip()]
```

### 3.3 How the gateway learns about its neighbours

```mermaid
flowchart TD
    ENV["Process env + backend/.env"] --> S["UnifiedGatewaySettings"]
    S -->|BACKEND_URL| P["httpx.AsyncClient base_url -> backend 8000"]
    S -->|REDIS_URL| RL["slowapi storage"]
    S -->|REDIS_URL| AC["Dispatcher agent cache - gateway:agent:client:channel"]
    S -->|REDIS_URL| ARQ["arq RedisSettings.from_dsn -> job queue"]
    S -->|DATABASE_URL| DB["Audio and video handlers open AsyncSessionLocal"]
    S -->|INTERNAL_TOKEN| AUTH["GatewayAuthMiddleware internal check"]
    S -->|JWT_SECRET| DEC["Best-effort JWT decode for logging"]
    S -->|CORS_ORIGINS| CORS["CORSMiddleware allow_origins"]
    S -->|STUN and TURN| ICE["RTCConfiguration iceServers"]
```

Notice what is **not** there: there is no service registry and no health probe of
the backend. The gateway discovers the backend purely through `BACKEND_URL` and
finds out it is down only when a proxied request raises `httpx.RequestError`,
at which point it returns `503`.

Note also that the gateway reaches the *voice* subsystem by importing it directly
([`src.voice.websocket_handler`](../../backend/src/voice/websocket_handler.py),
[`src.voice.session_manager`](../../backend/src/voice/session_manager.py)) rather
than over the network. The gateway process therefore needs the full backend
codebase and database access, not just a URL. See [12 — Voice & telephony](12-voice-and-telephony.md).

---

## 4. Auth middleware — who gets in

[`auth_middleware.py`](../../backend/src/gateway/auth_middleware.py) is 148 lines
and does much less than the name suggests. Its own docstring is honest about it:

```python
# backend/src/gateway/auth_middleware.py:66-69
"""
Missing / invalid credentials are NOT blocked here for REST / Webhook paths —
the internal handlers enforce auth. Only /internal/event is blocked at middleware.
"""
```

### 4.1 The rules, exactly

| Path prefix | Credential checked | Blocked on failure? | `TenantContext` populated |
|-------------|--------------------|---------------------|---------------------------|
| `/internal/event` | `X-Internal-Token` header must equal `settings.INTERNAL_TOKEN` (exact string compare) | **Yes — 401** | `is_internal=True`, `source_channel="internal"` |
| `/webhook/inbound` | None. `?client_id=` query param is read as-is | No | `company_id=<client_id>`, `is_webhook=True`, `source_channel="webhook"` |
| `/stream/audio`, `/stream/video` | None. `?client_id=` query param read | No | `company_id`, `source_channel="audio"`/`"video"` — **but see 4.3** |
| everything else (`/api/v1/*`, `/health`, `/webhooks/voice/*`, …) | `Authorization: Bearer <jwt>` decoded best-effort, or `X-API-Key` recorded | No | `user_id` and `company_id` from JWT claims if decode succeeds; `source_channel="rest"` |

`TenantContext` is a plain dataclass attached to `request.state.tenant`:

```mermaid
classDiagram
    class TenantContext {
        +str company_id
        +str user_id
        +bool is_internal
        +bool is_webhook
        +str source_channel
        +str raw_token
    }
```

### 4.2 The decision flow

```mermaid
flowchart TD
    START(["Request arrives"]) --> P{"path startswith"}
    P -->|/internal/event| I1{"X-Internal-Token == INTERNAL_TOKEN"}
    I1 -->|no| R401["401 JSONResponse - Unauthorized"]
    I1 -->|yes| ICTX["tenant.is_internal = true"]

    P -->|/webhook/inbound| W1["tenant.company_id = query client_id"]
    W1 --> WCTX["tenant.is_webhook = true - no rejection possible"]

    P -->|/stream/audio or /stream/video| S1["tenant.company_id = query client_id"]
    S1 --> SCTX["source_channel = audio or video"]

    P -->|anything else| A1{"Authorization header"}
    A1 -->|Bearer token| A2["_decode_jwt with JWT_SECRET"]
    A2 -->|decoded| A3["user_id = sub, company_id = claim"]
    A2 -->|failed| A4["leave context empty - still allowed"]
    A1 -->|X-API-Key| A5["record raw_token only"]
    A1 -->|neither| A4

    ICTX --> NEXT["call_next -> route handler"]
    WCTX --> NEXT
    SCTX --> NEXT
    A3 --> NEXT
    A4 --> NEXT
    A5 --> NEXT
```

The only hard gate is the internal token. Everything else is *observability*:
the middleware is extracting a tenant id so logs and future rate limits can be
keyed on it. Real authentication for `/api/v1/*` happens after the proxy hop, in
the backend's own dependencies — see [04 — Auth, RBAC & tenancy](04-auth-rbac-tenancy.md).

Two FastAPI dependencies re-expose the context to route handlers:

| Dependency | Behaviour |
|------------|-----------|
| [`require_internal`](../../backend/src/gateway/auth_middleware.py:135) | Raises 401 unless `tenant.is_internal`. Used by `/internal/event`. Belt-and-braces on top of the middleware. |
| [`get_tenant`](../../backend/src/gateway/auth_middleware.py:146) | Returns the context or an empty one. Currently unused by any route. |

### 4.3 The WebSocket blind spot

`GatewayAuthMiddleware` extends `BaseHTTPMiddleware`, and Starlette's
`BaseHTTPMiddleware.__call__` passes any scope whose type is not `"http"`
straight through to the inner app. WebSocket handshakes have
`scope["type"] == "websocket"`.

**Therefore the `/stream/audio` and `/stream/video` branch of the middleware
never executes for an actual WebSocket connection.** It would only fire if
something made a plain HTTP request to those paths.

The stream handlers do not compensate. [`audio_gateway.py:98`](../../backend/src/gateway/audio_gateway.py:98)
reads `token = handshake.get("token", "")` from the handshake JSON and then
**never uses the variable**. [`video_gateway.py`](../../backend/src/gateway/video_gateway.py:391)
does not even read it. The only gate on opening an audio or video session is
that `client_id` resolves to some non-archived entity for that company:

```mermaid
flowchart LR
    C["Client opens WS with client_id and token"] --> H["Handshake parsed"]
    H --> T["token read into a variable"]
    T -.never validated.-> X["ignored"]
    H --> RA["dispatcher.resolve_agent_for_client client_id"]
    RA -->|agent found| OK["Session created"]
    RA -->|none| CLOSE["close 1008 no agent"]
```

Anyone who knows a company UUID can open a streaming session. Treat this as a
known gap, not a design; do not build on the assumption that the token is checked.
CORS also does not apply to WebSockets, so browser origin is not restricted either.

---

## 5. The REST passthrough proxy

Interface 1 is a catch-all reverse proxy. It is deliberately the last route
registered so that every specific gateway route wins first.

### 5.1 Request transformation

```python
# backend/src/gateway/app.py:342-357
async def proxy_to_backend(request: Request, path: str):
    url = f"/{path}"
    if request.query_params:
        url += f"?{request.query_params}"

    headers = dict(request.headers)
    headers.pop("host", None)            # let httpx set Host for backend
    headers.pop("content-length", None)  # let httpx recompute
    content = await request.body()
```

| Step | What happens |
|------|--------------|
| Path | Rebuilt verbatim as `/{path}`; the gateway strips nothing. `/api/v1/x` reaches the backend as `/api/v1/x`. |
| Query string | Re-appended verbatim, including `?token=…` used by SSE. |
| Headers | All forwarded except `host` and `content-length`. `Authorization`, cookies and `X-API-Key` pass straight through — the backend does the real auth. |
| Body | Read fully into memory (`await request.body()`), then re-sent. Large uploads are buffered twice. |
| Redirects | `follow_redirects=True` on the client, so 3xx from the backend is chased server-side. |
| Timeout | 60 s read, 10 s connect (`httpx.Timeout(60.0, connect=10.0)`) — except for SSE, see below. |
| Failure | `httpx.RequestError` → `503` with `{"error": "Backend unavailable", "detail": "..."}`. |

The client is created lazily so ASGI tests can import the app without opening
sockets:

```python
# backend/src/gateway/app.py:317-327
def _get_proxy_client() -> httpx.AsyncClient:
    global _proxy_client
    if _proxy_client is None:
        _proxy_client = httpx.AsyncClient(
            base_url=settings.BACKEND_URL,
            timeout=httpx.Timeout(60.0, connect=10.0),
            follow_redirects=True,
        )
    return _proxy_client
```

### 5.2 Sequence — a normal proxied REST call

```mermaid
sequenceDiagram
    participant B as Browser
    participant AP as Apache 443
    participant GW as Gateway 8001
    participant MW as GatewayAuthMiddleware
    participant HX as httpx AsyncClient
    participant BE as Backend 8000
    participant PG as PostgreSQL

    B->>AP: GET /api/v1/ai/entities with Bearer JWT
    AP->>GW: proxied HTTP, ProxyPreserveHost On
    GW->>MW: dispatch
    MW->>MW: decode JWT best-effort, set request.state.tenant
    MW->>GW: call_next
    GW->>GW: slowapi limiter check against Redis
    Note over GW: no specific route matches -> catch-all
    GW->>HX: request GET /api/v1/ai/entities, headers minus host
    HX->>BE: HTTP/1.1
    BE->>BE: get_current_user, RBAC, tenant scoping
    BE->>PG: SELECT ... WHERE company_id = ...
    PG-->>BE: rows
    BE-->>HX: 200 application/json
    HX-->>GW: Response object
    GW-->>AP: Response content, status, headers copied verbatim
    AP-->>B: 200 with CORS headers
```

### 5.3 The SSE special case

A normal `proxy.request()` buffers the whole response. An SSE stream never
completes, so buffering it means the read timeout fires after 60 s and the
browser gets a 503. The proxy detects SSE and switches to a live relay:

```python
# backend/src/gateway/app.py:364-405
wants_sse = (
    path.endswith("/stream")
    or "text/event-stream" in headers.get("accept", "")
)
if wants_sse:
    req = proxy.build_request(
        method=request.method, url=url, headers=headers, content=content,
        timeout=httpx.Timeout(None, connect=10.0),  # no read timeout for SSE
    )
    upstream = await proxy.send(req, stream=True)
    ...
    return StreamingResponse(
        _relay_sse(), status_code=200, media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering (nginx/apache)
        },
    )
```

```mermaid
flowchart TD
    REQ["Proxied request"] --> D{"path ends with /stream OR Accept contains text/event-stream"}
    D -->|no| BUF["proxy.request - buffered - 60s read timeout"]
    BUF --> RESP["Response with upstream body, status, headers"]
    D -->|yes| BR["build_request with timeout read=None"]
    BR --> SEND["proxy.send stream=True"]
    SEND --> ST{"upstream status == 200"}
    ST -->|no| PASS["read body, close, return upstream status verbatim"]
    ST -->|yes| RELAY["StreamingResponse over aiter_raw"]
    RELAY --> HDR["adds Cache-Control no-cache, Connection keep-alive, X-Accel-Buffering no"]
```

Two caveats:

- The detection is a heuristic. Any future backend route ending in `/stream`
  that is *not* SSE will also be relayed unbuffered.
- `X-Accel-Buffering: no` is an **nginx** convention. Apache ignores it. The
  reason SSE works behind Apache anyway is discussed in [section 13](#13-reverse-proxy--apache).

---

## 6. The dispatcher

[`dispatcher.py`](../../backend/src/gateway/dispatcher.py) (425 lines) is the
"Central AI Dispatcher". Despite the name it dispatches only two of the five
interfaces — webhook and internal events. REST is proxied; audio and video are
handled inline by their WebSocket routes.

### 6.1 What it actually routes

| Envelope `channel` | Dispatch mode | What happens |
|--------------------|---------------|--------------|
| `webhook` | `async_job` | `_dispatch_async` → arq `enqueue_job("process_gateway_event", envelope)` |
| `internal` | `async_job` | same as webhook |
| `audio` | `streaming` | Returns immediately; the WS handler owns the session. Dispatcher only resolved the agent. |
| `video` | `streaming` | same as audio |
| anything else (incl. `rest`) | `async_job` | Returns `accepted=True` with no side effect — a no-op branch. |
| *missing `client_id`* | `rejected` | `DispatchResult(accepted=False, error="no_client_id")`, event dropped with a warning. |

```mermaid
flowchart TD
    E["EventEnvelope from bus"] --> C{"client_id present"}
    C -->|no| REJ["DispatchResult rejected - no_client_id"]
    C -->|yes| CH{"channel"}
    CH -->|webhook or internal| ASY["_dispatch_async"]
    CH -->|audio or video| STR["DispatchResult mode=streaming"]
    CH -->|other| NOP["DispatchResult mode=async_job - no side effect"]

    ASY --> ARQ{"arq pool created and job enqueued"}
    ARQ -->|success| JOB["job_id returned - worker picks it up"]
    ARQ -->|exception| FB["_execute_in_process fire and forget"]
    FB --> LEAD{"event_type is lead.created or lead_created"}
    LEAD -->|yes| LQ["LeadQueueService.enqueue_lead"]
    LEAD -->|no| RUN["Create ExecutionRun then AgentLoop.run in this process"]
```

### 6.2 The arq handoff and its fallback

The happy path opens a **new** arq pool per event, enqueues, and closes it:

```python
# backend/src/gateway/dispatcher.py:171-182
redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
arq_pool = await create_pool(redis_settings)
job = await arq_pool.enqueue_job("process_gateway_event", envelope.to_dict())
await arq_pool.aclose()
job_id = job.job_id if job else "queued"
```

Creating a pool per event is wasteful but simple. If *anything* in that block
throws — Redis down, arq missing — the dispatcher falls back to running the work
**inside the gateway process**:

```python
# backend/src/gateway/dispatcher.py:184-190
except Exception as exc:
    logger.warning(
        f"[Dispatcher] arq enqueue failed ({exc}); falling back to in-process dispatch"
    )
    asyncio.create_task(self._execute_in_process(envelope))
    return DispatchResult(accepted=True, mode="async_job", job_id="in_process")
```

That fallback runs a full `AgentLoop` — LLM calls, tool calls, database writes —
on the gateway's event loop. It is a safety valve, not a mode you want in
production: a busy fallback will starve live audio sessions sharing the same loop.
Grep for `job_id="in_process"` / the warning line when the gateway feels slow.

The worker-side job is
[`process_gateway_event`](../../backend/src/ai/core/arq_jobs.py:163), registered in
[`src/ai/worker.py`](../../backend/src/ai/worker.py). It re-does entity resolution,
special-cases `sheet.row_inserted` into the campaign pipeline, and otherwise
creates an `ExecutionRun` and runs the `AgentLoop`. See
[06 — Execution pipeline](06-execution-pipeline.md).

### 6.3 Agent resolution and its cache

Audio and video handshakes call `resolve_agent_for_client`. It is Redis-cached
for 5 minutes under `gateway:agent:{client_id}:{channel}`:

```mermaid
sequenceDiagram
    participant WS as Audio or video handler
    participant D as CentralDispatcher
    participant R as Redis
    participant PG as PostgreSQL

    WS->>D: resolve_agent_for_client client_id, channel
    D->>R: GET gateway:agent:client:channel
    alt cache hit
        R-->>D: JSON agent_info
        D-->>WS: agent_info
    else miss
        D->>PG: SELECT HierarchicalEntity WHERE company_id AND status != ARCHIVED LIMIT 1
        PG-->>D: entity or none
        alt none
            D-->>WS: None -> handler closes WS 1008
        else found
            D->>R: SETEX gateway:agent:... 300 json
            D-->>WS: agent_id, company_id, name, channel
        end
    end
```

The `LIMIT 1` with no `ORDER BY` is important: **which** agent answers a call for
a multi-agent tenant is whatever Postgres returns first. Same pattern appears in
`_execute_in_process` and in `process_gateway_event`. Route deliberately by
passing `entity_id` in the webhook payload or query string.

### 6.4 Dispatcher lifecycle

```mermaid
stateDiagram-v2
    [*] --> Created: get_dispatcher lazily constructs singleton
    Created --> Starting: start
    Starting --> Running: Redis connected, consumer task spawned
    Starting --> RunningNoRedis: Redis unavailable, warning logged
    Running --> Consuming: async for envelope in subscription
    RunningNoRedis --> Consuming
    Consuming --> Consuming: dispatch each envelope, exceptions logged not raised
    Consuming --> Stopping: stop
    Stopping --> [*]: task cancelled, redis closed
```

---

## 7. The event bus and internal events

### 7.1 It is in-process, not Redis

This is the single most misread part of the gateway. The docstring for
[`event_bus.py`](../../backend/src/gateway/event_bus.py) says "Async Event Bus —
In-process implementation using `asyncio.Queue`", and that is literally all it is.
`EVENT_BUS_TYPE` exists in config but is never read; `get_event_bus()`
unconditionally returns an `InMemoryEventBus`.

| Property | Value |
|----------|-------|
| Transport | `asyncio.Queue`, one queue per subscriber, inside one Python process |
| Durability | None. A gateway restart loses everything queued. |
| Fan-out | Every subscriber gets every event (`put_nowait` in a loop) |
| Backpressure | `maxsize=EVENT_BUS_MAXSIZE` (1000). On `QueueFull` the event is **dropped**, not blocked. |
| Cross-process | **No.** Redis pub/sub is used elsewhere in the platform, but not by this bus. |
| Consumers today | Exactly one: `CentralDispatcher._consume_event_bus` |

Cross-process delivery happens *after* the bus, via the arq job queue in Redis.

```mermaid
flowchart TB
    subgraph GWP["Gateway process - single asyncio loop"]
        WH["POST /webhook/inbound handler"] -->|BackgroundTasks| PUB1["_publish_to_bus"]
        IE["POST /internal/event handler"] -->|BackgroundTasks| PUB2["_publish_event"]
        HLP["emit_internal_event helper - direct call"] --> PUB3["bus.publish"]
        PUB1 --> BUS["InMemoryEventBus"]
        PUB2 --> BUS
        PUB3 --> BUS
        BUS -->|put_nowait fan-out| Q1["asyncio.Queue maxsize 1000"]
        Q1 --> DISP["CentralDispatcher consumer task"]
    end

    DISP -->|arq enqueue_job| RQ[("Redis - arq queue")]
    RQ --> WORK["Arq worker process - process_gateway_event"]
    WORK --> DB[("PostgreSQL")]
    DISP -.fallback when arq fails.-> INPROC["AgentLoop inside gateway process"]
```

The dropped-event counter is exposed on `/health` and `/metrics/gateway`:

```python
# backend/src/gateway/event_bus.py:130-136
@property
def stats(self) -> dict:
    return {
        "consumer_count": len(self._consumers),
        "total_published": self._total_published,
        "total_dropped": self._total_dropped,
    }
```

A rising `total_dropped` with `consumer_count: 0` means the dispatcher consumer
is gone. A rising `total_dropped` with `consumer_count: 1` means the dispatcher
is slower than the inbound rate.

### 7.2 The envelope

Everything on the bus is one shape,
[`EventEnvelope`](../../backend/src/gateway/event_bus.py:37):

```mermaid
classDiagram
    class EventEnvelope {
        +str channel
        +str source
        +str client_id
        +str event_type
        +dict raw_data
        +dict metadata
        +str id
        +str timestamp
        +to_dict() dict
        +from_dict(data) EventEnvelope
    }
```

| Field | Meaning | Example |
|-------|---------|---------|
| `channel` | Which interface produced it | `"webhook"`, `"internal"`, `"audio"`, `"video"`, `"rest"` |
| `source` | Originating system | `"email"`, `"crm"`, `"github"`, `"vector_db"`, `"cron"`, `"agent:abc123"` |
| `client_id` | Tenant / company UUID string | `"3f7c…"` |
| `event_type` | Dot-namespaced type | `"new_email"`, `"github.push"`, `"timer.daily_summary"` |
| `raw_data` | Normalised payload from the strategy | provider-specific dict |
| `metadata` | Correlation, priority, request headers | `{"correlation_id": "...", "priority": 5}` |
| `id` | Correlation id — reused as the envelope id | UUID4 string |
| `timestamp` | ISO-8601 UTC at construction | `"2026-08-13T09:12:44.101+00:00"` |

`to_dict()` / `from_dict()` exist because the envelope is JSON-serialised into
the arq job.

### 7.3 `/internal/event` — Interface 3

A typed, authenticated endpoint for other parts of the platform to push events in.

| Field | Type | Required | Constraint |
|-------|------|----------|-----------|
| `event_type` | str | yes | dot-namespaced |
| `client_id` | str | yes | company/tenant UUID |
| `source` | str | yes | e.g. `vector_db`, `cron`, `agent:<uuid>` |
| `payload` | dict | no | arbitrary JSON, default `{}` |
| `priority` | int | no | 1–10, default 5. Carried in `metadata` only — **nothing reads it** |
| `correlation_id` | str | no | echoed back; auto-UUID4 if omitted |

Well-known types are collected in
[`WellKnownEvents`](../../backend/src/gateway/internal_event.py:146):
`doc_indexed`, `timer.daily_summary`, `timer.weekly_report`, `agent.signal`,
`campaign.done`, `build.done`. These are constants only — no handler switches on
them; `process_gateway_event` treats everything except `sheet.row_inserted` the
same way.

```mermaid
sequenceDiagram
    participant SVC as Internal service
    participant MW as GatewayAuthMiddleware
    participant EP as POST /internal/event
    participant BT as Starlette BackgroundTasks
    participant BUS as InMemoryEventBus
    participant D as CentralDispatcher
    participant RQ as Redis arq queue

    SVC->>MW: POST /internal/event with X-Internal-Token
    alt token mismatch
        MW-->>SVC: 401 Unauthorized
    else token ok
        MW->>EP: tenant.is_internal = true
        EP->>EP: require_internal dependency re-checks
        EP->>EP: correlation_id = provided or uuid4
        EP->>BT: add_task _publish_event envelope
        EP-->>SVC: 202 accepted with correlation_id
        BT->>BUS: publish
        BUS->>D: queued envelope
        D->>RQ: enqueue_job process_gateway_event
    end
```

There is also a direct in-process helper,
[`emit_internal_event`](../../backend/src/gateway/internal_event.py:157), that
skips HTTP. **Nothing calls it.** Worse, if you call it from the backend or the
arq worker it will publish into *that* process's bus, which has no dispatcher
subscribed, so the event is silently counted as dropped. From outside the gateway
process, use the HTTP endpoint.

---

## 8. Inbound webhooks

Interface 2 is a single route, `POST /webhook/inbound`, with a Strategy pattern
behind it: identify the provider from headers/payload, normalise, publish.

### 8.1 The strategy registry

Order matters — the first `can_handle` that returns `True` wins, and
`GenericWebhookStrategy` must stay last.

| # | Strategy | Detected by | `source` | `event_type` produced |
|---|----------|-------------|----------|----------------------|
| 1 | `EmailWebhookStrategy` | header starts with `x-mailgun`, `x-sg-`, `x-postmark` | `email` | `new_email` |
| 2 | `CRMWebhookStrategy` | header starts with `x-hubspot`, `x-salesforce`, `x-zoho`, or `crm_event` in payload | `crm` | `subscriptionType` / `crm_event` / `crm_update` |
| 3 | `LinkedInWebhookStrategy` | `x-li-signature`, or `type` starts `linkedin.`, or `linkedin` in `source` | `linkedin` | payload `type` or `linkedin.event` |
| 4 | `GitHubWebhookStrategy` | `x-github-event` header | `github` | `github.<event name>` |
| 5 | `TwilioWebhookStrategy` | `x-twilio-signature` header | `twilio` | `twilio.<EventType>` |
| 6 | `InstagramWebhookStrategy` | payload `object == "instagram"` | `instagram` | `instagram.webhook` |
| 7 | `FacebookWebhookStrategy` | `x-hub-signature-256`, or payload `object` in page/instagram/permissions | `facebook` | `facebook.<object>` |
| 8 | `TwitterWebhookStrategy` | `x-twitter-webhooks-signature`, or `for_user_id` in payload | `twitter` | `twitter.<*_events key>` |
| 9 | `TikTokWebhookStrategy` | `x-tiktok-signature` header | `tiktok` | `tiktok.<event>` |
| 10 | `YouTubeWebhookStrategy` | `atom+xml` content-type, `youtube.com` in `link`, `pubsubhubbub` in `x-hub-signature`, or `hub.topic` starting with the YouTube URL | `youtube` | `youtube.video.published` |
| 11 | `PinterestWebhookStrategy` | `x-pinterest-signature`, payload `source == "pinterest"`, or `pinterest` in user-agent | `pinterest` | `pinterest.<event>` |
| 12 | `GenericWebhookStrategy` | always `True` | `generic` | `?event_type=` or payload `type` or `generic_event` |

Instagram is deliberately placed before Facebook because both send
`X-Hub-Signature-256`; Instagram is distinguished only by `object == "instagram"`.

```mermaid
flowchart TD
    IN["POST /webhook/inbound"] --> BODY["read raw body"]
    BODY --> PARSE{"request.json succeeds"}
    PARSE -->|yes| PJ["payload = JSON"]
    PARSE -->|no| PF["payload = dict of form fields"]
    PJ --> DET["detect_strategy headers, payload"]
    PF --> DET
    DET --> LOOP["iterate WEBHOOK_STRATEGIES in order"]
    LOOP --> HIT{"can_handle true"}
    HIT -->|yes| S["use that strategy"]
    HIT -->|no, list exhausted| G["GenericWebhookStrategy"]
    S --> SIG["validate_signature - result logged, never blocks"]
    G --> SIG
    SIG --> NORM["normalize -> client_id, event_type, normalized_data"]
    NORM --> ENV["EventEnvelope channel=webhook"]
    ENV --> BG["BackgroundTasks _publish_to_bus"]
    BG --> R202["202 accepted with correlation_id, source, event_type"]
```

### 8.2 Signature verification — what is actually implemented

| Strategy | `validate_signature` override | Real HMAC check? |
|----------|------------------------------|------------------|
| Email, CRM, Twilio, Generic | none — inherits base `return True` | No |
| LinkedIn | reads `X-Li-Signature`, logs `signature validation not yet configured` | **No — TODO in code** |
| GitHub | reads `X-Hub-Signature-256`, logs the same | **No — TODO in code** |
| Facebook | reads `X-Hub-Signature-256`, logs the same | **No — TODO in code** |
| Instagram | reads `X-Hub-Signature-256`, logs the same | **No** |
| Twitter | reads `X-Twitter-Webhooks-Signature`, logs the same | **No** |
| TikTok | reads `X-TikTok-Signature`, logs the same | **No** |

And even if one returned `False`, the endpoint would not reject the request:

```python
# backend/src/gateway/webhook_inbound.py:548-551
if not strategy.validate_signature(headers, raw_body):
    logger.warning(f"[WebhookRouter] Signature validation failed for source={source}")
    # We still process — providers may retry; we log for audit
```

`hmac` and `hashlib` are imported at the top of the file and never used. **There
is no working webhook signature verification anywhere in this endpoint.**
`/webhook/inbound` is an unauthenticated, unsigned, world-writable trigger for
agent executions on any company whose UUID the caller knows. Treat that as the
top security item for this subsystem.

### 8.3 Idempotency — there is none

Each delivery generates a fresh `correlation_id = str(uuid.uuid4())`. There is no
delivery-id header check, no `SETNX` in Redis, no dedup table. A provider that
retries (all of them do) produces a second envelope, a second arq job and a
second `ExecutionRun`.

The one partial exception: CRM `lead.created` events routed through
`_enqueue_lead` go into `LeadQueueService.enqueue_lead`, whose docstring promises
deduplication at the lead-queue layer — see
[`lead_queue_service.py`](../../backend/src/ai/lead_queue_service.py). That
protects lead calls, not generic executions.

### 8.4 Sequence — a HubSpot lead webhook end to end

```mermaid
sequenceDiagram
    participant HS as HubSpot
    participant AP as Apache
    participant GW as Gateway
    participant ST as CRMWebhookStrategy
    participant BUS as Event bus
    participant D as Dispatcher
    participant RQ as Redis arq
    participant W as Arq worker

    HS->>AP: POST /webhook/inbound?client_id=UUID with X-HubSpot-Signature
    AP->>GW: forwarded
    GW->>GW: middleware sets tenant.is_webhook, company_id from query
    GW->>ST: detect_strategy matches on x-hubspot header
    ST->>ST: validate_signature -> True, base class no-op
    ST->>ST: normalize -> event_type, phone, entity_id, properties
    GW-->>HS: 202 accepted with correlation_id
    Note over GW,BUS: response already sent; BackgroundTasks now runs
    GW->>BUS: publish EventEnvelope channel=webhook source=crm
    BUS->>D: consumer receives envelope
    D->>RQ: enqueue_job process_gateway_event
    RQ->>W: worker picks up job
    W->>W: resolve entity, create ExecutionRun, run AgentLoop
```

The `202` is returned **before** the event reaches the bus, because Starlette
background tasks run after the response is flushed. A provider seeing `202` has
no guarantee the event was processed — only that it was accepted.

### 8.5 Adding a provider

1. Subclass `WebhookStrategy` in
   [`webhook_inbound.py`](../../backend/src/gateway/webhook_inbound.py).
2. Implement `can_handle`, `get_source`, `normalize`; override
   `validate_signature` if you want to be the first one that actually verifies.
3. Insert into `WEBHOOK_STRATEGIES` **before** `GenericWebhookStrategy`, and
   before any strategy whose detection your headers would also satisfy.
4. Add a detection test to
   [`tests/e2e/test_12_unified_gateway.py`](../../backend/tests/e2e/test_12_unified_gateway.py:351).

---

## 9. Browser audio over WebSocket

Interface 4 is one endpoint, `WS /stream/audio`, serving four providers. Three of
them are telephony and are covered in [12 — Voice & telephony](12-voice-and-telephony.md);
the interesting one here is `web`, the browser microphone path.

| `provider` value | Wire format | Handler |
|------------------|-------------|---------|
| `twilio` | base64 mulaw inside JSON events | [`TwilioStreamHandler`](../../backend/src/voice/websocket_handler.py) |
| `tata_tele` | Twilio-compatible | `TwilioStreamHandler` |
| `exotel` | Twilio-compatible | `TwilioStreamHandler` |
| `web` | raw PCM16 binary frames | [`WebAudioAdapter`](../../backend/src/gateway/web_audio_adapter.py) |

### 9.1 Connection and handshake

Connection URL: `wss://gateway.hirebuddha.com/stream/audio` — no path params, no
query params required (the middleware's `?client_id=` branch does not run for
WebSockets anyway).

The first frame **must** be a JSON text frame:

```json
{
  "event": "connect",
  "provider": "web",
  "client_id": "<company_uuid>",
  "token": "<ignored — see section 4.3>",
  "metadata": {
    "session_id": "<optional: resume an existing VoiceSession>",
    "direction": "inbound",
    "phone_number": "<caller number>"
  }
}
```

Server replies:

```json
{"event": "connected", "session_id": "<uuid>", "status": "ready",
 "provider": "web", "agent_id": "<uuid>"}
```

### 9.2 Message catalogue

| Direction | Frame type | Shape | Meaning |
|-----------|-----------|-------|---------|
| Client → Server | text | `{"event": "connect", ...}` | Handshake. Must be first. |
| Server → Client | text | `{"event": "connected", session_id, status, provider, agent_id}` | Session ready. |
| Server → Client | text | `{"event": "error", "code": ..., "message": ...}` | Handshake failure before close. |
| Client → Server | **binary** | raw PCM16 LE, 16 kHz mono | Microphone audio, forwarded straight to the live LLM client. |
| Server → Client | **binary** | raw PCM16 LE, 24 kHz mono per the docstring | AI TTS audio. Produced by `pcm24_to_pcm16` on the model's PCM24 output. |
| Client → Server | text | `{"event": "stop"}` | End the session; adapter sets `is_running = False`. |
| Client → Server | text | `{"event": "ping"}` | Keepalive. |
| Server → Client | text | `{"event": "pong"}` | Keepalive reply. |

Close codes used during handshake:

| Code | Reason string | Trigger |
|------|---------------|---------|
| `1003` | `Invalid handshake JSON` | first frame not parseable |
| `1003` | `First message must be {event: 'connect'}` | wrong `event` value |
| `1003` | `client_id required in handshake` | missing tenant |
| `1003` | `Unsupported provider: <p>` | not in `AUDIO_PROVIDER_ADAPTERS` |
| `1008` | `No agent found for client` | `resolve_agent_for_client` returned `None` |

Note the sample-rate wrinkle: the docstring says the browser receives 24 kHz,
but `_send_to_browser` sends the output of
[`pcm24_to_pcm16`](../../backend/src/voice/audio_processor.py), which is a bit-depth
conversion, not a resample. Verify against the actual player before trusting the
number; if playback sounds chipmunked or slowed, this is the line to check.

### 9.3 Sequence — browser microphone to AI and back

```mermaid
sequenceDiagram
    participant BR as Browser mic
    participant AP as Apache wstunnel
    participant AG as audio_gateway
    participant D as Dispatcher
    participant SM as SessionManager
    participant WA as WebAudioAdapter
    participant AI as Gemini Live or Azure Realtime
    participant PG as PostgreSQL

    BR->>AP: WS upgrade /stream/audio
    AP->>AG: ws://127.0.0.1:8001/stream/audio
    AG->>AG: accept
    BR->>AG: text connect with provider=web, client_id
    AG->>D: resolve_agent_for_client
    D-->>AG: agent_info
    AG->>SM: create_voice_session provider=web, call_sid gw_web_<id>
    SM->>PG: INSERT VoiceSession
    AG->>BR: text connected with session_id
    AG->>WA: WebAudioAdapter.handle

    WA->>AI: LiveClientFactory.create_client then connect
    par four concurrent tasks
        BR-->>WA: binary PCM16 frames
        WA-->>AI: send_audio or send_realtime_input
    and
        AI-->>WA: response.data PCM24 + transcriptions
        WA->>WA: pcm24_to_pcm16 then queue
    and
        WA-->>BR: binary PCM16 frames from queue
    and
        WA->>WA: flush transcript buffers every 0.5s after 1s silence
        WA->>PG: ConversationLogger.log_turn channel=web_audio
    end

    BR->>WA: text stop
    WA->>SM: end_voice_session
    WA->>BR: close
```

The four tasks are started with `asyncio.wait(..., return_when=FIRST_COMPLETED)`,
so the first task to finish (usually the browser receive loop hitting a
disconnect) cancels the rest. Cleanup always runs in the `finally` of `handle()`.

### 9.4 Provider routing inside the endpoint

```mermaid
flowchart TD
    HS["connect handshake validated"] --> AR{"provider in AUDIO_PROVIDER_ADAPTERS"}
    AR -->|no| ERR["send error then close 1003"]
    AR -->|yes| VS["resolve or create VoiceSession via SessionManager"]
    VS --> ACK["send connected ack"]
    ACK --> P{"provider"}
    P -->|twilio, tata_tele, exotel| TW["TwilioStreamHandler.handle"]
    P -->|web| WEB["WebAudioAdapter.handle"]
```

`AUDIO_PROVIDER_ADAPTERS` maps provider names to *string* class names
(`"twilio": "TwilioAudioAdapter"`, …). Those strings are never resolved to
classes — the dict is used purely as a membership check, and the real routing is
the `if/elif` above. The named adapter classes do not exist in the repo.

---

## 10. Video and WebRTC

Interface 5, `WS /stream/video`, is a WebRTC signalling channel:
[`video_gateway.py`](../../backend/src/gateway/video_gateway.py) (540 lines).

### 10.1 Implemented versus stubbed — read this first

| Piece | State |
|-------|-------|
| WebSocket signalling endpoint, handshake, agent resolution | Implemented |
| `webrtc_enabled` feature gate and graceful "install aiortc" message | Implemented |
| `RTCPeerConnection` creation with STUN/TURN from config | Implemented, but **TURN credentials are never passed** |
| SDP offer → answer | Implemented (`setRemoteDescription`, `createAnswer`, `setLocalDescription`) |
| Client → server ICE candidates | Implemented, via `RTCIceCandidate(...)` built from the candidate string |
| Server → client ICE candidates | Registered on a `pc.on("icecandidate")` handler. aiortc does not emit trickle-ICE events, so this almost certainly never fires. |
| Video frame sampling → vision model → `vision_context` | Implemented (5 s interval, JPEG q60, capped at 500 chars) |
| Audio track → AI live client | **Broken.** See below. |
| AI audio → client | Sent as binary WS frames, not as an RTP track back into the peer connection |
| Zoom / Teams bot | Not in this repo. The docstring documents the contract for a bot you would have to build. |
| **aiortc installed?** | **No.** `aiortc` and `av` are absent from `backend/.venv`. `AIORTC_AVAILABLE` is `False`, so every connection today takes the "WebRTC media disabled" branch. |

The audio-track bug is at [`video_gateway.py:202`](../../backend/src/gateway/video_gateway.py:202):

```python
# backend/src/gateway/video_gateway.py:201-207
# Forward WebRTC audio frames → AI
async for frame in track.recv.__self__.__class__.__mro__[0]:  # type hint workaround
    break  # This is just for type hints; actual loop below

while self.is_running:
    try:
        frame = await track.recv()
```

`track.recv.__self__.__class__.__mro__[0]` is the track's *class object*.
`async for` over a class raises `TypeError`, which is caught by the method's
outer `except Exception` and logged as "Audio track error" — so the `while` loop
underneath is never reached. If you install aiortc and wonder why video calls
have no voice, delete those two lines first.

### 10.2 Signalling protocol

| Direction | Message | Fields |
|-----------|---------|--------|
| C → S | `connect` | `provider` (`web`/`zoom`/`teams`), `client_id`, `token` (unused) |
| S → C | `connected` | `session_id`, `status`, `provider`, `agent_id`, `webrtc_enabled` |
| S → C | `info` | `message` — sent only when WebRTC is disabled, then the socket closes after 2 s |
| S → C | `error` | `code`, `message` — e.g. `no_agent`, then close `1008` |
| C → S | `offer` | `sdp`, `type` |
| S → C | `answer` | `sdp`, `type` |
| C → S | `ice_candidate` | `candidate.{candidate, sdpMid, sdpMLineIndex}` |
| S → C | `ice_candidate` | same shape (handler registered; see caveat above) |
| C → S | `stop` | ends the signalling loop |
| S → C | binary | raw AI audio bytes |

### 10.3 Sequence — a browser video session (with aiortc installed)

```mermaid
sequenceDiagram
    participant BR as Browser
    participant VG as video_gateway
    participant D as Dispatcher
    participant PC as RTCPeerConnection
    participant LLM as LLMRouter vision
    participant AI as Live audio client

    BR->>VG: WS /stream/video, then connect message
    VG->>D: resolve_agent_for_client client_id, video
    D-->>VG: agent_info
    VG->>VG: webrtc_enabled = AIORTC_AVAILABLE and VIDEO_STREAMING_ENABLED
    VG-->>BR: connected with webrtc_enabled

    alt webrtc_enabled false
        VG-->>BR: info "install aiortc" then close
    else enabled
        VG->>PC: create with iceServers from STUN_SERVERS plus TURN_SERVER_URL
        BR->>VG: offer with SDP
        VG->>PC: setRemoteDescription then createAnswer then setLocalDescription
        VG-->>BR: answer with SDP
        BR->>VG: ice_candidate messages
        VG->>PC: addIceCandidate
        PC-->>VG: on track audio
        VG->>AI: connect live client with system prompt plus VIDEO CONTEXT
        PC-->>VG: on track video
        loop every 5 seconds
            VG->>VG: frame to JPEG quality 60
            VG->>LLM: call_llm task_type vision
            LLM-->>VG: description, stored in vision_context capped 500 chars
        end
        AI-->>VG: audio response bytes
        VG-->>BR: binary frames
        BR->>VG: stop
    end
    VG->>VG: session.close, remove from _active_video_sessions
```

### 10.4 Video session state

```mermaid
stateDiagram-v2
    [*] --> Accepted: websocket.accept
    Accepted --> Handshaking: await first text frame
    Handshaking --> Rejected: not a connect event or no client_id
    Handshaking --> NoAgent: resolve_agent_for_client returns None
    Handshaking --> Disabled: aiortc missing or VIDEO_STREAMING_ENABLED false
    Handshaking --> Signalling: peer connection created and registered
    Signalling --> Media: on track fires, is_running true
    Media --> Signalling: connectionstatechange failed or closed
    Signalling --> Closing: stop message or WebSocketDisconnect
    Media --> Closing: stop message or WebSocketDisconnect
    Rejected --> [*]
    NoAgent --> [*]
    Disabled --> [*]
    Closing --> [*]: session.close and registry pop
```

`_active_video_sessions` is a module-level dict, surfaced by
[`get_active_video_sessions`](../../backend/src/gateway/video_gateway.py:529) on
`/metrics/gateway`. It is per-process — see [section 14](#14-scaling-and-state).

---

## 11. Server-Sent Events for execution traces

This is how the Execution Detail page shows an agent run unfolding live.

### 11.1 Endpoint and stream format

The producer lives on the **backend**, not the gateway:
[`GET /api/v1/ai/executions/{execution_id}/stream`](../../backend/src/ai/router.py:324).
The browser reaches it through the gateway's SSE relay path
([section 5.3](#53-the-sse-special-case)).

```python
# backend/src/ai/router.py:324-364
@router.get("/executions/{execution_id}/stream")
async def stream_execution(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_from_query)
):
    service = AIService(db)
    await service.get_execution(execution_id, current_user.company_id, current_user.role)

    async def event_generator():
        r = redis.from_url(settings.REDIS_URL or "redis://localhost:6379")
        pubsub = r.pubsub()
        channel = f"execution:{execution_id}"
        await pubsub.subscribe(channel)
        try:
            yield "data: {\"status\": \"connected\"}\n\n"
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = message["data"].decode("utf-8")
                    yield f"data: {data}\n\n"
                    if any(
                        f"\"status\": \"{terminal}\"" in data
                        for terminal in ("COMPLETED", "FAILED", "CANCELLED")
                    ):
                        break
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(channel)
            await r.close()

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

Auth is by **query parameter**, because the browser `EventSource` API cannot set
headers. `get_current_user_from_query` takes `token` as a plain query arg and
runs the same `_authenticate_user` as the header path
([`dependencies.py:72`](../../backend/src/auth/dependencies.py:72)). Then the run
itself is authorised through `AIService.get_execution` with the caller's
`company_id` and role, so cross-tenant reads are blocked.

A real frame sequence on the wire (each record is `data: <json>` followed by a
blank line; there are no `event:` names and no `id:` fields):

```text
data: {"status": "connected"}

data: {"type": "task_class_classified", "task_class": "research"}

data: {"type": "span_open", "span_id": "0f1c…", "parent_span_id": null, "kind": "iteration", "name": "iteration-1", "iteration": 1, "seq": 1, "status": "running", "duration_ms": null, "cost_usd": null, "tokens_in": null, "tokens_out": null, "child_run_id": null, "payload": {}, "error": null}

data: {"type": "iteration_start", "iteration": 1, "executor": "tool_call", "budget_pressure": 0.08, "open_subgoals": 3}

data: {"type": "critic_pre", "iteration": 1, "verdict": "PROCEED", "concerns_count": 0, "cost_usd": 0.0004}

data: {"type": "iteration_end", "iteration": 1, "outcome": "success", "decision": "CONTINUE", "cost_iter_usd": 0.0121}

data: {"type": "run_end", "outcome": "COMPLETED", "iters": 4, "total_cost_usd": 0.0488, "status": "COMPLETED"}

```

### 11.2 Who publishes to `execution:{run_id}`

Every producer writes JSON to the same Redis channel. This is genuine Redis
pub/sub — unlike the gateway's in-process event bus — which is why a run
executing in the arq worker can stream to a browser attached to the backend.

| Publisher | File | Payload `type` values |
|-----------|------|----------------------|
| AgentLoop telemetry | [`agent_loop_sse.py:75`](../../backend/src/ai/core/agent_loop_sse.py:75) | `iteration_start`, `iteration_end`, `resume`, `critic_pre`, `critic_post`, `critic_align`, `critic_super`, `retry_picked`, `retry_dequeued`, `replan_triggered`, `cancelled`, `run_end` |
| Trace spans | [`trace.py:251`](../../backend/src/ai/core/trace.py:251) | `span_open`, `span_close` |
| HITL checkpoints | [`governance_service.py:336`](../../backend/src/ai/governance/governance_service.py:336) | no `type`; `{"status": "HITL_PENDING", "approval_id", "trigger", "message"}` |
| Cancellation | [`service.py:528`](../../backend/src/ai/service.py:528) | `{"type": "cancelled", "status": "CANCELLED"}` |

The internal-name → wire-`type` translation is a single dict:

```python
# backend/src/ai/core/agent_loop_sse.py:29-42
_SSE_EVENT_TYPES: dict[str, str] = {
    "agent.loop.iteration_start": "iteration_start",
    "agent.loop.iteration_end": "iteration_end",
    "agent.loop.resume": "resume",
    "agent.critic.pre_verdict": "critic_pre",
    "agent.critic.post_verdict": "critic_post",
    "agent.critic.alignment": "critic_align",
    "agent.critic.supervisor": "critic_super",
    "agent.retry.picked": "retry_picked",
    "agent.retry.dequeued": "retry_dequeued",
    "agent.loop.replan": "replan_triggered",
    "agent.loop.cancelled": "cancelled",
    "agent.loop.run_end": "run_end",
}
```

An event whose internal name is not in that dict is logged and traced but never
reaches the browser. If you add a loop event and it does not show up in the UI,
this dict is the missing link.

### 11.3 HITL on the same channel

[15 — Governance & HITL](15-governance-and-hitl.md) documents the checkpoint
protocol; from a transport point of view it is two channels:

```mermaid
sequenceDiagram
    participant W as Arq worker - AgentLoop
    participant G as GovernanceService
    participant R as Redis
    participant BE as Backend SSE endpoint
    participant BR as Browser
    participant OP as Operator

    W->>G: checkpoint reached
    G->>G: INSERT approval row PENDING
    G->>R: PUBLISH execution:run_id status HITL_PENDING, approval_id, trigger, message
    R->>BE: pubsub message
    BE-->>BR: data: {"status": "HITL_PENDING", ...}
    G->>R: SUBSCRIBE hitl:approval_id and wait until timeout_ms
    OP->>BE: POST /api/v1/ai/approvals/approval_id/respond
    BE->>R: PUBLISH hitl:approval_id status APPROVED, responded_by, notes
    R->>G: message received, checkpoint unblocks
    G->>W: resume the loop
```

Note the asymmetry: `execution:{run_id}` is browser-facing and relayed as SSE;
`hitl:{approval_id}` is worker-facing and never leaves the backend.

### 11.4 Stream termination and reconnection

```mermaid
stateDiagram-v2
    [*] --> Connecting: EventSource constructed with token query param
    Connecting --> Open: first frame status connected
    Connecting --> Errored: non-200 or network failure
    Open --> Open: data frames relayed from Redis
    Open --> Closed: payload contains status COMPLETED, FAILED or CANCELLED
    Open --> Errored: proxy timeout or backend restart
    Errored --> Connecting: browser EventSource auto-retry
    Closed --> [*]: generator breaks, pubsub unsubscribed
```

**There is no resume.** Nothing in the backend or frontend references
`Last-Event-ID`; no `id:` field is ever emitted, and Redis pub/sub has no
backlog. On reconnect the client gets `{"status": "connected"}` and then only
events published from that moment on. Everything emitted while the connection was
down is lost from the stream.

The UI compensates rather than resumes. `AgentLoopExecutionDetail` polls the REST
snapshot, health records and persisted trace spans every 3 s and merges them over
the SSE-derived slices:

```
// frontend/src/components/agent/AgentLoopExecutionDetail.tsx:79-82
// Merge persisted health records into the per-iteration slices the
// SSE reducer maintains, so the page shows accurate verdicts even
// for iterations that finished before the page subscribed.
```

So SSE is a *latency optimisation* layered on a polled source of truth. That is
worth knowing before you spend a day making the stream resumable.

### 11.5 The frontend consumers

| Hook | File | Used by | Behaviour |
|------|------|---------|-----------|
| `useAgentEvents` | [`services/events.ts`](../../frontend/src/services/events.ts) | `useExecutionEvents` | Low level. Opens one `EventSource`, JSON-parses each `message`, routes to `onEvent` or `onUnknown`. |
| `useExecutionEvents` | [`hooks/useExecutionEvents.ts`](../../frontend/src/hooks/useExecutionEvents.ts) | `AgentLoopExecutionDetail` | Reducer over `AgentEvent`. Builds `iterations`, `iterationOrder`, `spans`, `banditUpdates`, `replans`, `costByAttribution`, `taskClass`. |
| `useSSE` | [`hooks/useSSE.ts`](../../frontend/src/hooks/useSSE.ts) | **nothing** | Older generic hook. Closes on `data.status === 'complete'` — a lowercase value nothing publishes. Dead code. |

Token injection is identical in both live hooks:

```typescript
// frontend/src/services/events.ts:56-59
const token = localStorage.getItem('access_token');
const sep = url.includes('?') ? '&' : '?';
const source = new EventSource(`${url}${sep}token=${token ?? ''}`);
```

The URL comes from [`ExecutionDetail.tsx:777`](../../frontend/src/pages/ai/ExecutionDetail.tsx:777):

```typescript
const streamUrl = `${_API_BASE}/ai/executions/${run.id}/stream`;
```

with `_API_BASE` defaulting to `https://gateway.hirebuddha.com/api/v1`. So the
browser talks to the gateway, the gateway relays from the backend, the backend
relays from Redis.

```mermaid
flowchart LR
    W["Arq worker AgentLoop"] -->|publish| RD[("Redis channel execution:run_id")]
    G["GovernanceService HITL"] -->|publish| RD
    T["TraceRecorder spans"] -->|publish| RD
    S["AIService cancel"] -->|publish| RD
    RD -->|pubsub.listen| BE["Backend GET /ai/executions/id/stream"]
    BE -->|text/event-stream| GW["Gateway SSE relay, no read timeout"]
    GW -->|text/event-stream| ES["Browser EventSource"]
    ES --> HK["useAgentEvents parse"]
    HK --> RED["executionEventReducer"]
    RED --> UI["Iteration timeline, span tree, cost panel"]
```

---

## 12. Transport comparison

| Transport | Where | Direction | Used for | Why this one |
|-----------|-------|-----------|----------|--------------|
| **REST** (proxied HTTP) | `/{path:path}` → backend:8000 | request/response | Every `/api/v1/*` call: CRUD on entities, runs, billing, config | Cacheable, debuggable, the backend already speaks it. Zero state in the gateway. |
| **HTTP POST, fire-and-forget** | `/webhook/inbound`, `/internal/event` | inbound only, `202` | External systems and internal services triggering agents | Providers demand fast ACKs. Work is deferred to the bus and arq. |
| **SSE** | `/api/v1/ai/executions/{id}/stream` relayed | server → browser | Live execution traces, iteration timeline, HITL prompts | One-way, text-only, survives plain HTTP proxies, auto-reconnects in the browser, no extra client library. |
| **WebSocket, JSON frames** | `/stream/twilio/*`, `/stream/tata/*`, `/webhooks/voice/tata/incoming`, `/stream/audio` with telephony providers | bidirectional | Telephony media (base64 mulaw in JSON) | The wire format is dictated by Twilio and its clones. |
| **WebSocket, binary frames** | `/stream/audio` with `provider=web` | bidirectional | Browser microphone in, TTS out | Raw PCM16 avoids base64's 33% overhead on a latency-critical path. |
| **WebSocket, signalling only** | `/stream/video` | bidirectional JSON | SDP/ICE exchange | WebRTC needs an out-of-band signalling channel; WS is the standard choice. |
| **WebRTC (DTLS/SRTP)** | negotiated peer connection | bidirectional media | Video + audio tracks | Only transport with NAT traversal, jitter buffering and congestion control for real-time media. |

```mermaid
flowchart TD
    Q1{"Does a human need to see it change live"} -->|no| REST["REST - proxied"]
    Q1 -->|yes| Q2{"Does the client need to send data continuously"}
    Q2 -->|no| SSE["SSE - one-way text"]
    Q2 -->|yes| Q3{"Is it real-time media"}
    Q3 -->|no| WSJ["WebSocket JSON frames"]
    Q3 -->|yes| Q4{"Does the peer speak WebRTC"}
    Q4 -->|no| WSB["WebSocket binary PCM16"]
    Q4 -->|yes| RTC["WebRTC DTLS/SRTP"]
```

---

## 13. Reverse proxy — Apache

Configs live in [`deploy/apache/`](../../deploy/apache) and are installed by
[`setup_apache.sh`](../../deploy/apache/setup_apache.sh).

### 13.1 Virtual hosts

| Hostname | Upstream | Notes |
|----------|----------|-------|
| `app.hirebuddha.com` | `localhost:3000` | The React app. |
| `gateway.hirebuddha.com` | `localhost:8001` | The gateway. **The only vhost with WebSocket rewrite rules.** |
| `api.hirebuddha.com` | `localhost:8001` | Alias onto the gateway. No WS rules — WebSockets fail here. |
| `dev.hirebuddha.com` | see config | Dev environment. |
| `streaming.hirebuddha.com` | `localhost:8002` | Points at the **retired** port-8002 streaming service. Nothing listens there any more (`start_services.sh` starts 8000, 8001, 3000 and the arq worker only). Stale config. |

```mermaid
graph TB
    subgraph Internet
        U["Browser, telephony, SaaS"]
    end
    subgraph VM["Production VM"]
        AP["Apache 80 and 443"]
        FE["Vite dev/static 3000"]
        GW["Gateway 8001"]
        BE["Backend 8000"]
        WK["Arq worker"]
        RD["Redis 6379"]
        PG["Postgres 5433"]
        X8002["port 8002 - nothing listening"]
    end

    U -->|app.hirebuddha.com| AP
    U -->|gateway.hirebuddha.com| AP
    U -->|api.hirebuddha.com| AP
    U -->|streaming.hirebuddha.com| AP
    AP --> FE
    AP --> GW
    AP -.stale vhost.-> X8002
    GW --> BE
    GW --> RD
    GW --> PG
    BE --> PG
    BE --> RD
    RD --> WK
```

### 13.2 The WebSocket upgrade rules

```apache
# deploy/apache/gateway.hirebuddha.com-le-ssl.conf
ProxyPreserveHost On
ProxyRequests Off

# ===== WebSocket Proxy (MUST come before regular proxy) =====
RewriteEngine On
RewriteCond %{HTTP:Upgrade} =websocket [NC]
RewriteRule /stream/(.*) ws://127.0.0.1:8001/stream/$1 [P,L]

RewriteCond %{HTTP:Upgrade} =websocket [NC]
RewriteRule /webhooks/voice/tata/(.*) ws://127.0.0.1:8001/webhooks/voice/tata/$1 [P,L]

ProxyTimeout 86400

# ===== Regular HTTP Proxy =====
ProxyPass / http://localhost:8001/
ProxyPassReverse / http://localhost:8001/
```

Required modules, enabled by `setup_apache.sh`:
`proxy`, `proxy_http`, `proxy_wstunnel`, `ssl`, `rewrite`, `headers`, `remoteip`, `deflate`.

```mermaid
flowchart TD
    REQ["Request to gateway.hirebuddha.com"] --> UPG{"Upgrade header == websocket"}
    UPG -->|yes| PATH{"path matches /stream/ or /webhooks/voice/tata/"}
    PATH -->|yes| WS["RewriteRule with P flag -> mod_proxy_wstunnel -> ws://127.0.0.1:8001"]
    PATH -->|no| HTTP["falls through to ProxyPass, upgrade fails"]
    UPG -->|no| HTTP2["ProxyPass / -> http://localhost:8001/"]
    WS --> LIVE["Connection held up to ProxyTimeout 86400s"]
    HTTP2 --> RESP["Normal HTTP response"]
```

### 13.3 Pitfalls

- **`ProxyTimeout 86400`** (24 h) is the reason long calls and long SSE streams
  survive. It is set on `gateway.*` and `streaming.*` only. The `api.*` vhost has
  **no** `ProxyTimeout` and **no** WS rules — it inherits the default 60 s and will
  cut a quiet SSE stream. Use `gateway.hirebuddha.com` for anything long-lived.
- **`X-Accel-Buffering: no` does nothing here.** The gateway sets it
  ([`app.py:403`](../../backend/src/gateway/app.py:403)) but that is an nginx
  directive. Apache's `mod_proxy_http` streams a chunked response without
  content-length reasonably promptly, which is why SSE works; if you ever see
  events arriving in bursts, the Apache-native fix is
  `ProxyPass / http://localhost:8001/ flushpackets=on`.
- **`mod_deflate` is enabled.** If a future config compresses `text/event-stream`,
  frames will be buffered until the compression window fills and SSE will appear
  to hang. Exclude `text/event-stream` from `AddOutputFilterByType` if you touch
  compression.
- **Rate limits are keyed on the proxy's IP.** `get_remote_address` reads
  `request.client.host`, which behind Apache is `127.0.0.1` for every caller
  unless `RemoteIPHeader X-Forwarded-For` is configured. `remoteip` is enabled by
  the setup script but **no vhost configures `RemoteIPHeader`**, so today the
  200/minute limit is effectively a single global bucket for all users.
- **New WebSocket path?** Add a matching `RewriteCond`/`RewriteRule` pair. A path
  outside `/stream/` and `/webhooks/voice/tata/` will be proxied as plain HTTP and
  the upgrade will fail with a confusing 200 or 400.
- **`ProxyPreserveHost On`** means the backend sees the public hostname. Anything
  the backend builds from `request.url` will contain the public host, which is
  what you want for callback URLs.

---

## 14. Scaling and state

### 14.1 Is the gateway stateless?

Mostly, but not entirely. Four things live in process memory:

| State | Where | Consequence with more than one instance |
|-------|-------|-----------------------------------------|
| `InMemoryEventBus` singleton | [`event_bus.py:176`](../../backend/src/gateway/event_bus.py:176) | Not shared. Fine in practice: each instance's dispatcher consumes only its own instance's events and pushes work to the shared arq queue. Metrics on `/health` become per-instance. |
| `CentralDispatcher` singleton + consumer task | [`dispatcher.py:417`](../../backend/src/gateway/dispatcher.py:417) | One per instance. Also fine. |
| `_active_video_sessions` dict | [`video_gateway.py:341`](../../backend/src/gateway/video_gateway.py:341) | `/metrics/gateway` reports only the sessions on the instance you happened to hit. |
| Open WebSocket connections and their `VoiceSession` / `RTCPeerConnection` | per connection | **Session affinity required.** A telephony provider or browser must keep talking to the same instance for the life of the call. |

Shared, therefore safe to scale:

| Shared thing | Backing store |
|--------------|---------------|
| Rate-limit counters | Redis (`storage_uri=settings.REDIS_URL`) |
| Agent resolution cache | Redis key `gateway:agent:{client_id}:{channel}`, TTL 300 s |
| Job queue | Redis via arq |
| SSE fan-out | Redis pub/sub, `execution:{run_id}` |
| Voice sessions, runs, entities | PostgreSQL |

```mermaid
graph TB
    LB["Load balancer"] --> G1["Gateway instance A"]
    LB --> G2["Gateway instance B"]

    subgraph SharedOK["Shared - scales cleanly"]
        RD[("Redis - rate limits, agent cache, arq, pubsub")]
        PG[("PostgreSQL")]
    end

    subgraph PerInstance["Per instance - not shared"]
        B1["Event bus A"]
        V1["Video sessions A"]
        B2["Event bus B"]
        V2["Video sessions B"]
    end

    G1 --> RD
    G2 --> RD
    G1 --> PG
    G2 --> PG
    G1 --- B1
    G1 --- V1
    G2 --- B2
    G2 --- V2

    WSC["Live WebSocket - must pin to one instance"] -.sticky.-> G1
```

### 14.2 What breaks with two instances

1. **WebSocket sessions without stickiness.** A reconnect that lands on the other
   instance has no `VoiceSession` in memory and no peer connection. The audio
   handshake supports resume via `metadata.session_id`, which re-reads the
   `VoiceSession` from Postgres — but the live LLM connection and audio buffers do
   not transfer. WebRTC cannot resume at all.
2. **`/metrics/gateway` and `/health` become sampled, not total.** Scrape all
   instances and sum, or the numbers lie.
3. **Nothing else.** Webhooks, internal events and the REST proxy are genuinely
   stateless because the handoff point is Redis.

Today there is exactly one instance: `start_services.sh` binds a single uvicorn to
8001 and `docker-compose.yml` declares one `gateway` service with no `deploy.replicas`.

### 14.3 Where affinity is required

| Path | Affinity | Why |
|------|----------|-----|
| `/api/v1/*` | none | Pure proxy. |
| `/webhook/inbound`, `/internal/event` | none | Handoff to Redis. |
| `/api/v1/ai/executions/{id}/stream` | none | Redis pub/sub is shared; any instance can relay. |
| `/stream/audio`, `/stream/twilio/*`, `/stream/tata/*`, `/webhooks/voice/tata/incoming` | **required for connection lifetime** | In-memory session + live LLM socket. |
| `/stream/video` | **required for connection lifetime** | `RTCPeerConnection` is process-local. |

---

## 15. Operational runbook

### 15.1 Bring it up locally

```bash
# from repo root
./start_services.sh            # backend 8000, gateway 8001, arq worker, frontend 3000
tail -f logs/unified_gateway.log

# or just the gateway
cd backend
.venv/bin/python -m uvicorn src.gateway.app:app --host 0.0.0.0 --port 8001 --reload
```

### 15.2 Test each transport

**Health and metrics**

```bash
curl -s localhost:8001/health | jq
curl -s localhost:8001/metrics/gateway | jq
curl -s localhost:8001/ | jq .interfaces
```

**REST proxy** — should return whatever the backend returns, including its 401:

```bash
curl -i localhost:8001/api/v1/ai/entities
curl -i -H "Authorization: Bearer $TOKEN" localhost:8001/api/v1/ai/entities
```

**Webhook** — expect `202` and a `correlation_id`:

```bash
curl -i -X POST "localhost:8001/webhook/inbound?client_id=$COMPANY_UUID" \
  -H 'Content-Type: application/json' \
  -H 'X-GitHub-Event: push' \
  -d '{"repository":{"full_name":"acme/widgets"},"sender":{"login":"dev"}}'
# -> {"status":"accepted","source":"github","event_type":"github.push",...}
```

**Internal event** — check both the 401 and the 202:

```bash
curl -i -X POST localhost:8001/internal/event \
  -H 'Content-Type: application/json' \
  -d '{"event_type":"doc_indexed","client_id":"'$COMPANY_UUID'","source":"vector_db","payload":{}}'
# -> 401 {"error":"Unauthorized","detail":"Invalid or missing X-Internal-Token"}

curl -i -X POST localhost:8001/internal/event \
  -H "X-Internal-Token: $INTERNAL_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"event_type":"doc_indexed","client_id":"'$COMPANY_UUID'","source":"vector_db","payload":{"document_id":"d1"}}'
# -> 202
```

**SSE** — `-N` disables curl's own buffering:

```bash
curl -N "localhost:8001/api/v1/ai/executions/$RUN_ID/stream?token=$TOKEN"
# data: {"status": "connected"}
# data: {"type": "iteration_start", ...}
```

Inject a fake event from another shell to prove the pipe works end to end:

```bash
redis-cli PUBLISH "execution:$RUN_ID" '{"type":"iteration_start","iteration":1,"executor":"test"}'
redis-cli PUBLISH "execution:$RUN_ID" '{"type":"run_end","outcome":"COMPLETED","status":"COMPLETED"}'
```

**WebSocket audio** — with `websocat`:

```bash
websocat ws://localhost:8001/stream/audio
# then paste:
{"event":"connect","provider":"web","client_id":"<company-uuid>","token":"x","metadata":{"direction":"inbound"}}
# expect: {"event":"connected","session_id":"...","status":"ready","provider":"web","agent_id":"..."}
{"event":"ping"}
# expect: {"event":"pong"}
```

**WebSocket video**:

```bash
websocat ws://localhost:8001/stream/video
{"event":"connect","provider":"web","client_id":"<company-uuid>"}
# expect: {"event":"connected",...,"webrtc_enabled":false}
# then:   {"event":"info","message":"WebRTC media disabled. Install aiortc: pip install aiortc aiohttp"}
```

**Through Apache** (production shape):

```bash
curl -sN https://gateway.hirebuddha.com/health
websocat wss://gateway.hirebuddha.com/stream/audio
```

**The test suite**:

```bash
cd backend && python -m pytest tests/e2e/test_12_unified_gateway.py -v
```

### 15.3 Log signatures

| Log line | Meaning |
|----------|---------|
| `[Startup] Event bus ready (type=memory, maxsize=1000)` | Normal boot. |
| `[Dispatcher] Redis connection established` | Normal boot. |
| `[Dispatcher] Redis unavailable, session cache disabled` | Redis down; agent cache off and arq enqueue will fail into the in-process fallback. |
| `[EventBus] Consumer registered (1 total)` | Dispatcher subscribed. Should appear once per boot. |
| `[EventBus] No consumers registered; event '<type>' dropped` | Dispatcher consumer is gone. Every webhook is being thrown away. |
| `[EventBus] Consumer queue full; dropping event '<id>'` | Inbound rate exceeds dispatch rate; raise `EVENT_BUS_MAXSIZE` or find the slow dispatch. |
| `[WebhookRouter] Received <type> from source=<s> client=<id> correlation=<uuid>` | Webhook accepted. |
| `[WebhookRouter] <provider> signature validation not yet configured` | Expected today; see [8.2](#82-signature-verification--what-is-actually-implemented). |
| `[Dispatcher] Envelope <id> has no client_id — dropping` | Caller forgot `?client_id=`. |
| `[Dispatcher] arq enqueue failed (...); falling back to in-process dispatch` | Redis/arq problem. Agent runs are now executing inside the gateway. |
| `[Dispatcher] No active agent for company <id>` | Tenant has no non-archived `HierarchicalEntity`. |
| `[Proxy] Backend unreachable: ...` | Backend 8000 down → client got 503. |
| `[Proxy] SSE backend unreachable: ...` | Same, on the streaming path. |
| `[AudioGateway] Session <id> ready (web, agent=<id>)` | Browser audio session established. |
| `[VideoGateway] Session <id> connected (provider=web, ..., webrtc=False)` | aiortc missing or video disabled. |
| `[VideoSession] Audio track error: ...` | Almost certainly the `__mro__` bug in [10.1](#101-implemented-versus-stubbed--read-this-first). |
| `AgentLoop SSE publish failed for <event>: ...` | Redis publish failed; the run continues but the UI goes quiet. |

### 15.4 Common failures

| Symptom | Likely cause | Check |
|---------|--------------|-------|
| SSE connects then hangs forever with no events | Nothing is publishing to `execution:{run_id}` — the run finished before you subscribed, or `set_sse_redis` was never called | `redis-cli PUBLISH execution:$RUN_ID '{"type":"x"}'` and see if the curl prints it |
| SSE returns 503 after ~60 s | The relay path was not taken (URL does not end in `/stream` and no `Accept: text/event-stream`) | Confirm the exact request URL in the gateway log |
| SSE works on `gateway.*` but dies on `api.*` | `api.hirebuddha.com` vhost has no `ProxyTimeout` | Use the gateway hostname |
| WebSocket returns 200 HTML or 400 instead of upgrading | Path not covered by the Apache rewrite rules | `grep RewriteRule deploy/apache/gateway.hirebuddha.com-le-ssl.conf` |
| WebSocket drops after ~60 s in production | `ProxyTimeout` missing on that vhost | Add `ProxyTimeout 86400` |
| Audio WS closes with `1008 No agent found for client` | No non-archived entity for that company, or wrong `client_id` | Query `hierarchical_entities` for the company |
| Webhook returns 202 but nothing runs | Missing `?client_id=`, or dispatcher consumer dead | `/health` → `event_bus.consumer_count` and `total_dropped` |
| Everyone is rate limited at once | `get_remote_address` sees `127.0.0.1` for all callers behind Apache | Configure `RemoteIPHeader X-Forwarded-For` |
| Duplicate executions from one webhook | Provider retried; no idempotency | See [8.3](#83-idempotency--there-is-none) |
| 401 on `/internal/event` from a browser looks like a CORS error | Auth middleware short-circuits before CORS | See [2.3](#23-middleware-stack--the-ordering-trap) |
| Video calls silent | aiortc not installed, and the `__mro__` bug | `pip list \| grep aiortc`, then fix `video_gateway.py:202` |

---

## Key files reference

| File | Lines | What it does |
|------|-------|--------------|
| [`backend/src/gateway/app.py`](../../backend/src/gateway/app.py) | 436 | The live gateway app: lifespan, middleware, routers, back-compat WS endpoints, catch-all REST proxy with SSE relay. |
| [`backend/src/gateway/main.py`](../../backend/src/gateway/main.py) | 73 | Legacy thin proxy. Dead — nothing starts it. |
| [`backend/src/gateway/gateway_config.py`](../../backend/src/gateway/gateway_config.py) | 73 | `UnifiedGatewaySettings` — the 17 settings the live gateway reads. |
| [`backend/src/gateway/config.py`](../../backend/src/gateway/config.py) | 10 | `GatewaySettings` — 3 settings, used only by `main.py`. |
| [`backend/src/gateway/auth_middleware.py`](../../backend/src/gateway/auth_middleware.py) | 148 | `TenantContext`, `GatewayAuthMiddleware`, `require_internal`, `get_tenant`. Only `/internal/event` is actually gated. |
| [`backend/src/gateway/dispatcher.py`](../../backend/src/gateway/dispatcher.py) | 425 | `CentralDispatcher`: consumes the bus, enqueues arq jobs, resolves agents, in-process fallback, lead-queue path. |
| [`backend/src/gateway/event_bus.py`](../../backend/src/gateway/event_bus.py) | 186 | `EventEnvelope`, `InMemoryEventBus`, `EventBusSubscription`, `get_event_bus`. In-process only. |
| [`backend/src/gateway/internal_event.py`](../../backend/src/gateway/internal_event.py) | 192 | `POST /internal/event`, `InternalEvent` schema, `WellKnownEvents`, unused `emit_internal_event` helper. |
| [`backend/src/gateway/webhook_inbound.py`](../../backend/src/gateway/webhook_inbound.py) | 598 | 12 webhook strategies, `detect_strategy`, `POST /webhook/inbound`. No working signature verification. |
| [`backend/src/gateway/audio_gateway.py`](../../backend/src/gateway/audio_gateway.py) | 244 | `WS /stream/audio` handshake and provider routing. |
| [`backend/src/gateway/web_audio_adapter.py`](../../backend/src/gateway/web_audio_adapter.py) | 255 | Browser PCM16 ↔ live LLM bridge, four concurrent tasks, transcript logging. |
| [`backend/src/gateway/video_gateway.py`](../../backend/src/gateway/video_gateway.py) | 540 | `WS /stream/video` signalling, `VideoSession`, vision frame sampling, active-session registry. |
| [`backend/src/ai/router.py:324`](../../backend/src/ai/router.py:324) | — | The SSE producer: `GET /api/v1/ai/executions/{id}/stream`. |
| [`backend/src/ai/core/agent_loop_sse.py`](../../backend/src/ai/core/agent_loop_sse.py) | 80 | Internal event name → SSE `type` translation and Redis fan-out. |
| [`backend/src/ai/core/arq_jobs.py:163`](../../backend/src/ai/core/arq_jobs.py:163) | — | `process_gateway_event`, the worker side of every webhook/internal event. |
| [`frontend/src/services/events.ts`](../../frontend/src/services/events.ts) | 79 | `useAgentEvents` — the live `EventSource` hook. |
| [`frontend/src/hooks/useExecutionEvents.ts`](../../frontend/src/hooks/useExecutionEvents.ts) | 288 | Reducer turning SSE events into the Execution Detail view model. |
| [`frontend/src/hooks/useSSE.ts`](../../frontend/src/hooks/useSSE.ts) | 58 | Older generic SSE hook. No callers. |
| [`deploy/apache/gateway.hirebuddha.com-le-ssl.conf`](../../deploy/apache/gateway.hirebuddha.com-le-ssl.conf) | 32 | The only vhost with WebSocket upgrade rules and a 24 h `ProxyTimeout`. |
| [`backend/tests/e2e/test_12_unified_gateway.py`](../../backend/tests/e2e/test_12_unified_gateway.py) | 377 | ASGI-transport tests for health, webhooks, internal events, the bus and strategy detection. |

---

## Gotchas and things that surprise newcomers

- **`gateway/main.py` is dead.** Only `gateway/app.py` runs. Same for
  `gateway/config.py` versus `gateway/gateway_config.py`.
- **The "event bus" is not Redis.** It is an `asyncio.Queue` inside one process,
  with exactly one subscriber. Cross-process delivery happens later, via arq.
- **`EVENT_BUS_TYPE` is never read.** Neither are `TURN_USERNAME` and
  `TURN_CREDENTIAL`. `priority` on internal events is stored and ignored.
- **Auth middleware runs before CORS**, so its 401s carry no CORS headers.
- **The auth middleware never sees WebSockets.** `BaseHTTPMiddleware` passes
  non-HTTP scopes straight through, so the `/stream/*` branch is dead for real WS
  connections — and the handshake `token` is read into a variable and never
  validated.
- **No webhook signature is verified.** Every `validate_signature` returns `True`,
  several with an explicit TODO, and a `False` would not block the request anyway.
- **No webhook idempotency.** Provider retries create duplicate executions.
- **`@app.on_event("shutdown")` never fires** because a custom `lifespan` was
  supplied; `close_proxy_client` is dead code.
- **Rate limiting covers only the REST proxy.** Without `SlowAPIMiddleware`,
  slowapi's `default_limits` apply only to decorated routes — `/webhook/inbound`,
  `/internal/event` and all WebSocket routes are unlimited.
- **Rate limits are keyed on `127.0.0.1` in production** because no vhost sets
  `RemoteIPHeader`.
- **`X-Accel-Buffering: no` is an nginx header** and does nothing under Apache.
- **The proxy copies upstream response headers verbatim**, including
  `content-length` and `content-encoding`, while `httpx` has already decompressed
  the body. Harmless today because the backend has no `GZipMiddleware` — enabling
  one would break the proxy.
- **Agent selection is `LIMIT 1` with no `ORDER BY`** in three separate places.
  For multi-agent tenants, pass an explicit `entity_id`.
- **The arq fallback runs a full AgentLoop inside the gateway.** Convenient in
  dev, dangerous under load — it shares an event loop with live audio.
- **SSE has no `Last-Event-ID` and no replay.** Reconnection loses everything that
  happened while disconnected; the UI's 3-second polling is what actually keeps
  the page correct.
- **`streaming.hirebuddha.com` points at port 8002, which no longer exists.**
  All streaming moved into the gateway on 8001.
- **aiortc is not installed**, so `/stream/video` currently only answers the
  handshake and closes. Even with it installed, the audio pipeline aborts on the
  `__mro__` line at `video_gateway.py:202`.

---

## Where to go next

- [12 — Voice, telephony & messaging](12-voice-and-telephony.md) — what happens
  to audio after the gateway hands it to `TwilioStreamHandler` or the live client.
- [02 — System architecture & topology](02-system-architecture.md) — the full
  process and port map this document zooms into.
- [04 — Auth, RBAC & multi-tenancy](04-auth-rbac-tenancy.md) — the *real* auth,
  enforced after the proxy hop.
- [06 — Entities & the execution pipeline](06-execution-pipeline.md) — what
  `process_gateway_event` builds once a webhook becomes a run.
- [15 — Governance, HITL & feature flags](15-governance-and-hitl.md) — the
  `execution:{run_id}` / `hitl:{approval_id}` protocol in full.
- [16 — Frontend architecture](16-frontend.md) — where `useExecutionEvents` sits
  in the React app.
- [17 — API reference](17-api-reference.md) — the exhaustive endpoint list.
- [18 — Infrastructure, deployment & operations](18-infrastructure-and-deployment.md) —
  Apache, systemd, and the production VM.
