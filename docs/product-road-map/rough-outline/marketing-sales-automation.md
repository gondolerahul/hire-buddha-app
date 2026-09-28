# Automating the Marketing & Sales Department — Design Brainstorm

> **Status:** thinking document, not a committed plan.
> **Scope:** what it would take for HireBuddha to run the whole GTM function of a
> B2B SaaS startup — marketing + sales — as Actions/Skills/Agents/Processes.
> **Ground truth:** the platform as it exists on `fresh-main`, cross-checked
> against [docs/current/](../current/) and the code. Where the
> [rough outline](rough-outline/) roadmap disagrees with the code, the code wins
> and the gap is named.
> **Written:** 2026-08-22.

---

## 1. The honest verdict, up front

**The execution substrate is strong and genuinely ahead of most agent platforms.
The business-data layer and the compliant-outbound layer barely exist.**

You have a CPU and an operating system. You are missing the filesystem (business
objects the agents can read and write) and the network stack (stateful,
consent-gated, deliverable outbound communication).

Rough readiness against what a GTM department actually needs:

| Layer | Readiness | Why |
|---|---|---|
| Execution kernel (loop, critics, retry, budget, suspend/resume) | ~85% | One `AgentLoop`, 9 phases, 4 critic gates, budget-aware. Real. |
| Composition model (ACTION→SKILL→AGENT→PROCESS) | ~85% | Works, and the seeds prove it end-to-end. |
| Memory & retrieval (CORTEX, episodic, pgvector RAG) | ~75% | Strong for *the agent's own* experience. Not a business database. |
| Tool breadth | ~50% | 98 tools, but the GTM-critical ones are missing or experimental. |
| Human-in-the-loop | ~50% | Approve/reject on a step. No "edit this draft then publish". |
| Multi-tenancy, billing, RBAC | ~70% | Solid design; [known T0 defects](../current/DEFECT-REGISTER.md) in billing. |
| **Business object model (Account/Contact/Deal/Activity)** | **~0%** | Does not exist. This is the blocker. |
| **Triggers & scheduling for tenant work** | **~15%** | Webhook receiver exists; no scheduler, no declarative subscriptions. |
| **Consent, suppression, deliverability** | **~0%** | Zero code. Legally load-bearing. |
| **GTM reporting & attribution** | **~5%** | Reporting is platform-ops shaped, not revenue shaped. |

So: **capable enough to build the agents, not capable enough to run the
department.** The gap is four missing layers, not a hundred missing agents.

---

## 2. What actually exists today (inventory)

Verified in code, not taken from the roadmap docs.

### 2.1 The kernel — genuinely good

- One engine: `AgentLoop.run(run_id)`
  ([core/agent_loop.py](../../backend/src/ai/core/agent_loop.py)). Nine phases per
  iteration: perceive → strategize → pre-critic → act → observe → post-critic →
  alignment → supervisor → reflect → decide.
- Four critic gates in `RealCriticPipeline`, with a failure-tag → retry-strategy
  pure function (`pick_retry`, 7 strategies), and a **critic cost cap at 20% of
  run spend**. That last detail matters: quality control is budgeted.
- Planning is best-of-N: 3 candidate plans at 3 temperatures, 8 deterministic
  invariant checks, LLM judge picks. Static plans bypass generation.
- Suspend/resume: a step that invokes a child entity snapshots the parent and
  releases the worker. That is what makes PROCESS→AGENT→SKILL composition
  affordable at all.
- Governance budget per entity (`max_cost_usd`, `timeout_ms`,
  `max_recursion_depth`), consumed every iteration.

### 2.2 Tools — 98 registered

| Family | Count | GTM relevance |
|---|---|---|
| `core/` | 5 | `web_search`, `batch_web_search` (25 queries), `scraper_tool` (Firecrawl), `calculator`, `file_writer` — **directly usable for research, ICP work, competitive intel** |
| `documents/` | 5 | pdf / docx / pptx / xlsx generation — **proposals, one-pagers, decks, reports: production-ready** |
| `email/` | 4 | IMAP ingest/classify/draft + SMTP send, per-company `email_connections` — **fine for a rep's inbox, wrong shape for sequences** |
| `media/` | 5 | Imagen image gen, Veo video gen, ffmpeg edit — **ad creative and social assets** |
| `sandbox/` | 3 | python/bash, terminal, Playwright headless browser — **the escape hatch for anything unbuilt** |
| `crm/` | 4 | `get_current_datetime`, `whatsapp_send_tenant`, `google_calendar_create_event`, `crm_update_lead` — **misleading name: these are thin HTTP bridges to a *tenant-hosted* endpoint, not a CRM** |
| `meta/` | 8 | Meta-Agent Board tooling — introspect, registry search, entity creator/executor, tool synthesis |
| `social/` | 64 | 16 platforms incl. LinkedIn, X, FB, IG, YouTube, TikTok, Reddit + **6 ad platforms** + Sales Navigator — **all `EXPERIMENTAL`, all `$0` SKU** |

