# End-State Functional Roadmap — Audit Register (v1 → v2)

> **Document Type:** Quality audit of [HIREBUDDHA_ENDSTATE_FUNCTIONAL_ROADMAP.md](./HIREBUDDHA_ENDSTATE_FUNCTIONAL_ROADMAP.md)
> **Audit Date:** 2026-09-08
> **Sources audited against:**
> * `rough-outline/product_functional_documentation.md` (v3.0.3)
> * `rough-outline/product_technical_documentation.md` (v3.0.6)
> * `rough-outline/Unified Business Process & Agent Template Blueprint v2.md` (v2.3)
> * `rough-outline/skill-first-capability-model.md` (v0.1)
> * `../marketing-sales-automation.md` (2026-08-22 design brainstorm)
> * The owner's ad-hoc end-state feature directive (2026-09-08)
> **Result:** 42 findings — 11 Critical, 16 High, 15 Medium. All are resolved in roadmap **v2.0**.

---

## 0. How to read this register

Each finding carries a **class**:

* **GAP** — a capability required by a source document or the owner directive that the v1 roadmap omitted entirely.
* **CONFLICT** — the v1 roadmap states something that contradicts a settled decision in a source document, or contradicts itself.
* **AMBIGUITY** — present but under-specified to the point that two downstream teams would build different things.

Severity is judged by **downstream blast radius**: Critical = a wrong data model, a missing safety gate, or a missing subsystem that other epics silently assume; High = a whole feature family missing; Medium = precision defects that would surface in design review rather than in production.

---

## 1. Coverage of the owner's ad-hoc directive

Every item in the owner's list, mapped to its v1 status and its v2 home.

| # | Owner directive item | v1 status | v2 home |
|---|---|---|---|
| 1 | Exotel support | ✅ covered | Epic 8 · F8.1 |
| 2 | Signal bus and events | ✅ covered | Epic 9 |
| 3a | Per-tenant **relational** DB (not JSONB), predefined schema | ✅ covered | Epic 5 · F5.1 + F5.2 |
| 3b | API to interact with tenant data | ◐ named in one bullet only | Epic 5 · F5.5 (Tenant Data API) |
| 3c | **Runtime tool generation — persistence** | ❌ **GAP R-07** | Epic 5 · F5.6 · Epic 12 · F12.3 |
| 3d | Custom internal application development | ✅ covered | Epic 5 · F5.7 |
| 3e | Website development / hosting | ✅ covered | Epic 5 · F5.7 |
| 3f | Per-tenant containers | ✅ covered | Epic 5 · F5.7 |
| 3g | Storage limiting | ✅ covered | Epic 5 · F5.7 |
| 3h | File structure for artifacts + uploaded/mirrored docs | ◐ artifacts + mirrored only; **uploads missing** | Epic 5 · F5.8 |
| 4 | Move campaigns, leads, calling data to tenant DB | ✅ covered — but **CONFLICT R-05** on transcripts/memory | Epic 5 · F5.2 + F5.3 |
| 5 | Hierarchy Action→Skill→Agent→Process→Loop→**Graph** | ◐ present but **AMBIGUITY R-09** (Graph vs Loop federation) | Epic 3 · F3.1–F3.2 |
| 6 | Unified Business Process — restructure then develop | ✅ covered | Epic 4 |
| 7 | Ad-hoc tenant-requested initiatives (financial models, market research decks) | ✅ covered | Epic 4 · F4.4 |
| 8 | Pre-deployment brainstorming, visual, co-editable, 3D/digital twin, realtime | ◐ present but **AMBIGUITY R-10** (canvas ≠ twin?) | Epic 1 · F1.3 + Epic 2 · F2.1 |
| 9 | Multi-model: Gemini, Claude, OpenAI, GLM, Qwen, Kimi / Veo, Seedance, Wan / Gemini Image, GPT Image, Qwen Image, Kling | ✅ covered | Epic 7 · F7.1 |
| 10 | Intelligent routing | ✅ covered | Epic 7 · F7.3 |
| 11 | Meta Agent refinement | ✅ covered | Epic 12 · F12.2 |
| 12 | Learning system / CORTEX refinements | ◐ learning ✅; **memory model is stale — GAP R-19** | Epic 11 + Epic 12 · F12.1 |
| 13 | Per-tenant knowledge graph + procedural intelligence, editable, doc-traceable | ✅ covered | Epic 11 · F11.1 / F11.6 |
| 14 | **Pragya control layer (Backend API MCP / Tenant API MCP / UI MCP or better)** | ❌ **GAP R-01** | Epic 1 · F1.2 |
| 15 | Generative UI + isometric 3D twin, 6-level traversal, conversational analytics drill-down | ✅ covered | Epic 2 |
| 16 | Tenant knowledge/memory/document/asset explorer | ✅ covered | Epic 11 · F11.2 |
| 17 | Own models — BabyBuddha, OmniBuddha | ◐ present but **CONFLICT R-13** (framing) | Epic 7 · F7.2 |
| 18 | Self-evolving / self-improving code | ◐ present but **GAP R-24** (no independent-suite rule) | Epic 12 · F12.3 / F12.4 |

