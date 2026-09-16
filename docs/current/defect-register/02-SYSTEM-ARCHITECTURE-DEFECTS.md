# 02. System Architecture & Topology — Defect Register

> **What this document is:** defects in how the processes are wired — ports, config
> defaults, queues, proxies and the boot scripts — plus the improvements that would
> make the topology cheaper and easier to run.
> **Source document:** [`02-system-architecture.md`](../02-system-architecture.md)
> **Compiled:** 2026-09-01, against branch `fresh-main`.
> **Context:** everything runs on **one VM**. Most of what follows only bites when
> that stops being true, or when something restarts at a bad moment.

---

## How to read this file

- **✅ Verified** — the code or config file was read on 2026-09-01 and the claim held.
- **📄 Doc-reported** — taken from `02-system-architecture.md` without a re-check.
- The defects are grouped by how bad the outcome is, not by which file they live in.
- Improvements are separate. They are not bugs; they are places where the current
  shape costs more than it needs to.

---

## Contents

1. [Summary](#1-summary)
2. [T0 — Wrong by default](#2-t0--wrong-by-default)
3. [T1 — Silently does nothing](#3-t1--silently-does-nothing)
4. [T2 — Delete](#4-t2--delete)
5. [T3 — Fragile](#5-t3--fragile)
6. [Improvements](#6-improvements)
7. [Suggested order of work](#7-suggested-order-of-work)

---

## 1. Summary

| Tier | Theme | Count | When to do it |
|---|---|---|---|
| [T0](#2-t0--wrong-by-default) | Wrong by default | 5 | Before the next deployment |
| [T1](#3-t1--silently-does-nothing) | Silently does nothing | 5 | Before relying on the feature |
| [T2](#4-t2--delete) | Delete | 5 | **Now** — free |
| [T3](#5-t3--fragile) | Fragile | 6 | When the area is next touched |

**Total: 21 defects, 10 improvements.**

The three worth reading first:

- **[SA-01](#sa-01--streaming_host-defaults-to-a-service-that-does-not-run)** — the
  default streaming host points at a retired port. Telephony WebSockets fail.
- **[SA-04](#sa-04--five-enqueue-calls-ignore-redis_url-and-hardcode-localhost)** —
  five job enqueues use arq's defaults instead of the configured Redis.
- **[SA-06](#sa-06--the-6-hourly-dreaming-cron-enqueues-a-job-the-worker-cannot-run)** —
  a cron has been firing four times a day for months and every job it schedules is
  rejected.

---

## 2. T0 — Wrong by default

These are defaults that are wrong out of the box. Each one works today only because
someone remembered to override it.

### SA-01 — `STREAMING_HOST` defaults to a service that does not run

**✅ Verified · Critical**

`common/config.py` sets `STREAMING_HOST = "localhost:8002"` and
`STREAMING_PROTOCOL = "ws"`. Port 8002 is the retired voice service. No script starts
it — it is not in `start_services.sh`, `stop_services.sh`, or `docker-compose.yml`.

The webhook router builds the `wss://` URL it hands to Twilio from these two settings.
If `backend/.env` does not override them, every inbound call returns TwiML pointing
telephony at a dead port, and the call fails at the WebSocket handshake.

- [`common/config.py:10`](../../../backend/src/common/config.py:10) — the two defaults
- [`voice/webhook_router.py`](../../../backend/src/voice/webhook_router.py) — where the URL is built

**Fix:** change the defaults to the gateway host and `wss`. The gateway already serves
`/stream/twilio/{id}` and `/stream/tata/{id}` natively.

---

### SA-02 — Apache still proxies `streaming.hirebuddha.com` to the dead port

**✅ Verified · High**

`streaming.hirebuddha.com-le-ssl.conf` still has
`ProxyPass / http://localhost:8002/` and two `RewriteRule`s pointing WebSocket
upgrades at `ws://127.0.0.1:8002/`. Nothing listens there.

This is the other half of [SA-01](#sa-01--streaming_host-defaults-to-a-service-that-does-not-run):
even with the setting fixed, any client that has cached the old host keeps hitting a
dead vhost, and the failure looks like a network problem rather than a config one.

- [`deploy/apache/streaming.hirebuddha.com-le-ssl.conf:12`](../../../deploy/apache/streaming.hirebuddha.com-le-ssl.conf:12), [`:19`](../../../deploy/apache/streaming.hirebuddha.com-le-ssl.conf:19)

**Fix:** repoint both vhosts at 8001, or delete them. This is step 3 of **W-1** in the
platform register.

---

### SA-03 — The gateway's default database port is wrong

**✅ Verified · High**

`UnifiedGatewaySettings.DATABASE_URL` defaults to
`postgresql+asyncpg://postgres:postgres@localhost:5432/hirebuddha`. Docker maps
Postgres to host port **5433**, not 5432. Every other config in the tree uses 5433.

The gateway needs the database for the dispatcher and `SessionManager`. With the
default in play it cannot connect at all.

- [`gateway/gateway_config.py:28`](../../../backend/src/gateway/gateway_config.py:28)

**Fix:** change the default to 5433 so it matches the compose file it ships with.

---

### SA-04 — Five enqueue calls ignore `REDIS_URL` and hardcode localhost

**✅ Verified · High**

`ai/service.py` enqueues jobs with `create_pool(RedisSettings())` — no arguments — at
five separate places. `RedisSettings()` with no arguments means arq's defaults:
`localhost:6379`. `settings.REDIS_URL` is never consulted on any of these paths.

It works today because Redis is on localhost. The day Redis moves to a managed
instance or another host, executions stop being enqueued and no error points at the
cause.

- [`ai/service.py:316`](../../../backend/src/ai/service.py:316), [`:611`](../../../backend/src/ai/service.py:611), [`:747`](../../../backend/src/ai/service.py:747), [`:852`](../../../backend/src/ai/service.py:852), [`:926`](../../../backend/src/ai/service.py:926)

**Fix:** one shared helper that builds `RedisSettings` from `settings.REDIS_URL`, used
everywhere. The worker already has `_parse_redis_url` — extract and reuse it.

---

### SA-05 — The worker's Redis parser throws away password, TLS and database index

**✅ Verified · High**

`WorkerSettings._parse_redis_url` returns only `parsed.hostname` and `parsed.port`.
A `REDIS_URL` of `rediss://:secret@redis.internal:6380/2` becomes
`RedisSettings(host="redis.internal", port=6380)` — no password, no TLS, database 0.

The connection then either fails with an auth error, or worse, succeeds against the
wrong database.

- [`ai/worker.py`](../../../backend/src/ai/worker.py) — `_parse_redis_url`

**Fix:** use `RedisSettings.from_dsn(settings.REDIS_URL)`, which arq provides for
exactly this.

---

## 3. T1 — Silently does nothing

### SA-06 — The 6-hourly dreaming cron enqueues a job the worker cannot run

**✅ Verified · High**

`worker.py` imports `dreaming_worker` and `graph_maintenance_worker` from `arq_jobs`,
but **neither appears in `WorkerSettings.functions`**. `dreaming_cron_trigger` — which
*is* registered as a cron and runs at 00:15, 06:15, 12:15 and 18:15 — enqueues by
string name:

```python
await arq.enqueue_job("dreaming_worker", entity_id, company_id, False)
```

The worker rejects every one of those as an unknown function. So scheduled memory
consolidation has never run. Only the outcome-triggered path
(`dreaming_outcome_trigger`, which *is* registered) works.

`graph_maintenance_worker` — edge-weight decay and pruning of the semantic graph — has
no caller at all, so the graph is never maintained.

- [`ai/worker.py`](../../../backend/src/ai/worker.py) — the `functions` list and the imports above it
- [`ai/core/arq_jobs.py`](../../../backend/src/ai/core/arq_jobs.py) — `dreaming_worker`, `graph_maintenance_worker`

**Fix:** add both to `functions`, and add a cron for graph maintenance. Then check
whether four dreaming runs a day is actually what you want before switching it on.

---

### SA-07 — The child-run queue is declared and not used

**✅ Verified · Medium**

`CHILD_RUN_QUEUE = "children"` is declared with a long comment explaining that it
exists so a fan-out `PROCESS` cannot starve top-level runs. The comment then says
plainly: **"NOT routed yet"**.

Child runs still go on the default queue. The only thing bounding fan-out is
`governance.max_concurrent_children`, which is itself advisory — see **D-13** in the
platform register. So there are two separate controls against runaway fan-out and
neither one is active.

- [`ai/worker.py`](../../../backend/src/ai/worker.py) — `CHILD_RUN_QUEUE`

---

### SA-08 — The lead queue fills up and is never drained

**✅ Verified · Medium**

`ai/lead_queue_worker.py` defines a 5-second polling loop and an arq wrapper. Neither
appears in `WorkerSettings.functions`, no script starts it, and no startup hook awaits
it. Grepping `backend/src` finds zero importers.

The gateway dispatcher writes leads into `lead_queue` on the `lead.created` path.
Those rows accumulate and are never dialled.

- [`ai/lead_queue_worker.py`](../../../backend/src/ai/lead_queue_worker.py)
- [`gateway/dispatcher.py:282`](../../../backend/src/gateway/dispatcher.py:282) — the producer

Also recorded as D-21 / D-26 in the platform register. **Decide: wire it up or delete
it.** Leaving it is the only wrong answer.

---

### SA-09 — The event bus loses everything on a gateway restart

**✅ Verified · Medium**

`InMemoryEventBus` is an `asyncio.Queue` fan-out inside the gateway process. It does
not persist and does not span processes. Any envelope published but not yet dispatched
when the gateway restarts is gone, with no record that it existed.

Events published when no consumer is registered are counted as **dropped**, not
queued.

`EVENT_BUS_TYPE` defaults to `memory` and `memory` is the only implemented backend —
`kafka` is aspirational.

- [`gateway/event_bus.py`](../../../backend/src/gateway/event_bus.py)

**Fix:** for a webhook that has already been acknowledged to a provider, in-memory is
the wrong durability. Write the envelope to Postgres or push straight to Redis before
returning 200.

---

### SA-10 — Neither the gateway nor the worker reports traces

**✅ Verified · Medium**

`setup_telemetry` is called on the last line of `main.py` — the Backend API only. The
gateway has no OpenTelemetry instrumentation at all (it has a hand-rolled
`/metrics/gateway` JSON endpoint instead), and the worker has none either.

The worker is where every agent execution actually happens. So the process that does
the expensive work is the one with no distributed tracing.

- [`common/telemetry.py`](../../../backend/src/common/telemetry.py) — 32 lines, one caller
- [`backend/src/main.py`](../../../backend/src/main.py) — the only `setup_telemetry` call

---

## 4. T2 — Delete

| ID | Delete | Why | Status |
|---|---|---|---|
| **SA-11** | [`gateway/main.py`](../../../backend/src/gateway/main.py) + [`gateway/config.py`](../../../backend/src/gateway/config.py) | 73 lines of superseded pure-proxy gateway plus its 10-line settings class. Nothing starts either. `config.py` is imported only by `main.py` | ✅ Verified |
| **SA-12** | [`voice/main.py`](../../../backend/src/voice/main.py) | The retired port-8002 app. Blocked only on **W-1** in the platform register. The two routers it mounts (`webhook_router`, `messaging_router`) are already mounted by the backend | ✅ Verified |
| **SA-13** | Both `streaming.hirebuddha.com` vhosts | See [SA-02](#sa-02--apache-still-proxies-streaminghirebuddhacom-to-the-dead-port) | ✅ Verified |
| **SA-14** | The duplicate `*:80` vhost for `app.hirebuddha.com` | `app.hirebuddha.com.conf` declares a port-80 vhost, and `app.hirebuddha.com-le-ssl.conf` declares a **second** one at line 20 with the HTTPS redirect commented out. Whichever Apache loads first wins, and it is not obvious which | ✅ Verified |
| **SA-15** | The stale `worker.py` docstring | It says execution logic lives in `ai.core.execution_engine`. That module does not exist — `core/` has no `execution_engine.py`. The docstring sends every new reader to a file that was deleted | ✅ Verified |

---

## 5. T3 — Fragile

### SA-16 — Route order in the gateway is load-bearing and unguarded

**✅ Verified · Medium**

`gateway/app.py` ends with a catch-all `@app.api_route("/{path:path}")`. FastAPI
matches in declaration order, so **any endpoint added below that line is unreachable**
— it is silently swallowed by the reverse proxy and forwarded to port 8000, where it
404s.

Nothing enforces the ordering. It is a comment and a convention.

- [`gateway/app.py`](../../../backend/src/gateway/app.py) — the catch-all, declared last

**Fix:** move the catch-all into a small `register_proxy(app)` function called at the
very end of the module, so adding a route in the wrong place is impossible rather than
merely discouraged.

---

### SA-17 — SSE only works if the path ends in `/stream`

**✅ Verified · Medium**

The gateway decides whether to use the no-read-timeout relay path with:

```python
wants_sse = path.endswith("/stream") or "text/event-stream" in headers.get("accept", "")
```

Any streaming endpoint whose path does not end in `/stream`, from a client that does
not set the `Accept` header, gets the buffered proxy path: it blocks until the 60-second
read timeout and hands the client a 503.

- [`gateway/app.py`](../../../backend/src/gateway/app.py) — the `wants_sse` check

---

### SA-18 — Suspension middleware costs a database round trip on every request

**✅ Verified · Medium**

`CompanySuspensionMiddleware` decodes the bearer token itself, opens **its own**
`AsyncSessionLocal`, and looks up the company — on every authenticated request, before
the route runs. Its own docstring admits it should probably be a dependency.

At current traffic this is invisible. It is a fixed tax on every request and the first
thing to look at when p50 latency matters.

- [`common/middleware.py`](../../../backend/src/common/middleware.py)

**Fix:** make it a dependency, and cache the suspension flag in Redis with a short TTL.
A suspended company does not need to be detected within one request.

---

### SA-19 — Two CORS lists that must be kept in sync by hand

**✅ Verified · Low**

The Backend API has a hardcoded Python list in `main.py`. The gateway has
`CORS_ORIGINS` from the environment. Both use `allow_credentials=True` with
`allow_methods=["*"]`. Adding a hostname means editing two places, and forgetting one
produces a browser-only failure that does not appear in any server log.

- [`backend/src/main.py:11`](../../../backend/src/main.py:11)
- [`gateway/gateway_config.py`](../../../backend/src/gateway/gateway_config.py) — `CORS_ORIGINS`

---

### SA-20 — Both shared secrets ship as `change-me-in-production`

**✅ Verified · High**

`INTERNAL_TOKEN` and `JWT_SECRET` both default to the literal string
`change-me-in-production`, in code and in `.env.example`.

`INTERNAL_TOKEN` is the only thing protecting `POST /internal/event`, which can create
executions. `JWT_SECRET` mismatching the API's `SECRET_KEY` does not fail loudly —
JWT decode returns `None`, `TenantContext` is left empty, requests still work, and
gateway-side tenant logging is silently blank.

- [`gateway/gateway_config.py:32`](../../../backend/src/gateway/gateway_config.py:32) and [`:35`](../../../backend/src/gateway/gateway_config.py:35)

**Fix:** refuse to start when either still holds the default value. A failed boot is
much better than a silently unauthenticated internal endpoint.

---

### SA-21 — Three different Python versions across the deployment path

**✅ Verified · Low**

`setup_production_vm.sh` installs **3.12**. `pyproject.toml` declares
`python = "^3.11"`. `backend/Dockerfile` uses `python:3.11-slim`. Whatever is tested
locally is not necessarily what runs on the VM.

- [`setup_production_vm.sh`](../../../setup_production_vm.sh)
- [`backend/pyproject.toml`](../../../backend/pyproject.toml)
- [`backend/Dockerfile`](../../../backend/Dockerfile)

---

## 6. Improvements

### SA-I1 — Serve the frontend as a build, not a dev server

**Effect: large.** The React SPA is served by `vite` (`npm run dev`) in production,
with `hmr: false` to stop it reloading. There is a `build` script; the deploy scripts
do not use it.

A dev server is slower, holds more memory, does no minification or asset hashing, and
has a much larger attack surface than a directory of static files behind Apache.
Switching to `npm run build` plus an Apache `DocumentRoot` removes a whole process from
the box.

### SA-I2 — One config object, one source of truth

**Effect: medium.** There are three settings classes today: `common.config.Settings`,
`gateway.gateway_config.UnifiedGatewaySettings`, and the legacy
`gateway.config.GatewaySettings`. They overlap on `DATABASE_URL`, `REDIS_URL`,
`STREAMING_HOST` and `STREAMING_PROTOCOL`, and they **disagree on the defaults** —
which is the direct cause of [SA-03](#sa-03--the-gateways-default-database-port-is-wrong).

Delete the legacy one, and have the gateway import shared values from
`common.config` rather than redeclaring them.

### SA-I3 — Validate config at boot instead of at first use

**Effect: medium.** `extra="ignore"` means a typo'd key in `backend/.env` is silently
dropped. `STREAMING_HOST` pointing at a dead port is only discovered when a call comes
in. `JWT_SECRET` mismatch is never discovered at all.

A startup check — required keys present, no placeholder secrets, database and Redis
reachable, `STREAMING_HOST` resolvable — turns a class of 3am problems into a failed
boot with a clear message.

### SA-I4 — Give the worker a health signal

**Effect: large.** When the Arq worker dies, the API keeps accepting executions and
every run sits in `PENDING` forever. Nothing surfaces an error to the user. The
document calls this "the most common *the platform looks broken but nothing is
logging* failure".

A heartbeat key in Redis plus a check on `/health` would turn a silent stall into a
visible alarm. A "runs stuck in PENDING for more than N minutes" count would be even
better.

### SA-I5 — Cache the suspension check

**Effect: medium.** See [SA-18](#sa-18--suspension-middleware-costs-a-database-round-trip-on-every-request).
One Redis lookup with a 60-second TTL replaces one Postgres round trip per request.

### SA-I6 — Split the worker pool by job type

**Effect: medium.** One worker runs everything: agent executions (up to 2 hours),
document processing, campaign dialling and seven crons. A long `PROCESS` run occupies
a slot that a 3-second document embed also needs.

`CHILD_RUN_QUEUE` was the first step towards this and was never finished. Two worker
pools — one for interactive/short jobs, one for long runs — would stop head-of-line
blocking without any change to the job code.

### SA-I7 — Make the layout lint part of the merge gate

**Effect: medium.** `backend/scripts/lint_ai_layout.py` is 271 lines of real, working
architecture policy: package line caps, forbidden imports, the `tools/` root rule. It
runs only when someone remembers to type the command.

The repository has no functioning CI at all (see
[19 — Testing](19-TESTING-DEFECTS.md) and D-14 in the platform register), so this is
blocked on that — but it is the cheapest useful check to add first.

### SA-I8 — Make the SSE terminal signal a field, not a substring

**Effect: small, prevents a nasty bug.** The API's SSE generator breaks out of the loop
when the raw JSON contains `"status": "COMPLETED"`, `"FAILED"` or `"CANCELLED"`. It is
a substring match on a serialised payload. `agent_loop_sse.py` copies `outcome` into a
`status` key purely to make this work.

Parse the event and check the field. Both sides then stop being coupled through a
string.

### SA-I9 — Fix the observability compose file before anyone needs it

**Effect: small, high value in an incident.** Two problems make the bundled monitoring
stack fail on first use: `prometheus.yml` scrapes `host.docker.internal:8000`, which
does not resolve on stock Linux Docker without an `extra_hosts` entry; and the Grafana
container publishes **port 3000**, which collides with the Vite dev server.

Both are one-line fixes, and both will be discovered at exactly the wrong moment.

### SA-I10 — Record why a router failed to mount

**Effect: small.** Same point as PO-10 in
[01 — Product overview](01-PRODUCT-OVERVIEW-DEFECTS.md), from the architecture side:
about a dozen routers are mounted inside `try/except ImportError` with a
`logger.warning`. Collect the failures into a list and expose it on `/health`.

---

## 7. Suggested order of work

| Step | Work | Why here |
|---|---|---|
| **1** | SA-01, SA-03, SA-05, SA-04 | Four wrong defaults. Each is a few lines and each is a live trap |
| **2** | SA-20 | Refuse to boot on placeholder secrets. One check, closes a real hole |
| **3** | T2 deletions — SA-11 to SA-15 | Free. Do SA-12 and SA-13 together as **W-1** |
| **4** | SA-06, SA-08 | Two background jobs that have never run. Decide each: wire up or delete |
| **5** | SA-I4 (worker health) | The single most valuable operational change on this list |
| **6** | SA-I1 (build the frontend), SA-I6 (split the worker pool) | The two changes that matter when load grows |

---

## Where to go next

- [02 — System architecture](../02-system-architecture.md) — the source document.
- [`DEFECT-REGISTER.md`](../DEFECT-REGISTER.md) — SA-12 and SA-13 are the platform
  register's **W-1**; SA-08 is D-21/D-26.
- [13 — Gateway & real-time](13-GATEWAY-AND-REALTIME-DEFECTS.md) — for SA-09, SA-16,
  SA-17.
- [18 — Infrastructure & deployment](18-INFRASTRUCTURE-AND-DEPLOYMENT-DEFECTS.md) —
  for SA-02, SA-14, SA-21 and SA-I1.
- [08 — Memory & CORTEX](08-MEMORY-AND-CORTEX-DEFECTS.md) — for what SA-06 actually
  breaks.
