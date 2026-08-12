# HireBuddha — Build Road Map: Dependency Graph & Increment Plan

> **Document Class:** Product Development Road Map (the *path*; the other docs in this folder are the *destination*)
> **Author:** Buddha Cognitive Lab (drafted by Claude, decisions by Rahul)
> **Created:** 2026-07-18 · **Status:** v1.0 — closes register findings **F2** (dependency graph) and **F3** (MVP cut)
> **Inputs:** [codebase_current_state_analysis.md](./codebase_current_state_analysis.md) (what exists) · [product_functional_documentation.md](./product_functional_documentation.md) v3.0.2 + [product_technical_documentation.md](./product_technical_documentation.md) v3.0.3 + [Blueprint v2.2](./Unified%20Business%20Process%20%26%20Agent%20Template%20Blueprint%20v2.md) (the target) · [roadmap_gap_register.md](./roadmap_gap_register.md) (open findings)
> **Decisions incorporated:** one Sheel + 7 starter bundles (A4) · Solo Pack default deployment (C7) · per-object system of record (B4) · impact-tiered Pragya auth (D1) · post-trained open-weight BabyBuddha/OmniBuddha (B15) · LOOP federation first-class (A8)

---

## 1. The Goal, Stated Once

> **Sell the Solo Pack:** Sheel (one root Loop) + Pragya + 12 agents running thin slices of P03/P06/P08/P10/P14/P19 at autonomy A1, on a governed signal fabric, for a solopreneur/SME — then expand by bundles.

Everything below is ordered to reach that sellable moment fastest, without building anything that has to be thrown away for the later increments (router, Pragya, self-evolution, federation).

## 2. Foundations Already In Place

The road map *builds on*, and does not re-plan, what ships today (baseline §3): the **AgentLoop** as sole engine with async suspend/resume · **CORTEX v2** (4 domains, dreaming, trust) as the `hb-cortex-memory` package · the **Meta-Agent Board** (7 roles) with tool synthesis flag-OFF · **billing** (TB formula, 3-bucket wallets, thresholds, cost attribution) · **channels** (Gemini Live + Azure Realtime voice over Twilio/Tata, WhatsApp ×2, IMAP/SMTP email, campaigns) · **HITL** (approvals + panel) · the **eval/parity harnesses** · the **MCP adapter** · **per-tenant sandbox containers** with egress allow-listing (flag-OFF) · 4-level tenancy, key vault, suspension middleware.

## 3. The Dependency Graph (F2)

```mermaid
graph TD
    subgraph SHIPPED["✅ Shipped foundations"]
        AL[AgentLoop]
        BD[Meta-Agent Board]
        CH[Voice / WhatsApp / Email]
        EH[Eval + parity harnesses]
        MCP[MCP adapter]
        SBX[Sandbox runtime flag-OFF]
    end

    OPS0["Inc 0 — Ops & flag debt<br/>(push, PyPI, sandbox S7, board GA)"]

    SIG["SIG — Signal bus + trigger registry (§18)"]
    GOV["GOV — Governance core:<br/>typed block + checkpoints + PolicyGate + validators (§20.1–.3, .5)"]
    SCH["SCH — Tenant schema seed + links (§10, §19)"]
    LOOP["LOOP — Loop runtime lite (§17)"]
    ENV["ENV — Budget envelopes + protected reserve (§20.4)"]
    KAR["KAR — Karuna gateway agents"]
    SOLO["🎯 SOLO PACK — the MVP<br/>(12 agents, Wave-0 processes, bundle packaging)"]

    AUTH["AUTH — Inward-channel auth (§11.3)"]
    PRAGYA["PRAGYA v1 — account-manager runtime (§11)"]
    SOR["SOR — System of record + mirrors (§21)"]
    CONN["CONN — Connector catalog build-out (§6.6 via MCP)"]

    EVX["EVX — Eval extensions:<br/>independent suites, canary, model gate (§22.2–.4)"]
    RTR["RTR — Model router v1→v2 (§3.3)"]
    LEARN["LEARN — Unified learning store + charter tuning"]
    SEGA["SEGA — Self-evolution GA (§9/§12)"]
    GENUI["GENUI — Generative UI (§8)"]
    FED["FED — Federation at scale (§17.6)"]
    BB["BB — BabyBuddha / OmniBuddha admission (§3.1)"]

    OPS0 --> SIG
    SIG --> LOOP
    LOOP --> ENV
    GOV --> ENV
    SIG --> KAR
    GOV --> KAR
    CH --> KAR
    KAR --> SOLO
    LOOP --> SOLO
    ENV --> SOLO
    BD --> SOLO
    SCH --> SOLO
    GOV --> AUTH
    AUTH --> PRAGYA
    SIG --> PRAGYA
    SCH --> SOR
    SIG --> SOR
    MCP --> CONN
    CONN --> SOR
    EH --> EVX
    EVX --> SEGA
    SBX --> SEGA
    RTR --> BB
    EVX --> BB
    SIG --> LEARN
    EVX --> LEARN
    SCH --> GENUI
    LEARN --> GENUI
    LOOP --> FED
```