### 2.3 Channels

- **Voice**: inbound + outbound speech-to-speech over Twilio / Tata Tele, an
  auto-dialer (`CampaignExecutor`), `campaigns` / `campaign_calls` tables, and
  LLM disposition classification (`interested` / `not_interested` /
  `voicemail` / …) with reason codes. This is the most production-shaped surface
  on the platform.
- **WhatsApp**: sessions + conversation history.
- **Email**: IMAP/SMTP per company.
- **Webhooks in**: `POST /webhook/inbound` with source-detection strategies for
  HubSpot/Salesforce/Zoho headers, LinkedIn, Facebook, Instagram, Twitter,
  TikTok, GitHub, Twilio, plus a generic fallback
  ([gateway/webhook_inbound.py](../../backend/src/gateway/webhook_inbound.py)).
- **`lead_queue`**: a persistent, deduped, retrying queue of CRM leads awaiting
  an outbound call ([lead_queue_model.py](../../backend/src/ai/lead_queue_model.py)).

### 2.4 What the platform remembers

CORTEX trees (4 domains: knowledge / episodic / experience / intelligence),
`documents` + `document_chunks` with pgvector RAG, offline "Dreaming"
consolidation into rules.

**Read that list again and notice what it is:** the platform remembers *what the
agent did*. It does not remember *what the business is*.

---

## 3. The four missing layers

### Layer 1 — There is no business object store

This is the single biggest gap and everything else depends on it.

Verified absent:
- No `accounts`, `contacts`, `leads`, `opportunities`, `activities` tables.
- `tenant_entity_defs` / `tenant_records` / `tenant_record_links` — the dynamic
  per-tenant schema the roadmap builds on ([tech doc §10](rough-outline/product_technical_documentation.md))
  — **zero code**. `grep` returns nothing.
- `lead_queue` is a *dialer* queue with a `lead_data` JSONB blob, not a lead record.
- `campaigns` is a *voice calling* campaign, not a marketing campaign. **Name
  collision to plan around.**
- `crm_update_lead` POSTs to whatever HTTP endpoint the tenant configured in
  `IntegrationRegistry.service_metadata`. HireBuddha stores nothing.

Consequence: an agent cannot answer *"have we contacted this person before?"*,
*"which accounts match our ICP?"*, *"what happened on this deal last month?"* —
which is most of the job.

### Layer 2 — There are no tenant-controlled triggers

- Every arq cron is a platform maintenance job (CORTEX resume, dreaming, critic
  calibration, KPI rollup) — [worker.py:104](../../backend/src/ai/worker.py:104).
  **A tenant cannot schedule anything.** No "every Monday 9am", no "poll the
  inbox every 5 minutes".
- The webhook dispatcher routes on an `entity_id` in the payload or a fallback —
  there is no declarative "which Process owns `lead.inbound`" registry, no
  dedupe key, no parked/dead-letter state, no completion signal.
- No LOOP tier / standing entity. Every run is a one-shot.

GTM work is overwhelmingly **event-driven and recurring**. Right now the only
way to start work is a human pressing Execute, an inbound call, or a raw webhook.

### Layer 3 — Outbound is not production-shaped

`email_send` is one SMTP message. A real sequence engine needs, and the platform
has **none** of:

- suppression / unsubscribe / bounce / complaint handling (`grep` for
  `unsubscribe|suppression|bounce|consent|dnc` across `backend/src/` returns
  three unrelated hits — a Redis `pubsub.unsubscribe` and an audio echo comment)
- per-recipient enrollment state machine, send windows, throttling
- reply detection → auto-stop
- open/click tracking, link wrapping
- sender identity / domain warmup management
- **idempotency on side effects.** `idempotency_key` columns exist on the log
  tables ([orm/execution.py:59](../../backend/src/ai/orm/execution.py:59)) but no
  tool reads one. The kernel *retries steps by design*. A retried
  `email_send` sends twice.

### Layer 4 — There is no compliance surface

No consent store, no DNC list, no AI-disclosure, no consent-to-record. **The
voice campaign path is already shipping and already exposed** — this is a
present-tense gap, not a future one.

---

## 4. Decisions taken (2026-08-22)