---

## 2. Critical findings

### R-01 · GAP · Pragya has no control plane
**Finding.** The owner directive is explicit: *"Pragya will be the only interface a human user has with the system. Hence all functionality should be accessible and executable through Pragya"*, and names candidate mechanics (Backend API MCP, Tenant API MCP, UI MCP, or a better approach). v1 Feature 1.1 asserts *"Full Natural Language System Command"* but the document nowhere describes **how** Pragya reaches the platform. Without this, "everything through Pragya" is an aspiration with no surface area, and downstream teams cannot scope it.
**Resolution (v2).** New **Feature 1.2 — The Pragya Control Plane**: three declared control surfaces (Platform Control Surface, Tenant Data & Workspace Surface, Interface Control Surface), each a governed, capability-scoped, audited tool surface; every Pragya action is an ordinary governed run subject to the PolicyGate; a completeness rule stating that no platform capability may ship without a control-plane verb. The transport (MCP vs. internal tool registry) is named as an implementation choice, not a functional requirement.

### R-02 · GAP · No integrations / connector epic
**Finding.** Functional §6.6 defines ~20 third-party integration domains (banking, payouts, tax, e-signature, KYB/AML, Slack/Teams cards, Jira/Linear, enrichment, calendar, HRIS, inventory, knowledge sources, enterprise systems); technical §21 defines system-of-record semantics; the marketing brainstorm settles **MCP-first before hand-built connectors**. v1 mentions integrations only in passing (Stage 7 of the engagement flow). An entire subsystem the Sheel processes depend on was unrepresented.
**Resolution (v2).** New **Epic 6 — Integrations, Connector Fabric & Systems of Record**, with the integration catalog, MCP-first strategy, per-object mastering, mirror/write-back semantics, conflict handling, and ownership migration.

### R-03 · GAP · The 27 canonical business objects are absent
**Finding.** Blueprint §3.2 defines the Canonical Business Object Model — 27 objects and the lifecycle chain `Signal → Lead → Opportunity → Quote → Contract → Order → Project → Invoice → Payment → Ledger Entry` with `Ticket`/`Risk`/`Incident` attachable anywhere. This chain **is** the "one memory, no seams" claim; without it the claim is rhetorical. v1 named the HBS modules but never the objects or the graph.
**Resolution (v2).** **Feature 5.1** enumerates the 27 objects by domain and states the lifecycle chain and the typed-link requirement.

### R-04 · GAP · No write-ownership / record-service model
**Finding.** Technical §23.1–§23.2 settles: one owning Process per object type, all writes through a single record service, non-owners emit `object.change_proposed`, compare-and-set versioning, `object.write_conflict` signals, and a HITL-gated cross-owner escape hatch. This is what makes segregation of duties **structural** rather than advisory. v1 had none of it, while simultaneously claiming SoD in Epic 11.
**Resolution (v2).** **Feature 5.4 — Single Write Path, Object Ownership & Conflict Handling**, cross-referenced from the SoD feature.

