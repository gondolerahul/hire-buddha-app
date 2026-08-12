# Increment 1 — One-Loop Foundations: Overview

> **Document Class:** Increment Design & Implementation Plan (index)
> **Author:** Buddha Cognitive Lab (drafted by Claude, decisions by Rahul)
> **Created:** 2026-07-18 · **Status:** Draft — for brainstorm review before development begins
> **Parent:** [build_roadmap.md](../build_roadmap.md) §4 (Increment 1, size L)
> **Design authority:** [product_technical_documentation.md](../product_technical_documentation.md) §10, §17–§20, §23–§24 (v3.0.5). The workstream docs below are **self-contained** — a developer should not need the 1,300-line technical doc open — but if a workstream doc and the technical doc ever diverge, the technical doc is corrected first and the workstream doc follows.

---

## 1. Goal

Build the four foundations everything after the MVP hangs on — the signal bus, the governance core, the tenant schema + data plane, and the Loop runtime with real budget accounting — such that at the end of the increment this demo runs end-to-end:

> **Exit demo:** a Sheel row exists; a webhook becomes a signal; a trigger fires a Process run; the PolicyGate raises a HITL card in the existing approvals panel; the Loop heartbeat rolls up cost into its envelope; and two concurrent runs **cannot** double-spend the same wallet dollar.

**Register findings:** none open — B6, B8, and E3 were closed at design level (technical §23–§24, decisions 2026-07-18). This increment *executes* those designs. The §24.4 retrieval upgrade may trail into Increment 2.

## 2. Workstreams

| # | Doc | Workstream | Design §§ | Depends on |
|---|---|---|---|---|
| 1 | [01_sig_signal_bus.md](./01_sig_signal_bus.md) | **SIG** — Signal bus + trigger registry | §18 | nothing unbuilt |
| 2 | [02_gov_governance.md](./02_gov_governance.md) | **GOV** — Typed governance, checkpoint registry, PolicyGate, deploy validators | §20.1–.3, .5, .6 | nothing unbuilt |
| 3 | [03_sch_tenant_schema.md](./03_sch_tenant_schema.md) | **SCH** — HBS seed, records/links, record service, tenant data plane, memory scoping | §10.3–.5, §19, §23.1–.2, §23.4, §24.1–.3 | SIG (proposal/conflict signals) |
| 4 | [04_loop_env_runtime_budget.md](./04_loop_env_runtime_budget.md) | **LOOP+ENV** — LOOP tier, heartbeat, watchdog, budget envelopes, wallet holds | §17, §20.4, §23.3 | SIG (schedule signals), GOV (envelope ref in governance block) |

## 3. Build Order

The roadmap calls SIG/GOV/SCH "parallel roots with separate hands"; with one development stream we serialize by dependency weight:

1. **SIG** (branch `inc1/sig`) — the keystone; SCH and LOOP both emit/consume signals.
2. **GOV** (branch `inc1/gov`) — pure schema + one pipeline stage; independent of SIG except for the §18.6 trust field the PolicyGate reads (mock-able if built first, real once SIG merges).
3. **SCH** (branch `inc1/sch`) — the largest workstream (includes the tenant data-plane container).
4. **LOOP+ENV** (branch `inc1/loop-env`) — last, because the heartbeat dispatches schedule signals (SIG), rolls up into envelopes (GOV's governance block references them), and the wallet-hold demo needs the credit-service changes.

Each branch merges to master only when its workstream's acceptance criteria (listed per doc) pass and the eval/parity gates are green.

## 4. Decisions Already Taken (do not re-open during build)

Recorded here so build sessions don't re-litigate them:

* **One Sheel root Loop per tenant**; the 7 legacy Loops are starter bundles (A4, 2026-07-18).
* **A Loop is a scheduler/aggregator, never a run** — no LOOP wallet threshold exists by design (B1).
* **Postgres is the bus** — outbox + `FOR UPDATE SKIP LOCKED` + Arq; no new infrastructure (B2).
* **Uniform Postgres+pgvector-in-sandbox per tenant**, tiered hibernation; built in Increment 1, not staged (B6 + Rahul, 2026-07-18).
* **Owner writes, others propose**; CAS versioning; wallet holds with graceful finish + bounded debt (B6/E3).
* **Share knowledge, not habits** memory scoping (B8).
* **Signals stay control-plane only** in v1 (§23.4 settles the §10.5 open question).
* **HBS spine field definitions:** Claude drafts the 27-object field appendix; Rahul reviews before it becomes seed data (2026-07-18).
* **No new frontend in Increment 1** — API-only; the PolicyGate's HITL cards surface in the existing approvals panel; admin UI ships with Increment 2 (2026-07-18).

## 5. Standing Rules (from the roadmap, applied to this increment)

1. **Nothing ships flag-OFF into the sellable path.** New subsystems may sit dark (unwired) during the build, but the increment does not close with any of its capabilities behind a default-OFF flag.
2. **Docs move with code.** On merge of each workstream, flip the relevant ⬜→✅ maturity tags in the three target-state docs and note it in this folder.
3. **Eval/parity gates are non-negotiable.** The PolicyGate inserts a new stage into the critic pipeline — parity goldens must be re-captured deliberately, never silently regenerated.
4. **Autonomy starts at A1 everywhere.**

## 6. Brainstorm Decisions (Rahul, 2026-07-19)

The open-questions round is closed; outcomes are recorded per doc in each workstream's final section. Cross-workstream outcomes:

1. **Heartbeat topology** — single platform scanning cron, **simple but configurable** (platform-level scan interval setting + per-Loop `heartbeat_interval_s`); per-tenant cron registration deferred to fleet scale (B14, Inc 7).
2. **Package layout** — confirmed: new `src/ai/signals/`, `src/ai/tenant_schema/`, `src/ai/loop/` packages mirroring existing `ai/` conventions (`models.py` + service modules + README, `mypy --strict` from day one).
3. **Sheel seeding** — explicit data migration (visible, auditable).

4. **KB/CORTEX placement** — **control plane, permanently** (03 §5 Q3): hot-path latency, hibernation economics, and zero migration outweigh volume-portability; the tenant export bundle includes a KB+memory dump as the portability rider. Technical doc amended to v3.0.6. **All Increment-1 questions are now closed — the increment is clear to build.**