| # | Decision | Chosen |
|---|---|---|
| 1 | System of record | **Hybrid — per-object mastering** |
| 2 | Storage placement | **Per-tenant Postgres in the tenant sandbox** |
| 3 | First customer | **Ourselves as tenant zero** |
| 4 | Connectors | **Finish MCP first**, then hand-built HubSpot |

### 4.1 Hybrid system of record

A B2B SaaS startup almost always already has HubSpot or Pipedrive, Google
Workspace, LinkedIn, maybe Apollo or Clay. Becoming their CRM is a three-year
product. But orchestrating with no local store means agents are stateless and
you can never answer a cross-run question. So: local store for everything, with
declared mastering per object.

| Object class | Master | Behaviour |
|---|---|---|
| Account, Contact, Opportunity | **External CRM** if connected, else HireBuddha | Mirror + write-back; master wins conflicts |
| Activity/Touch, Signal, Sequence, Enrollment, ContentAsset, Segment, Consent | **HireBuddha always** | No external home exists for these |

This matches [tech doc §21](rough-outline/product_technical_documentation.md) and
lets you sell to both "we have HubSpot" and "we have a spreadsheet" without
maintaining two products.

### 4.2 Storage placement — sandbox-resident, and why tenant-zero makes that cheap

Per the roadmap ([tech doc §10.4](rough-outline/product_technical_documentation.md)):
`gtm_*` tables, field defs and links live in a Postgres inside the tenant's own
container. Hard physical isolation, cross-tenant leakage impossible by
construction, and the portability promise becomes literal — the business is a
volume.

The standing objection to this is **fleet operations**: hibernation tiers,
pooled connections, nightly dumps, regional topology. At **n = 1 tenant those
costs are all deferred**, and decision 3 (tenant zero) means n = 1 for the whole
of Increments 0–2. The isolation is bought now; the fleet bill arrives when
there is a fleet.

**But it is not "reuse the shipped sandbox."** What exists today
([tenant_manager.py](../../backend/src/ai/tools/sandbox/tenant_manager.py))
was built for ephemeral code execution, and three of its properties are actively
wrong for a database:

| Shipped behaviour | Problem for a tenant DB |
|---|---|
| Workspace is a **bind mount on `/tmp/sandbox/{company_id}`** | `/tmp` is not durable storage. A Postgres data directory cannot live there. Needs a **named Docker volume** |
| Container **auto-pauses after `SANDBOX_IDLE_PAUSE_SECONDS` (900)**, reaped by cron | A paused container is a paused Postgres. Every control-plane read would have to unpause first — the hibernation problem arrives immediately, even at n=1 |
| Image is `hb-sandbox` (Playwright + ffmpeg + LibreOffice), joined to an `--internal` network behind the egress proxy | No Postgres in the image. And the egress proxy governs traffic *out of* the sandbox; the control plane reading *into* the tenant DB is the opposite direction and has no path today |

**Therefore:** a **separate `hb-tenant-db-{company_id}` container** — its own
image (`postgres` + `pgvector` if ever needed), its own named volume, its own
lifecycle independent of the code-sandbox idle-pause, and an explicit
control-plane→tenant-db network. Bounded work, but a real build; do not size it
as "we already have sandboxes."

**Non-negotiable regardless of placement:** one **record service is the sole
write path**. Agents never touch tables. That is what keeps ownership rules,
compare-and-set versioning and ref materialization enforceable — and what makes
the placement decision reversible if the fleet economics turn out badly.

### 4.3 Tenant zero

HireBuddha is itself a B2B SaaS startup, so our own GTM is the test case. This
is the cheapest possible source of truth about what is missing, carries no
customer risk while Layers 3 and 4 are unbuilt, and gives every agent a real
brand brain and real ICP to work against from day one instead of synthetic
fixtures.

It also front-loads the honesty: if we will not run our own outbound on it, it
is not ready to sell.

### 4.4 MCP before hand-built connectors

[`mcp/`](../../backend/src/ai/tools/mcp/) is a complete, tested adapter layer
with no transport. Finishing it costs one concrete client + a config table + a
bind call at worker startup, and then tenants attach connectors nobody wrote.
HubSpot still gets hand-built afterwards as the reference two-way integration —
mastering and conflict semantics (§4.1) are too load-bearing to leave to a
generic adapter — but the long tail rides on MCP.

## 5. The GTM data model

### 5.1 Shape: typed spine + validated flex bag + typed edges

The roadmap proposes pure JSONB `tenant_records`. I would not do that for GTM.
Pure JSONB makes uniqueness (email dedupe!), indexing, constraints and reporting
painful, and every agent has to guess field names. Pure fixed schema can't
absorb per-tenant reality.

