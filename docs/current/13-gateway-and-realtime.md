# 13. The Webhook & Real-Time Edge (formerly the Unified Gateway)

> **What this document covers:** the inbound-event and real-time endpoints of the API on port 8000 — webhooks, internal events, WebSocket audio, WebRTC video, the telephony media streams and Server-Sent Events — and how each transport behaves end to end. Until 2026-09-30 these ran in a separate gateway process on port 8001 that also reverse-proxied REST to the API; that process is merged into the API ([§5](#5-the-former-rest-proxy)).
> **Who should read it:** anyone touching an endpoint the browser or an external system talks to, anyone debugging "the stream died", and anyone adding a new webhook provider or real-time channel.
> **Prerequisites:** [02 — System architecture](02-system-architecture.md) for the process topology, [04 — Auth, RBAC & tenancy](04-auth-rbac-tenancy.md) for how the API authenticates. Voice semantics (what happens to the audio once it arrives) live in [12 — Voice & telephony](12-voice-and-telephony.md).

---

## Table of contents

1. [The 60-second version](#1-the-60-second-version)
2. [How the edge is mounted](#2-how-the-edge-is-mounted)
3. [Configuration](#3-configuration)
4. [Auth at the edge — who gets in](#4-auth-at-the-edge--who-gets-in)
5. [The former REST proxy](#5-the-former-rest-proxy)
6. [Agent resolution (the former dispatcher)](#6-agent-resolution-the-former-dispatcher)
7. [Queuing inbound events and internal events](#7-queuing-inbound-events-and-internal-events)
8. [Inbound webhooks](#8-inbound-webhooks)
9. [Browser audio over WebSocket](#9-browser-audio-over-websocket)
10. [Video and WebRTC](#10-video-and-webrtc)
11. [Server-Sent Events for execution traces](#11-server-sent-events-for-execution-traces)
12. [Transport comparison](#12-transport-comparison)
13. [Reverse proxy — Apache](#13-reverse-proxy--apache)
14. [Scaling and state](#14-scaling-and-state)
15. [Operational runbook](#15-operational-runbook)
16. [Key files reference](#key-files-reference)
17. [Gotchas and things that surprise newcomers](#gotchas-and-things-that-surprise-newcomers)

---

## 1. The 60-second version

There is one FastAPI process, the **API** ([`src/main.py`](../../backend/src/main.py)) on
port 8000. It holds the business logic, the database session, auth, RBAC and every
`/api/v1/*` route — and it is also the "edge": the endpoints external systems and
real-time clients talk to. Those live in the `src/gateway/` package, which is now
a set of routers the API mounts, not an app of its own:

| # | Interface | Path | Module |
|---|-----------|------|--------|
| 1 | Domain REST API | `/api/v1/*` | the API's own routers |
| 2 | Unified webhook receiver | `POST /webhook/inbound` | [`webhook_inbound.py`](../../backend/src/gateway/webhook_inbound.py) |
| 3 | Internal event endpoint | `POST /internal/event` | [`internal_event.py`](../../backend/src/gateway/internal_event.py) |
| 4 | Bidirectional audio | `WS /stream/audio` | [`audio_gateway.py`](../../backend/src/gateway/audio_gateway.py) |
| 5 | Bidirectional video (WebRTC signalling) | `WS /stream/video` | [`video_gateway.py`](../../backend/src/gateway/video_gateway.py) |
| — | Telephony media streams | `WS /stream/twilio/{id}`, `WS /stream/tata/{id}`, `WS /webhooks/voice/tata/incoming` | [`telephony_streams.py`](../../backend/src/gateway/telephony_streams.py) |
| — | Mobile push socket | `WS /mobile/ws` | [`mobile/push_gateway.py`](../../backend/src/mobile/push_gateway.py) |
| — | Execution traces (SSE) | `GET /api/v1/ai/executions/{id}/stream` | [`ai/router.py`](../../backend/src/ai/router.py) |

Why was there a separate gateway at all? Its design argued three things: that
long-lived sockets should not share a process with request/response traffic, that
one public surface should front many protocols, and that CORS and rate limiting
belonged at the edge. In practice the gateway imported the voice handlers and
opened its own database sessions — it needed the whole codebase anyway — and the
split added a proxy hop, a second settings class with drifting defaults, two CORS
lists, and a catch-all route that swallowed anything declared after it. One
public hostname (`gateway.hirebuddha.com`) still fronts every protocol; it now
points at port 8000.

### Master diagram — everything that flows through the edge

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

    subgraph API["API - uvicorn 8000"]
        MW["CORS -> rate limit"]
        REST["/api/v1 routers"]
        SSE["GET /ai/executions/id/stream"]
        R2["POST /webhook/inbound"]
        R3["POST /internal/event"]
        R4["WS /stream/audio"]
        R5["WS /stream/video"]
        R6["WS /stream/twilio and /stream/tata"]
        QE["queue_event - before the 202"]
        DISP["CentralDispatcher - agent resolution"]
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
    MW --> REST
    MW --> SSE
    MW --> R2
    MW --> R3
    AP -.websocket upgrade.-> R4
    AP -.websocket upgrade.-> R5
    AP -.websocket upgrade.-> R6

    R2 --> QE
    R3 --> QE
    QE -->|arq enqueue| RD
    R4 --> DISP
    R5 --> DISP
    RD --> WK
    WK --> PG
    WK -->|publish execution:run_id| RD
    RD --> SSE
    REST --> PG
    R4 --> PG
    R5 --> PG
```

The edge modules are a **fan-in point, not a brain**. Business logic is
elsewhere. They normalise, authenticate lightly, and hand off.

---

## 2. How the edge is mounted

### 2.1 In `main.py`

```python
# backend/src/main.py
app = FastAPI(title="HireBuddha Platform", version="0.2.0", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins_list, ...)
...
app.include_router(mobile_push_router)                    # WS /mobile/ws
...
mount_optional(app, "src.gateway.webhook_inbound")        # POST /webhook/inbound
mount_optional(app, "src.gateway.internal_event")         # POST /internal/event
mount_optional(app, "src.gateway.telephony_streams")      # WS /stream/twilio|tata/{id}, ...
mount_optional(app, "src.gateway.audio_gateway")          # WS /stream/audio
mount_optional(app, "src.gateway.video_gateway")          # WS /stream/video
mount_optional(app, "src.gateway.status")                 # GET /metrics/gateway
```

The edge routers go through `mount_optional`
([`common/router_mounts.py`](../../backend/src/common/router_mounts.py)): if one
fails to import, the API still boots, that router's paths answer 404, and
`GET /api/v1/health` names it under `unmounted_routers`.

### 2.2 Middleware

Starlette's `add_middleware` **prepends**: the middleware added *last* runs
*first*. So a request meets `CORSMiddleware`, then `SlowAPIMiddleware`, then the
route. CORS is outermost on purpose — it answers preflights before anything else
and decorates every response, so a 401, 403 or 429 reaches a browser as itself
rather than as an opaque CORS failure. (Company suspension is checked by the
auth dependency, not middleware — SA-18.) (On
the gateway the auth middleware ran before CORS and its 401s carried no CORS
headers.)

Both are HTTP-only: WebSocket connections pass straight through — see
[section 4.3](#43-the-websocket-blind-spot).

### 2.3 Startup and shutdown lifecycle

```python
# backend/src/main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    from src.gateway.dispatcher import get_dispatcher

    dispatcher = get_dispatcher()
    await dispatcher.start()
    yield
    await dispatcher.stop()
```

```mermaid
sequenceDiagram
    participant U as uvicorn
    participant A as API app
    participant D as CentralDispatcher
    participant R as Redis

    U->>A: ASGI lifespan startup
    A->>D: get_dispatcher then start
    D->>R: aioredis.from_url REDIS_URL
    alt Redis reachable
        R-->>D: connection
        D->>D: log "Redis connection established"
    else Redis down
        D->>D: log warning, session cache disabled, keep going
    end
    A-->>U: ready, serving traffic

    Note over U,R: ... requests served ...

    U->>A: ASGI lifespan shutdown
    A->>D: stop
    D->>R: aclose
```

**Redis is optional at startup.** [`dispatcher.py`](../../backend/src/gateway/dispatcher.py)
swallows the connection error and logs a warning. The API boots without Redis;
the webhook and internal-event endpoints then answer 503 until it is back.

### 2.4 Route table

| Method | Path | Handler | Purpose |
|--------|------|---------|---------|
| `GET` | `/health`, `/api/v1/health` | [`health`](../../backend/src/common/router_mounts.py) | Liveness + routers that failed to mount. |
| `GET` | `/metrics/gateway` | [`gateway_metrics`](../../backend/src/gateway/status.py) | Active video sessions. |
| `POST` | `/webhook/inbound` | [`unified_webhook_inbound`](../../backend/src/gateway/webhook_inbound.py) | Interface 2. |
| `POST` | `/internal/event` | [`unified_internal_event`](../../backend/src/gateway/internal_event.py) | Interface 3. |
| `WS` | `/stream/audio` | [`unified_audio_streaming`](../../backend/src/gateway/audio_gateway.py) | Interface 4. |
| `WS` | `/stream/video` | [`unified_video_streaming`](../../backend/src/gateway/video_gateway.py) | Interface 5. |
| `WS` | `/webhooks/voice/tata/incoming` | [`tata_websocket_incoming`](../../backend/src/gateway/telephony_streams.py) | Tata Tele direct media stream (the HTTP webhook on the same path is `voice/webhook_router.py`). |
| `WS` | `/stream/twilio/{session_id}` | [`twilio_stream_websocket`](../../backend/src/gateway/telephony_streams.py) | Twilio media stream. |
| `WS` | `/stream/tata/{session_id}` | [`tata_stream_websocket`](../../backend/src/gateway/telephony_streams.py) | Tata media stream. |
| `WS` | `/mobile/ws` | [`mobile_push_socket`](../../backend/src/mobile/push_gateway.py) | Mobile dialer push socket. |

There is no catch-all route. `GET /metrics/gateway` is declared before the
Prometheus `/metrics` mount that `setup_telemetry` adds last, which would
otherwise match it.

When webhooks go missing, look at the worker, not the API: a 202 means the
`process_gateway_event` job is in Redis (see [section 7](#7-queuing-inbound-events-and-internal-events)).

---

## 3. Configuration

The edge reads the one settings class, `common.config.Settings`. Until the merge
the gateway had its own `UnifiedGatewaySettings` (and a legacy `GatewaySettings`),
which redeclared `DATABASE_URL`, `REDIS_URL` and `STREAMING_HOST` with different
defaults — its `DATABASE_URL` pointed at port 5432, not the compose file's 5433.

| Setting | Default | Purpose |
|---------|---------|---------|
| `REDIS_URL` | **required** | Rate-limit storage, the dispatcher's agent cache, the arq queue (via [`common/job_queue.py`](../../backend/src/common/job_queue.py)). |
| `RATE_LIMIT` | `200/minute` | slowapi limit per client IP, every REST route; `/webhook/inbound` and `/internal/event` are exempt. |
| `CORS_ORIGINS` | 6 origins incl. `localhost:3000`, `dev/app/gateway.hirebuddha.com` | Comma-separated; exposed as `cors_origins_list`. |
| `STREAMING_HOST` | `localhost:8000` | Public host used to build the `ws(s)://` URLs handed to telephony providers ([`voice/public_urls.py`](../../backend/src/voice/public_urls.py)). Set to `gateway.hirebuddha.com` in production. |
| `STREAMING_PROTOCOL` | `ws` | Scheme for those URLs; `wss` in production (then HTTP callbacks are `https`). |
| `INTERNAL_TOKEN` | `""` | Shared secret for `X-Internal-Token` on `/internal/event`. Empty or a placeholder disables the endpoint (503). |
| `VIDEO_STREAMING_ENABLED` | `True` | Kill switch for `/stream/video` media (signalling still answers). |
| `STUN_SERVERS` | `stun:stun.l.google.com:19302` | Comma-separated; exposed as `stun_servers_list`. |
| `TURN_SERVER_URL` | `""` | Appended to the ICE server list when set. |
| `TURN_USERNAME` | `""` | Declared but **never used** — `RTCIceServer` is built with `urls` only. |
| `TURN_CREDENTIAL` | `""` | Same: declared, never used. Authenticated TURN will not work as written. |

Gone with the gateway: `BACKEND_URL` (the proxy target), `GATEWAY_PORT`,
`JWT_SECRET` / `JWT_ALGORITHM` (a second copy of the JWT key, used only to decode
tokens for logging) and `EVENT_BUS_TYPE` (never read); `EVENT_BUS_MAXSIZE` went
with the in-process bus (SA-09). A `.env` that still sets
them is harmless — `extra="ignore"`.

The edge reaches the *voice* subsystem by importing it directly
([`src.voice.websocket_handler`](../../backend/src/voice/websocket_handler.py),
[`src.voice.session_manager`](../../backend/src/voice/session_manager.py)); see
[12 — Voice & telephony](12-voice-and-telephony.md).

---

## 4. Auth at the edge — who gets in

### 4.1 The rules, exactly

| Path | Credential checked | Blocked on failure? |
|------|--------------------|---------------------|
| `/internal/event` | `X-Internal-Token` header compared with `settings.INTERNAL_TOKEN` in constant time (`require_internal`) | **Yes — 401**; **503** while `INTERNAL_TOKEN` is empty or a placeholder |
| `/webhook/inbound` | None. `?client_id=` query param is read as-is | No |
| `/stream/audio`, `/stream/video` | None beyond the handshake's `client_id` — **see 4.3** | No |
| `/api/v1/*` and everything else | The route's own dependencies (`get_current_user`, `RoleChecker`) — see [04](04-auth-rbac-tenancy.md) | Per route |

```python
# backend/src/gateway/internal_event.py
def require_internal(x_internal_token: str = Header(default="")) -> None:
    if not hmac.compare_digest(x_internal_token.encode(), settings.INTERNAL_TOKEN.encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Internal-Token")
```

FastAPI resolves this dependency before it validates the body, so an
unauthenticated caller gets a 401, not a schema error.

### 4.2 What the gateway's middleware used to do

`GatewayAuthMiddleware` classified every request into a channel (`internal`,
`webhook`, `audio`/`video`, `rest`), blocked `/internal/event` without the token,
and JWT-decoded every other bearer token with a separate `JWT_SECRET` to fill a
`TenantContext` that no route read. It is deleted; the token check is the
`require_internal` dependency above.

### 4.3 The WebSocket blind spot

The HTTP middleware (`BaseHTTPMiddleware` subclasses and CORS) passes any scope
whose type is not `"http"` straight through; WebSocket handshakes have
`scope["type"] == "websocket"`. So nothing in front of the stream handlers checks
anything, and the handlers do not compensate.
[`audio_gateway.py`](../../backend/src/gateway/audio_gateway.py) reads
`token = handshake.get("token", "")` from the handshake JSON and then **never
uses the variable**. [`video_gateway.py`](../../backend/src/gateway/video_gateway.py)
does not even read it. The only gate on opening an audio or video session is that
`client_id` resolves to some non-archived entity for that company:

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
(`/mobile/ws` is different: it authenticates the access token in its first
message and closes with 4001 otherwise.)

---

## 5. The former REST proxy

Interface 1 used to be a catch-all reverse proxy in the gateway,
`@app.api_route("/{path:path}")`, forwarding everything the gateway did not serve
itself to `BACKEND_URL` (port 8000) over httpx. It is gone; the SPA's REST calls
reach the API's routers directly. What it did, and what its removal changed:

| Proxy behaviour | Now |
|-----------------|-----|
| Declared last because FastAPI matches in order — any route added below it was silently proxied and 404'd (SA-16) | No catch-all; route order does not matter |
| SSE relayed unbuffered only when the path ended in `/stream` or the client sent `Accept: text/event-stream`; otherwise buffered until a 60 s read timeout and answered 503 (SA-17) | The API streams the response itself. It sends the `Cache-Control: no-cache` and `X-Accel-Buffering: no` headers the relay used to add |
| 60 s read timeout on every other request | No application timeout; Apache's applies |
| Followed backend redirects server-side (`follow_redirects=True`), so the browser never saw one | The browser receives the redirect. Apache sets `X-Forwarded-Proto: https` on the SSL vhosts so it keeps the `https` scheme |
| Read the whole body into memory and re-sent it; copied upstream headers verbatim | Nothing in between |
| `503 {"error": "Backend unavailable"}` when port 8000 was down | Apache's 503 when the API is down |
| slowapi limit on the proxy route only | The same limit on every REST route via `SlowAPIMiddleware` |

---

## 6. Agent resolution (the former dispatcher)

[`dispatcher.py`](../../backend/src/gateway/dispatcher.py) keeps the name
`CentralDispatcher`, but since SA-09 its only job is picking the agent a
streaming session talks to. It used to drain the in-process event bus, enqueue
`process_gateway_event`, and — when arq was unreachable — run a whole AgentLoop
inside the web process. The ingress endpoints now queue their own events
([section 7](#7-queuing-inbound-events-and-internal-events)).

### 6.1 Agent resolution and its cache

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
a multi-agent tenant is whatever Postgres returns first. The same pattern
appears in `process_gateway_event`. Route deliberately by passing `entity_id` in
the webhook payload or query string.

### 6.2 Lifecycle

The API's `lifespan` calls `start()` (connect the Redis cache — optional; without
it every lookup hits Postgres) and `stop()` (close it). There is no background
task any more.

---

## 7. Queuing inbound events and internal events

### 7.1 Queued before the 202

`POST /webhook/inbound` and `POST /internal/event` build an `EventEnvelope`
and call [`queue_event`](../../backend/src/gateway/envelope.py), which enqueues
a `process_gateway_event` arq job — **before** the endpoint answers:

| Outcome | Response |
|---------|----------|
| Redis took the job | `202` with the `correlation_id` |
| Redis unreachable | `503 {"status": "unavailable", ...}` — the provider retries |
| No `client_id` (webhook) | `400` — the worker would drop a tenant-less event |

```mermaid
flowchart TB
    subgraph API["API process"]
        WH["POST /webhook/inbound handler"] --> ENV["EventEnvelope"]
        IE["POST /internal/event handler"] --> ENV
        HLP["emit_internal_event helper - API or worker"] --> ENV
        ENV --> Q["queue_event - enqueue_job process_gateway_event"]
    end
    Q -->|"job in Redis, then 202"| RQ[("Redis - arq queue")]
    Q -.->|"Redis down: 503"| X["caller retries"]
    RQ --> WORK["Arq worker - process_gateway_event"]
    WORK --> DB[("PostgreSQL")]
```

Until SA-09 (2026-09-30) the endpoints answered 202 first and published the
envelope to an `InMemoryEventBus` — an `asyncio.Queue` inside the process — from
a Starlette background task; the dispatcher drained it and enqueued the job. A
restart in between lost the event without a trace, an event published while the
dispatcher was not subscribed was counted as "dropped", a full queue (1000)
dropped events too, and when arq failed the dispatcher ran the AgentLoop
in-process, on the same event loop as live audio. The bus, its
`EVENT_BUS_MAXSIZE` setting and its counters on `/metrics/gateway` are gone.

The arq job is the durable hand-off: once it is in Redis it survives an API
restart and is retried by the worker.

### 7.2 The envelope

Everything queued is one shape,
[`EventEnvelope`](../../backend/src/gateway/envelope.py):

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
| `channel` | Which interface produced it | `"webhook"`, `"internal"` |
| `source` | Originating system | `"email"`, `"crm"`, `"github"`, `"vector_db"`, `"cron"`, `"agent:abc123"` |
| `client_id` | Tenant / company UUID string | `"3f7c…"` |
| `event_type` | Dot-namespaced type | `"new_email"`, `"github.push"`, `"timer.daily_summary"` |
| `raw_data` | Normalised payload from the strategy | provider-specific dict |
| `metadata` | Correlation, priority, request headers | `{"correlation_id": "...", "priority": 5}` |
| `id` | Correlation id — reused as the envelope id | UUID4 string |
| `timestamp` | ISO-8601 UTC at construction | `"2026-08-13T09:12:44.101+00:00"` |

`to_dict()` is what goes into the arq job; `process_gateway_event` reads it back.

### 7.3 `/internal/event` — Interface 3

A typed, authenticated endpoint for other parts of the platform to push events in.

| Field | Type | Required | Constraint |
|-------|------|----------|-----------|
| `event_type` | str | yes | dot-namespaced |
| `client_id` | str | yes | company/tenant UUID, non-empty |
| `source` | str | yes | e.g. `vector_db`, `cron`, `agent:<uuid>` |
| `payload` | dict | no | arbitrary JSON, default `{}` |
| `priority` | int | no | 1–10, default 5. Carried in `metadata` only — **nothing reads it** |
| `correlation_id` | str | no | echoed back; auto-UUID4 if omitted |

Well-known types are collected in
[`WellKnownEvents`](../../backend/src/gateway/internal_event.py):
`doc_indexed`, `timer.daily_summary`, `timer.weekly_report`, `agent.signal`,
`campaign.done`, `build.done`. These are constants only — no handler switches on
them; `process_gateway_event` treats everything except `sheet.row_inserted` the
same way.

```mermaid
sequenceDiagram
    participant SVC as Internal service
    participant EP as POST /internal/event
    participant RQ as Redis arq queue
    participant W as Arq worker

    SVC->>EP: POST /internal/event with X-Internal-Token
    EP->>EP: require_internal - constant-time compare
    alt token mismatch
        EP-->>SVC: 401
    else token ok
        EP->>EP: validate body, correlation_id = provided or uuid4
        EP->>RQ: enqueue_job process_gateway_event
        alt queued
            EP-->>SVC: 202 queued=true
        else Redis down
            EP-->>SVC: 503 queued=false
        end
        RQ->>W: process_gateway_event
    end
```

There is also a direct helper,
[`emit_internal_event`](../../backend/src/gateway/internal_event.py), that
skips HTTP and the token and calls the same `queue_event`, so it works from the
API or the worker. **Nothing calls it** yet.

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
    NORM --> CID{"client_id present"}
    CID -->|no| R400["400"]
    CID -->|yes| ENV["EventEnvelope channel=webhook"]
    ENV --> QE["queue_event - enqueue process_gateway_event"]
    QE -->|queued| R202["202 accepted with correlation_id, source, event_type"]
    QE -->|Redis down| R503["503 - provider retries"]
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

(The in-process fallback once routed CRM `lead.created` events into a
deduplicated `lead_queue`; that path was deleted with the undrained lead queue,
SA-08.)

### 8.4 Sequence — a HubSpot lead webhook end to end

```mermaid
sequenceDiagram
    participant HS as HubSpot
    participant AP as Apache
    participant GW as API
    participant ST as CRMWebhookStrategy
    participant RQ as Redis arq
    participant W as Arq worker

    HS->>AP: POST /webhook/inbound?client_id=UUID with X-HubSpot-Signature
    AP->>GW: forwarded
    GW->>ST: detect_strategy matches on x-hubspot header
    ST->>ST: validate_signature -> True, base class no-op
    ST->>ST: normalize -> event_type, phone, entity_id, properties
    GW->>RQ: enqueue_job process_gateway_event EventEnvelope
    RQ-->>GW: job stored
    GW-->>HS: 202 accepted with correlation_id
    RQ->>W: worker picks up job
    W->>W: resolve entity, create ExecutionRun, run AgentLoop
```

The `202` is returned only **after** the job is in Redis: a provider that sees it
knows the event survives an API restart. If Redis cannot take it the provider
gets a 503 and retries (SA-09). What the `202` still does not promise is that the
run succeeded — or that a retried delivery will not run twice (section 8.3).

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
    AP->>AG: ws://127.0.0.1:8000/stream/audio
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

The producer is an ordinary API route:
[`GET /api/v1/ai/executions/{execution_id}/stream`](../../backend/src/ai/router.py:324).
The browser reaches it through Apache directly; until the merge it went through
the gateway's SSE relay ([section 5](#5-the-former-rest-proxy)).

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
pub/sub — unlike the edge's in-process event bus — which is why a run
executing in the arq worker can stream to a browser attached to the API.

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
browser talks to the API (through Apache), and the API relays from Redis.

```mermaid
flowchart LR
    W["Arq worker AgentLoop"] -->|publish| RD[("Redis channel execution:run_id")]
    G["GovernanceService HITL"] -->|publish| RD
    T["TraceRecorder spans"] -->|publish| RD
    S["AIService cancel"] -->|publish| RD
    RD -->|pubsub.listen| BE["API GET /ai/executions/id/stream"]
    BE -->|text/event-stream via Apache| ES["Browser EventSource"]
    ES --> HK["useAgentEvents parse"]
    HK --> RED["executionEventReducer"]
    RED --> UI["Iteration timeline, span tree, cost panel"]
```

---

## 12. Transport comparison

| Transport | Where | Direction | Used for | Why this one |
|-----------|-------|-----------|----------|--------------|
| **REST** | `/api/v1/*` on the API | request/response | Every `/api/v1/*` call: CRUD on entities, runs, billing, config | Cacheable, debuggable, stateless. |
| **HTTP POST, fire-and-forget** | `/webhook/inbound`, `/internal/event` | inbound only, `202` | External systems and internal services triggering agents | Providers demand fast ACKs. The work is queued on arq before the 202. |
| **SSE** | `/api/v1/ai/executions/{id}/stream` | server → browser | Live execution traces, iteration timeline, HITL prompts | One-way, text-only, survives plain HTTP proxies, auto-reconnects in the browser, no extra client library. |
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
| `gateway.hirebuddha.com` | `localhost:8000` | The API. **The only vhost with WebSocket rewrite rules.** |
| `api.hirebuddha.com` | `localhost:8000` | Alias onto the API. No WS rules — WebSockets fail here. |
| `dev.hirebuddha.com` | `localhost:3000` | Dev environment. |

`streaming.hirebuddha.com` pointed at the retired port-8002 voice service, where
nothing listened; its vhosts are deleted. Both API vhosts' SSL configs set
`RequestHeader set X-Forwarded-Proto "https"`, so redirects the API builds keep
the `https` scheme (uvicorn trusts forwarded headers from `127.0.0.1`).

```mermaid
graph TB
    subgraph Internet
        U["Browser, telephony, SaaS"]
    end
    subgraph VM["Production VM"]
        AP["Apache 80 and 443"]
        FE["Vite dev/static 3000"]
        BE["API 8000"]
        WK["Arq worker"]
        RD["Redis 6379"]
        PG["Postgres 5433"]
    end

    U -->|app.hirebuddha.com| AP
    U -->|gateway.hirebuddha.com| AP
    U -->|api.hirebuddha.com| AP
    AP --> FE
    AP --> BE
    BE --> PG
    BE --> RD
    RD --> WK
```

### 13.2 The WebSocket upgrade rules

```apache
# deploy/apache/gateway.hirebuddha.com-le-ssl.conf
ProxyPreserveHost On
ProxyRequests Off
RequestHeader set X-Forwarded-Proto "https"

# ===== WebSocket Proxy (MUST come before regular proxy) =====
RewriteEngine On
RewriteCond %{HTTP:Upgrade} =websocket [NC]
RewriteRule /stream/(.*) ws://127.0.0.1:8000/stream/$1 [P,L]

RewriteCond %{HTTP:Upgrade} =websocket [NC]
RewriteRule /webhooks/voice/tata/(.*) ws://127.0.0.1:8000/webhooks/voice/tata/$1 [P,L]

RewriteCond %{HTTP:Upgrade} =websocket [NC]
RewriteRule /mobile/ws$ ws://127.0.0.1:8000/mobile/ws [P,L]

ProxyTimeout 86400

# ===== Regular HTTP Proxy =====
ProxyPass / http://localhost:8000/
ProxyPassReverse / http://localhost:8000/
```

Required modules, enabled by `setup_apache.sh`:
`proxy`, `proxy_http`, `proxy_wstunnel`, `ssl`, `rewrite`, `headers`, `remoteip`, `deflate`.

```mermaid
flowchart TD
    REQ["Request to gateway.hirebuddha.com"] --> UPG{"Upgrade header == websocket"}
    UPG -->|yes| PATH{"path matches /stream/, /webhooks/voice/tata/ or /mobile/ws"}
    PATH -->|yes| WS["RewriteRule with P flag -> mod_proxy_wstunnel -> ws://127.0.0.1:8000"]
    PATH -->|no| HTTP["falls through to ProxyPass, upgrade fails"]
    UPG -->|no| HTTP2["ProxyPass / -> http://localhost:8000/"]
    WS --> LIVE["Connection held up to ProxyTimeout 86400s"]
    HTTP2 --> RESP["Normal HTTP response"]
```

### 13.3 Pitfalls

- **`ProxyTimeout 86400`** (24 h) is the reason long calls and long SSE streams
  survive. It is set on `gateway.*` only. The `api.*` vhost has
  **no** `ProxyTimeout` and **no** WS rules — it inherits the default 60 s and will
  cut a quiet SSE stream. Use `gateway.hirebuddha.com` for anything long-lived.
- **`X-Accel-Buffering: no` does nothing here.** The SSE endpoint sets it
  ([`ai/router.py`](../../backend/src/ai/router.py)) but that is an nginx
  directive. Apache's `mod_proxy_http` streams a chunked response without
  content-length reasonably promptly, which is why SSE works; if you ever see
  events arriving in bursts, the Apache-native fix is
  `ProxyPass / http://localhost:8000/ flushpackets=on`.
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
  outside `/stream/`, `/webhooks/voice/tata/` and `/mobile/ws` will be proxied as
  plain HTTP and the upgrade will fail with a confusing 200 or 400.
- **`ProxyPreserveHost On`** means the backend sees the public hostname. Anything
  the backend builds from `request.url` will contain the public host, which is
  what you want for callback URLs.

---

## 14. Scaling and state

### 14.1 Is the edge stateless?

Mostly, but not entirely. Three things live in the API process's memory:

| State | Where | Consequence with more than one instance |
|-------|-------|-----------------------------------------|
| `CentralDispatcher` singleton (agent cache client) | [`dispatcher.py`](../../backend/src/gateway/dispatcher.py) | One per instance. Fine: the cache itself is in Redis. |
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
    LB["Load balancer"] --> G1["API instance A"]
    LB --> G2["API instance B"]

    subgraph SharedOK["Shared - scales cleanly"]
        RD[("Redis - rate limits, agent cache, arq, pubsub")]
        PG[("PostgreSQL")]
    end

    subgraph PerInstance["Per instance - not shared"]
        V1["Video sessions A"]
        V2["Video sessions B"]
    end

    G1 --> RD
    G2 --> RD
    G1 --> PG
    G2 --> PG
    G1 --- V1
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
3. **Nothing else.** Webhooks, internal events and REST are genuinely stateless
   because the handoff point is Redis or Postgres.

Today there is exactly one instance: `start_services.sh` binds a single uvicorn to
8000 and `docker-compose.yml` declares one `app` service with no `deploy.replicas`.
Running uvicorn with `--workers N` has the same effect as N instances behind one
port: a WebSocket stays on the worker that accepted it, which is fine.

### 14.3 Where affinity is required

| Path | Affinity | Why |
|------|----------|-----|
| `/api/v1/*` | none | Request/response. |
| `/webhook/inbound`, `/internal/event` | none | Handoff to Redis. |
| `/api/v1/ai/executions/{id}/stream` | none | Redis pub/sub is shared; any instance can relay. |
| `/stream/audio`, `/stream/twilio/*`, `/stream/tata/*`, `/webhooks/voice/tata/incoming` | **required for connection lifetime** | In-memory session + live LLM socket. |
| `/stream/video` | **required for connection lifetime** | `RTCPeerConnection` is process-local. |

---

## 15. Operational runbook

### 15.1 Bring it up locally

```bash
# from repo root
./start_services.sh            # API 8000, arq worker, frontend 3000
tail -f logs/backend_api.log

# or just the API
cd backend
.venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

### 15.2 Test each transport

**Health and metrics**

```bash
curl -s localhost:8000/health | jq
curl -s localhost:8000/metrics/gateway | jq
```

**REST** — a 401 without a token:

```bash
curl -i localhost:8000/api/v1/ai/entities
curl -i -H "Authorization: Bearer $TOKEN" localhost:8000/api/v1/ai/entities
```

**Webhook** — expect `202` and a `correlation_id`:

```bash
curl -i -X POST "localhost:8000/webhook/inbound?client_id=$COMPANY_UUID" \
  -H 'Content-Type: application/json' \
  -H 'X-GitHub-Event: push' \
  -d '{"repository":{"full_name":"acme/widgets"},"sender":{"login":"dev"}}'
# -> {"status":"accepted","source":"github","event_type":"github.push",...}
```

**Internal event** — check both the 401 and the 202:

```bash
curl -i -X POST localhost:8000/internal/event \
  -H 'Content-Type: application/json' \
  -d '{"event_type":"doc_indexed","client_id":"'$COMPANY_UUID'","source":"vector_db","payload":{}}'
# -> 401 {"detail":"Invalid or missing X-Internal-Token"}

curl -i -X POST localhost:8000/internal/event \
  -H "X-Internal-Token: $INTERNAL_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"event_type":"doc_indexed","client_id":"'$COMPANY_UUID'","source":"vector_db","payload":{"document_id":"d1"}}'
# -> 202
```

**SSE** — `-N` disables curl's own buffering:

```bash
curl -N "localhost:8000/api/v1/ai/executions/$RUN_ID/stream?token=$TOKEN"
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
websocat ws://localhost:8000/stream/audio
# then paste:
{"event":"connect","provider":"web","client_id":"<company-uuid>","token":"x","metadata":{"direction":"inbound"}}
# expect: {"event":"connected","session_id":"...","status":"ready","provider":"web","agent_id":"..."}
{"event":"ping"}
# expect: {"event":"pong"}
```

**WebSocket video**:

```bash
websocat ws://localhost:8000/stream/video
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
| `[Dispatcher] Redis connection established` | Normal boot. |
| `[Dispatcher] Redis unavailable, agent cache disabled` | Redis down at boot; agent lookups hit Postgres and webhooks will 503 until Redis is back. |
| `[WebhookRouter] Received <type> from source=<s> client=<id> correlation=<uuid>` | Webhook received. |
| `[Ingress] Queued webhook event <type> (<uuid>) as job <id>` | The job is in Redis; the 202 follows. |
| `[WebhookRouter] Could not queue event <uuid>` | Redis refused the enqueue; the caller got 503. |
| `[WebhookRouter] <provider> signature validation not yet configured` | Expected today; see [8.2](#82-signature-verification--what-is-actually-implemented). |
| `[process_gateway_event] No active entity for company <id>` (worker log) | Tenant has no non-archived `HierarchicalEntity`. |
| `[AudioGateway] Session <id> ready (web, agent=<id>)` | Browser audio session established. |
| `[VideoGateway] Session <id> connected (provider=web, ..., webrtc=False)` | aiortc missing or video disabled. |
| `[VideoSession] Audio track error: ...` | Almost certainly the `__mro__` bug in [10.1](#101-implemented-versus-stubbed--read-this-first). |
| `AgentLoop SSE publish failed for <event>: ...` | Redis publish failed; the run continues but the UI goes quiet. |

### 15.4 Common failures

| Symptom | Likely cause | Check |
|---------|--------------|-------|
| SSE connects then hangs forever with no events | Nothing is publishing to `execution:{run_id}` — the run finished before you subscribed, or `set_sse_redis` was never called | `redis-cli PUBLISH execution:$RUN_ID '{"type":"x"}'` and see if the curl prints it |
| SSE works on `gateway.*` but dies on `api.*` | `api.hirebuddha.com` vhost has no `ProxyTimeout` | Use the gateway hostname |
| WebSocket returns 200 HTML or 400 instead of upgrading | Path not covered by the Apache rewrite rules | `grep RewriteRule deploy/apache/gateway.hirebuddha.com-le-ssl.conf` |
| WebSocket drops after ~60 s in production | `ProxyTimeout` missing on that vhost | Add `ProxyTimeout 86400` |
| Audio WS closes with `1008 No agent found for client` | No non-archived entity for that company, or wrong `client_id` | Query `hierarchical_entities` for the company |
| Webhook returns 202 but nothing runs | The worker is not consuming, or the tenant has no active entity | `logs/arq_worker.log` for `process_gateway_event`; `/api/v1/health` |
| Webhook returns 503 | Redis is down or unreachable from the API | `redis-cli ping`; the API log shows `Could not queue event` |
| Everyone is rate limited at once | `get_remote_address` sees `127.0.0.1` for all callers behind Apache | Configure `RemoteIPHeader X-Forwarded-For` |
| Duplicate executions from one webhook | Provider retried; no idempotency | See [8.3](#83-idempotency--there-is-none) |
| Video calls silent | aiortc not installed, and the `__mro__` bug | `pip list \| grep aiortc`, then fix `video_gateway.py:202` |

---

## Key files reference

| File | Lines | What it does |
|------|-------|--------------|
| [`backend/src/main.py`](../../backend/src/main.py) | 170 | The API app: lifespan (dispatcher), middleware, and the edge routers mounted next to the REST ones. |
| [`backend/src/common/rate_limit.py`](../../backend/src/common/rate_limit.py) | 22 | The slowapi `limiter` (`RATE_LIMIT` per client IP). |
| [`backend/src/gateway/telephony_streams.py`](../../backend/src/gateway/telephony_streams.py) | 100 | The Twilio/Tata media-stream WebSockets. |
| [`backend/src/gateway/status.py`](../../backend/src/gateway/status.py) | 18 | `GET /metrics/gateway`. |
| [`backend/src/gateway/dispatcher.py`](../../backend/src/gateway/dispatcher.py) | 110 | `CentralDispatcher`: agent resolution (Redis-cached) for the audio/video handshakes. |
| [`backend/src/gateway/envelope.py`](../../backend/src/gateway/envelope.py) | 95 | `EventEnvelope` and `queue_event` — the enqueue that precedes every ingress 202. |
| [`backend/src/gateway/internal_event.py`](../../backend/src/gateway/internal_event.py) | 200 | `POST /internal/event`, `require_internal`, `InternalEvent` schema, `WellKnownEvents`, unused `emit_internal_event` helper. |
| [`backend/src/gateway/webhook_inbound.py`](../../backend/src/gateway/webhook_inbound.py) | 598 | 12 webhook strategies, `detect_strategy`, `POST /webhook/inbound`. No working signature verification. |
| [`backend/src/gateway/audio_gateway.py`](../../backend/src/gateway/audio_gateway.py) | 244 | `WS /stream/audio` handshake and provider routing. |
| [`backend/src/gateway/web_audio_adapter.py`](../../backend/src/gateway/web_audio_adapter.py) | 255 | Browser PCM16 ↔ live LLM bridge, four concurrent tasks, transcript logging. |
| [`backend/src/gateway/video_gateway.py`](../../backend/src/gateway/video_gateway.py) | 540 | `WS /stream/video` signalling, `VideoSession`, vision frame sampling, active-session registry. |
| [`backend/src/ai/router.py:324`](../../backend/src/ai/router.py:324) | — | The SSE producer: `GET /api/v1/ai/executions/{id}/stream`. |
| [`backend/src/ai/core/agent_loop_sse.py`](../../backend/src/ai/core/agent_loop_sse.py) | 80 | Internal event name → SSE `type` translation and Redis fan-out. |
| [`backend/src/ai/core/arq_jobs.py:163`](../../backend/src/ai/core/arq_jobs.py:163) | — | `process_gateway_event`, the worker side of every webhook/internal event. |
| [`frontend/src/services/events.ts`](../../frontend/src/services/events.ts) | 79 | `useAgentEvents` — the live `EventSource` hook. |
| [`frontend/src/hooks/useExecutionEvents.ts`](../../frontend/src/hooks/useExecutionEvents.ts) | 288 | Reducer turning SSE events into the Execution Detail view model. |
| [`deploy/apache/gateway.hirebuddha.com-le-ssl.conf`](../../deploy/apache/gateway.hirebuddha.com-le-ssl.conf) | 32 | The only vhost with WebSocket upgrade rules and a 24 h `ProxyTimeout`. |
| [`backend/tests/e2e/test_12_unified_gateway.py`](../../backend/tests/e2e/test_12_unified_gateway.py) | 360 | ASGI-transport tests (on the API app) for health, webhooks, internal events, the bus and strategy detection. |
| [`backend/tests/unit/test_single_port_app.py`](../../backend/tests/unit/test_single_port_app.py) | 155 | Every edge route is on the API; no catch-all; one CORS list; WebSockets untraced; rate limit and its exemptions. |

---

## Gotchas and things that surprise newcomers

- **There is no gateway process.** `src/gateway/` is a package of routers the
  API mounts; `gateway.hirebuddha.com` is the API's public name on port 8000.
- **There is no event bus any more.** Webhook and internal events go straight
  onto the arq queue before the endpoint answers; a 503 means Redis refused them.
- **`TURN_USERNAME` and `TURN_CREDENTIAL` are never read.** `priority` on
  internal events is stored and ignored.
- **Nothing authenticates `/stream/audio` or `/stream/video`.** HTTP middleware
  passes WebSockets straight through, and the handshake `token` is read into a
  variable and never validated.
- **No webhook signature is verified.** Every `validate_signature` returns `True`,
  several with an explicit TODO, and a `False` would not block the request anyway.
- **No webhook idempotency.** Provider retries create duplicate executions.
- **`@app.on_event` handlers never fire** on the API: it passes a custom
  `lifespan`. Put startup and shutdown work in `lifespan` in `main.py`.
- **Rate limiting covers every REST route** through `SlowAPIMiddleware`, except
  `/webhook/inbound` and `/internal/event` (`@limiter.exempt`) and the
  WebSockets. A module with an exempt route must not use `from __future__ import
  annotations` — FastAPI would resolve its string annotations against slowapi's
  wrapper and turn `request: Request` into a query parameter.
- **Rate limits are keyed on `127.0.0.1` in production** because no vhost sets
  `RemoteIPHeader`.
- **`X-Accel-Buffering: no` is an nginx header** and does nothing under Apache.
- **Agent selection is `LIMIT 1` with no `ORDER BY`** in three separate places.
  For multi-agent tenants, pass an explicit `entity_id`.
- **SSE has no `Last-Event-ID` and no replay.** Reconnection loses everything that
  happened while disconnected; the UI's 3-second polling is what actually keeps
  the page correct.
- **WebSockets are not traced.** The OTel ASGI instrumentation would open a span
  per message; `setup_telemetry` excludes `ws://`/`wss://` URLs.
- **aiortc is not installed**, so `/stream/video` currently only answers the
  handshake and closes. Even with it installed, the audio pipeline aborts on the
  `__mro__` line at `video_gateway.py:202`.

---

## Where to go next

- [12 — Voice, telephony & messaging](12-voice-and-telephony.md) — what happens
  to audio after the stream endpoint hands it to `TwilioStreamHandler` or the live client.
- [02 — System architecture & topology](02-system-architecture.md) — the full
  process and port map this document zooms into.
- [04 — Auth, RBAC & multi-tenancy](04-auth-rbac-tenancy.md) — the *real* auth,
  enforced by the REST routes' dependencies.
- [06 — Entities & the execution pipeline](06-execution-pipeline.md) — what
  `process_gateway_event` builds once a webhook becomes a run.
- [15 — Governance, HITL & feature flags](15-governance-and-hitl.md) — the
  `execution:{run_id}` / `hitl:{approval_id}` protocol in full.
- [16 — Frontend architecture](16-frontend.md) — where `useExecutionEvents` sits
  in the React app.
- [17 — API reference](17-api-reference.md) — the exhaustive endpoint list.
- [18 — Infrastructure, deployment & operations](18-infrastructure-and-deployment.md) —
  Apache, systemd, and the production VM.
