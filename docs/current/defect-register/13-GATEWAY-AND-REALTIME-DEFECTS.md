# 13. The Unified Gateway & Real-Time Transport — Defect Register

> **What this document is:** defects in the public front door — the reverse proxy, the
> webhook receiver, the internal-event endpoint, audio and video WebSockets and the SSE
> relay — plus the improvements that would make the edge safe to expose and cheap to scale.
> **Source document:** [`13-gateway-and-realtime.md`](../13-gateway-and-realtime.md)
> **Compiled:** 2026-09-01, against branch `fresh-main`. **Last reviewed:** 2026-10-07, on branch `roadmap-development-defect-fixes`.
> **Context:** everything external reaches the platform through this process. It is the
> only thing between the internet and the API, and **several of its controls are not
> wired**.
>
> **Update 2026-09-30:** the gateway (port 8001) was merged into the API on port 8000 — the
> `src/gateway/` modules are now routers the API mounts, and the reverse proxy, its
> settings class and its auth middleware are deleted. Entries that the merge closed or
> changed carry a status line; the rest still hold, with "the gateway" now meaning those
> endpoints on the API. See [02 — SA-16 et al.](02-SYSTEM-ARCHITECTURE-DEFECTS.md).

---

## How to read this file

- **✅ Verified** — the code was read on 2026-09-01 and the claim held.
- **📄 Doc-reported** — from `13-gateway-and-realtime.md`, not independently re-checked.
- The recurring shape here is a control that exists as an object but was never attached to
  the request path: the rate limiter without its middleware, the auth middleware that
  cannot see WebSockets, the signature validators whose result is ignored.

---

## Contents