**Hybrid:**

```
gtm_<object>
  id, company_id, created_at, updated_at, deleted_at
  <typed core columns>          -- real columns, real indexes, real constraints
  custom          JSONB         -- validated against gtm_field_defs
  external_refs   JSONB         -- {"hubspot": "123", "salesforce": "003..."}
  source, source_run_id         -- provenance: which agent run wrote this
  version                       -- compare-and-set

gtm_field_defs                  -- per-tenant custom field registry
  company_id, object_type, name, type, target (for refs), status, aliases

gtm_links                       -- typed edge table
  company_id, src_id, src_type, dst_id, dst_type, rel_type
```

Three properties this buys you:

1. **Agents can be prompted against a stable vocabulary.** `contact.email` is
   always `contact.email`.
2. **Per-tenant variance is real but bounded.** New fields land in `custom`;
   when the Learning System sees one filtered often, promote it to an expression
   index (roadmap §19.3 — good idea, keep it).
3. **Field promotion is an upgrade path, not a migration.** Nothing breaks.

**Critical companion: a `gtm_schema_describe` tool.** An agent asks *"what
fields does Account have in this tenant?"* rather than hallucinating. This is
what makes multi-tenant shape variance actually work in practice, and it is
cheap to build.

### 5.2 The objects — a GTM subset, not all 27

The blueprint's 27 canonical objects span the whole enterprise. For marketing +
sales, start with **14**:

| # | Object | Core fields | Notes |
|---|---|---|---|
| 1 | **Account** | domain, name, industry, employee_count, revenue_band, country, tech_stack[], icp_score, tier, lifecycle_stage, owner | Domain is the natural key |
| 2 | **Contact** | email, phone, first/last, title, seniority, function, linkedin_url, account_id, lifecycle_stage, consent_state | **No separate Lead object** — see below |
| 3 | **Opportunity** | account_id, name, amount, currency, stage, close_date, probability, source, competitor, loss_reason | |
| 4 | **Activity** | type, direction, channel, contact_id, account_id, opportunity_id, occurred_at, subject, body_ref, outcome, run_id | **The highest-value object.** Every email, call, meeting, post, reply. Attribution and "have we touched this person" both come from here |
| 5 | **Signal** | type, subject_ref, source, urgency, confidence, payload, observed_at | The world did something: funding round, job post, tech install, review, competitor mention, site visit |
| 6 | **Segment** | name, definition (query DSL), materialized_at, member_count | Saved audience |
| 7 | **GtmCampaign** | name, goal, channels[], budget, start/end, segment_id, kpis | ⚠️ **must not be called `campaigns`** — collides with voice |
| 8 | **Sequence** | name, steps[] (channel, delay, template_ref, condition), exit_rules | The definition |
| 9 | **Enrollment** | sequence_id, contact_id, current_step, next_action_at, status, exit_reason | The per-contact state machine instance. **Deterministic code, never LLM-driven** |
| 10 | **ContentAsset** | type, title, channel, body/artifact_id, state, brand_check, published_url, metrics | Blog, post, email template, case study, ad creative |
| 11 | **Message** | enrollment_id, contact_id, channel, rendered_subject/body, sent_at, provider_id, thread_id, events[] | Per-recipient instance; needed for threading + reply matching |
| 12 | **Consent** | identifier (email/phone), channel, purpose, state, source, captured_at, expires_at, evidence_ref | **Non-negotiable.** Enforced in the tool layer, not in a prompt |
| 13 | **ICPDefinition** | firmographic rules, technographic rules, disqualifiers, scoring weights, version | ICP as *data* makes scoring auditable and tunable instead of vibes-in-a-system-prompt |
| 14 | **MessagingLibrary** | positioning, value props, proof points, objection handling, tone rules, banned claims | The "brand brain". Every content agent reads it; the brand critic enforces it |

Later, as the department deepens: `Quote`, `CompetitorProfile`, `Target/Quota`,
`Forecast`, `Partner`.

**Two deliberate deviations from the blueprint:**

- **No `Lead` object.** Use `Contact` + `lifecycle_stage`. The Salesforce
  lead-then-convert model creates duplicate-identity pain that agents handle
  badly. HubSpot's contact-with-stage model is simpler and loses nothing.
- **`Signal` and `Activity` are separate.** *We did something* vs *the world did
  something*. Collapsing them destroys attribution.

---

## 6. The entity registry — deliberately lean

The most instructive thing in the codebase is
[SeedDocFactoryLite](../../backend/scripts/seeds/default_entities/SeedDocFactoryLite/create_lite.py):
a 50-entity, 4-level hierarchy replaced by **one flat AGENT**, because every
extra level gets its own perceive-strategize-act-critique cycle and multiplies
LLM calls.

