# Defect Register — Index

> **What this folder is:** one defect register per numbered engineering document, plus a
> deep pass over the tool layer. Each file lists what is broken in that module and what
> would make it more efficient.
> **Compiled:** 2026-09-01, against branch `fresh-main`.
> **Context:** there are **no paying tenants**. Nothing here is a production emergency.
> Everything marked T0 should close before the first one.

---

## How to use this folder

1. **Find the register for the area you are touching** in the table below. Each one maps
   one-to-one onto a document in [`docs/current/`](../).
2. **Read the confidence label on every entry before acting.**
   - ✅ **Verified** — the code was read on 2026-09-01 and the claim held.
   - 📄 **Doc-reported** — a numbered document asserts it and it was not independently
     re-checked. Treat as a high-confidence lead; confirm before you change code.
3. **Re-verify line numbers before editing.** Any commit after 2026-09-01 may have shifted
   them. Grep for the quoted symbol rather than trusting the line.
4. **Work the "Suggested order of work" section**, not tier order. Deletions are free and
   come first in almost every file.
5. **Definition of done for any migration item: the old path is deleted.** A large share of
   these defects exist because a previous migration stopped at "the new thing works".

Every file has the same shape: **defects first, grouped by severity; improvements second.**
The two lists are separate on purpose — a defect is something broken, an improvement is
something that works but costs more than it should.

---

## The registers

| # | Register | Source document | Defects | Improvements |
|---|---|---|---:|---:|
| 01 | [Product & functional overview](01-PRODUCT-OVERVIEW-DEFECTS.md) | [01](../01-product-overview.md) | 22 | 12 |
| 02 | [System architecture & topology](02-SYSTEM-ARCHITECTURE-DEFECTS.md) | [02](../02-system-architecture.md) | 21 | 10 |
| 03 | [Database & data model](03-DATA-MODEL-DEFECTS.md) | [03](../03-data-model.md) | 20 | 10 |
| 04 | [Auth, RBAC & multi-tenancy](04-AUTH-RBAC-TENANCY-DEFECTS.md) | [04](../04-auth-rbac-tenancy.md) | 22 | 10 |
| 05 | [The agent kernel](05-AGENT-KERNEL-DEFECTS.md) | [05](../05-agent-kernel.md) | 21 | 10 |
| 06 | [Entities & the execution pipeline](06-EXECUTION-PIPELINE-DEFECTS.md) | [06](../06-execution-pipeline.md) | 24 | 10 |
| 07 | [Planning, critics & self-correction](07-PLANNING-AND-CRITICS-DEFECTS.md) | [07](../07-planning-and-critics.md) | 22 | 10 |
| 08 | [Memory, CORTEX & retrieval](08-MEMORY-AND-CORTEX-DEFECTS.md) | [08](../08-memory-and-cortex.md) | 20 | 10 |
| 09 | [Tools & the tool registry](09-TOOLS-DEFECTS.md) | [09](../09-tools.md) | 6 + **[49 deep](TOOL-LAYER-DEFECTS.md)** | 10 |
| 10 | [LLM providers & routing](10-LLM-PROVIDERS-DEFECTS.md) | [10](../10-llm-providers.md) | 24 | 10 |
| 11 | [Meta-intelligence & the Board](11-META-INTELLIGENCE-DEFECTS.md) | [11](../11-meta-intelligence.md) | 19 | 10 |
| 12 | [Voice, telephony & messaging](12-VOICE-AND-TELEPHONY-DEFECTS.md) | [12](../12-voice-and-telephony.md) | 21 | 10 |
| 13 | [Gateway & real-time transport](13-GATEWAY-AND-REALTIME-DEFECTS.md) | [13](../13-gateway-and-realtime.md) | 21 | 10 |
| 14 | [Billing, costing & credits](14-BILLING-AND-CREDITS-DEFECTS.md) | [14](../14-billing-and-credits.md) | 25 | 10 |
| 15 | [Governance, HITL & feature flags](15-GOVERNANCE-AND-HITL-DEFECTS.md) | [15](../15-governance-and-hitl.md) | 21 | 10 |
| 16 | [Frontend architecture](16-FRONTEND-DEFECTS.md) | [16](../16-frontend.md) | 23 | 10 |
| 17 | [API reference](17-API-REFERENCE-DEFECTS.md) | [17](../17-api-reference.md) | 20 | 10 |
| 18 | [Infrastructure & deployment](18-INFRASTRUCTURE-AND-DEPLOYMENT-DEFECTS.md) | [18](../18-infrastructure-and-deployment.md) | 21 | 10 |
| 19 | [Testing & quality gates](19-TESTING-DEFECTS.md) | [19](../19-testing.md) | 19 | 10 |
| 20 | [Developer onboarding & glossary](20-ONBOARDING-AND-GLOSSARY-DEFECTS.md) | [20](../20-onboarding-and-glossary.md) | 18 | 10 |
| — | [**Tool layer — deep pass**](TOOL-LAYER-DEFECTS.md) | [09](../09-tools.md) | 49 | — |