### R-05 · CONFLICT · Tenant DB vs. control plane data placement
**Finding.** v1 Feature 5.1 states conversational transcripts and telephony recordings *"are stored directly within the tenant's database"*. Technical §10.4–§10.5 (decision v3.0.6) settles the opposite for memory-adjacent data: **the knowledge base, CORTEX memory, episodic history and conversation logs stay control-plane permanent** (hot path of every run, hibernation, and vector-index footprint), with the export bundle reuniting both stores. v1 also never states where signals, runs, billing, or registries live — leaving Epic 9 and Epic 11 implicitly contradicting Epic 5.
**Resolution (v2).** **Feature 5.3 — The Data Placement Contract**: an explicit two-column table (control plane vs. tenant data plane), the rationale, and the rule that the export bundle spans both. Campaigns, leads, and calling *records* move to the tenant DB per the owner directive; call *transcripts and memory* are indexed control-plane with the tenant DB holding the business record and the artifact pointers.

### R-06 · CONFLICT · A4 autonomy loses its defining meaning
**Finding.** Blueprint §9.2 defines **A4 = Self-modify**: "A3 + may accept self-evolved code/instruction changes affecting itself (still test-gated + HITL for high impact)". v1 redefines A4 as "Fully Autonomous (self-monitors, self-optimizes, reports aggregated outcomes)" — which is indistinguishable from A3 and, critically, **deletes the only gate that governs which entities may accept self-evolved code**. Epic 10 (self-evolving code) then has no autonomy predicate at all.
**Resolution (v2).** A4 restored to its blueprint definition in **Feature 14.1**, and Epic 12 self-evolution explicitly predicated on it.

### R-07 · GAP · Runtime-generated capability persistence
**Finding.** The owner directive asks for *"runtime Tools generation persistence"*. v1 Feature 10.3 generates tools at runtime and v1 Feature 3.6 materializes skill assets, but nothing states that generated tools/skills are **durable, tenant-scoped, versioned records that survive container recycling and are re-materialized on demand**. Without this the self-evolution story regenerates the same tool forever.
**Resolution (v2).** **Feature 5.6 — Runtime-Generated Capability Persistence** (durable registry, content-hashed assets, warm re-materialization, portable in the export bundle), referenced from Epic 12.

### R-08 · GAP · No world-facing threat model
**Finding.** Blueprint §9.5 is a full threat model for the outward face: counterparty content is data-never-instruction, social-engineering resistance with out-of-band counterparty verification, impersonation/fraud gates, information-boundary enforcement via memory viewports, and abuse/jailbreak handling. v1's Karuna feature (7.4) covers only DNC, AI disclosure, and human handoff. For a platform whose agents transact money with strangers, this is the single most consequential omission.
**Resolution (v2).** **Feature 8.5 — The Karuna Profile** (mandatory, deploy-time-enforced overlay) and **Feature 14.5 — World-Facing Threat Model & Counterparty Verification**.

### R-09 · AMBIGUITY · GRAPH tier vs. LOOP federation
**Finding.** The owner directive adds a **GRAPH** tier above LOOP. The source docs instead legalize **LOOP-parents-LOOP federation** (blueprint §13, technical §17.6) with a root-Loop uniqueness constraint. v1 introduces GRAPH without saying whether it replaces federation, wraps it, or is a view over it — and simultaneously keeps the federated/holding language in Epic 3.1. Two teams would build two different things.
**Resolution (v2).** **Feature 3.2** settles it: GRAPH is a **first-class entity tier** that owns one or more Loops; federation semantics (memory down, KPIs up, never sideways; per-Loop residency and allow-lists; root-Loop uniqueness *within a Graph*) are attached to the Graph tier; the three topologies (single, federated, holding) are restated against it.

