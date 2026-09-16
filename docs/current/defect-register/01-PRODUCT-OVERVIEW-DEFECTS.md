# 01. Product & Functional Overview — Defect Register

> **What this document is:** the defects and improvement ideas that sit at the
> *product* level — features a user can see, click or be promised, that do not work
> the way the product says they do.
> **Source document:** [`01-product-overview.md`](../01-product-overview.md)
> **Compiled:** 2026-09-01, against branch `fresh-main`.
> **Context:** there are **no paying tenants**. Nothing here is a live emergency.
> Everything in T0 should be closed before the first paying customer.

---

## How to read this file

- **✅ Verified** — the code was read on 2026-09-01 and the claim held.
- **📄 Doc-reported** — `01-product-overview.md` says it and it was not re-checked
  by hand. Treat it as a strong lead, but confirm before you change code.
- Line numbers move. Search for the quoted function or variable name, not the line.
- Defects come first, then improvements. The two lists are separate on purpose:
  a defect is something broken, an improvement is something that works but costs
  more than it should.

This register is about **whole-product behaviour**. When a defect is really about
one subsystem, the deep entry lives in that subsystem's register and is only
cross-referenced here.

---

## Contents

1. [Summary](#1-summary)
2. [T0 — User-visible things that do not work](#2-t0--user-visible-things-that-do-not-work)
3. [T1 — Promises the product does not keep](#3-t1--promises-the-product-does-not-keep)
4. [T2 — Dead code and dead surfaces](#4-t2--dead-code-and-dead-surfaces)
5. [T3 — Rough edges](#5-t3--rough-edges)
6. [Improvements](#6-improvements)
7. [Suggested order of work](#7-suggested-order-of-work)

---

## 1. Summary

| Tier | Theme | Count | When to do it |
|---|---|---|---|
| [T0](#2-t0--user-visible-things-that-do-not-work) | User-visible things that do not work | 5 | Before the first paying tenant |
| [T1](#3-t1--promises-the-product-does-not-keep) | Promises the product does not keep | 6 | Before selling the feature |
| [T2](#4-t2--dead-code-and-dead-surfaces) | Dead code and dead surfaces | 6 | **Now** — free, nothing changes |
| [T3](#5-t3--rough-edges) | Rough edges | 5 | When the area is next touched |

**Total: 22 defects, 12 improvements.**

The three worth reading first:

- **[PO-01](#po-01--deleting-a-knowledge-base-document-always-fails)** — a button in
  the UI calls an endpoint that does not exist.
- **[PO-04](#po-04--any-logged-in-user-can-read-the-internal-cost-report)** — the raw
  cost basis, from which your margin can be worked out, is readable by any signed-in
  user.
- **[PO-06](#po-06--64-of-the-98-tools-are-unfinished-integrations)** — two thirds of
  the advertised tool count are social integrations that no production entity uses.

---

## 2. T0 — User-visible things that do not work

### PO-01 — Deleting a knowledge-base document always fails

**✅ Verified · High**

The Knowledge Base page has a delete button. It calls
`DELETE /ai/documents/{id}`. That route does not exist. `ai/router.py` declares only
`POST /documents/upload`, `GET /documents` and `POST /documents/search`. The user
clicks delete, gets an error, and the document stays.

- [`frontend/src/pages/KnowledgeBase.tsx:106`](../../../frontend/src/pages/KnowledgeBase.tsx:106) — the call
- [`ai/router.py:606`](../../../backend/src/ai/router.py:606), [`:658`](../../../backend/src/ai/router.py:658), [`:667`](../../../backend/src/ai/router.py:667) — the only three document routes

**Fix:** add the delete route. It must also delete the `document_chunks` rows and
their embeddings, or the deleted document keeps coming back in search results.

---

### PO-02 — A tenant admin can open the AI config page but cannot save

**✅ Verified · Medium**

The React route for `/ai-config` allows `APP_ADMIN` **and** `TENANT_ADMIN`. Every
`/config/task-defaults` endpoint behind that page is guarded by `_require_app_admin`.
So a tenant admin browses to the page, fills the form, presses save, and gets
`403 Only App Administrators can configure AI task defaults`.

- [`frontend/src/router/index.tsx:321`](../../../frontend/src/router/index.tsx:321) — the route gate
- [`config/router.py`](../../../backend/src/config/router.py) — `_require_app_admin`

**Fix:** pick one. Either drop `TENANT_ADMIN` from the route gate, or let a tenant
admin set defaults for their own company. Do not leave a page that only fails on save.

---

### PO-03 — Nothing pushes a new user into onboarding

**✅ Verified · Medium**

The docstring on `onboarding_router.py` says the `ProtectedRoute` guard sends users
with `onboarding_status != "completed"` to `/onboarding`. It does not.
`ProtectedRoute` checks two things only: are you logged in, and is your role allowed.
`onboarding_status` is never read anywhere in the frontend outside a partner
dashboard pill.

A brand new tenant lands on an empty dashboard with no LLM key, no agent and no
phone number, and no prompt telling them what to do first.

- [`frontend/src/router/index.tsx:78`](../../../frontend/src/router/index.tsx:78) — `ProtectedRoute`
- [`auth/onboarding_router.py`](../../../backend/src/auth/onboarding_router.py) — the docstring that claims otherwise

**Fix:** add the redirect in `ProtectedRoute`, or delete the claim from the docstring
and accept that onboarding is optional. The first is better — the wizard is already
built and skippable.

---

### PO-04 — Any logged-in user can read the internal cost report

**✅ Verified · High**

`GET /reports/costing` depends on `get_current_user` and `get_db` and nothing else.
There is no `RoleChecker`. It scopes rows to `current_user.company_id`, so it is not
a cross-tenant leak, but every `tenant_user` can read their company's **raw internal
cost** — what the platform pays providers. Compare that with the billed amount on the
same screen and the markup is obvious.

The React route has no `allowedRoles` at all. The only thing hiding the page is that
the sidebar link is shown to `app_admin` only — anyone who types the URL gets in.

- [`billing/billing_router.py:148`](../../../backend/src/billing/billing_router.py:148) — `get_costing_report`
- [`frontend/src/router/index.tsx:443`](../../../frontend/src/router/index.tsx:443) — `<ProtectedRoute>` with no roles

**Fix:** gate the route to `app_admin`. See also **BC-xx** in
[14 — Billing](14-BILLING-AND-CREDITS-DEFECTS.md).

---

### PO-05 — A reviewer approves without seeing what they are approving

**✅ Verified · High**

Every HITL approval row stores a `context_snapshot` — what the agent was about to do.
`HITLPanel.tsx` never renders it. `grep context_snapshot` in that file returns
nothing. The reviewer sees the trigger string, a run-id prefix and a timestamp, and
two buttons: **Authorize** and **Block Cycle**.

An approval control that shows nothing about the action being approved is not a
safety control; it is a delay.

- [`frontend/src/pages/ai/HITLPanel.tsx`](../../../frontend/src/pages/ai/HITLPanel.tsx)
- [`ai/orm/execution.py:121`](../../../backend/src/ai/orm/execution.py:121) — where the snapshot is stored

**Fix:** render `context_snapshot` on the card, collapsed by default. It is already in
the row the endpoint returns.

---

## 3. T1 — Promises the product does not keep

### PO-06 — 64 of the 98 tools are unfinished integrations

**✅ Verified · High**

`tools/__init__.py` makes exactly 98 `ToolRegistry.register(...)` calls. 64 of those
are social-platform tools — 16 modules × 4 tools each. All of them inherit
`status = ToolStatus.EXPERIMENTAL`, and the tools README says plainly that they are
"not yet wired to any production entity and several are unfinished".

So "98 tools" is a true count of registered classes and a misleading count of working
capability. The number a customer should be told is closer to **34**.

Worse: the visibility gate that is supposed to hide `EXPERIMENTAL` tools is not wired
into execution at all — see
[`TOOL-LAYER-DEFECTS.md` TL-13](TOOL-LAYER-DEFECTS.md#tl-13--the-tool-status-gate-is-not-wired-into-execution).
So they are not just unfinished; they are runnable.

- [`ai/tools/__init__.py`](../../../backend/src/ai/tools/__init__.py) — 98 registrations
- [`ai/tools/social/base.py:48`](../../../backend/src/ai/tools/social/base.py:48) — the status line
- [`ai/tools/README.md`](../../../backend/src/ai/tools/README.md) — the honest note

**Fix:** cut the social set down to the platforms that will actually be sold. See the
recommended reduction in [TOOL-LAYER-DEFECTS.md §7](TOOL-LAYER-DEFECTS.md#7-suggested-execution-order).

---

### PO-07 — You can connect 9 social platforms but 16 have tools

**✅ Verified · Medium**

`VALID_PLATFORMS` in `social_router.py` accepts nine platforms:
`linkedin, twitter, facebook, instagram, google_ads, youtube, tiktok, reddit, quora`.
The tools directory has sixteen. So an agent can be given `pinterest_*`,
`meta_ads_*`, `snapchat_ads_*`, `x_ads_*`, `linkedin_ads_*`, `linkedin_sales_nav_*`
and `youtube_ads_*` tools that can never find a stored connection, because the API
refuses to store one.

The failure surfaces as a runtime credential error inside the tool, not as a clear
"this platform is not supported" message at build time.

- [`ai/social_router.py:65`](../../../backend/src/ai/social_router.py:65) — `VALID_PLATFORMS`
- [`ai/tools/social/`](../../../backend/src/ai/tools/social/) — 16 modules

**Fix:** derive one list from the other. A platform is supported when it has both a
connection type and a tool module — everything else should not be registerable.

---

### PO-08 — `DB_RECORDS` is an advertised context source that does nothing

**✅ Verified · Low**

`ContextSourceType.DB_RECORDS` exists in the backend enum and in the frontend types.
The builder shows the panel with a **Coming Soon** badge and disables it. Nothing
reads the value anywhere.

This is honest in the UI, so it is low severity — but the enum value is live in the
API, so an entity created through the API can carry a `DB_RECORDS` context source
that is silently ignored at run time.

- [`ai/schemas/enums.py:166`](../../../backend/src/ai/schemas/enums.py:166)
- [`frontend/src/types/index.ts:271`](../../../frontend/src/types/index.ts:271)

**Fix:** reject `DB_RECORDS` at the API boundary until it is implemented, so the
"Coming Soon" badge is true on both surfaces.

---

### PO-09 — A mistyped config key in the entity builder disappears silently

**📄 Doc-reported · Medium**

Entity create is a closed Pydantic model. Unknown keys are dropped rather than
rejected. A seed author or an API user who writes `retry_policy` in the wrong JSON
column, or misspells a key, gets a `200 OK` and an entity that quietly ignores the
setting.

The seed authors hit this often enough to write it down as a known trap in
`SeedDocFactoryLite`.

- [`ai/schemas/`](../../../backend/src/ai/schemas/) — the entity create models

**Fix:** set the model to forbid extra fields and return a `422` naming the unknown
key. This is a small change with a large effect on how debuggable the builder is.

---

### PO-10 — A broken import turns a whole feature area into 404s

**✅ Verified · Medium**

Most routers in `main.py` are mounted inside `try / except ImportError` with only a
`logger.warning` on failure. Billing, credits, cron, reports, email, social, tool
management, voice webhooks, phone numbers, sessions and messaging are all mounted
this way.

If one of those modules fails to import — a missing package, a typo — the app starts
normally and that entire feature area returns 404. Nothing in the UI says why.

- [`backend/src/main.py:120`](../../../backend/src/main.py:120) onwards — the mount blocks

**Fix:** keep the `try/except` if you want a partial boot, but record the failures and
expose them on the health endpoint, so "billing is 404" is one API call to diagnose
instead of a log hunt.

---

### PO-11 — Templates sit outside tenant scoping by design

**✅ Verified · Medium**

A template is an ordinary entity row with `is_template = true` and
`company_id = NULL`. `NULL` is what makes it visible to everyone.

That is the intended mechanism, but it means a template is not covered by any of the
`WHERE company_id = ...` filters that protect everything else. Any bug that lets a
non-`app_admin` set `is_template` on their own entity makes that entity global —
including its prompts and its plan.

- [`ai/service.py:32`](../../../backend/src/ai/service.py:32) —
  `effective_company_id = None if entity_data.get("is_template") else company_id`

**Fix:** check the caller's role at that line, not only on the template routes. The
create path is what actually decides the row's visibility.

---

## 4. T2 — Dead code and dead surfaces

Free to remove. Nothing here can break anything that is not already broken.

| ID | Delete | Why | Status |
|---|---|---|---|
| **PO-12** | [`voice/phone_pool_router.py`](../../../backend/src/voice/phone_pool_router.py) | 701 lines, not mounted anywhere. The only surviving reference is a sentence in the replacement's docstring. Also recorded as D-22 in the platform register | ✅ Verified |
| **PO-13** | [`frontend/src/pages/assets/AssetLibrary.tsx`](../../../frontend/src/pages/assets/AssetLibrary.tsx) | 314 lines, not routed, imported by nothing but its own CSS. Replaced by `Artifacts.tsx` | ✅ Verified |
| **PO-14** | `send_whatsapp_message()` in [`voice/whatsapp_handler.py:261`](../../../backend/src/voice/whatsapp_handler.py:261) | Body is a `[MOCK]` log line with the real SDK call commented out. Nothing imports it, but it is easy to grab by mistake | 📄 Doc-reported |
| **PO-15** | The `approval:{id}` Redis publish at [`ai/service.py:854`](../../../backend/src/ai/service.py:854) | Nothing subscribes to it. The live channel is `hitl:{id}`, published by the router at [`ai/router.py:456`](../../../backend/src/ai/router.py:456) and consumed at [`governance_service.py:345`](../../../backend/src/ai/governance/governance_service.py:345) | ✅ Verified |
| **PO-16** | The `/api/v1/ai/phase11/*` and `/admin/phase11/*` redirect shims | Both carry an explicit *"Remove after 2026-09-01"* comment. That date is today | ✅ Verified |
| **PO-17** | The `video_generation` deprecated tool | `ToolStatus.DEPRECATED`, still registered, still selectable because the visibility gate is unwired. Superseded by `video_generate` + `video_edit` | ✅ Verified |

> Before deleting, confirm nothing still imports it:
> `grep -rn "<module_name>" backend/src frontend/src --include=*.py --include=*.ts --include=*.tsx`

---

## 5. T3 — Rough edges

### PO-18 — Two Redis channels look like the HITL channel

**✅ Verified · Low**

`hitl:{id}` is the real one. `approval:{id}` is published and never consumed. A
developer debugging a stuck approval will find the wrong channel first, because the
comment above the dead publish says *"The execution engine subscribes to
`approval:{approval_id}` before gating"* — which is not true.

Covered by the deletion in [PO-15](#4-t2--dead-code-and-dead-surfaces); listed here
because the misleading comment is the actual cost.

---

### PO-19 — The SSE stream closes on a substring match

**📄 Doc-reported · Low**

The browser stops listening when it sees `COMPLETED`, `FAILED` or `CANCELLED` in the
raw JSON payload — a substring match, not a field read. Any event that happens to
carry one of those words inside a message, a tool result or a critic note will close
the stream early and the user will think the run stopped.

- [`frontend/src/hooks/useExecutionEvents.ts`](../../../frontend/src/hooks/useExecutionEvents.ts)

**Fix:** match on the parsed `status` field.

---

### PO-20 — A long HITL timeout ties up a worker

**✅ Verified · Medium**

The governance service subscribes to `hitl:{approval_id}` and then blocks, polling
until `timeout_ms`. The default is 5 minutes, but the field is free — a tenant can set
an hour. That worker slot is unavailable for that whole hour.

With a small worker pool, a handful of pending approvals can stall every other run in
the company.

- [`ai/governance/governance_service.py:345`](../../../backend/src/ai/governance/governance_service.py:345)

**Fix:** stop blocking. Park the run in `PAUSED`, release the worker, and re-enqueue
it when the approval is answered. This is the single biggest throughput change
available in the kernel.

---

### PO-21 — "Agent" means four different things

**📄 Doc-reported · Low**

`AGENT` is one of four entity types, but the UI, the docs and the sidebar all use
"agent" loosely for any entity. New developers and new customers both misread
capacity limits and pricing because of it.

**Fix:** in user-facing copy, say "agent" only for the type. Everywhere else say
"entity" or the specific type.

---

### PO-22 — Costing and billing reports are the same query

**✅ Verified · Low**

`GET /reports/billing` calls `svc.get_costing_report(...)` — the same method, the same
rows — and only builds a different `totals` dict. The comment says so:
*"For now billing and costing use the same data source"*.

That is fine today, but the two reports have different audiences and one of them
(costing) should not be visible to a tenant at all. Sharing the query makes it easy to
gate one and forget the other, which is exactly what happened in
[PO-04](#po-04--any-logged-in-user-can-read-the-internal-cost-report).

- [`billing/billing_router.py:188`](../../../backend/src/billing/billing_router.py:188)

---

## 6. Improvements

These are not broken. They are places where the product costs more — in money, in
latency, or in user confusion — than it needs to.

### PO-I1 — Stop blocking a worker on human approval

**Effect: large.** See [PO-20](#po-20--a-long-hitl-timeout-ties-up-a-worker). Moving
from "block and poll" to "pause and re-enqueue" frees worker capacity in direct
proportion to how much HITL a tenant uses. It also makes long approval windows a
product feature instead of a capacity problem.

### PO-I2 — Show the cost of a hierarchy before it is run

**Effect: large.** Every extra level in an `ACTION → SKILL → AGENT → PROCESS` tree
adds a full perceive-strategise-act-critique cycle. `SeedDocFactoryLite` exists only
because a 50-entity hierarchy was multiplying LLM calls.

The builder should show an estimated per-run cost as the tree is assembled, using the
same `cost_estimator` the planner already has. Users cannot avoid a cost they cannot
see.

### PO-I3 — Warn in the builder when a child entity is not ACTIVE

**Effect: medium.** A `PROCESS` whose children are still `DRAFT` will fail at
dispatch. The graph editor already runs a validation pass on every change; add the
status check there so the problem is caught at build time, not at run time.

### PO-I4 — Make the template clone report what it cloned

**Effect: medium.** `clone_template` walks three separate discovery paths — the
`parent_id` FK, the `hierarchy.children` JSON, and the static plan's
`CHILD_ENTITY_INVOCATION` targets. When a seed wires children in only one of those
ways, a partial clone is possible and nothing says so. Return the list of cloned ids
and show it in the toast.

### PO-I5 — Replace the 10-second approvals poll with the existing SSE channel

**Effect: medium.** `HITLPanel` polls `GET /ai/approvals/pending` every 10 seconds for
every open browser tab. The platform already publishes `approval_required` on the
run's Redis channel. Reusing it removes a constant background query and makes
approvals appear instantly.

### PO-I6 — Cache the partner entity fan-out

**Effect: medium.** `GET /ai/entities` runs one extra query **per child tenant** for
`partner_admin` and `partner_user`, then merges and de-duplicates in Python. A partner
with 50 tenants pays 51 queries for one page load. One query with
`company_id IN (...)` replaces the whole loop.

### PO-I7 — Give the wallet a low-balance warning before the run dies

**Effect: medium.** The credit circuit breaker stops a run mid-flight with *"Partial
results saved. Please top up credits and retry."* By then the money is spent and the
work is half done. A pre-run estimate compared against the balance would let the
platform refuse to start a run it cannot afford to finish.

### PO-I8 — One number for "how many tools do I have"

**Effect: medium.** Today there are three different true answers: 98 registered
classes, 34 usable ones, 16 social modules, 9 connectable platforms. Every surface
quotes a different one. Pick "tools an agent in this company can actually call today"
and show that everywhere.

### PO-I9 — Surface failed router mounts on the health endpoint

**Effect: small, high value at 3am.** See
[PO-10](#po-10--a-broken-import-turns-a-whole-feature-area-into-404s). Collect the
`ImportError`s into a list and return it from `/health`. Diagnosing a missing feature
area becomes one curl instead of a log search.

### PO-I10 — Let the entity builder test one step

**Effect: large for users.** Today the only way to know whether a prompt template or a
tool binding works is to run the whole entity and pay for it. A "run this step only"
button against a saved draft would cut the build-test loop from minutes and dollars to
seconds and cents.

### PO-I11 — Show `total_cost_usd` and `billed_amount` side by side, always

**Effect: small.** Both live on `execution_runs` and they are different numbers.
Reporting on the wrong one misstates revenue. Any screen that shows one should show
both, labelled "our cost" and "charged".

### PO-I12 — Add a "what does this company actually have" page

**Effect: medium.** Support questions today ("why did my agent fail?") usually resolve
to one of: no LLM integration, no credits, an entity still in `DRAFT`, a tool that is
`EXPERIMENTAL`, or an unclaimed phone number. All five are one query each. One
diagnostic page for a tenant admin would remove most support load.

---

## 7. Suggested order of work

| Step | Work | Why here |
|---|---|---|
| **1** | T2 deletions — PO-12 to PO-17 | Free. The phase11 shims are already past their own removal date |
| **2** | PO-04, PO-01, PO-05 | Each is a small, self-contained change with a directly visible effect |
| **3** | PO-02, PO-03, PO-08 | Align the UI's promises with the API's rules |
| **4** | PO-I1 (worker blocking) then PO-20 | The largest throughput win in the product |
| **5** | PO-06, PO-07 | Decide the real tool surface before anyone sells it |
| **6** | PO-I2, PO-I10 | Build-time cost visibility and step testing — the two things that make the builder usable at scale |

---

## Where to go next

- [01 — Product & functional overview](../01-product-overview.md) — the document these
  defects were found against.
- [`DEFECT-REGISTER.md`](../DEFECT-REGISTER.md) — the platform-wide list. PO-12,
  PO-16 and PO-17 also appear there as D-22, D-24 and D-25.
- [04 — Auth, RBAC & tenancy](04-AUTH-RBAC-TENANCY-DEFECTS.md) — for PO-04 and PO-11.
- [`TOOL-LAYER-DEFECTS.md`](TOOL-LAYER-DEFECTS.md) — for PO-06 and PO-07 in depth.
- [15 — Governance & HITL](15-GOVERNANCE-AND-HITL-DEFECTS.md) — for PO-05 and PO-20.
