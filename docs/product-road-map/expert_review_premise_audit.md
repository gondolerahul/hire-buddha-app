# HireBuddha — Expert Review: The Premise Audit

> **Document Class:** Independent Expert Review (agentic AI systems · business process re-engineering · process excellence)
> **Author:** External review (Claude), commissioned by Rahul
> **Date:** 2026-07-18
> **Scope:** All six docs in `docs/product-road-map/` + codebase baseline.
> **Relationship to [roadmap_gap_register.md](./roadmap_gap_register.md):** This is a *second-order* audit. The register audited the docs for internal consistency and mechanism-completeness and did that well (49 findings, 29 closed). It could not, by construction, audit its own **premises** — the assumptions every finding sits on top of. This document does that. New finding IDs are prefixed `PR-`. Where I amplify an existing register item I say so.

---

## 0. The one-paragraph verdict

The conceptual architecture is genuinely strong and the self-audit is better than most teams ever produce. But the register's success created a blind spot: it made the *documents* consistent without ever testing whether the *concept* survives contact with reality. "29 of 49 closed" reads as "60% sound," when in fact the closed items are almost entirely **internal-consistency fixes and design paragraphs for unbuilt subsystems** — while the load-bearing premises (that an emergent JSONB schema can be a business's only system of record; that LLMs are reliable enough to run finance/legal/HR autonomously; that a solopreneur can supply the supervision the model requires; that the loop economics close) were never findings at all, because they were assumptions. **The biggest risks in this concept are not in the gap register, and cannot be, because they are the things the register took as given.**

---

## 1. The ten findings that should change the plan

Ordered by how much they threaten the concept, not by how easy they are to fix.

| # | Finding | Class | Register status |
|---|---|---|---|
| PR-1 | The "standalone system" claim quietly commits you to building an ERP + GL + CRM + HRMS on emergent JSONB | Concept / scope | **New** (C6 touches an edge) |
| PR-2 | The residual-human operating model assumes an org the ICP (solopreneur) does not have | BPR / adoption | **New** |
| PR-3 | Legal agency: who is liable when an autonomous agent contracts, pays, or represents? | Compliance / existential | **New** |
| PR-4 | The agent's own sandboxed code executor is co-located with the tenant's entire business DB | Security / architecture | **New** (amplifies D2/D3) |
| PR-5 | External side effects are not idempotent, even though signals are | Agentic correctness | **New** (amplifies B2) |
| PR-6 | The 8-stage loop multiplies LLM calls ~5–6× per unit of work — nets against the router's savings | Economics | **New** (amplifies E1) |
| PR-7 | No compensating-transaction / saga model for business actions that fail partway | Agentic correctness | **New** |
| PR-8 | Shared memory is a poisoning surface; promoted "rules" have no ground-truth gate | Learning safety | **New** (amplifies B10/D3) |
| PR-9 | DR posture (24h RPO) is fine for an add-on, catastrophic for a business's only system | Resilience | **New** (amplifies B14) |
| PR-10 | Big-design-up-front for unvalidated, research-heavy subsystems; no build-vs-buy | Process-of-work | **New** |

---

## 2. Concept-level findings (the premises)

### PR-1 — "Run your entire business on HireBuddha alone" is a different, much larger product than an agent platform. *(Concept, Critical)*

The v3.0.4 owner directive (functional §13.1, technical §10.3, §21.3) promotes the dynamic schema from "a place agents jot down entities they encounter" to **"a complete, predefined HBS deep enough that a tenant with no external systems runs their entire business on HireBuddha alone… CRM, Accounting, HRMS, ERP/Operations, Legal, Marketing, Planning."** Stored as JSONB records in `tenant_records` with a typed link table.

This is not a schema decision; it is a decision to build, on an EAV/JSONB substrate, the products that Workday, SAP, Salesforce, and QuickBooks each took thousands of engineer-years to build. Specifically:

- **Accounting is not a data shape; it is a set of invariants.** A general ledger needs double-entry integrity (every posting balances), immutable closed periods, an audit trail that cannot be rewritten, statutory report formats (GST/VAT/GAAP/IndAS), and reconciliation guarantees. A JSONB store validated "against the def's current fields" (technical §19.4) enforces *shape*, not *accounting law*. An agent that can `object.change_proposed` a ledger entry, or a schema that "evolves additively," is structurally incompatible with the immutability a book of accounts requires. The register's C6 notes "gross margin requires COGS capture" — that's the tip; the real finding is that **an emergent schema cannot be a system of record for regulated financial data.**
- **The standalone guarantee and the SoR design (§21) are in tension.** §21 is careful and good: per-object mastering, mirror + write-back, master-wins conflicts. But it exists precisely *because* real businesses keep their books in real accounting software. The standalone guarantee says "you don't need that software." You cannot simultaneously be a serious accounting system *and* a mirror layer that assumes the real accounting system lives elsewhere. Pick one per module.

**Recommendation:** Split the HBS explicitly into (a) **operational objects** HireBuddha can legitimately master on a flexible schema (leads, tickets, projects, campaigns, activities) and (b) **regulated/system-of-record objects** (ledger, payroll, contracts) where HireBuddha is a **mirror-and-orchestrate layer over a purpose-built store or a connected system**, never the emergent JSONB master. Drop or heavily qualify the "one and only system" language for regulated modules — it is a compliance and credibility liability.

### PR-2 — The human operating model assumes an organization the customer doesn't have. *(BPR / adoption, High)*

Blueprint §11 defines five residual human roles: Goal-Setter, Judgment Desk, Relationship Principals, Quality & Ethics Steward, Domain Experts (fractional legal/CPA/security). The stated ICP (functional §1.1) is **solopreneurs and SMEs** — and the Solo Pack targets a single owner.

For that owner, all five roles collapse into one person who by definition has no spare hours (that scarcity is *why they're buying*). The model therefore relocates work rather than removing it: it converts "doing the work" into "supervising, approving, sampling, and ethics-auditing a workforce of 12+ agents" — plus fielding HITL cards, ratifying autonomy promotions, and reviewing Karuna-conduct. **The register's C3 (HITL capacity) and C7 (SME-fit) each see one facet; the premise-level finding is that the product's own governance model may impose more supervisory load than the target buyer can supply**, which inverts the value proposition for exactly the segment being sold to.

**Recommendation:** Model the owner's *time budget* as a hard constraint the way wallet balance is. Design the Solo Pack to minimize approvals-per-week (aggressive batching of HITL, "digest" approvals, conservative default autonomy that trades a little value for near-zero supervision), and measure "owner minutes/week" as a first-class product KPI. If the Solo Pack needs more than a few owner-minutes a day, it fails its own market.

### PR-3 — Legal agency and liability are unaddressed, and they may be existential. *(Compliance, Critical)*

The authority matrix (Blueprint §9.3) lets agents autonomously execute contracts up to $2,000 TCV, issue refunds, make payouts, and send binding communications. Nowhere do the docs address:

- **Can an AI agent legally bind the company to a contract?** Whose intent/authority does an AI-initiated e-signature represent, and is it enforceable? (This varies by jurisdiction and is actively contested.)
- **Liability allocation** between platform and tenant when an agent makes a costly error, an unauthorized representation, a discriminatory hiring decision (see D4), or a payment to a fraudster it was social-engineered into trusting.
- **Regulated-advice boundaries:** agents drafting tax filings (Statutory Reporting Agent), giving what amounts to financial or legal guidance to customers, or the Collections agent operating under FDCPA-class rules.

D4 (employment AI) is the only regulatory item flagged, and it's open. But the broader agency question underpins the *entire* "autonomous business" thesis. If AI agents cannot lawfully take the actions the authority matrix grants them without a human principal's ratification, then A2+ autonomy for money/contract/employment actions is legally void and the product collapses back to A1 (propose-only) for everything that matters — which is a very different, much less differentiated product.

**Recommendation:** Get a real legal opinion on AI agency for the specific action categories, per launch jurisdiction, *before* Increment 2 sets pricing on the autonomy story. Treat "which action categories may ever exceed A1" as a legal input to the roadmap, not a product toggle.

## 3. Agentic-architecture findings the register missed

### PR-4 — The agent's sandboxed code executor sits next to the tenant's whole business. *(Security, Critical)*

Two v3.0.4 decisions collide:
1. The tenant's **entire business DB** (HBS records, KB, CORTEX, contracts, PII) lives in a **docker-backed sandbox volume** (technical §10.4).
2. Agents wield a **Sandbox Code Executor and Terminal tool** that "run arbitrary Python / shell inside a sandbox" (functional §6.5), and a **Playwright headless browser**.

The existing egress proxy (`egress_proxy.py`, `NetworkPolicy.ALLOWLIST`) governs **outbound internet**. It says nothing about whether arbitrary agent-authored code, running in the tenant's sandbox, can reach the **co-located tenant Postgres** on the sandbox network. Given prompt injection is an *open* item (D3) and counterparty content is treated as data-but-parsed-by-LLMs, the threat is concrete: **a single injected instruction → agent runs code → code connects to the local business DB → exfiltrates or destroys the entire company's records.** This is a categorically worse blast radius than the register's D2/D3 contemplate (they're about credentials and single-run injection, not agent-code-adjacent-to-the-master-DB).