### R-10 · AMBIGUITY · Is the brainstorming canvas the digital twin?
**Finding.** The owner directive asks for pre-deployment co-creation *"through some sort of a 3D workflow or the same digital twin feature"*. v1 has a Brainstorming Studio (1.2) and a Digital Twin (2.1) as unconnected features; the Epic 1 sequence diagram calls the canvas "3D Digital Twin Canvas", implying they are one thing, but no text says so.
**Resolution (v2).** **Feature 2.1** states the twin has two modes — **Live Mode** (operating reality) and **Design Mode** (proposed, editable, simulatable) — and **Feature 1.3** binds the brainstorming studio to Design Mode of the same twin, with the same six levels of traversal.

### R-11 · GAP · No privacy, data-protection or regulatory compliance map
**Finding.** Blueprint §9.6 wires baseline obligations into named Processes (AI disclosure, DNC/TCPA, CAN-SPAM/GDPR consent, GDPR/DPDP with DSAR and retention and breach notification, financial SoD/e-invoicing, employment, sector packs). Agent AGT-072 (Privacy & DSAR) and checkpoint `before_bulk_data_deletion` exist in the source. v1 mentions DNC and AI disclosure only. **DSAR, retention, lawful basis, breach notification, and jurisdiction packs are absent from the entire document** — while Epic 5 simultaneously promises to store every customer record and call recording.
**Resolution (v2).** **Feature 14.6 — Regulatory Compliance Map & Jurisdiction Packs** and **Feature 14.7 — Privacy, Consent, Retention & DSAR**.

---

## 3. High findings