The blueprint's 100 agents would be a cost catastrophe and an ops nightmare.
**For the entire marketing + sales department, target roughly 6 Processes, ~18
Agents, ~30 Skills, ~25 Actions.**

Rules of thumb:
- **ACTION** only for a genuinely reusable tool wrapper with a real IO contract.
- **SKILL** should be fat — 3–6 steps doing a coherent job. Prefer one fat skill
  over three thin ones.
- **AGENT** only where judgment loops and self-correction earn their cost.
- **PROCESS** = one end-to-end value stream with its own budget envelope.

### 6.1 Processes (6)

| ID | Process | Trigger | Autonomy | Blast radius |
|---|---|---|---|---|
| **GTM-P1** | **Demand Sensing** — competitive intel, intent signals, market/news watch, review monitoring | schedule (daily/weekly) | A3 autonomous | **read-only, ship first** |
| **GTM-P2** | **Revenue Reporting** — funnel, pipeline, channel performance, weekly exec brief, forecast | schedule (weekly) | A3 autonomous | read-only |
| **GTM-P3** | **Content Engine** — brief → draft → brand/fact critic → HITL → publish → measure | schedule + signal | A1 (approve before publish) | brand risk |
| **GTM-P4** | **Inbound Response** — form/chat/call → enrich → score → route → respond in minutes → book | signal (`lead.inbound`) | A2 (act, notify) | customer-facing |
| **GTM-P5** | **Outbound Prospecting** — ICP → list → enrich → score → personalize → sequence → reply handling → handoff | schedule + signal | A1 → A2 | **highest risk** |
| **GTM-P6** | **Deal Desk** — pre-call research, call notes, follow-ups, proposal/quote, RFP & security questionnaires, CRM hygiene, deal risk | signal (`meeting.*`, `deal.*`) | A2 | internal-mostly |

### 6.2 Agents (~18)

| Process | Agents |
|---|---|
| P1 | Competitive Analyst · Intent & Signal Scout · Market/News Monitor |
| P2 | Funnel Analyst · Exec Briefing Writer |
| P3 | Content Strategist (briefs, calendar) · Long-Form Writer · Social & Repurposing Agent · Brand Guardian (critic role) |
| P4 | Speed-to-Lead Responder (voice/chat/email) · Qualifier & Router · Meeting Booker |
| P5 | List Builder · Enrichment & Hygiene Agent · Personalization Writer · Reply Handler |
| P6 | Pre-Call Researcher · Call Notes & CRM Scribe · Proposal & RFP Agent |

### 6.3 Skills (~30, reusable across processes)

Enrichment-by-research · ICP scoring · identity resolution & dedupe · account
research brief · buying-committee mapping · personalization render · brand-voice
check · claim/fact verification · SEO brief · competitive teardown ·
repurposing (1 asset → N derivatives) · reply classification · meeting notes →
MEDDIC/BANT · CRM writeback · sequence step render · suppression check ·
segment materialization · proposal assembly · RFP answer retrieval · funnel
query · attribution rollup · exec brief composition · social post render ·
ad copy variants · landing page copy · case study interview → draft · review
response · webinar follow-up · no-show recovery · deal risk scoring.

### 6.4 Actions (~25)

Mostly thin wrappers on existing tools plus the **new record CRUD tools**
(§7.1). Do not create an ACTION per tool "for completeness" — create one when a
Skill needs a stable IO contract around it.

---

## 7. Missing tools, prioritized

### 7.1 Tier A — blocks everything

| Tool | Why |
|---|---|
| `gtm_record_query` / `gtm_record_upsert` / `gtm_record_link` | **The single most important new tool.** Without it agents cannot remember business facts. All writes go through the record service (ownership, versioning, ref materialization) |
| `gtm_schema_describe` | Lets an agent discover this tenant's field shape instead of hallucinating |
| `consent_check` / `suppression_check` | Called *by the tool layer* before any send or dial. Not advisory |
| ESP send (SendGrid / Postmark / SES / Resend) | Bulk-capable, with suppression injection, unsubscribe header, link wrapping, tracking, and **an idempotency key** |
| Inbound event ingest (bounce / complaint / open / click / reply) | The other half of the ESP. Feeds `Message.events` and auto-suppression |
| Calendar availability + booking | Only `google_calendar_create_event` exists — create-only, real-estate shaped, service-account auth. Need free/busy, round-robin, reschedule, tenant timezone |

### 7.2 Tier B — high leverage