**459 defects, 202 improvements.**

Related: [`../DEFECT-REGISTER.md`](../DEFECT-REGISTER.md) is the earlier platform-wide list
(45 items, `D-nn`). Every one of its entries reappears in the module register that owns it,
cross-referenced by its `D-nn` id.

---

## The ten findings that matter most

Ranked by consequence, not by how hard they are to fix. Six of the ten are small changes.

| # | Finding | Where | Why it matters |
|---|---|---|---|
| 1 | **The wallet is credited with an amount the client chooses**, with no replay guard | [BC-01](14-BILLING-AND-CREDITS-DEFECTS.md#bc-01--the-client-chooses-how-much-to-credit-its-own-wallet) | Verify a $1 payment, claim $1000, repeat |
| 2 | **Any admin can promote themselves to `app_admin`** | [AU-01](04-AUTH-RBAC-TENANCY-DEFECTS.md#au-01--any-admin-can-promote-themselves-to-app_admin) | One PATCH; `app_admin` then bypasses every tenant filter |
| 3 | **The email-connection API has no authentication** | [AU-02](04-AUTH-RBAC-TENANCY-DEFECTS.md#au-02--the-email-connection-api-has-no-authentication-at-all) | Five routes managing SMTP/IMAP credentials, open |
| 4 | **CORTEX is write-only** — memory is recorded and never read back into a prompt | [MC-01](08-MEMORY-AND-CORTEX-DEFECTS.md#mc-01--cortex-is-write-only-on-the-live-path) | An agent's tenth run knows what its first run knew |
| 5 | **Three of the four credit gates have no callers** | [BC-05](14-BILLING-AND-CREDITS-DEFECTS.md#bc-05--three-of-the-four-credit-gates-have-no-callers) | No pre-run gate, no in-run breaker. Both are written and tested |
| 6 | **No webhook signature is verified, and a failure would not block** | [GW-01](13-GATEWAY-AND-REALTIME-DEFECTS.md#gw-01--no-webhook-signature-is-ever-verified-and-a-failure-would-not-block) | Anyone who can reach the endpoint can run any tenant's agents |
| 7 | **The default sandbox runs LLM-authored code as the backend OS user** | [TL-01](TOOL-LAYER-DEFECTS.md#tl-01--the-default-sandbox-runs-llm-authored-code-as-the-backend-os-user) + [TX-01](09-TOOLS-DEFECTS.md#tx-01--the-per-company-sandbox-flag-is-never-read) | The feature flag says "on"; the runtime default says "off"; off wins |
| 8 | **A run where every step failed can report `COMPLETED`** | [AK-01](05-AGENT-KERNEL-DEFECTS.md#ak-01--a-run-where-every-step-failed-can-report-completed) | Runs that did nothing are billed and counted as successes |
| 9 | **Every retry strategy executes identically** | [PC-06](07-PLANNING-AND-CRITICS-DEFECTS.md#pc-06--every-retry-strategy-executes-identically) | The remedy is chosen, logged, and then dropped |
| 10 | **There is no CI** — the one workflow filters on a directory that no longer exists | [TS-01](19-TESTING-DEFECTS.md#ts-01--the-only-ci-workflow-has-never-fired) | 1,063 tests and three working gates run only when someone remembers |

---

## Five patterns that explain most of the list

Fixing a pattern is cheaper than fixing its symptoms one at a time.

### 1. Built, tested, never called

The single most common shape in this codebase. A module is complete, has unit tests, and
has **no production call site**:

`ToolCostResolver` · `RedisRateLimiter` · `TrustLearner` · `FailurePatternService` ·
`check_credit_gate` · `consume_step_cost` · `check_credit_circuit_breaker` ·
`assemble_memory` · `CortexBridge.get_relevant_knowledge` · `PlanGenerator.replan` ·
`Budget.can_afford` · `get_reasoning` · `get_visible_tools_for_company` ·
`get_tools_for_company` · `EgressProxyManager`

**Being unit-tested is not evidence that a module runs.** Grep for call sites before
assuming a tested module is a live one. The check that would catch this is
[TS-I7](19-TESTING-DEFECTS.md#ts-i7--add-a-declared-but-never-called-check).

### 2. Declared but not enforced

A setting is authored in the UI, saved, shown back — and read by nothing. At least eight
feature flags, eight entity-builder settings, `routing_mode`, `max_concurrent_children`,
`max_calls_per_hour`, `max_retries`, `rate_limit_per_run`, `max_recursion_depth`,
`io_contract.input_schema`.

Adding a flag is not the same as wiring a control. See
[EP-05](06-EXECUTION-PIPELINE-DEFECTS.md#ep-05--eight-settings-in-the-builder-have-no-runtime-reader)
and [GH-16](15-GOVERNANCE-AND-HITL-DEFECTS.md#4-t2--feature-flags-that-are-not-controls).

### 3. Gates that fail open

Credit checks, HITL pub/sub, rate limiting, suspension middleware, semantic duplicate
detection, webhook signatures, anti-sprawl — every one swallows its errors and lets the
request through.

Each was written so a broken control could not break a run. Together they mean **a failing
gate and a passing gate are indistinguishable**. See
[GH-21](15-GOVERNANCE-AND-HITL-DEFECTS.md#gh-21--almost-every-gate-in-the-platform-fails-open).

### 4. Half-finished migrations

The new path works and the old one was never deleted: two `ToolResult` classes, two healing
ladders, two RAG paths, two episodic stores, four price tables, two gateways, two config
classes, the `assets` table, `models.py`, the root `tests/`, `phone_pool_router.py`,
`voice/main.py`.

Adopt the rule that would have prevented all of them: **a migration is not done until the
old path is deleted.**

### 5. Money tracked in several places and reconciled with `max()`

The loop's `Budget`, `run.total_cost_usd` written by nested step code on a different
session, and `usage_logs` written by the critics. Reconciled once per iteration in an order
that is easy to break, with three cost surfaces that write no ledger row at all.

One write path — every spender writes one attributed `usage_logs` row — closes five
separate defects. See
[BC-I3](14-BILLING-AND-CREDITS-DEFECTS.md#bc-i3--one-cost-write-path) and
[AK-I1](05-AGENT-KERNEL-DEFECTS.md#ak-i1--one-cost-write-path).

---

## Where to start

If you are picking up hardening work and want the order that produces the most value per
day:

| Phase | Work | Registers |
|---|---|---|
| **1. Turn on the lights** | Fix CI, make skips fail, add gate-failure metrics, add an error boundary | [19](19-TESTING-DEFECTS.md), [18](18-INFRASTRUCTURE-AND-DEPLOYMENT-DEFECTS.md), [15](15-GOVERNANCE-AND-HITL-DEFECTS.md), [16](16-FRONTEND-DEFECTS.md) |
| **2. Close the money and auth holes** | BC-01, BC-02, BC-03, AU-01, AU-02, AU-03, GW-01 | [14](14-BILLING-AND-CREDITS-DEFECTS.md), [04](04-AUTH-RBAC-TENANCY-DEFECTS.md), [13](13-GATEWAY-AND-REALTIME-DEFECTS.md) |
| **3. Clear the ground** | Every T2 deletion across all registers. Free, and it shrinks what everyone else has to reason about | all |
| **4. Call what already exists** | The credit gates, the memory read path, the cost resolver, the two worker jobs | [14](14-BILLING-AND-CREDITS-DEFECTS.md), [08](08-MEMORY-AND-CORTEX-DEFECTS.md), [09](09-TOOLS-DEFECTS.md), [02](02-SYSTEM-ARCHITECTURE-DEFECTS.md) |
| **5. Fix the defaults** | `STREAMING_HOST`, the gateway DB port, `cost_unit`, Redis URL parsing, placeholder secrets | [02](02-SYSTEM-ARCHITECTURE-DEFECTS.md), [10](10-LLM-PROVIDERS-DEFECTS.md) |
| **6. Make the run report the truth** | AK-01, then the single cost write path | [05](05-AGENT-KERNEL-DEFECTS.md), [14](14-BILLING-AND-CREDITS-DEFECTS.md) |
| **7. Throughput** | Stop blocking a worker on HITL; enforce the child cap; add LLM retry and timeout | [15](15-GOVERNANCE-AND-HITL-DEFECTS.md), [05](05-AGENT-KERNEL-DEFECTS.md), [10](10-LLM-PROVIDERS-DEFECTS.md) |
| **8. Design work** | Tenancy as a structural boundary, credit holds, the typed tool contract, idempotency | [04](04-AUTH-RBAC-TENANCY-DEFECTS.md), [14](14-BILLING-AND-CREDITS-DEFECTS.md), [09](09-TOOLS-DEFECTS.md) |

---

## Keeping this current

These registers describe code, so they rot. When you fix something:

1. Mark the entry resolved in its register rather than deleting it — the history is useful.
2. If the fix changes the source document's description, update that document too.
3. If you find a new defect, add it to the register that owns the module, using the next
   free id in that file's prefix.

The four **census checks** in
[IN-I10](18-INFRASTRUCTURE-AND-DEPLOYMENT-DEFECTS.md#in-i10--write-the-four-census-checks)
plus the **never-called check** in
[TS-I7](19-TESTING-DEFECTS.md#ts-i7--add-a-declared-but-never-called-check) are what stop
this list regrowing. Between them they would have caught seventeen of the entries here.
