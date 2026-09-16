# Defect Register

> **What this document is:** every actionable defect recorded across the 20 numbered
> engineering documents, consolidated, de-duplicated, triaged, and checked against the
> code in this repository.
> **Who should read it:** anyone picking up hardening work, and any agent session
> asked to "fix the defects".
> **Compiled:** 2026-08-15, against branch `fresh-main`.
> **Context:** there are **no paying tenants**. Nothing here is a production
> emergency; everything in T0 is a launch blocker.

---

## How to use this in a fresh session

This file is written to be self-contained. You should not need the conversation that
produced it.

1. **Read the confidence label on every entry before acting.**
   - ✅ **Verified** — the code was read on 2026-08-15 and the claim held. The cited
     file and line are accurate as of that date.
   - 📄 **Doc-reported** — a numbered document asserts it and it was *not*
     independently re-checked. Those documents proved ~97% accurate on the claims that
     were tested, so treat these as high-confidence leads, **but confirm before you
     change code**.
2. **Re-verify line numbers before editing.** Any commit after 2026-08-15 may have
   shifted them. Grep for the quoted symbol rather than trusting the line.
3. **Work in the suggested order** ([§7](#7-suggested-execution-order)), not tier
   order. T2 (deletions) is free and comes first.
4. **Ship behavioural changes behind a feature flag.** The platform has 41 flags with
   entity → company → env → default resolution
   ([`core/feature_flags.py`](../../backend/src/ai/core/feature_flags.py)). Use it —
   see [15 — Governance](15-governance-and-hitl.md).
5. **Definition of done for any migration item: the old path is deleted.** Most of
   T2 exists because a previous migration stopped at "the new thing works".

### Provenance

Compiled by harvesting every ⚠️ marker and every `## Gotchas` entry from the 20
numbered documents — **291 raw items** — then discarding purely explanatory entries
and merging duplicates into **45 defects**, of which **24 were verified against code**.

---

## Contents

1. [Summary](#1-summary)
2. [T0 — Money and access control](#2-t0--money-and-access-control)
3. [T1 — Silently broken](#3-t1--silently-broken)
4. [T2 — Delete](#4-t2--delete)
5. [T3 — Correctness and robustness](#5-t3--correctness-and-robustness)
6. [T4 — Accept and document](#6-t4--accept-and-document)
7. [Suggested execution order](#7-suggested-execution-order)
8. [W-1 — Retire port 8002](#8-w-1--retire-port-8002)
9. [Guardrails](#9-guardrails)

---

## 1. Summary

| Tier | Theme | Count | When |
|---|---|---|---|
| [T0](#2-t0--money-and-access-control) | Money and access control | 10 | Before the first paying tenant |
| [T1](#3-t1--silently-broken) | Silently broken | 11 | Before relying on the feature |
| [T2](#4-t2--delete) | Delete | 9 | **Now** — free, no behaviour change |
| [T3](#5-t3--correctness-and-robustness) | Correctness and robustness | 10 | Needs design; does not block launch |
| [T4](#6-t4--accept-and-document) | Accept and document | 5 | Never — recorded so it is not re-litigated |

Three items are worth reading before anything else:

- **[D-02](#d-02--subscribing-strands-the-wallet-and-grants-nothing)** — a complete
  pay-and-get-nothing path, formed by three separately-documented defects compounding.
- **[D-01](#d-01--top-up-credits-an-amount-the-client-chooses)** — the wallet is
  credited with a client-supplied amount, with no replay guard.
- **[D-11](#d-11--the-inbound-call-credit-gate-cannot-run)** — the inbound-call credit
  gate has never executed; it raises `NameError`, fails open, and logs a message that
  reads like a transient blip.

---

## 2. T0 — Money and access control

These decide whether the first real tenant can be charged correctly and whether their
data is reachable by anyone else. Several are one-line fixes.

### D-01 — Top-up credits an amount the client chooses

**✅ Verified · Critical**

The Razorpay signature *is* verified correctly (HMAC-SHA256 over
`order_id|payment_id`). The problem is what happens next: the wallet is credited with
`payload.amount` taken straight from the request body, never reconciled against the
stored `PaymentTransaction`. There is also no idempotency check on `txn.status`, so
replaying one valid signature credits the wallet again on every replay.

- [`billing/credits_router.py:146`](../../backend/src/billing/credits_router.py:146) — `verify_topup`

**Fix:** credit the amount recorded on the stored transaction, not the request body;
reject when `txn.status == "success"`.

---

### D-02 — Subscribing strands the wallet and grants nothing

**✅ Verified · Critical**

Three confirmed facts compound:

1. `verify_subscription` sets `sub.status = "active"` and
   `wallet.account_model = "subscription"` but never calls
   `inject_subscription_credits`.
2. Deduction branches `if … == "pay_as_you_go"` / `elif … == "subscription"`, so any
   existing `wallet_balance` becomes **unspendable** the moment the model flips.
3. The only caller of `inject_subscription_credits` is the monthly cron — which is
   never scheduled, see [D-03](#d-03--the-billing-crons-are-never-scheduled).

Net effect: a subscriber pays, loses access to their existing balance, and receives
no credits until a human manually POSTs a cron endpoint.

- [`billing/credits_router.py:416`](../../backend/src/billing/credits_router.py:416) — `verify_subscription`
- [`billing/credit_service.py:161`](../../backend/src/billing/credit_service.py:161) and [`:170`](../../backend/src/billing/credit_service.py:170) — the `if`/`elif`
- [`billing/credit_service.py:204`](../../backend/src/billing/credit_service.py:204) — `inject_subscription_credits`

**Fix:** call the credit injection on activation, and let subscription accounts spend
a residual `wallet_balance` (change the `elif` to an independent `if`, or migrate the
balance on switch).

---

### D-03 — The billing crons are never scheduled

**✅ Verified · Critical**

`WorkerSettings.cron_jobs` registers CORTEX resumption, dreaming, critic calibration,
skill promotion, prompt evolution, KPI rollup and cost-estimator refresh. It registers
**no** daily-credit job and **no** monthly-billing job. Both exist only as HTTP
endpoints under `/api/v1/cron` that a human has to trigger.

- [`ai/worker.py:104`](../../backend/src/ai/worker.py:104) — the `cron_jobs` list
- [`billing/cron_service.py`](../../backend/src/billing/cron_service.py) — the jobs themselves
- [`billing/cron_router.py`](../../backend/src/billing/cron_router.py) — the manual endpoints

**Related:** re-running the daily job **resets** rather than tops up —
`wallet.daily_credits = daily_amount` is an assignment
([`credit_service.py`](../../backend/src/billing/credit_service.py), `flush_and_inject_daily_credits`).

---

### D-04 — The email connection API has no authentication

**✅ Verified · Critical**

All five routes on `/api/v1/email/*` depend only on `get_db`. No `get_current_user`,
no `RoleChecker`. This router creates, lists, deletes and validates **SMTP/IMAP
credentials**, which makes it the highest-value unauthenticated surface in the tree.

- [`ai/email_router.py:88`](../../backend/src/ai/email_router.py:88), [`:94`](../../backend/src/ai/email_router.py:94), [`:159`](../../backend/src/ai/email_router.py:159), [`:179`](../../backend/src/ai/email_router.py:179), [`:204`](../../backend/src/ai/email_router.py:204)

**Fix:** add the standard auth dependency and company scoping. Use
[`ai/social_router.py`](../../backend/src/ai/social_router.py) as the reference
pattern — never this file.

---

### D-05 — No inbound webhook signature is ever validated

**✅ Verified · Critical**

The base implementation returns `True` with the docstring *"Default: always True (no
validation)"*. Every concrete strategy returns `True` when the signature header is
absent and carries a `TODO` where the HMAC comparison belongs.

- [`gateway/webhook_inbound.py:59`](../../backend/src/gateway/webhook_inbound.py:59) — base, always `True`
- [`:161`](../../backend/src/gateway/webhook_inbound.py:161) LinkedIn · [`:193`](../../backend/src/gateway/webhook_inbound.py:193) GitHub · [`:250`](../../backend/src/gateway/webhook_inbound.py:250) Facebook

**Fix:** implement the HMAC checks and fail closed. Pairs naturally with
[D-31](#5-t3--correctness-and-robustness) (webhook idempotency).

---

### D-06 — `subscription_tiers` has no migration

**✅ Verified · High**

The table is referenced by the ORM, the credits router and the seed path, but nothing
in `backend/migrations/` creates it. A database built purely from Alembic will not
have the table, and every subscription route fails.

Reproduce: `grep -rl subscription_tiers backend/migrations/` → no match.

- [`billing/billing_models.py`](../../backend/src/billing/billing_models.py) — `SubscriptionTier`

---

### D-07 — `billing_events` has no unique constraint

**✅ Verified · High**

No `__table_args__` and no `UniqueConstraint` on the logical upsert key
(`company_id`, `period_month`, `grouping_type`, `grouping_value`). Concurrent
settlement writes duplicate rows, and every report summing this table over-counts.

- [`billing/billing_models.py:153`](../../backend/src/billing/billing_models.py:153) — `class BillingEvent`

---

### D-08 — Subscription tiers are readable without a token

**✅ Verified · High**

`GET /api/v1/credits/subscription-tiers` takes only
`db: AsyncSession = Depends(get_db)`. The sibling POST/PUT/DELETE routes on the same
path *are* admin-gated; only the read is open.

- [`billing/credits_router.py:199`](../../backend/src/billing/credits_router.py:199)

---

### D-09 — Cost reports are not role-gated

**📄 Doc-reported · High**

Any authenticated user can `GET /api/v1/reports/costing` and read their company's raw
provider cost basis, from which the markup is inferable. Costing and Billing are also
the same underlying query with only a different `totals` dict.

- [`billing/billing_router.py`](../../backend/src/billing/billing_router.py)
- Source: [14 — Billing §16](14-billing-and-credits.md)

---

### D-10 — `partner_admin` can edit platform-wide pricing

**📄 Doc-reported · High**

`PUT /billing/config` reportedly accepts `company_id: null` from a partner admin,
writing the global default row every tenant inherits.

Note the seeded global default is **not** at cost: `mf=1.3`, `pf=0.15`, `spf=0.10`
means a tenant pays **1.625×** raw cost by default. Any pricing analysis assuming
at-cost is wrong.

- [`billing/billing_router.py`](../../backend/src/billing/billing_router.py)
- Source: [14 — Billing §16](14-billing-and-credits.md)

---

## 3. T1 — Silently broken

Features that are wired up, look alive in the UI or config, and do nothing. More
dangerous than obvious breakage because they read as working.

### D-11 — The inbound-call credit gate cannot run

**✅ Verified · Critical**

Both inbound handlers construct `CreditService(db)`, but `db` is not a parameter and
is never assigned — the signatures take only `request`, `session_manager` and
`number_router`. The resulting `NameError` is caught by the surrounding `except`,
logged as *"Pre-call credit check failed (allowing call)"*, and **the call proceeds**.
Inbound calls have never been credit-gated.

- [`voice/webhook_router.py:74`](../../backend/src/voice/webhook_router.py:74) — inside `twilio_incoming_call` (signature at [`:34`](../../backend/src/voice/webhook_router.py:34))
- [`voice/webhook_router.py:615`](../../backend/src/voice/webhook_router.py:615) — inside `tata_incoming_call` (signature at [`:497`](../../backend/src/voice/webhook_router.py:497))

**Fix:** add `db: AsyncSession = Depends(get_db)` to both signatures. One line each.
Consider narrowing the `except` so a coding error cannot masquerade as a transient
failure again.

---

### D-12 — Any Claude integration dies on the first call

**✅ Verified · High**

`anthropic` is in neither `pyproject.toml` nor `backend/.venv`, while the adapter
raises on import. An admin can follow the credentials guide, register an `anthropic`
integration, point `thinking` at it, and every call fails before reaching Vertex AI.
Five of the nine critic-ladder entries route to Claude models.

- [`ai/llm/anthropic_adapter.py:30`](../../backend/src/ai/llm/anthropic_adapter.py:30) — `raise RuntimeError("anthropic package not installed…")`
- [`backend/pyproject.toml:34`](../../backend/pyproject.toml:34) — only `google-genai` and `openai` declared

**Fix:** add the dependency and reinstall, or remove the adapter and the credentials
guide section so nobody can configure a path that cannot work.

---

### D-13 — The child-concurrency cap does not cap

**✅ Verified · High**

`within_child_dispatch_cap` is evaluated; when it returns false the code logs
*"dispatching anyway"* and dispatches. The comment states the cap is now advisory.
`max_concurrent_children` is configurable in the builder and enforces nothing.

- [`ai/core/executors/child_entity.py:112`](../../backend/src/ai/core/executors/child_entity.py:112) — the advisory branch
- [`:48`](../../backend/src/ai/core/executors/child_entity.py:48) — `within_child_dispatch_cap`
- [`:33`](../../backend/src/ai/core/executors/child_entity.py:33) — `DEFAULT_MAX_CONCURRENT_CHILDREN = 8`

**Fix:** either enforce it (queue or await) or remove the setting from the builder so
it stops advertising a control that does not exist.

---

### D-14 — The repository has no functioning CI

**✅ Verified · High · not recorded in the numbered docs**

Worse than the documented "no CI for the main app". The single workflow triggers on
`paths: ["backend/cortex_memory/**"]`, but that directory is now
`backend/cortex_memory_moved_to_pypi_repo/`. The filter matches nothing, so the
workflow has never fired — and its `working-directory: backend/cortex_memory` would
fail if it did. The 1,063 tests run only when someone remembers.

- [`.github/workflows/cortex-memory.yml:11`](../../.github/workflows/cortex-memory.yml:11)

**Fix first.** Nothing in [§9 Guardrails](#9-guardrails) matters until this is
resolved.

---

### D-15 — Transcript endpoints are stranded on a service nobody starts

**✅ Verified · High**

`transcript_api.py` is mounted **only** by `voice/main.py` on port 8002, which
`start_services.sh` does not launch. Four endpoints under `/api/calls/*` are
unreachable and the call-detail UI that consumes them is broken.

**Decided: move onto the gateway and delete the service** — see
[§8 W-1](#8-w-1--retire-port-8002).

- [`voice/transcript_api.py:21`](../../backend/src/voice/transcript_api.py:21)

---

### D-16 — WebRTC video answers only the handshake

**✅ Verified · Medium**

`aiortc` is in neither `pyproject.toml` nor the virtualenv, so `/stream/video` cannot
negotiate a peer connection.

- [`gateway/video_gateway.py`](../../backend/src/gateway/video_gateway.py)

**Fix:** install the dependency, or remove the endpoint and its Apache upgrade rule.

---

### D-17 — Half the social connections cannot refresh their tokens

**✅ Verified · Medium**

`PLATFORM_REFRESH_CONFIG` covers 8 platforms: LinkedIn, Twitter, Facebook, Instagram,
Google Ads, YouTube, TikTok, Reddit. The other **8 of 16** have no entry, so the
connection dies at token expiry with no warning and a human must reconnect.

Missing: Pinterest, Quora, Snapchat Ads, X Ads, YouTube Ads, LinkedIn Ads, LinkedIn
Sales Navigator, Meta Ads.

- [`ai/social_connection_service.py:23`](../../backend/src/ai/social_connection_service.py:23)

---

### D-18 — Azure Realtime voice does not work

**📄 Doc-reported · Medium**

The handler reportedly stores the *client* object where the *session* belongs.
`web_audio_adapter.py` repeats the error and additionally calls a nonexistent method.

- [`voice/azure_realtime.py`](../../backend/src/voice/azure_realtime.py)
- Source: [12 — Voice, Gotchas](12-voice-and-telephony.md)

---

### D-19 — Every WhatsApp AI reply falls back to an apology

**📄 Doc-reported · Medium**

`GeminiTextServiceFactory.get_service` is reportedly called with the wrong keyword
arguments, so every customer receives the fallback string instead of a generated
reply.

- [`voice/whatsapp_handler.py`](../../backend/src/voice/whatsapp_handler.py)
- Source: [12 — Voice, Gotchas](12-voice-and-telephony.md)

---

### D-20 — A custom tool created through the API is inert

**📄 Doc-reported · Medium**

There is no loader behind `tool_registry_entries`, so a tool created through the API
never executes. Separately, the admin UI's `is_enabled` toggle does not gate
execution. Both controls appear functional in the interface.

- [`ai/tool_management_router.py`](../../backend/src/ai/tool_management_router.py)
- Source: [09 — Tools, Gotchas](09-tools.md)

---

### D-21 — The lead queue is never drained

**✅ Verified · Medium**

`lead_queue_worker.py` exists and has **zero importers** anywhere in `backend/src`.
The docs add that its call signature is wrong. Rows accumulate in `lead_queue` and
nothing consumes them.

- [`ai/lead_queue_worker.py`](../../backend/src/ai/lead_queue_worker.py)

**Fix:** decide — wire it into `WorkerSettings` and fix the signature, or delete it
([D-26](#4-t2--delete)). Leaving it is the only wrong answer.

---

## 4. T2 — Delete

**Do these first.** Every item is dead or superseded code that cannot break anything
that is not already broken. Removing it shrinks the surface everyone else has to
reason about — the cheapest risk reduction available. With no paying tenants there is
no reason to defer any of it.

| ID | Delete | Notes | Status |
|---|---|---|---|
| **D-22** | [`voice/phone_pool_router.py`](../../backend/src/voice/phone_pool_router.py) | 701 lines, 7 routes under `/api/v1/phone-pool`, never mounted. **Keep** `phone_pool_models.py` — the live router still imports `PhoneNumber` from it | ✅ Verified |
| **D-23** | [`voice/main.py`](../../backend/src/voice/main.py) + both `streaming.hirebuddha.com` vhosts + the `STREAMING_HOST` default | Blocked on [W-1](#8-w-1--retire-port-8002) only | ✅ Verified |
| **D-24** | The `/api/v1/ai/phase11/*` redirect shim | Carries an explicit *"Remove after 2026-09-01"* comment at [`main.py:105`](../../backend/src/main.py:105). Remove the five matching legacy routes from the frontend router in the same change | ✅ Verified |
| **D-25** | The `video_generation` tool | `ToolStatus.DEPRECATED`, still registered, still selectable because the visibility gate is unwired. Superseded by `video_generate` + `video_edit` | ✅ Verified |
| **D-26** | [`ai/lead_queue_worker.py`](../../backend/src/ai/lead_queue_worker.py) | Or wire it up — see [D-21](#d-21--the-lead-queue-is-never-drained) | ✅ Verified |
| **D-27** | `gateway/main.py` | Dead; only `gateway/app.py` is served | 📄 Doc-reported |
| **D-28** | The legacy `assets` table + its two redirect shims | The artifacts migration said it would drop `assets` and never did | 📄 Doc-reported |
| **D-29** | Duplicate `"meta_agent.board_routing"` key | Declared twice at [`feature_flags.py:53`](../../backend/src/ai/core/feature_flags.py:53) and [`:71`](../../backend/src/ai/core/feature_flags.py:71). Harmless — second wins — but it makes the file look unreviewed | ✅ Verified |
| **D-30** | Unused frontend deps + stale READMEs | `react-hook-form`, `zod`, `date-fns` installed and unused. `core/README.md` documents the deleted `execution_engine.py` | 📄 Doc-reported |

> Before each deletion, confirm there is no remaining importer:
> `grep -rn "<module_name>" backend/src frontend/src --include=*.py --include=*.ts --include=*.tsx`

---

## 5. T3 — Correctness and robustness

Real defects that need a decision and a design, not a one-line patch. None should hold
up a launch.

| ID | Defect | Consequence | Status |
|---|---|---|---|
| **D-31** | No webhook idempotency | Provider retries create duplicate executions and duplicate charges | 📄 Doc |
| **D-32** | Rate limits key on `127.0.0.1` | No vhost sets a forwarded-for header, so every caller shares one bucket | 📄 Doc |
| **D-33** | Child-resolver strategy 4 is not company-scoped | A name-based lookup can cross a tenant boundary | 📄 Doc |
| **D-34** | `_final_status` can return `COMPLETED` when every step failed | Runs that did nothing are billed and reported as successes | 📄 Doc |
| **D-35** | Run status transitions are advisory | `validate_transition` warns but never blocks; illegal states are reachable | 📄 Doc |
| **D-36** | Agent selection is `LIMIT 1` with no `ORDER BY` | Non-deterministic agent choice, in three separate call sites | 📄 Doc |
| **D-37** | No credit holds | Cost accrues during a run and settles at the end, so one run can overdraw | 📄 Doc |
| **D-38** | Frontend has no error boundary | One render throw blanks the entire page | 📄 Doc |
| **D-39** | `npm run lint` fails — no ESLint config exists | The `lint` script is defined in `package.json`; no config file is present. No lint gate at all | ✅ Verified |
| **D-40** | No frontend test runner | Two `.test.ts` files import `vitest`, which is not configured | 📄 Doc |

---

## 6. T4 — Accept and document

Known, understood, and not worth the regression risk. **Recorded so nobody
re-litigates them.**

| ID | Quirk | Why leave it |
|---|---|---|
| **D-41** | Doubled `/api/v1/ai/admin/admin/*` segment | Cosmetic. Changing it breaks the admin UI for no user-visible gain |
| **D-42** | `"sucess"` misspelled in the Tata webhook response | It is an external contract. Correcting it is a breaking change — coordinate with the provider, or never |
| **D-43** | Naive `DateTime` columns throughout | UTC by convention. A timezone migration touches every table and buys little today |
| **D-44** | `JSON` on older tables, `JSONB` on newer | Migrate opportunistically when a table is being changed anyway |
| **D-45** | Postgres on host port 5433, not 5432 | Deliberate — Docker maps `5433:5432`. Fix the stale `backend/.env` instead of the mapping |

---

## 7. Suggested execution order

Deliberately **not** tier order.

### Phase 1 — Clear the ground · all of T2 + W-1

Nine deletions, no behaviour change, no dependencies. Do [W-1](#8-w-1--retire-port-8002)
in the same phase so the 8002 removal lands with the rest.

Adopt the rule that produced most of this tier: **a migration is not done until the
old path is deleted.**

### Phase 2 — Close the money and auth holes · T0

D-01 → D-05 first; those are what matter on day one of real revenue. D-06 and D-07
are schema changes and want a carefully written migration.

### Phase 3 — Make the silent failures loud · T1

Start with **D-11** — a one-line signature fix that restores a credit gate you already
believed you had. Then **D-14**, because CI is what stops this list from regrowing.

Ship each behavioural change behind a feature flag and enable it per company.

### Phase 4 — Design work · T3

Idempotency, credit holds, tenant scoping. These need thought; none block a launch.

---

## 8. W-1 — Retire port 8002

**Decision taken:** move `transcript_api` onto the gateway and delete the voice
service.

**Why it is cheap:** [`transcript_api.py`](../../backend/src/voice/transcript_api.py)
imports only `get_db`, `ConversationLogger` and `SessionManager` — all already
reachable from the gateway process — and declares its own full `/api/calls` prefix, so
nothing needs re-prefixing.

| Step | Action | Watch out for |
|---|---|---|
| 1 | Add `include_router(transcript_router)` to [`gateway/app.py`](../../backend/src/gateway/app.py) | Must sit **above** the catch-all proxy. Ordering is load-bearing — a route added below it is unreachable |
| 2 | Repoint the call-detail UI from the streaming host to the gateway | These paths have **no `/v1`** segment. Decide now whether to normalise `/api/calls` → `/api/v1/calls`; doing it later is a second breaking change |
| 3 | Delete `voice/main.py`, both `streaming.hirebuddha.com` vhosts, and the `STREAMING_HOST` default pointing at 8002 | The other two routers it mounted — `webhook_router` and `messaging_router` — are already mounted by the backend, so nothing else is lost |
| 4 | Verify | Four endpoints answer on the gateway; no vhost references 8002; the three WebSocket paths previously duplicated across both apps still resolve on the gateway |

Related context: [17 — API reference §17](17-api-reference.md), [02 — Architecture §2.6](02-system-architecture.md).

---

## 9. Guardrails

Four mechanical checks that would have caught most of this register. Each is minutes
to write and seconds to run.

| Check | Compares | Catches |
|---|---|---|
| Route census | Router decorators vs the documented API surface in [17](17-api-reference.md) | Undocumented routes, dead routers, mount-order mistakes |
| Schema census | `__tablename__` and columns vs [03](03-data-model.md) | Missing migrations (D-06), undocumented columns |
| Registry census | `ToolRegistry.register` calls vs the catalogue in [09](09-tools.md) | Unregistered tools, deprecated tools still exposed (D-25) |
| Dependency census | Imports in adapters vs `pyproject.toml` and the venv | D-12 and D-16 — adapters whose package was never installed |

> ⚠️ None of these matter until **[D-14](#d-14--the-repository-has-no-functioning-ci)**
> is fixed. Today a workflow exists, looks green in the repository listing, and has
> never run.

---

## Where to go next

- [README](README.md) — the documentation index
- [14 — Billing and credits](14-billing-and-credits.md) — context for all of T0
- [12 — Voice and telephony](12-voice-and-telephony.md) — context for D-11, D-18, D-19
- [18 — Infrastructure](18-infrastructure-and-deployment.md) — context for W-1 and D-14
