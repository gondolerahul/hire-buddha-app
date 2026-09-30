# 01. Product & Functional Overview — Defect Register

> **What this document is:** the defects and improvement ideas that sit at the
> *product* level — features a user can see, click or be promised, that do not work
> the way the product says they do.
> **Source document:** [`01-product-overview.md`](../01-product-overview.md)
> **Compiled:** 2026-09-01, against branch `fresh-main`. **Last reviewed:** 2026-09-29, on
> branch `roadmap-development-defect-fixes`, with the product owner.
> **Context:** there are **no paying tenants**. Nothing here is a live emergency.
> Everything in T0 should be closed before the first paying customer.

---

## How to read this file

- **✅ Verified** — the code was read on 2026-09-01 and the claim held.
- **📄 Doc-reported** — `01-product-overview.md` says it and it was not re-checked
  by hand. Treat it as a strong lead, but confirm before you change code.
- **Status** — `open` (scheduled for fixing), `fixed` (with commit), `deferred` (real,
  not scheduled; pick up on request), or `won't fix` (the behaviour is intended). The
  product owner's decision from the 2026-09-29 review is quoted under each entry.
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

| Tier | Theme | Count | Open | Fixed | Deferred | Won't fix |
|---|---|---|---|---|---|---|
| [T0](#2-t0--user-visible-things-that-do-not-work) | User-visible things that do not work | 5 | 0 | 4 | 1 | 0 |
| [T1](#3-t1--promises-the-product-does-not-keep) | Promises the product does not keep | 6 | 1 | 3 | 1 | 1 |
| [T2](#4-t2--dead-code-and-dead-surfaces) | Dead code and dead surfaces | 6 | 0 | 6 | 0 | 0 |
| [T3](#5-t3--rough-edges) | Rough edges | 5 | 0 | 1 | 4 | 0 |

**Total: 22 defects (1 open, 14 resolved, 6 deferred, 1 won't fix), 12 improvements (11 deferred; PO-I9 done by PO-10).** The one open defect is PO-07 (social connections); PO-06 delivered its audit.

| ID | Defect | Status |
|---|---|---|
| PO-01 | Deleting a knowledge-base document always fails | ✅ fixed `4ff3778` |
| PO-02 | A tenant admin can open the AI config page but cannot save | ✅ fixed `c8f4d52` |
| PO-03 | Nothing pushes a new user into onboarding | ⏸ deferred |
| PO-04 | Any logged-in user can read the internal cost report | ✅ fixed `682da36` |
| PO-05 | A reviewer approves without seeing what they are approving | ✅ fixed `ad74c46` |
| PO-06 | 64 of the 98 tools are unfinished integrations | ✅ audit delivered `579c14f` |
| PO-07 | You can connect 9 social platforms but 16 have tools | open |
| PO-08 | `DB_RECORDS` is an advertised context source that does nothing | ⏸ deferred |
| PO-09 | A mistyped config key in the entity builder disappears silently | ✅ fixed `3fadd76` |
| PO-10 | A broken import turns a whole feature area into 404s | ✅ fixed `0fd3b29` |
| PO-11 | Templates sit outside tenant scoping by design | won't fix |
| PO-12 | `voice/phone_pool_router.py` | ✅ fixed `964c9ab` |
| PO-13 | `pages/assets/AssetLibrary.tsx` | ✅ fixed `9719f1b` |
| PO-14 | Mock `send_whatsapp_message()` | ✅ fixed `2e8410b` |
| PO-15 | Unconsumed `approval:{id}` publish | ✅ fixed `ba5e6ec` |
| PO-16 | The phase11 redirect shims | ✅ fixed `6d90428` |
| PO-17 | The deprecated `video_generation` tool | ✅ fixed `a8fb38e` |
| PO-18 | Two Redis channels look like the HITL channel | ✅ fixed `ba5e6ec` (by PO-15) |
| PO-19 – PO-22 | Rough edges | ⏸ deferred |
| PO-I1 – PO-I12 | Improvements | ⏸ deferred, except PO-I9 — done by PO-10 — and PO-I6, done by AU-20 |

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

**✅ Verified · High** · **Status: fixed (2026-09-29, `4ff3778`)**

> **Product owner, 2026-09-29:** document upload was wired to the legacy RAG path, which
> has been retired. The knowledge base must now run on CORTEX memory, and all the basic
> operations — create, read, update and delete — must work.

The Knowledge Base page has a delete button. It calls
`DELETE /ai/documents/{id}`. That route does not exist. `ai/router.py` declares only
`POST /documents/upload`, `GET /documents` and `POST /documents/search`. The user
clicks delete, gets an error, and the document stays.

- [`frontend/src/pages/KnowledgeBase.tsx:106`](../../../frontend/src/pages/KnowledgeBase.tsx:106) — the call
- [`ai/router.py:606`](../../../backend/src/ai/router.py:606), [`:658`](../../../backend/src/ai/router.py:658), [`:667`](../../../backend/src/ai/router.py:667) — the only three document routes

**Fix:** add the delete route. It must also delete the document's chunk nodes (and their
embeddings) from the company or entity Knowledge Tree, or the deleted document keeps
coming back in search results. *(Updated 2026-09-28: the v1 `document_chunks` table was
dropped in `a30bb85`; documents are now chunked into CORTEX Knowledge Trees — see
[MC-12](08-MEMORY-AND-CORTEX-DEFECTS.md).)*

**Done (2026-09-29).** Upload already ingested into Knowledge Trees; the rest of CRUD is
built on the same nodes. `ai/services/knowledge_base.py` (`KnowledgeBaseService`) keeps the
`documents` row and its nodes in step, using host-side node operations in
`ai/memory/knowledge_tree_service.py` — no change to the `cortex_memory` package, nothing to
port.

| Operation | Endpoint | Row | Knowledge Tree |
|---|---|---|---|
| Create | `POST /ai/documents/upload` (`?entity_id=` optional) | created, `processing` | ingested by `process_document` into the agent's tree or the company tree |
| Read | `GET /ai/documents`, `GET /ai/documents/{id}` | + `entity_name` | chunk counts, section titles, opening text |
| Update — rename | `PATCH /ai/documents/{id}` `{filename}` | `filename` | every node's `source_ref.filename`, the document node's title |
| Update — scope | `PATCH /ai/documents/{id}` `{entity_id}` (`null` = company-wide) | `entity_id` | nodes moved to the target tree, re-parented under its root |
| Update — content | `POST /ai/documents/{id}/file` | name, type, size, `processing` | old nodes deleted; the job ingests the new file |
| Delete | `DELETE /ai/documents/{id}` | deleted | every node deleted, with embeddings and edges |

Also:

- Every operation is confined to the caller's company. Uploading or moving a document to
  **another company's agent is now refused** (404); before, `upload` accepted any
  `entity_id`.
- Rename, re-scope and replace return 409 while the document is `processing` — the job has
  already read the scope and filename.
- Tree `total_nodes` counts are adjusted on delete and move.
- Deleting an entity already turned its documents company-wide in the `documents` table,
  but left their nodes in the deleted entity's tree, where no agent could read them. The
  nodes now move to the company tree too.
- The enqueue builds its Redis settings from `REDIS_URL` — two of SA-04's five sites are gone
  (this one and PO-15's).
- The page: an upload scope picker; per document View (outline and text), Edit (name and
  scope), Replace and Delete; errors are shown instead of logged; the list refreshes while
  anything is processing.

**Evidence:** `tests/integration/test_knowledge_base_crud.py`, 8 cases against the real
Postgres in a rolled-back transaction: read outline; delete removes the row and every node,
adjusts `total_nodes`, drops the document from search and leaves other documents alone;
rename reaches every node and search results; re-scope moves the nodes both ways; replace
drops old nodes and re-queues; 409 while processing; another company gets 404 and cannot
scope a document to its own agent; `DELETE /ai/documents/{id}` through the router (404 on
the old router). Live on the local stack: uploaded a Markdown file on the page, viewed its
sections and text, renamed it and scoped it to an agent (all five nodes moved to that
agent's tree with the new name), replaced it (old nodes gone, new content in the same tree),
deleted it (no row and no nodes left). Embedding was not exercised live — Vertex ADC had
expired, so the uploads ended `failed` with unembedded chunks; search is covered by the
integration tests.
---

### PO-02 — A tenant admin can open the AI config page but cannot save

**✅ Verified · Medium** · **Status: fixed (2026-09-29, `c8f4d52`)**

> **Product owner, 2026-09-29:** a tenant admin should not have access to the AI config
> page. Close the route to them; the API guard stays `app_admin` only.

The React route for `/ai-config` allows `APP_ADMIN` **and** `TENANT_ADMIN`. Every
`/config/task-defaults` endpoint behind that page is guarded by `_require_app_admin`.
So a tenant admin browses to the page, fills the form, presses save, and gets
`403 Only App Administrators can configure AI task defaults`.

- [`frontend/src/router/index.tsx:321`](../../../frontend/src/router/index.tsx:321) — the route gate
- [`config/router.py`](../../../backend/src/config/router.py) — `_require_app_admin`

**Fix:** pick one. Either drop `TENANT_ADMIN` from the route gate, or let a tenant
admin set defaults for their own company. Do not leave a page that only fails on save.

**Done (2026-09-29):** the first option. `TENANT_ADMIN` is dropped from all three places
that offered the page — the `/ai-config` route gate, its sidebar item, and the "AI Task
Defaults" card on the Integrations page, which linked to it. The API was already
`app_admin` only and is unchanged.

**Evidence:** live on a local SPA. As a `tenant_admin`: no sidebar item, no card on
`/integrations`, and navigating to `/ai-config` lands on `/dashboard`. As the `app_admin`:
all three present, and the page loads `GET /config/task-defaults` with 200. There is no
frontend test runner to hold a regression test ([FE-03](16-FRONTEND-DEFECTS.md#fe-03--there-is-no-test-runner)).

---

### PO-03 — Nothing pushes a new user into onboarding

**✅ Verified · Medium** · **Status: deferred (2026-09-29)**

> **Product owner, 2026-09-29:** new-user onboarding needs a fresh take on how it is
> designed and implemented. Deferred until then.

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

**✅ Verified · High** · **Status: fixed (2026-09-29, `682da36`)**

> **Product owner, 2026-09-29:** the cost report is for `app_admin` only.

`GET /reports/costing` depends on `get_current_user` and `get_db` and nothing else.
There is no `RoleChecker`. It scopes rows to `current_user.company_id`, so it is not
a cross-tenant leak, but every `tenant_user` can read their company's **raw internal
cost** — what the platform pays providers. Compare that with the billed amount on the
same screen and the markup is obvious.

The React route has no `allowedRoles` at all. The only thing hiding the page is that
the sidebar link is shown to `app_admin` only — anyone who types the URL gets in.

- [`billing/billing_router.py:148`](../../../backend/src/billing/billing_router.py:148) — `get_costing_report`
- [`frontend/src/router/index.tsx:443`](../../../frontend/src/router/index.tsx:443) — `<ProtectedRoute>` with no roles

**Fix:** gate the route to `app_admin`. See also **BC-20** in
[14 — Billing](14-BILLING-AND-CREDITS-DEFECTS.md#bc-20--two-open-endpoints-on-the-money-surface).

**Done (2026-09-29):**

- `GET /reports/costing` **and** `GET /reports/billing` depend on `RoleChecker(["app_admin"])`.
  The billing report returns the same rows, `base_cost` included, and no page uses it —
  gating only the costing route would have left the cost one URL away.
- Billing events are recorded under the company that ran the work, so an `app_admin` report
  scoped to the caller's own company would show no tenant costs. Both reports now span every
  company, take an optional `company_id` filter, and name each row's company
  (`company_name`, eager-loaded).
- The React route is `allowedRoles={[UserRole.APP_ADMIN]}`; the page shows a Company column
  and exports it in the CSV.

**Evidence:** `tests/unit/test_billing_report_access.py` — the five other roles get 403 on
both routes and the query never runs; `app_admin` gets every company by default and one
company with `company_id`. 14 cases, all failing on the old code. Live on a local API and
SPA: a `tenant_admin` receives 403 from the API and is redirected from the page to
`/dashboard`; the `app_admin` sees the report with its Company column.

Found while fixing: `GET /billing/config` returns the multiplier and base costs to any user
([BC-26](14-BILLING-AND-CREDITS-DEFECTS.md#bc-26--any-user-can-read-the-billing-multiplier-and-base-costs)),
and reloading any `/reports/*` page is proxied away from the SPA
([FE-24](16-FRONTEND-DEFECTS.md#fe-24--reloading-any-reports-page-proxies-the-browser-to-the-gateway)).

---

### PO-05 — A reviewer approves without seeing what they are approving

**✅ Verified · High** · **Status: fixed (2026-09-29, `ad74c46`)**

> **Product owner, 2026-09-29:** needs to be fixed.

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

**Done (2026-09-29).** Rendering the snapshot alone would not have been enough, for two
reasons found in the code:

- The snapshot held only `step_name` and a message — nothing about what the agent was
  doing. It is now built by `governance/hitl_snapshot.py`: the agent's name, the step's name,
  type, description and tool, its **resolved** prompt, the run's input, the run's cost so far,
  and for `AFTER_STEP` checkpoints the step's **output** (the step engine now passes the step
  result to the AFTER evaluation, which previously ran before the output was stored). Text
  fields are capped at 4000 characters; step ids stay out.
- `GET /ai/approvals/pending` built its rows by hand and left the snapshot out. It now returns
  `context_snapshot` and `timeout_ms`.

The panel shows the message, agent, step and tool on every card, links the run, and puts the
prompt, output, description, input and cost behind **Show what is being approved**
(collapsed by default).

**Evidence:** `tests/unit/test_hitl_context_snapshot.py` — BEFORE, AFTER and
`COST_THRESHOLD` snapshots, clipping, and the list endpoint; all five fail on the old code.
Live: a real `AFTER_STEP` checkpoint fired through `GovernanceService.evaluate_hitl` on the
local database appeared on the panel with the resolved prompt and the step's output.

**Found while fixing — the approval flow did not work end to end.** Recorded in
[15](15-GOVERNANCE-AND-HITL-DEFECTS.md) and fixed right after this, on 2026-09-29:
[GH-22](15-GOVERNANCE-AND-HITL-DEFECTS.md#gh-22--every-hitl-checkpoint-fails-to-subscribe-so-none-of-them-waits)
(no checkpoint ever waits — the subscribe call raises on every checkpoint and the step
proceeds),
[GH-23](15-GOVERNANCE-AND-HITL-DEFECTS.md#gh-23--authorize-and-block-cycle-always-fail-with-422)
(the panel's buttons always get 422) and
[GH-24](15-GOVERNANCE-AND-HITL-DEFECTS.md#gh-24--any-user-can-answer-any-companys-approval)
(the respond endpoint does not check the company).

---

## 3. T1 — Promises the product does not keep

### PO-06 — 64 of the 98 tools are unfinished integrations

**✅ Verified · High** · **Status: audit delivered (2026-09-29, `579c14f`)**

> **Product owner, 2026-09-29:** audit the entire tools stack and list what needs to be
> fixed. The deliverable is the audit, not a code change.

**Delivered:** [`PO-06-TOOL-STACK-AUDIT.md`](PO-06-TOOL-STACK-AUDIT.md) — re-verifies the
55 existing tool-layer entries against the current code, adds **18** new defects
(TL-50…TL-67), and ends with a prioritised fix list. Headline corrections to the numbers
below: after PO-17 there are **97** registered tools, not 98; by status **29 are
`ACTIVE`** and 68 `EXPERIMENTAL` (the 64 social + the 3 video tools + `tool_synthesis`).
The biggest new finding is that execution is **not** restricted to an entity's granted
tools (TL-50). No code was changed for PO-06; the fixes are scheduled through the tool-layer
register.

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

**✅ Verified · Medium** · **Status: open**

> **Product owner, 2026-09-29:** fix the social connection module properly.

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

**✅ Verified · Low** · **Status: deferred (2026-09-29)**

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

**✅ Verified · Medium** · **Status: fixed (2026-09-29, `3fadd76`)**

> **Product owner, 2026-09-29:** needs to be fixed.

Entity create is a closed Pydantic model. Unknown keys are dropped rather than
rejected. A seed author or an API user who writes `retry_policy` in the wrong JSON
column, or misspells a key, gets a `200 OK` and an entity that quietly ignores the
setting.

The seed authors hit this often enough to write it down as a known trap in
`SeedDocFactoryLite`.

- [`ai/schemas/`](../../../backend/src/ai/schemas/) — the entity create models

**Fix:** set the model to forbid extra fields and return a `422` naming the unknown
key. This is a small change with a large effect on how debuggable the builder is.

**Done (2026-09-29).** `extra="forbid"` on the models themselves would have been unsafe:
the nested models (`LogicGate`, `Planning`, …) also validate **stored** entities on every
read, and one stray key would have made the Entity Library a 500. Instead:

- `schemas/strict_keys.py` — `unknown_keys(model, payload)` walks a raw payload through
  nested models, lists and dicts of models, and returns the dotted path of every key the
  model would drop.
- `HierarchicalEntityCreateRequest` / `HierarchicalEntityUpdateRequest` run it before
  validation and raise a 422: *Unknown configuration key(s), which would be ignored:
  `logic_gate.retry_polcy`*. The entity and template create/update routes use them. The base
  models stay lenient for the internal callers that validate stored or generated JSON (the
  meta-agent tools, template cloning).
- **What the runtime reads is declared first**, so the 422 cannot block a real setting:
  `governance.critic_cost_share_pct` (0.20), `goal_validation_interval` (2),
  `meta_review_interval` (3), `max_concurrent_children` (unset) and
  `review_mechanism.critic_model_override` (unset). The defaults are the runtime's own
  fallbacks, so entities that do not set them behave as before. This closes EP-11 and PC-16.
- What the builder sends but nothing reads — `capabilities.tools[].usage`,
  `governance.checkpoint_every_n_steps` — and a plan step's legacy `reasoning_mode` are
  accepted by name (`extra_accepted_keys`), so the builder keeps working.
- The one undeclared key in any seed, `governance.meta_review_enabled` (deep-research v2
  director; nothing reads it), is removed from the seed. Its sibling `meta_review_interval`,
  which the kernel does read and which was being silently dropped, now reaches the entity.

**How the key list was found:** every seed payload (Autonomous BI, Document Factory via
`enrich_payload`, DocFactoryLite, deep-research v2), the test fixtures, and two real save
payloads captured from the running builder (intercepted in the browser, not sent) were
run through `unknown_keys`; the backend was grepped for every key it reads from
`governance` and `review_mechanism`.

**Evidence:** `tests/unit/test_entity_strict_keys.py` — 12 cases: the builder's payload is
accepted; six typos, nested down to `planning.static_plan.steps[1].target.tool`, are
rejected with their path; a typo inside a HITL checkpoint; the declared knobs survive
`model_dump`; their defaults equal the runtime fallbacks; a stored entity with a retired key
still reads back; and the routes return 422 naming the key while a valid payload reaches the
service. Live: an entity created and then edit-saved through the builder UI returned 200; a
`PUT` with `meta_review_intreval` returned 422 naming it; `meta_review_interval: 5` was
stored.

Found while verifying:
[FE-25](16-FRONTEND-DEFECTS.md#fe-25--saving-from-the-entity-builder-rewrites-config-it-does-not-show)
— saving from the builder rewrites config it does not show.

---

### PO-10 — A broken import turns a whole feature area into 404s

**✅ Verified · Medium** · **Status: fixed (2026-09-29, `0fd3b29`)** — also closes SA-I10,
PO-I9 and API-09

> **Product owner, 2026-09-29:** fix it.

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

**Done (2026-09-29).** The partial boot stays; the failure is now recorded and served.

- `src/common/router_mounts.py` — `mount_optional(app, module, prefix)` imports
  `module.router` and includes it. On an `ImportError` it logs at **error** level with the
  traceback, leaves the router out, and appends `{"router", "error"}` to
  `app.state.unmounted_routers`. The error text has the file path stripped, because the
  endpoint is public.
- `main.py` mounts the twelve optional routers through it, **one router per call**. The old
  blocks grouped two or three routers, so a failure in the second import left the first
  mounted and the third missing, and the warning named the whole group.
- **`GET /api/v1/health`** is new; the backend had no health route at all. It returns
  `{"status": "ok" | "degraded", "unmounted_routers": [...]}` with no auth. It is under
  `/api/v1` because the gateway answers `/health` itself and proxies only other paths to
  the backend. It is always a 200: every replica runs the same code, so a 503 would take
  them all out of rotation for one broken feature area.
- The core routers (auth, AI, config, CORTEX, artifacts, campaigns, mobile) are still
  imported unguarded, so a broken import there still stops the boot.

**Evidence:** `tests/unit/test_router_mounts.py` — 4 cases: a good router is mounted and
health is `ok`; a missing module is reported and the app still serves; a broken import
inside a module is reported without its file path; and the real `src.main` app reports
`ok` with nothing unmounted. The last one returns 404 on the old `main.py`, and it is also
a tripwire: any optional router that stops importing now fails the suite. Live: after a
restart, `GET :8010/api/v1/health` returned `ok` with an empty list. The real app booted
with `src.ai.social_router` made unimportable returned `degraded` naming that router,
`/api/social-connections` answered 404, and the email router stayed mounted.

---

### PO-11 — Templates sit outside tenant scoping by design

**✅ Verified · Medium** · **Status: won't fix (2026-09-29)**

> **Product owner, 2026-09-29:** no fix needed — templates are global by design.

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

> **Product owner, 2026-09-29:** remove all the dead code and dead surfaces.

| ID | Delete | Why | Status |
|---|---|---|---|
| **PO-12** | `voice/phone_pool_router.py` | 701 lines, not mounted anywhere. The only surviving reference is a sentence in the replacement's docstring. Also recorded as D-22 in the platform register | ✅ fixed (2026-09-29, `964c9ab`) — deleted; the replacement's docstring no longer mentions it |
| **PO-13** | `frontend/src/pages/assets/AssetLibrary.tsx` | 314 lines, not routed, imported by nothing but its own CSS. Replaced by `Artifacts.tsx` | ✅ fixed (2026-09-29, `9719f1b`) — deleted with its CSS and `services/asset.service.ts`, which only it used |
| **PO-14** | `send_whatsapp_message()` in `voice/whatsapp_handler.py` | Body is a `[MOCK]` log line with the real SDK call commented out. Nothing imports it, but it is easy to grab by mistake | ✅ fixed (2026-09-29, `2e8410b`) — confirmed unimported, deleted |
| **PO-15** | The `approval:{id}` Redis publish in `AIService.respond_to_approval` | Nothing subscribes to it. The live channel is `hitl:{id}`, published by the router at [`ai/router.py:456`](../../../backend/src/ai/router.py:456) and consumed at [`governance_service.py:345`](../../../backend/src/ai/governance/governance_service.py:345) | ✅ fixed (2026-09-29, `ba5e6ec`) — the publish and its misleading comment are gone; this also removes one of SA-04's five `RedisSettings()` call sites |
| **PO-16** | The `/api/v1/ai/phase11/*` and `/admin/phase11/*` redirect shims | Both carry an explicit *"Remove after 2026-09-01"* comment. That date is today | ✅ fixed (2026-09-29, `6d90428`) — the backend 307 shim and the five SPA redirects are deleted; no frontend code called the old paths |
| **PO-17** | The `video_generation` deprecated tool | `ToolStatus.DEPRECATED`, still registered, still selectable because the visibility gate is unwired. Superseded by `video_generate` + `video_edit` | ✅ fixed (2026-09-29, `a8fb38e`) — no entity referenced it; unregistered and deleted, with its entries in the three cost tables and the category map. 97 tools are now registered |

> Before deleting, confirm nothing still imports it:
> `grep -rn "<module_name>" backend/src frontend/src --include=*.py --include=*.ts --include=*.tsx`

---

## 5. T3 — Rough edges

> **Product owner, 2026-09-29:** PO-18 to PO-22 are deferred.

### PO-18 — Two Redis channels look like the HITL channel

**✅ Verified · Low** · **Status: fixed (2026-09-29, `ba5e6ec`)** — closed by the PO-15
deletion, which removed both the dead publish and its misleading comment. Only `hitl:{id}`
remains.

`hitl:{id}` is the real one. `approval:{id}` is published and never consumed. A
developer debugging a stuck approval will find the wrong channel first, because the
comment above the dead publish says *"The execution engine subscribes to
`approval:{approval_id}` before gating"* — which is not true.

Covered by the deletion in [PO-15](#4-t2--dead-code-and-dead-surfaces); listed here
because the misleading comment is the actual cost.

---

### PO-19 — The SSE stream closes on a substring match

**📄 Doc-reported · Low** · **Status: deferred (2026-09-29)**

The browser stops listening when it sees `COMPLETED`, `FAILED` or `CANCELLED` in the
raw JSON payload — a substring match, not a field read. Any event that happens to
carry one of those words inside a message, a tool result or a critic note will close
the stream early and the user will think the run stopped.

- [`frontend/src/hooks/useExecutionEvents.ts`](../../../frontend/src/hooks/useExecutionEvents.ts)

**Fix:** match on the parsed `status` field.

---

### PO-20 — A long HITL timeout ties up a worker

**✅ Verified · Medium** · **Status: deferred (2026-09-29)**

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

**📄 Doc-reported · Low** · **Status: deferred (2026-09-29)**

`AGENT` is one of four entity types, but the UI, the docs and the sidebar all use
"agent" loosely for any entity. New developers and new customers both misread
capacity limits and pricing because of it.

**Fix:** in user-facing copy, say "agent" only for the type. Everywhere else say
"entity" or the specific type.

---

### PO-22 — Costing and billing reports are the same query

**✅ Verified · Low** · **Status: deferred (2026-09-29)**

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

> **Product owner, 2026-09-29:** PO-I1 to PO-I12 are all deferred for now.

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

**Status: done (2026-09-30)** — with [AU-20](04-AUTH-RBAC-TENANCY-DEFECTS.md#au-20--five-independent-copies-of-own-company-plus-children):
the partner entity list is one `company_id IN (...)` query.

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

**Status: done (2026-09-29, `0fd3b29`)** — by PO-10; the endpoint is `GET /api/v1/health`.

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

## 7. Order of work

Agreed at the 2026-09-29 review. Each item is committed on its own.

| Step | Work | Why here |
|---|---|---|
| **1** | T2 deletions — PO-12 to PO-17 | Free. The phase11 shims are already past their own removal date |
| **2** | PO-04, PO-02, PO-05 | Small, self-contained, directly visible |
| **3** | PO-01 | Knowledge-base CRUD on CORTEX Knowledge Trees |
| **4** | PO-09, PO-10 | Make builder typos and broken router imports loud |
| **5** | ~~PO-06 audit~~ (delivered), then PO-07 | The audit decides which platforms the connection module must support — see its Tier 3 |

Deferred: PO-03, PO-08, PO-18 to PO-22, and every improvement. Won't fix: PO-11.
Open: PO-07 (the last defect in this register), informed by the PO-06 audit's Tier 3.

---

## Where to go next

- [01 — Product & functional overview](../01-product-overview.md) — the document these
  defects were found against.
- [`DEFECT-REGISTER.md`](../DEFECT-REGISTER.md) — the platform-wide list. PO-12,
  PO-16 and PO-17 also appear there as D-22, D-24 and D-25.
- [04 — Auth, RBAC & tenancy](04-AUTH-RBAC-TENANCY-DEFECTS.md) — for PO-04 and PO-11.
- [`TOOL-LAYER-DEFECTS.md`](TOOL-LAYER-DEFECTS.md) — for PO-06 and PO-07 in depth.
- [15 — Governance & HITL](15-GOVERNANCE-AND-HITL-DEFECTS.md) — for PO-05 and PO-20.
