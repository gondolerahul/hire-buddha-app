# Phase 12 — Consolidation, Extraction & the Next Autonomy Step

> **Author:** Agentic Systems Architecture
> **Date:** 2026-06-02
> **Status:** Plan. Not yet executed.
> **Predecessor:** Phase 11 (shipped, `in-canary`). See `docs/phase11/`.
> **Frame of reference:** the platform's *current, implemented* state — not the
> pre-implementation review in `docs/phase11/review/`.

---

## 0. Why Phase 12 exists

Phase 11 was a 12-week programme that rebuilt the agent kernel:

* a real **AgentLoop** (`core/agent_loop.py`) with perceive → strategize →
  pre-critic → act → observe → post-critic → reflect → decide,
* seven **executors** and four **reasoning modes**,
* a **Critic Pipeline v2** with calibration,
* a **Meta-Agent Board** (7 roles + Meta-Intelligence Tree + Skill Library),
* **Memory v2** canonical (four CORTEX domain trees + dreaming),
* a **Planner v2** (multi-candidate + invariants + judge + bandit),
* a **Tool/Cost** layer with attribution and resilience.

It shipped **additively**: every new path is reachable, every legacy path is
gated behind a feature flag for rollback, and two master switches
(`agent_loop.enabled`, `meta_agent.board_routing`) remain **OFF** pending
per-company canary. The codebase is now *correct but double-stacked*: new and
old run side by side, everything carries `p11`/`P11`/`phase11` canary labels,
and ~15 follow-up items were explicitly deferred.

**Phase 12 turns the canary build into the production build.** It is mostly
*consolidation and extraction*, plus one genuine capability step (tooling +
Meta-Agent). It is deliberately **not** another ground-up redesign.

---

## 1. Scope (as requested)

| # | Theme | Plan file |
|---|-------|-----------|
| 1 | Phase 11 consolidation: de-prefix, legacy removal, restructure | [`01_phase11_consolidation.md`](./01_phase11_consolidation.md) |
| 2 | Robust headless-browser / terminal / sandbox + per-tenant persistent containers | [`02_sandbox_browser_terminal.md`](./02_sandbox_browser_terminal.md) |
| 3 | Decompose the video-generation tool into generate / edit-merge / sound | [`03_video_tool_decomposition.md`](./03_video_tool_decomposition.md) |
| 4 | Extract CORTEX into a pip-installable package | [`04_cortex_package.md`](./04_cortex_package.md) |
| 5 | Pending Phase 11 items + planned-for-Phase-12 gaps | [`05_pending_and_gaps.md`](./05_pending_and_gaps.md) |
| 6 | Make the Meta-Agent the world's best agent-designing entity | [`06_meta_agent_evolution.md`](./06_meta_agent_evolution.md) |
| 7 | Other observations worth implementing | [`07_additional_observations.md`](./07_additional_observations.md) |
| — | Sequencing, dependencies, risk, KPIs | [`08_roadmap_and_sequencing.md`](./08_roadmap_and_sequencing.md) |

Read order: **00 → 05 → 01 → 06 → 02/03/04 (parallel) → 07 → 08**.
(`05` first because it inventories what's already half-done; `01` then plans the
cleanup; `06` is the highest-leverage capability work; `02/03/04` are
independent tracks; `08` sequences everything.)

---

## 2. Cross-cutting architectural decisions

These are the decisions the brief explicitly asked for. They bind every plan
file below. Each is argued in full in `01` and `06`; summarized here so the
rest of the docs can reference a single source of truth.

### D-1 — Keep the entity hierarchy. Decouple "type" from "execution".

> *"Should we keep the hierarchy of entities, or — since one AgentLoop can now
> run a whole hierarchy — do away with it?"*

**Decision: keep `ACTION / SKILL / AGENT / PROCESS` as a declarative contract;
do NOT collapse to a single mega-agent.**

The hierarchy is one of the platform's genuine strengths (the Phase 11 review
called the entity contract "more expressive than most open-source platforms").
But its *meaning* changes:

* **Before P11:** entity type ≈ execution engine. `engine_type` was a property
  of the entity; AGENT+RECURSIVE behaved differently from PROCESS+DAG.
* **After P11:** the AgentLoop's **Strategist picks the executor per
  iteration**. Type no longer dictates *how* you run.
* **In P12:** type becomes purely about **capability surface, governance scope,
  reuse granularity, and meta-cognition defaults** (see the per-level matrix in
  `06`). It is the unit the Meta-Agent reasons about, composes, and the
  Skill Library promotes into.

So: one loop, many entities. The hierarchy is the *org chart*; the AgentLoop is
the *worker*. We delete the `engine_type`-as-behavior-switch (already vestigial
under the loop) but keep the four types as a typed, governed contract.

### D-2 — Demote static planning from backbone to optional prior.

> *"Should we do away with static planning?"*

**Decision: keep `static_plan` as an optional authored *hint/guardrail*; make
dynamic planning the default and the backbone.**

Planner v2 (`plan_generator.py` + `plan_invariants.py` + `plan_judge.py` +
bandit priors) is strictly better than the old "LLM emits a plan, reconcile
against static." But static plans still earn their place for:

* **Compliance / deterministic workflows** (a regulated PROCESS that must run
  exactly these steps in this order),