**Recommendation:** The code-execution sandbox and the tenant data plane must be **separate network/security domains** even though both are "in the tenant's sandbox." The DB must be reachable only by the platform's record service over an authenticated channel, never by the agent's arbitrary-code runtime. Make this an explicit Increment-1 security invariant with a red-team test, not an assumed property.

### PR-5 — Signals are idempotent; the real world is not. *(Correctness, High — amplifies B2)*

Technical §18.4 correctly specifies at-least-once delivery with idempotent *consumption* (a re-delivered signal can't spawn a second run). But the thing that actually matters — the **external side effect** — has no idempotency layer. A run that crashes *after* sending an email / dialing a number / posting a payout but *before* committing its terminal state will, on resume or re-dispatch, **do it again.** Suspend/resume (technical §12.2) makes this more likely, not less, because runs are designed to restart mid-flight.

There is no **effect ledger / idempotency key on outbound actions** anywhere in the design. "Exactly-once" is guaranteed for the cheap internal thing (signal→run) and left unguaranteed for the expensive, irreversible external thing (payout, email, call).

**Recommendation:** Every side-effecting Action must carry an idempotency key derived from `(run_id, step_id, effect_hash)` and record the effect in a durable ledger *before* and *after* the external call, with the connector honoring the key where the provider supports it (Stripe, DocuSign do). This is a prerequisite for any A2 money action, and it belongs in Increment 1/2, not later.

### PR-6 — The loop's own LLM-call multiplier undercuts the router's cost story. *(Economics, High — amplifies E1)*

The 8-stage loop runs multiple LLM calls per *single step* (confirmed in code: `strategist.py` alone drives most of the reasoning, plus pre-critic, post-critic, reflect, and the planner/judge/bandit machinery). Realistically a single "the agent did one thing" costs on the order of **5–6 model calls**, before you count the Debate executor (multi-candidate + judge) or replans.

The functional doc's headline economic claim (§3.3, §14.2) is that the router makes HireBuddha "a fraction of the cost" of a flat frontier-model product because 80–90% of steps don't need a frontier model. That is a *per-call* saving. It is silently **multiplied against a 5–6× per-step call count** that the architecture imposes and that competitors using a single-shot prompt do not pay. Nobody has netted the router's per-call savings against the loop's per-step call inflation. It is entirely possible the loop architecture costs *more* per business outcome than a cheaper-architecture competitor even with a worse router.

**Recommendation:** Before pricing (Increment 2, E1), instrument **model-calls-per-completed-business-outcome** on real Solo-Pack flows and publish the net. If the multiplier is real, the mitigations are architectural (collapse stages for low-stakes steps — which also solves B7's voice-latency problem — and reserve the full 8-stage loop for high-stakes ones). The router is not sufficient on its own.

### PR-7 — There is no way to unwind a business process that fails halfway. *(Correctness, High)*

The docs have excellent *code* rollback (tool_versions, §9/§12) and *run* recovery (suspend/resume, §12.2). They have **nothing for business-action rollback.** Order-to-Cash sends an invoice → applies a late fee → opens a collections case → *then* the payment turns out to have arrived on day one. Hire-to-Retire provisions accounts, sends an offer, notifies the team → the candidate declines. These are multi-step, multi-effect, cross-agent sequences with real external consequences, and there is no **saga / compensating-transaction** concept anywhere — no notion of "for effect X, the compensating effect is X⁻¹," no orchestration that can drive a partial process backward.

For a perpetual autonomous loop this is not optional: partial failures are the *normal* case, not the exception.

**Recommendation:** Introduce a compensation contract at the Action/Skill tier (each side-effecting Action declares its compensating Action, or "irreversible — requires HITL to proceed"). Process design sheets (register C1) must include the exception-and-unwind path, not just the happy path. This reframes C1 from "documentation debt" to "correctness prerequisite."

### PR-8 — Shared, self-promoting memory is an unguarded poisoning surface. *(Learning safety, High — amplifies B10/D3)*

Two designs combine into a risk neither addresses alone:
- **Memory is tenant-shared** for Knowledge and Episodic domains, written by "channel handlers / gateways" from counterparty content (technical §24.1).
- **The Learning System promotes rules** from reflections into Intelligence memory that then **gate planning** (dreaming engine, confirmed-rule lifecycle).

So counterparty-supplied content can land in shared Knowledge memory, and agent reflections can be promoted into rules that steer *future* behavior — with **no ground-truth validation of a promoted rule, no decay/challenge mechanism, and injection defense still open (D3).** A patient adversary can (a) inject content that persists into shared memory and resurfaces across agents (past the single-run defenses D3 contemplates), or (b) induce a spurious "lesson" that gets promoted and then silently biases the loop. Because the same platform critics judge whether a rule "worked," this is another self-grading loop (the B9 pathology, applied to memory).

**Recommendation:** (1) Provenance/trust already exists (`source_trust_scores`) — extend it so counterparty-trust content can populate Knowledge only through an explicit, gated path, never directly. (2) Promoted rules need a challenge/decay lifecycle and a ground-truth check (does following the rule correlate with a *real* outcome, not a critic's opinion?). (3) Reserve "share knowledge, not habits" (§24) is the right instinct — but make the sharing of *knowledge* itself trust-gated.

## 4. BPR / process-excellence findings

### PR-9 — DR posture is sized for an add-on, not for "your only system." *(Resilience, High — amplifies B14)*

Technical §23.4: "nightly encrypted logical dump + weekly volume snapshot." That's a **~24-hour RPO.** For a SaaS layer that sits on top of the customer's real systems, fine. For a system the docs insist is **the tenant's one and only system of record** (§21.3), losing up to a day of invoices, payments, and contracts is a business-ending event — and the customer has no other copy by design. The standalone guarantee and the backup cadence are mutually incompatible.

**Recommendation:** If you keep the standalone claim, regulated data needs continuous WAL archiving / PITR and a stated RPO/RTO SLA, per tier. If you don't want to fund that, that's another reason to scope regulated modules out of "standalone" (PR-1).

### PR-10 — No baseline metrics capture means the ROI story is unfalsifiable. *(BPR, Medium)*

Core BPR discipline: measure the *as-is* cost and cycle time before you re-engineer, so improvement is provable. The nine-stage Pragya flow (functional §4.3) captures the as-is *process map* (good) but **not as-is metrics** — current cost-per-lead, current DSO, current time-to-hire. Yet the entire pitch ("compare an AI call to a human rep," "Week 12 > Week 1," cost-per-outcome dashboards) rests on before/after deltas that have no "before." A12 softened the "measurably smarter" language; the deeper gap is that there's **no baseline-capture step in the methodology at all.**

**Recommendation:** Add a baseline-metrics capture to Pragya stage 3/4 (from connected systems where possible, owner estimate otherwise) and store it as the denominator for every ROI/KPI claim. Without it, C6's KPI definitions have nothing to compare against.

### PR-11 — 19 canonical processes may not fit the messy long tail of real SMEs. *(BPR, Medium — sharpens C1)*

The 19 processes are clean textbook value streams. A dental practice, a freight broker, and a wedding photographer share almost none of their real operational control flow, exceptions, or domain rules — and a *process is not just its data shape* (which is all the dynamic schema captures). The register's C1 treats this as "author the step-level sheets"; the sharper premise-level question is whether canonical processes **generalize** at all, and whether the Meta Agent generating novel processes on the fly (unproven, high-blast-radius) is a safe fallback. Betting the deployment model on "the Meta Agent will just build whatever's missing" is the single least-validated leap in the concept.

**Recommendation:** Validate on 3–5 deliberately dissimilar real SMEs during Increment 2 whether the canonical processes + Solo Pack actually fit, or whether each needs so much Meta-Agent generation that the "starter bundle" premise breaks. This is a go/no-go signal for the whole packaging strategy.

### PR-12 — Counterparty acceptance of full automation is assumed, not tested. *(BPR / market, Medium)*

The blueprint reserves humans for "Relationship Principals" (key accounts, final interviews, crisis calls) but the *default* is automate-then-escalate for everyone else. There is no treatment of whether **vendors will negotiate payment terms with a bot, candidates will accept AI-only screening, or B2B buyers will tolerate an AI closing the deal** — and in high-trust relationships, visible full automation can *destroy* the relationship value the business depends on. This is a demand-side/market-acceptance risk orthogonal to whether the tech works.

**Recommendation:** Karuna's disclosure requirement (§9.6) is honest but doubles as a market test — measure counterparty drop-off when the AI discloses itself, per channel and per process, and let that data set which processes should default to human-fronted.

## 5. Security / compliance findings

### PR-13 — Training BabyBuddha on tenant traces is stated as the plan and unflagged as the risk. *(Compliance, High — sharpens D5)*

Functional §3.1: BabyBuddha is "post-trained on the platform's own agent traces." Agent traces contain tenant business data, customer PII, and financial records. Training a **shared** model on cross-tenant traces is a serious data-governance and contractual problem (data-residency, purpose limitation, the possibility of one tenant's data influencing another's model behavior or leaking through it). D5 flags it as an open question; §3.1 states it as the build path. **The build path and the open risk contradict each other, and the build path currently wins by default.**

**Recommendation:** Make "no cross-tenant training without explicit opt-in and de-identification" a stated invariant now, and treat BabyBuddha's training-data rights as a legal precondition of the model existing — not a detail deferred to Increment 7.

### PR-14 — Default allow-list includes every provider, including data-sovereignty-sensitive ones. *(Compliance, Medium — this is D5, re-emphasized)*

Already in the register (D5, open), but worth escalating: the shipped Sheel deployment JSON (Blueprint §15) ships `allow_list` with **Zhipu (GLM) and Alibaba (Qwen) on by default.** For any EU/regulated tenant that is an immediate DPA/sovereignty problem, and it's baked into the canonical example config where it will be copied. Fix the *example* even before the policy engine exists.

## 6. Process-of-work findings (how the docs themselves are being built)

### PR-15 — "Resolved (design)" is being counted as progress on a research-heavy product. *(Meta, High)*

~15 of the 29 "closed" findings are **"Resolved (design)"** — a design paragraph was written for a subsystem that is 0% built and whose premises are unvalidated. The register is scrupulous about labeling this, but the **cumulative framing ("29 of 49 closed," "Increment 1 has zero open design questions")** manufactures confidence that the hard part is behind you. It isn't: writing `wallet_holds` and `tenant_record_links` schemas in a canonical doc is the *easy, cheap* part. The expensive, uncertain parts (PR-1, PR-3, PR-6, PR-11) aren't "open findings" because they were never framed as findings — they're premises.

**Recommendation:** Track a second metric alongside "findings closed": **"premises validated"** — each with a cheap experiment (a GL-integrity spike, a legal opinion, a real-SME fit test, a model-calls-per-outcome measurement). A closed design finding is a *plan*; a validated premise is *evidence*. Only the latter de-risks the concept.

### PR-16 — Detailed schema is being frozen into canonical docs before any spike validates it. *(Meta, Medium)*

Technical §17–§24 specify tables, columns, and indexes in commit-ready detail for subsystems no one has built. For a product this research-heavy, that is big-design-up-front, and it creates commitment bias: once `signals`, `budget_envelopes`, and `tenant_record_links` are "the design" in the canonical manual, implementation reality that contradicts them meets resistance. The register even notes designs will be "the checklist" for increments — i.e., the doc leads the code.

**Recommendation:** Demote §17–§24 from "specification" to "design intent," and let Increment-1 spikes rewrite them. Treat the first implementation as the thing that *proves* the design, not the thing that *conforms* to it.

### PR-17 — No build-vs-buy anywhere, for a scope that is a decade of in-house work. *(Meta / strategy, High)*

The docs assume building everything in-house: the model router (vs LiteLLM/OpenRouter), the agent kernel (already built, fine), realtime voice (vs Vapi/Retell/Pipecat), the ERP/GL/CRM/HRMS (vs… not building them — PR-1), *two* proprietary foundation models (BabyBuddha, OmniBuddha), connectors to ~30 third-party APIs (§6.6, vs an iPaaS/MCP marketplace). There is no make/integrate/buy decision recorded for any of it. The register's F-series demanded a roadmap and got one, but the roadmap sequences **in-house builds** without ever asking whether each should be built at all.

**Recommendation:** Add an explicit build/integrate/buy column to each roadmap increment. The MVP especially should integrate ruthlessly (the codebase already has an MCP adapter — lean on it) and reserve in-house build for the genuine differentiator (the loop + memory + governance), not the commodities (routing, voice transport, connectors, and — emphatically — accounting).

---

## 7. Smaller but real (quick list)

- **PR-18 (Medium):** No end-to-end causal tracing across the signal graph. Per-run trace spans exist, but when an autonomous business does the wrong thing, forensics require following cause across many signals, proposals, memory reads, and router choices spanning multiple runs. There's no cross-run causal view. Operability gap for anything autonomous.
- **PR-19 (Medium):** Time/scheduling semantics unspecified — timezones per counterparty, business-hours calendars, DST, and the interaction between **DB hibernation (§23.4) and time-critical scheduled signals** ("call at 2pm" that parks until a cold tenant DB wakes could fire late and breach Karuna's contact-window compliance).
- **PR-20 (Medium):** The router's `utility()` function is undefined and self-graded. A cost-optimizing learned utility will systematically under-route to cheap models that fail, and "success" is judged by the same platform's critics — a quality death-spiral invisible to itself. Same pathology as B9, applied to routing; not called out for the router.
- **PR-21 (Low):** "No seams" is rhetorically asserted then rebuilt as SoD boundaries, authority bands, and Karuna membranes (§9.4, §9.3, §2.3). Departmental seams often exist for *good* reasons (specialization, risk isolation, checks and balances). The doctrine dissolves departments then re-erects every boundary as governance — worth stating honestly rather than as a contradiction.
- **PR-22 (Low):** Trust bootstrapping vs. instant value. A0→A4 autonomy earned on evidence requires a long supervised runway generating clean signal; the sales promise is value in "<10 minutes." These pull opposite directions and the tension is never acknowledged in the go-to-market framing.

---

## 8. What to actually do with this

The register's increment plan is sound *as a build order for the mechanisms.* What it's missing is a **premise-validation track running in parallel**, cheap and early, gating the expensive builds:

1. **Before Increment 2 pricing:** measure model-calls-per-business-outcome on a real flow (PR-6); build the idle+loop cost model for real (E1).
2. **Before selling any A2 money/contract action:** a legal opinion on AI agency per jurisdiction (PR-3); an effect-idempotency + compensation design (PR-5, PR-7).
3. **Before the standalone-system claim ships:** decide which HBS modules are genuinely master-able on JSONB and which are mirror-only (PR-1); size DR to match (PR-9).
4. **During Increment 2:** fit-test the canonical processes on 3–5 dissimilar real SMEs (PR-11); measure owner-supervision-minutes/week as a product KPI (PR-2); measure counterparty drop-off on disclosure (PR-12).
5. **As a security invariant in Increment 1:** separate the agent-code sandbox from the tenant data plane, red-teamed (PR-4).
6. **Continuously:** track *premises validated*, not just *findings closed* (PR-15); demote frozen schemas to design intent (PR-16); add build/integrate/buy to every increment (PR-17).

None of this contradicts the existing plan. It de-risks the parts of the plan the existing audit was structurally unable to see.

> **The register made the documents true to each other. This review asks whether they're true to the world.** The concept is strong enough to be worth holding to that higher standard.
