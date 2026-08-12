# Increment 5 — The Intelligence Engine — Charter Stub

> **Status:** Stub — deepened just-in-time. A clarifying-questions round with Rahul precedes the full docs. Note: unlike Inc 1–4, the router's detailed design (§3.3 target state) is **not yet written at build depth** — a design pass precedes implementation here.
> **Parent:** [build_roadmap.md](../build_roadmap.md) §4, Increment 5 (L). **Prerequisite:** Increment 2 (traffic to learn from); EVX pieces build on the shipped eval harness.

## Goal

The §3.3 cost story becomes real and auditable: complexity-scored, wallet-aware model routing over a governed fleet, with the eval harness as the admission gate.

## Scope (from the roadmap, in order)

1. **B12 first** — model registry versioning/regions/price effective-dating (the router is blind without it).
2. **RTR v1** — registry + static rules + `routing_decisions` attribution (replaces `model_task_defaults` per-task defaults).
3. **RTR v2** — complexity scoring, wallet-aware downshift.
4. **Fleet expansion** — GLM/Qwen/Mistral behind **D5** data-flow disclosure + a conservative default allow-list.
5. **EVX** — eval extensions (technical §22.2–.4, design done): independent-suite rule, canary rollout on the shipped per-company flag pattern, model-change non-inferiority gate — wired as the admission gate for every fleet change.

## Register findings to close here

B12 (model registry too coarse), D5 (data-flow disclosure, subprocessor/DPA story, conservative allow-list) — plus the EVX docs side of B9.

## Known open questions

1. Router placement: inside the LLM adapter layer (`ai/llm/`) vs a stage the planner consults — the current static `model_task_defaults` seam suggests the adapter.
2. Complexity scoring approach for RTR v2 (heuristic features vs small-model classifier) and its own eval golden set.
3. Which open-weight providers/hosts for the fleet expansion given D5 sovereignty constraints.
