# Can HireBuddha build the GTM automation with no code change?

> **Question asked:** does the platform as it stands on `fresh-main` support building
> the end-to-end marketing & sales automation described in
> [marketing-sales-automation.md](marketing-sales-automation.md) **without any code
> change** — i.e. purely by authoring entities, connecting integrations, flipping
> feature flags and uploading content?
> **Method:** every claim below was checked against the code in this repository, not
> against the roadmap or the numbered docs. Where a numbered doc or the brainstorm
> disagrees with the code, the code wins.
> **Written:** 2026-09-09, against branch `fresh-main`.

---

## 1. Answer

**No.** About **15–20% of the described department** can be built with zero code —
and it is exactly the read-only, human-triggered, inside-the-walls slice.
Everything that makes it a *department* rather than a set of research assistants
requires code.

The brainstorm's own verdict — *"capable enough to build the agents, not capable
enough to run the department"* — is right in shape but slightly optimistic in
degree. Three things it does not account for tighten the answer:

1. **Agents cannot read the knowledge you give them.** Uploaded documents are
   chunked and embedded, but no tool and no context path exposes them to a run.
   There is no brand brain, no ICP grounding, no RFP retrieval — not because the
   objects are missing, but because *retrieval is unwired*.
2. **Learned memory never reaches a prompt.** `AgentLoop` constructs its
   `Perceiver` with `memory_assembler=None`, so intelligence rules and episodic
   recall are always empty. The Dreaming → rules → behaviour loop is open at
   runtime.
3. **The approval gate has a 5-minute default and fails open.** The A1
   "draft → human approves → publish" discipline that the entire GTM plan rests
   on cannot survive a human who is at lunch, and silently publishes if Redis
   hiccups.

So the honest framing is not "the agents work, the plumbing is missing". It is
**"the execution loop works; the agents cannot be grounded, cannot be scheduled,
cannot remember, and cannot be safely gated."**

### Readiness, re-scored against code