1. [Summary](#1-summary)
2. [T0 — The edge is not defended](#2-t0--the-edge-is-not-defended)
3. [T1 — Wired to nothing](#3-t1--wired-to-nothing)
4. [T2 — Delete](#4-t2--delete)
5. [T3 — Correctness and scaling](#5-t3--correctness-and-scaling)
6. [Improvements](#6-improvements)
7. [Suggested order of work](#7-suggested-order-of-work)

---

## 1. Summary

| Tier | Theme | Count | Fixed | Partly fixed | Open | Closed otherwise |
|---|---|---|---|---|---|---|
| [T0](#2-t0--the-edge-is-not-defended) | The edge is not defended | 5 | 4 | 0 | 0 | 1 |
| [T1](#3-t1--wired-to-nothing) | Wired to nothing | 5 | 3 | 1 | 1 | 0 |
| [T2](#4-t2--delete) | Delete | 4 | 3 | 1 | 0 | 0 |
| [T3](#5-t3--correctness-and-scaling) | Correctness and scaling | 7 | 6 | 0 | 1 | 0 |

**Total: 21 defects (16 fixed, 2 partly fixed, 2 open, 1 invalid), 10 improvements.** Re-verified against the code on 2026-10-07; what is left is scheduled in [`REMAINING-DEFECTS-PLAN.md`](REMAINING-DEFECTS-PLAN.md).

| ID | Defect | Status | Plan |
|---|---|---|---|
| GW-01 | No webhook signature is ever verified, and a failure would not block | ✅ fixed `f0ec5db` | — |
| GW-02 | Rate limiting covers one route | ✅ fixed (2026-10-08) | — |
| GW-03 | No webhook idempotency | ✅ fixed `302d276` | — |
| GW-04 | The auth middleware never sees a WebSocket | ✅ fixed `4357a92` | — |
| GW-05 | Rate limits are keyed on `127.0.0.1` in production | invalid | — |
| GW-06 | `EVENT_BUS_TYPE` and the TURN credentials are never read | partly fixed — TURN settings still unread | [H6](REMAINING-DEFECTS-PLAN.md#h6--real-time-transport) |
| GW-07 | The event bus is in-process with one subscriber | ✅ fixed (single port) | — |
| GW-08 | The arq fallback runs a full AgentLoop inside the gateway | ✅ fixed (single port) | — |
| GW-09 | `X-Accel-Buffering: no` does nothing here | ✅ fixed `01fa369` | — |
| GW-10 | `aiortc` is not installed, and the video path has a second bug behind it | open — decision HD11 | [H6](REMAINING-DEFECTS-PLAN.md#h6--real-time-transport) |
| GW-11 | `gateway/main.py` and `gateway/config.py` | ✅ fixed (single port) | — |
| GW-12 | `@app.on_event("shutdown")` / `close_proxy_client` | ✅ fixed (single port) | — |
| GW-13 | `EVENT_BUS_TYPE`, `TURN_USERNAME`, `TURN_CREDENTIAL`, event `priority` | partly fixed — see GW-06 | [H6](REMAINING-DEFECTS-PLAN.md#h6--real-time-transport) |
| GW-14 | Both `streaming.hirebuddha.com` vhosts | ✅ fixed | — |
| GW-15 | The proxy copies response headers verbatim after decompressing | ✅ fixed | — |
| GW-16 | Auth middleware runs before CORS, so its 401s have no CORS headers | ✅ fixed | — |
| GW-17 | Agent selection is `LIMIT 1` with no `ORDER BY`, in three places | ✅ fixed `3ca2d38` | — |
| GW-18 | SSE has no replay and no `Last-Event-ID` | ✅ fixed (2026-10-08) | — |
| GW-19 | SSE terminates on a substring match | ✅ fixed (2026-10-08) | — |
| GW-20 | The catch-all proxy must stay last, and nothing enforces it | ✅ fixed | — |
| GW-21 | WebSocket sessions require affinity that nothing provides | open — decision HD12 | [H6](REMAINING-DEFECTS-PLAN.md#h6--real-time-transport) |

The three to read first:

- **[GW-01](#gw-01--no-webhook-signature-is-ever-verified-and-a-failure-would-not-block)** —
  every validator returns `True`, and a `False` is logged and ignored.
- **[GW-02](#gw-02--rate-limiting-covers-one-route)** — the limiter has no middleware, so
  only the REST proxy is limited. Webhooks and WebSockets are unlimited.
- **[GW-04](#gw-04--the-auth-middleware-never-sees-a-websocket)** — the `/stream/*` branch
  of the auth middleware is dead code for real WebSocket connections.

> **Update 2026-10-07:** GW-01 is unchanged and is the most serious open defect on the platform. GW-02 is partly fixed: every REST route is limited, but webhooks and WebSockets are not. GW-04's middleware is deleted, and the WebSocket token is still never checked.

---

## 2. T0 — The edge is not defended

### GW-01 — No webhook signature is ever verified, and a failure would not block

**✅ Verified · Critical** · **Status: fixed (2026-10-07, `f0ec5db`)** — a webhook is accepted only at `POST /webhook/inbound/{endpoint_id}`, an endpoint a company admin registers (`/api/v1/webhook-endpoints`; table `webhook_endpoints`, migration `h2_webhook_endpoints`). The endpoint names the company, the source and the secret (encrypted); the request is checked with that source's native scheme or the relay `X-HB-Signature` (`gateway/webhook_signatures.py`, constant-time), and a missing or wrong signature is a **401 with nothing queued**, plus a `gateway.webhook.signature_failed` event. The scheme is never chosen from the request's headers: the header-sniffing `detect_strategy` and the always-`True` `validate_signature` methods are deleted. The tenant is the endpoint's company — `?client_id=` names nothing. The bare `POST /webhook/inbound` answers 401; a revoked endpoint or a suspended company 404. Tests: `test_webhook_signatures.py` (every source signed, tampered, unsigned, wrong secret, other scheme, stale), `test_webhook_ingress_auth.py`, `tests/integration/test_webhook_endpoints.py` (Postgres). Not exercised with real provider deliveries. No UI yet: endpoints are managed through the API. The secrets column joins AU-24's re-encryption

Two separate problems, either of which alone would be enough.

**First**, the validators do not validate. The base implementation is:

```python
def validate_signature(self, request_headers: dict, raw_body: bytes) -> bool:
    """Override for signature validation. Default: always True (no validation)."""
    return True
```

Every concrete strategy returns `True` when the header is absent, and the GitHub and
Facebook ones carry a `TODO` where the HMAC comparison belongs.

**Second**, and worse, the result is discarded:

```python
if not strategy.validate_signature(headers, raw_body):
    logger.warning(f"[WebhookRouter] Signature validation failed for source={source}")
    # We still process — providers may retry; we log for audit
```

So even a correctly implemented validator returning `False` would not stop the request.

`POST /webhook/inbound` creates executions. Anyone who can reach it can make any tenant's
agents run, and pay for it.

- [`gateway/webhook_inbound.py:59`](../../../backend/src/gateway/webhook_inbound.py:59) — the base, always `True`
- [`gateway/webhook_inbound.py:161`](../../../backend/src/gateway/webhook_inbound.py:161) LinkedIn · [`:193`](../../../backend/src/gateway/webhook_inbound.py:193) GitHub · [`:250`](../../../backend/src/gateway/webhook_inbound.py:250) Facebook
- [`gateway/webhook_inbound.py:549`](../../../backend/src/gateway/webhook_inbound.py:549) — the ignored result
- Also recorded as **D-05** in the platform register

**Fix:** implement the HMACs and **fail closed**. Pairs with
[GW-03](#gw-03--no-webhook-idempotency).

---

### GW-02 — Rate limiting covers one route

**✅ Verified · High** · **Status: fixed (2026-10-08)** — REST since 2026-09-30: the API installs
`SlowAPIMiddleware`, so every REST route is limited at `RATE_LIMIT` per client IP (GW-I1),
falling back to in-memory counts when Redis is down. The rest of the edge since 2026-10-08:
signed webhook deliveries per endpoint — one company, one source — at `WEBHOOK_RATE_LIMIT`
(300/minute; 429 + `Retry-After`, after the signature check so unsigned requests cannot use
up a tenant's allowance, and before the delivery is claimed so the retry is taken);
live-socket handshakes per client IP on `/stream/audio`, `/stream/video` and `/mobile/ws`
at `WS_HANDSHAKE_RATE_LIMIT` (30/minute; close `4429`) — `gateway/socket_limits.py`, counted
in the REST limiter's Redis, in process memory when it is down (gate `edge_rate_limit`); and
live AI sessions per company at `LIVE_SESSIONS_PER_COMPANY` (20, `voice/live_sessions.py`):
a call is refused at admission at the cap (`call_refusal`, every checkpoint) and a session
that connects past it — the media socket or browser audio — closes `4429`. The webhooks
stay exempt from the per-IP limit (a provider's IPs are shared by every tenant) and so does
`/internal/event` (it carries the internal token; GH-03 caps the runs it starts). Browser
audio (`/stream/audio`, provider `web`) was never admitted for credit at all; it goes
through `call_refusal` now. The telephony streams are not limited per IP (their IPs are the
provider's); each is gated by its call. `tests/unit/test_edge_limits.py` (13). Live on :8000:
of 32 handshakes from one address, the first 30 reached the handshake check and the 31st
and 32nd closed `4429`. The live-session count is per process (one instance, GW-21).

The limiter is constructed with `default_limits=[settings.RATE_LIMIT]`, attached to
`app.state.limiter`, and given an exception handler. **`SlowAPIMiddleware` is never
added.**

Without the middleware, slowapi's `default_limits` apply only to routes carrying an
explicit `@limiter.limit(...)` decorator. Exactly one route has it: the catch-all REST
proxy.

Unlimited, therefore:

| Path | What it does |
|---|---|
| `POST /webhook/inbound` | creates executions |
| `POST /internal/event` | creates executions |
| `WS /stream/audio`, `/stream/twilio/*`, `/stream/tata/*` | opens live LLM sessions |
| `WS /stream/video` | opens peer connections |

The two endpoints that can spend a tenant's money without a login are both in that list.

- `gateway/app.py:80` — the limiter
- `gateway/app.py:104` — `app.state.limiter`, no middleware
- `gateway/app.py:341` — the one decorated route

**Fix:** `app.add_middleware(SlowAPIMiddleware)`. One line, and it makes the configured
limit mean what everyone assumes it means.

---

### GW-03 — No webhook idempotency

**📄 Doc-reported · High** · **Status: fixed (2026-10-07, `302d276`)** — after the signature check a delivery is claimed with Redis `SET NX EX 86400`, keyed on the endpoint and the provider's delivery id (`X-GitHub-Delivery`, `I-Twilio-Idempotency-Token`, a relay's `X-HB-Delivery`) or the body's SHA-256. A delivery already taken answers 200 `duplicate` and is not queued; the claim is released if the enqueue fails, so a retried 503 still runs; Redis unavailable is a 503, never a second run. `tests/unit/test_webhook_deliveries.py` (fails on the old route: a retry ran twice), and `test_webhook_endpoints.py::test_a_retried_delivery_runs_once` against the local Redis

Providers retry. Nothing deduplicates. A retried delivery creates a **second execution**
and a second charge.

Every provider sends a delivery id; none is recorded. Combined with
[GW-01](#gw-01--no-webhook-signature-is-ever-verified-and-a-failure-would-not-block), a
single captured webhook body can be replayed indefinitely.

- [`gateway/webhook_inbound.py`](../../../backend/src/gateway/webhook_inbound.py)
- Also recorded as **D-31** in the platform register

**Fix:** store the provider delivery id with a TTL and drop repeats.

---

### GW-04 — The auth middleware never sees a WebSocket

**✅ Verified · High** · **Status: fixed (2026-10-07, `4357a92`)** — the auth middleware was
deleted on 2026-09-30 (the internal-token check is a `require_internal` dependency), and
the gap it described is closed in the handlers themselves (GW-I6): `/stream/audio` and
`/stream/video` call `gateway/stream_auth.py`'s `stream_company` first. The handshake's
`token` must be a URL token minted for `/stream/` (`POST /api/v1/auth/url-token`; ten
minutes, path-scoped, ended with the user's sessions) — else an `unauthorized` error and
close **4401**; the company is the token's, and a `client_id` naming another company is
close **4403**. `tests/unit/test_stream_auth.py` (both sockets; fails on the old code,
which resolved an agent for a bare `client_id`). Checked live on the running API: a bare
`client_id`, a login token or an artifacts-scoped token → 4401; a stream token with a
foreign `client_id` → 4403; a stream token → reaches agent resolution. Nothing in the
repository opens these sockets yet, so no client changed.

`GatewayAuthMiddleware` extends `BaseHTTPMiddleware`, which passes non-HTTP ASGI scopes
straight through. WebSocket connections never enter it.

So the middleware's `/stream/*` branch — which classifies the audio and video channels and
reads `?client_id=` — is **dead code for real WebSocket connections**. And the handshake
`token` parameter it was meant to check is read into a variable and never validated
anywhere.

Live audio sessions are therefore opened without any credential check at the gateway.

- `gateway/auth_middleware.py:20` — `BaseHTTPMiddleware`
- `gateway/auth_middleware.py:55` — `GatewayAuthMiddleware`

**Fix:** validate the token inside the WebSocket endpoint itself, where the scope is
available. Middleware is the wrong layer for this.

---

### GW-05 — Rate limits are keyed on `127.0.0.1` in production

**📄 Doc-reported · High** · **Status: invalid (2026-10-07)** — uvicorn (0.27.1) runs with `proxy_headers` on and, by default (`FORWARDED_ALLOW_IPS`), trusts `X-Forwarded-For` from `127.0.0.1`. It takes the right-most untrusted address — the one Apache's `mod_proxy` appends — and every vhost proxies to `localhost:8000`. So `request.client.host`, and the limiter's key, is the real client. `RemoteIPHeader` ([GW-I2](#gw-i2--set-remoteipheader-in-the-vhosts)) would only change Apache's own logs.

`key_func=get_remote_address`. Every request arrives from Apache on the loopback
interface, and **no vhost sets `RemoteIPHeader`**, so `X-Forwarded-For` is never trusted
and the remote address is always `127.0.0.1`.

Every caller in the world therefore shares one bucket. The limit is effectively a global
cap, and one noisy client exhausts it for everyone.

- `gateway/app.py:80` — `get_remote_address`
- [`deploy/apache/`](../../../deploy/apache/) — no `RemoteIPHeader` in any vhost
- Also recorded as **D-32** in the platform register

**Fix:** set `RemoteIPHeader X-Forwarded-For` and `RemoteIPInternalProxy 127.0.0.1` in the
vhosts. `mod_remoteip` is already enabled by `setup_apache.sh`.

---

## 3. T1 — Wired to nothing

### GW-06 — `EVENT_BUS_TYPE` and the TURN credentials are never read

**📄 Doc-reported · Medium** · **Status: partly fixed (2026-09-30)** — `EVENT_BUS_TYPE` is gone
with the gateway's settings class. `TURN_USERNAME` / `TURN_CREDENTIAL` (now in the one
`Settings`) are still never read.

Three settings are declared, documented and unused:

| Setting | Reality |
|---|---|
| `EVENT_BUS_TYPE` | never read; `memory` is the only implementation and `kafka` is aspirational |
| `TURN_USERNAME` | never read |
| `TURN_CREDENTIAL` | never read |

The TURN pair matters: WebRTC behind a symmetric NAT needs a relay, and configuring the
credentials does nothing.

`priority` on internal events is likewise stored and ignored.

---

### GW-07 — The event bus is in-process with one subscriber

**✅ Verified · Medium** · **Status: fixed (2026-09-30)** — the bus is deleted; the ingress
endpoints enqueue on arq before their 202 (SA-09).

"Event bus" suggests infrastructure. It is an `asyncio.Queue` inside one process with
exactly one subscriber, and cross-process delivery happens later via arq.

Consequences:

- A gateway restart loses every envelope that was published but not yet dispatched — after
  the provider has already been told `200 OK`.
- Events published with no consumer registered are counted as **dropped**, not queued.
- `/health` metrics are per-instance.

- [`gateway/event_bus.py`](../../../backend/src/gateway/event_bus.py)

**Fix:** persist the envelope before acknowledging the webhook. Once a provider has been
told the delivery succeeded, in-memory is the wrong durability.

---

### GW-08 — The arq fallback runs a full AgentLoop inside the gateway

**📄 Doc-reported · High** · **Status: fixed (2026-09-30)** — the fallback is deleted: when arq
is unreachable the endpoint answers 503 and the caller retries (SA-09, GW-I5). (Between
the single-port merge and SA-09 it briefly ran inside the API process.)

When the arq pool is unreachable, `_execute_in_process` runs the whole agent loop as a
fire-and-forget task **in the gateway process**.

That process also serves live audio WebSockets on the same event loop. A single fallback
execution — minutes of LLM calls and tool runs — competes with real-time audio for the
same loop, and the failure mode is stuttering calls rather than an obvious error.

It is convenient in development and dangerous under load, and it triggers exactly when
Redis is already unhealthy.

- [`gateway/dispatcher.py`](../../../backend/src/gateway/dispatcher.py) — `_execute_in_process`

**Fix:** return `503` and let the provider retry. The webhook path is already built around
provider retries.

---

### GW-09 — `X-Accel-Buffering: no` does nothing here

**📄 Doc-reported · Low** · **Status: fixed (2026-10-07, `01fa369`)** — the header is gone; the stream sends `Cache-Control: no-cache, no-transform` (`ai/router.py` `SSE_HEADERS`), which asks Apache's mod_deflate — enabled by `setup_apache.sh` — not to compress or hold back the frames. `tests/unit/test_sse_headers.py`. Not checked behind a live Apache (no VM in this session)

The SSE relay sets `X-Accel-Buffering: no` to stop intermediate proxies buffering. That is
an **nginx** header. The deployment uses Apache, which ignores it.

SSE works today because Apache's `ProxyPass` does not buffer these responses by default —
not because of this header. Anyone who adds `mod_deflate` or a caching layer will break
streaming and this header will not save them.

---

### GW-10 — `aiortc` is not installed, and the video path has a second bug behind it

**✅ Verified · Medium** · **Status: open** — re-verified 2026-10-07: `aiortc` is still undeclared, and `video_gateway.py:207` still iterates over `track.recv.__self__.__class__.__mro__[0]`. Plan: [H6](REMAINING-DEFECTS-PLAN.md#h6--real-time-transport).

`aiortc` appears in neither `pyproject.toml` nor the virtualenv, and `video_gateway.py`
imports it conditionally. So `/stream/video` answers the signalling handshake, tells the
client to check the installation, and closes.

The doc records a second defect behind it: even with `aiortc` installed, the audio pipeline
aborts on a `__mro__` line at `video_gateway.py:202`.

So installing the dependency alone will not make video work.

- [`gateway/video_gateway.py:48`](../../../backend/src/gateway/video_gateway.py:48)–65
- [`backend/pyproject.toml`](../../../backend/pyproject.toml)
- Also recorded as **D-16** in the platform register

**Fix:** decide. Either install it and fix line 202, or remove the endpoint, the Apache
upgrade rule and the STUN/TURN settings.

---

## 4. T2 — Delete

| ID | Delete | Notes | Status |
|---|---|---|---|
| **GW-11** | `gateway/main.py` and `gateway/config.py` | The superseded pure-proxy gateway and its settings class. Only `app.py` and `gateway_config.py` run | ✅ fixed (2026-09-30) — deleted, with `app.py` and `gateway_config.py` (SA-11) |
| **GW-12** | `@app.on_event("shutdown")` / `close_proxy_client` | A custom `lifespan` was supplied at `app.py:98`, so the `on_event` handler at `:330` **never fires**. The shared `httpx` client is never closed on shutdown | ✅ fixed (2026-09-30) — the proxy and its client are gone with `gateway/app.py` |
| **GW-13** | `EVENT_BUS_TYPE`, `TURN_USERNAME`, `TURN_CREDENTIAL`, event `priority` | See [GW-06](#gw-06--event_bus_type-and-the-turn-credentials-are-never-read). Delete or wire | 📄 Doc-reported · partly fixed (2026-09-30) — `EVENT_BUS_TYPE` deleted |
| **GW-14** | Both `streaming.hirebuddha.com` vhosts | They point at port 8002, which nothing serves. Part of **W-1** | ✅ fixed (2026-09-30) — deleted (SA-13) |

> Move `close_proxy_client`'s body into the `lifespan` shutdown half rather than deleting
> the behaviour — the client should still be closed.

---

## 5. T3 — Correctness and scaling

### GW-15 — The proxy copies response headers verbatim after decompressing

**📄 Doc-reported · Medium** · **Status: fixed (2026-09-30)** — the proxy is deleted.

The reverse proxy copies upstream response headers including `content-length` and
`content-encoding`, while `httpx` has **already decompressed the body**.

Harmless today only because the backend has no `GZipMiddleware`. Adding one — a normal
performance change — silently breaks every proxied response, because the client is told
the body is gzipped and it is not.

- `gateway/app.py` — the catch-all proxy

**Fix:** strip `content-encoding` and `content-length` from the copied headers.

---

### GW-16 — Auth middleware runs before CORS, so its 401s have no CORS headers

**📄 Doc-reported · Low** · **Status: fixed (2026-09-30)** — the middleware is deleted and
`CORSMiddleware` is the API's outermost layer; a 401 from `/internal/event` (and any 403
or 429) carries CORS headers.

Starlette runs middleware in reverse registration order. `GatewayAuthMiddleware` is added
after `CORSMiddleware` and therefore runs before it on the inbound leg — and returns its
401 without CORS headers.

In a browser that surfaces as an opaque CORS error rather than "401 Unauthorized", which
sends the developer looking in entirely the wrong place.

---

### GW-17 — Agent selection is `LIMIT 1` with no `ORDER BY`, in three places

**📄 Doc-reported · Medium** · **Status: fixed (2026-10-07, `3ca2d38`)** — correction to the 2026-10-07 re-verification: all three call sites were still there — `dispatcher.resolve_agent_for_client` and two in `ai/core/arq_jobs.py` (the webhook worker's agent fallback and the sheet campaign's user fallback). One rule now, `gateway/agent_choice.py` `choose_agent`: an agent named explicitly (a webhook endpoint's binding, then the event's `entity_id`; a socket handshake's `agent_id`) if it is an active, non-template agent of the company, else refused (`unknown_agent`); with none named, the company's only active top-level agent; several is refused (`ambiguous_agent`) instead of guessed. Drafts, archived, soft-deleted, template and child entities are never picked. The sheet campaign's user fallback is the company admin, else the earliest user. `tests/integration/test_agent_choice.py` (Postgres), `tests/unit/test_agent_choice_wiring.py`

When a webhook or internal event does not name an entity, the gateway picks one with
`LIMIT 1` and no ordering. A tenant with several agents gets a non-deterministic choice —
possibly a different one on each delivery of the same event type.

- Three call sites across [`gateway/dispatcher.py`](../../../backend/src/gateway/dispatcher.py)
- Also recorded as **D-36** in the platform register

---

### GW-18 — SSE has no replay and no `Last-Event-ID`

**📄 Doc-reported · Medium** · **Status: fixed (2026-10-08)** — a run's frames are a Redis stream per run, `run_events:{run_id}` (`ai/core/run_stream.py`: `XADD … MAXLEN ~ 1000`, kept a day after the last frame), not pub/sub. The SSE endpoint sends each frame with its stream id as `id:`, starts after `Last-Event-ID` (the header of the browser's own reconnect) or `?last_event_id=` (a reopened `EventSource`), else from the first frame kept, sends a keep-alive every 15 s of silence, and ends a finished run with nothing left to send at once (a terminal `run_end` of the stored status). The page opens one stream (`useExecutionEvents` in `ExecutionDetail`), re-reads REST half a second after a frame that changes what is stored, and polls every 3 s only while the stream is down, ended before the final status was stored, or the run waits on children. `tests/unit/test_run_stream_replay.py` (8), integration `test_run_stream_redis.py` (3, the local Redis), `frontend/src/services/events.test.ts` (4). Live: frames carry ids; a reconnect with `Last-Event-ID` got the frame published while it was away; the run page made no poll for 10 s while the stream was open, one re-read per milestone, polled while the API was stopped, showed the frame published during the outage once the API was back, and closed its stream on the terminal frame without reconnecting

A reconnecting `EventSource` loses everything that happened while it was disconnected.
There is no event id, no buffer, no replay.

What actually keeps the execution page correct is a 3-second poll running alongside the
stream. So the platform pays for both a live stream and a polling loop, and needs both
because neither is sufficient.

---

### GW-19 — SSE terminates on a substring match

**📄 Doc-reported · Medium** · **Status: fixed (2026-10-08)** — every frame on a run's channel is published by `ai/core/run_stream.publish_run_event`, which marks the run's last frame `"terminal": true`: `run_end` with a finished outcome (`COMPLETED`, `FAILED`, `PARTIAL_COMPLETE`, `CANCELLED` — not `PAUSED` or `WAITING_ON_CHILDREN`), `cancelled` with a finished status, and the cancel endpoint's frame. The generator parses each frame and stops on that field only; the `status` copied into `run_end` for the substring match is gone. On the old code a child's `"status": "COMPLETED"` inside a span's payload closed the parent's stream, and a `PARTIAL_COMPLETE` run's stream never closed. `tests/unit/test_run_stream_terminal.py` (10; 9 fail on the old code)

The generator breaks when the raw JSON payload contains `"status": "COMPLETED"`,
`"FAILED"` or `"CANCELLED"`. `agent_loop_sse.py` copies `outcome` into a `status` key
purely so this works.

Any event carrying one of those words inside a tool result or a critic note closes the
stream early, and the user sees a run that appears to stop.

Same as [PO-19](01-PRODUCT-OVERVIEW-DEFECTS.md#po-19--the-sse-stream-closes-on-a-substring-match)
and [SA-I8](02-SYSTEM-ARCHITECTURE-DEFECTS.md#sa-i8--make-the-sse-terminal-signal-a-field-not-a-substring).

---

### GW-20 — The catch-all proxy must stay last, and nothing enforces it

**✅ Verified · Medium** · **Status: fixed (2026-09-30)** — no catch-all exists (SA-16).

`@app.api_route("/{path:path}")` is declared last on purpose. FastAPI matches in
declaration order, so any endpoint added below it is silently swallowed and forwarded to
port 8000, where it 404s.

The protection is a comment.

Same as [SA-16](02-SYSTEM-ARCHITECTURE-DEFECTS.md#sa-16--route-order-in-the-gateway-is-load-bearing-and-unguarded).

---

### GW-21 — WebSocket sessions require affinity that nothing provides

**📄 Doc-reported · Medium** · **Status: open** — re-verified 2026-10-07: unchanged; latent while there is one instance. Plan: [H6](REMAINING-DEFECTS-PLAN.md#h6--real-time-transport).

`VoiceSession` objects, live LLM sockets, audio buffers and `RTCPeerConnection` objects all
live in the gateway process. A reconnect landing on a second instance finds none of them.

Audio can partially resume via `metadata.session_id`, which re-reads the `VoiceSession`
from Postgres — but the live LLM connection and the buffers do not transfer. WebRTC cannot
resume at all.

Today there is exactly one instance, so this is latent. It is the thing that blocks
horizontal scaling, and it should be decided before it is needed rather than during an
incident.

---

## 6. Improvements

### GW-I1 — Add `SlowAPIMiddleware`

**Status: done (2026-09-30)** — on the API, with the two ingress endpoints exempt. See GW-02.

**Effect: large, one line.** [GW-02](#gw-02--rate-limiting-covers-one-route). Everything on
the gateway is unlimited today except the REST proxy, including the two endpoints that can
start billable work without a login.

### GW-I2 — Set `RemoteIPHeader` in the vhosts

**Effect: large, two lines of Apache config.**
[GW-05](#gw-05--rate-limits-are-keyed-on-127001-in-production). Without it, GW-I1 gives you
one global bucket rather than per-client limits — so these two changes belong in the same
commit.

### GW-I3 — Persist webhook envelopes before acknowledging

**Status: done (2026-09-30)** — the arq job in Redis is the persisted envelope, written before
the 202 (SA-09).

**Effect: large.** [GW-07](#gw-07--the-event-bus-is-in-process-with-one-subscriber). Once a
provider is told `200 OK`, the platform owns that event. An `asyncio.Queue` is not a
durable owner. Write it to Postgres or push it to Redis before returning.

This also gives [GW-03](#gw-03--no-webhook-idempotency) somewhere to record the delivery id.

### GW-I4 — Verify signatures and fail closed

**Effect: large.** [GW-01](#gw-01--no-webhook-signature-is-ever-verified-and-a-failure-would-not-block).
Three HMAC implementations, plus changing `if not validate: log` into `if not validate:
return 401`. Do the second half even before the first — a `False` that does not block is
worse than no check, because it looks like a check.

### GW-I5 — Return 503 instead of running the loop in the gateway

**Status: done (2026-09-30)** — SA-09.

**Effect: medium, removes a failure amplifier.**
[GW-08](#gw-08--the-arq-fallback-runs-a-full-agentloop-inside-the-gateway). The fallback
turns "Redis is down" into "Redis is down **and** live calls stutter". Provider retries
already handle the alternative.

### GW-I6 — Validate the WebSocket token in the endpoint

**Effect: medium.** [GW-04](#gw-04--the-auth-middleware-never-sees-a-websocket). The
handshake already carries `?client_id=` and `?token=`; the token is simply never checked.
Do it in the endpoint, where the scope exists, and delete the dead middleware branch.

### GW-I7 — Give SSE an event id and a short replay buffer

**Status: done (2026-10-08)** — with [GW-18](#gw-18--sse-has-no-replay-and-no-last-event-id), as a Redis stream per run rather than `seq` (spans are only part of what the page shows).

**Effect: medium.** [GW-18](#gw-18--sse-has-no-replay-and-no-last-event-id). `seq` already
exists on `execution_trace_events` and is monotonic per run. Emitting it as the SSE event
id and honouring `Last-Event-ID` on reconnect would let the frontend drop its 3-second
poll entirely — removing a constant query per open execution page.

### GW-I8 — Reuse one `httpx` client and close it properly

**Status: moot (2026-09-30)** — the proxy and its client are deleted.

**Effect: small.** The shared lazily-created client is right; the shutdown that closes it
never runs ([GW-12](#4-t2--delete)). Move the close into the `lifespan` shutdown half so
connections are released on restart.

### GW-I9 — Make the proxy header handling explicit

**Status: moot (2026-09-30)** — the proxy is deleted.

**Effect: small, prevents a future outage.**
[GW-15](#gw-15--the-proxy-copies-response-headers-verbatim-after-decompressing). Strip
`content-encoding` and `content-length`. Today's correctness depends on the backend never
enabling compression, which is not a property anyone is tracking.

### GW-I10 — Decide the video story

**Effect: medium.** [GW-10](#gw-10--aiortc-is-not-installed-and-the-video-path-has-a-second-bug-behind-it).
The endpoint, the signalling protocol, the STUN/TURN settings, the session dict and the
Apache upgrade rule all exist for a feature that cannot run. Either finish it or remove all
five, so the surface reflects what the product does.

---

## 7. Suggested order of work

| Step | Work | Why here |
|---|---|---|
| **1** | GW-I1 + GW-I2 | One line of Python, two of Apache. Turns a decorative rate limit into a real one |
| **2** | GW-I4 / GW-01 | Fail closed on signatures, then implement the HMACs |
| **3** | GW-I3 / GW-07 + GW-03 | Durable envelopes and delivery-id idempotency, together |
| **4** | GW-I6 / GW-04 | Validate the WebSocket token where the scope exists |
| **5** | GW-I5 / GW-08 | Stop running agent loops in the gateway process |
| **6** | T2 deletions — GW-11 to GW-14 | Free, and GW-14 is part of **W-1** |
| **7** | GW-I7 / GW-18, GW-19 | SSE replay and a real terminal signal; drop the polling loop |
| **8** | GW-I10 / GW-10, GW-21 | Decide on video, and on whether a second instance is coming |

---

## Where to go next

- [13 — The unified gateway & real-time transport](../13-gateway-and-realtime.md) — the
  source document.
- [`DEFECT-REGISTER.md`](../DEFECT-REGISTER.md) — GW-01 is D-05, GW-03 is D-31, GW-05 is
  D-32, GW-10 is D-16, GW-17 is D-36.
- [02 — System architecture](02-SYSTEM-ARCHITECTURE-DEFECTS.md) — SA-09, SA-16, SA-17 for
  the same subsystem from the topology side.
- [12 — Voice & telephony](12-VOICE-AND-TELEPHONY-DEFECTS.md) — the handlers behind the
  audio WebSockets.
- [04 — Auth, RBAC & tenancy](04-AUTH-RBAC-TENANCY-DEFECTS.md) — AU-11 and AU-13 for the
  gateway's shared secrets.