| Tool | Notes |
|---|---|
| **CRM connectors: HubSpot first**, then Pipedrive, then Salesforce | Two-way, honouring the mastering rules of §4. HubSpot has the best API and the highest B2B-SaaS penetration at this stage |
| Enrichment | **v0: enrichment-by-research** using the existing `web_search` + `scraper_tool` + LLM extraction. Costs tokens, no vendor contract, ships in days. Swap to Apollo/Clearbit/PDL later behind the same Skill interface |
| Slack / Teams | Approvals and notifications where the team already is. Approving a draft post from Slack is a large UX unlock |
| Analytics ingest (GA4 / Segment / PostHog) | Intent signals + attribution |
| Embeddable web form + chat widget | The generic webhook works, but there is no capture surface to hand a customer |
| E-signature (DocuSign / Dropbox Sign) | Closes the proposal loop |
| Stripe | Closed-won → revenue, for real attribution |
| Meeting recorder / transcription | Call notes today only work for platform-originated voice calls |
| SEO (GSC / Ahrefs / Semrush) | Content Engine is guessing without it |

### 7.3 Tier C — validate what already exists

The 64 social tools and 6 ad platforms are `EXPERIMENTAL` with `$0` SKUs. Before
any of them is promised to a customer:

- a live-credential integration test per platform
- **budget guardrails on ad spend.** `max_cost_usd` caps *platform* cost. An
  agent that raises a Google Ads daily budget 10× is not caught by anything
- HITL binding on every spend-changing call
- billing SKUs, so the platform isn't eating the metering

### 7.4 The MCP shortcut

[`mcp/`](../../backend/src/ai/tools/mcp/) is a **complete, tested adapter layer
with no transport**: `MCPToolAdapter` works, `bind_mcp_server` works, the
read-only-first policy works — but `MCPClient` is a bare `Protocol` with no
stdio/HTTP/SSE implementation, no `mcp_servers` config table, and nothing calls
it outside tests.

Finishing MCP (one concrete client + a config table + a bind call at worker
startup) would let tenants attach third-party connectors *without you building
each one*. For a long tail of GTM SaaS, this is likely a better investment than
writing connectors by hand. **Strong candidate for early work.**

### 7.5 A warning on LinkedIn

The shipped LinkedIn tools cover **publishing, analytics, comments and profile**
— all legitimate. They do **not** cover connection requests or DMs, because the
LinkedIn API does not offer them. Automating those via the headless browser is
against LinkedIn's ToS and risks the customer's account. Recommend: LinkedIn =
publish + listen + (Sales Navigator *if* the tenant holds API access), and
human-in-the-loop for connections and DMs. Say this to customers explicitly —
competitors who don't will burn accounts.

---

## 8. Missing platform features (not tools)

| # | Feature | Why it's needed | Size |
|---|---|---|---|
| 1 | **Record service + object store** | §5. Everything depends on it | L |
| 2 | **Entity scheduler** — `entity_schedules` table + arq sweeper | "Every Monday 9am". Table stakes, currently absent | **S** |
| 3 | **Signal bus + trigger registry** | Declarative event→Process routing, dedupe, parking, completion signals. Roadmap §18 is a good design; build the 80% version | M |
| 4 | **Sequence/enrollment engine** | Deterministic state machine. **Never let the LLM decide "is it time for step 3"** | M |
| 5 | **Consent & suppression service** | Enforced in the tool layer | S |
| 6 | **Content review queue** — approve / **edit** / reject, batched | HITL today is approve-or-reject on a step. Marketers need to tweak a draft and ship it | M |
| 7 | **Send-window + rate limiting per channel per tenant** | Deliverability and courtesy | S |
| 8 | **Identity resolution / dedupe** | Two lists, one person, two emails. Silently poisons everything downstream | M |
| 9 | **Brand critic wired into the critic pipeline** | The pipeline is generic; a *domain* critic reading `MessagingLibrary` is the single highest-leverage quality lever available | **S, high ROI** |
| 10 | **Tenant timezone + working hours** | `get_current_datetime` is hardcoded IST ([crm_tools.py:25](../../backend/src/ai/tools/crm/crm_tools.py:25)). `companies` has no timezone column | **XS** |
| 11 | **Outbound idempotency** | The kernel retries by design. Every side-effecting tool needs a key | S |
| 12 | **Dry-run / preview mode** | Render a whole sequence, send nothing. Essential for customer trust before go-live | M |
| 13 | **Business KPI reporting** | Current reports are execution health and cost. Customers want pipeline, funnel, CAC, meetings booked | M |
| 14 | **Sender identity & domain warmup management** | Which mailbox, which domain, what daily cap, what warmup stage | M |
| 15 | **"What did my AI SDR do today" activity feed** | Observability for the customer, not just for ops. Drives retention more than any feature here | S |
| 16 | **Standing/resident agent** | Cheap version: a scheduled PROCESS with CORTEX-persisted state. Do this before building a real LOOP tier | S |