| Layer | Brainstorm's score | Verified | Why the difference |
|---|---|---|---|
| Execution kernel | ~85% | **~85%** | Confirmed. 9 phases, 4 critic gates, budget-aware, suspend/resume real |
| Composition model | ~85% | **~80%** | Works, but the create API is a closed schema that silently drops kernel-read fields ([N-8](#n-8)) |
| Memory & retrieval | ~75% | **~30%** | CORTEX viewport is wired; the 4-domain assembler and pgvector RAG are not ([N-1](#n-1), [N-2](#n-2)) |
| Tool breadth | ~50% | **~50%** | Confirmed — and no durable way to add one ([N-6](#n-6), D-20) |
| Human-in-the-loop | ~50% | **~25%** | Configurable triggers, but a blocking 5-min wait that fails open ([N-3](#n-3)) |
| Multi-tenancy / billing / RBAC | ~70% | ~70% | Confirmed; T0 defects stand |
| Business object model | ~0% | **0%** | Confirmed — no `accounts`/`contacts`/`opportunities`/`activities`, no `tenant_records` |
| Triggers & scheduling | ~15% | **~10%** | Every arq cron is platform maintenance; webhook fallback picks a random entity ([N-5](#n-5)); `campaigns.scheduled_start` is inert ([N-4](#n-4)) |
| Consent / suppression / deliverability | ~0% | **0%** | Confirmed — `grep` for `consent|suppression|unsubscribe|bounce|dnc|opt_out` over `backend/src/` returns **nothing** |
| GTM reporting & attribution | ~5% | ~5% | Confirmed |
| **Ad-spend governance** | not scored | **0%** | New: budget is a free tool parameter, uncapped and unmetered ([N-9](#n-9)) |

---

## 2. What genuinely works with zero code

This part is real and should not be undersold.

**Entity authoring is fully data-driven.** `hierarchical_entities` stores
`identity` / `logic_gate` / `planning` / `capabilities` / `governance` /
`io_contract` as JSON ([orm/entity.py:41-50](../../backend/src/ai/orm/entity.py:41)).
The EntityBuilder UI exposes static plans, dynamic planning, best-of-N,
tool binding, retry policy, cost caps and HITL checkpoints. Composing
ACTION → SKILL → AGENT → PROCESS needs no deployment.

**HITL checkpoints are configurable per entity**, on five triggers —
`BEFORE_STEP`, `AFTER_STEP`, `COST_THRESHOLD`, `TOOL_CALL`, and a `CUSTOM`
expression evaluated by a hand-written safe parser (no `eval`)
([governance_service.py:246-312](../../backend/src/ai/governance/governance_service.py:246)).
The *triggering* is genuinely good. The *waiting* is not — see [N-3](#n-3).

**Research tooling is the platform's strongest GTM surface.** `web_search`,
`batch_web_search` (25 queries in one call), Firecrawl `scraper_tool`,
`headless_browser`, `sandbox_code`, `terminal`. Competitive teardowns, ICP
research, account briefs and market monitoring are all buildable today.

**Document generation is production-shaped.** `pdf_generator`, `docx_tool`,
`pptx_tool`, `excel`, `document_save` — proposals, one-pagers, decks and reports
land as registered artifacts.

**Social publishing is real code against real APIs**, not stubs
([social/base.py](../../backend/src/ai/tools/social/base.py) resolves credentials
from `social_connections` and makes live HTTP calls).

⚠️ **Correction (2026-09-12).** An earlier draft of this document said the 64
`EXPERIMENTAL` social tools sit behind a per-company
`tools.experimental.{tool_id}` opt-in. **They do not.** The status gate
`ToolRegistry.get_visible_tools_for_company` has no production caller; the live
path builds schemas from `ToolExecutor.get_tool_schemas` →
`ToolRegistry.get_all_schemas()` with no `company_id` and no status filter
([tool_executor.py:287](../../backend/src/ai/tool_executor.py:287),
[step_executor.py:755](../../backend/src/ai/step_executor.py:755)). Any tool an
entity names executes, whatever its status. The admin flag endpoint writes rows
nothing reads. Recorded as
[TL-13](../current/defect-register/TOOL-LAYER-DEFECTS.md#tl-13--the-tool-status-gate-is-not-wired-into-execution)
and [PO-06](../current/defect-register/01-PRODUCT-OVERVIEW-DEFECTS.md#po-06--64-of-the-98-tools-are-unfinished-integrations).
This makes [N-9](#n-9) worse, not better: the ad tools are reachable by default.

A second constraint the earlier draft missed: `VALID_PLATFORMS` in the social
connection API accepts **nine** platforms while sixteen have tools, so
`pinterest_*`, `meta_ads_*`, `linkedin_ads_*`, `x_ads_*`, `snapchat_ads_*`,
`youtube_ads_*` and `linkedin_sales_nav_*` can never find a stored connection —
they fail at runtime with a credential error rather than at build time
([PO-07](../current/defect-register/01-PRODUCT-OVERVIEW-DEFECTS.md#po-07--you-can-connect-9-social-platforms-but-16-have-tools)).
Of the ad platforms, only Google Ads is actually connectable today.

**Outbound voice campaigns actually run.** `execute_campaign_task`,
`pause_campaign_task` and `stop_campaign_task` are registered in
[`WorkerSettings.functions`](../../backend/src/ai/worker.py:72), so campaign
creation → dial → LLM conversation → disposition classification works end to end
via the UI. This remains the most production-shaped path on the platform.

**Email is usable for a rep's inbox**: IMAP ingest, classify, draft, and a single
SMTP send with artifact attachment.

### Therefore, buildable this week with no code at all

| Buildable | Caveat |
|---|---|
| **GTM-P1 Demand Sensing** — competitive teardowns, funding/hiring signals, news & review monitoring | Someone must press Execute; findings land as artifacts, not as queryable records, so run *N+1* cannot diff against run *N* |
| Pre-call research briefs | Output is a document, not a CRM note |
| Content drafting — blogs, posts, ad copy, one-pagers, decks | Grounded only in the prompt, not in a brand brain ([N-2](#n-2)) |
| Ad creative and video assets | — |
| Proposal drafting | Not RFP *answering* — that needs retrieval ([N-2](#n-2)) |
| Social publishing | Nine platforms are connectable; the other seven have tools that can never resolve a credential. Unvalidated, ungated, and with no approval gate you can trust ([N-3](#n-3)) |
| Outbound voice campaigns | No consent/DNC layer of any kind ([§3, Layer 4](#layer-4--compliance-0)) |
| Inbound voice response | Only from the platform's own telephony, not from a form |

**GTM-P2 Revenue Reporting is *not* on this list.** Funnel, pipeline and
attribution reporting requires revenue data the platform does not store. The
existing reports are execution-health and cost-shaped.

---

## 3. What is hard-blocked, and by what

The brainstorm's four missing layers are all confirmed. Summarised, with the
verification:

### Layer 1 — Business object store: **absent**
Every `__tablename__` in `backend/src/` was enumerated. There is no `accounts`,
`contacts`, `leads`, `opportunities` or `activities` table, and no
`tenant_entity_defs` / `tenant_records` / `tenant_record_links`. `lead_queue` is
a dialer queue; `campaigns` is the voice dialer; `crm_update_lead` POSTs to a
tenant-hosted endpoint and stores nothing locally.

Consequence, unchanged from the brainstorm: an agent cannot answer *"have we
touched this person before?"*.

### Layer 2 — Triggers & scheduling: **absent for tenants**
All seven arq crons are platform maintenance
([worker.py:104-118](../../backend/src/ai/worker.py:104)). No
`entity_schedules` table, no `cron_expression`, no `next_run_at` anywhere in
`backend/src/`. The only ways to start work are: a human pressing Execute, an
inbound call, or a raw webhook — and see [N-4](#n-4) and [N-5](#n-5) for how weak
the last two are.

### Layer 3 — Outbound: **one-shot SMTP only**
`email_send` takes one recipient, one subject, one body
([email_tool.py:477](../../backend/src/ai/tools/email/email_tool.py:477)). No
enrollment state, no send windows, no throttling, no reply detection, no
tracking, no List-Unsubscribe header, no sender rotation. The `idempotency_key`
columns exist on both log tables
([orm/execution.py:59](../../backend/src/ai/orm/execution.py:59), `:115`) and
**nothing anywhere reads or writes them** — verified by grep. The kernel retries
steps by design, so a retried `email_send` sends twice.

### Layer 4 — Compliance: **0%**
`grep -rniE "unsubscribe|suppression|bounce|consent|dnc|opt_out" backend/src/`
returns **zero matches**. Not three unrelated hits as the brainstorm reports —
zero. The voice campaign path ships today with no consent store, no DNC list, no
AI disclosure and no consent-to-record.

---

## 4. New findings — not in the brainstorm

These are the ones that change the answer, in rough order of impact.

<a id="n-1"></a>
### N-1 — Learned memory never reaches a prompt · **Critical**

`AgentLoop._setup_components` constructs the perceiver as
`Perceiver(db=..., cortex=self.cortex, memory_assembler=None)`
([agent_loop.py:766](../../backend/src/ai/core/agent_loop.py:766)). `Perceiver`
returns `[]` from both `_gather_intelligence_rules` and `_gather_similar_runs`
whenever `self.memory is None`
([perceiver.py:133](../../backend/src/ai/core/perceiver.py:133),
[:169](../../backend/src/ai/core/perceiver.py:169)).

`assemble_memory()` — which
[`memory/README.md:36`](../../backend/src/ai/memory/README.md:36) calls *"the
single entry point from worker / loop"* — has **zero production callers**. Its
only importers are two unit tests.

**Consequence:** intelligence rules distilled by Dreaming, and episodic recall of
similar past runs, are always empty in perception. The self-improvement loop is
open at runtime. CORTEX's viewport *is* wired, so the platform is not amnesiac
within a run — it is amnesiac *across* runs in the way that matters for a GTM
agent ("what did I learn about this segment last month?").

<a id="n-2"></a>
### N-2 — Agents cannot read the tenant's knowledge base · **Critical**

There is no retrieval tool in the registry. All ~98 registered tool names were
enumerated: no `rag_search`, no `document_query`, no `knowledge_search`, no
`memory_search`, no `cortex_query`.

Vector search over `document_chunks` exists **only as a human REST endpoint**
([service.py:938 `search_documents`](../../backend/src/ai/service.py:938), exposed
at [router.py:668](../../backend/src/ai/router.py:668)).

Meanwhile the EntityBuilder UI offers `semantic_search_enabled`,
`semantic_top_k`, `inject_semantic_context` and `inject_episodic_memory`
toggles. Those fields are declared in
[`schemas/capabilities.py:73-98`](../../backend/src/ai/schemas/capabilities.py:73)
and **read by no backend code** — grep returns the schema definitions and nothing
else.

**Consequence:** the brainstorm's Increment 2 ("brand brain + brand critic") and
its highest-value sales use case ("security questionnaires & RFP responses ←
perfectly RAG-shaped") both have no delivery mechanism today. You can upload the
messaging library; no agent can read it. Everything an agent knows must be pasted
into its prompt, which caps the brand brain at whatever fits in a system prompt
and makes it uneditable by non-engineers.

<a id="n-3"></a>
### N-3 — The approval gate is a 5-minute blocking wait that fails open · **Critical**

Three properties of
[`evaluate_hitl`](../../backend/src/ai/governance/governance_service.py:246):

- **Default timeout is 5 minutes.** `HITLCheckpoint.timeout_ms: int = 300000`
  ([schemas/governance.py:29](../../backend/src/ai/schemas/governance.py:29)).
  On expiry the run either raises (fails) or auto-approves, depending on
  `auto_approve_on_timeout`.
- **The wait is a busy-loop inside the arq job**, polling Redis pub/sub every
  0.5s until the deadline
  ([governance_service.py:353-375](../../backend/src/ai/governance/governance_service.py:353)).
  Each pending approval pins a worker slot for the whole window; the job's
  absolute ceiling is `job_timeout = 7200`.
- **Any pub/sub error is swallowed and execution continues.** The `except`
  re-raises only when the message contains `"Execution blocked"` or
  `"timed out"`; everything else logs a warning and falls through
  ([:392-396](../../backend/src/ai/governance/governance_service.py:395)).

**Consequence:** "draft → marketer approves → publish" is not achievable with the
current mechanism at any realistic human latency, and a Redis blip publishes
unreviewed content to a customer's LinkedIn. This is the load-bearing control for
the brainstorm's entire A1-before-A2 autonomy discipline.

**The good news:** the kernel already has the right mechanism for this. Child
entity invocation snapshots the parent and releases the worker
([`resume_parent_run`](../../backend/src/ai/core/arq_jobs.py) is registered in
`WorkerSettings.functions`). HITL should suspend the same way. The fix is
smaller than the brainstorm's "Content review queue — size M" implies, because
the suspend/resume machinery exists and is proven.

<a id="n-4"></a>
### N-4 — `campaigns.scheduled_start` is stored and never read · **High**

The column exists
([campaign_models.py:72](../../backend/src/ai/campaign_models.py:72)), is accepted
by the create API
([campaign_router.py:114](../../backend/src/ai/campaign_router.py:114)), is
returned in campaign responses (`:483`) — and **no code reads it**. There is no
sweeper cron for due campaigns. The `status` enum includes `scheduled`, a state
the system cannot act on.

**Consequence:** a user schedules a campaign for Monday 9am, the UI shows it
scheduled, and nothing dials. Every voice campaign must be started by hand.

<a id="n-5"></a>
### N-5 — The webhook→entity fallback can hand a lead to an ACTION · **High**

Both the arq path
([arq_jobs.py `process_gateway_event`](../../backend/src/ai/core/arq_jobs.py:163))
and the in-process fallback
([dispatcher.py:234](../../backend/src/gateway/dispatcher.py:234)) resolve the
target with:

```sql
SELECT ... FROM hierarchical_entities
WHERE company_id = :cid AND status != 'ARCHIVED'
LIMIT 1
```

No `ORDER BY` (this is D-36) and — additionally, not recorded anywhere — **no
filter on `type`**. Any inbound webhook without an explicit `entity_id` in its
payload is routed to an arbitrary entity of the tenant, which may be an ACTION or
a SKILL rather than a PROCESS or AGENT.

Combined with **D-05** (no inbound signature is ever validated — the handler logs
a warning and processes anyway,
[webhook_inbound.py:549](../../backend/src/gateway/webhook_inbound.py:549)) and
**D-31** (no webhook idempotency), the inbound path is not usable for GTM-P4
speed-to-lead without work.

And **D-21**: `lead_queue_worker.py` has zero importers. Rows land in
`lead_queue` and nothing ever drains them — so even the one purpose-built lead
path is dead.

<a id="n-6"></a>
### N-6 — There is no durable way to add a tool without deploying code · **High**

Three independent paths all dead-end:

1. **Custom tools via the API** — D-20: no loader behind `tool_registry_entries`.
   The row is created, `is_enabled` toggles, nothing executes.
2. **Tool synthesis** — the runtime wrapper is real
   ([`SandboxedSynthesizedTool`](../../backend/src/ai/tools/sandbox/synthesized_tool.py))
   and registration works
   ([tool_synthesis_pipeline.py:95](../../backend/src/ai/meta/tool_synthesis_pipeline.py:95))
   — but it registers into `ToolRegistry._tenant_tools`, a **class-level Python
   dict** ([base.py:159](../../backend/src/ai/tools/base.py:159)) with **no
   rehydration at startup** anywhere in the codebase. A synthesized tool exists
   only inside the process that created it and vanishes on restart. The API
   process cannot see what the worker synthesized.
3. **MCP** — confirmed as the brainstorm describes: `MCPClient` is a bare
   `Protocol` with no stdio/HTTP/SSE implementation
   ([mcp/client.py](../../backend/src/ai/tools/mcp/client.py)), and
   `bind_mcp_server` has no callers outside its own package. Note that even once
   a transport is written, `bind_mcp_server` registers into the same
   process-local dict — **MCP needs the durable registration path too**, which
   the brainstorm's "one concrete client + a config table + a bind call" sizing
   does not include.

**Consequence:** the GTM plan's Tier-A tools (`gtm_record_query`,
`consent_check`, ESP send, calendar availability) cannot be added by any
no-code route. This is the single most decisive fact for the question asked.

<a id="n-7"></a>
### N-7 — The sandbox is too small to be the workaround · **Medium**

The obvious "no code change" hack for the missing object store is: have an agent
keep SQLite in the sandbox. It does not work well enough to build on.

- `SANDBOX_CONTAINER_RUNTIME_ENABLED` defaults to `False`
  ([config.py:15](../../backend/src/common/config.py:15)) and `backend/.env` does
  not override it, so the **subprocess tier** runs — on the host, as the backend
  user, with the workspace at `/tmp/sandbox/{company_id}`.
- **Stdout is truncated at 4096 characters**
  ([sandbox_executor.py:47](../../backend/src/ai/tools/sandbox/sandbox_executor.py:47)).
  A query returning more than a page of rows is silently cut.
- Default timeout is 30 seconds.
- `/tmp` is not durable storage, and `SANDBOX_REAP_SECONDS` (86400) reaps
  workspaces.
- Nothing in the UI, reports or billing can see inside it.

It is a fine scratchpad for one run's computation. It is not a business record.

<a id="n-8"></a>
### N-8 — The no-code builder has a silent ceiling · **Medium**

The team's own seed script documents this
([SeedDocFactoryLite/create_lite.py:22-35](../../backend/scripts/seeds/default_entities/SeedDocFactoryLite/create_lite.py:22)):

> *"entity create is a **closed** Pydantic model — unknown keys are silently
> dropped"* … *"`review_mechanism.critic_model_override` is read by the kernel but
> is NOT a declared schema field, so it cannot be set from a seed payload"* …
> *"critic cadence … Governance is a closed schema without those fields, so we
> rely on the favourable defaults"*.

**Consequence:** some kernel behaviour is configurable only by deploying code,
and attempts to configure it through the API fail **silently** — the entity saves,
the field is gone. For a GTM build where a brand critic's model choice and critic
cadence matter, this is a real ceiling and a bad failure mode.

<a id="n-9"></a>
### N-9 — Ad spend is uncapped and unmetered · **Medium, but expensive**

`google_ads_create_campaign` takes `budget_amount_micros` as a required free
parameter ([google_ads.py:47](../../backend/src/ai/tools/social/google_ads.py:47))
and passes it straight through (`:111`). `governance.max_cost_usd`
([schemas/governance.py:36](../../backend/src/ai/schemas/governance.py:36)) caps
*platform* cost — tokens, minutes, tool calls — and knows nothing about money
committed on a third-party ad account.

There is also **no SKU for any of the 64 social/ads tools** in the rate catalogue
([billing_rates_by_primitive.md §11-14](../current/billing_rates_by_primitive.md)),
so they fall to the `$0.01` unknown-tool fallback.

**Consequence:** an agent that mis-parses a budget and sets `10000000000` micros
is caught by nothing. The brainstorm flags this under Tier C; it deserves to be
higher — it is the only failure mode in the whole plan that can spend a
customer's money without any ceiling.

<a id="n-10"></a>
### N-10 — No machine authentication · **Medium**

`POST /api/v1/ai/execute` is guarded by `Depends(get_current_user)`
([router.py:164](../../backend/src/ai/router.py:164)) — JWT only. There are no
API keys, service accounts, or signed tokens for tenant automation anywhere in
the codebase.

**Consequence:** the natural workaround for the missing scheduler — "put a cron
on the host that curls the execute endpoint" — requires parking a human user's
refresh token in a script. Workable for tenant zero; not something to hand a
customer.

---

## 5. Corrections to the brainstorm

The document is accurate on the large majority of what it asserts. Five
refinements:

| § | It says | Correction |
|---|---|---|
| §1 table | Memory & retrieval ~75% | ~30% at runtime. The stores exist; retrieval is unwired in both directions ([N-1](#n-1), [N-2](#n-2)) |
| §1 table | Human-in-the-loop ~50% | Closer to 25%. Trigger configuration is good; the wait mechanism is unusable and fails open ([N-3](#n-3)) |
| §2.2 / §7.3 | 64 social tools are `EXPERIMENTAL` and `$0` SKU | Correct on status, but the gate is a per-company feature flag flipped from the admin API — **configuration, not code**. The `$0` claim is closer to "no SKU at all, falls back to $0.01/call" |
| §3 Layer 4 | grep returns "three unrelated hits" | It returns **zero**. Nothing named `consent`, `suppression`, `unsubscribe`, `bounce`, `dnc` or `opt_out` exists in `backend/src/` |
| §7.4 / §8 #6 | MCP = "one client + a config table + a bind call"; review queue sized M | Both under-size. MCP also needs durable tenant-tool registration ([N-6](#n-6)); the review queue needs the HITL wait replaced with suspend/resume — though that machinery already exists and is proven, so it is cheaper than a from-scratch M ([N-3](#n-3)) |

Everything else checked — the kernel description, the tool inventory, the four
missing layers, the `campaigns` name collision, the LinkedIn ToS warning, the
27→14 object reduction, the "no `Lead` object" call, and the deliberate
`Signal`/`Activity` split — held up against the code.

---

## 6. The shortest path to a real answer of "yes"

Ordered by unblocked-value per unit of work, not by the brainstorm's increment
numbering. The first three are small and change what is buildable *this quarter*;
the fourth is the large one the brainstorm already identifies.

| # | Change | Size | Unblocks |
|---|---|---|---|
| 1 | **Wire `assemble_memory` into `AgentLoop`, and add a `knowledge_search` tool** over the existing `document_chunks` pgvector index | **XS–S** | Brand brain, ICP grounding, RFP/security-questionnaire answering, cross-run learning. Both stores already exist; this is connection work, not construction |
| 2 | **`entity_schedules` table + an arq sweeper**, and make `campaigns.scheduled_start` actually fire | **S** | Every recurring Process. Turns GTM-P1/P2 from "someone presses Execute" into a standing function |
| 3 | **HITL suspend/resume instead of blocking wait**, plus fail-closed on pub/sub error | **S–M** | The A1 draft→approve→publish discipline the whole plan depends on. Reuses the proven child-entity suspend path |
| 4 | **Record service + `gtm_*` object store + `gtm_record_*` tools** | **L** | Everything else. The brainstorm's §5 design is sound; the typed-spine + validated-flex-bag shape is the right call |
| 5 | **Durable tenant-tool registration** (a loader for `tool_registry_entries` + rehydration at worker startup) | **S–M** | Fixes D-20, makes tool synthesis survive a restart, and is a prerequisite for MCP being worth finishing ([N-6](#n-6)) |
| 6 | **Consent/suppression service + ESP + outbound idempotency + ad-spend cap** | **M** | Any outbound at all, and the only guard against uncapped ad spend ([N-9](#n-9)) |

Items 1–3 together are plausibly a couple of weeks and would move the honest
answer from *"research assistants you trigger by hand"* to *"a scheduled,
grounded, safely-gated content and intelligence function"* — which is Increments
1 and 2 of the brainstorm, delivered without touching the object store.

Item 4 remains the gate on everything that deserves the word *sales*.

---

## 7. One thing worth deciding early

The brainstorm's §4.2 decision — a `hb-tenant-db-{company_id}` container per
tenant — is well argued at n=1, and its honesty about *not* reusing the shipped
sandbox is the right instinct ([N-7](#n-7) independently confirms the sandbox is
unsuitable).

But note the interaction with [N-6](#n-6): a per-tenant database the control
plane must reach, combined with a tool registry that is a process-local Python
dict, means **two separate durability problems** land at the same time. If item 5
above is done first, item 4 gets simpler — the record tools become ordinary
registered tools with a real lifecycle rather than a special case.

Worth sequencing 5 before 4 even though 5 looks like unrelated cleanup.

---

## 8. Coverage against the defect register

> Added 2026-09-12, after cross-checking every item above against
> [`docs/current/defect-register/`](../current/defect-register/) (459 defects,
> 202 improvements, compiled 2026-09-01) and the earlier platform-wide
> [`DEFECT-REGISTER.md`](../current/DEFECT-REGISTER.md) (45 `D-nn` items).

**Headline: seven of the ten new findings were already recorded** — several in
more depth than this document had them. Three are genuinely absent. Separately,
none of the four missing GTM layers are in the register, and that is correct:
the register records *things that exist and are broken*, not capabilities that
were never built.

### 8.1 Findings already covered

| # | Register coverage | Notes |
|---|---|---|
| **N-1** Memory never reaches a prompt | [MC-01](../current/defect-register/08-MEMORY-AND-CORTEX-DEFECTS.md#mc-01--cortex-is-write-only-on-the-live-path), [MC-03](../current/defect-register/08-MEMORY-AND-CORTEX-DEFECTS.md), [MC-04](../current/defect-register/08-MEMORY-AND-CORTEX-DEFECTS.md), [AK-05, AK-06](../current/defect-register/05-AGENT-KERNEL-DEFECTS.md), [OG entry](../current/defect-register/20-ONBOARDING-AND-GLOSSARY-DEFECTS.md), + README top-ten #4 | **Covered more deeply than here.** MC-01 adds that `step_executor` *actively strips* `__memory__`, `__episodic_memory__`, `__semantic_context__` from a child's context — an extra deletion this document missed |
| **N-2** Agents cannot read the knowledge base | **Partial.** [MC-04](../current/defect-register/08-MEMORY-AND-CORTEX-DEFECTS.md#mc-04--embeddings-are-paid-for-and-rarely-searched) + [MC-01](../current/defect-register/08-MEMORY-AND-CORTEX-DEFECTS.md#mc-01--cortex-is-write-only-on-the-live-path) | The register frames it as *wasted embedding spend* — “the agent-facing retrieval that justifies embedding every node does not happen”. It does not record the two consequences that matter here: there is **no agent-callable retrieval tool** in the registry at all (vector search exists only as the human `/documents/search` endpoint), and the builder's memory toggles that imply otherwise are inert — see §8.2 |
| **N-3** HITL blocking wait, fails open | [GH-01](../current/defect-register/15-GOVERNANCE-AND-HITL-DEFECTS.md#gh-01--if-redis-is-down-every-hitl-checkpoint-is-skipped) (fail-open), [GH-07](../current/defect-register/15-GOVERNANCE-AND-HITL-DEFECTS.md#gh-07--a-hitl-wait-blocks-a-worker-slot) (worker slot, 5-min default), [PO-20](../current/defect-register/01-PRODUCT-OVERVIEW-DEFECTS.md#po-20--a-long-hitl-timeout-ties-up-a-worker), [GH-I3](../current/defect-register/15-GOVERNANCE-AND-HITL-DEFECTS.md#gh-i3--pause-instead-of-blocking-on-hitl), [PO-I1](../current/defect-register/01-PRODUCT-OVERVIEW-DEFECTS.md#po-i1--stop-blocking-a-worker-on-human-approval) | **Fully covered, plus three more.** [GH-06](../current/defect-register/15-GOVERNANCE-AND-HITL-DEFECTS.md) reject/timeout detected by *matching exception text*; [GH-08](../current/defect-register/15-GOVERNANCE-AND-HITL-DEFECTS.md) `COST_THRESHOLD` fires after the money is spent; [GH-09](../current/defect-register/15-GOVERNANCE-AND-HITL-DEFECTS.md) malformed checkpoints skipped silently; [PO-05 / GH-11](../current/defect-register/01-PRODUCT-OVERVIEW-DEFECTS.md#po-05--a-reviewer-approves-without-seeing-what-they-are-approving) the reviewer is shown nothing |
| **N-5** Webhook routing | [GW-17](../current/defect-register/13-GATEWAY-AND-REALTIME-DEFECTS.md#gw-17--agent-selection-is-limit-1-with-no-order-by-in-three-places) (= D-36), [GW-01](../current/defect-register/13-GATEWAY-AND-REALTIME-DEFECTS.md) (= D-05), [GW-03](../current/defect-register/13-GATEWAY-AND-REALTIME-DEFECTS.md#gw-03--no-webhook-idempotency) (= D-31), [VT-14](../current/defect-register/12-VOICE-AND-TELEPHONY-DEFECTS.md#vt-14--the-lead-queue-is-written-and-never-drained) (= D-21) | Covered **except** the missing `type` filter — see §8.2 |
| **N-6** No durable way to add a tool | [TL-10](../current/defect-register/TOOL-LAYER-DEFECTS.md#tl-10--tenant-scoped-tools-are-unreachable-by-construction), [TL-13](../current/defect-register/TOOL-LAYER-DEFECTS.md#tl-13--the-tool-status-gate-is-not-wired-into-execution), [TL-22](../current/defect-register/TOOL-LAYER-DEFECTS.md) (MCP), [EP-02](../current/defect-register/06-EXECUTION-PIPELINE-DEFECTS.md), [MI-14](../current/defect-register/11-META-INTELLIGENCE-DEFECTS.md), [DM-08](../current/defect-register/03-DATA-MODEL-DEFECTS.md), + D-20 | **Worse than recorded here.** TL-10: the executor never passes `company_id`, so tenant tools are unreachable *even in the process that registered them* — the restart-loss concern is secondary |
| **N-7** Sandbox unsuitable as a store | [TL-16](../current/defect-register/TOOL-LAYER-DEFECTS.md#tl-16--the-tenant-workspace-lives-in-tmp-and-is-node-local), [TL-01](../current/defect-register/TOOL-LAYER-DEFECTS.md#tl-01--the-default-sandbox-runs-llm-authored-code-as-the-backend-os-user), [TX-01](../current/defect-register/09-TOOLS-DEFECTS.md) | Durability and the host-user exposure both covered. The 4096-char stdout cap is not — see §8.2 |
| **N-8** Closed schema, silent drops | [EP-05](../current/defect-register/06-EXECUTION-PIPELINE-DEFECTS.md#ep-05--eight-settings-in-the-builder-have-no-runtime-reader), [EP-06](../current/defect-register/06-EXECUTION-PIPELINE-DEFECTS.md), [PO-09](../current/defect-register/01-PRODUCT-OVERVIEW-DEFECTS.md#po-09--a-mistyped-config-key-in-the-entity-builder-disappears-silently), [PC entry at 07:281](../current/defect-register/07-PLANNING-AND-CRITICS-DEFECTS.md) | Fully covered, and named as register pattern #2, *“declared but not enforced”* |
| **Layer 3** outbound idempotency | [TL-39](../current/defect-register/TOOL-LAYER-DEFECTS.md), [EP-13, EP-14](../current/defect-register/06-EXECUTION-PIPELINE-DEFECTS.md) (dead `idempotency_key` columns), [TX-I7](../current/defect-register/09-TOOLS-DEFECTS.md#tx-i7--idempotency-keys-on-every-write-tool) | Covered. [TL-04](../current/defect-register/TOOL-LAYER-DEFECTS.md#tl-04--email_send-lets-the-model-override-the-smtp-server-and-password) and [TL-09](../current/defect-register/TOOL-LAYER-DEFECTS.md#tl-09--subject-data-is-model-chosen-with-no-ownership-check) add two this document missed: the model can override the SMTP host and password, and recipient / lead-id / ad-account are all model-chosen with no ownership check |

### 8.2 Genuine gaps — not in any register

Five items, in the order they should be added.

| Gap | Where it belongs | Why it is not already there |
|---|---|---|
| **N-4 — `campaigns.scheduled_start` is written and never read** | [12 — Voice & telephony](../current/defect-register/12-VOICE-AND-TELEPHONY-DEFECTS.md), next free id | The voice register has 21 defects and covers `max_calls_per_hour` ([VT-I2](../current/defect-register/12-VOICE-AND-TELEPHONY-DEFECTS.md#vt-i2--enforce-max_calls_per_hour)) but not scheduling. It is the same *declared-but-not-enforced* shape as EP-05 — a field the UI shows and nothing acts on — and it strands a reachable `scheduled` status |
| **N-5b — the dispatch fallback has no entity-`type` filter** | [13 — Gateway](../current/defect-register/13-GATEWAY-AND-REALTIME-DEFECTS.md), as a second paragraph on GW-17 | GW-17 records the missing `ORDER BY`. It does not record that the query is also unfiltered on tier, so an inbound webhook can be dispatched to an `ACTION` or `SKILL` that was never meant to be an entry point |
| **N-9 — third-party ad budget is uncapped** | [15 — Governance](../current/defect-register/15-GOVERNANCE-AND-HITL-DEFECTS.md) or the tool layer | [TL-09](../current/defect-register/TOOL-LAYER-DEFECTS.md#tl-09--subject-data-is-model-chosen-with-no-ownership-check) covers *which* ad account is charged; [GH-05](../current/defect-register/15-GOVERNANCE-AND-HITL-DEFECTS.md#gh-05--an-unmapped-tool-costs-0-and-warns-once-per-process) covers unpriced tools costing nothing. Neither covers **how much** — `budget_amount_micros` is a free model-supplied parameter and `governance.max_cost_usd` governs platform cost only. Now sharper given TL-13: these tools are ungated |
| **N-10 — no machine authentication** | [04 — Auth, RBAC & tenancy](../current/defect-register/04-AUTH-RBAC-TENANCY-DEFECTS.md) | Zero mentions of API keys or service accounts across all 22 registers. Arguably a missing feature rather than a defect — but it becomes a defect the moment a scheduler exists, because the only way to drive the platform on a timer is to park a human's refresh token in a script |
| **The memory/context builder toggles are inert** | [06 — Execution pipeline](../current/defect-register/06-EXECUTION-PIPELINE-DEFECTS.md), appended to EP-05 | EP-05 lists eight dead builder settings and omits six more: `capabilities.memory.semantic_search_enabled`, `semantic_top_k`, `episodic_memory_count`, `context_engineering.inject_semantic_context`, `inject_episodic_memory`, `inject_cortex_viewport`. MC-01 explains *why* they do nothing; nothing records that the UI still offers them |

Also worth recording, though smaller: the **4096-character stdout cap** on
`sandbox_code` ([sandbox_executor.py:47](../../backend/src/ai/tools/sandbox/sandbox_executor.py:47))
belongs alongside TL-16 — silent truncation of a tool result is a correctness
issue, not just a limit.

### 8.3 What is deliberately absent, and should stay absent

The four missing GTM layers — **business object store, tenant scheduler, sequence
/ ESP engine, consent & suppression** — appear nowhere in the register, and that
is the right call. A defect register records code that exists and misbehaves.
These are capabilities that were never built, so they belong in the roadmap
([marketing-sales-automation.md §8](marketing-sales-automation.md)), not here.

Two caveats to that:

1. **Consent and suppression are arguably a present-tense defect, not a future
   feature.** The voice campaign path ships today and dials real numbers with no
   DNC check, no consent record and no AI disclosure. That is a compliance
   exposure in running code — closer in kind to the T0 auth and billing entries
   than to an unbuilt feature. Worth one entry in
   [12 — Voice](../current/defect-register/12-VOICE-AND-TELEPHONY-DEFECTS.md)
   saying so plainly, even if the fix is a roadmap item.
2. **[PO-08](../current/defect-register/01-PRODUCT-OVERVIEW-DEFECTS.md#po-08--db_records-is-an-advertised-context-source-that-does-nothing)
   is the object store's stub.** `ContextSourceType.DB_RECORDS` is live in the
   API enum and ignored at runtime, with a *Coming Soon* badge in the builder. It
   is the one place the missing Layer 1 already has a footprint in shipped code.

### 8.4 What the register caught that this document got wrong

Recorded for honesty, and corrected in §2 above:

- **The `EXPERIMENTAL` gate does not gate anything** — [TL-13](../current/defect-register/TOOL-LAYER-DEFECTS.md#tl-13--the-tool-status-gate-is-not-wired-into-execution).
  This document originally claimed the 64 social tools sit behind a feature-flag
  opt-in, and called that “configuration, not code”. Both halves were wrong: the
  gate has no caller, and the tools run unconditionally.
- **Seven of the sixteen social platforms cannot store a connection at all** —
  [PO-07](../current/defect-register/01-PRODUCT-OVERVIEW-DEFECTS.md#po-07--you-can-connect-9-social-platforms-but-16-have-tools).
  Not mentioned here at all, and it narrows what “social publishing works today”
  means considerably.
