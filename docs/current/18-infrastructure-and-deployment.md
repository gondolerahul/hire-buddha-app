# 18. Infrastructure, Deployment & Operations

> **What this document covers:** getting the stack running on your laptop, what runs in production, how Apache routes traffic, the sandbox and egress containers, backups, CI, the code-quality gates, and runbooks for when something breaks.
> **Who should read it:** every new developer on day one, and anyone who might be on call.
> **Prerequisites:** none. This is the most self-contained document in the set. [02 — System architecture](02-system-architecture.md) explains *why* the topology looks like this; this one tells you how to operate it.

---

## Table of contents

1. [The 60-second version](#1-the-60-second-version)
2. [Local development from a fresh clone](#2-local-development-from-a-fresh-clone)
3. [docker-compose](#3-docker-compose)
4. [The backend Dockerfile](#4-the-backend-dockerfile)
5. [Environment configuration](#5-environment-configuration)
6. [Starting and stopping services](#6-starting-and-stopping-services)
7. [Production VM provisioning](#7-production-vm-provisioning)
8. [Apache — reverse proxy and TLS](#8-apache--reverse-proxy-and-tls)
9. [Security hardening at the edge](#9-security-hardening-at-the-edge)
10. [The sandbox and egress-proxy containers](#10-the-sandbox-and-egress-proxy-containers)
11. [Database operations](#11-database-operations)
12. [Backups](#12-backups)
13. [Continuous integration](#13-continuous-integration)
14. [Code-quality gates](#14-code-quality-gates)
15. [Observability dashboards](#15-observability-dashboards)
16. [Runbooks](#16-runbooks)
17. [Scaling limits](#17-scaling-limits)
18. [Key files reference](#18-key-files-reference)
19. [Gotchas](#19-gotchas)

---

## 1. The 60-second version

The whole platform runs on **one Ubuntu VM**. Apache terminates TLS and reverse-
proxies five subdomains to five local processes. PostgreSQL and Redis run in
Docker; everything else runs as plain `nohup` background processes managed by
two shell scripts.

```mermaid
graph TB
    NET["Internet"] --> AP["Apache 2.4 - ports 80/443<br/>mod_ssl, mod_proxy, mod_rewrite"]

    AP -->|app / dev .hirebuddha.com| FE["Vite dev server - 3000"]
    AP -->|api.hirebuddha.com| BE["Backend API - 8000<br/>src.main:app"]
    AP -->|gateway.hirebuddha.com| GW["Unified Gateway - 8001<br/>src.gateway.app:app"]
    AP -->|streaming.hirebuddha.com| VO["Voice service - 8002"]

    subgraph Docker["Docker containers"]
        PG[("PostgreSQL 15 + pgvector<br/>host 5433 - container 5432")]
        RD[("Redis 7 - 6379")]
    end

    subgraph Background["nohup processes"]
        WK["Arq worker<br/>src.ai.worker.WorkerSettings"]
    end

    BE --> PG
    BE --> RD
    GW --> BE
    GW --> RD
    VO --> PG
    RD --> WK
    WK --> PG
```

| Process | Port | Entrypoint | Log | PID file |
|---|---|---|---|---|
| Backend API | 8000 | `uvicorn src.main:app` | `logs/backend_api.log` | `logs/backend_api.pid` |
| Unified Gateway | 8001 | `uvicorn src.gateway.app:app` | `logs/unified_gateway.log` | `logs/unified_gateway.pid` |
| Voice service | 8002 | `uvicorn src.voice.main:app` | — | — |
| Arq worker | — | `python -m arq src.ai.worker.WorkerSettings` | `logs/arq_worker.log` | `logs/arq_worker.pid` |
| Frontend | 3000 | `npm run dev` | `logs/frontend.log` | `logs/frontend.pid` |
| PostgreSQL | 5433 | `docker compose up db` | docker | — |
| Redis | 6379 | `docker compose up redis` | docker | — |

> ⚠️ **`start_services.sh` does not start the voice service.** It starts five
> things (Docker, backend, gateway, worker, frontend) and its own banner says
> `[1/5]`…`[5/5]`. Port 8002 has an Apache VirtualHost
> (`streaming.hirebuddha.com`) and the README lists it, but nothing in the start
> script launches it. If you need voice, start it by hand — see
> [§6.3](#63-starting-the-voice-service).

---

## 2. Local development from a fresh clone

### 2.1 Prerequisites

| Tool | Version | Why |
|---|---|---|
| Ubuntu | 22.04 or 24.04 LTS | What the setup script targets |
| Python | 3.11+ (script installs 3.12) | `pyproject.toml` requires `^3.11` |
| Poetry | 1.7+ | The only dependency manager — there is no `requirements.txt` |
| Node.js | 20 LTS | Vite 5 |
| Docker + Compose plugin | current | PostgreSQL and Redis |

### 2.2 Step by step

```mermaid
flowchart TD
    S1["1. Clone the repo"] --> S2["2. poetry install"]
    S2 --> S3["3. cp .env.example .env and edit"]
    S3 --> S4["4. docker compose up -d db redis"]
    S4 --> S5["5. alembic upgrade head"]
    S5 --> S6["6. seed_admin_user.py"]
    S6 --> S7["7. npm install --legacy-peer-deps"]
    S7 --> S8["8. ./start_services.sh"]
    S8 --> V["Verify: /docs, login, run an entity"]
```

**Step 1 — clone and enter the repo**

```bash
git clone <repo-url> && cd hire-buddha-app
```

**Step 2 — backend dependencies**

```bash
cd backend && python3 -m venv .venv && poetry install --no-interaction
```

Verify: `.venv/` exists and `.venv/bin/python -c "import fastapi"` is silent.

**Step 3 — environment file**

```bash
cp backend/.env.example backend/.env
```

`start_services.sh` **exits with an error if `backend/.env` is missing**, so this
step is mandatory. See [§5](#5-environment-configuration) for what to edit.

**Step 4 — start the data stores**

```bash
cd backend && docker compose up -d db redis
```

Verify: `docker compose ps` shows `hirebuddha-db` and `hirebuddha-redis`
running, and `psql -h localhost -p 5433 -U postgres -d hirebuddha -c '\dt'`
connects (password `postgres`).

**Step 5 — run migrations**

```bash
cd backend && .venv/bin/alembic upgrade head
```

Verify: `\dt` now lists `companies`, `users`, `hierarchical_entities`,
`execution_runs`, `cortex_trees`, and the rest — see
[03 — Data model](03-data-model.md).

**Step 6 — seed an admin user**

```bash
cd backend && .venv/bin/python db-scripts/seed_admin_user.py
```

Verify: a row exists in `users` with role `app_admin`.

**Step 7 — frontend dependencies**

```bash
cd frontend && npm install --legacy-peer-deps
```

`--legacy-peer-deps` is required — the setup script uses it. The React Three
Fiber v9 / React 18 combination produces peer-dependency conflicts otherwise.

**Step 8 — start everything**

```bash
./start_services.sh
```

Verify each service:

| Check | Command |
|---|---|
| Backend API | `curl -s localhost:8000/` → `{"message":"Welcome to HireBuddha Platform v2.0"}` |
| Swagger | open `http://localhost:8000/docs` |
| Gateway | `curl -s localhost:8001/` |
| Frontend | open `http://localhost:3000` |
| Worker booted | `.venv/bin/python -c "from src.ai.worker import WorkerSettings; print(len(WorkerSettings.functions), 'jobs;', len(WorkerSettings.cron_jobs), 'crons')"` |
| Redis | `redis-cli ping` → `PONG` |

The worker smoke test comes from
[backend/src/ai/ONBOARDING.md](../../backend/src/ai/ONBOARDING.md) and is the
fastest way to confirm the AI package imports cleanly.

### 2.3 The shortcut

`setup_production_vm.sh` performs steps 2, 3 and 7 (plus installing Python,
Poetry, Node and Docker) in one shot. Despite the name it is equally usable for
a fresh dev VM:

```bash
chmod +x setup_production_vm.sh && ./setup_production_vm.sh
```

It deliberately stops short of migrations, seeding and starting services, and
prints those as "next steps".

---

## 3. docker-compose

[backend/docker-compose.yml](../../backend/docker-compose.yml) defines **four**
services, but day-to-day you only start two of them.

```mermaid
graph TB
    subgraph Compose["docker-compose.yml"]
        GW["gateway - 8001<br/>build from Dockerfile"]
        APP["app - 8000<br/>build from Dockerfile"]
        DB[("db - pgvector/pgvector:pg15<br/>5433 to 5432")]
        RD[("redis - redis:7-alpine<br/>6379")]
    end
    GW -->|depends_on| APP
    GW -->|depends_on| RD
    APP -->|depends_on| DB
    APP -->|depends_on| RD
    DB --- V1[("postgres_data volume")]
    RD --- V2[("redis_data volume")]

    style GW stroke-dasharray: 5 5
    style APP stroke-dasharray: 5 5
```

Dashed services are defined but **not used in the normal workflow** — both
`start_services.sh` and the setup script run the Python processes natively and
bring up only `db` and `redis`:

```bash
docker compose up -d db redis
```

### 3.1 Service detail

| Service | Image / build | Ports | Volumes | Notes |
|---|---|---|---|---|
| `gateway` | build `.` / `Dockerfile` | `8001:8001` | — | `container_name: hirebuddha-unified-gateway` |
| `app` | build `.` | `8000:8000` | `.:/app` (live mount) | `container_name: hirebuddha-backend` |
| `db` | `pgvector/pgvector:pg15` | **`5433:5432`** | `postgres_data` | `container_name: hirebuddha-db` |
| `redis` | `redis:7-alpine` | `6379:6379` | `redis_data` | `container_name: hirebuddha-redis` |

**The port mapping is the number-one local-dev gotcha.** PostgreSQL listens on
**5433 on the host**, mapped to 5432 in the container. So:

- From the host: `postgresql://postgres:postgres@localhost:5433/hirebuddha`
- From inside a compose container: `postgresql://postgres:postgres@db:5432/hirebuddha`

`.env.example` ships with `DATABASE_URL=...@localhost:5432/hirebuddha` — **port
5432, which is wrong for host-based development.** Change it to `5433` or your
migrations will hang trying to reach a non-existent local Postgres.

### 3.2 Gateway environment in compose

```yaml
# backend/docker-compose.yml
environment:
  - BACKEND_URL=http://app:8000
  - REDIS_URL=redis://redis:6379
  - RATE_LIMIT=200/minute
  - DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/hirebuddha
  - INTERNAL_TOKEN=${INTERNAL_TOKEN:-change-me-in-production}
  - JWT_SECRET=${SECRET_KEY:-change-me-in-production}
  - STREAMING_HOST=gateway.hirebuddha.com
  - STREAMING_PROTOCOL=wss
  - VIDEO_STREAMING_ENABLED=true
  - STUN_SERVERS=stun:stun.l.google.com:19302
```

Note `RATE_LIMIT=200/minute` — a gateway-level limit that only exists in the
compose definition, not in `.env.example`.

Both secrets default to the literal string `change-me-in-production`. There is
no guard that stops you shipping that.

### 3.3 Data persistence

Two named volumes, `postgres_data` and `redis_data`. `docker compose down`
preserves them; `docker compose down -v` **deletes your database**.

---

## 4. The backend Dockerfile

[backend/Dockerfile](../../backend/Dockerfile) is a two-stage build.

```mermaid
flowchart LR
    subgraph B["Stage 1: builder"]
        B1["python:3.11-slim"] --> B2["apt: curl, build-essential"]
        B2 --> B3["Install Poetry 1.7.1"]
        B3 --> B4["COPY pyproject.toml poetry.lock"]
        B4 --> B5["poetry install --no-root<br/>into /app/.venv"]
    end
    subgraph R["Stage 2: runtime"]
        R1["python:3.11-slim"] --> R2["COPY --from=builder /app/.venv"]
        R2 --> R3["COPY . ."]
        R3 --> R4["EXPOSE 8000"]
        R4 --> R5["CMD uvicorn src.main:app --reload"]
    end
    B5 --> R2
```

Key settings:

```dockerfile
# backend/Dockerfile
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VERSION=1.7.1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1
```

`POETRY_VIRTUALENVS_IN_PROJECT=true` is what puts the venv at `/app/.venv` so
the runtime stage can copy it as a single directory. Dependencies are installed
before the application code is copied, so a code change does not invalidate the
dependency layer.

> ⚠️ Two production-readiness problems with this image:
> 1. **`CMD` uses `--reload`.** The auto-reloader is a development feature — it
>    watches the filesystem, uses more memory, and is not intended for
>    production traffic.
> 2. **No non-root user.** The container runs as root.
>
> Neither matters today because production runs the processes natively, not from
> this image. If you containerise production, fix both first.

Build:

```bash
cd backend && docker build -t hirebuddha-backend .
```

---

## 5. Environment configuration

### 5.1 The design decision

Only **core application settings** live in environment variables. Every
third-party credential — AI providers, Twilio, Razorpay, social OAuth — is
stored **encrypted in the database** via the Integration Registry
([10 — LLM providers](10-llm-providers.md)).

```mermaid
flowchart LR
    subgraph Env["backend/.env - infrastructure only"]
        E1["DATABASE_URL"]
        E2["REDIS_URL"]
        E3["SECRET_KEY"]
        E4["INTERNAL_TOKEN"]
        E5["CORS_ORIGINS"]
    end
    subgraph DB["integration_registry table - encrypted"]
        D1["Vertex AI credentials"]
        D2["Azure OpenAI keys"]
        D3["Twilio SID and token"]
        D4["Razorpay keys"]
        D5["Social OAuth secrets"]
        D6["internal_cost per SKU"]
    end
    Env --> APP["Application"]
    DB --> APP
```

Consequences worth understanding:

- **Adding a provider needs no redeploy.** An admin adds credentials through the
  UI and they take effect immediately.
- **Credentials are per company**, with an APP-company fallback — impossible
  with env vars.
- **The database is now a secrets store.** Your backup strategy is a secrets
  backup strategy. Treat `deploy/backup/dumps/` accordingly.

### 5.2 Complete `.env` reference

From [backend/.env.example](../../backend/.env.example):

| Variable | Example value | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/hirebuddha` | Postgres DSN. ⚠️ **Change 5432 → 5433** for host dev |
| `REDIS_URL` | `redis://localhost:6379` | Redis DSN |
| `SECRET_KEY` | `dev_secret_key_change_in_production` | JWT signing key |
| `ALGORITHM` | `HS256` | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access-token lifetime |
| `GATEWAY_PORT` | `8001` | Gateway bind port |
| `BACKEND_URL` | `http://localhost:8000` | Where the gateway proxies REST |
| `INTERNAL_TOKEN` | `change-me-in-production` | Shared secret for `POST /internal/event` |
| `JWT_SECRET` | `change-me-in-production` | Gateway-level auth for audio/video WS handshake |
| `STREAMING_HOST` | `localhost:8001` | Public hostname used to build WS URLs for telephony |
| `STREAMING_PROTOCOL` | `ws` | `ws` locally, `wss` in production |
| `VIDEO_STREAMING_ENABLED` | `true` | WebRTC on/off |
| `STUN_SERVERS` | `stun:stun.l.google.com:19302` | ICE servers |
| `TURN_SERVER_URL` | *(commented out)* | Optional TURN relay |
| `TURN_USERNAME` | *(commented out)* | TURN credential |
| `TURN_CREDENTIAL` | *(commented out)* | TURN credential |
| `EVENT_BUS_TYPE` | `memory` | Event bus backend |
| `EVENT_BUS_MAXSIZE` | `1000` | In-memory queue depth |
| `CORS_ORIGINS` | `http://localhost:3000,https://dev.hirebuddha.com,...` | Comma-separated allowed origins |

Note `SECRET_KEY` and `JWT_SECRET` are **separate** — the backend signs user
JWTs with `SECRET_KEY`, while the gateway validates streaming handshakes with
`JWT_SECRET`. In compose, `JWT_SECRET` is fed from `${SECRET_KEY}`, so they
match there; in a hand-rolled `.env` they can drift apart, which produces
confusing "invalid token" failures on WebSocket connect only.

> ⚠️ `EVENT_BUS_TYPE=memory` means the event bus is **per-process and in-memory**.
> Events published in the gateway are not visible to the backend or the worker.
> This is a hard constraint on running multiple gateway instances — see
> [13 — Gateway and realtime](13-gateway-and-realtime.md) and
> [§17](#17-scaling-limits).

> ⚠️ **`backend/.env` is committed to the working tree** (it exists alongside
> `.env.example` and is byte-identical at 2165 bytes). Confirm it is in
> `.gitignore` before putting real secrets in it.

CORS origins are also hard-coded in
[main.py:11-20](../../backend/src/main.py:11) in addition to the env var — the
hard-coded list is what the backend actually uses. Adding a new frontend origin
requires a code change there, not just an env edit.

---

## 6. Starting and stopping services

### 6.1 `start_services.sh`

```mermaid
flowchart TD
    A["Check backend/.env exists"] -->|missing| FAIL["Exit 1"]
    A -->|present| B["1/5 docker compose up -d db redis"]
    B --> C{"Port 8000 in use?"}
    C -->|yes| CS["Skip"]
    C -->|no| C1["2/5 nohup uvicorn src.main:app --reload"]
    C1 --> C2["Write backend_api.pid, wait_for_service"]
    CS --> D{"Port 8001 in use?"}
    C2 --> D
    D -->|yes| DS["Skip"]
    D -->|no| D1["3/5 nohup uvicorn src.gateway.app:app --reload"]
    DS --> E{"pgrep arq worker?"}
    D1 --> E
    E -->|running| ES["Skip"]
    E -->|no| E1["4/5 nohup python -m arq src.ai.worker.WorkerSettings"]
    ES --> F{"Port 3000 in use?"}
    E1 --> F
    F -->|yes| FS["Skip"]
    F -->|no| F1["5/5 nohup npm run dev -- --host 0.0.0.0"]
    FS --> G["Print summary"]
    F1 --> G
```

Two helper functions do the heavy lifting:

```bash
# start_services.sh
check_port() {
    local port=$1
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1 ; then
        return 0  # Port is in use
    fi
    return 1
}

wait_for_service() {
    # polls check_port up to 30 times, 1s apart
}
```

Every step is **idempotent** — an already-occupied port is skipped with a
warning rather than causing a failure. Re-running the script to bring up one
crashed service is safe.

The Arq worker is detected by process name rather than port:

```bash
if pgrep -f "arq src.ai.worker.WorkerSettings" > /dev/null; then
```

All services run with `--reload`, including in the "production" path. That is
convenient but means a syntax error in a saved file takes down a live service.

### 6.2 `stop_services.sh`

Shuts down in reverse dependency order — frontend, worker, backend, gateway,
Docker — using a belt-and-braces approach per service:

1. Kill by PID file (`kill`, then `kill -9`)
2. `pkill -f <pattern>`
3. `kill -9 $(lsof -t -i:<port>)`

```mermaid
flowchart LR
    S1["1/5 Frontend 3000"] --> S2["2/5 Arq worker"]
    S2 --> S3["3/5 Backend 8000"]
    S3 --> S4["4/5 Gateway 8001"]
    S4 --> S5["5/5 docker compose down"]
```

> ⚠️ It runs a blanket `pkill -f "uvicorn"`. If you have **any other uvicorn
> application running on this machine**, it will be killed too. It also does not
> stop the voice service explicitly — only the blanket `pkill` catches it.

`docker compose down` stops the containers but keeps the named volumes, so your
data survives a stop/start cycle.

### 6.3 Starting the voice service

Not covered by the scripts. By hand:

```bash
cd backend && .venv/bin/python -m uvicorn src.voice.main:app --host 0.0.0.0 --port 8002 --reload
```

See [12 — Voice and telephony](12-voice-and-telephony.md).

---

## 7. Production VM provisioning

[setup_production_vm.sh](../../setup_production_vm.sh) is an eight-step
idempotent installer for Ubuntu 22.04/24.04.

```mermaid
flowchart TD
    S1["1/8 apt update + essential packages<br/>curl wget git build-essential lsof jq libpq-dev libffi-dev libssl-dev"]
    S1 --> S2["2/8 Python 3.12 via deadsnakes PPA<br/>+ update-alternatives"]
    S2 --> S3["3/8 Poetry via install.python-poetry.org<br/>+ PATH in .bashrc"]
    S3 --> S4["4/8 Node.js 20 LTS via NodeSource"]
    S4 --> S5["5/8 Docker CE + compose plugin<br/>+ usermod -aG docker"]
    S5 --> S6["6/8 python3 -m venv .venv + poetry install"]
    S6 --> S7["7/8 npm install --legacy-peer-deps"]
    S7 --> S8["8/8 cp .env.example .env if absent"]
    S8 --> DONE["Print versions + next steps"]
```

Every step guards against re-running:

```bash
# setup_production_vm.sh
if python3 --version 2>/dev/null | grep -q "3.1[2-9]"; then
    echo -e "${YELLOW}Python 3.12+ already installed: $(python3 --version)${NC}"
else
    sudo add-apt-repository ppa:deadsnakes/ppa -y
    ...
fi
```

What it deliberately does **not** do:

| Not done | Why it matters |
|---|---|
| Run migrations | Printed as next step 3 |
| Seed the admin user | Printed as next step 4 |
| Start services | Printed as next step 5 |
| Install or configure Apache | Separate — `deploy/apache/setup_apache.sh` |
| Configure a firewall | No `ufw` rules are set anywhere in the repo |
| Create systemd units | Services are `nohup`, not supervised |

**After `usermod -aG docker $USER` you must log out and back in** before Docker
commands work without `sudo`. The script warns about this.

> ⚠️ The script installs **Python 3.12** while `pyproject.toml` targets
> `python = "^3.11"` and the Dockerfile uses `python:3.11-slim`. Three different
> Python versions across three surfaces. 3.12 satisfies the `^3.11` constraint,
> but note `audioop-lts` is conditionally pinned for `python >= 3.13`, so the
> audio path has version-sensitive dependencies. Local dev and production may
> not be running the same interpreter.

---

## 8. Apache — reverse proxy and TLS

Five subdomains, each with an HTTP and an HTTPS (`-le-ssl`) config, installed by
[deploy/apache/setup_apache.sh](../../deploy/apache/setup_apache.sh).

| Subdomain | Proxies to | Config |
|---|---|---|
| `app.hirebuddha.com` | `localhost:3000` | [app.hirebuddha.com-le-ssl.conf](../../deploy/apache/app.hirebuddha.com-le-ssl.conf) |
| `dev.hirebuddha.com` | `localhost:3000` | [dev.hirebuddha.com-le-ssl.conf](../../deploy/apache/dev.hirebuddha.com-le-ssl.conf) |
| `api.hirebuddha.com` | `localhost:8001` | [api.hirebuddha.com-le-ssl.conf](../../deploy/apache/api.hirebuddha.com-le-ssl.conf) |
| `gateway.hirebuddha.com` | `localhost:8001` | [gateway.hirebuddha.com-le-ssl.conf](../../deploy/apache/gateway.hirebuddha.com-le-ssl.conf) |
| `streaming.hirebuddha.com` | `localhost:8002` | [streaming.hirebuddha.com-le-ssl.conf](../../deploy/apache/streaming.hirebuddha.com-le-ssl.conf) |

> ⚠️ **`api` and `gateway` both point at 8001. Nothing proxies to port 8000.**
> Both vhosts `ProxyPass / http://localhost:8001/`
> ([api.hirebuddha.com.conf:7](../../deploy/apache/api.hirebuddha.com.conf:7),
> [gateway.hirebuddha.com.conf:7](../../deploy/apache/gateway.hirebuddha.com.conf:7)),
> so `api.hirebuddha.com` and `gateway.hirebuddha.com` are two names for the
> same Unified Gateway. The backend API on 8000 has **no public vhost** — it is
> reachable only from inside the VM, which is exactly what
> [02 §1](02-system-architecture.md#1-the-60-second-version) means by "nothing
> external talks to port 8000 directly".
>
> Two other places in the tree disagree and are **wrong about the `gateway`
> row**: the root [README.md:46](../../README.md:46) routing table and the
> [setup_apache.sh:156](../../deploy/apache/setup_apache.sh:156) banner both
> claim `gateway.hirebuddha.com` → 8000 (Backend API). Both are right that
> `api.hirebuddha.com` → 8001. Trust the `.conf` files — they are what Apache
> actually loads.

### 8.1 The WebSocket upgrade pattern

Every streaming vhost uses the same structure, and **order matters**:

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

```mermaid
flowchart TD
    REQ["Incoming request"] --> UP{"Upgrade: websocket header?"}
    UP -->|yes| P1{"Path /stream/*?"}
    P1 -->|yes| WS1["Proxy to ws://127.0.0.1:PORT/stream/*"]
    P1 -->|no| P2{"Path /webhooks/voice/tata/*?"}
    P2 -->|yes| WS2["Proxy to ws://127.0.0.1:PORT/webhooks/voice/tata/*"]
    P2 -->|no| HTTP
    UP -->|no| HTTP["ProxyPass to http://localhost:PORT/"]
```

Three things to remember:

- **`RewriteRule` must precede `ProxyPass`.** `ProxyPass` matches greedily on
  `/`; if it comes first, the upgrade rules never run and WebSockets silently
  degrade to failed HTTP requests.
- **`ProxyTimeout 86400`** (24 hours) keeps long-lived voice calls from being cut
  by the proxy.
- **Two upgrade paths** are needed: the generic `/stream/*` and the Tata Tele
  telephony path `/webhooks/voice/tata/*`, which starts as an HTTP webhook and
  then upgrades on the same path prefix.

The `RewriteRule` targets use `127.0.0.1` while `ProxyPass` uses `localhost` —
functionally the same here, just inconsistent.

### 8.2 TLS

Let's Encrypt via Certbot. Each vhost includes:

```apache
SSLCertificateFile /etc/letsencrypt/live/<domain>/fullchain.pem
SSLCertificateKeyFile /etc/letsencrypt/live/<domain>/privkey.pem
Include /etc/letsencrypt/options-ssl-apache.conf
```

> ⚠️ **`streaming.hirebuddha.com` uses `gateway.hirebuddha.com`'s certificate.**
> Both `SSLCertificateFile` lines point at
> `/etc/letsencrypt/live/gateway.hirebuddha.com/`. That will produce a hostname
> mismatch unless the gateway certificate carries `streaming.hirebuddha.com` as
> a SAN. Verify with:
> ```bash
> openssl s_client -connect streaming.hirebuddha.com:443 -servername streaming.hirebuddha.com < /dev/null 2>/dev/null | openssl x509 -noout -text | grep -A1 "Subject Alternative Name"
> ```

Both streaming vhosts also log to `example-error.log` / `example-access.log` —
placeholder names that were never customised, so gateway and streaming traffic
land in the same files.

Renewal is Certbot's own systemd timer. Verify with:

```bash
sudo certbot renew --dry-run
```

Required Apache modules: `mod_ssl`, `mod_proxy`, `mod_proxy_http`,
`mod_proxy_wstunnel`, `mod_rewrite`, `mod_headers`, and optionally
`mod_evasive`.

---

## 9. Security hardening at the edge

[hirebuddha-security.conf](../../deploy/apache/hirebuddha-security.conf) is
applied globally via `a2enconf`. It is unusually thorough and clearly written in
response to real attack traffic — the comments cite log-analysis dates.

```mermaid
flowchart TB
    REQ["Request"] --> L1["1 Security headers"]
    L1 --> L2["2 IP blocklist - 24 addresses"]
    L2 --> L3["3 Path pattern blocks"]
    L3 --> L4["4 mod_evasive rate limiting"]
    L4 --> L5["5 Request size limits"]
    L5 --> APP["Application"]

    L2 -.blocked.-> DENY["403"]
    L3 -.blocked.-> DENY
    L4 -.blocked.-> DENY
```

### 9.1 Response headers

```apache
Header always set X-Content-Type-Options "nosniff"
Header always set X-Frame-Options "SAMEORIGIN"
Header always set X-XSS-Protection "1; mode=block"
Header always set Referrer-Policy "strict-origin-when-cross-origin"
Header always set Permissions-Policy "camera=(), microphone=(self), geolocation=()"
Header always unset X-Powered-By
Header always unset Server
```

`Permissions-Policy` allows `microphone=(self)` — required for the browser audio
capture in the streaming pages — while denying camera and geolocation.

> There is no `Strict-Transport-Security` (HSTS) header and no
> `Content-Security-Policy`. Both would be reasonable additions.

### 9.2 IP blocklist

24 addresses in two dated batches (2026-03-16 and 2026-04-07), each annotated
with what it was caught doing — Next.js fingerprinting, credential harvesting,
LFI path traversal, PHP webshell scanning, Hikvision IoT probing, and
"AI credential probing (`anthropic.json`, `secrets.py`)".

Wrapped in `<Location "/">` with `<RequireAll>` so `Require not ip` directives
are valid in server config.

This is a manually curated list. It will grow stale; it is not a substitute for
fail2ban or a WAF.

### 9.3 Path blocks

| Pattern | Blocks |
|---|---|
| `\.\.[/\\]` in URI or request | Path traversal / LFI |
| `CONNECT` method | Open-proxy abuse |
| `allow_url_include`, `auto_prepend_file`, `php://input` in query | PHP RCE |
| `^/\.` | Any dotfile — `.env`, `.git`, `.aws`, `.kube` |
| `/[^/]*\.env` | `.env` in any subdirectory |
| `config.(json\|php\|yml)`, `docker-compose.yml`, `credentials`, `phpinfo` | Config harvesting |
| `wp-login`, `wp-admin`, `xmlrpc.php`, `wlwmanifest.xml` | WordPress scanning |
| `\.php$` | **All PHP** — this is a Python app |
| `vendor/phpunit`, `phpmyadmin`, `adminer`, … | PHPUnit RCE, DB admin probing |
| `SDK/webLanguage`, `onvif`, `ISAPI` | Hikvision CVE-2021-36260 |
| `anthropic.json`, `openai.json`, `secrets.py`, `api.?keys?` | AI credential probing |
| ~40 VoIP/SIP provisioning paths | SIP scanners |
| `\.(cfg\|bak\|old\|orig\|sql\|tar\|gz\|zip\|rar\|7z)$` | Backup/archive probing |
| `solr`, `actuator`, `cgi-bin`, `console`, `debug`, `trace` | Service discovery |
| `^/(uploads\|shell\|cmd\|c99\|r57\|webshell)` | Shell directories |

> ⚠️ **`^/(uploads...)` conflicts with a real route.**
> [main.py:72](../../backend/src/main.py:72) mounts static files at `/uploads`
> for profile pictures. This Apache rule denies `/uploads/...` outright, so
> profile images served from that mount will 403 in production. Either rename
> the mount or carve an exception.

### 9.4 Rate limiting and size limits

```apache
<IfModule mod_evasive20.c>
    DOSPageCount        15
    DOSPageInterval     1
    DOSSiteCount        100
    DOSSiteInterval     1
    DOSBlockingPeriod   300
    DOSWhitelist        127.0.0.1
    DOSWhitelist        10.160.0.*
    DOSWhitelist        172.21.0.*
    DOSWhitelist        152.56.13.*
</IfModule>

LimitRequestBody 10485760
LimitRequestFields 100
LimitRequestFieldSize 8190
LimitRequestLine 8190
```

The comments note both DOS counts were raised from their defaults (5→15, 50→100)
because the **Vite dev server** loads 30–50 modules per page and HMR polls
rapidly — a nice illustration of dev tooling driving production config.

`LimitRequestBody` is **10 MB**. Document uploads larger than that will fail at
Apache before reaching the app. If you raise the app's upload limit, raise this
too.

---

## 10. The sandbox and egress-proxy containers

Two purpose-built images under `backend/docker/`, used by the sandbox tools
described in [09 — Tools](09-tools.md).

```mermaid
flowchart LR
    AGENT["Agent tool call"] --> SBX["Sandbox container<br/>backend/docker/sandbox"]
    SBX -->|all outbound traffic| EGR["Egress proxy<br/>tinyproxy"]
    EGR -->|allowlist| NET["Internet"]
    EGR -.denied.-> BLOCK["Blocked"]
    SBX -.no direct route.-> NET

    style EGR fill:#4a3a2d,stroke:#a85
```

| Directory | Files | Purpose |
|---|---|---|
| [docker/sandbox](../../backend/docker/sandbox) | `Dockerfile`, `README.md`, `build.sh`, `requirements.txt` | The container agent code executes in |
| [docker/egress-proxy](../../backend/docker/egress-proxy) | `Dockerfile`, `README.md`, `build.sh`, `entrypoint.sh`, `tinyproxy.conf` | Forced-proxy network boundary |

The egress proxy is **tinyproxy** with an allowlist config. Sandboxed code has no
direct network route; everything must traverse the proxy, which enforces the
allowlist. This is the network half of the sandbox isolation model — the process
and filesystem half is documented in [09 — Tools](09-tools.md).

Each directory has its own `build.sh` and `README.md`. Read those before
changing either image; the network policy in particular is security-critical.

Container naming follows `hb-sandbox-<COMPANY>` and `hb-sandbox-<COMPANY>-egress`,
so containers are per-tenant. The `sandbox.container_runtime_enabled` feature
flag (default ON) gates the whole mechanism — see
[15 — Governance and flags](15-governance-and-hitl.md).

---

## 11. Database operations

### 11.1 Alembic configuration

[backend/alembic.ini](../../backend/alembic.ini):

```ini
script_location = %(here)s/migrations
sqlalchemy.url = driver://user:pass@localhost/dbname
```

The `sqlalchemy.url` in the ini file is a **placeholder** — the real URL comes
from `DATABASE_URL` via `migrations/env.py`. Do not edit it.

`env.py`'s `target_metadata` includes **both** the host `Base.metadata` and
`cortex_memory.metadata`, so the extracted CORTEX package's tables are migrated
by the host — see [08 — Memory and CORTEX](08-memory-and-cortex.md).

### 11.2 Common commands

```bash
cd backend && .venv/bin/alembic upgrade head
```

```bash
cd backend && .venv/bin/alembic revision --autogenerate -m "add widget table"
```

```bash
cd backend && .venv/bin/alembic downgrade -1
```

```bash
cd backend && .venv/bin/alembic current && .venv/bin/alembic history --verbose
```

Always read an autogenerated migration before applying it — autogenerate does
not reliably detect column renames, index changes on JSONB, or pgvector index
definitions.

### 11.3 pgvector

The `pgvector/pgvector:pg15` image ships the extension, but a migration must
still `CREATE EXTENSION IF NOT EXISTS vector`. Verify:

```bash
psql -h localhost -p 5433 -U postgres -d hirebuddha -c "SELECT extname, extversion FROM pg_extension WHERE extname='vector';"
```

If you point `DATABASE_URL` at a stock Postgres without pgvector, migrations
that create `Vector(768)` columns will fail.

### 11.4 Utility scripts

| Script | Purpose |
|---|---|
| [db-scripts/seed_admin_user.py](../../backend/db-scripts/seed_admin_user.py) | Create the first `app_admin` user and APP company |
| [db-scripts/clean_db.sql](../../backend/db-scripts/clean_db.sql) | ⚠️ Wipe data — read it before running |
| [db-scripts/backfill_cortex_trees.py](../../backend/db-scripts/backfill_cortex_trees.py) | Backfill CORTEX trees for existing entities |
| [scripts/seed_sandbox_sku.py](../../backend/scripts/seed_sandbox_sku.py) | Register the sandbox billing SKU |
| [scripts/migrations/](../../backend/scripts/migrations/) | One-off data migrations (moved here from `src/ai/`) |
| [scripts/seeds/](../../backend/scripts/seeds/) | Default entity seeds — `SeedAutonomousBI`, `SeedDocumentFactory`, `SeedDocFactoryLite`, `deep_research/` |
| [scripts/record_golden_runs.py](../../backend/scripts/record_golden_runs.py) | Regenerate parity goldens — see [19 — Testing](19-testing.md) |

---

## 12. Backups

[deploy/backup/db_backup.sh](../../deploy/backup/db_backup.sh) is a monthly
`pg_dump` with 90-day retention.

```mermaid
flowchart LR
    CRON["cron: 0 2 1 * *<br/>1st of month, 02:00"] --> DUMP["pg_dump --no-owner --no-privileges<br/>--format=plain --verbose"]
    DUMP --> GZ["gzip"]
    GZ --> FILE["dumps/hirebuddha_backup_TIMESTAMP.sql.gz"]
    FILE --> PRUNE["Delete files older than<br/>RETENTION_DAYS = 90"]
    DUMP --> LOG["logs/backup_TIMESTAMP.log"]
```

Configurable via environment variables, all with defaults:

| Variable | Default |
|---|---|
| `DB_HOST` | `localhost` |
| `DB_PORT` | `5433` |
| `DB_NAME` | `hirebuddha` |
| `DB_USER` | `postgres` |
| `BACKUP_ROOT` | `.../deploy/backup/dumps` |
| `LOG_DIR` | `.../deploy/backup/logs` |
| `RETENTION_DAYS` | `90` |

Install the cron entry with
[deploy/backup/setup_cron.sh](../../deploy/backup/setup_cron.sh).

Restore:

```bash
gunzip -c deploy/backup/dumps/hirebuddha_backup_2026-08-01_020000.sql.gz | psql -h localhost -p 5433 -U postgres -d hirebuddha
```

> ⚠️ **Monthly backups mean up to 31 days of potential data loss.** For a
> platform holding conversation transcripts, billing ledgers and encrypted
> third-party credentials, that is a very long RPO. Consider daily dumps plus
> WAL archiving. Also note `BACKUP_ROOT` defaults to a path inside the repo
> (`/home/rahul/workspace/hb-proto-3/...` — an older checkout path), so backups
> live on the same disk as the database. A disk failure loses both.
>
> The hard-coded paths in the script header reference `hb-proto-3`, not this
> checkout's directory name. Override `BACKUP_ROOT` and `LOG_DIR` or fix the
> defaults before relying on it.

---

## 13. Continuous integration

There is exactly **one** GitHub Actions workflow:
[.github/workflows/cortex-memory.yml](../../.github/workflows/cortex-memory.yml).

```mermaid
flowchart TD
    TRIG["push or PR touching<br/>backend/cortex_memory/**"] --> J1["job: test"]
    TRIG --> J2["job: build"]
    J1 --> M["matrix: Python 3.10, 3.11, 3.12"]
    M --> SVC["service: pgvector/pgvector:pg16"]
    SVC --> I["pip install -e cortex_memory[dev]"]
    I --> T1["mypy --strict on package modules"]
    T1 --> T2["coverage run pytest<br/>--fail-under=85"]
    J2 --> B1["python -m build - sdist + wheel"]
    B1 --> B2["upload-artifact cortex-memory-dist"]
```

| Aspect | Value |
|---|---|
| Trigger | `push` / `pull_request` on `paths: ["backend/cortex_memory/**"]` |
| Python matrix | 3.10, 3.11, 3.12 |
| Postgres | `pgvector/pgvector:pg16` with healthcheck |
| Type gate | `mypy --strict --follow-imports=silent --exclude '/(tests\|examples)/'` |
| Coverage gate | `--fail-under=85` |
| Build | sdist + wheel, uploaded as an artifact |

> ⚠️ **The main application has no CI.** This workflow only fires on changes
> under `backend/cortex_memory/**` — the extracted package. Nothing in GitHub
> Actions runs `backend/tests/`, the layout lint, ruff, black, or the frontend
> build. The `run_ci_matrix.sh` script below describes lanes that are **not
> wired to any CI trigger**; they must be run manually.

Note the workflow header anticipates the package moving to its own repo:

```yaml
# .github/workflows/cortex-memory.yml
# In-repo the package lives flat in backend/cortex_memory/ (its pyproject maps
# the import package to "."). When it moves to its own repo this becomes the
# repo-root workflow; only the working-directory / paths change.
```

The in-repo copy is at `backend/cortex_memory_moved_to_pypi_repo/`, so the
workflow's `paths` filter (`backend/cortex_memory/**`) **does not match the
directory that currently exists**. As checked out, this workflow never fires.

### 13.1 The intended CI matrix

[backend/scripts/run_ci_matrix.sh](../../backend/scripts/run_ci_matrix.sh)
defines three lanes:

```bash
# backend/scripts/run_ci_matrix.sh
#   fast      — every PR. Unit + layout lint + fast integration tests.
#   nightly   — chaos + parity + regression. Skipped on PR.
#   migration — Alembic upgrade head + downgrade -1 + upgrade head.
```

```bash
cd backend && scripts/run_ci_matrix.sh fast
```

`DATABASE_URL` is required for the integration, chaos and migration lanes; the
script never starts containers itself. See [19 — Testing](19-testing.md).

---

## 14. Code-quality gates

### 14.1 `lint_ai_layout.py` — architectural rules

[backend/scripts/lint_ai_layout.py](../../backend/scripts/lint_ai_layout.py)
enforces the shape of `backend/src/ai/` mechanically.

**Per-package line caps.** No single file in these packages may exceed its cap:

```python
# backend/scripts/lint_ai_layout.py
MAX_LINES: dict[str, int] = {
    "core": 1500,         # agent_loop.py is 1480 (loop + suspend/resume).
    "planning": 700,
    "memory": 1200,       # cortex_service.py is 1117 (CORTEX engine).
    "meta": 900,          # platform_schema_compiler.py is 839.
    "governance": 600,
    "tools": 1000,
    "llm": 800,
    "shared": 400,
}
```

The comments record how close the largest file in each package sits to its cap —
`core` at 1480/1500 is 20 lines from failing. **Adding to `agent_loop.py` will
break the build.** That is the point: the cap forces extraction rather than
accretion.

**Forbidden imports:**

```python
FORBIDDEN_IMPORT_PATTERNS: list[str] = [
    "from src.ai.worker import ",
    "import src.ai.worker",
]

FORBIDDEN_ALIAS_PATTERNS: list[str] = [
    " as CortexService",       # the CortexRouter alias dance — Track 0 killed it
]
```

`worker.py` must stay minimal — only `WorkerSettings` and cron registration — so
nothing may import from it. Import the canonical location instead.

**Top-level file allowlist.** `ALLOWED_TOPLEVEL` plus `TRANSITIONAL_TOPLEVEL`
govern which files may sit directly in `src/ai/`. New top-level files are
rejected; the transitional set is the backlog of modules still awaiting a move
into a subpackage.

**Tools root allowlist:**

```python
TOOLS_ROOT_ALLOWED = {"__init__.py", "base.py", "resilience.py", "README.md"}
```

Every tool must live in a category subdirectory.

```mermaid
flowchart TD
    LINT["lint_ai_layout.py"] --> C1["Top-level file allowlist"]
    LINT --> C2["Per-package MAX_LINES"]
    LINT --> C3["Forbidden import patterns"]
    LINT --> C4["Forbidden alias patterns"]
    LINT --> C5["tools/ root allowlist"]
    C1 --> FAIL{"any violation?"}
    C2 --> FAIL
    C3 --> FAIL
    C4 --> FAIL
    C5 --> FAIL
    FAIL -->|yes| X["Non-zero exit - CI fails"]
    FAIL -->|no| OK["Pass"]
```

```bash
cd backend && .venv/bin/python scripts/lint_ai_layout.py
```

### 14.2 `typecheck_ai.py` — incremental strict typing

```bash
cd backend && .venv/bin/python scripts/typecheck_ai.py
```

Whole-tree `mypy --strict` is not green yet, so this gate maintains a **growing
allowlist** of packages that must pass strictly. From the script docstring:
*"allowlisted packages are type-checked strictly, but errors in the modules they
import are silenced"* — via `--follow-imports=silent`.

`pyproject.toml` sets the shared baseline so editor and manual mypy runs agree
with the gate:

```toml
# backend/pyproject.toml
[tool.mypy]
python_version = "3.11"
ignore_missing_imports = true
```

### 14.3 Formatters and linters

```toml
# backend/pyproject.toml
[tool.ruff]
line-length = 88
target-version = "py311"
select = ["E", "F", "I", "B"]
ignore = []

[tool.ruff.isort]
known-first-party = ["src"]
```

| Gate | Command | Enforces |
|---|---|---|
| ruff | `.venv/bin/ruff check src/` | pycodestyle (E), pyflakes (F), isort (I), bugbear (B) |
| black | `.venv/bin/black src/` | Formatting, 88 columns |
| mypy | `.venv/bin/python scripts/typecheck_ai.py` | Strict typing on the allowlist |
| layout | `.venv/bin/python scripts/lint_ai_layout.py` | Architecture and line caps |
| frontend lint | `cd frontend && npm run lint` | ESLint, `--max-warnings 0` |
| frontend build | `cd frontend && npm run build` | `tsc` then `vite build` |

`npm run lint` runs with `--max-warnings 0`, so a warning fails it.
`npm run build` runs `tsc` first, so type errors fail the build.

---

## 15. Observability dashboards

[infra/dashboards/](../../infra/dashboards/) holds SQL queries, not a dashboard
tool. Point Grafana, Metabase or `psql` at them.

| File | Covers |
|---|---|
| [phase11/01_run_health.sql](../../infra/dashboards/phase11/01_run_health.sql) | Run success/failure rates |
| [phase11/02_cost.sql](../../infra/dashboards/phase11/02_cost.sql) | Cost aggregation |
| [phase11/03_critic_pipeline.sql](../../infra/dashboards/phase11/03_critic_pipeline.sql) | Critic verdict distribution |
| [phase11/04_meta_agent.sql](../../infra/dashboards/phase11/04_meta_agent.sql) | Board decisions and promotions |
| [phase11/05_memory.sql](../../infra/dashboards/phase11/05_memory.sql) | CORTEX tree and node growth |
| [phase11/06_loop_telemetry.sql](../../infra/dashboards/phase11/06_loop_telemetry.sql) | Iterations, budget pressure |
| [phase12/01_csat.sql](../../infra/dashboards/phase12/01_csat.sql) | Thumbs up/down on runs |
| [phase12/02_sandbox_mcp_cost.sql](../../infra/dashboards/phase12/02_sandbox_mcp_cost.sql) | Sandbox and MCP spend |
| [phase12/03_tool_synthesis_trust.sql](../../infra/dashboards/phase12/03_tool_synthesis_trust.sql) | Synthesised-tool trust scores |

Application-level telemetry (OpenTelemetry, Prometheus) is wired in
[common/telemetry.py](../../backend/src/common/telemetry.py) and initialised at
[main.py:190](../../backend/src/main.py:190) — see
[02 — System architecture](02-system-architecture.md).

---

## 16. Runbooks

### 16.1 Deploy a new version

```bash
cd /path/to/hire-buddha-app && ./stop_services.sh && git pull && cd backend && poetry install && .venv/bin/alembic upgrade head && cd ../frontend && npm install --legacy-peer-deps && cd .. && ./start_services.sh
```

There is **no zero-downtime path** — the stack goes down for the duration.

### 16.2 Restart one service

```bash
kill $(cat logs/backend_api.pid) && ./start_services.sh
```

`start_services.sh` skips services whose ports are already occupied, so it
restarts only the one you killed.

### 16.3 Tail logs

```bash
tail -f logs/backend_api.log logs/unified_gateway.log logs/arq_worker.log logs/frontend.log
```

### 16.4 Inspect the Arq queue

```bash
redis-cli --scan --pattern 'arq:*' | head -50
```

Queue depth:

```bash
redis-cli LLEN arq:queue
```

### 16.5 Drain and restart the worker

```bash
kill $(cat logs/arq_worker.pid) && sleep 5 && cd backend && nohup .venv/bin/python -m arq src.ai.worker.WorkerSettings > ../logs/arq_worker.log 2>&1 &
```

In-flight jobs are lost. Runs stuck in `RUNNING` will need manual reconciliation.

### 16.6 Clear the queue (destructive)

```bash
redis-cli --scan --pattern 'arq:*' | xargs -r redis-cli DEL
```

This discards queued work. Only do it when the queue is poisoned.

### 16.7 Investigate high latency

```mermaid
flowchart TD
    SLOW["Requests are slow"] --> Q1{"Which surface?"}
    Q1 -->|frontend| F["Check logs/frontend.log<br/>Vite HMR storms"]
    Q1 -->|API| A1{"DB or app?"}
    A1 -->|DB| A2["pg_stat_activity for long queries<br/>check pgvector index exists"]
    A1 -->|app| A3["Check worker queue depth<br/>runs blocked on HITL hold worker slots"]
    Q1 -->|WebSocket drops| W["ProxyTimeout in Apache vhost<br/>should be 86400"]
    A3 --> HITL["SELECT count(*) FROM human_approvals WHERE status='PENDING'"]
```

Long-running queries:

```bash
psql -h localhost -p 5433 -U postgres -d hirebuddha -c "SELECT pid, now()-query_start AS dur, state, left(query,120) FROM pg_stat_activity WHERE state <> 'idle' ORDER BY dur DESC LIMIT 20;"
```

A common cause of slow AI runs is a **missing pgvector index** — every semantic
search degrades to a sequential scan. See
[08 — Memory and CORTEX §18](08-memory-and-cortex.md#18-cost-performance-and-tuning).

Another is **HITL checkpoints holding worker slots** — see
[15 — Governance §8.5](15-governance-and-hitl.md#85-operational-implications-of-a-blocking-wait).

### 16.8 Recover from a full disk

Likely culprits, in order:

```bash
du -sh logs/ backend/artifact/ deploy/backup/dumps/ /var/log/apache2/ 2>/dev/null | sort -h
```

| Directory | Why it grows | Safe action |
|---|---|---|
| `logs/` | No rotation configured | Truncate old logs |
| `backend/artifact/system-generated/` | Every generated PDF/XLSX | Archive and prune |
| `deploy/backup/dumps/` | Monthly dumps, 90-day retention | Move off-box |
| `/var/log/apache2/` | `example-access.log` from two vhosts | logrotate |

> ⚠️ **No log rotation is configured for `logs/`.** The `nohup` output files grow
> without bound. Add a logrotate rule — this is the most likely cause of a full
> disk on a long-lived VM.

### 16.9 Rotate a secret

For `SECRET_KEY` / `INTERNAL_TOKEN` / `JWT_SECRET`: edit `backend/.env`, then
restart all services. Rotating `SECRET_KEY` invalidates every issued JWT, so all
users are logged out.

For third-party credentials (AI providers, Twilio, Razorpay): rotate them in the
**Integrations UI** — they are in the database, not `.env`. No restart needed;
see [10 — LLM providers](10-llm-providers.md) for the TTL cache behaviour.

### 16.10 Roll back

```bash
./stop_services.sh && git checkout <previous-sha> && cd backend && poetry install && .venv/bin/alembic downgrade -1 && cd .. && ./start_services.sh
```

Only downgrade migrations you have verified are reversible. Many are not.

---

## 17. Scaling limits

Everything runs on one VM, and several design choices assume that.

```mermaid
flowchart TB
    subgraph Current["Today - single VM"]
        A["Apache"] --> P1["All 5 processes"]
        P1 --> D1[("One Postgres")]
        P1 --> R1[("One Redis")]
    end
    subgraph Blockers["What blocks horizontal scaling"]
        B1["EVENT_BUS_TYPE=memory<br/>per-process, not shared"]
        B2["nohup processes<br/>no supervisor, no restart-on-crash"]
        B3["PID-file service management<br/>assumes one host"]
        B4["Feature-flag process cache<br/>60s TTL per process"]
        B5["HITL blocks a worker slot<br/>for up to timeout_ms"]
        B6["Local artifact filesystem<br/>backend/artifact/"]
    end
```

| Constraint | Consequence | Fix direction |
|---|---|---|
| `EVENT_BUS_TYPE=memory` | Events do not cross processes | Switch to a Redis-backed bus |
| `nohup` process management | No auto-restart on crash | systemd units or a supervisor |
| PID files in `logs/` | Single-host assumption | Container orchestration |
| Artifacts on local disk | A second app host cannot serve them | Object storage |
| Single Redis | Queue and pub/sub SPOF | Redis with replication |
| Single Postgres | Data SPOF | Managed Postgres with replicas |
| No health endpoints in the scripts | `wait_for_service` only checks the port is open | Real `/health` probes |
| `--reload` everywhere | Higher memory, filesystem watching | Drop `--reload` in production |

The realistic first steps, in order: systemd units for supervision, log rotation,
a Redis-backed event bus, then moving artifacts to object storage.

---

## 18. Key files reference

| File | What it does |
|---|---|
| [setup_production_vm.sh](../../setup_production_vm.sh) | 8-step idempotent VM provisioner |
| [start_services.sh](../../start_services.sh) | Starts Docker, backend, gateway, worker, frontend |
| [stop_services.sh](../../stop_services.sh) | Reverse-order shutdown with PID / pkill / port fallbacks |
| [backend/docker-compose.yml](../../backend/docker-compose.yml) | `gateway`, `app`, `db`, `redis` |
| [backend/Dockerfile](../../backend/Dockerfile) | Two-stage Poetry build |
| [backend/pyproject.toml](../../backend/pyproject.toml) | All Python deps, ruff/mypy config |
| [backend/alembic.ini](../../backend/alembic.ini) | Migration config |
| [backend/.env.example](../../backend/.env.example) | Complete env template |
| [deploy/apache/setup_apache.sh](../../deploy/apache/setup_apache.sh) | Installs vhosts and enables modules |
| [deploy/apache/hirebuddha-security.conf](../../deploy/apache/hirebuddha-security.conf) | Global edge hardening |
| [deploy/apache/*-le-ssl.conf](../../deploy/apache/) | Five HTTPS vhosts |
| [deploy/backup/db_backup.sh](../../deploy/backup/db_backup.sh) | Monthly pg_dump, 90-day retention |
| [deploy/backup/setup_cron.sh](../../deploy/backup/setup_cron.sh) | Installs the backup cron entry |
| [backend/docker/sandbox/](../../backend/docker/sandbox/) | Agent code-execution image |
| [backend/docker/egress-proxy/](../../backend/docker/egress-proxy/) | tinyproxy network boundary |
| [backend/scripts/lint_ai_layout.py](../../backend/scripts/lint_ai_layout.py) | Architecture lint + line caps |
| [backend/scripts/typecheck_ai.py](../../backend/scripts/typecheck_ai.py) | Incremental strict mypy |
| [backend/scripts/run_ci_matrix.sh](../../backend/scripts/run_ci_matrix.sh) | fast / nightly / migration lanes |
| [.github/workflows/cortex-memory.yml](../../.github/workflows/cortex-memory.yml) | The only GitHub Actions workflow |
| [infra/dashboards/](../../infra/dashboards/) | SQL dashboard queries |
| [QUICK_START.md](../../QUICK_START.md) | Condensed getting-started |

---

## 19. Gotchas

1. **PostgreSQL is on host port 5433, not 5432**, and `.env.example` ships with
   5432. Fix it or nothing connects.

2. **`start_services.sh` does not start the voice service** despite the vhost and
   README implying otherwise. Start port 8002 manually.

3. **`stop_services.sh` runs a blanket `pkill -f "uvicorn"`** — it will kill
   unrelated uvicorn apps on the same machine.

4. **The README's `api`/`gateway` port mapping contradicts the Apache configs.**
   The configs are right: `api` → 8000, `gateway` → 8001.

5. **`streaming.hirebuddha.com` uses the gateway's TLS certificate.** Verify the
   SAN list or expect hostname mismatches.

6. **The Apache security config blocks `/uploads`**, which is a real static mount
   in `main.py`. Profile pictures will 403 in production.

7. **`LimitRequestBody` is 10 MB.** Larger uploads fail at Apache, not the app.

8. **`RewriteRule` for WebSockets must come before `ProxyPass`**, or upgrades
   silently fail.

9. **The Dockerfile's `CMD` uses `--reload` and runs as root.** Not
   production-ready as-is.

10. **Only the extracted `cortex_memory` package has CI**, and its `paths` filter
    (`backend/cortex_memory/**`) does not even match the directory currently in
    the tree (`backend/cortex_memory_moved_to_pypi_repo/`). Effectively there is
    no CI. Run `scripts/run_ci_matrix.sh fast` manually.

11. **`core` is 20 lines from its 1500-line cap.** Adding to `agent_loop.py`
    breaks the layout lint.

12. **`backend/.env` exists in the working tree** and matches `.env.example`
    byte-for-byte. Verify `.gitignore` before adding real secrets.

13. **CORS origins are hard-coded in `main.py`** as well as the env var; the
    hard-coded list is authoritative for the backend.

14. **`EVENT_BUS_TYPE=memory` is per-process.** Cross-process events do not work.

15. **No log rotation for `logs/`.** The most likely cause of a full disk.

16. **Backups are monthly and stored on the same disk**, under a hard-coded
    `hb-proto-3` path that does not match this checkout.

17. **Three different Python versions** across the setup script (3.12),
    `pyproject.toml` (`^3.11`) and the Dockerfile (3.11).

18. **`npm install` needs `--legacy-peer-deps`.** Without it, installation fails
    on React Three Fiber peer conflicts.

19. **`docker compose down -v` deletes your database.** Omit `-v`.

20. **No firewall configuration exists in the repo.** Nothing restricts direct
    access to ports 3000/8000/8001/8002/5433/6379 if the VM is internet-facing.
    Confirm your cloud security groups do that job.

---

## Where to go next

- [02 — System architecture](02-system-architecture.md) — why the topology is
  shaped this way and how the processes talk.
- [19 — Testing](19-testing.md) — what the CI lanes actually run.
- [03 — Data model](03-data-model.md) — the schema the migrations build.
- [09 — Tools](09-tools.md) — the sandbox isolation model these containers
  implement.
- [15 — Governance and flags](15-governance-and-hitl.md) — runtime switches you
  can flip without a deploy.
- [20 — Onboarding and glossary](20-onboarding-and-glossary.md) — the condensed
  day-one path.
