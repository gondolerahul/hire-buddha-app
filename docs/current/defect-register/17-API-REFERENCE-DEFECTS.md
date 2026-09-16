# 17. API Reference — Defect Register

> **What this document is:** defects in the HTTP surface itself — routes that do not exist,
> routes that should not be reachable, inconsistent paths and missing pagination — plus the
> improvements that would make the API predictable.
> **Source document:** [`17-api-reference.md`](../17-api-reference.md)
> **Compiled:** 2026-09-01, against branch `fresh-main`.
> **Context:** the API is assembled from about twenty routers mounted with chained
> prefixes, half of them inside `try/except ImportError`. There is no route census, so
> nothing checks that the documented surface and the real one agree.

---

## How to read this file

- **✅ Verified** — the code was read on 2026-09-01 and the claim held.
- **📄 Doc-reported** — from `17-api-reference.md`, not independently re-checked.
- Route-level authorisation defects live in
  [04 — Auth, RBAC & tenancy](04-AUTH-RBAC-TENANCY-DEFECTS.md); this file covers the shape
  of the surface. The two overlap on [API-01](#api-01--four-endpoints-are-open-or-wrongly-gated),
  which is repeated here because an API reference is where someone checks.

---

## Contents

1. [Summary](#1-summary)
2. [T0 — Reachable and should not be](#2-t0--reachable-and-should-not-be)
3. [T1 — Documented and not reachable](#3-t1--documented-and-not-reachable)
4. [T2 — Delete](#4-t2--delete)
5. [T3 — Inconsistency across the surface](#5-t3--inconsistency-across-the-surface)
6. [Improvements](#6-improvements)
7. [Suggested order of work](#7-suggested-order-of-work)

---

## 1. Summary

| Tier | Theme | Count | When to do it |
|---|---|---|---|
| [T0](#2-t0--reachable-and-should-not-be) | Reachable and should not be | 4 | **Now** |
| [T1](#3-t1--documented-and-not-reachable) | Documented and not reachable | 5 | Before anyone integrates |
| [T2](#4-t2--delete) | Delete | 4 | Free — two are past their own removal date |
| [T3](#5-t3--inconsistency-across-the-surface) | Inconsistency across the surface | 7 | Opportunistically |

**Total: 20 defects, 10 improvements.**

The three to read first:

- **[API-01](#api-01--four-endpoints-are-open-or-wrongly-gated)** — five routes that
  create, read or delete credentials and cost data without adequate auth.
- **[API-02](#api-02--the-cron-endpoints-move-money-over-http)** — two HTTP endpoints that
  grant credits, triggerable by hand.
- **[API-05](#api-05--the-frontend-calls-a-delete-route-that-does-not-exist)** — the UI
  calls an endpoint nobody wrote.

---

## 2. T0 — Reachable and should not be

### API-01 — Four endpoints are open or wrongly gated

**✅ Verified · Critical**

| Route | Guard | Consequence |
|---|---|---|
| `POST/GET/DELETE /api/v1/email/connections*` (5 routes) | **none** — `Depends(get_db)` only | Anyone can create, list, delete and validate SMTP/IMAP credentials for any company |
| `GET /api/v1/credits/subscription-tiers` | **none** | Pricing readable without a token. The sibling POST/PUT/DELETE *are* admin-gated |
| `GET /api/v1/reports/costing` | `get_current_user` only | Any user reads their company's raw provider cost and infers the markup |
| `PATCH /api/v1/companies/{id}` | company match only, **no role check** | Any user can suspend their own company |
| `PATCH /api/v1/users/{id}` | admin-in-company, no role validation | A `tenant_admin` can set their own role to `app_admin` |

The email router is the standout: five routes managing credentials with no authentication
dependency at all.

- [`ai/email_router.py:88`](../../../backend/src/ai/email_router.py:88), [`:94`](../../../backend/src/ai/email_router.py:94), [`:159`](../../../backend/src/ai/email_router.py:159), [`:179`](../../../backend/src/ai/email_router.py:179), [`:204`](../../../backend/src/ai/email_router.py:204)
- [`billing/credits_router.py:199`](../../../backend/src/billing/credits_router.py:199)
- [`billing/billing_router.py:148`](../../../backend/src/billing/billing_router.py:148)
- [`auth/company_router.py:110`](../../../backend/src/auth/company_router.py:110)
- [`auth/user_router.py:48`](../../../backend/src/auth/user_router.py:48)

Full write-ups in
[04 — Auth, RBAC & tenancy](04-AUTH-RBAC-TENANCY-DEFECTS.md#2-t0--privilege-escalation-and-open-doors).
Also **D-04**, **D-08**, **D-09** in the platform register.

---

### API-02 — The cron endpoints move money over HTTP

**✅ Verified · High**

`POST /api/v1/cron/daily-credits` and `POST /api/v1/cron/monthly-billing` grant credits.
They are `app_admin`-only, which is right, but:

- nothing schedules them, so triggering them by hand is the **only** way they ever run
  ([BC-04](14-BILLING-AND-CREDITS-DEFECTS.md#bc-04--the-billing-crons-are-never-scheduled));
- the daily job **resets** `daily_credits` rather than topping up, so an accidental second
  call is not idempotent;
- the monthly job grants credits regardless of whether money moved.

An operationally necessary endpoint that is also a money lever, with no idempotency and no
audit trail beyond a log line.

- [`billing/cron_router.py`](../../../backend/src/billing/cron_router.py)

---

### API-03 — No webhook signature verification on the gateway's inbound route

**✅ Verified · Critical**

`POST /webhook/inbound` creates executions. Every `validate_signature` returns `True`, and
the result is logged and ignored regardless.

Full write-up:
[GW-01](13-GATEWAY-AND-REALTIME-DEFECTS.md#gw-01--no-webhook-signature-is-ever-verified-and-a-failure-would-not-block).
Listed here because this is the route an integrator will find first, and the reference
should say plainly that it is unauthenticated.

---

### API-04 — `POST /internal/event` is protected by a default secret

**✅ Verified · High**

It is the one route hard-blocked at the gateway middleware, and it is protected by
`X-Internal-Token` compared with `!=` against `INTERNAL_TOKEN`, which defaults to
`change-me-in-production` in code **and** in `.env.example`.

It can create executions.

- [`gateway/auth_middleware.py`](../../../backend/src/gateway/auth_middleware.py)
- [`gateway/gateway_config.py:32`](../../../backend/src/gateway/gateway_config.py:32)

---

## 3. T1 — Documented and not reachable

### API-05 — The frontend calls a delete route that does not exist

**✅ Verified · High**

`KnowledgeBase.tsx` calls `DELETE /ai/documents/{id}`. `ai/router.py` declares only
`POST /documents/upload`, `GET /documents` and `POST /documents/search`.

- [`frontend/src/pages/KnowledgeBase.tsx:106`](../../../frontend/src/pages/KnowledgeBase.tsx:106)
- [`ai/router.py:606`](../../../backend/src/ai/router.py:606), [`:658`](../../../backend/src/ai/router.py:658), [`:667`](../../../backend/src/ai/router.py:667)

Same as [PO-01](01-PRODUCT-OVERVIEW-DEFECTS.md#po-01--deleting-a-knowledge-base-document-always-fails).

---

### API-06 — Password reset: two documented routes, neither implemented

**✅ Verified · High**

The frontend posts to `/auth/forgot-password` and `/auth/reset-password`. Grepping the
whole backend for `forgot`, `reset-password` or `new_password` returns **nothing**.

Both pages fail against a 404 and show "Failed to send reset email".

Same as [AU-06](04-AUTH-RBAC-TENANCY-DEFECTS.md#au-06--password-reset-works-in-the-browser-and-does-not-exist-in-the-backend).

---

### API-07 — Transcript endpoints exist only on a service nobody starts

**✅ Verified · High**

`transcript_api.py` declares four endpoints under `/api/calls/*` and is mounted **only** by
`voice/main.py` on port 8002, which `start_services.sh` does not launch and the gateway
describes as retired.

The call-detail UI that consumes them is therefore broken.

- [`voice/transcript_api.py:21`](../../../backend/src/voice/transcript_api.py:21)
- Also **D-15**; the decided fix is **W-1** — move the router onto the gateway

Note the paths have **no `/v1` segment**. Decide whether to normalise `/api/calls` →
`/api/v1/calls` during the move; doing it later is a second breaking change.

---

### API-08 — `/api/v1/phone-pool/*` does not exist at runtime

**✅ Verified · Medium**

Seven routes are declared in `phone_pool_router.py`. The router is never mounted —
`main.py` says *"Phone Number Pool is now unified into phone_number_router"*.

| Dead | Live |
|---|---|
| `POST /api/v1/phone-pool` | `POST /api/v1/phone-numbers` |
| `POST /api/v1/phone-pool/bulk` | `.../bulk` |
| `POST /api/v1/phone-pool/sync` | `.../sync` |
| `GET /api/v1/phone-pool` | `GET /api/v1/phone-numbers` |
| `POST /api/v1/phone-pool/{id}/claim` | `.../{id}/claim` |
| `POST /api/v1/phone-pool/{id}/release` | `.../{id}/release` |
| `DELETE /api/v1/phone-pool/{id}` | `DELETE /api/v1/phone-numbers/{id}` |

- [`voice/phone_pool_router.py`](../../../backend/src/voice/phone_pool_router.py) — 701 lines, unmounted

---

### API-09 — A failed import silently removes a whole route group

**✅ Verified · High**

About a dozen routers are mounted inside `try/except ImportError` with only a
`logger.warning`: billing, credits, cron, reports, email, social, tool management, voice
webhooks, phone numbers, sessions, messaging.

If one fails to import, the app starts normally and that **entire route group returns
404**. There is no signal on `/health`, in the OpenAPI schema, or anywhere else.

So "the endpoint is missing" has two indistinguishable causes: it was never written, or its
router failed to load.

- [`backend/src/main.py:120`](../../../backend/src/main.py:120) onwards

---

## 4. T2 — Delete

| ID | Delete | Notes | Status |
|---|---|---|---|
| **API-10** | `GET\|POST /api/v1/ai/phase11/{subpath}` | 307 shim carrying an explicit *"Remove after 2026-09-01"* comment. **That date is today.** Remove the five matching legacy routes from the frontend router in the same change | ✅ Verified |
| **API-11** | `GET /api/v1/assets` and `/api/v1/assets/{path}` | Redirect shims to `/api/v1/artifacts*`. The legacy `assets` table they existed for was never dropped either — see [DM-10](03-DATA-MODEL-DEFECTS.md#4-t2--wrong-types-and-dead-tables) | ✅ Verified |
| **API-12** | [`voice/phone_pool_router.py`](../../../backend/src/voice/phone_pool_router.py) | 701 lines, never mounted. **Keep** `phone_pool_models.py` — the live router still imports `PhoneNumber` from it. Also **D-22** | ✅ Verified |
| **API-13** | `GET /api/v1/auth/admin-only` | Exists purely to probe the admin role guard. A debug route on the public surface | ✅ Verified |

---

## 5. T3 — Inconsistency across the surface

### API-14 — Nine admin routes have a doubled `admin/admin` segment

**✅ Verified · Low · accept**

The router is declared `APIRouter(prefix="/ai/admin")` and mounted with `prefix="/api/v1"`.
Nine of its routes then declare their own path starting `/admin/...`, producing
`/api/v1/ai/admin/admin/kpi/runs` and eight siblings.

- [`ai/api/admin.py:60`](../../../backend/src/ai/api/admin.py:60) — the router prefix
- [`ai/api/admin.py:479`](../../../backend/src/ai/api/admin.py:479), [`:574`](../../../backend/src/ai/api/admin.py:574), [`:619`](../../../backend/src/ai/api/admin.py:619), [`:653`](../../../backend/src/ai/api/admin.py:653), [`:706`](../../../backend/src/ai/api/admin.py:706), [`:748`](../../../backend/src/ai/api/admin.py:748), [`:966`](../../../backend/src/ai/api/admin.py:966), [`:1160`](../../../backend/src/ai/api/admin.py:1160), [`:1202`](../../../backend/src/ai/api/admin.py:1202)

**Decision: leave it.** Cosmetic, and changing it breaks the admin UI for no user-visible
gain. Also **D-41**. Recorded so it is not "fixed" in passing.

---

### API-15 — `/api/social-connections` breaks the versioning convention

**✅ Verified · Low**

Declared as `APIRouter(prefix="/api/social-connections")` — the only business route in the
platform with no `/v1` segment.

Adding `/v1` is a breaking change for any client already using it. Worth doing now, while
there are no external consumers.

- [`ai/social_router.py:25`](../../../backend/src/ai/social_router.py:25)

---

### API-16 — There is no universal pagination

**📄 Doc-reported · Medium**

Every list endpoint decides for itself. `GET /config/integrations` as `app_admin` returns
**every company's rows** with no pagination at all
([LP-11 context](10-LLM-PROVIDERS-DEFECTS.md)). `GET /ai/entities`, the execution list and
the artifact list all differ.

A client cannot write one paging helper, and no endpoint degrades gracefully as data grows.

---

### API-17 — Full paths chain two prefixes, so the decorator misleads

**✅ Verified · Low**

`include_router(..., prefix="/api/v1")` + `APIRouter(prefix="/ai")` +
`@router.post("/entities")` = `/api/v1/ai/entities`.

Reading the decorator alone gives the wrong path. Combined with
[API-14](#api-14--nine-admin-routes-have-a-doubled-adminadmin-segment), the real path can
be three concatenations away from what the code shows.

---

### API-18 — `DELETE /api/v1/ai/entities/{id}` is a soft delete

**📄 Doc-reported · Medium**

The row stays; `status` becomes `DELETED` and `deleted_at` is set, recursively across
descendants.

That is a reasonable design and the wrong HTTP verb semantics. A client that deletes and
then lists will still see the entity in any query that forgets
`.where(status != "DELETED")` — and there is no default filter
([DM-16](03-DATA-MODEL-DEFECTS.md#dm-16--soft-delete-has-no-default-filter)).

---

### API-19 — Two similarly named tool endpoints return different things

**📄 Doc-reported · Low**

`GET /api/v1/ai/tools` returns tenant-visible tools. `GET /api/v1/ai/tool-registry` returns
the full registry. The names do not signal the difference, and only one is admin-gated.

---

### API-20 — The credentials guide documents the wrong path prefix

**📄 Doc-reported · Low**

`AI_MODEL_CREDENTIALS_GUIDE.md` documents `/api/config/...`. The real prefix is
`/api/v1/config/...`. Anyone following the guide gets a 404 on their first call.

---

## 6. Improvements

### API-I1 — Add a route census to the merge gate

**Effect: large.** Compare the router decorators against the documented surface in
`17-api-reference.md`. It would catch undocumented routes, dead routers
([API-08](#api-08--apiv1phone-pool-does-not-exist-at-runtime)), mount-order mistakes
([GW-20](13-GATEWAY-AND-REALTIME-DEFECTS.md#gw-20--the-catch-all-proxy-must-stay-last-and-nothing-enforces-it))
and frontend calls to nonexistent endpoints
([API-05](#api-05--the-frontend-calls-a-delete-route-that-does-not-exist)).

This is the first of the four guardrails named in the platform register, and the cheapest
to write.

### API-I2 — Surface failed router mounts

**Effect: medium, large at 3am.**
[API-09](#api-09--a-failed-import-silently-removes-a-whole-route-group). Collect the
`ImportError`s into a list and return it from `/health`. Diagnosing a missing feature area
becomes one curl instead of a log search.

### API-I3 — One pagination contract

**Effect: medium.** [API-16](#api-16--there-is-no-universal-pagination). `limit`, `offset`
and a `total` in the envelope, on every list endpoint. Clients get one helper; the platform
gets endpoints that do not degrade with data volume.

Start with `GET /config/integrations`, which currently returns every company's rows to an
`app_admin` in one response.

### API-I4 — Generate the frontend service layer from OpenAPI

**Effect: large.** FastAPI publishes a schema. `frontend/src/types/index.ts` and the service
modules are hand-maintained against it.

Generating them makes [API-05](#api-05--the-frontend-calls-a-delete-route-that-does-not-exist)
and [API-06](#api-06--password-reset-two-documented-routes-neither-implemented) impossible
by construction — you cannot call a route that is not in the schema — and it fixes the
type-drift problem in
[FE-I7](16-FRONTEND-DEFECTS.md#fe-i7--generate-the-api-types-from-the-backend).

### API-I5 — One auth dependency, applied by default

**Effect: large for safety.** Today each route opts in to `get_current_user`, and
[API-01](#api-01--four-endpoints-are-open-or-wrongly-gated) is what happens when one
forgets.

Apply the dependency at the `include_router` level and make public routes opt **out**
explicitly. Then an unauthenticated endpoint is a deliberate, visible decision.

### API-I6 — Consistent error envelopes

**Effect: medium.** Some routes raise `HTTPException` with a string `detail`, some return
`{"error": ...}`, the gateway proxy returns its own `{"error": "Backend unavailable"}` on
503, and one Tata webhook returns `{"sucess": false}`.

A client cannot write one error handler. One envelope — `{"error": {"code", "message"}}` —
across the whole surface.

### API-I7 — Version the social-connections route

**Effect: small, do it now.** [API-15](#api-15--apisocial-connections-breaks-the-versioning-convention).
There are no external consumers yet, so this is free today and a breaking change later.

### API-I8 — Make soft delete explicit in the API

**Effect: small.** [API-18](#api-18--delete-apiv1aientitiesid-is-a-soft-delete). Return
`202 Accepted` with the new status, or add `?hard=true` for a real delete. Silently
returning `204` for an operation that does not delete is the shape that causes bug reports.

### API-I9 — Publish the OpenAPI schema as an artefact

**Effect: medium.** With the schema checked in and diffed on every change, an unintended
breaking change becomes a visible diff in review rather than a support ticket. It also
gives [API-I1](#api-i1--add-a-route-census-to-the-merge-gate) something concrete to compare
against.

### API-I10 — Rate-limit per route class, not globally

**Effect: medium.** Once
[GW-I1](13-GATEWAY-AND-REALTIME-DEFECTS.md#gw-i1--add-slowapimiddleware) and
[GW-I2](13-GATEWAY-AND-REALTIME-DEFECTS.md#gw-i2--set-remoteipheader-in-the-vhosts) land,
a single `200/minute` for every route is still wrong: `POST /auth/login` wants a tight
per-email limit, `POST /ai/execute` wants a per-company one, and a list endpoint wants
neither. Three limit classes cover the whole surface.

---

## 7. Suggested order of work

| Step | Work | Why here |
|---|---|---|
| **1** | API-01 | Five routes with missing or wrong guards. See register 04 for the fixes |
| **2** | API-03, API-04 | The two unauthenticated execution-creating endpoints |
| **3** | T2 deletions — API-10 to API-13 | Free, and API-10 is past its own removal date |
| **4** | API-05, API-06 | Implement the two routes the frontend already calls |
| **5** | API-07 — **W-1** | Move the transcript router onto the gateway; decide the `/v1` question then |
| **6** | API-I1, API-I2 | The route census and the mount-failure list |
| **7** | API-I5, API-I4 | Auth by default; generate the client from the schema |
| **8** | API-I3, API-I6, API-I7 | Pagination, error envelopes, versioning — the consistency pass |

---

## Where to go next

- [17 — API reference](../17-api-reference.md) — the source document, with the full route
  table.
- [`DEFECT-REGISTER.md`](../DEFECT-REGISTER.md) — API-01 is D-04/D-08/D-09, API-07 is D-15
  and **W-1**, API-10 is D-24, API-12 is D-22, API-14 is D-41.
- [04 — Auth, RBAC & tenancy](04-AUTH-RBAC-TENANCY-DEFECTS.md) — the fixes for API-01.
- [13 — Gateway & real-time](13-GATEWAY-AND-REALTIME-DEFECTS.md) — the port-8001 surface.
- [16 — Frontend](16-FRONTEND-DEFECTS.md) — the client side of API-05 and API-I4.