**Reading the graph — three structural facts:**

1. **SIG (the signal bus) is the keystone.** The Loop runtime, Karuna gateways, SoR sync, Pragya's reporting, and the unified learning store all hang off it. It is deliberately first after ops debt — and it has *no* unbuilt prerequisites (Postgres + Arq ship today).
2. **GOV and SCH are parallel roots.** Neither depends on anything unbuilt; both are pure-schema starts. They can proceed alongside SIG with separate hands.
3. **Nothing on the MVP path depends on the router, Pragya, self-evolution, GenUI, or BabyBuddha.** The expensive, speculative subsystems are all post-MVP by construction — the MVP risk is integration work on proven parts, not research.

## 4. The Increment Plan (F3)

Sizing is relative (S < M < L < XL), not calendar time. Each increment ends in a state you can demo, and Increment 2 ends in a state you can *sell*.

> **Per-increment working docs** live in subfolders of this directory — [increment-1/](./increment-1/00_overview.md) (full design + implementation plan) and charter stubs for [increment-2](./increment-2/00_charter.md) through [increment-7](./increment-7/00_charter.md), each deepened just-in-time when its turn comes (with a clarifying-questions round first).

### Increment 0 — Ops & Flag Debt *(S–M, mostly ops)*
Clear the "built but not live" backlog (`docs/phase12/OPS_REMAINDER.md`): push pending commits · publish `hb-cortex-memory` to PyPI and delete the in-repo copy · sandbox image CVE scan + registry publish + S7 canary→default-ON · Meta-Agent board GA flip · frontend polish items. **Outcome:** the shipped platform *is* the baseline document, with no flag-gated asterisks on the MVP path.

### Increment 1 — One-Loop Foundations *(L)*
The three parallel roots, then the Loop:
* **SIG** — `signals` + `trigger_registry`, outbox insert, SKIP-LOCKED dispatcher, sweeper, parked/dead states, completion hook (§18).
* **GOV** — typed governance block, `hitl_checkpoint_defs` (18 seeded), PolicyGate ahead of the Pre-Critic, deploy-time SoD/Karuna validators (§20.1–.3, .5).
* **SCH** — `tenant_entity_defs` + `tenant_records` + `tenant_record_links`, initialized with the **predefined HireBuddha Business Schema** (27 canonical objects as the spine; module skeletons per §10.3), hosted in the **sandbox-resident tenant DB** — a uniform Postgres+pgvector container per tenant with tiered hibernation (§23.4), under the master/tenant segregation of §10.5. The record service enforces owner-writes/others-propose + CAS versioning (§23.1–§23.2); the credit service gains wallet holds (§23.3); memory scoping lands per the §24 matrix. Evolution triggers still deferred to Increment 6.
* **LOOP-lite** — `LOOP` enum + root-Loop index + `loop_runtime` + heartbeat/watchdog crons; then **ENV** budget envelopes with the protected reserve (§17, §20.4).

**Register gaps:** none open — B6, B8, and E3 closed at design level (technical §23–§24, decisions 2026-07-18); this increment *executes* those designs. The §24.4 retrieval upgrade may trail into Increment 2.
**Outcome (demo):** a Sheel row exists; a webhook becomes a signal, a trigger fires a Process run, the PolicyGate raises a HITL card, the heartbeat rolls up cost — and two concurrent runs cannot double-spend the same wallet dollar.