* **Cheap, well-understood ACTIONs/SKILLs** where dynamic planning is pure
  overhead,
* **Seeding** the PlanGenerator with a strong prior (authored steps become a
  candidate the judge can pick or improve).

Concretely: `static_plan` stops being executed verbatim and instead becomes a
**named candidate** fed into `PlanGenerator`, plus an invariant
(`plan must cover authored compliance steps` when `static_plan.binding=true`).
This finishes the `PlannerService.reconcile` v2 swap that Phase 11 deferred.

### D-3 — Keep ReAct + CoT per-step; retire per-entity Reflection mode; reframe ToT as an opt-in debate executor.

> *"Are reasoning modes (CoT / Reflection / ReAct / ToT) still relevant?"*

**Decision:**

| Mode | Verdict | Rationale |
|------|---------|-----------|
| **ReAct** | **Keep — the workhorse.** | Tool-using turn loop; nothing replaces it. |
| **Chain-of-Thought** | **Keep, but per-step and cheap.** | Useful for THOUGHT steps; the loop itself is "CoT between steps," so in-step CoT is for the leaf reasoning only. |
| **Reflection** | **Retire as a per-entity mode; fold into the loop.** | The AgentLoop has a first-class `Reflector` stage every iteration. A separate per-step "reflection reasoning mode" now duplicates it and double-bills. |
| **Tree-of-Thoughts** | **Reframe as an opt-in `DebateExecutor`.** | Single-LLM ToT rarely pays off. The real value (explore alternatives, judge) maps onto CORTEX as a multi-persona *debate workspace* — make it an executor the Strategist selects for high-stakes/high-uncertainty steps, not a per-entity setting. |

And the structural fix the review flagged (F-16): **reasoning mode is chosen
per-step by the Strategist, not hard-coded per entity.** A cheap TOOL_CALL
should never pay for Reflection; a high-stakes synthesis step can opt into
debate.

### D-4 — Remove flag-gated legacy *after* telemetry; keep genuine adapters.

> *"Completely remove old legacy code, or merge selectively?"*

**Decision: selective.** Three buckets:

1. **Delete (after ≥30 days of zero-traffic telemetry):** `_review_step_output`
   v1 critic body, `MemoryRouter` body, `MetaReviewer` shim, `CortexRouter`
   alias, v1 critic compat flag, `engine_type` behavior branch. These are pure
   duplicates of shipped v2 paths.
2. **Keep as real adapters (not legacy debt):** `LegacyEpisodicReader`
   (first-run top-up is a permanent migration concern, not a temporary shim),
   the `schemas/__init__.py` and `orm/__init__.py` re-export facades (they are
   the stable public surface).
3. **Keep, generalize, rename:** the `static_plan` path (per D-2) — not deleted,
   repurposed.

The de-prefix work (`p11`/`P11`/`phase11` → neutral names) happens *with* the
deletions so the diff is one coherent "canary → GA" cutover, not two passes.

---

## 3. The shape of Phase 12

```
Stage 0  Telemetry gate + canary flip          (weeks 1–2)
         └─ flip agent_loop.enabled + board_routing per company; watch risks
Stage 1  Consolidation & de-canary             (weeks 2–5)   ── file 01, 05
         └─ delete flag-gated legacy; strip p11/P11; reconcile-v2; tool git mv
Stage 2  Meta-Agent v5 + tooling               (weeks 4–9)   ── file 06, 02, 03
         └─ board GA, tool synthesis, per-tenant containers, video split
Stage 3  CORTEX extraction                     (weeks 6–14)  ── file 04
         └─ Protocols → package → cutover (parallel track)
Stage 4  Hardening, KPI, DX                     (weeks 12–15) ── file 07, 08
```

Stages 1–4 overlap; the dependency graph and a per-week breakdown live in
`08_roadmap_and_sequencing.md`.

---

## 4. Non-goals for Phase 12

* **No new orchestration paradigm.** The AgentLoop is the kernel; we deepen it,
  we do not replace it.
* **No microservices split** (except the CORTEX *package*, which still runs
  in-process via adapters — it is a packaging boundary, not a network boundary).
* **No public-API breakage** of the entity JSON schema or HTTP routes beyond the
  documented de-prefix (which ships with redirect/alias shims).
* **No RL over the Strategist** — needs ≥3 months of telemetry (P13).

---

## 5. How success is measured

Phase 12 inherits the Phase 11 KPI dashboard
(`infra/dashboards/phase11/*.sql`) and adds consolidation-specific exit gates.
Full table in `08`. The headline gates:

* **De-canary complete:** zero references to `p11`/`P11`/`phase11` outside
  `docs/`; zero flag-gated legacy bodies in tree; `agent_loop.enabled` and
  `meta_agent.board_routing` default **ON**.
* **No regression:** goal-hit rate, cost-per-success, false-pass rate hold at
  or beat Phase 11 canary targets across the cutover.
* **CORTEX v0.1.0** published; host consumes it as a dependency with no
  `src/ai/memory/` code other than thin adapters.
* **Meta-Agent v5:** ≥1 Meta-Intelligence rule per run in 80% of runs; tool
  synthesis produces ≥1 accepted tool in canary.