---

## 9. What to actually automate — the task catalogue

### Marketing

**Research & intelligence** — ICP maintenance · competitive teardowns &
battlecards · pricing/feature watch · funding & hiring signals · category/news
monitoring · review & G2 monitoring · voice-of-customer synthesis

**Content** — SEO keyword & gap analysis · content briefs · blog/long-form ·
landing pages · case studies · one-pagers & whitepapers · newsletters · social
posts · video scripts · ad copy · webinar decks · **repurposing (1 asset → 10
derivatives)** ← highest ROI-per-token on the platform, and the tools already exist

**Distribution & demand** — editorial calendar · social publishing & engagement ·
community management · lifecycle/nurture programs · webinar & event ops
(invites, reminders, follow-ups) · PR drafting & journalist lists

**Paid** — campaign setup · creative variants · budget pacing · keyword/bid
hygiene · performance reporting · landing-page A/B

**Analytics** — funnel reporting · channel attribution · MQL quality · CAC by
channel · content performance

### Sales

**Pipeline generation** — target account list from ICP · buying-committee
mapping · enrichment & data hygiene · dedupe · lead scoring & routing ·
**speed-to-lead inbound response** ← the voice infra is closest to done ·
outbound sequences · reply handling & classification · meeting booking,
reminders, no-show recovery

**Deal execution** — pre-call research briefs · discovery notes →
MEDDIC/BANT · **security questionnaires & RFP responses** ← huge B2B SaaS time
sink and perfectly RAG-shaped · proposal & quote generation · pricing approvals ·
objection handling · competitive displacement · contract redlines (legal HITL)

**Hygiene & management** — auto-logging activities · field completion · stage
validation · pipeline inspection · deal risk scoring · forecast rollup ·
renewal & expansion signals · weekly exec pipeline brief · rep onboarding &
enablement

### The sequencing insight

Split the department by **blast radius**, not by function:

> **Inside the walls** — research, enrichment, scoring, list building,
> competitive intel, reporting, CRM hygiene, meeting prep, proposal drafting,
> RFP answers, forecasting. Read-mostly, reversible, no brand risk, no legal
> surface.
>
> **Outside the walls** — sending email, posting, calling, spending ad budget.
> Irreversible, brand-bearing, legally regulated.

Inside-the-walls work can go to **A3 (autonomous, notify)** almost immediately
and is where the existing tool set is strongest. Outside-the-walls work needs
Layers 3 and 4 built first, and should sit at **A1 (draft → human approves)**
for at least two quarters.

That happens to be the exact opposite of what a demo would emphasise — and it's
the right order.

---

## 10. Proposed increments

| Inc | Theme | Contains | Customer-visible? |
|---|---|---|---|
| **0** | **Foundation** | `hb-tenant-db` container + named volume + control-plane network (§4.2) · object store + **record service as sole write path** · record/schema tools · entity scheduler · consent & suppression · tenant timezone · outbound idempotency | No — but everything blocks on it |
| **1** | **Read-only value** | GTM-P1 Demand Sensing + GTM-P2 Revenue Reporting. Uses existing search/scrape/doc tools + the new store. Real artifacts, zero brand risk. **Run against our own GTM** | Internal first (tenant zero) |
| **2** | **Content, human-gated** | Brand brain + brand critic + review queue (approve/**edit**/reject) + GTM-P3. Publish via existing social tools, HITL before publish | Yes |
| **3** | **Inbound / speed-to-lead** | GTM-P4. Form + webhook capture → enrich → score → route → instant voice/email/WhatsApp → book. Leans on the strongest existing infra | Yes — highest ROI per unit of build |
| **4** | **Outbound** | ESP + deliverability + sequence engine + reply handling + warmup + GTM-P5. **Only after 0–3 are solid** | Yes — highest risk |
| **5** | **Deal desk** | GTM-P6: pre-call research, notes, proposals, RFP/security questionnaires, CRM hygiene, forecast | Yes |
| **6** | **Later** | Paid media ops · ABM · partner/channel · customer marketing & advocacy | — |

Cross-cutting, in parallel: **MCP transport (Inc 0–1 — decided first, ahead of
hand-built connectors)** · signal bus (Inc 1–2) · hand-built HubSpot as the
reference two-way integration (Inc 2–3) · evaluation harness (from Inc 1 onward)
· nightly `pg_dump` of the tenant DB (from the first write).

