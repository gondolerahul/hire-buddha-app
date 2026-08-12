# Increment 6 — The Self-Improving Platform — Charter Stub

> **Status:** Stub — deepened just-in-time; the hardest-gated increment. A clarifying-questions round with Rahul precedes the full docs. **GenUI additionally requires the Design Gate** (owner directive): a dedicated, deep design-and-brainstorming phase producing a detailed, unique design before any development.
> **Parent:** [build_roadmap.md](../build_roadmap.md) §4, Increment 6 (XL). **Prerequisite:** Increment 5 (EVX gates operational — nothing self-modifying ships without them).

## Goal

The "Week 12 > Week 1" promise, measured by the §22 harness rather than asserted.

## Scope (from the roadmap, in order)

1. **LEARN** — unified learning store on the signal bus; charter tuning under EVX gates + the B10 risk policy (reward-hacking constraints: Karuna bounds are hard constraints, drift monitors, explicit cross-tenant learning policy).
2. **SEGA** — self-evolution GA: independent-suite rule + canary + B11 blast-radius limits (**tenant-scoped only**; global tool changes stay on the platform-admin pipeline). Builds on the shipped tool-synthesis pipeline.
3. **GENUI** — a **completely new frontend built from scratch**, hard-gated behind the Design Gate; the shipped React app remains the surface until GenUI replaces it.
4. **Dynamic-schema evolution triggers** (technical §10.2) — agent-proposed fields, learning-driven def promotion, learning-promoted expression indexes (§19.3).

## Register findings to close here

B10 (learning-system risk blindspots), B11 (self-evolution blast radius), D3 (full context-taint tracking — the §18.6 trust field shipped in Inc 1 is the down-payment).

## Known open questions

1. Design Gate process: who participates, what artifact ("detailed, unique design") exits the gate, and what evaluation admits it?
2. Cross-tenant learning policy (B10): pooled with disclosure vs strictly per-tenant with cold start.
3. Learning-store shape: extend the shipped signal bus + CORTEX Intelligence trees vs a dedicated `learning_signals` store.