### Increment 2 — 🎯 The Solo Pack (the MVP cut) *(L–XL)*
* **KAR** — Karuna gateway agents (voice, email, messaging) as templates over the shipped channels, entering work through SIG, with the Karuna-profile deploy check live.
* **The 12 Solo Pack agents** (Blueprint §14 Wave 0) seeded via the Board, plus the six Wave-0 processes (thin P03/P06/P08/P10/P14/P19) authored as PROCESS entities.
* **Bundle packaging** — the 7 starter bundles as named activation sets; Solo Pack as the default.
* **Onboarding** — wizard-driven (Pragya-less) setup: connect channels, upload KB, confirm governance defaults (all A1).

**Register gaps to close here:** C1 (process design sheets for the six Wave-0 processes — the template for the other 13), C3 (HITL capacity: per-checkpoint SLAs for the checkpoints Solo Pack actually fires), C5 (dunning/degraded mode — money is on the line once it's sellable), D6 (consent/DNC registry — the AR chaser and deal closer make outbound calls), B7 (realtime-voice vs loop reconciliation — the voice gateway forces it), B13 (platform-spend budget class), E1/E2/E4 (idle-cost model, free-credit abuse controls, fee edge cases — pricing must be right to sell).
**Outcome (sellable):** a solopreneur activates the Solo Pack, and it answers calls/email/WhatsApp, qualifies and quotes, books appointments, chases invoices, reconciles, and reports — governed at A1 with HITL.

**Explicitly NOT in the MVP:** the model router (static per-task config stays), Pragya (the wizard + dashboards serve), SoR mirrors (HireBuddha masters everything the pack touches; connectors read-only), dynamic-schema evolution, GenUI, self-evolution GA, federation, BabyBuddha. Every one of these is additive later — none is load-bearing for the sale.

### Increment 3 — Pragya v1 *(L)*
**AUTH** (§11.3 tiers + step-up) → **PRAGYA v1**: the **nine-stage engagement flow** (functional §4.3 — baseline research → assumptions → deep ingestion → revised analysis → solution engineering → blueprint finalization → integration → test/deploy → operate), implemented as conversational orchestration over the same APIs the wizard uses. Stages 1–5 need per-stage scripts/prompts (the discovery protocol's flow closed C8; the scripts are built here). **Register gaps:** C4 (autonomy demotion triggers), C6 (KPI metric definitions — Pragya reports them, so they must be defined). **Outcome:** the "talk to your account manager" experience, safely authenticated, running a consulting-grade onboarding.

### Increment 4 — The Connected Business *(L–XL, parallelizable per connector)*
**CONN** — the §6.6 catalog built out MCP-first (accounting/bank feed first: it deepens the Solo Pack's AR/bookkeeping immediately; then calendar, e-sign, enrichment, payouts behind the authority matrix) → **SOR** — per-object mastering, mirrors, write-back, `sync.conflict` flow (§21). **HBS module depth** (§10.3) lands here too: field-level completeness for Accounting/HRMS/ERP/Legal so the standalone-system guarantee holds for tenants with no external software. **Register gaps:** D2 (per-agent credential scoping — SoD becomes real here or never), C2 (human-task step type — physical fulfillment appears with real operations). **Outcome:** the tenant's existing systems join the loop without a migration — or HireBuddha *is* all their systems.

### Increment 5 — The Intelligence Engine *(L)*
**B12 first** (model registry versioning/regions/price dating — the router is blind without it) → **RTR v1** (registry + static rules + `routing_decisions` attribution) → **RTR v2** (complexity scoring, wallet-aware downshift) → fleet expansion (GLM/Qwen/Mistral behind **D5** data-flow disclosure + conservative default allow-list) → **EVX** (§22.2–.4) wired as the admission gate. **Outcome:** the §3.3 cost story becomes real and auditable.

### Increment 6 — The Self-Improving Platform *(XL, gated hardest)*
**LEARN** (unified learning store on the signal bus; charter tuning under EVX gates + B10 risk policy) → **SEGA** (self-evolution GA: independent-suite rule + canary + B11 blast-radius limits; tenant-scoped only) → **GENUI** — per owner directive, a **completely new frontend built from scratch**, hard-gated behind the **Design Gate**: a dedicated, deep design-and-brainstorming phase that must produce a detailed, unique design before development begins; the shipped React app remains the surface until GenUI replaces it → dynamic-schema evolution triggers (§10.2). **Outcome:** the "Week 12 > Week 1" promise, measured by the §22 harness rather than asserted.

### Increment 7 — Scale & Enterprise *(L–XL)*
**FED** at scale (child Loops, group Pragya view) · **B14** production topology (HA, regions — pull earlier if tenant count demands) · compliance packs incl. **D4** employment-AI gates *(hard gate: the Talent bundle does not GA without D4)* · **BB** — BabyBuddha/OmniBuddha post-training runs and must pass §22.4 admission; falls out of the router as just another registry row if it wins, costs nothing if it doesn't.

## 5. Open Register Findings → Increment Map

| Increment | Register findings to close in it |
|---|---|
| 1 | ~~B6, B8, E3~~ — all closed at design level (technical §23–§24, 2026-07-18); Increment 1 executes the designs |
| 2 | C1, C3, C5, D6, B7, B13, E1, E2, E4 |
| 3 | C4, C6 (C8 closed by the §4.3 nine-stage flow; its per-stage scripts are Inc-3 build work) |
| 4 | D2, C2 |
| 5 | B12, D5 (+ EVX docs side of B9 done) |
| 6 | B10, B11, D3 (full taint; §18.6 down-payment ships in Inc 1) |
| 7 | B14, D4 |

Every remaining open finding has exactly one home. When an increment starts, its row above is the checklist; the register is updated as each closes.

## 6. Standing Rules for All Increments

1. **Nothing ships flag-OFF into the sellable path.** A capability is either GA'd in its increment or it isn't in the increment (the Increment-0 lesson).
2. **Docs move with code.** Each increment updates the maturity tags (⬜→🚩→✅) in the three target-state docs — the F1 matrix stays true forever.
3. **The eval/parity gates are non-negotiable** on the AgentLoop path, and §22.2's independent-suite rule applies to *anything* self-modified from Increment 6 on.
4. **Autonomy starts at A1 everywhere** and rises only through the §9.7 evidence process — including for platform-built (Solo Pack) agents.

---

## Change Log

| Date | Change |
|---|---|
| 2026-07-18 | v1.0 — initial road map: dependency graph (F2) + increment plan with MVP cut at the Solo Pack (F3). |
| 2026-07-18 | v1.1 — owner directives folded in: SCH is the predefined HBS in a sandbox-resident tenant DB with master/tenant segregation (Inc 1, depth in Inc 4); Pragya v1 implements the nine-stage engagement flow (Inc 3; C8 closed at protocol level); GenUI is a ground-up new frontend behind a mandatory Design Gate (Inc 6). |
| 2026-07-18 | v1.2 — B6/B8/E3 closed at design level (technical §23–§24): uniform Postgres-in-sandbox data plane with tiered hibernation, owner-writes/others-propose, wallet holds with graceful-finish + bounded debt, share-knowledge-not-habits memory scoping. Increment 1 now has zero open design questions; §24.4 retrieval upgrade may trail into Increment 2. |
| 2026-07-18 | v1.3 — Increment 0 complete (ops debt cleared); per-increment doc subfolders created: increment-1/ full plan (4 workstream docs + overview), increment-2..7/ charter stubs. Inc-1 build decisions recorded: data plane built in Inc 1 (not staged), HBS spine drafted-then-reviewed, no new frontend in Inc 1. |
| 2026-07-19 | v1.4 — Increment-1 brainstorm closed: all open questions answered (decisions recorded in each increment-1/ doc §5). Notable: email ingest is SIG's first channel producer; PolicyGate passes unset authority bands through until Inc-2 seeding; uniform configurable default envelope; **KB + CORTEX memory are control-plane permanent** (technical doc v3.0.6 — §10.4/§10.5/§23.4/§24.4 amended; export bundle includes KB+memory dump). Increment 1 is clear to build. |