**Tenant-zero gate:** we do not sell an increment we are not running ourselves.
Inc 1–2 land internally, Inc 3–4 land internally, and only then do they go to a
customer. That is what makes the A1-before-A2 autonomy discipline (§9) real
rather than aspirational.

---

## 11. Things that are easy to miss

1. **Deliverability is a product, not a tool.** Subdomain strategy, SPF/DKIM/
   DMARC, warmup, volume ramps, per-mailbox caps, bounce/complaint thresholds.
   Get this wrong and everything downstream is worthless because nothing reaches
   an inbox. This is the #1 non-obvious blocker for the outbound increment.

2. **Compliance is present-tense, not future.** The voice campaign path already
   ships. TCPA/DNC, consent-to-record, CAN-SPAM, GDPR/ePrivacy opt-in, CASL,
   India DPDP, and AI-disclosure rules (California SB 1001, EU AI Act
   transparency) all apply to what is running today.

3. **Do not let LLMs run state machines.** Sequence timing, suppression checks,
   dedupe, routing rules, enrollment transitions → deterministic code. LLMs for
   content, classification and judgment only. This is the single most important
   architectural rule here, for both reliability and cost.

4. **Evaluation.** How do you know a content agent is good enough to raise its
   autonomy? You need a golden set + an LLM-judge rubric + human spot-checks +
   downstream outcome metrics. The critic pipeline exists but there is no
   *domain* eval harness. Without one, autonomy levels are guesses.

5. **Cold start.** A new tenant has no ICP, no brand brain, no history.
   Onboarding must extract them: crawl the website, ingest existing content,
   import the CRM, mine won/lost deals. The onboarding wizard today is thin.
   This is where the roadmap's "Pragya" concept actually earns its keep.

6. **Attribution honesty.** Multi-touch attribution is mostly wrong. Build a
   clean `Activity` log + self-reported attribution ("how did you hear about
   us") + simple first/last touch, and say plainly that it's directional.

7. **Cost per outcome.** Per-contact personalization across 10k contacts is
   expensive. Tier it: templates for the long tail, N variants mid-tier,
   per-contact research only for tier-1 accounts. **Cost per booked meeting** is
   the metric that matters, not cost per token.

8. **Human accountability.** "Fully automate the department" still needs a named
   owner for brand approval, an escalation path, and a RevOps owner for data
   quality. And the customer's human reps must not be able to bypass logging, or
   the object store rots within a quarter.

9. **Billing model mismatch.** Metering platform cost is right for the platform
   and wrong for the buyer. Someone buying "an AI SDR" expects per-seat or
   per-meeting pricing. Separately: [D-01, D-02, D-03](../current/DEFECT-REGISTER.md)
   must be fixed before the first paying tenant.

10. **PII.** Storing prospect data means DPA, retention policy, deletion, DSAR.
    Prospect PII flowing into CORTEX and into Gemini/Anthropic/Azure prompts
    needs an explicit answer.

11. **The `campaigns` name collision.** Existing table is the voice dialer. Name
    the marketing object `gtm_campaigns` from day one.

12. **The demo-to-production gap.** 64 social tools sounds impressive and is
    mostly unvalidated. Pick the 6 that matter for B2B SaaS (LinkedIn, X,
    LinkedIn Ads, Google Ads, YouTube, Reddit), harden those, and mark the rest
    honestly.

---

## 12. Still open

Resolved in §4: system of record, storage placement, first customer, connector
strategy.

Still needing a call:

1. **Tenant-DB container lifecycle** — the code sandbox pauses at 900s idle and
   is reaped by cron. The DB container needs its own policy. Always-on at n=1 is
   simplest; the hibernation question returns at roughly n=20.
2. **Backup posture for tenant zero** — nightly `pg_dump` to object storage is
   the cheap answer. Worth doing from the first write, not the first customer:
   the object store *is* the business record.
3. **How much of our own GTM goes on the platform, and by when?** Tenant zero is
   only useful if it is real usage. Half-using it produces the same blind spots
   as not using it.
4. **Autonomy ceiling for our own outbound.** We are our own first blast radius.
   Recommend the same A1 draft→approve discipline we would sell — if we bypass
   it for ourselves, we learn nothing about whether the approval UX works.
5. **Billing model for a GTM product.** Metering platform cost is right for the
   platform and wrong for the buyer. Someone buying "an AI SDR" expects per-seat
   or per-meeting pricing. Separately, [D-01, D-02, D-03](../current/DEFECT-REGISTER.md)
   must be fixed before the first paying tenant — which tenant zero conveniently
   postpones but does not remove.
