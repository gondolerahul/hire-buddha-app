# Increment 7 — Scale & Enterprise — Charter Stub

> **Status:** Stub — deepened just-in-time. A clarifying-questions round with Rahul precedes the full docs.
> **Parent:** [build_roadmap.md](../build_roadmap.md) §4, Increment 7 (L–XL). **Prerequisite:** Increments 1–5 in production with real tenant load (B14 may pull earlier if tenant count demands).

## Goal

The platform grows from one VM and one Loop per tenant to federated topologies, production-grade infrastructure, and regulated-industry readiness.

## Scope (from the roadmap)

* **FED at scale** — child Loops under Sheel (the §17.6 rules shipped in Inc 1; real topologies + group Pragya view built here).
* **B14 production topology** — HA, horizontal scaling units, multi-region; Redis into the architecture diagram; replaces the single-VM dev-box topology.
* **Compliance packs** — incl. **D4** employment-AI gates (EU AI Act / NYC LL144: bias audits, candidate disclosure, human-review requirements). **Hard gate: the Talent bundle does not GA without D4.**
* **BB** — BabyBuddha/OmniBuddha post-training runs (open-weight framing per B15): must pass the §22.4 admission gate; falls out of the router as just another registry row if it wins, costs nothing if it doesn't.

## Register findings to close here

B14 (GA topology), D4 (employment-AI regulation).

## Known open questions

1. Scaling unit: per-service horizontal scaling vs cell-based (a cell = N tenants with their sandboxes + DB pool)?
2. Region strategy driven by data-residency demand (which market first)?
3. BabyBuddha base-model choice, training-data rights policy, and serving economics — the full B15 build path.