### R-12 · GAP · Outbound compliance and deliverability layer
Consent & suppression service, per-channel/per-tenant send windows and rate limits, sender identity and domain warmup, outbound idempotency keys, a **deterministic** sequence/enrollment engine (the marketing brainstorm's rule: *never let the LLM decide "is it time for step 3"*), dry-run/preview, and identity resolution/dedupe are all absent from v1's three outbound bullets. Deliverability is named in the source as the **#1 non-obvious blocker** for outbound.
**→ v2 Features 8.3, 8.4.**

### R-13 · CONFLICT · BabyBuddha / OmniBuddha framing
Blueprint §0.3 (decision B15) and functional §3.1 settle both as **post-trained open-weight** models built on a leading open-weight base, differentiated by agentic post-training — explicitly *not* from-scratch proprietary pretrains — and gated behind beating incumbents on the eval harness before the router admits them. v1 calls them "Proprietary Foundational Models" with no admission gate, which overstates the claim and drops the gate.
**→ v2 Feature 7.2** (framing corrected, admission gate added and cross-linked to Feature 12.6).

### R-14 · GAP · The independent-suite rule for self-modification
Technical §22.2 is explicit: a self-modified artifact may **never** be promoted on self-generated tests alone — promotion requires the incumbent's golden suite (captured before modification), platform curated suites, then self-generated tests as *additional* coverage only, plus a mandatory red-team step. v1's Epic 10 has the Meta Agent generate its own tests and then promote on them — the exact circularity the source forbids. v1 also omits canary rollout with automatic SLO rollback (§22.3) and the model-change non-inferiority policy (§22.4).
**→ v2 Features 12.5 and 12.6.**

### R-15 · CONFLICT · Authority matrix values contradict the blueprint
v1 Feature 11.2 gives "maximum supplier payout: $1,000"; blueprint §9.3 sets outbound payment autonomous **up to $500**, HITL above $500, **hard block above $10,000 (dual human approval)**. v1 also drops the third column (hard block) entirely, and omits five of the ten action categories (contract execution, employment offer, public statement, regulatory filing, vendor creation, data deletion, price change).
**→ v2 Feature 14.2** reproduces the full three-column matrix verbatim.

### R-16 · GAP · The 18 HITL checkpoints are never enumerated
v1 references "18 Mandatory HITL Checkpoints" inside a diagram box only. The catalog is a build artifact (a seeded `hitl_checkpoint_defs` registry) and must be enumerated. Additionally "Mandatory" is inaccurate: the source distinguishes tenant-tunable thresholds from `platform_mandatory` checkpoints that cannot be removed.
**→ v2 Feature 14.3** enumerates all 18 and marks the platform-mandatory subset.

### R-17 · GAP · Segregation of duties is missing two of five rules
v1 lists three SoD rules. Blueprint §9.4 has five: the three v1 has, plus **auditor independence** (read-only actions, separate budget, reporting through Pragya to the owner, never parented by an audited Process) and **self-modification quarantine** (no agent may promote code changes to itself). The latter is the structural control behind Epic 10 — omitting it while shipping self-evolving code is a live safety gap.
**→ v2 Feature 14.4.**

### R-18 · GAP · No human operating model
Blueprint §11 defines the residual human organization: Goal-Setter, **Judgment Desk**, Relationship Principals, Quality & Ethics Steward, Domain Experts; the RACI; and the shadow→sample transition. v1 has HITL cards but no owner for them, no escalation-on-no-answer path, and no notion of who ratifies autonomy promotions.
**→ v2 Epic 13 · Features 13.1, 13.2.**

### R-19 · GAP · The memory model is the superseded Phase-1 model
v1 Feature 9.2 describes the four *tiers* (working / episodic / semantic / CORTEX tree). The shipped and target CORTEX v2 model is four **typed domains** — Knowledge, Episodic, **Experience**, **Intelligence** — each with an explicit scope (tenant-shared vs. per-entity vs. inheritable-downward), plus tier write rules (a Skill's lesson lands on the Skill, not its caller), Dreaming promotion along `parent_id`, and federation isolation (technical §24.1–§24.2). Experience and Intelligence are precisely the domains that make the learning system work, and v1 omits both. v1 also keeps the superseded retrieval stack (plain vector search) instead of the settled hybrid lexical+semantic RRF retrieval with structure-aware chunking, schema-aware filters and reranking (§24.4).
**→ v2 Features 11.3, 11.4, 11.5.**

### R-20 · GAP · No resilience, degradation or continuity model
Blueprint §12: the five-rung degradation ladder (provider outage → tool failure → channel outage → budget exhaustion → systemic anomaly), the loop-level kill-switch reachable by one sentence to Pragya, backup/DR posture, and suspend/resume recovery. v1 has vendor failover only.
**→ v2 Features 13.3, 13.4.**

### R-21 · GAP · No scheduling / Chronos feature
"Every Monday 9am" is table stakes and is called out in the marketing brainstorm as absent and small. v1 mentions "Chronos Scheduled Events" inside one diagram and never as a feature. The Loop heartbeat, envelope refresh, parked-signal sweeps and recurring processes all depend on it.
**→ v2 Feature 9.3.**

### R-22 · GAP · No platform administration, tenancy or partner tier
Functional §15.1 defines a four-level hierarchy — App Admins, **Partners** (portfolio management, pricing multipliers, commissions, white-label), Tenants, Users — and the platform registries admins own (model fleet and router policy, global tool registry, SKU base costs). v1 addresses only the tenant. Partner white-labeling is also load-bearing in the billing formula (`Partner Fee %`), which v1 reproduces without ever introducing partners.
**→ v2 Epic 15.**

### R-23 · GAP · No user-facing observability
v1 has a micro-cent ledger and a signal audit ledger but no run traces, no step-level execution timeline, and no *"what did my digital workforce do today"* activity feed — named in the source as driving retention more than any single feature.
**→ v2 Feature 2.5.**

### R-24 · GAP · No KPI tree or agent SLOs
Blueprint §10.2 defines three levels: Loop KPIs (owner dashboard, including loop-health measures — signal coverage %, HITL backlog age, autonomy distribution, cost-per-outcome trend), Process KPIs, and **per-agent SLOs** (task success, escalation rate, HITL edit rate, complaint rate, latency, cost per completed task, critic-block rate). Those SLOs are the evidence base for autonomy promotion (§9.7) and for canary rollback — v1 promises evidence-based promotion with no defined evidence.
**→ v2 Feature 14.9.**

### R-25 · GAP · Wallet holds and graceful exhaustion
Technical §23.3: admission-time holds against available balance (closing the concurrent-run oversubscription race), top-up at 80% consumption, and the mid-run exhaustion rule — **the run completes its current step cleanly (a live call is never dropped mid-sentence)**, then suspends with bounded debt capped at max($1, 5% of hold). This is user-visible behaviour, not implementation detail. Absent from v1.
**→ v2 Feature 14.8.**

### R-26 · CONFLICT · Packs vs. starter bundles
Blueprint §14 / functional §2.1 define **both** the Wave-0 Solo Pack *and* seven starter bundles (Growth, Customer Success, Operational Fulfillment, Fiscal Optimizer, Regulatory & Compliance, Talent Vitality, Self-Optimizing Intelligence) as the *expansion units* covering all 19 processes exactly once. v1 replaced the bundles with MSME/Startup/Enterprise packs and dropped the bundles entirely, leaving no defined expansion path between Solo and Enterprise and no mapping that proves all 19 processes are covered.
**→ v2 Feature 4.2** carries both: packs are the commercial SKUs, bundles are the functional activation units, with the bundle→process mapping table.

### R-27 · GAP · Entity registry not referenced
Blueprint §7 enumerates 1 Loop · 19 Processes · **100 Agents** · **62 Skills** · **37 Actions**, with stable template IDs. This registry is the direct input to seeding work. v1 mentions "12 agents" for the Solo Pack and nothing else.
**→ v2 Feature 4.5** states the registry as a required deliverable with its counts and ID scheme, and Feature 3.5 states the primitive/skill split against the 37-action catalog.

---

## 4. Medium findings

| ID | Class | Finding | v2 resolution |
|---|---|---|---|
| R-28 | GAP | **Tool-vs-skill decision rule missing.** Epic 3 prunes to ~20 primitives while Epic 10 synthesizes new *tools* at runtime — with no stated rule for which a new capability becomes. Skill-first §4 gives the rule: a capability stays a tool when money/metered side effects, credentials, latency, or a narrow stable contract are involved; everything workflow-shaped becomes a Skill. | F3.6 |
| R-29 | GAP | **Uploads directory missing** from the workspace file structure (artifacts and mirrored docs were named; the owner directive names uploads too). | F5.8 |
| R-30 | AMBIGUITY | **Runtime package-installation ban vs. app/website hosting.** F3.7's ban is scoped to skill execution, but Epic 5 hosts tenant-built applications that plainly need dependencies. Unscoped, the two features contradict. | F3.8 + F5.7 (build-time vs. run-time boundary stated) |
| R-31 | GAP | **Schema evolution has no governance.** v1 says the schema "automatically expands"; the source requires additive-only evolution, field lifecycle `active→deprecated→hidden`, alias-based renames, no in-place type changes, def versioning, and auto-or-HITL application. | F5.2 |
| R-32 | GAP | **Signal delivery semantics** — at-least-once with idempotent consumption, `dedupe_key`, best-effort per-tenant FIFO with no global ordering, immutable replay-by-clone, park/escalate/dead terminal states, and the trust taint hook restricting high-impact tool categories on counterparty-trust runs. v1 asserted "zero dropped signals" without the machinery that makes it auditable. | F9.2 |
| R-33 | GAP | **Content review queue with edit.** HITL today is approve-or-reject on a step; operators need approve / **edit** / reject, batched, before anything ships. | F2.4 |
| R-34 | GAP | **Evidence store / immutable compliance archival** (SKL-X03 / ACT-35) — required by Guardrails and Internal Audit. | F14.7 |
| R-35 | GAP | **Tenant users, roles and permissions.** v1 speaks only of "the owner"; the source has a Users level and role-scoped access. | F15.2 |
| R-36 | GAP | **Tenant timezone and working hours** as first-class tenant configuration (currently hardcoded IST in code; `companies` has no timezone column). Everything about scheduling, send windows and calling hours depends on it. | F15.3 |
| R-37 | GAP | **Karuna Gateway Agents** (voice, email, messaging, chat, social) as registered standing entities, and the deploy-time rule *no agent without the Karuna Profile may hold a world-facing channel binding*. v1 described Karuna as a membrane with no entities and no enforcement point. | F8.5 |
| R-38 | GAP | **Inward-auth hardening details** — enrolled channel bindings via verified handshake, channel identity as hint-never-proof, session elevation with expiry, lockout-and-alert on repeated failed step-ups, and **Pragya can never satisfy her own checkpoint**. v1 had the T0–T3 tiers but none of the surrounding controls. | F1.5 |
| R-39 | AMBIGUITY | **Process definitions are name-only.** The 19 processes are listed but carry no trigger subscriptions, read/write objects, or starting autonomy — all three of which the source specifies per process and all three of which downstream seeding needs. | F4.3 (table restored) |
| R-40 | GAP | **Executor modes per tier** (Process: DAG / parallel / debate; Agent: dialog / single-step; Skill: tool-burst) — referenced in the source hierarchy, absent from v1. | F3.1 |
| R-41 | GAP | **Wallet consumption priority** (daily free → PAYG → subscription) and the partner/platform fee structure in the billing formula. v1 listed the three pools without the priority that determines what a tenant is actually charged. | F14.8 |
| R-42 | GAP | **No document, content or creative production epic.** Functional §6.3–§6.4 define the document/spreadsheet/deck factory, OCR and extraction, and image and video generation; the marketing brainstorm names asset repurposing as the highest return-per-token operation on the platform and a brand critic wired into the critic pipeline as the highest-leverage single quality lever. v1 referenced document output only obliquely, inside the ad-hoc feature. Since most of what a business actually *ships* is a document, a deck or a piece of media, this warranted its own epic. | **Epic 10** (F10.1–F10.4) |

---

## 5. Verified-clean areas

The following were checked and found correct, complete and internally consistent in v1; they are carried into v2 unchanged or lightly edited:

* The 19 canonical processes — names, IDs, and domain grouping all reconcile with blueprint §5, and the mermaid grouping sums to exactly 19.
* The Solo Pack agent count (Pragya + 12) matches blueprint §14 Wave 0 exactly.
* The 8-stage AgentLoop, including the three-consecutive-block pre-critic circuit breaker and the four decide states.
* The skill-first model — two-tier primitives/skills split, progressive disclosure, DB-backed skill entities, immutable version snapshots with provenance on runs, on-demand workspace materialization at `/workspace/.skills/<slug>/<version>/`, the code-security invariant, sandbox metering with per-skill cost envelopes, and the autonomous skill-promotion loop. This is the most faithfully transcribed section of v1.
* The nine-stage Pragya engagement flow.
* The model fleet coverage — every model named in the owner directive appears, including Kimi, Wan and Seedance.
* The three-tier semantic-zoom / six-level digital-twin traversal.
* The budget hierarchy with protected reserves for P14/P17, including the correct framing that "never paused" means pre-funded carve-out rather than exemption.

---

## 6. Structural recommendations applied in v2

1. **Stable feature IDs.** Every feature is `F<epic>.<n>` and epics are numbered — so downstream documents, tickets and tests can cite them and so a later audit can diff coverage mechanically.
2. **A source-traceability column** on the epic overview, naming which source document and section each epic derives from. This is what lets the next revision detect drift instead of re-auditing from scratch.
3. **An explicit non-goals section.** v1 had no boundary statement; several findings above exist because a reader could not tell whether something was omitted deliberately.
4. **A glossary.** Pragya / Sheel / Karuna / Loop / Graph / arc / bundle / pack / envelope / hold / viewport / domain are all used as terms of art across four source documents with slight variations.
5. **Open decisions carried forward, not silently dropped.** v1 read as fully settled; several genuinely open questions (skill-selection accuracy at high skill counts, tenant-DB hibernation thresholds, buyer-facing pricing model, taint tracking depth) belong on the face of the document.

---

*Audit performed against the four rough-outline source documents, the marketing/sales design brainstorm, and the owner's 2026-09-08 ad-hoc directive. All 42 findings are closed in [HIREBUDDHA_ENDSTATE_FUNCTIONAL_ROADMAP.md](./HIREBUDDHA_ENDSTATE_FUNCTIONAL_ROADMAP.md) v2.0.*
