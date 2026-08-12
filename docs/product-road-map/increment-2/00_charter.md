# Increment 2 — 🎯 The Solo Pack (the MVP cut) — Charter Stub

> **Status:** Stub — deepened just-in-time when Increment 1 nears completion. A clarifying-questions round with Rahul precedes the full design/implementation docs (same process as Increment 1).
> **Parent:** [build_roadmap.md](../build_roadmap.md) §4, Increment 2 (L–XL). **Prerequisite:** Increment 1 complete (SIG, GOV, SCH, LOOP+ENV live).

## Goal

The sellable moment: a solopreneur activates the Solo Pack and it answers calls/email/WhatsApp, qualifies and quotes, books appointments, chases invoices, reconciles, and reports — governed at A1 with HITL.

## Scope (from the roadmap)

* **KAR** — Karuna gateway agents (voice, email, messaging) as templates over the shipped channels, entering work through SIG, with the Karuna-profile deploy check live.
* **The 12 Solo Pack agents** (Blueprint §14 Wave 0) seeded via the Meta-Agent Board + the six Wave-0 processes (thin P03/P06/P08/P10/P14/P19) authored as PROCESS entities.
* **Bundle packaging** — the 7 starter bundles as named activation sets; Solo Pack default.
* **Onboarding** — wizard-driven (Pragya-less): connect channels, upload KB, confirm governance defaults (all A1).
* Carried from Inc 1: the §24.4 retrieval upgrade; admin UI for signals/triggers/envelopes (Inc-1 frontend deferral); Solo Pack seeding must give every channel-facing entity explicit authority bands and real `sod_class` values (Inc-1 GOV decision: unset bands pass through, so the seeding closes that window); resolve `owner_process_id` process codes to the seeded PROCESS entity ids (Inc-1 SCH decision).

## Register findings to close here (the largest open batch)

C1 (process design sheets for the six Wave-0 processes), C3 (per-checkpoint HITL SLAs), C5 (dunning/degraded mode), D6 (consent/DNC registry), B7 (realtime-voice vs loop reconciliation), B13 (platform-spend budget class), E1 (idle-cost model — takes the measured Inc-1 tenant-DB idle cost as input), E2 (free-credit abuse controls), E4 (fee edge cases).

## Explicitly NOT in the MVP

Model router, Pragya, SoR mirrors (connectors read-only), dynamic-schema evolution, GenUI, self-evolution GA, federation, BabyBuddha.

## Known open questions (grow this list as they arise)

1. C1 process design sheets: authored per-process before agent seeding, or iteratively per wave-0 slice?
2. B7: which loop stages collapse for the realtime voice profile, and how does a live call warm-transfer to a Process agent?
3. Onboarding wizard scope: how much of the nine-stage Pragya flow does the wizard preview (it becomes Pragya's API surface in Inc 3)?
