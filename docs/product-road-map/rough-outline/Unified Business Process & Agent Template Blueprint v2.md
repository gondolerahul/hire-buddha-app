# HireBuddha — Sheel
## The Unified, AI-Native Business Blueprint & Agent Template Library — **Version 2**
### Pragya · Sheel · Karuna — the wisdom, the discipline, and the compassion of an awakened business

> **Document Class:** Business Architecture & Transformation Blueprint
> **Author:** Buddha Cognitive Lab
> **Target Platform Version:** 3.0.0 (road-map target state)
> **Blueprint Version:** 2.3 — v2.1 applied the §0.3 errata; v2.2 added the Wave-0 Solo Pack (§14), legalized LOOP federation (§13), and linked the SoR/inward-auth designs; v2.3 links the owner directives (predefined HBS as the canonical objects' full expansion, the nine-stage Pragya flow); v2.0 superseded "Unified Business Process & Agent Template Blueprint" (v1)
> **Last Updated:** July 2026
> **Status:** Definitive Reference — **Target-State Blueprint.** Deployability is gated on the platform road map: the shipped platform has no `LOOP` tier, signal contract, or governance schema yet (§0.3 Reality Baseline).
> **Companion Docs:** [product_functional_documentation.md](./product_functional_documentation.md) · [product_technical_documentation.md](./product_technical_documentation.md)

---

## 0. What Changed in Version 2 — The Audit Register

Version 1 established the right doctrine: **one loop, not seven silos**, turning through six arcs around the Pragya axle, facing the world through Karuna. That doctrine is fully retained. But an audit against the functional and technical documentation found the v1 blueprint incomplete in ways that would surface immediately in a real deployment. Version 2 closes every finding below.

### 0.1 Gap Register (v1 findings → v2 resolution)

| # | Severity | v1 Gap | v2 Resolution |
|---|---|---|---|
| G1 | **Critical** | **The hierarchical entity registry enumerated only 2 of 5 tiers.** §10.1 listed one Loop and ten Processes; Agents appeared only as templates, Skills only as prose mentions, Actions not at all — despite the platform's composition rule (Actions→Skills→Agents→Processes→Loop). | §7 provides the **complete five-tier registry**: 1 Loop, 19 Processes, 100 Agents (each with parent Process and arc), a 62-entry Skill library, and the full 37-entry Action→Tool catalog (31 in v2.0, +6 in v2.1 — §0.3) mapped to the platform's registered tools. |
| G2 | **Critical** | **Named entities were internally inconsistent.** §4 named Processes (Plan-to-Done, Invoice-to-Collected, Hire-to-Retire, Source-to-Pay *and* Procure-to-Pay, Verify-&-Sign-off, Source-to-Stock…) and Agents (Offer & Negotiation Agent, Interview Scheduler, Experiment Designer, Internal Audit Agent, Benefits & Time-off Agent, Dependency Resolver, Vendor Risk Agent…) that never appeared in the §8 template library or §10 registry. | §5 reconciles and de-duplicates the Process set into 19 canonical end-to-end Processes *(count corrected in v2.1 — this cell previously said 18)* with explicit absorption notes; §8 template library now contains **every** Agent named anywhere in the document. |
| G3 | **Critical** | **Karuna had no entity realization.** Pragya is a real Agent (with a UUID in `loop_config.hub_agent`); Karuna was pure metaphor — no tier, no config, no enforcement. A named pillar of the architecture was undeployable. | §2.3 formalizes Karuna as the **Karuna Gateway**: a mandatory governance-and-persona profile plus channel-gateway Agents through which *every* world-facing interaction passes. Deployable, auditable, enforceable. |
| G4 | **High** | **Whole business functions were missing** from the "No Function Left Behind" convergence: PR & Corporate Communications, Investor Relations & Fundraising, Corporate Development / M&A, Partnerships & Channel, Product Management (distinct from R&D), Pricing & Monetization, Information Security (distinct from IT), Data Privacy / DPO, Facilities & Physical Assets, ESG / Sustainability, Customer Education & Enablement, Community Management, Data & Analytics Engineering, Insurance & Corporate Secretarial, Incident / Crisis Management, and **Offboarding** (the "Retire" in Hire-to-Retire). | §4 master map extended to 39 functions; new Processes (Incident-to-Resolution, Partner-to-Revenue, Record-to-Report, Idea-to-Launch) and ~20 new Agent templates added. |
| G5 | **High** | **"No seams" was asserted but never specified.** Nothing defined *how* a PERCEIVE signal actually reaches ENGAGE: no event taxonomy, no trigger registry, no shared business-object model. The seam was removed rhetorically, not architecturally. | §3.2 defines the **Canonical Business Object Model** (the seed of the dynamic per-tenant schema) and §3.3 the **Signal & Trigger Contract** — the actual mechanics of seamlessness. |
| G6 | **High** | **Governance was thin.** Five HITL checkpoints for an entire enterprise; no autonomy levels, no authority matrix by value band, no **segregation of duties** (v1's design let one agent both create a vendor and pay it), no external threat model (prompt injection, social engineering of agents, counterparty fraud), no AI-disclosure, telemarketing (DNC/TCPA), consent-to-record, or data-protection compliance treatment. | §9 provides the full **Governance & Trust Architecture**: A0–A4 autonomy ladder, authority matrix, SoD rules, 18-checkpoint HITL catalog, world-facing threat model, and a regulatory compliance map. |
| G7 | **High** | **Economics didn't survive contact with a perpetual loop.** A never-terminating Loop carried a single `max_cost_usd: 500` with no budget hierarchy, no per-arc/per-Process allocation, no cost-per-outcome KPIs, and no reconciliation with the platform's wallet thresholds. | §10 defines the **budget hierarchy** (Loop → Process → Agent envelopes, refreshed on cycle), unit-economics KPIs, and the three-level **KPI tree** with targets and agent SLOs. |
| G8 | **Medium** | **The human operating model was one sentence** ("humans move up the stack"). No residual org design, no exception-handling roles, no RACI, no change management or reskilling path. | §11 defines the **Human Operating Model**: the five residual human roles, the RACI against the six arcs, and the transition plan. |
| G9 | **Medium** | **No failure modes.** Nothing on degradation, business continuity, provider outage, loop-wide circuit breakers, data portability, or exit. | §12 Resilience & Continuity: degradation ladder, DR posture, kill-switches, and exit/portability guarantees. |
| G10 | **Medium** | **Single-company assumption.** No answer for business units, subsidiaries, brands, or regions — one Sheel or many? | §13 Scaling Topologies: single-Sheel, federated Sheels (Loop-parents-Loop via `parent_id`), and holding-company patterns. |
| G11 | **Medium** | **The roadmap had phases but no risk logic.** No autonomy maturity ladder, no risk-tiered sequencing of which processes to automate first. | §14 Roadmap v2: the A0–A4 ladder applied per Process, with risk-tiered adoption sequencing. |
| G12 | **Low** | **Deployment JSON was under-specified**: no `identity`, `observability`, or `planning` blocks; KPIs without definitions or targets; `timeout_ms: 0` unexplained; no escalation policy; conceptual tension between Arc III (Orchestrate) and the axle left unresolved. | §15 Deployment Config v2; §2.4 resolves the Orchestrate/axle distinction explicitly. |

### 0.2 What Did *Not* Change
The one-loop doctrine, the six arcs, the Pragya/Sheel/Karuna trinity and its Buddhist grounding, the three planes, and the transformation-by-deployment philosophy are all retained from v1 — they were conceptually correct. Version 2 makes them **complete, consistent, and deployable**.

### 0.3 Version 2.1 Errata & Reality Baseline (2026-07-18)

An external audit ([roadmap_gap_register.md](./roadmap_gap_register.md)) found defects that survived the v2 audit, and a codebase baseline ([codebase_current_state_analysis.md](./codebase_current_state_analysis.md)) established what the platform actually ships today. v2.1 applies the mechanical corrections; the design-level gaps (register B/C/D items — signal-contract mechanics, object relationships, governance schema, SoD credential scoping, etc.) remain open for the next revision.

| Fix | Register ID | Change |
|---|---|---|
| Process count | A1 | §0.1 G2 said 18 canonical Processes; the canon is **19** (P01–P19). |
| Object count + missing objects | A2, A3 | The Canonical Business Object Model claimed 24 but listed 25, and **Product/SKU** and **Evidence** (declared by P16 / P14 / P17) were missing entirely. The model now has **27 objects**. |
| Unresolvable tool bindings | A5 | Six Actions added (ACT-32…ACT-37: tenant data query, OCR, translation, evidence store, social post/listen, alerting) backed by new functional-doc §6.6 rows; §8 templates re-bound to registered Actions; "pgvector" bindings restated as platform semantic-memory retrieval. |
| Knowledge Curator home | A10 | Registered exactly once: AGT-034 under P06 (arc II); axle-side tenant-KB ingestion belongs to Pragya alone (§4.1 row updated). |
| Loop-scope circuit breaker | A11 | §15 `logic_gate` now defines a **process-scoped** breaker that quarantines the offender and raises an incident — it never halts Sheel. |
| One Loop, seven bundles | A4 *(decision)* | Sheel is the **only** Loop instance per tenant. The functional doc's former "7 shipped Loops" are now **7 starter bundles** — packaging views over P01–P19 (functional doc §2.1). |
| BabyBuddha / OmniBuddha framing | B15 *(decision)* | Both are **post-trained open-weight** flagship models (road map), not from-scratch proprietary pretrains (functional doc §3.1 / §8.1). |

**Reality baseline:** the shipped platform implements 4 of the 5 tiers (no `LOOP` value in the entity enum), none of the Phase-2 schema this blueprint relies on (no signal envelope/trigger registry, no autonomy-level fields, no SoD enforcement, no budget hierarchy), and no Pragya or Karuna entities. This blueprint is therefore a **target-state design**: §3.2–§3.3 and §9–§10 specify platform mechanics that must be built before any Process here can deploy (register B1–B5).

---

## 1. The Thesis: One Loop, Not Seven Silos (Retained)

A *digitized* business puts software between its departments. An **AI-Native** business **dissolves the departments**. Work does not move from one team's queue to another's; it flows through one continuous cognitive loop in which:

* **There is one brain.** Every function reasons on the same Intelligence Engine — BabyBuddha + the frontier fleet + the Intelligent Model Router (functional doc §3).
* **There is one memory.** Every interaction, document, decision, and outcome lands in one shared cognitive fabric: CORTEX + Episodic + Semantic memory + the dynamic per-tenant schema (functional doc §9, §13).
* **There is one inward face.** The owner talks to **Pragya** (functional doc §4) — never "logs into the CRM and then the accounting tool."
* **There is one outward face.** Every customer, prospect, candidate, vendor, and regulator meets the business through **Karuna** (§2.3) — empathetic, omnichannel, governed.
* **There is one nervous system that learns.** The Learning System (functional doc §10) feeds every outcome back into every future decision.
* **It builds itself.** The Meta Agent (functional doc §5) constructs missing Employees and Tools; self-evolving code (functional doc §12) keeps them working.

**The seam is where businesses leak money, time, and trust.** The seam table from v1 (Marketing→Sales, Sales→Delivery, Delivery→Support, Support→Finance, Finance→Legal, Everything→Strategy) remains the canonical statement of the problem. Version 2 adds what v1 lacked: the *mechanics* that make seamlessness real (§3.2–§3.3) rather than asserted.

---

## 2. The Trinity, Formalized

### 2.1 Sheel Is One Loop-Tier Entity
In HireBuddha's five-tier hierarchy (**Action → Skill → Agent → Process → Loop** — the `LOOP` tier is ⬜ road map; 4 tiers ship today), Sheel is **one instance of the `LOOP` tier** scoping the entire enterprise: it owns all Processes, persists across all of them, holds company-level goals and KPIs in `loop_config`, and never terminates. (Multi-entity companies: see §13.)

> **v2.1 (gap A4 decision):** Sheel is the **only** Loop instance a tenant deploys. The functional doc's former "7 shipped Loops" are **7 starter bundles** — named packaging views over P01–P19 used for onboarding and reporting (mapping table in functional doc §2.1) — not sibling Loop entities. *(v2.2: precisely, Sheel is the only **root** Loop — in federated topologies, child Loops for business units federate beneath it; §13, technical doc §17.6.)*
>
> **Design pointer (2026-07-18):** the Loop *runtime* — heartbeat scheduler, CORTEX-backed state, watchdog, and the no-run billing model — is now specified in technical doc §17.

```
            LOOP   →   Sheel  (the whole company, one self-running entity)
              │
           PROCESS →   19 canonical end-to-end Processes (§5)
              │
            AGENT  →   100 registered Agents (§7.3), incl. Pragya (hub) & Karuna gateways
              │
            SKILL  →   62-entry Skill library (§7.4)
              │
           ACTION  →   thin wrappers around the registered Tool catalog (§7.5)
```

### 2.2 Pragya — The Inward Face (Retained, Clarified)
Pragya is a real, deployed Agent-tier entity (functional doc §4, technical doc §11): the tenant's account manager and single point of contact, reachable by Meetings, phone, WhatsApp, Slack, Teams, and email, holding continuous cross-channel context. In Sheel she is registered as `loop_config.hub_agent`. **Pragya is not a peer of the workforce; she is the axle's voice.** She onboards, connects systems, relays goals to the Meta Agent, assigns work, surfaces HITL checkpoints, and reports status.

### 2.3 Karuna — The Outward Face, Now Deployable (New in v2)
v1 described Karuna as "the rim" — a metaphor with no entity behind it. v2 formalizes Karuna as two enforceable constructs:

**(a) The Karuna Profile — a mandatory governance-and-persona overlay.**
A named configuration block (carried in each entity's `identity` + `governance` JSON) that **must** be attached to every Agent that communicates with any external party. It enforces:

* **Empathy floor & tone bounds** — Personality Matrix minimums (Empathy ≥ 0.6, configured tone range) for world-facing conversation.
* **Disclosure** — the agent identifies itself as an AI assistant of the business where law or policy requires (§9.6).
* **Language & channel courtesy** — respond in the counterparty's language (Translation & Localization Skill auto-invoked); respect contact-time windows and channel preferences.
* **Outbound compliance gates** — DNC/consent list check before dialing/messaging; consent-to-record prompts on calls; unsubscribe honoring on email/WhatsApp.
* **External threat posture** — the world-facing prompt-injection and social-engineering defenses of §9.5 are active by default.
* **Escalation courtesy** — a guaranteed, always-available path to a human on counterparty request.

**(b) Karuna Gateway Agents — the channel front door.**
Per channel (voice, WhatsApp, email, chat, social), a standing gateway Agent authenticates/identifies the counterparty, classifies intent, applies the threat posture, and routes into the right Process **with the signal contract of §3.3** — so an inbound call, a support email, and a vendor WhatsApp all enter the loop through one governed membrane. Gateways are registered Agent-tier entities (§7.3, KAR-01…KAR-05).

> **Rule:** *No Agent without the Karuna Profile may hold a world-facing channel binding.* This is enforced as a platform governance check at deploy time.

### 2.4 Resolving the Orchestrate/Axle Tension (New in v2)
v1's wheel diagram placed Arc III (Orchestrate, "Meta-cog") on the rim while describing axle-like duties, leaving ambiguity. The v2 rule:

* **The axle decides *how the system thinks***: model routing, memory assembly, learning, entity construction (Meta Agent), governance enforcement. These are platform cognition — they belong to no arc.
* **Arc III decides *what the business does***: prioritization, resource allocation, project coordination, dispatch, scheduling. These are business decisions — they are work, performed by Agents, inside the loop.

The Meta Agent is therefore *invoked from* Arc III (when orchestration discovers a missing capability) but *lives in* the axle. The wheel diagram, arc table, and the Buddhist foundation (two wings — Pragya/wisdom and Karuna/compassion — resting on the ground of Sheel/discipline) are retained from v1 §2.2–§2.4 unchanged.

---

## 3. The Complete Business Architecture

### 3.1 The Three Planes (Retained)
The Relationship Plane (Pragya inward, Karuna outward, HITL to humans), the Cognition Plane (Intelligence Engine, Meta Agent, 8-stage AgentLoop, Learning System, Generative UI), and the Memory & Systems Plane (CORTEX + Episodic + Semantic, dynamic schema, tool registry & connectors) stand as defined in v1 §3.1. v2 adds the two missing architectural specifications below — the actual anti-seam machinery.

### 3.2 The Canonical Business Object Model (New in v2)
"One memory" is only real if every arc reads and writes the **same objects**. These **27 canonical objects** *(v2.1: count corrected from "24" — the v2.0 table actually listed 25 — and **Product/SKU** + **Evidence** added, closing gaps A2/A3)* seed each tenant's dynamic schema (`tenant_entity_defs`) at onboarding; the schema then evolves per tenant (functional doc §13). Every Process in §5 declares which objects it reads/writes — that declaration *is* the integration.

| Domain | Canonical Objects (seed) | Primary writing arcs |
|---|---|---|
| Market & Demand | **Signal**, **Campaign**, **Lead** | I, II |
| Revenue | **Account**, **Contact**, **Opportunity**, **Quote**, **Contract** | II, III, V |
| Delivery | **Order**, **Project/Engagement**, **Deliverable**, **Ticket** | III, IV, II |
| Money | **Invoice**, **Payment**, **Bill**, **Ledger Entry**, **Budget** | V |
| Supply | **Vendor**, **Purchase Order**, **Asset/Inventory Item** | IV, V |
| People | **Candidate**, **Employee** | II, V |
| Product | **Product/SKU** *(added v2.1 — declared by P16 Idea-to-Launch)* | VI, III |
| Trust | **Risk**, **Incident**, **Policy/Obligation**, **Evidence** *(Evidence added v2.1 — declared by P14/P17)* | V, all |

Object lifecycles chain across arcs without translation: `Signal → Lead → Opportunity → Quote → Contract → Order → Project → Invoice → Payment → Ledger Entry`, with `Ticket`, `Risk`, and `Incident` attachable to any node. The support conversation and the invoice dispute are the *same object graph* — which is why the dispute "resolves in-loop."

> **Design pointer (2026-07-18):** the storage that makes this graph real — JSONB records + the typed `tenant_record_links` edge table, `ref` field materialization, indexing, and non-additive schema evolution — is now specified in technical doc §19.
>
> **Design pointer (v2.2, closes register B4):** *who masters each object* is now decided and specified in technical doc §21 — **per-object ownership**: objects already managed in a connected system stay mastered there (HireBuddha mirrors + writes back through the connector; master wins conflicts via `sync.conflict` signals); objects with no external home are mastered in HireBuddha. Links may span both masters — one graph, declared mastering.
>
> **v2.3 (owner directive):** these canonical objects are the **spine of the predefined HireBuddha Business Schema** (technical doc §10.3) — each expands into a full functional module (CRM, Accounting, HRMS, ERP/Operations, Legal, Marketing & PR, Planning), so a tenant with no external systems runs their entire business on HireBuddha alone. The tenant's schema and data live in their sandbox-resident tenant DB (technical doc §10.4–§10.5).

### 3.3 The Signal & Trigger Contract (New in v2)
Any event, from any source, enters the loop as one standard envelope written to the shared fabric:

```json
{
  "signal_id": "uuid",
  "source": "karuna_gateway | connector | telemetry | schedule | agent | human",
  "type": "e.g. lead.inbound, payment.failed, usage.anomaly, reg.change, ticket.opened",
  "object_refs": ["canonical object ids"],
  "urgency": "low | normal | high | critical",
  "confidence": 0.0,
  "payload": { }
}
```

**Trigger registry.** Each Process (§5) subscribes to signal `type` patterns; the Chronos Daemon supplies scheduled signals; Karuna Gateways supply conversational ones; connectors (CRM/ERP/bank feed/webhooks) supply systemic ones. Routing rules: (1) exactly-one owning Process per signal (the dispatcher resolves contention by declared priority); (2) every signal is either consumed, escalated, or explicitly parked with a review timer — **no dropped signals**; (3) every consumption emits a completion signal, which is what lets the Evolve arc audit the whole nervous system.

This section is the formal answer to "how is it *one* loop": objects are shared (§3.2), events are standard (§3.3), and no seam exists because there is nothing to hand off — only state changing in one fabric.

> **Design pointer (2026-07-18):** the platform mechanics behind this contract — the `signals` outbox table, `trigger_registry`, `SKIP LOCKED` claim semantics, parking/dead-letter states, completion signals, and the signal-coverage audit query — are now specified in technical doc §18. Delivery is at-least-once with idempotent consumption; the "no dropped signals" rule is enforced by the status machine, not asserted.

---

## 4. The Great Convergence — Old Departments → Sheel (Completed)

v2 extends the master map to **39 functions**. No function is left behind — now verifiably.

### 4.1 Department → Arc → Process → Agents (Master Map v2)

| # | Traditional Department / Function | Arc(s) | Canonical Process(es) (§5) | Primary AI Agents (§7.3/§8) |
|---|---|---|---|---|
| 1 | Marketing (brand, content, demand-gen) | I, II | Awareness-to-Demand | Content Studio, Campaign Orchestrator, Social Listener, Market Intel Scout |
| 2 | PR & Corporate Communications *(new)* | II, V | Awareness-to-Demand · Incident-to-Resolution | PR & Comms Agent, Crisis Response Agent |
| 3 | Community Management *(new)* | II | Awareness-to-Demand | Community Manager Agent |
| 4 | Sales / Business Development | II, III | Cold-to-Closed Acquisition | Outbound Prospector, Inbound Deal Closer (voice), Proposal & Quote, Deal Desk |
| 5 | Sales Engineering / Pre-sales | II | Cold-to-Closed Acquisition | Tech Pre-Sales Agent |
| 6 | Partnerships / Channel / Alliances *(new)* | II, V | Partner-to-Revenue | Partnership Manager, Channel Enablement Agent |
| 7 | Pricing & Monetization *(new)* | III, VI | Idea-to-Launch · Plan-Budget-Forecast | Pricing Analyst Agent |
| 8 | Customer Support | II | Resolve-to-Retain | Omnichannel Care Orchestrator, Tier-2 Tech Resolver, Escalation Voice Agent |
| 9 | Customer Success / Account Mgmt | I, II, V | Resolve-to-Retain · Renew-&-Expand | Proactive Account Advisor, Renewal & Expansion, Health-Score Monitor |
| 10 | Customer Education & Enablement *(new)* | II, IV | Resolve-to-Retain | Customer Education Agent, Knowledge Curator |
| 11 | Operations / Service Delivery | III, IV | Order-to-Fulfilled | Service Dispatcher, Delivery Operator, Provisioning Agent |
| 12 | Project / Program Management | III | Order-to-Fulfilled | Project Orchestrator, Milestone & SLA Tracker, Dependency Resolver |
| 13 | Quality Assurance | IV | Order-to-Fulfilled | QA & Audit Agent, Proof-of-Work Validator |
| 14 | Manufacturing / Production | IV | Order-to-Fulfilled | Production Scheduler, QA & Audit Agent |
| 15 | Supply Chain / Logistics / Inventory | IV, V | Source-to-Pay · Order-to-Fulfilled | Inventory Oracle, Shipping Agent, Returns & Refunds Agent |
| 16 | Procurement / Vendor Management | V | Source-to-Pay | Procurement & Sourcing, Vendor Onboarding, Vendor Risk, Contract & SLA Manager |
| 17 | Finance / FP&A / Treasury | V, VI | Plan-Budget-Forecast | Treasury & Ledger Controller, Cashflow Forecaster, FP&A Analyst |
| 18 | Accounting / Bookkeeping / Close *(expanded)* | V | Record-to-Report | Bookkeeping & Reconciliation, Tax-Matrix, Statutory Reporting Agent |
| 19 | Accounts Receivable / Collections | V, II | Order-to-Cash | AR Agent, Empathetic Collections Voice Agent |
| 20 | Accounts Payable | V | Source-to-Pay | AP/Payout Agent |
| 21 | Payroll & Benefits | V | Hire-to-Retire | Payroll Run Agent, Benefits & Time-off Agent |
| 22 | Expense Management | V | Record-to-Report | Expense Management Agent |
| 23 | Legal / Contracts | V | Draft-Review-Sign | Contract Review Specialist, Redline & Drafting, E-Signature Router |
| 24 | Compliance / Risk / Internal Audit | V | Continuous Guardrails | Regulatory Watchdog, KYB/AML Gateway, Internal Audit Agent, Risk Register Agent |
| 25 | Data Privacy / DPO *(new)* | V | Continuous Guardrails | Privacy & DSAR Agent |
| 26 | Information Security *(new)* | V, IV | Continuous Guardrails · Incident-to-Resolution | InfoSec Sentinel, Access & Identity Agent |
| 27 | Insurance & Corporate Secretarial *(new)* | V | Continuous Guardrails | Corporate Records & Insurance Agent |
| 28 | Human Resources | V | Hire-to-Retire | HR Helpdesk, Onboarding Buddy, Offboarding Agent |
| 29 | Recruiting / Talent Acquisition | II, V | Hire-to-Retire (Source-to-Hire stage) | Talent Scout, Sourcing Agent, Candidate Voice Screener, Interview Scheduler, Offer & Negotiation Agent |
| 30 | Learning & Development *(new)* | V, VI | Hire-to-Retire | Enablement & Training Agent |
| 31 | IT / DevOps / Internal Tools | IV, V | Provision-&-Maintain | Provisioning Agent, Self-Healing Tool Agent, Access & Identity Agent |
| 32 | Data & Analytics Engineering *(new)* | IV, VI | Provision-&-Maintain · Sense-Decide-Optimize | Data Pipeline Agent |
| 33 | Facilities & Physical Assets *(new)* | V | Provision-&-Maintain | Facilities & Asset Agent |
| 34 | Product Management *(new, distinct from R&D)* | III, VI | Idea-to-Launch | Product Manager (Backlog Curator), Experiment Designer, Voice-of-Customer Agent |
| 35 | R&D / Innovation | VI | Idea-to-Launch | Insights Synthesizer, Experiment Designer |
| 36 | Executive / Strategy / BI | III, VI | Sense-Decide-Optimize | Chief Strategy Analyst, Executive Briefing Agent, Instruction Optimizer |
| 37 | Executive Assistant / Office Mgmt | III | Sense-Decide-Optimize (coordination stage) | Scheduling, Comms Triage, Meeting-Notes Agents |
| 38 | Investor Relations & Fundraising *(new)* | II, V, VI | Capital-&-Stakeholders | Investor Relations Agent, Data-Room Curator |
| 39 | Corporate Development / M&A *(new)* | I, III, VI | Capital-&-Stakeholders | Corp-Dev Scout Agent |
| — | Incident / Crisis Management *(new, cross-cutting)* | all | Incident-to-Resolution | Incident Commander, Crisis Response, InfoSec Sentinel |
| — | Knowledge Management *(v2.1: home fixed — gap A10)* | II + axle | Resolve-to-Retain (knowledge-curation stage) | Knowledge Curator (AGT-034, P06); Pragya (axle) for tenant-KB ingestion |
| — | The Owner's job | Relationship plane | — | Goals, HITL judgment, relationships — via Pragya |

> **Reading the map:** a department is not "ported" — it is *absorbed*: its work becomes Processes and Agents sharing the loop's brain and memory. Rows marked *(new)* are v2 additions closing gap G4.

### 4.2 Role Convergence
v1 §4.3's role-by-role table ("who does my job now") remains valid and is extended by the new agents above; the complete, deduplicated deployment list is now the Agent Registry (§7.3), which supersedes it as the single source of truth. The v1 principle stands: *humans move up the stack — into goal-setting, exceptions, relationships, and judgment via HITL* — and is now given a full operating model in §11.

---

## 5. The Canonical Process Architecture (Reconciled)

v1 named Processes inconsistently across §4.1, §4.2, and §10.1 (gap G2). v2 fixes the taxonomy: **19 canonical end-to-end Processes**, each an entity of tier `PROCESS` parented by Sheel, each with declared trigger subscriptions (§3.3), read/write objects (§3.2), a starting autonomy level (§9.2), and a budget envelope (§10.1).

| ID | Process | Arcs | Absorbs / supersedes (v1 names) | Reads / writes (key objects) | Start autonomy |
|---|---|---|---|---|---|
| P01 | **Signal-to-Insight** | I | Demand Sensing (standing perception) | Signal, Lead, Risk | A3 |
| P02 | **Awareness-to-Demand** | I→II | Content Engine · Campaign Orchestration; + PR, community | Campaign, Signal, Lead | A2 |
| P03 | **Cold-to-Closed Acquisition** | I→II→III | (retained) | Lead, Opportunity, Quote, Contract | A2 |
| P04 | **Partner-to-Revenue** *(new)* | II→V | — | Account, Contract, Invoice | A1 |
| P05 | **Order-to-Fulfilled** | III→IV | Plan-to-Done · Verify-&-Sign-off · Pick-Pack-Ship | Order, Project, Deliverable, Asset | A2 |
| P06 | **Resolve-to-Retain** | II | (retained); + customer education | Ticket, Account, Signal | A2→A3 |
| P07 | **Renew-&-Expand** | I→II→V | (retained) | Account, Opportunity, Contract, Invoice | A2 |
| P08 | **Order-to-Cash** | V→II | Invoice-to-Collected (merged) | Invoice, Payment, Ledger Entry | A2 |
| P09 | **Source-to-Pay** | IV→V | Procure-to-Pay · Source-to-Stock · Source-to-Pay (unified) | Vendor, PO, Bill, Payment, Asset | A1 |
| P10 | **Record-to-Report** *(new)* | V | (bookkeeping, close, statutory & expense — previously scattered) | Ledger Entry, Bill, Invoice, Budget | A2 |
| P11 | **Plan-Budget-Forecast** | V→VI | (retained); + pricing analytics | Budget, Ledger Entry, Signal | A1 |
| P12 | **Hire-to-Retire** | II→V | Source-to-Hire · Hire-to-Onboard (now stages); + Develop-&-Retain, **Offboard** | Candidate, Employee, Policy | A1→A2 |
| P13 | **Draft-Review-Sign** | V | (retained) | Contract, Risk | A1 |
| P14 | **Continuous Guardrails** | V | (retained); + privacy, infosec, internal audit, insurance/secretarial | Policy, Risk, Incident, Evidence | A2 |
| P15 | **Provision-&-Maintain** | IV→V | (retained); + facilities, data pipelines | Asset, Ticket, Employee | A2→A3 |
| P16 | **Idea-to-Launch** *(new)* | VI→III | Insight-to-Roadmap (expanded to launch & pricing) | Signal, Product/SKU, Campaign | A1 |
| P17 | **Incident-to-Resolution** *(new)* | cross-cutting | — (security, outage, PR crisis, fraud events) | Incident, Risk, Ticket | A1 (declare) / A3 (contain) |
| P18 | **Capital-&-Stakeholders** *(new)* | II·V·VI | — (IR, fundraising support, corp dev, board reporting) | Budget, Contract, Signal | A0→A1 |
| P19 | **Sense-Decide-Optimize** | III→VI | (retained); + EA/coordination stage | all (read), Budget, Policy (write) | A2 |

**Reconciliation notes (closing G2):** *Hire-to-Retire* is the umbrella — its stages are Source-to-Hire → Hire-to-Onboard → Develop-&-Retain → Offboard; v1 treated two stages as separate processes and omitted the last two entirely. *Source-to-Pay* and *Procure-to-Pay* were duplicate names for one flow; v2 keeps **Source-to-Pay** (it starts earlier, at sourcing). *Invoice-to-Collected* was a fragment of **Order-to-Cash**. *Verify-&-Sign-off* and *Pick-Pack-Ship* are stages of **Order-to-Fulfilled**, not Processes. **Record-to-Report** — the classic close-the-books value stream — was missing outright.

**Cross-cutting rule for P17 (Incident-to-Resolution):** any Agent, any arc, any Karuna gateway, or the platform's own critics can emit `incident.*` signals; P17 preempts normal routing at `urgency: critical`, can invoke the loop-level degradation ladder (§12), and always raises HITL for public statements, regulator notifications, and legal holds.

---

## 6. Arc Anatomy — v2 Amendments

The per-arc flow diagrams of v1 §6 (Perceive, Engage, Orchestrate, Fulfill, Sustain, Evolve) remain accurate and are incorporated by reference. v2 amends them as follows:

* **Every arc entry point is a Karuna Gateway or a signal envelope** (§3.3) — the ad-hoc "[Triggers: …]" headers of v1 are replaced by declared trigger subscriptions per Process.
* **Arc II** gains PR/community/education agents; all Arc II agents carry the Karuna Profile (§2.3).
* **Arc III** is explicitly business-decision orchestration (§2.4); Meta Agent invocation is an axle call, not an Arc III step.
* **Arc IV** gains Data Pipeline and Document Processing flows; Returns/RMA joins fulfillment.
* **Arc V** gains Privacy (DSAR), InfoSec monitoring, statutory reporting, insurance/secretarial, and offboarding flows; segregation-of-duties boundaries (§9.4) are drawn *inside* this arc.
* **Arc VI** now also audits the nervous system itself: completion-signal coverage (were any signals dropped/parked too long?) is a standing Evolve KPI.

---

## 7. The Complete Hierarchical Entity Registry

> **This section closes gap G1.** All five tiers, enumerated. IDs are stable template keys; deployment instantiates them as `hierarchical_entities` rows (technical doc §2.1) with tenant UUIDs.

### 7.1 Tier 5 — LOOP (1)

| ID | Entity | Config |
|---|---|---|
| LOOP-SHEEL | **Sheel — Unified Business Engine** | Owns P01–P19; hub agent Pragya; KPIs & budget hierarchy §10; deployment JSON §15 |

### 7.2 Tier 4 — PROCESS (19)
As enumerated in §5 (P01–P19).

### 7.3 Tier 3 — AGENT (100 = 1 hub + 5 Karuna gateways + 94 workforce)

**Hub & Gateways**

| ID | Agent | Parent | Notes |
|---|---|---|---|
| HUB-PRAGYA | Pragya (Account-Manager Hub) | LOOP-SHEEL | Inward face; all channels; Meta Agent relay |
| KAR-01 | Karuna Voice Gateway | LOOP-SHEEL | Telephony front door (OmniBuddha/Gemini Live/GPT Realtime) |
| KAR-02 | Karuna Email Gateway | LOOP-SHEEL | IMAP ingest → classify → route |
| KAR-03 | Karuna Messaging Gateway | LOOP-SHEEL | WhatsApp/SMS |
| KAR-04 | Karuna Chat/Web Gateway | LOOP-SHEEL | Website/app chat, forms |
| KAR-05 | Karuna Social Gateway | LOOP-SHEEL | Social inboxes & mentions |

**Workforce Agents** (arc shown for reading; parent Process is authoritative)

| ID | Agent | Parent Process | Arc |
|---|---|---|---|
| AGT-001 | Market Intel Scout | P01 | I |
| AGT-002 | Telemetry & Health Monitor | P01 | I |
| AGT-003 | Social Listener | P01 | I |
| AGT-004 | Demand Sensor | P01 | I |
| AGT-005 | Health-Score Monitor (customer) | P01 | I |
| AGT-006 | Content Studio Agent | P02 | II |
| AGT-007 | Campaign Orchestrator | P02 | II |
| AGT-008 | PR & Comms Agent *(new)* | P02 | II |
| AGT-009 | Community Manager Agent *(new)* | P02 | II |
| AGT-010 | Reputation & Review Agent | P02 | II |
| AGT-011 | Survey & NPS Agent | P02 | II |
| AGT-012 | Outbound Prospector | P03 | II |
| AGT-013 | Inbound Deal Closer (Voice) | P03 | II |
| AGT-014 | Tech Pre-Sales Agent | P03 | II |
| AGT-015 | Proposal & Quote Agent | P03 | II |
| AGT-016 | Deal Desk Agent *(new)* | P03 | III |
| AGT-017 | Partnership Manager Agent *(new)* | P04 | II |
| AGT-018 | Channel Enablement Agent *(new)* | P04 | II |
| AGT-019 | Service Dispatcher | P05 | III |
| AGT-020 | Project Orchestrator | P05 | III |
| AGT-021 | Milestone & SLA Tracker | P05 | III |
| AGT-022 | Dependency Resolver | P05 | III |
| AGT-023 | Delivery Operator | P05 | IV |
| AGT-024 | Provisioning / Client Welcome Agent | P05 | IV |
| AGT-025 | QA & Audit Agent | P05 | IV |
| AGT-026 | Proof-of-Work Validator | P05 | IV |
| AGT-027 | Production Scheduler | P05 | IV |
| AGT-028 | Shipping Agent | P05 | IV |
| AGT-029 | Returns & Refunds Agent | P05 | IV |
| AGT-030 | Omnichannel Care Orchestrator | P06 | II |
| AGT-031 | Tier-2 Tech Resolver | P06 | II |
| AGT-032 | Escalation Voice Agent | P06 | II |
| AGT-033 | Customer Education Agent *(new)* | P06 | II |
| AGT-034 | Knowledge Curator *(new; arc fixed v2.1)* | P06 | II |
| AGT-035 | Appointment Concierge | P06 | II |
| AGT-036 | Proactive Account Advisor | P07 | II |
| AGT-037 | Renewal & Expansion Agent | P07 | II |
| AGT-038 | Accounts Receivable Agent | P08 | V |
| AGT-039 | Empathetic Collections Voice Agent | P08 | V/II |
| AGT-040 | Procurement & Sourcing Agent | P09 | V |
| AGT-041 | Vendor Onboarding Agent | P09 | V |
| AGT-042 | Vendor Risk Agent *(new)* | P09 | V |
| AGT-043 | Contract & SLA Manager *(new)* | P09 | V |
| AGT-044 | Inventory Oracle | P09 | IV |
| AGT-045 | Accounts Payable / Payout Agent | P09 | V |
| AGT-046 | Bookkeeping & Reconciliation Agent | P10 | V |
| AGT-047 | Treasury & Ledger Controller | P10 | V |
| AGT-048 | Tax-Matrix Agent | P10 | V |
| AGT-049 | Expense Management Agent | P10 | V |
| AGT-050 | Statutory Reporting Agent *(new)* | P10 | V |
| AGT-051 | Cashflow Forecaster | P11 | V |
| AGT-052 | FP&A Analyst | P11 | V |
| AGT-053 | Pricing Analyst Agent *(new)* | P11 | VI |
| AGT-054 | Talent Scout Coordinator | P12 | II |
| AGT-055 | Sourcing Agent | P12 | II |
| AGT-056 | Candidate Voice Screener | P12 | II |
| AGT-057 | Interview Scheduler *(now registered)* | P12 | III |
| AGT-058 | Offer & Negotiation Agent *(now registered)* | P12 | II |
| AGT-059 | Onboarding Buddy | P12 | V |
| AGT-060 | HR Helpdesk Agent | P12 | V |
| AGT-061 | Payroll Run Agent | P12 | V |
| AGT-062 | Benefits & Time-off Agent *(now registered)* | P12 | V |
| AGT-063 | Enablement & Training Agent *(new)* | P12 | V |
| AGT-064 | Offboarding Agent *(new)* | P12 | V |
| AGT-065 | Contract Review Specialist | P13 | V |
| AGT-066 | Redline & Drafting Agent | P13 | V |
| AGT-067 | E-Signature Router | P13 | V |
| AGT-068 | Regulatory Watchdog | P14 | V |
| AGT-069 | KYB/AML Gateway Agent | P14 | V |
| AGT-070 | Internal Audit Agent *(now registered)* | P14 | V |
| AGT-071 | Risk Register Agent | P14 | V |
| AGT-072 | Privacy & DSAR Agent *(new)* | P14 | V |
| AGT-073 | InfoSec Sentinel *(new)* | P14 | V |
| AGT-074 | Fraud & AML Monitor | P14 | V |
| AGT-075 | Corporate Records & Insurance Agent *(new)* | P14 | V |
| AGT-076 | Access & Identity Agent | P15 | V |
| AGT-077 | Self-Healing Tool Agent | P15 | IV |
| AGT-078 | Data Pipeline Agent *(new)* | P15 | IV |
| AGT-079 | Facilities & Asset Agent *(new)* | P15 | V |
| AGT-080 | Product Manager / Backlog Curator *(new)* | P16 | VI |
| AGT-081 | Experiment Designer *(now registered)* | P16 | VI |
| AGT-082 | Voice-of-Customer Agent *(now registered)* | P16 | VI |
| AGT-083 | Incident Commander *(new)* | P17 | cross |
| AGT-084 | Crisis Response Agent *(new)* | P17 | cross |
| AGT-085 | Investor Relations Agent *(new)* | P18 | II/V |
| AGT-086 | Data-Room Curator *(new)* | P18 | V |
| AGT-087 | Corp-Dev Scout Agent *(new)* | P18 | I |
| AGT-088 | Chief Strategy Analyst | P19 | VI |
| AGT-089 | Executive Briefing Agent | P19 | VI |
| AGT-090 | Insights Synthesizer | P19 | VI |
| AGT-091 | Instruction Optimizer (Self-Optimizing Intelligence Engine hook) | P19 | VI |
| AGT-092 | Scheduling Agent | P19 | III |
| AGT-093 | Comms Triage Agent | P19 | III |
| AGT-094 | Meeting-Notes Agent | P19 | III |

*(Every Agent named anywhere in v1 §4 now exists here — closing G2. Translation & Localization is reclassified as a Skill, SKL-E12, auto-invoked by the Karuna Profile.)*

### 7.4 Tier 2 — SKILL Library (62)

Skills are reusable compositions of Actions; any Agent may bind any Skill. Grouped by arc:

**Perceive (8):** SKL-P01 ICP & Signal Enrichment · P02 Anomaly Detection · P03 Sentiment & Trend Capture · P04 Competitor Price/Feature Watch · P05 Regulatory Change Watch · P06 Demand Forecasting · P07 Intent-Signal Scoring · P08 Health-Score Computation

**Engage (12):** SKL-E01 Hyper-Personalized Outreach · E02 Multi-Channel Sequencing · E03 Live Call Qualification · E04 Quote & ROI Calculation · E05 Proposal Rendering · E06 Contextual Resolution (semantic KB) · E07 Sandbox Debugging · E08 Structured Interview · E09 Appointment Booking & Reminders · E10 Review Solicitation & Response · E11 Survey/NPS Collection · E12 Translation & Localization

**Orchestrate (7):** SKL-O01 Resource Allocation & Planning · O02 Milestone/SLA Tracking · O03 Dependency Resolution · O04 Calendar Coordination · O05 Inbox & Notification Triage · O06 Meeting Capture & Actioning · O07 Approval Routing

**Fulfill (9):** SKL-F01 Automated Provisioning · F02 Environment/Workspace Setup · F03 Proof-of-Work Verification · F04 Pick-Pack-Ship · F05 Production Sequencing · F06 Returns/RMA Processing · F07 Document Generation Pipeline · F08 Data Extraction & OCR · F09 Integration Self-Healing

**Sustain (16):** SKL-S01 Bank Reconciliation · S02 Ledger Close · S03 Invoice Generation · S04 Empathetic Collection · S05 3-Way Match · S06 Global Payout Execution · S07 Tax/VAT Computation · S08 Payroll Execution · S09 Expense Claim Processing · S10 Cashflow Projection · S11 Contract Risk Audit · S12 Redlining & Drafting · S13 E-Signature Routing · S14 KYB/AML Screening · S15 DSAR Fulfillment · S16 Access Provision/Deprovision

**Evolve (6):** SKL-V01 Cross-Process KPI Harvest · V02 Executive Briefing Composition · V03 Voice-of-Customer Synthesis · V04 Experiment Design & A/B · V05 Instruction Optimization · V06 Router Preference Tuning

**Cross-cutting (4):** SKL-X01 Signal Envelope Emission · X02 HITL Checkpoint Raising · X03 Evidence Capture & Archival · X04 Counterparty Verification

### 7.5 Tier 1 — ACTION Catalog (37, mapped to the registered Tool registry)

Each Action is a thin, IO-contracted wrapper around one registered Tool (functional doc §6). The Meta Agent extends this catalog at runtime via tool synthesis (functional doc §12). *(v2.1: ACT-32…ACT-37 added, closing gap A5 — every Skill and template binding now resolves to a registered Action.)*

| Action | Wraps Tool | Functional doc ref |
|---|---|---|
| ACT-01 Web Search | Web Search (DuckDuckGo/Google CSE) | §6.1 |
| ACT-02 Scrape Page | Web Scraper (BS4/Firecrawl) | §6.1 |
| ACT-03 Browse & Interact | Headless Browser (Playwright) | §6.1 |
| ACT-04 Ingest Email | Email Ingest (IMAP) | §6.2 |
| ACT-05 Classify Email | Email Classify | §6.2 |
| ACT-06 Draft Email | Email Draft | §6.2 |
| ACT-07 Send Email | Email Send (SMTP) | §6.2 |
| ACT-08 Build Spreadsheet | Excel Tool (openpyxl) | §6.3 |
| ACT-09 Render PDF | PDF Generator (WeasyPrint) | §6.3 |
| ACT-10 Render DOCX | Word Generator (python-docx) | §6.3 |
| ACT-11 Render PPTX | PowerPoint Generator | §6.3 |
| ACT-12 Write File | File Writer | §6.3 |
| ACT-13 Generate Image | Image Gen (Nano Banana/ChatGPT Image/Kling) | §6.4 |
| ACT-14 Generate Video | Video Gen (Veo/SeeDance) | §6.4 |
| ACT-15 Calculate | Calculator | §6.5 |
| ACT-16 Execute Code | Sandbox Code Executor | §6.5 |
| ACT-17 Run Shell | Terminal Tool | §6.5 |
| ACT-18 Sync Bank Feed | Bank Feed Synchronizer (Plaid/Yodlee) | §6.6 |
| ACT-19 Execute Payout | Global Payout Rails (Stripe/Wise/PayPal) | §6.6 |
| ACT-20 Compute Tax | Automated Tax Matrix (Avalara/TaxJar) | §6.6 |
| ACT-21 Route E-Signature | E-Signature Handler (DocuSign/Dropbox Sign) | §6.6 |
| ACT-22 Verify Entity | KYB/AML Gateway (Middesk/Persona) | §6.6 |
| ACT-23 Post Interactive Card | Rich Communication Broker (Slack/Teams) | §6.6 |
| ACT-24 Raise Eng Ticket | Helpdesk Route-and-Lock (Jira/Linear) | §6.6 |
| ACT-25 Enrich Entity | Enrichment & Signal Harvester (Apollo/Clearbit/ZoomInfo) | §6.6 |
| ACT-26 Book Calendar Slot | Calendar Matrix Orchestrator (Google/MS Graph) | §6.6 |
| ACT-27 Access HRIS | HRIS Core Accessor (Gusto/Rippling/BambooHR) | §6.6 |
| ACT-28 Check/Update Inventory | Warehousing & Inventory Oracle (ShipStation/Shopify) | §6.6 |
| ACT-29 Sync Knowledge Source | Knowledge Source Connectors (SharePoint/Notion/Drive/DB) | §6.6 |
| ACT-30 Read/Write Business System | Enterprise System Connectors (CRM/ERP/Accounting/HRMS/Invoicing) | §6.6 |
| ACT-31 Schedule Wake-up | Chronos Daemon | §6.6 |
| ACT-32 Query Tenant Data *(v2.1)* | Tenant Data Query (read-only SQL/analytics, company-scoped) | §6.6 |
| ACT-33 Extract & OCR Document *(v2.1)* | Document Extraction & OCR | §6.6 |
| ACT-34 Translate Text *(v2.1)* | Translation & Localization (auto-invoked by Karuna Profile; backs SKL-E12) | §6.6 |
| ACT-35 Capture Evidence *(v2.1)* | Evidence Store (immutable, audit-trailed; backs SKL-X03) | §6.6 |
| ACT-36 Post & Listen (Social) *(v2.1)* | Social Publishing & Listening (EXPERIMENTAL in code) | §6.6 |
| ACT-37 Send Alert *(v2.1)* | Alerting & Notification | §6.6 |

---

## 8. The AI Agent Template Library — v2 Additions

All v1 §8 templates are retained with their charters, tool bindings, and reasoning modes. The table below defines the **new and newly-registered** templates (the delta that closes G2/G4). As before: any remaining gap is filled at runtime by the Meta Agent from a plain-language goal. *(v2.1: tool bindings re-stated against the registered Action catalog — closing gap A5; "pgvector" bindings are restated as platform semantic-memory retrieval, which is a memory-system capability, not a tool.)*

| Template | Default Role | Tools (Actions) | Reasoning / Governance |
|---|---|---|---|
| **Karuna Gateway (per channel ×5)** | Authenticate, classify intent, apply threat posture, route inbound | Channel adapters, Email Classify, ACT-22 verify, SKL-X01 | ReAct · Karuna Profile mandatory |
| **PR & Comms Agent** | Press releases, media inquiries, brand statements | DOCX/PDF Gen, Email, Web Search | CoT · **HITL on all public statements** |
| **Crisis Response Agent** | Drafts holding statements, coordinates comms in incidents | Email/Slack/Teams broker, DOCX | CoT · strict HITL |
| **Community Manager Agent** | Moderate & engage community spaces | Post & Listen (ACT-36), KB, Rich Comm Broker (ACT-23) | ReAct · Karuna Profile |
| **Deal Desk Agent** | Discount/terms approval analysis, quote governance | Calculate (ACT-15), Query Tenant Data (ACT-32), policy KB | CoT · authority matrix §9.3 |
| **Partnership Manager Agent** | Source, negotiate & manage partner agreements | Enrichment, Email, E-sign, Calendar | CoT · HITL on agreements |
| **Channel Enablement Agent** | Partner onboarding, collateral, co-selling support | KB, PPTX/PDF Gen, Email | ReAct |
| **Customer Education Agent** | Tutorials, help content, onboarding academies | DOCX/Video Gen, KB | CoT |
| **Knowledge Curator** | Keep Semantic KB fresh, deduplicated, gap-flagged | Knowledge Connectors, File Writer | ReAct |
| **Statutory Reporting Agent** | GST/VAT filings prep, statutory statements | Tax Matrix, Excel, PDF Gen | CoT · **HITL before any filing** |
| **Pricing Analyst Agent** | Price/packaging analysis & proposals | Query Tenant Data (ACT-32), Execute Code (ACT-16), Competitor Watch (SKL-P04) | CoT · HITL on price changes |
| **Interview Scheduler** | Coordinate candidate interviews | Calendar Orchestrator, Email/WhatsApp | ReAct |
| **Offer & Negotiation Agent** | Compose offers, negotiate within bands | HRIS, DOCX, E-sign | CoT · authority matrix + HITL |
| **Benefits & Time-off Agent** | Administer leave & benefits queries | HRIS Accessor, policy KB | ReAct |
| **Enablement & Training Agent** | Internal training paths & certifications | KB, DOCX/Video Gen | CoT |
| **Offboarding Agent** | Exit checklist: access revocation, final pay, knowledge capture | HRIS, Access & Identity, Payroll hooks | ReAct · SoD with Access Agent · HITL |
| **Internal Audit Agent** | Independent control testing & evidence sampling | Query Tenant Data (ACT-32, read-only), Capture Evidence (ACT-35) | CoT · **must not share parent with audited agents** (§9.4) |
| **Privacy & DSAR Agent** | Data-subject requests, consent registry, retention | Tenant schema APIs, DOCX | CoT · HITL on erasure |
| **InfoSec Sentinel** | Monitor access anomalies, secrets hygiene, agent-behavior anomalies | Query Tenant Data (ACT-32), Send Alert (ACT-37) | ReAct · emits `incident.security` |
| **Corporate Records & Insurance Agent** | Registrations, licenses, policies, renewal calendar | Chronos, DOCX, KB | ReAct |
| **Vendor Risk Agent** | Score & monitor vendor risk continuously | KYB/AML, Web Search, Risk register | CoT |
| **Contract & SLA Manager (vendor-side)** | Track vendor obligations & SLAs | KB, Query Tenant Data (ACT-32), Send Alert (ACT-37) | ReAct |
| **Data Pipeline Agent** | Maintain connectors, schema syncs, data quality | Enterprise Connectors, Sandbox | ReAct |
| **Facilities & Asset Agent** | Physical assets, leases, maintenance schedules | Asset registry, Chronos, Email | ReAct |
| **Product Manager / Backlog Curator** | Synthesize signals into prioritized backlog | Semantic memory retrieval (platform), Query Tenant Data (ACT-32), Render PPTX (ACT-11) | CoT |
| **Experiment Designer** | Design/monitor A-B and pricing experiments | Execute Code (ACT-16), Query Tenant Data (ACT-32) | CoT |
| **Voice-of-Customer Agent** | Mine conversations for product insight | Semantic memory retrieval across tickets/calls (platform) | CoT |
| **Incident Commander** | Own incident lifecycle: declare, contain, resolve, post-mortem | All alert channels, runbooks KB | ReAct · preemptive priority · HITL |
| **Investor Relations Agent** | Investor updates, KPI packs, Q&A prep | Render PPTX/PDF (ACT-11/ACT-09), Query Tenant Data (ACT-32) | CoT · **HITL on all external sends** |
| **Data-Room Curator** | Maintain diligence-ready data room | File Writer, Knowledge Connectors | ReAct |
| **Corp-Dev Scout Agent** | Track acquisition/partnership targets | Web Search, Enrichment | ReAct |

---

## 9. Governance & Trust Architecture (New in v2)

The single most important correction to v1: a business run by one loop needs governance *designed into the loop*, not five checkpoint strings in a JSON block.

### 9.1 The Layered Model
Platform guardrails (functional doc §7, §15 — Pre/Post-Critics, circuit breakers, Key Vault, JWT, suspension middleware, model allow-lists) form layer 0. This section defines the **business-governance layers** above them.

> **Design pointer (2026-07-18):** the enforcement mechanics for this entire section — the typed governance schema, the `hitl_checkpoint_defs` registry, the deterministic **PolicyGate** ahead of the LLM Pre-Critic, deploy-time SoD/Karuna validators, and `budget_envelopes` — are now specified in technical doc §20. The authority matrix (§9.3) becomes data an LLM cannot be talked out of.

### 9.2 The Autonomy Ladder (A0–A4)
Every Process and Agent carries an autonomy level in its `governance` JSON. Levels are raised per entity, based on evidence (§9.7), never globally.

| Level | Name | Meaning |
|---|---|---|
| **A0** | Observe | Reads, analyzes, drafts internally. Nothing leaves the loop. |
| **A1** | Propose | Prepares complete outputs; a human approves every external effect. |
| **A2** | Act with exceptions | Acts autonomously inside the authority matrix; HITL fires on threshold breaches and anomalies. |
| **A3** | Act with audit | Fully autonomous within scope; every act logged, sampled by Internal Audit Agent; humans review dashboards, not queues. |
| **A4** | Self-modify | A3 + may accept self-evolved code/instruction changes affecting itself (still test-gated + HITL for high impact, functional doc §12.2). |

### 9.3 The Authority Matrix
Autonomy is bounded by **value bands** per action category. Defaults (tenant-tunable):

| Action category | Autonomous up to | HITL required above | Hard block above |
|---|---|---|---|
| Outbound payment / payout | $500 | $500 | $10,000 (dual human approval) |
| Refund / credit note | $200 | $200 | $5,000 |
| Discount on quote | 10% | 10% | 30% |
| Contract execution | Standard templates, ≤ $2,000 TCV | Any non-standard clause or > $2,000 | High-liability clauses (always human) |
| Employment offer | — | All offers | Compensation outside approved band |
| Public statement / PR | — | All | Crisis/regulatory statements (named human only) |
| Regulatory filing | Draft only | All submissions | — |
| Vendor creation | KYB-passed, ≤ $1,000 exposure | Above / KYB flags | Sanctions-list hit (block + incident) |
| Data deletion (DSAR) | Single-subject, verified | Bulk or ambiguous | Legal-hold conflict |
| Price change | Experiments ≤ 5% on ≤ 10% of traffic | Beyond | Contractual prices |

### 9.4 Segregation of Duties (SoD)
Deterministic conflict rules enforced at deploy time, exactly like the Karuna-Profile check:

* **Maker ≠ checker.** The Agent that initiates a financial effect (payout, refund, payroll, vendor creation) may not be the Agent that approves or reconciles it. AGT-045 (AP/Payout) pays; AGT-046 (Reconciliation) verifies; AGT-070 (Internal Audit) samples — three distinct entities, never sharing Skills that cross those lines.
* **Vendor creation ≠ vendor payment.** AGT-041 onboards; AGT-045 pays; the KYB gate (AGT-069) sits between.
* **Access granter ≠ access user.** AGT-076 provisions access it does not itself consume; offboarding revocation (AGT-064 → AGT-076) is dual-entity by design.
* **Auditor independence.** AGT-070 and AGT-071 run with read-only Actions, separate budget, and report through Pragya directly to the owner — no parent Process being audited.
* **Self-modification quarantine.** No Agent may promote code changes to itself; promotion flows through the sandbox pipeline + a different approving entity (+ HITL if high-impact).

### 9.5 The World-Facing Threat Model (Karuna hardening)
World-facing agents are attack surface. The Karuna Profile activates:

* **Prompt-injection defense** — counterparty content (emails, documents, web pages, call transcripts) is treated as *data, never instruction*; injected directives are flagged by the Pre-Critic and logged as `incident.security` signals on pattern-match.
* **Social-engineering resistance** — payment-detail changes, urgent payout requests, credential requests, and "CEO fraud" patterns trigger SKL-X04 Counterparty Verification (out-of-band confirmation) and HITL, regardless of autonomy level.
* **Impersonation & fraud gates** — KYB/AML screening on new counterparties; bank-detail changes always verified out-of-band; sanctions screening before payouts.
* **Information-boundary enforcement** — world-facing agents hold need-to-know memory viewports; a support conversation cannot exfiltrate payroll data because the agent's CORTEX viewport never contains it.
* **Abuse & jailbreak handling** — scripted disengagement + escalation to human; abusive counterparties never degrade the agent's Karuna conduct.

> **Design pointer (v2.2, closes register D1):** this threat model hardens the *outward* face. The **inward** face — verifying that the person commanding Pragya is actually the owner — is now specified in technical doc §11.3: enrolled channel bindings, impact-tiered T0–T3 command classification sharing the §9.3 authority taxonomy, passkey/OTP step-up for sensitive commands, out-of-band confirmation for critical ones, and the rule that Pragya can never satisfy her own checkpoint.

### 9.6 Regulatory Compliance Map
Baseline obligations wired into the relevant Processes (jurisdiction packs configure specifics):

| Domain | Obligation | Enforced at |
|---|---|---|
| AI disclosure | Agent identifies as AI where required (e.g., bot-disclosure and emerging AI-act rules) | Karuna Profile |
| Outbound calling | DNC/TCPA-class consent, calling windows, consent-to-record | KAR-01 + Campaign engine |
| Email/messaging | CAN-SPAM/GDPR-consent, unsubscribe honoring, WhatsApp Business policy | KAR-02/03 + P02 |
| Data protection | GDPR/DPDP-class: lawful basis, DSAR, retention, breach notification | AGT-072 + P14 |
| Financial | SoD (§9.4), audit trail, e-invoicing/GST-VAT rules | P08–P11 |
| Employment | Offer/termination compliance, payroll statutory | P12 (HITL-heavy) |
| Sector packs | HIPAA-class, lending, etc. via Regulatory Watchdog config | P14 |

### 9.7 The Expanded HITL Checkpoint Catalog (18)
`before_high_value_email_dispatch` · `before_contract_esignature_routing` · `before_outbound_payout_above_band` · `before_high_liability_clause_acceptance` · `before_self_evolving_code_promotion` *(the five from v1)* + `before_public_statement` · `before_regulatory_filing` · `before_employment_offer` · `before_termination_or_offboarding_action` · `before_price_change_beyond_band` · `before_bulk_data_deletion` · `before_bank_detail_change_acceptance` · `before_vendor_activation_on_kyb_flags` · `before_refund_above_band` · `before_discount_above_band` · `before_incident_public_disclosure` · `before_autonomy_level_promotion` · `before_new_channel_binding`.

**Evidence-based autonomy promotion:** the Learning System tracks per-entity HITL approval rates; when an entity sustains ≥ N approvals with ≥ 98% unedited acceptance over a rolling window, Pragya *proposes* raising its autonomy level (checkpoint 17) — the human always ratifies the promotion. Autonomy is earned, monitored, and reversible.

---

## 10. Economics, Budget Hierarchy & the KPI Tree (New in v2)

### 10.1 The Budget Hierarchy
A perpetual Loop cannot run on a single `max_cost_usd`. v2 defines cascading, cycle-refreshed envelopes reconciled with the platform wallet (functional doc §14):

```
LOOP (Sheel)      monthly envelope, e.g. $2,000  ── set by owner via Pragya
  └─ PROCESS      envelope % of loop (see §15)   ── e.g. P03 Acquisition 25%, P06 Support 15%
       └─ AGENT   daily ceiling + per-run cap    ── inherits entity `intelligence.max_cost_per_step_usd`
            └─ RUN platform thresholds apply     ── $0.50/$0.05/$0.02/$0.01 minimums (functional doc §14.3)
```

Rules: envelopes refresh on cycle (Chronos); a Process at 80% of envelope triggers a Pragya notification; at 100% it downshifts (router prefers cheap models, defers batch work) before pausing non-critical runs — **P14 Guardrails and P17 Incidents are never paused by budget**. All spend attributes to Process → arc → KPI, enabling true **cost-per-outcome** ROI (cost per qualified lead, per resolved ticket, per collected invoice).

> **Design pointer (2026-07-18, closes register A6):** "never paused" is mechanical, not exempt — P14/P17's envelope share is **carved out as a pre-funded reserve** at each cycle refresh (technical doc §20.4, `budget_envelopes.reserved_usd`). The platform's hard wallet floor is unchanged: an empty wallet stops everything and triggers the emergency HITL + dunning path. No free execution exists.

### 10.2 The KPI Tree (Loop → Process → Agent)

**Loop-level (owner's dashboard, reported by Pragya):** revenue growth · gross margin · net revenue retention · CAC & CAC-payback · DSO · runway days · cSAT/NPS · compliance status · **loop health** (signal-coverage %, HITL backlog age, autonomy-distribution, cost-per-outcome trend).

**Process-level (illustrative):**

| Process | Primary KPIs |
|---|---|
| P03 Acquisition | pipeline value, win rate, cost per opportunity, cycle time |
| P06 Resolve-to-Retain | first-contact resolution, containment rate, CSAT, cost per resolution |
| P08 Order-to-Cash | DSO, collection rate, dispute cycle time |
| P09 Source-to-Pay | 3-way-match exception rate, payment accuracy, vendor risk score |
| P10 Record-to-Report | days-to-close, reconciliation exception rate |
| P12 Hire-to-Retire | time-to-hire, offer-accept rate, onboarding completion, attrition signals |
| P14 Guardrails | obligations met %, open risks by severity, audit findings |
| P19 Sense-Decide-Optimize | optimization acceptance rate, KPI lift per change |

**Agent-level SLOs (every agent):** task success rate · escalation rate · HITL edit rate · complaint/correction rate · latency (channel-appropriate) · cost per completed task · critic-block rate. These SLOs are the raw material of §9.7 autonomy promotion and Learning System tuning — closing the wheel with *measured* discipline rather than asserted discipline.

---

## 11. The Human Operating Model (New in v2)

"Humans move up the stack" is now an org design. The residual human organization of a Sheel-run business has **five roles** (one person may hold several in an SME):

| Role | Owns | Interacts via |
|---|---|---|
| **Goal-Setter (Owner/CEO)** | Business goals, KPI targets, budget envelope, autonomy ratification | Pragya (conversation) |
| **Judgment Desk** | The HITL queue: approvals in §9.7, exception decisions | HITL cards (Rich Comm Broker / Generative UI) |
| **Relationship Principals** | High-trust human moments: key accounts, final-round interviews, investor meetings, crisis calls | Briefed by agents pre/post |
| **Quality & Ethics Steward** | Sampling agent output, complaint review, Karuna-conduct audits, autonomy-promotion sign-off | Evolve-arc dashboards |
| **Domain Experts (fractional)** | Legal counsel, CPA, security — engaged at named HITL checkpoints | Checkpoint-routed |

**RACI against the arcs:** humans are *Accountable* everywhere, *Responsible* only at HITL checkpoints and relationship moments; agents are *Responsible* for execution; Pragya is *Consulted/Informing* by default. **Change management:** the §14 roadmap runs each affected role through a shadow period (human does, agent drafts → agent does, human reviews → agent does, human samples), which is exactly the A0→A3 ladder applied to people's trust, not just to risk. Displaced effort is redirected into the Judgment Desk and Relationship roles before any headcount decision — the platform's own docs are explicit that the scarce input becomes judgment, not labor.

---

## 12. Resilience, Continuity & Exit (New in v2)

**Degradation ladder.** When components fail, Sheel downshifts rather than stops: (1) model/provider outage → router failover (functional doc §3.4); (2) tool/integration failure → Self-Healing pipeline, with the affected Skill marked degraded and dependent runs queued; (3) channel outage → Karuna gateways reroute (voice → callback promise via WhatsApp/email); (4) budget exhaustion → §10.1 downshift; (5) systemic anomaly → **loop-level kill-switch**: any Process can be paused by the owner through one sentence to Pragya; P14/P17 keep running in every degradation state.

**Business continuity.** The state that matters — CORTEX, episodic, semantic memory, the dynamic schema, execution ledger — lives in the tenant DB and is backup-scheduled; a restored tenant resumes with institutional memory intact (the inverse of human attrition risk). Suspend/resume semantics of the AgentLoop (technical doc §12.2) mean interrupted runs recover rather than restart.

**Exit & portability.** An AI-Native business must not be a hostage. Tenants can export: the knowledge base, the dynamic-schema entity definitions and records (JSON), all conversation and execution history, entity configurations (charters, personalities, IO contracts), and the ledger. Agents-as-configuration means the *institutional memory* is the tenant's asset, exportable by design.

---

## 13. Scaling Topologies (New in v2)

| Topology | When | Shape |
|---|---|---|
| **Single Sheel** | One company, one P&L (the default) | 1 `LOOP` owning P01–P19 |
| **Federated Sheels** | Business units / brands / regions with separate P&Ls or regulatory regimes | A parent `LOOP` row parenting child `LOOP` rows — **first-class as of v2.2** (the composition rule is formally amended; runtime rules in technical doc §17.6: one root Loop per tenant, per-Loop heartbeats/envelopes, parent rolls up children); each child runs its own arcs; the parent runs consolidated P10/P11/P14/P18/P19 and a group-level Pragya view |
| **Holding pattern** | Portfolio/holding companies | Parent Loop runs only Capital-&-Stakeholders + Sense-Decide-Optimize; subsidiaries are full Sheels; consolidation via shared reporting objects |

Federation rules: memory is shared *downward* (group policy, brand voice) and *aggregated upward* (KPIs, risk), never *sideways* by default — BU-to-BU visibility is an explicit policy choice. Model allow-lists and data-residency (functional doc §3.4) are set per child Loop, which is how a EU subsidiary and an India subsidiary coexist under one parent.

---

## 14. The Transformation Roadmap v2 — Risk-Tiered, Autonomy-Laddered

The six phases of v1 §9 (Meet → Ingest → Connect → Model → Deploy → Run & Evolve), driven by Pragya, are retained — and refined in v2.3 into the **nine-stage Pragya engagement flow** (functional doc §4.3): baseline research → working assumptions → deep ingestion → revised analysis → solution engineering *with* the user → blueprint finalization → integration → test/deploy → operate. v2 adds the missing logic: **what to automate first, and how fast to loosen the leash.**

**Risk-tiered sequencing.** Score each Process on (value × frequency) ÷ (blast radius of an error). Deploy in three waves — preceded by the day-one default:

* **Wave 0 (day 1): the Solo Pack — the smallest sellable Sheel.** *(v2.2, closes gap C7; pairs with the A4 starter bundles.)* The default first deployment for a solopreneur/SME is a cross-functional slice, not one function: **Sheel + Pragya (HUB) + 12 agents** — KAR-01/02/03 (voice, email, messaging gateways) · AGT-013 Inbound Deal Closer · AGT-015 Proposal & Quote · AGT-030 Omnichannel Care Orchestrator · AGT-035 Appointment Concierge · AGT-038 Accounts Receivable · AGT-046 Bookkeeping & Reconciliation · AGT-051 Cashflow Forecaster · AGT-068 Regulatory Watchdog · AGT-092 Scheduling Agent — activating thin slices of P03, P06, P08, P10, P14, and P19, all at A1. The seven starter bundles (functional doc §2.1) are the expansion units from here.

* **Wave 1 (weeks 1–4): high volume, low blast radius, instant ROI.** P01 Signal-to-Insight, P06 Resolve-to-Retain (draft-first), P03 top-of-funnel, P10 reconciliation (A1). These generate the learning signal that makes everything after them better.
* **Wave 2 (weeks 4–10): money-adjacent, band-protected.** P08 Order-to-Cash, P05 Order-to-Fulfilled, P02 campaigns, P12 sourcing/screening stages — at A2 with the §9.3 authority matrix doing the guarding.
* **Wave 3 (weeks 10+): judgment-heavy, HITL-dense.** P09 payouts, P13 contracts, P12 offers/offboarding, P14 filings, P18 — starting at A0/A1 and earning autonomy via §9.7.

**The adoption physics still hold:** because every wave shares the axle, each deployed Process makes the next one smarter — the opposite of bolting on another silo. The v1 rule of thumb (start with Cold-to-Closed Acquisition or Order-to-Cash) survives as the Wave 1/2 anchor choice.

---

## 15. Deployment Config v2 — Sheel (`LOOP` entity)

Corrects gap G12: adds `identity`, `observability`, budget hierarchy, KPI definitions with targets, escalation policy, Karuna enforcement, and all 19 Processes.

```json
{
  "name": "Sheel — Unified Business Engine",
  "version": "2.0.0",
  "type": "LOOP",
  "goal": "Run the entire business as one continuous, self-improving, AI-native loop — perceive, engage, orchestrate, fulfill, sustain, evolve — with Pragya as the single inward point of contact and Karuna as the governed outward face.",
  "identity": {
    "trinity": { "inward_face": "PRAGYA", "loop": "SHEEL", "outward_face": "KARUNA" },
    "karuna_profile_required_for_external_channels": true,
    "default_personality_floor": { "empathy_min": 0.6 }
  },
  "logic_gate": {
    "reasoning_mode": "auto",
    "breaker": { "scope": "process", "max_consecutive_blocks": 3, "on_trip": "quarantine_offender_and_raise_incident" }
  },
  "intelligence": {
    "mode": "auto",
    "allow_list": ["babybuddha-fast", "babybuddha-reasoning", "claude-opus", "gpt", "gemini", "glm", "qwen", "mistral"],
    "router": "complexity_and_cost_optimized"
  },
  "loop_config": {
    "arcs": ["PERCEIVE", "ENGAGE", "ORCHESTRATE", "FULFILL", "SUSTAIN", "EVOLVE"],
    "hub_agent": "agt-pragya-account-manager-uuid",
    "karuna_gateways": ["kar-voice", "kar-email", "kar-messaging", "kar-chat", "kar-social"],
    "kpis": [
      { "key": "revenue_growth_mom", "target": ">= 0.05", "source": "P03+P07+P08" },
      { "key": "gross_margin", "target": ">= 0.60", "source": "P10" },
      { "key": "net_revenue_retention", "target": ">= 1.05", "source": "P07" },
      { "key": "cac_payback_months", "target": "<= 12", "source": "P02+P03" },
      { "key": "dso_days", "target": "<= 45", "source": "P08" },
      { "key": "runway_days", "target": ">= 270", "source": "P11" },
      { "key": "csat", "target": ">= 4.5", "source": "P06" },
      { "key": "compliance_status", "target": "green", "source": "P14" },
      { "key": "signal_coverage_pct", "target": ">= 0.99", "source": "axle" },
      { "key": "hitl_backlog_age_hours", "target": "<= 24", "source": "axle" }
    ],
    "schedules": [
      { "trigger": "continuous", "purpose": "gateway intake + telemetry perceive (P01, KAR-*)" },
      { "trigger": "cron:daily", "purpose": "reconciliation + ledger (P10), collections (P08), guardrails sweep (P14)" },
      { "trigger": "cron:weekly", "purpose": "executive briefing + optimization (P19), vendor risk (P09)" },
      { "trigger": "cron:monthly", "purpose": "close + statutory (P10), budget refresh, investor pack (P18)" }
    ]
  },
  "hierarchy": {
    "child_process_ids": [
      "prc-signal-to-insight", "prc-awareness-to-demand", "prc-cold-to-closed-acquisition",
      "prc-partner-to-revenue", "prc-order-to-fulfilled", "prc-resolve-to-retain",
      "prc-renew-and-expand", "prc-order-to-cash", "prc-source-to-pay",
      "prc-record-to-report", "prc-plan-budget-forecast", "prc-hire-to-retire",
      "prc-draft-review-sign", "prc-continuous-guardrails", "prc-provision-and-maintain",
      "prc-idea-to-launch", "prc-incident-to-resolution", "prc-capital-and-stakeholders",
      "prc-sense-decide-optimize"
    ]
  },
  "governance": {
    "budget": {
      "cycle": "monthly",
      "loop_envelope_usd": "2000.00",
      "process_allocation_pct": {
        "prc-cold-to-closed-acquisition": 20, "prc-awareness-to-demand": 12,
        "prc-resolve-to-retain": 15, "prc-order-to-fulfilled": 12,
        "prc-order-to-cash": 6, "prc-source-to-pay": 5, "prc-record-to-report": 5,
        "prc-hire-to-retire": 5, "prc-continuous-guardrails": 6, "prc-signal-to-insight": 4,
        "prc-sense-decide-optimize": 4, "others": 6
      },
      "never_pause": ["prc-continuous-guardrails", "prc-incident-to-resolution"],
      "downshift_at_pct": 80
    },
    "autonomy": { "default_level": "A1", "promotion_policy": "evidence_based_hitl_ratified" },
    "authority_matrix_ref": "blueprint_v2#9.3",
    "sod_rules_ref": "blueprint_v2#9.4",
    "hitl_checkpoints": "blueprint_v2#9.7 (all 18)",
    "escalation": {
      "hitl_unanswered_hours": 24,
      "path": ["judgment_desk", "owner_via_pragya"],
      "incident_preemption": true
    },
    "timeout_ms": 0
  },
  "observability": {
    "trace_level": "step",
    "ledger_attribution": ["process", "arc", "kpi"],
    "audit_sampling_agent": "agt-internal-audit",
    "signal_coverage_audit": "weekly"
  },
  "io_contract": {
    "input_schema": {
      "type": "object",
      "properties": {
        "business_goals": { "type": "array", "items": { "type": "string" } },
        "kpi_targets": { "type": "object" },
        "budget_envelope_usd": { "type": "string" },
        "connected_systems": { "type": "array", "items": { "type": "string" } },
        "knowledge_sources": { "type": "array", "items": { "type": "string" } },
        "jurisdiction_packs": { "type": "array", "items": { "type": "string" } }
      },
      "required": ["business_goals", "budget_envelope_usd"]
    },
    "output_schema": {
      "type": "object",
      "properties": {
        "active_processes": { "type": "integer" },
        "kpi_snapshot": { "type": "object" },
        "autonomy_distribution": { "type": "object" },
        "budget_utilization": { "type": "object" },
        "optimizations_applied": { "type": "array", "items": { "type": "string" } },
        "hitl_pending": { "type": "array", "items": { "type": "string" } },
        "open_incidents": { "type": "array", "items": { "type": "string" } }
      }
    }
  }
}
```

> **Note on `timeout_ms: 0`:** 0 means *no run timeout* — intentional and valid only for the `LOOP` tier, whose lifetime is the company's. All child tiers carry finite timeouts.
>
> **Note on `breaker` (v2.1 — closes gap A11):** the pre-critic circuit breaker never halts the Loop. `"scope": "process"` means three consecutive blocks trip only the offending Process/Agent run: it is quarantined and an `incident.governance` signal is raised (P17); Sheel and all sibling Processes keep running. (v2.0 reused the agent-level `max_consecutive_blocks: 3` at Loop scope, which would have let three blocked actions anywhere halt the entire company.)

---

## 16. Summary — The One-Loop Doctrine, Now Complete

* A traditional business is **silos**. A digitized business is **silos with software between them**. An AI-Native business is **one loop** — and v2 makes that loop *specifiable*, not just describable.
* **Sheel** is one `LOOP` entity turning through six arcs; its seamlessness is now mechanical — one object model (§3.2), one signal contract (§3.3) — not rhetorical.
* **Pragya** is the wisdom inward; **Karuna** is now a deployable, enforceable outward membrane (§2.3), not a metaphor. *Wise within, disciplined throughout, compassionate outward.*
* Every tier is enumerated: **1 Loop · 19 Processes · 100 Agents · 62 Skills · 37 Actions** (§7). Every department — including the fifteen v1 forgot — has a home (§4). Every name used anywhere resolves to a registered entity *(re-verified in v2.1 after closing gaps A3/A5)*.
* Discipline is now *architected*: autonomy is earned on evidence (§9.2, §9.7), authority is banded (§9.3), duties are segregated (§9.4), the world-facing surface is hardened (§9.5), spend cascades through a real budget hierarchy (§10), humans hold a designed role (§11), failure degrades gracefully (§12), and growth has topologies (§13).
* And because the **Learning System** closes the wheel, the loop you deploy from this blueprint is the slowest, dumbest version you will ever run. It only compounds from here.

> **One business. One loop.** *Pragya knows. Sheel acts. Karuna cares.*




