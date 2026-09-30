# 02. System Architecture & Topology

> **What this document covers:** every process that runs in production, which port it owns, how requests reach it, how the processes talk to each other, and how the backend Python package is layered.
> **Who should read it:** any developer before their first code change — this is the map of the territory.
> **Prerequisites:** [01 — Product overview](01-product-overview.md) for *what* the product does. This document is the *how it is wired*.

---

## Table of contents

1. [The 60-second version](#1-the-60-second-version)
2. [The runtime processes](#2-the-runtime-processes)
3. [Deployment topology](#3-deployment-topology)
4. [Subdomains and the Apache reverse proxy](#4-subdomains-and-the-apache-reverse-proxy)
5. [Backend layering and the AI-package import rules](#5-backend-layering-and-the-ai-package-import-rules)
6. [Module map of backend/src](#6-module-map-of-backendsrc)
7. [Cross-process communication](#7-cross-process-communication)
8. [Async job architecture: Arq](#8-async-job-architecture-arq)
9. [Configuration and settings](#9-configuration-and-settings)
10. [Observability](#10-observability)
11. [Error handling and resilience](#11-error-handling-and-resilience)
12. [Security architecture at the system level](#12-security-architecture-at-the-system-level)
13. [Key files reference](#key-files-reference)
14. [Gotchas and things that surprise newcomers](#gotchas-and-things-that-surprise-newcomers)
15. [Where to go next](#where-to-go-next)

---

## 1. The 60-second version

HireBuddha runs as **four long-lived processes on one virtual machine**, fronted by Apache:

| # | Process | Port | One-line job |
|---|---------|------|--------------|
| 1 | Vite dev server (React SPA) | 3000 | Serves the browser app |
| 2 | API (FastAPI) | 8000 | Every HTTP and WebSocket endpoint: REST, business logic, auth, billing, AI routers, inbound webhooks, internal events, audio/video/telephony media streams |
| 3 | Arq worker | — | Runs agent executions and cron jobs off a Redis queue |
| 4 | Docker: PostgreSQL+pgvector / Redis | 5433 / 6379 | Durable state / queue, cache, pub-sub |

Until 2026-09-30 there was a fifth: the **Unified Gateway** on port 8001, a second
FastAPI app that reverse-proxied REST to the API and served the webhook,
internal-event and media-stream endpoints itself. It is merged into the API — see
[§2.2](#22-the-former-unified-gateway--merged-into-the-api). The voice streaming
service that once ran on 8002 is deleted.

The single most important rule: **the API on port 8000 is the only backend
process that answers the outside world.** Every browser request, every webhook,
every telephony callback and media stream lands on Apache, which forwards it to
port 8000.

```mermaid
graph TB
    subgraph Internet
        BROWSER["Browser SPA"]
        TWILIO["Twilio / Tata Tele"]
        EXT["CRMs, email, social webhooks"]
    end

    APACHE["Apache 80/443 - SSL, vhosts, WS upgrade"]

    subgraph VM["Single VM"]
        FE["Vite dev server :3000"]
        API["API :8000 - REST, webhooks, WebSockets"]
        ARQ["Arq worker - no port"]
        PG[("PostgreSQL + pgvector :5433")]
        RD[("Redis :6379")]
    end

    BROWSER --> APACHE
    TWILIO --> APACHE
    EXT --> APACHE

    APACHE --> FE
    APACHE --> API
    ARQ -->|"consume queue"| RD
    API -->|"arq enqueue"| RD
    API --> PG
    ARQ --> PG
    API -->|"SSE relay via pubsub"| RD
    ARQ -->|"publish spans"| RD
```

Everything else in this document is detail on those boxes and arrows.

---

## 2. The runtime processes

[`start_services.sh`](../../start_services.sh) is the authoritative list. It does
four things in order, and the ordering matters: Docker first (everything needs
the DB), then the API, then the worker, then the frontend.

```mermaid
flowchart TD
    S["./start_services.sh"] --> C{"backend/.env exists?"}
    C -->|no| ERR["exit 1"]
    C -->|yes| D1["1. docker compose up -d db redis"]
    D1 --> D2["2. uvicorn src.main:app :8000"]
    D2 --> D3["3. python -m arq src.ai.worker.WorkerSettings"]
    D3 --> D4["4. npm run dev -- --host 0.0.0.0 :3000"]
    D4 --> DONE["Print URLs, write PID files to logs/"]
```

Each step is skipped if its port is already bound (`check_port` uses `lsof`), and
each writes a PID file into `logs/`. Steps 2 and 4 then poll for up to 30
seconds with `wait_for_service`. The Arq worker has no port, so it is detected by
`pgrep -f "arq src.ai.worker.WorkerSettings"` instead.

### 2.1 API — port 8000

* **What it is.** The one FastAPI application, built imperatively (no factory
  function) in [`backend/src/main.py`](../../backend/src/main.py). It is *not* a
  `create_app()` — the module body constructs `app`, adds middleware, then
  imports and includes the routers. The optional ones go through
  `mount_optional` ([`common/router_mounts.py`](../../backend/src/common/router_mounts.py)):
  a broken import degrades to a missing route set rather than a dead process, and
  `GET /api/v1/health` (also `GET /health`) lists the routers that failed
  (`status: degraded`, always a 200). The core routers — auth, AI, config,
  CORTEX, artifacts, campaigns, mobile (with its push socket) — are imported
  unguarded, so a broken import there stops the boot.

  ```python
  # backend/src/main.py
  app = FastAPI(title="HireBuddha Platform", version="0.2.0", lifespan=lifespan)
  app.state.limiter = limiter
  app.add_middleware(SlowAPIMiddleware)                 # inner
  app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins_list, ...)
  app.include_router(auth_router, prefix="/api/v1")
  ...
  mount_optional(app, "src.gateway.webhook_inbound")     # POST /webhook/inbound
  mount_optional(app, "src.gateway.internal_event")      # POST /internal/event
  mount_optional(app, "src.gateway.telephony_streams")   # WS /stream/twilio|tata/{id}, ...
  mount_optional(app, "src.gateway.audio_gateway")       # WS /stream/audio
  mount_optional(app, "src.gateway.video_gateway")       # WS /stream/video
  mount_optional(app, "src.gateway.status")              # GET /metrics/gateway
  ...
  setup_telemetry(app)          # last line of the file
  ```

* **How it starts.**
  `backend/.venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload`
  from `backend/`, backgrounded with `nohup`
  ([`start_services.sh`](../../start_services.sh)).
* **What it owns.** The database. Every ORM model, every service class, auth and
  RBAC, billing, the AI routers, the voice HTTP webhook router, three static
  mounts (`/uploads`, `/reports`, `/artifact`) — and, since the merge, the
  interfaces that were the gateway's:

  | Interface | Path | Handled by |
  |-----------|------|-----------|
  | Domain REST API | `/api/v1/*` | the API's own routers (no proxy any more) |
  | Unified webhook receiver | `POST /webhook/inbound` | [`gateway/webhook_inbound.py`](../../backend/src/gateway/webhook_inbound.py) |
  | Internal event endpoint | `POST /internal/event` | [`gateway/internal_event.py`](../../backend/src/gateway/internal_event.py) |
  | Telephony media streams | `WS /stream/twilio/{id}`, `WS /stream/tata/{id}`, `WS /webhooks/voice/tata/incoming` | [`gateway/telephony_streams.py`](../../backend/src/gateway/telephony_streams.py) |
  | Bidirectional audio | `WS /stream/audio` | [`gateway/audio_gateway.py`](../../backend/src/gateway/audio_gateway.py) |
  | Bidirectional video | `WS /stream/video` | [`gateway/video_gateway.py`](../../backend/src/gateway/video_gateway.py) |
  | Mobile push socket | `WS /mobile/ws` | [`mobile/push_gateway.py`](../../backend/src/mobile/push_gateway.py) |
  | Edge counters | `GET /metrics/gateway` | [`gateway/status.py`](../../backend/src/gateway/status.py) |

* **On startup** its `lifespan` starts the
  [`CentralDispatcher`](../../backend/src/gateway/dispatcher.py) — today only the
  Redis-cached agent lookup the audio/video handshakes use.
* **What it talks to.** PostgreSQL (SQLAlchemy async), Redis (job enqueue, SSE
  pub-sub, the rate-limit counters, the mobile call-control channels), LLM
  providers over HTTPS.
* **If it dies.** Everything public goes down: the SPA, all webhooks, all live
  audio. Runs already in the worker keep going; their SSE streams are lost until
  the API is back. Webhooks it had acknowledged are safe: a 202 is sent only after
  the job is in Redis (SA-09).

### 2.2 The former Unified Gateway — merged into the API

Until 2026-09-30 `backend/src/gateway/app.py`
was a second FastAPI app on port **8001**: the public front door. It served the
webhook, internal-event and media-stream interfaces above itself and forwarded
everything else to the API with a catch-all `/{path:path}` httpx reverse proxy.
That cost a second process, a second hop and a set of traps, all gone with it:

| What the gateway had | What replaced it |
|----------------------|------------------|
| Catch-all proxy — any route declared after it was unreachable (SA-16); SSE relayed without a read timeout only if the path ended in `/stream` (SA-17); a 60 s timeout on everything else | Nothing: the routes are the API's own |
| Its own settings class `UnifiedGatewaySettings`, with a `DATABASE_URL` default on the wrong port (SA-03) and a `JWT_SECRET` that had to match the API's `SECRET_KEY` | `common.config.Settings` only |
| Its own CORS list (`CORS_ORIGINS`), next to the API's hardcoded one (SA-19) | One list: `settings.CORS_ORIGINS` |
| A slowapi limit of `RATE_LIMIT` per client IP on proxied traffic | The same limit on the API ([`common/rate_limit.py`](../../backend/src/common/rate_limit.py)); webhooks and internal events still exempt |
| `GatewayAuthMiddleware` — blocked `/internal/event` without the token, JWT-decoded everything else for logging nothing read | `require_internal`, a dependency on the one route that needs it |
| `GET /health` | `GET /health`, same body as `GET /api/v1/health` |
| No OpenTelemetry (SA-10, gateway half) | The API's instrumentation, WebSockets excluded |

An **older, superseded gateway** (`gateway/main.py` + `gateway/config.py`, a pure
httpx proxy — SA-11) and the **voice streaming service** (`voice/main.py`, port
8002 — SA-12) were deleted at the same time, with `voice/transcript_api.py`, which
only the 8002 app mounted and which had no authentication; call transcripts are
served by `GET /api/v1/streaming/voice-sessions/{id}`.

### 2.3 Arq worker

* **What it is.** A queue consumer, not a web server. Its entrypoint module is
  [`backend/src/ai/worker.py`](../../backend/src/ai/worker.py) — deliberately
  small, containing only `WorkerSettings` and cron registration, because arq
  requires them at module level for worker discovery.
* **How it starts.**
  `backend/.venv/bin/python -m arq src.ai.worker.WorkerSettings`
  ([`start_services.sh`](../../start_services.sh)).
* **What it owns.** Long-running agent executions. When you POST
  `/api/v1/execute`, the API creates a row and returns immediately; the worker is
  what actually drives [`AgentLoop.run()`](../../backend/src/ai/core/agent_loop.py).
  It also owns the cron jobs (see [§8](#8-async-job-architecture-arq)).
* **What it talks to.** Redis (dequeue), PostgreSQL (own sessions — never the
  request-scoped `get_db()`), LLM providers, and Redis again to publish trace
  spans that the SSE stream relays.
* **If it dies.** The API still accepts executions; runs sit in `PENDING`
  forever. Nothing surfaces an error to the user. This is the most common
  "the platform looks broken but nothing is logging" failure — always check
  `logs/arq_worker.log` first.

### 2.4 Frontend — port 3000

* **What it is.** A React 18 + TypeScript SPA served by the **Vite dev server**,
  even in production. `npm run dev` maps to `vite`
  ([`frontend/package.json`](../../frontend/package.json)). There is a `build`
  script, but the deployment scripts do not use it.
* **How it starts.** `npm run dev -- --host 0.0.0.0` from `frontend/`
  ([`start_services.sh`](../../start_services.sh)).
* **Notable config** in [`vite.config.ts`](../../frontend/vite.config.ts):
  `hmr: false` (hot reload deliberately disabled),
  `allowedHosts: ["dev.hirebuddha.com", "app.hirebuddha.com"]`, and a dev proxy
  sending `/api`, `/reports`, `/artifact` to `http://gateway.hirebuddha.com`
  (the hostname is unchanged; Apache now forwards it to 8000).
* **If it dies.** Only the UI. All APIs keep serving.

### 2.5 PostgreSQL + Redis (Docker)

Defined in [`backend/docker-compose.yml`](../../backend/docker-compose.yml):

| Service | Image | Container | Host port | Notes |
|---------|-------|-----------|-----------|-------|
| `db` | `pgvector/pgvector:pg15` | `hirebuddha-db` | **5433** → 5432 | Named volume `postgres_data`. The non-standard host port is why `DATABASE_URL` says `5433`. |
| `redis` | `redis:7-alpine` | `hirebuddha-redis` | 6379 | Named volume `redis_data`. |

The same compose file *also* declares an `app` service that builds the
[`backend/Dockerfile`](../../backend/Dockerfile) and serves the API on 8000.
**`start_services.sh` never brings it up** — it runs `docker compose up -d db
redis` and then launches the Python processes on the host from `backend/.venv`.
The containerised app path is an alternative that is not the deployed one.

If Postgres dies: everything fails, loudly. If Redis dies: job enqueue fails —
executions error, and the webhook and internal-event endpoints answer 503 so the
caller retries (see [§7](#7-cross-process-communication)) — SSE streams go silent,
and the rate limiter falls back to counting in process memory.

### 2.6 One more "worker" that is not a process

[`ai/campaign_worker.py`](../../backend/src/ai/campaign_worker.py) is **not** a
separate process. It defines three coroutines (`execute_campaign_task`,
`pause_campaign_task`, `stop_campaign_task`) that are imported into
`WorkerSettings.functions` and run inside the same Arq worker.

There used to be a second, `ai/lead_queue_worker.py` — a 5-second poller meant to
dial CRM leads from the `lead_queue` table. Nothing ever started or registered
it, and the only producer was the dispatcher's in-process fallback (when arq was
unreachable); outbound calls from CRM/Sheets rows go through campaigns. It was
deleted with `lead_queue_service.py` on 2026-09-30 (SA-08). The `lead_queue`
table and its model remain.

---

## 3. Deployment topology

```mermaid
graph TB
    subgraph EXT["External"]
        USER["Browser"]
        TEL["Twilio / Tata Tele"]
        HOOK["CRM / email / social webhooks"]
        SVC["Internal microservices and crons"]
    end

    subgraph EDGE["Apache 2 - ports 80 and 443"]
        VH1["app.hirebuddha.com"]
        VH2["dev.hirebuddha.com"]
        VH3["gateway.hirebuddha.com"]
        VH4["api.hirebuddha.com"]
        SEC["hirebuddha-security.conf - headers, IP blocks, mod_evasive"]
    end

    subgraph HOST["Host processes - backend/.venv and npm"]
        FE["Vite dev server :3000"]
        API["API :8000 - src.main:app"]
        WK["Arq worker - src.ai.worker.WorkerSettings"]
    end

    subgraph DOCKER["Docker compose - db and redis only"]
        PG[("hirebuddha-db - pgvector pg15 :5433")]
        RD[("hirebuddha-redis - redis 7 :6379")]
    end

    subgraph OPT["Optional - docker-compose.observability.yml"]
        JAEGER["Jaeger :16686 OTLP :4317"]
        PROM["Prometheus :9090"]
        GRAF["Grafana :3000 in-container"]
    end

    USER --> VH1
    USER --> VH2
    TEL --> VH3
    HOOK --> VH3
    SVC --> VH3
    SEC -.applies to all.-> VH1

    VH1 --> FE
    VH2 --> FE
    VH3 --> API
    VH4 --> API

    FE -->|"browser XHR to gateway host"| VH3
    API --> PG
    API --> RD
    WK --> RD
    WK --> PG
    API -->|"OTLP spans"| JAEGER
    PROM -->|"scrape :8000/metrics"| API
```

### Process, port, command, log

| Process | Port | Entrypoint command (cwd) | Log file | PID file |
|---------|------|--------------------------|----------|----------|
| API | 8000 | `backend/.venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload` (`backend/`) | `logs/backend_api.log` | `logs/backend_api.pid` |
| Arq worker | — | `backend/.venv/bin/python -m arq src.ai.worker.WorkerSettings` (`backend/`) | `logs/arq_worker.log` | `logs/arq_worker.pid` |
| Frontend (Vite) | 3000 | `npm run dev -- --host 0.0.0.0` (`frontend/`) | `logs/frontend.log` | `logs/frontend.pid` |
| PostgreSQL + pgvector | 5433 | `docker compose up -d db` (`backend/`) | `docker logs hirebuddha-db` | — |
| Redis | 6379 | `docker compose up -d redis` (`backend/`) | `docker logs hirebuddha-redis` | — |

Shutdown is [`stop_services.sh`](../../stop_services.sh), which kills by PID
file, then force-kills by port (`lsof -t -i:$port`), then `pkill -f uvicorn`
(which also stops a gateway an older start script left on 8001), then `docker
compose down`. Note that `docker compose down` removes the containers but **not**
the named volumes, so data survives a stop/start cycle.

### Provisioning a fresh VM

[`setup_production_vm.sh`](../../setup_production_vm.sh) is an eight-step Ubuntu
22.04/24.04 bootstrap: apt essentials → Python 3.12 (deadsnakes PPA) → Poetry →
Node 20 → Docker CE → `python3 -m venv .venv` + `poetry install` → `npm install
--legacy-peer-deps` → `cp .env.example .env`. It then prints the manual
follow-ups: edit `.env`, `docker compose up -d db redis`, `alembic upgrade head`,
`python db-scripts/seed_admin_user.py`, `./start_services.sh`.

Note the Python-version split: the VM script installs **3.12**, `pyproject.toml`
declares `python = "^3.11"`, and [`backend/Dockerfile`](../../backend/Dockerfile)
uses `python:3.11-slim`.

Apache is set up separately by
[`deploy/apache/setup_apache.sh`](../../deploy/apache/setup_apache.sh) (run as
root), which installs `apache2` + `libapache2-mod-evasive` and enables
`proxy`, `proxy_http`, **`proxy_wstunnel`**, `ssl`, `rewrite`, `headers`,
`remoteip`, `deflate` — `proxy_wstunnel` and `rewrite` are what make WebSockets
work at all.

Backups: [`deploy/backup/db_backup.sh`](../../deploy/backup/db_backup.sh) does a
gzipped `pg_dump` against `localhost:5433/hirebuddha` with 90-day retention;
[`setup_cron.sh`](../../deploy/backup/setup_cron.sh) registers it at
`0 2 1 * *` (monthly, 02:00 on the 1st).

---

## 4. Subdomains and the Apache reverse proxy

Four hostnames, each with a plain-HTTP vhost that 301-redirects to HTTPS and a
`-le-ssl.conf` companion holding the real proxy config plus Let's Encrypt certs.

| Hostname | Proxies to | WebSocket rewrites | Cert |
|----------|-----------|--------------------|------|
| `app.hirebuddha.com` | `http://localhost:3000/` | none | own cert |
| `dev.hirebuddha.com` | `http://localhost:3000/` | none | own cert |
| `gateway.hirebuddha.com` | `http://localhost:8000/` | `/stream/*`, `/webhooks/voice/tata/*`, `/mobile/ws` | own cert |
| `api.hirebuddha.com` | `http://localhost:8000/` | **none** | reuses the `gateway.hirebuddha.com` cert |

`streaming.hirebuddha.com` pointed at the retired voice service on 8002, where
nothing listened (SA-02, SA-13); both of its vhost files are deleted.
`gateway.hirebuddha.com` keeps its name — the SPA, the mobile app and every
telephony callback already use it — and is now answered by the API directly.

```mermaid
flowchart LR
    subgraph A["Apache :443"]
        R1["app / dev"]
        R2["gateway / api"]
    end
    R1 --> P3000[":3000 Vite"]
    R2 --> P8000[":8000 API"]
```

Both SSL API vhosts set `RequestHeader set X-Forwarded-Proto "https"`. Apache
talks plain HTTP to port 8000; uvicorn trusts forwarded headers from
`127.0.0.1`, so a redirect the API builds (FastAPI's trailing-slash redirect,
say) keeps the `https` scheme. The gateway used to follow such redirects itself,
server-side, so the browser never saw them.

### How the WebSocket upgrade is handled

Apache's `ProxyPass` cannot upgrade an HTTP connection to a WebSocket, so the
`gateway.` vhost does it with a `mod_rewrite` proxy rule placed *before* the
plain `ProxyPass`:

```apache
# deploy/apache/gateway.hirebuddha.com-le-ssl.conf
RewriteEngine On
RewriteCond %{HTTP:Upgrade} =websocket [NC]
RewriteRule /stream/(.*) ws://127.0.0.1:8000/stream/$1 [P,L]

RewriteCond %{HTTP:Upgrade} =websocket [NC]
RewriteRule /webhooks/voice/tata/(.*) ws://127.0.0.1:8000/webhooks/voice/tata/$1 [P,L]

RewriteCond %{HTTP:Upgrade} =websocket [NC]
RewriteRule /mobile/ws$ ws://127.0.0.1:8000/mobile/ws [P,L]

ProxyTimeout 86400
ProxyPass / http://localhost:8000/
```

Reading it piece by piece: `RewriteCond %{HTTP:Upgrade} =websocket` fires only
when the client actually sent `Upgrade: websocket`. The `[P]` flag means "proxy
this", and because the target scheme is `ws://` Apache routes it through
`mod_proxy_wstunnel`. `[L]` stops rule processing so the generic `ProxyPass`
never sees the request. `ProxyTimeout 86400` (24 hours) keeps a long call from
being cut off by the default 60-second proxy timeout.

```mermaid
sequenceDiagram
    participant T as Twilio
    participant A as Apache :443
    participant API as API :8000

    T->>A: "GET /stream/twilio/abc  Upgrade: websocket"
    A->>A: "RewriteCond HTTP:Upgrade == websocket -> match"
    A->>API: "ws://127.0.0.1:8000/stream/twilio/abc via mod_proxy_wstunnel"
    API-->>A: "101 Switching Protocols"
    A-->>T: "101 Switching Protocols"
    loop bidirectional audio frames
        T->>API: media frames
        API->>T: audio frames
    end
```

If `mod_proxy_wstunnel` is missing or the rewrite is absent, Apache falls back to
the plain HTTP `ProxyPass`, FastAPI sees a normal GET on a WebSocket route and
returns 404 — which surfaces as **Twilio error 31920, WebSocket Handshake
Error**.

### Global security config

[`hirebuddha-security.conf`](../../deploy/apache/hirebuddha-security.conf) is
enabled with `a2enconf` and applies to every vhost:

| Layer | What it does |
|-------|--------------|
| Response headers | `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `X-XSS-Protection`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy: camera=(), microphone=(self), geolocation=()`; unsets `X-Powered-By` and `Server` |
| IP blocklist | 24 hardcoded `Require not ip` entries inside `<Location "/">`, gathered from two log-analysis passes |
| Path blocks | `<LocationMatch>` denies for `.php`, dotfiles, `.env` anywhere, WordPress paths, phpMyAdmin/PHPUnit, VoIP provisioning paths, `/uploads`, archive extensions, `anthropic.json`/`openai.json`/`secrets.py` |
| Rewrite blocks | path traversal (`..`), the `CONNECT` method, `allow_url_include`/`php://input` query strings |
| `mod_evasive` | `DOSPageCount 15` / `DOSSiteCount 100` per second, 300-second block, whitelists `127.0.0.1`, `10.160.0.*`, `172.21.0.*` |
| Size limits | `LimitRequestBody 10485760` (10 MB), `LimitRequestFields 100`, `LimitRequestLine 8190` |

The 10 MB body limit is the one that bites: any upload larger than that is
rejected by Apache before FastAPI is involved.

---

## 5. Backend layering and the AI-package import rules

### 5.1 The layer stack

```mermaid
graph TB
    subgraph L1["Layer 1 - transport"]
        RT["Routers - src/**/router.py, src/ai/api/admin.py"]
        WS["WebSocket handlers - src/voice, src/gateway"]
    end
    subgraph L2["Layer 2 - services"]
        SV["Domain services - AIService, CampaignService, BillingService, ConfigService"]
    end
    subgraph L3["Layer 3 - the AI kernel"]
        LOOP["core/agent_loop.py - AgentLoop"]
        SUP["planning, memory, meta, governance, llm, tools"]
    end
    subgraph L4["Layer 4 - persistence"]
        ORM["src/ai/orm, src/auth/models, src/billing/billing_models"]
        DB["src/common/database.py - engine, AsyncSessionLocal"]
    end
    PG[("PostgreSQL + pgvector")]

    RT --> SV
    WS --> SV
    SV --> LOOP
    SV --> ORM
    LOOP --> SUP
    LOOP --> ORM
    SUP --> ORM
    ORM --> DB
    DB --> PG
```

The kernel sits **below** the service layer, not beside it. A router never
touches `AgentLoop`; it calls a service, and the service either does DB work or
enqueues an Arq job that eventually constructs an `AgentLoop` in the worker
process. The only place `AgentLoop` is instantiated is
[`core/arq_jobs.py`](../../backend/src/ai/core/arq_jobs.py) and the dispatcher's
in-process fallback.

### 5.2 The lint that enforces the shape

[`backend/scripts/lint_ai_layout.py`](../../backend/scripts/lint_ai_layout.py) is
271 lines of real, executable architecture policy. It exits non-zero on
violation and prints one line per problem. It enforces six rules:

```mermaid
flowchart TD
    START["lint_ai_layout.py"] --> R1["1. Top-level allow-list under src/ai/"]
    START --> R2["2. Per-package line caps"]
    START --> R3["3. Forbidden imports and aliases"]
    START --> R4["4. Comment-narration ban"]
    START --> R5["5. Canary-label ban"]
    START --> R6["6. tools/ root must hold only the shell"]
    R1 --> OUT{"any violations?"}
    R2 --> OUT
    R3 --> OUT
    R4 --> OUT
    R5 --> OUT
    R6 --> OUT
    OUT -->|yes| FAIL["exit 1"]
    OUT -->|no| PASS["exit 0"]
```

**Rule 1 — top-level allow-list.** Only `__init__.py`, `worker.py`, `README.md`
and `ONBOARDING.md` are permanently allowed directly under `backend/src/ai/`.
Everything else there lives on a `TRANSITIONAL_TOPLEVEL` set of 32 modules
(`service.py`, `router.py`, `step_executor.py`, the campaign/artifact/lead-queue/
social/email/reports modules …) that Track 1 is meant to relocate into
`services/`, `orm/` and `schemas/`. **You cannot add a new file at that level** —
put it in a subpackage.

**Rule 2 — per-package line caps.** From `MAX_LINES`:

| Package | Cap | Why that number |
|---------|-----|-----------------|
| `core/` | 1500 | `agent_loop.py` is 1480 (loop plus suspend/resume) |
| `planning/` | 700 | |
| `memory/` | 1200 | `cortex_service.py` is 1117 |
| `meta/` | 900 | `platform_schema_compiler.py` is 839 |
| `governance/` | 600 | |
| `tools/` | 1000 | |
| `llm/` | 800 | |
| `shared/` | 400 | |

The comment above the dict is explicit that these are "HEAD reality plus a small
buffer", and names lower post-programme targets (core 600, memory 800, meta 800,
tools 1000, llm 800). So a cap is a ratchet, not a budget: never raise one.

**Rule 3 — forbidden imports and aliases.**

```python
# backend/scripts/lint_ai_layout.py
FORBIDDEN_IMPORT_PATTERNS: list[str] = [
    "from src.ai.worker import ",
    "import src.ai.worker",
]
FORBIDDEN_ALIAS_PATTERNS: list[str] = [
    " as CortexService",       # the CortexRouter alias dance — Track 0 killed it
]
```

Nothing may import from `worker.py` — it is a leaf entrypoint, and importing it
would drag arq bootstrapping into unrelated modules. Import the canonical
location (`src.ai.core.arq_jobs`) instead. The alias ban is escapable if the file
contains the literal string `Backwards-compat alias` or `DEPRECATED`.

**Rule 4 — comment-narration ban** (`COMMENT_NARRATION_MODE = "error"`). Comments
matching `# Phase \d+`, `# Fix X:`, `# RACE-\d+`, `# Ph-X`, `# Gap #\d` are
violations. The rationale in the file: historical narrative confuses new readers;
rewrite the rule as an invariant ("MUST run before commit() to …"). The matcher
tracks triple-quoted blocks so docstrings and prompt templates do not trip it.

**Rule 5 — canary-label ban** (`CANARY_LABEL_MODE = "error"`). No filename or
source line under `src/ai/` may contain `p11`, `P11` or `phase11`. Alembic
migrations are skipped because renaming applied revisions is unsafe. The
one-release redirect shims outside the tree (`/api/v1/ai/phase11/*` in `main.py` and
`/admin/phase11/*` in the SPA router) were removed on 2026-09-29 (PO-16).

**Rule 6 — `tools/` root.** Only `__init__.py`, `base.py`, `resilience.py` and
`README.md` may sit at `src/ai/tools/`. Every concrete tool lives in a
subpackage (`core/`, `crm/`, `documents/`, `email/`, `mcp/`, `media/`, `meta/`,
`sandbox/`, `social/`).

Run it manually with `python backend/scripts/lint_ai_layout.py`.

---

## 6. Module map of `backend/src/`

| Package | Purpose | Key files |
|---------|---------|-----------|
| `common/` | Cross-cutting infrastructure shared by the API and the worker. | [`config.py`](../../backend/src/common/config.py) (the one `Settings` object), [`database.py`](../../backend/src/common/database.py) (`engine`, `AsyncSessionLocal`, `get_db`), [`job_queue.py`](../../backend/src/common/job_queue.py) (arq connection + `enqueue_job`), [`rate_limit.py`](../../backend/src/common/rate_limit.py), [`router_mounts.py`](../../backend/src/common/router_mounts.py), [`security.py`](../../backend/src/common/security.py), [`telemetry.py`](../../backend/src/common/telemetry.py), `email.py`, `genai_factory.py` |
| `auth/` | Users, companies, partners, RBAC dependencies, onboarding wizard. | `models.py`, `router.py`, `dependencies.py`, `company_router.py`, `partner_router.py`, `user_router.py`, `profile_router.py`, `onboarding_router.py` |
| `billing/` | SKU costing, credit wallets, admin cron endpoints. | `billing_models.py`, `billing_service.py`, `credit_service.py`, `credits_router.py`, `cron_router.py` (`/api/v1/cron/*`, `app_admin` only), `cron_service.py` |
| `config/` | Admin-managed integration registry and per-task model defaults. | `models.py` (`ModelTaskDefault`, `TASK_TYPES`), `service.py`, `router.py`, `schemas.py` |
| `gateway/` | Inbound events and real-time media — routers the API mounts (there is no gateway app any more). | `webhook_inbound.py`, `internal_event.py`, `envelope.py`, `telephony_streams.py`, `audio_gateway.py`, `video_gateway.py`, `web_audio_adapter.py`, `dispatcher.py`, `status.py` |
| `voice/` | Telephony, WhatsApp, live-audio session handling. | `webhook_router.py` (1.4k lines of Twilio/Tata/WhatsApp HTTP webhooks), `public_urls.py` (the stream and callback URLs handed to providers), `websocket_handler.py` (the biggest file in the repo), `session_manager.py`, `phone_number_router.py`, `gemini_live.py`, `azure_realtime.py`, `call_guards.py`, `usage_logger.py` |
| `ai/core/` | The agent kernel: control loop and its layers. | `agent_loop.py` (1500 lines), `agent_state.py`, `budget.py`, `perceiver.py`, `strategist.py`, `observer.py`, `reflector.py`, `arq_jobs.py`, `trace.py`, `events.py`, `agent_loop_sse.py`, `feature_flags.py`, `executors/`, `reasoning/` |
| `ai/planning/` | Plan generation, critics, retry policy, cost estimation. | `plan_generator.py`, `planner_service.py`, `critic_pipeline.py`, `supervisor_critic.py`, `goal_guard.py`, `retry_strategies.py`, `cost_estimator.py`, `critic_calibration.py`, `plan_style_bandit.py`, `step_health_record.py` |
| `ai/memory/` | CORTEX trees, RAG, embeddings, the dreaming pipeline. | `cortex_service.py`, `cortex_models.py`, `cortex_router.py`, `knowledge_tree_service.py`, `episodic_tree_service.py`, `intelligence_tree_service.py`, `experience_tree_service.py`, `embedding_service.py`, `graph_service.py`, `dreaming_engine.py` |
| `ai/meta/` | Meta-Agent board, tool synthesis, anti-sprawl, skill library. | `meta_intelligence_tree.py`, `skill_library.py`, `tool_synthesis_pipeline.py`, `tool_red_team.py`, `tool_validator.py`, `platform_schema_compiler.py`, `prompt_evolution.py`, `anti_sprawl.py`, `board/` |
| `ai/governance/` | Cost gates, HITL, rate limiting. | `governance_service.py` (credit circuit breaker, child credit gate), `rate_limiter.py` (Redis sliding window), `tool_cost_resolver.py` |
| `ai/llm/` | Provider adapters behind one router. | `router.py` (`LLMRouter`), `base.py`, `types.py`, `gemini_adapter.py`, `anthropic_adapter.py`, `azure_adapter.py` |
| `ai/tools/` | Tool registry shell plus nine tool subpackages. | Root: `base.py`, `resilience.py`. Subpackages: `core/` (search, scraper, calculator, file_writer), `documents/`, `email/`, `crm/`, `media/`, `mcp/`, `meta/`, `sandbox/`, `social/` (17 platform adapters) |
| `ai/orm/` | SQLAlchemy models for the AI domain. | `entity.py`, `execution.py`, `memory.py`, `document.py`, `tools.py`, `trace.py`, `trust.py`, `usage.py` |
| `ai/schemas/` | Pydantic request/response and internal contracts. | `entity.py`, `execution.py`, `planning.py`, `capabilities.py`, `governance.py`, `io_contract.py`, `reasoning.py`, `enums.py` |
| `ai/services/` | Extracted service modules (post-restructure landing zone). | `cost_attribution.py`, `attributed_usage.py` |
| `ai/shared/` | Tiny cross-package helpers. | `json_utils.py`, `text_utils.py` |
| `ai/api/` | Kernel admin/debug HTTP surface. | `admin.py` — everything under `/api/v1/ai/admin/*` |
| `ai/` (top level) | The 32 transitional modules the lint tolerates. | `service.py` (60 kB `AIService`), `router.py`, `step_executor.py`, `tool_executor.py`, `campaign_*`, `artifact_*`, `reports_*`, `social_*`, `email_*`, `lead_queue_model.py` |

---

## 7. Cross-process communication

Three distinct mechanisms, plus a shared secret. Knowing which one a feature
uses tells you where to look when it breaks.

```mermaid
graph LR
    SPA["Browser SPA"]
    API["API :8000"]
    WK["Arq worker"]
    RD[("Redis")]
    EXT["External systems"]

    SPA -->|"HTTPS REST"| API
    SPA -->|"SSE - text/event-stream"| API
    EXT -->|"HTTP webhook + X-Internal-Token"| API
    EXT -->|"WebSocket audio"| API
    API -->|"arq enqueue_job"| RD
    RD -->|"dequeue"| WK
    WK -->|"PUBLISH execution:run_id"| RD
    RD -->|"SUBSCRIBE"| API
```

| Mechanism | Where | Notes |
|-----------|-------|-------|
| Arq job queue | Redis sorted set, consumed by the worker | The only durable hand-off between the web tier and the execution tier. Producers enqueue through [`common/job_queue.py`](../../backend/src/common/job_queue.py); inbound webhooks and internal events through [`gateway/envelope.py`](../../backend/src/gateway/envelope.py), before their 202. |
| Redis pub-sub | Channel `execution:{run_id}` (per-run trace/SSE), `agent.events` (global telemetry), `voice:session:{id}:control` and `mobile:user:{id}:push` (mobile dialer) | Producers: [`trace.py:251`](../../backend/src/ai/core/trace.py:251), [`agent_loop_sse.py:75`](../../backend/src/ai/core/agent_loop_sse.py:75), [`events.aevent`](../../backend/src/ai/core/events.py:241), [`mobile/realtime.py`](../../backend/src/mobile/realtime.py). Consumers: the SSE endpoint, the stream handler, the push socket. |
| Internal token | Header `X-Internal-Token`, checked by `require_internal` in [`internal_event.py`](../../backend/src/gateway/internal_event.py) | Only `POST /internal/event` takes it; compared in constant time with `INTERNAL_TOKEN`. |

### 7.1 Sequence: an HTTP execute request that ends up in the worker

```mermaid
sequenceDiagram
    participant B as Browser
    participant A as Apache
    participant API as API :8000
    participant PG as PostgreSQL
    participant R as Redis
    participant W as Arq worker

    B->>A: "POST /api/v1/execute  Bearer JWT"
    A->>API: proxy to localhost:8000
    API->>API: "CORSMiddleware"
    API->>R: "slowapi rate-limit count per client IP"
    API->>API: "get_current_user - user, company, 403 if suspended"
    API->>PG: "INSERT execution_runs status=PENDING"
    API->>R: "enqueue_job run_execution_recursive run_id"
    API-->>B: "200 - run created, still PENDING"

    Note over W,R: asynchronously, in a different process
    W->>R: dequeue job
    W->>PG: "load run + entity, guard against ghost or terminal run"
    W->>W: "bind TraceRecorder via set_recorder"
    W->>W: "AgentLoop.run run_id"
    W->>R: "PUBLISH execution:run_id  span_open / span_close"
    W->>PG: "INSERT execution_trace_events, UPDATE run status"
```

The enqueue itself is one line in
[`ai/service.py`](../../backend/src/ai/service.py):

```python
# backend/src/ai/service.py
await enqueue_job("run_execution_recursive", str(execution.id))
```

`enqueue_job` and `arq_pool` live in
[`common/job_queue.py`](../../backend/src/common/job_queue.py). Every producer and
the worker build their arq connection there, with `RedisSettings.from_dsn(REDIS_URL)`
— host, port, password, TLS and database index. Before SA-04/SA-05 three enqueues
used `RedisSettings()` (arq's `localhost:6379`, whatever `REDIS_URL` said) and the
worker and campaign routes parsed the URL by hand, keeping only host and port.

On the worker side, `run_execution_recursive` runs two guards before doing any
work — both worth knowing because they explain "my job silently did nothing":

1. **Ghost-run guard** — if the run row or its entity is gone (or the entity is
   `DELETED`), it returns cleanly instead of raising, so arq stops retrying.
2. **Idempotency guard** — if the run is already `COMPLETED` / `FAILED` /
   `PARTIAL_COMPLETE` / `CANCELLED`, it returns without re-driving the engine.
   The comment is explicit about why: re-running would **re-settle billing on a
   run that already paid**.

### 7.2 Sequence: an inbound Twilio call

```mermaid
sequenceDiagram
    participant T as Twilio
    participant A as Apache
    participant API as API :8000
    participant PG as PostgreSQL
    participant LLM as Gemini Live

    T->>A: "POST /webhooks/voice/twilio/incoming - form data"
    A->>API: proxy
    API->>PG: "NumberRouter.find_customer_by_number To"
    API->>PG: "CreditService.get_balance - reject below 0.10 USD"
    API->>PG: "SessionManager.create_voice_session"
    API-->>T: "TwiML with Connect Stream url=stream_url(/stream/twilio/session_id)"

    T->>A: "GET /stream/twilio/session_id  Upgrade: websocket"
    A->>API: "ws://127.0.0.1:8000/... via mod_proxy_wstunnel"
    API->>API: "TwilioStreamHandler websocket, session_id, db"
    API->>LLM: open live audio session
    loop conversation
        T->>API: mu-law media frames
        API->>LLM: PCM audio
        LLM->>API: audio response
        API->>T: mu-law frames
    end
    T->>A: "POST /webhooks/voice/twilio/status"
    A->>API: proxy
    API->>PG: finalise session, log usage
```

The HTTP webhook ([`voice/webhook_router.py`](../../backend/src/voice/webhook_router.py),
mounted with `prefix="/webhooks/voice"`) and the WebSocket
([`gateway/telephony_streams.py`](../../backend/src/gateway/telephony_streams.py))
are different code but, since the merge, the same process. The URL handed to
Twilio (and Tata's `wss_url`) is built by
[`voice/public_urls.py`](../../backend/src/voice/public_urls.py) from
`STREAMING_HOST` + `STREAMING_PROTOCOL`:

```python
# backend/src/voice/public_urls.py
def stream_url(path: str) -> str:
    return f"{settings.STREAMING_PROTOCOL}://{settings.STREAMING_HOST}{path}"

def callback_url(path: str) -> str:          # Twilio TwiML / status callbacks
    scheme = "https" if settings.STREAMING_PROTOCOL == "wss" else "http"
    return f"{scheme}://{settings.STREAMING_HOST}{path}"
```

The defaults (`localhost:8000`, `ws`) are this API on a local stack. Production
sets `STREAMING_HOST=gateway.hirebuddha.com` and `STREAMING_PROTOCOL=wss` in
`backend/.env`. Before SA-01 the default was the retired voice service on 8002,
and seven call sites each repeated the fallback.

WebSocket connections are **not traced** by OpenTelemetry
(`excluded_urls="^wss?://"` in [`common/telemetry.py`](../../backend/src/common/telemetry.py)):
the ASGI instrumentation opens a child span per message, which on a call's audio
stream is about a hundred spans a second.

### 7.3 Sequence: an SSE trace stream reaching the browser

```mermaid
sequenceDiagram
    participant B as Browser EventSource
    participant A as Apache
    participant API as API :8000
    participant R as Redis
    participant W as Arq worker

    B->>A: "GET /api/v1/ai/executions/id/stream?token=JWT"
    A->>API: proxy
    API->>API: "get_current_user_from_query - JWT in query string"
    API->>R: "SUBSCRIBE execution:id"
    API-->>B: "200 text/event-stream + data connected"

    loop while run is live
        W->>R: "PUBLISH execution:id  span_open"
        R-->>API: message
        API-->>B: "data: ...span_open..."
    end

    W->>R: "PUBLISH execution:id  run_end with status COMPLETED"
    R-->>API: message
    API->>API: "terminal status seen -> break"
    API-->>B: close
```

The API streams the response itself. The gateway used to relay it, and only
without a read timeout when the path ended in `/stream` or the client sent
`Accept: text/event-stream`; anything else was buffered until its 60-second read
timeout and answered 503 (SA-17). On the API side the generator terminates on a
terminal status ([`ai/router.py:353`](../../backend/src/ai/router.py:353)):

```python
# backend/src/ai/router.py
if any(
    f"\"status\": \"{terminal}\"" in data
    for terminal in ("COMPLETED", "FAILED", "CANCELLED")
):
    break
```

That is a **substring match on the raw JSON**, which is why
[`agent_loop_sse.py:73`](../../backend/src/ai/core/agent_loop_sse.py:73)
deliberately copies `outcome` into a `status` key on the terminal `run_end`
event. Change either side and streams stop closing.

Note the auth quirk: this endpoint uses `get_current_user_from_query` rather than
the usual bearer dependency, because the browser `EventSource` API cannot set
request headers.

### 7.4 Webhook and internal-event ingestion

Both interfaces normalise into the same `EventEnvelope` dataclass and enqueue a
`process_gateway_event` job **before** answering
([`gateway/envelope.py`](../../backend/src/gateway/envelope.py)).

```mermaid
flowchart TD
    W["POST /webhook/inbound"] --> DET["detect_strategy - first matching adapter"]
    DET --> NORM["strategy.normalize -> client_id, event_type, normalized_data"]
    I["POST /internal/event + X-Internal-Token"] --> ENV
    NORM --> ENV["EventEnvelope channel, source, client_id, event_type, raw_data, metadata"]
    ENV --> Q["queue_event - enqueue process_gateway_event"]
    Q -->|"in Redis"| OK["202 accepted"]
    Q -->|"Redis refused"| NO["503 - the caller retries"]
```

Until SA-09 the endpoints answered 202 first and published to an in-process
`asyncio.Queue` from a background task; a dispatcher drained it and enqueued the
job, or — when arq was unreachable — ran the AgentLoop inside the API process.
An API restart in between lost the event without a trace.

Twelve webhook adapters are registered in order, with `GenericWebhookStrategy`
required to be last ([`webhook_inbound.py`](../../backend/src/gateway/webhook_inbound.py)):
email, CRM, LinkedIn, GitHub, Twilio, **Instagram (before Facebook — both use
`X-Hub-Signature-256`)**, Facebook, Twitter, TikTok, YouTube, Pinterest, generic.
Signature validation is **best-effort**: a failure logs a warning and the event
is still processed, because "providers may retry; we log for audit".

`process_gateway_event` then branches on `event_type`: `sheet.row_inserted`
creates a single-contact `Campaign` and enqueues `execute_campaign_task`;
everything else creates an `ExecutionRun` and drives `AgentLoop` inline in the
job.

---

## 8. Async job architecture: Arq

Arq is a small Redis-backed job queue. A worker process is configured by a
`WorkerSettings` class: `functions` lists the callables it can run, `cron_jobs`
lists scheduled ones, `redis_settings` says where the queue lives.

```mermaid
stateDiagram-v2
    [*] --> Enqueued: "enqueue_job(name, args)"
    Enqueued --> Running: worker dequeues
    Running --> Complete: returns
    Running --> Retrying: raises
    Retrying --> Running: "arq default max_tries"
    Retrying --> Failed: tries exhausted
    Running --> Timeout: "job_timeout 7200s"
    Complete --> [*]
    Failed --> [*]
    Timeout --> [*]
```

### Registered job functions

All from [`WorkerSettings.functions`](../../backend/src/ai/worker.py:70).

| Job name | Defined in | Arguments | What it does |
|----------|-----------|-----------|--------------|
| `run_execution_recursive` | [`arq_jobs.py:24`](../../backend/src/ai/core/arq_jobs.py:24) | `run_id_str` | The main entry point. Guards against ghost and already-terminal runs, binds a `TraceRecorder`, drives `AgentLoop.run()`. |
| `process_gateway_event` | [`arq_jobs.py:163`](../../backend/src/ai/core/arq_jobs.py:163) | `envelope_dict` | Resolves the target entity for a webhook/internal event; routes `sheet.row_inserted` to a campaign, everything else to a new `ExecutionRun`. |
| `process_document` | [`arq_jobs.py:449`](../../backend/src/ai/core/arq_jobs.py:449) | `document_id_str, file_content, file_type, filename` | Extracts text from txt/pdf/docx, chunks at 500 chars, embeds each chunk, sets `upload_status` to completed/partial/failed, then dual-writes into the Knowledge Tree. |
| `execute_campaign_task` | [`campaign_worker.py:23`](../../backend/src/ai/campaign_worker.py:23) | `campaign_id` | `CampaignExecutor.start_campaign_standalone()`. |
| `pause_campaign_task` | [`campaign_worker.py:44`](../../backend/src/ai/campaign_worker.py:44) | `campaign_id` | Pauses a running campaign. |
| `stop_campaign_task` | [`campaign_worker.py:64`](../../backend/src/ai/campaign_worker.py:64) | `campaign_id` | Stops a campaign. |
| `resume_execution` | [`arq_jobs.py:685`](../../backend/src/ai/core/arq_jobs.py:685) | `run_id_str` | Resumes a checkpointed run from `run.context_state`. |
| `resume_parent_run` | [`arq_jobs.py:701`](../../backend/src/ai/core/arq_jobs.py:701) | `parent_run_id_str` | Enqueued by `AgentLoop._maybe_resume_parent` when a child run finalises. Idempotent no-op unless the parent is `WAITING_ON_CHILDREN`. |
| `dreaming_outcome_trigger` | [`arq_jobs.py:831`](../../backend/src/ai/core/arq_jobs.py:831) | `entity_id_str, reason="success", company_id_str=None` | Outcome-triggered memory consolidation, enqueued from `AgentLoop._finalize`. Runs a cheap `should_dream` guard first. |

### Registered cron jobs

All from [`WorkerSettings.cron_jobs`](../../backend/src/ai/worker.py:104), wrapped
in a `try/except ImportError` in case `arq.cron` is unavailable.

| Cron | Schedule (as written) | What it does |
|------|----------------------|--------------|
| `cortex_resume_scheduled` | every 5 minutes (`minute={0,5,...,55}`) | Wakes suspended CORTEX trees whose `next_resume_at` has passed; creates a run and enqueues `run_execution_recursive`. |
| `dreaming_cron_trigger` | `hour={0,6,12,18}, minute={15}` | Finds memory-enabled entities (`capabilities.memory.enabled`) and enqueues `dreaming_worker` for each. |
| `graph_maintenance_worker` | `hour={3}, minute={45}` | One global pass: decays stale semantic-graph edges and prunes the weakest. |
| `critic_calibration_job` | `weekday=6, hour=3, minute=15` — the comment says Sunday 03:15 UTC | Per company, runs `CriticCalibrator` over recent `StepHealthRecord`s and writes false-pass/false-fail metrics back as Intelligence rules. |
| `skill_promotion_scan` | `weekday=6, hour=4, minute=30` — Sunday 04:30 UTC | Scans up to 500 recently-active entities for repeated tool chains and proposes skill candidates. Human approval required. |
| `meta_agent_prompt_evolution` | `weekday=0, hour=5, minute=0` — Monday 05:00 UTC | Writes prompt-update candidates into the `MetaIntelligenceTree`. **Never auto-applies** — an admin must POST the approve endpoint. |
| `kpi_rollup_refresh` | `minute={7}` — hourly at xx:07 | `REFRESH MATERIALIZED VIEW CONCURRENTLY kpi_daily_rollup`, falling back to a plain refresh if the unique index is missing. |
| `cost_estimator_refresh` | `hour=2, minute=30` — nightly 02:30 UTC | Computes a median cost per tool from the last 30 days of `tool_interaction_logs` (minimum 20 samples) and updates `cost_estimator.TOOL_BASELINE_COST` in-process. |

### Dreaming and graph maintenance

`dreaming_worker` and `graph_maintenance_worker` are registered in `functions`,
and graph maintenance has its own daily cron (03:45). Until MC-02 / SA-06
(`bb4f01e`) neither was registered, so every job the 6-hourly
`dreaming_cron_trigger` enqueued by name was rejected and the semantic graph was
never maintained; see
[08 — Memory](defect-register/08-MEMORY-AND-CORTEX-DEFECTS.md#mc-02--the-scheduled-dreaming-job-has-never-run).

### Worker configuration details

```python
# backend/src/ai/worker.py
job_timeout = 7200  # 2-hour absolute ceiling; per-entity timeout via logic_gate config

# All of REDIS_URL — password, TLS and database index included (SA-05).
redis_settings = arq_redis_settings()
```

`CHILD_RUN_QUEUE = "children"` is declared with a long comment explaining it is
the *intended* dedicated queue for async child runs so a fan-out `PROCESS` cannot
starve top-level runs — but it is explicitly **"NOT routed yet"**; children still
go on the default queue, bounded only by `governance.max_concurrent_children`.

---

## 9. Configuration and settings

One Pydantic `BaseSettings` class, reading `backend/.env` with
`extra="ignore"`, so an unknown key in the file is silently dropped rather than
raising. Until the gateway merge there were three — the gateway's
`UnifiedGatewaySettings` and the legacy `GatewaySettings` redeclared
`DATABASE_URL`, `REDIS_URL` and `STREAMING_HOST` with **different defaults**
(the cause of SA-03). Keys only they read (`BACKEND_URL`, `GATEWAY_PORT`,
`JWT_SECRET`, `JWT_ALGORITHM`, `EVENT_BUS_TYPE`) are now ignored if still present
in a `.env`.

```mermaid
graph TB
    ENV["backend/.env"] --> S1["common.config.Settings"]
    OSENV["OS environment - AI_FLAG_*, OTEL_*, TRACE_MAX_FIELD_BYTES"] --> RUNTIME["read directly via os.getenv"]
    S1 --> API["src/main.py - API :8000"]
    S1 --> WK["arq worker"]
```

### `common/config.py` — `Settings`

Loaded by the API and the Arq worker.

| Setting | Default | Purpose |
|---------|---------|---------|
| `DATABASE_URL` | **required** | SQLAlchemy async DSN, e.g. `postgresql+asyncpg://postgres:postgres@localhost:5433/hirebuddha`. |
| `REDIS_URL` | **required** | Queue, cache, pub-sub. |
| `SECRET_KEY` | **required** | JWT signing key for the Backend API. |
| `ALGORITHM` | `HS256` | JWT algorithm. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access-token lifetime. |
| `ENCRYPTION_MASTER_KEY` | `your-default-dev-key-must-be-32-bytes` | Envelope key for stored credentials. Must be overridden. |
| `STREAMING_HOST` | `localhost:8000` | Host telephony reaches this API on — the media-stream URLs and Twilio callbacks are built from it ([`voice/public_urls.py`](../../backend/src/voice/public_urls.py)). Production: `gateway.hirebuddha.com`. |
| `STREAMING_PROTOCOL` | `ws` | `ws` or `wss`; HTTP callbacks use `https` when this is `wss`. Production: `wss`. |
| `CORS_ORIGINS` | six-host comma string | The one CORS list, exposed as `cors_origins_list`. |
| `RATE_LIMIT` | `200/minute` | slowapi limit per client IP on REST routes ([`common/rate_limit.py`](../../backend/src/common/rate_limit.py)). Webhooks and internal events are exempt. |
| `INTERNAL_TOKEN` | `""` | Shared secret for `POST /internal/event`. Empty or a placeholder (`change-me-in-production` …) disables the endpoint — it answers 503 — and `/api/v1/health` reports `internal_events: disabled` (SA-20). |
| `VIDEO_STREAMING_ENABLED` | `True` | |
| `STUN_SERVERS` | `stun:stun.l.google.com:19302` | Comma-separated; exposed as `stun_servers_list`. |
| `TURN_SERVER_URL` / `TURN_USERNAME` / `TURN_CREDENTIAL` | `""` | Optional TURN relay for WebRTC. |
| `SANDBOX_CONTAINER_RUNTIME_ENABLED` | `False` | Master switch for per-tenant container sandboxing. Off = `SubprocessRuntime`. |
| `SANDBOX_IMAGE` | `hb-sandbox:local` | Sandbox image tag or digest. |
| `SANDBOX_NETWORK` | `none` | Docker network for the sandbox. |
| `SANDBOX_MEMORY` | `1g` | Container memory cap. |
| `SANDBOX_CPUS` | `1.0` | Container CPU cap. |
| `SANDBOX_PIDS_LIMIT` | `256` | Container PID cap. |
| `SANDBOX_IDLE_PAUSE_SECONDS` | `900` | Pause an idle tenant container after 15 min. |
| `SANDBOX_REAP_SECONDS` | `86400` | Delete after 24 h. |
| `SANDBOX_COST_SKU` | `sandbox-runtime` | SKU that sandbox seconds are metered against. |
| `SANDBOX_PERSISTENT_BROWSER_ENABLED` | `False` | Persist a Chromium profile per tenant so logins survive. |
| `SANDBOX_EGRESS_PROXY_ENABLED` | `False` | Turn on the allow-list egress proxy. |
| `SANDBOX_EGRESS_IMAGE` | `hb-egress-proxy:local` | Proxy image. |
| `SANDBOX_EGRESS_NETWORK` | `hb-egress-internal` | The `--internal` network the sandbox joins. |
| `SANDBOX_EGRESS_UPLINK_NETWORK` | `hb-egress-uplink` | Proxy's internet-facing network. |
| `SANDBOX_EGRESS_PROXY_PORT` | `8888` | tinyproxy port. |
| `SANDBOX_EGRESS_ALLOWLIST` | `googleapis.com,google.com` | Comma-separated host suffixes the proxy permits. |
| `VOICEMAIL_DETECTION_ENABLED` | `True` | Hang up instead of pitching an answering machine. |
| `VOICEMAIL_NO_SPEECH_SECONDS` | `25` | No lead speech for this long after the agent's first audio → voicemail. |
| `VOICEMAIL_PHRASE_WINDOW_SECONDS` | `30` | Only scan for greeting phrases inside this window. |
| `VOICE_PIPELINE_STALL_SECONDS` | `10` | No first agent audio within this window → tear the call down. |
| `VOICE_SILENCE_DISCONNECT_SECONDS` | `15` | Both sides idle this long → wind-down then disconnect. |
| `VOICE_SILENCE_GRACE_SECONDS` | `20` | No silence enforcement for the first N seconds. |
| `VOICE_AGENT_STALL_SECONDS` | `10` | Agent silent this long after the lead's turn → nudge the model. |
| `VOICE_AGENT_STALL_DISCONNECT` | `False` | Whether to hard-disconnect at 2x the stall window. |
| `VOICE_VAD_RMS_THRESHOLD` | `300` | RMS on 16-bit PCM above which the lead counts as speaking. |
| `VOICE_ECHO_SUPPRESS_RMS` | `600` | Drop inbound frames quieter than this while agent audio is playing. `0` disables. |
| `VOICE_BARGE_IN_RMS_THRESHOLD` | `1000` | Loudness required before an interruption flushes the playback buffer. |
| `VOICE_AGENT_CACHE_TTL_SECONDS` | `300` | Agent-config cache TTL; agent edits take up to this long to reach new calls. `0` disables. |
| `TATA_AUTH_TOKEN_TTL_SECONDS` | `43200` | Smartflo login-JWT cache TTL. |
| `DEFAULT_PHONE_COUNTRY_CODE` | `91` | Prepended to bare 10-digit campaign numbers, because Tata rejects non-E.164 with HTTP 422. |

### Environment variables read outside the settings classes

| Variable | Read in | Default | Purpose |
|----------|---------|---------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | [`telemetry.py:21`](../../backend/src/common/telemetry.py:21) | `http://localhost:4317` | OTLP gRPC collector. |
| `TRACE_MAX_FIELD_BYTES` | [`trace.py:57`](../../backend/src/ai/core/trace.py:57) | `1048576` | Per-field cap on trace payloads. |
| `AI_FLAG_<KEY>` | [`feature_flags.py:147`](../../backend/src/ai/core/feature_flags.py:147) | — | Env override for any feature flag, e.g. `AI_FLAG_AGENT_LOOP_ENABLED=true`. Flag keys use dots; the env form uppercases and replaces `.` with `_`. |

`start_services.sh` refuses to run if `backend/.env` is missing. There is **no
frontend `.env`** in use beyond `frontend/.env.example`; the SPA reaches the API
through the Vite dev proxy and Apache.

---

## 10. Observability

Three separate systems, easy to confuse:

```mermaid
graph TB
    subgraph OTEL["1. OpenTelemetry + Prometheus - infrastructure level"]
        SETUP["common/telemetry.py setup_telemetry"]
        SETUP --> FASTAPI["FastAPIInstrumentor - auto spans per HTTP request"]
        SETUP --> OTLP["BatchSpanProcessor -> OTLP gRPC :4317"]
        SETUP --> PROMEP["mount /metrics - prometheus_client ASGI app"]
    end
    subgraph EV["2. Structured events - application level"]
        EVENT["core/events.py event / aevent / emit"]
        EVENT --> LOG["logger agent.events at INFO"]
        EVENT --> OTELX["optional set_otel_exporter"]
        EVENT --> REDISCH["optional Redis channel agent.events"]
    end
    subgraph TR["3. Execution traces - per-run spans"]
        SPAN["core/trace.py span context manager"]
        SPAN --> LIVE["Redis PUBLISH execution:run_id"]
        SPAN --> HIST["INSERT execution_trace_events"]
    end
    LIVE --> SSE["GET /api/v1/ai/executions/id/stream"]
    HIST --> TRACEEP["GET /api/v1/ai/executions/id/trace"]
```

### OpenTelemetry and Prometheus

[`common/telemetry.py`](../../backend/src/common/telemetry.py) is called once, on
the **last line of `main.py`**. It creates a `TracerProvider` with
`service.name = "hirebuddha-backend"`, adds a `BatchSpanProcessor` pointing at
`OTEL_EXPORTER_OTLP_ENDPOINT` (insecure gRPC), instruments the FastAPI app for
HTTP only (WebSocket scopes are excluded — a span per audio frame would swamp the
exporter), and mounts the `prometheus_client` ASGI app at `/metrics`.
`GET /metrics/gateway` is a separate JSON endpoint with the active video
sessions; it is declared before the `/metrics` mount, which would otherwise match
it.

The webhook and streaming endpoints the gateway served are now covered by the
API's instrumentation. The **worker** has none; a worker-side OTel exporter would
have to be wired via `events.set_otel_exporter(...)`.

[`docker-compose.observability.yml`](../../backend/docker-compose.observability.yml)
brings up Jaeger (UI 16686, OTLP 4317/4318), Prometheus (9090) and Grafana. Two
sharp edges: [`prometheus.yml`](../../backend/prometheus.yml) scrapes
`host.docker.internal:8000`, which does not resolve on stock Linux Docker without
an `extra_hosts` entry; and the Grafana container publishes **port 3000**, which
collides with the Vite dev server.

### How a trace is produced

[`core/trace.py`](../../backend/src/ai/core/trace.py) is the mechanism the
"what happened inside each iteration" UI is built on. The design problem it
solves: deep layers such as the `@staticmethod` tool executor and the LLM router
receive no run context in their signatures. The fix is a `ContextVar`.

```python
# backend/src/ai/core/arq_jobs.py
recorder = TraceRecorder(
    run_id, company_id=company_id, redis=redis_pool,
    capture_payloads=_capture,
)
with set_recorder(recorder):
    loop = AgentLoop(db, redis_pool, company_id=company_id, feature_flags=flags)
    await loop.run(run_id)
```

Any code inside that block can then open a span with no plumbing:

```python
async with span("tool", tool_id, input=raw_input) as sp:
    result = await ToolExecutor.execute_tools(...)
    sp.set_output(result)
```

Each span has two sinks. **Live**: `span_open` / `span_close` envelopes published
to `execution:{run_id}` — the same channel the SSE endpoint relays. **Historical**:
one `execution_trace_events` row per closed span, written on a *dedicated*
short-lived `AsyncSessionLocal` so a trace write can never poison the run's own
session. Both are best-effort; failures are logged at DEBUG and swallowed.

Parent-child nesting uses a second `ContextVar` (`_CURRENT_SPAN`). Because
asyncio copies context per task, concurrent DAG branches nest correctly without a
shared mutable stack. When no recorder is bound (unit tests, non-run callers),
`span()` yields a detached handle and does nothing — so call sites never need a
conditional.

Payload capture is gated by the entity's `observability.log_thoughts` flag, and
each field is capped at `TRACE_MAX_FIELD_BYTES` (1 MiB) with a
`{"_truncated": True, "preview": ...}` replacement.

### How a trace is read

* **Live** — the browser opens an `EventSource` on
  `GET /api/v1/ai/executions/{id}/stream` (see [§7.3](#73-sequence-an-sse-trace-stream-reaching-the-browser)).
* **Historical** — `GET /api/v1/ai/executions/{id}/trace` reads back the
  `execution_trace_events` rows.
* **Loop-level events** — [`agent_loop_sse.py`](../../backend/src/ai/core/agent_loop_sse.py)
  maps 12 internal event names onto short frontend discriminators
  (`agent.loop.iteration_start` → `iteration_start`, `agent.critic.pre_verdict` →
  `critic_pre`, …) consumed by `frontend/src/hooks/useExecutionEvents.ts`.
* **SQL dashboards** — [`infra/dashboards/`](../../infra/dashboards) holds
  ready-made queries (run health, cost, critic pipeline, meta-agent, memory, loop
  telemetry, CSAT, sandbox/MCP cost, tool-synthesis trust).

The event naming convention is `agent.<layer>.<verb>[_<qualifier>]`
([`events.py:23`](../../backend/src/ai/core/events.py:23)). Reserved structured
keys — `company_id`, `user_id`, `run_id`, `entity_id`, `iteration`, `severity` —
are lifted into the `TelemetryEvent` envelope; everything else is sanitised into
`payload`.

---

## 11. Error handling and resilience

```mermaid
flowchart TD
    CALL["Tool call"] --> EX1["ToolExecutor.execute_tools"]
    EX1 --> CLS["classify_tool_failure"]
    CLS -->|NONE| OK["return result"]
    CLS -->|"FORMAT / IO / EMPTY / ERROR_MSG"| RF["Step 1 - LLM reformat-retry with the exact error text"]
    CLS -->|"TIMEOUT / OTHER"| FB
    RF --> RF2{"retry clean?"}
    RF2 -->|yes| OK
    RF2 -->|no| FB["Step 2 - fallback chain via get_fallback_tool"]
    FB --> FB2{"fallback allowed and clean?"}
    FB2 -->|yes| OK2["return alt result, tool renamed a to b"]
    FB2 -->|no| EMPTY["Step 3 - return TOOL_EMPTY marker, success=False"]
```

### Tool-level: `ToolResilience`

[`ai/tools/resilience.py`](../../backend/src/ai/tools/resilience.py) exists to
remove an asymmetry: before it, the REACT/AFC path silently skipped the
reformat-retry that the direct `TOOL_CALL` path had. Now both go through
`ToolResilience.run` / `run_function_call`.

`classify_tool_failure` maps a `ToolResult` onto a `FailureKind` by keyword
matching, and **order matters** — `TIMEOUT` and `IO` are checked before `FORMAT`,
and an `"ERROR: invalid json"` output resolves to `FORMAT` (the actionable
bucket) rather than the generic `ERROR_MSG`. `_is_format_error` deliberately
excludes infrastructure keywords (`api key`, `unauthorized`, `403`, `rate limit`)
so a credentials problem is never mistaken for a formatting problem.

| `FailureKind` | Triggers reformat-retry? |
|---------------|--------------------------|
| `NONE` | n/a — success |
| `FORMAT` | yes |
| `IO` | yes |
| `EMPTY` | yes |
| `ERROR_MSG` | yes |
| `TIMEOUT` | no — straight to fallback |
| `OTHER` | no — straight to fallback |

`_fallback_allowed` refuses a substitute tool that is not in the entity's
`capabilities.tools` allow-list — an entity cannot be silently escalated to a
tool it was never granted.

### Run-level: retry strategy

[`ai/planning/retry_strategies.py`](../../backend/src/ai/planning/retry_strategies.py)
holds `MAX_RETRIES_PER_STEP = 2` — a hard ceiling the loop refuses to exceed for
one step in one run. `pick_retry` is a **pure function** (no LLM, no DB) mapping
a `StepHealthRecord` plus `AgentState` to one of seven strategies:

```mermaid
stateDiagram-v2
    [*] --> Check
    Check --> NONE: "post verdict PASS"
    Check --> ABANDON: "budget pressure > 0.85"
    Check --> ABANDON2: POLICY_VIOLATION
    Check --> ASK_USER: NEEDS_CLARIFICATION
    Check --> RETRY_DIFFERENT_TOOL: TOOL_FAILURE
    Check --> RETRY_DIFFERENT_PROMPT: WRONG_FORMAT
    Check --> RETRY_DIFFERENT_MODEL: "OFF_TOPIC or HALLUCINATION"
```

Budget pressure wins over everything: at >0.85 the run abandons regardless of
what the failure tags say.

### Idempotency

| Mechanism | Where |
|-----------|-------|
| Terminal-run guard in `run_execution_recursive` | [`arq_jobs.py:87`](../../backend/src/ai/core/arq_jobs.py:87) — refuses to re-drive a `COMPLETED`/`FAILED`/`PARTIAL_COMPLETE`/`CANCELLED` run, explicitly to avoid re-billing. Retry and refine create *new* run rows so they are unaffected. |
| Ghost-run guard | [`arq_jobs.py:61`](../../backend/src/ai/core/arq_jobs.py:61) — returns cleanly when the run or entity no longer exists, preventing a cascade of `ForeignKeyViolationError` → `PendingRollbackError` on every arq retry. |
| Step-level `idempotency_key` | `String(255)`, nullable, indexed, on two tables in [`ai/orm/execution.py:59`](../../backend/src/ai/orm/execution.py:59) and `:115`. |
| `resume_parent_run` no-op | Idempotent by design: does nothing unless the parent is `WAITING_ON_CHILDREN`, so duplicate enqueues are harmless. |

### Timeouts and circuit breakers

| Guard | Value | Where |
|-------|-------|-------|
| Arq job timeout | 7200 s | `WorkerSettings.job_timeout` |
| Apache proxy timeout | 86400 s on the `gateway.` vhost (WebSockets) | `gateway.hirebuddha.com-le-ssl.conf` |
| DB pool | `pool_size=20`, `max_overflow=40`, `pool_timeout=60`, `pool_recycle=1800`, `pool_pre_ping=True` | [`common/database.py:18`](../../backend/src/common/database.py:18) |
| Credit circuit breaker | trips when effective balance ≤ 0 mid-run | [`governance_service.py:90`](../../backend/src/ai/governance/governance_service.py:90) |
| Child credit gate | pre-spawn check before launching a child entity | `governance_service.py:120` |
| Redis sliding-window rate limiter | caller-supplied `limit` / `window_seconds` | [`governance/rate_limiter.py`](../../backend/src/ai/governance/rate_limiter.py) |
| API HTTP rate limit | `RATE_LIMIT` (`200/minute`) per client IP; webhooks and internal events exempt | [`common/rate_limit.py`](../../backend/src/common/rate_limit.py), `SlowAPIMiddleware` in `main.py` |

The DB pool comment is worth reading in full: Deep Research spawns roughly 15–20
concurrent connections per run, Postgres `max_connections` is 100, so 60 are
allocated to the worker pool and ~40 left for the API.

Both rate limiters keep serving when Redis fails: the tool-level
`RedisRateLimiter` returns `True` (allowed), and the API's slowapi limiter counts
in process memory until Redis recovers.

---

## 12. Security architecture at the system level

```mermaid
flowchart TD
    REQ["Incoming request"] --> AP["Apache: TLS, security headers, IP blocklist, path blocks, mod_evasive, 10MB body cap"]
    AP --> CORS["CORSMiddleware - settings.cors_origins_list"]
    CORS --> RL["SlowAPIMiddleware - RATE_LIMIT per client IP, Redis backed"]
    RL --> ROUTE{"route"}
    ROUTE -->|"/internal/event"| INT["require_internal - X-Internal-Token"]
    ROUTE -->|"/webhook/inbound, WebSockets"| NATIVE["handler - own checks, not rate limited"]
    ROUTE -->|"REST"| DEP["Route dependencies - get_current_user incl. suspension 403, RoleChecker"]
    DEP --> SVC["Service layer"]
```

### The middleware chain, in execution order

Starlette runs middleware in **reverse** order of `add_middleware` calls. `main.py`
adds `SlowAPIMiddleware`, then `CORSMiddleware`, so CORS runs first: it answers
preflights before anything else and puts its headers on every response, a 429
included. Both pass WebSocket connections straight through.

**Company suspension** is enforced once, by the auth dependency: every
`get_current_user*` variant goes through `_authenticate_user`
([`auth/dependencies.py`](../../backend/src/auth/dependencies.py)), which loads the
user with its company and answers 403 if the company is suspended. Until SA-18
(2026-09-30) a `CompanySuspensionMiddleware` did the same check first, on every request
carrying a bearer token — decoding the token itself, opening its own session and
loading the company (even for a 404), then letting the dependency load it again.
It also failed open on a database error and trusted the token's `company_id`
claim rather than the user's current company. Deleting it took one authenticated
request from 4 SQL statements to 3.

`SlowAPIMiddleware` applies `RATE_LIMIT` to every HTTP route except those marked
`@limiter.exempt` — `POST /webhook/inbound` and `POST /internal/event`, which the
gateway never limited either. Static mounts have no route handler and are not
counted.

`POST /internal/event` depends on `require_internal`
([`internal_event.py`](../../backend/src/gateway/internal_event.py)), which
compares `X-Internal-Token` with `INTERNAL_TOKEN` in constant time and returns 401
on a mismatch — or 503 for everyone while `INTERNAL_TOKEN` is empty or a
placeholder. The gateway's `GatewayAuthMiddleware` used to do this for the
whole app and JWT-decode every other request with a separate `JWT_SECRET` for
logging nothing read; it is gone.

### CORS

One origin list: `settings.CORS_ORIGINS`, a comma-separated string exposed as
`cors_origins_list`. The default covers `http://localhost:3000`,
`http://127.0.0.1:3000`, `http://34.100.230.121:3000`,
`https://dev.hirebuddha.com`, `https://app.hirebuddha.com` and
`https://gateway.hirebuddha.com`. It uses `allow_credentials=True` with
`allow_methods=["*"]` and `allow_headers=["*"]`. Before the merge the API had a
hardcoded list and the gateway its own `CORS_ORIGINS`, maintained by hand in two
places (SA-19).

### The sandbox container

Untrusted and LLM-synthesized code runs in `hb-sandbox`
([`backend/docker/sandbox/Dockerfile`](../../backend/docker/sandbox/Dockerfile)),
based on `mcr.microsoft.com/playwright/python:v1.58.0-noble` and carrying
ffmpeg, LibreOffice headless, Node + `pptxgenjs`, the Document Factory scripts at
`/opt/docfactory/scripts`, and a non-root `sandbox` user (uid 10001).

**The image carries no isolation policy of its own.** All of it is applied at
`docker run` time by
[`tools/sandbox/tenant_manager.py`](../../backend/src/ai/tools/sandbox/tenant_manager.py):
`--user`, `--read-only` root filesystem, tmpfs `/tmp`, `--cap-drop ALL`,
`no-new-privileges`, `--network none` by default, and `--memory` / `--cpus` /
`--pids-limit` from settings. The container is long-lived and idle (`CMD ["sleep",
"infinity"]`); the runtime `docker exec`s into it per call and the manager
pauses/reaps it on the `SANDBOX_IDLE_PAUSE_SECONDS` / `SANDBOX_REAP_SECONDS`
TTLs.

Container runtime is **off by default** — `SubprocessRuntime` is both the dev/CI
default and the production rollback path. Per-company rollout uses the
`sandbox.container_runtime_enabled` feature flag rather than the process-wide
setting. The README names a security review of the container-escape surface as a
release gate before any default-ON flip.

### The egress proxy

```mermaid
graph LR
    SB["Sandbox container on hb-egress-internal - no internet route"]
    PX["hb-egress-proxy - tinyproxy FilterDefaultDeny Yes"]
    UP["hb-egress-uplink bridge"]
    NET["Approved hosts only"]
    SB -->|"HTTP_PROXY / HTTPS_PROXY :8888"| PX
    PX --> UP
    UP --> NET
    SB -.no route.-x NET
```

When `ToolSpec.network_policy == ALLOWLIST`, the sandbox joins an `--internal`
Docker network with **no route to the internet at all** — even tool code that
ignores the proxy env vars has nowhere to go. The only way out is the dual-homed
`hb-egress-proxy`
([`backend/docker/egress-proxy/`](../../backend/docker/egress-proxy)), an Alpine
container running tinyproxy with:

```
# backend/docker/egress-proxy/tinyproxy.conf
Filter "/etc/tinyproxy/filter"
FilterDefaultDeny Yes
FilterExtended On
FilterURLs Off          # match the host, not the URL, so HTTPS CONNECT is covered
ConnectPort 443
ConnectPort 80
```

The filter file is built at container start by
[`entrypoint.sh`](../../backend/docker/egress-proxy/entrypoint.sh), turning each
comma-separated entry of `$ALLOWLIST` into an anchored regex —
`googleapis.com` becomes `(^|\.)googleapis\.com$` — so the allow-list is
per-deployment config rather than baked into the image. Today it is **one
process-wide list**; per-company allow-lists are listed as remaining work.

### Secrets and other notes

* `INTERNAL_TOKEN` defaults to empty, and an empty or placeholder value disables
  `POST /internal/event` (503) instead of guarding it with a secret published in
  the repository (SA-20). Before, it defaulted to `change-me-in-production` in
  code, `.env.example` and docker-compose. (`JWT_SECRET`, the gateway's copy of
  the JWT key, is gone with the gateway.)
* Webhook signature validation is best-effort and never blocks
  ([`webhook_inbound.py:548`](../../backend/src/gateway/webhook_inbound.py:548)).
* `ENCRYPTION_MASTER_KEY` protects stored third-party credentials and ships with
  an obviously-fake default.

---

## Key files reference

| File | Lines | What it does |
|------|-------|--------------|
| [`start_services.sh`](../../start_services.sh) | 150 | Boots Docker, the API, the worker and the frontend in dependency order; writes PID files and logs into `logs/` |
| [`stop_services.sh`](../../stop_services.sh) | 98 | Kills by PID file, then by port, then `docker compose down` |
| [`setup_production_vm.sh`](../../setup_production_vm.sh) | 183 | Eight-step Ubuntu bootstrap: Python 3.12, Poetry, Node 20, Docker, venv, npm, `.env` |
| [`backend/docker-compose.yml`](../../backend/docker-compose.yml) | 57 | Defines `app` (the API, 8000), `db` (5433), `redis` (6379); only `db` and `redis` are actually used |
| [`backend/src/main.py`](../../backend/src/main.py) | 170 | The API app: lifespan (dispatcher), CORS, suspension middleware, rate limiter, ~30 routers (18 of them optional) including the webhook/stream edge, three static mounts, telemetry |
| [`backend/src/common/router_mounts.py`](../../backend/src/common/router_mounts.py) | 52 | `mount_optional` — mounts a router or records why its import failed; `GET /api/v1/health` and `GET /health` report the failures |
| [`backend/src/common/rate_limit.py`](../../backend/src/common/rate_limit.py) | 22 | The slowapi `limiter`: `RATE_LIMIT` per client IP, Redis storage with in-memory fallback |
| [`backend/src/common/job_queue.py`](../../backend/src/common/job_queue.py) | 37 | `arq_redis_settings`, `arq_pool`, `enqueue_job` — every arq connection, from all of `REDIS_URL` |
| [`backend/src/gateway/dispatcher.py`](../../backend/src/gateway/dispatcher.py) | 110 | Redis-cached agent resolution for the audio/video handshakes |
| [`backend/src/gateway/envelope.py`](../../backend/src/gateway/envelope.py) | 95 | `EventEnvelope` + `queue_event` — webhook and internal events go onto arq before their 202 |
| [`backend/src/gateway/internal_event.py`](../../backend/src/gateway/internal_event.py) | 200 | `POST /internal/event`, `require_internal`, `WellKnownEvents`, `emit_internal_event` helper |
| [`backend/src/gateway/webhook_inbound.py`](../../backend/src/gateway/webhook_inbound.py) | 600 | Twelve webhook adapters + `detect_strategy` + `POST /webhook/inbound` |
| [`backend/src/gateway/telephony_streams.py`](../../backend/src/gateway/telephony_streams.py) | 100 | The Twilio/Tata media-stream WebSockets |
| [`backend/src/voice/public_urls.py`](../../backend/src/voice/public_urls.py) | 20 | `stream_url` / `callback_url` — the URLs handed to telephony providers |
| [`backend/src/ai/worker.py`](../../backend/src/ai/worker.py) | 124 | `WorkerSettings`: 9 job functions, 7 crons, `job_timeout=7200`, Redis host/port parse |
| [`backend/src/ai/core/arq_jobs.py`](../../backend/src/ai/core/arq_jobs.py) | 1126 | Every Arq job body, including the ghost-run and idempotency guards |
| [`backend/src/ai/core/trace.py`](../../backend/src/ai/core/trace.py) | 373 | `TraceRecorder`, `SpanHandle`, the ambient `span()` context manager |
| [`backend/src/ai/core/events.py`](../../backend/src/ai/core/events.py) | 297 | `TelemetryEvent` envelope, `event` / `aevent` / `emit`, test capture |
| [`backend/src/ai/core/agent_loop_sse.py`](../../backend/src/ai/core/agent_loop_sse.py) | 79 | Maps 12 loop event names to frontend SSE discriminators |
| [`backend/src/ai/tools/resilience.py`](../../backend/src/ai/tools/resilience.py) | 403 | `classify_tool_failure`, reformat-retry, fallback chain, `[TOOL_EMPTY]` marker |
| [`backend/src/common/config.py`](../../backend/src/common/config.py) | 180 | The one `Settings` object, for the API and the worker |
| [`backend/src/common/database.py`](../../backend/src/common/database.py) | 36 | Engine with the tuned pool, `AsyncSessionLocal`, `get_db` |
| [`backend/src/common/telemetry.py`](../../backend/src/common/telemetry.py) | 38 | OTel tracer provider, FastAPI instrumentation (WebSockets excluded), `/metrics` mount |
| [`backend/scripts/lint_ai_layout.py`](../../backend/scripts/lint_ai_layout.py) | 271 | Executable architecture policy for `backend/src/ai/` |
| [`deploy/apache/hirebuddha-security.conf`](../../deploy/apache/hirebuddha-security.conf) | 200 | Global headers, IP blocklist, path blocks, mod_evasive, size limits |
| [`deploy/apache/gateway.hirebuddha.com-le-ssl.conf`](../../deploy/apache/gateway.hirebuddha.com-le-ssl.conf) | 41 | The canonical WebSocket-upgrade + proxy vhost, all to port 8000 |

---

## Gotchas and things that surprise newcomers

* **Port 5433, not 5432.** Docker maps the Postgres container's 5432 to host
  **5433**; `DATABASE_URL` must say 5433.
* **One port.** Every endpoint — REST, webhooks, internal events, the audio,
  video and telephony WebSockets, the mobile push socket — is on 8000. There is
  no gateway process on 8001 any more, and `gateway.hirebuddha.com` is simply the
  API's public name.
* **`STREAMING_HOST` must be the public hostname in production.** The default,
  `localhost:8000`, is right only for a local stack; Twilio and Tata need
  `gateway.hirebuddha.com` with `STREAMING_PROTOCOL=wss`.
* **Enqueue through `common/job_queue.py`.** A hand-built `RedisSettings(...)`
  is what SA-04/SA-05 removed; a test fails if one reappears.
* **A webhook 202 means the job is in Redis.** The endpoint enqueues before it
  answers, and answers 503 if it cannot — so a provider's retry, not an
  in-memory queue, covers a Redis outage.
* **Terminal SSE detection is a substring match** on `"status": "COMPLETED"` in
  the raw JSON. That is why `agent_loop_sse` copies `outcome` into `status`.
* **Suspension is checked in `_authenticate_user`, not in middleware.** A route
  that does not depend on `get_current_user` (or a sibling) is not protected
  against suspended companies — or against anyone.
* **`app.hirebuddha.com` has two competing port-80 vhosts.** `app.hirebuddha.com.conf`
  redirects to HTTPS; `app.hirebuddha.com-le-ssl.conf` also declares a `*:80`
  vhost with the redirect commented out. Whichever Apache loads first wins.
* **Apache caps request bodies at 10 MB** globally. Larger uploads are rejected
  before FastAPI sees them.
* **`api.hirebuddha.com` reuses the `gateway.hirebuddha.com` certificate.**
  Renewing the gateway cert affects both hostnames.
* **A new endpoint that should not be rate limited** needs `@limiter.exempt` —
  and its module must not use `from __future__ import annotations`: FastAPI
  resolves the string annotations against slowapi's wrapper module and turns
  `request: Request` into a query parameter (a 422).
* **Grafana in the observability compose file also uses port 3000** and will
  collide with the Vite dev server.
* **`core/README.md` is stale.** It documents `execution_engine.py` and
  `recursive_engine.py` as living in `core/`; neither file exists any more, and
  `arq_jobs.py` states that `AgentLoop` is now "the sole run engine (C4)".
* **You cannot add a file directly under `backend/src/ai/`.** The layout lint
  fails on any name outside the allow-list. Nor may you exceed a package's line
  cap, write a `# Phase N:` comment, or use the string `phase11` anywhere in the
  tree.

---

## Where to go next

* [03 — Database & data model](03-data-model.md) — the tables behind the ORM layer.
* [04 — Auth, RBAC & multi-tenancy](04-auth-rbac-tenancy.md) — what the middleware chain is protecting.
* [05 — The agent kernel](05-agent-kernel.md) — inside `AgentLoop.run()`.
* [06 — Entities & the execution pipeline](06-execution-pipeline.md) — what an `ExecutionRun` actually does.
* [12 — Voice, telephony & messaging](12-voice-and-telephony.md) — the full call lifecycle.
* [13 — The unified gateway & real-time transport](13-gateway-and-realtime.md) — deep dive on the five interfaces.
* [18 — Infrastructure, deployment & ops](18-infrastructure-and-deployment.md) — runbooks, backups, scaling.
* [20 — Developer onboarding & glossary](20-onboarding-and-glossary.md) — get a local stack running.
