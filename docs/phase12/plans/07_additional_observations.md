# 07 — Additional Observations & Improvements

> Scope item 7. Things worth doing that the brief didn't name explicitly, found
> while auditing the post-Phase-11 codebase. Ordered by leverage. Each is sized
> so it can be slotted into `08`'s schedule or deferred without blocking the
> headline tracks.

---

## 1. Adopt MCP as the external-tool protocol

The runtime already exposes MCP servers (Apollo, a data-enrichment server,
Claude-in-Chrome, computer-use, an MCP registry with
`search_mcp_registry`/`suggest_connectors`). The platform's own tool system is
bespoke (`Tool` base + `ToolRegistry`). These are converging on the same idea.

**Proposal:** add an **`MCPToolAdapter`** that wraps any MCP server's tools as
first-class platform `Tool`s, so:

* Entities can use MCP-exposed connectors (Apollo, etc.) through the normal tool
  path, with the normal cost/resilience/attribution wrappers.
* The Meta-Agent's `RegistrySearchService` can surface MCP tools as REUSE
  candidates ("there's already an Apollo connector — don't synthesize one").
* Tool synthesis (`06` §2) gains a cheaper option than writing code: *discover
  and bind an existing MCP server* via `suggest_connectors` before synthesizing.

Scope it: read-only adapter first (list + invoke MCP tools), per-company
allow-list, cost attribution `MCP`. Defer write-heavy/destructive MCP tools
behind HITL. This is the retrospective's "MCP / external tool integration" theme,
made concrete and bounded.

---

## 2. Budget-aware REACT (close the last review gap)

`Budget` is typed, tracked, and surfaced in the perception payload — but the LLM
inside REACT is not *bound* by it; only the engine enforces it via exception
(review gap #9). Result: the all-too-common mode where a run blows its budget on
the last steps despite being 90% done.

**Proposal:** thread `Budget.pressure` into the REACT/Strategist prompt as a
*soft constraint the model must plan within*: when `pressure > 0.7`, the
Strategist's `Move` must prefer cheaper executors/shorter plans, and the prompt
explicitly says "you have $X / N turns left — finish, don't expand." Pair with a
hard engine cap (already present). Low effort, measurable effect on
`budget_overshoot_rate` (a tracked KPI).

---

## 3. Provenance trust-score learning (small, in-tenant)

`Provenance.trust_score` is constant per source type today. Learn it in-tenant
(no privacy issue): track downstream usefulness of knowledge nodes — did a
finding from source S survive critic review / contribute to a successful run? —
and adjust S's trust score. The board Critic (`06`) and the planner can then
weight evidence by *learned* reliability, not a static guess. The `trust_score`
field lives in the CORTEX package (`04`); the learning loop is host-side.

---

## 4. Cost attribution completeness as a release gate

`01` §6.3 wires `CostLedger.add(...)` into every non-tool site and flips
`tools.cost_attribution_required` ON. Make **zero `UNATTRIBUTED` cost** a
standing dashboard invariant and a CI assertion in the integration suite. Once
in place, the cost dashboard answers "which loop spent the money" (planner vs
step vs critic vs reformat vs meta-review vs dreaming vs sandbox vs MCP) — the
single most useful lever for tuning cost/perf, and the data the bandit and the
critic-budget cap both depend on.

---

## 5. A real A/B / eval harness for kernel changes

There is a KPI rollup but no per-change A/B harness (review gap #3). Every
prompt/mode/model change today is evaluated anecdotally.

**Proposal:** a lightweight offline eval harness (`tests/eval/`) that replays a
fixed corpus of representative tasks through two configs (e.g. v1-rules vs
v2-embedding task classifier from `06` §5; deterministic vs LLM Strategist from
`06` §3.2; critic model A vs B) and reports goal-hit / cost-per-success /
false-pass / latency deltas with variance. This turns "we think it's better"
into "it's +6pp goal-hit at −9% cost, p<0.05." It also de-risks the C4 keystone
deletion in `01` (run legacy vs loop on the corpus, prove parity before deleting
the legacy executor). The `parity/` and `regression/` test dirs are the seed.

---

## 6. Smaller, high-value items

| Item | Why | Effort |
|------|-----|--------|
| One-line CSAT capture on completed runs (P-O2) | The only first-party "was this actually good?" signal; feeds critic false-pass calibration with ground truth instead of proxy. | S |
| Resumability test in CI | Review's "good loop smell test #1": crash worker mid-iteration, new worker resumes from CORTEX snapshot. `snapshot_every_iteration` is ON — assert it actually works. | S |
| `INTERNAL_CONTEXT_KEYS` doc enforcement | `core/INTERNAL_KEYS.md` exists; add a test that every key used in code is documented and vice-versa, so the doc can't rot. | S |
| Seed-entity hygiene | `SeedEntities/` + the deleted-but-tracked `DeepResearchSetup/` should live under `backend/scripts/seeds/`; one consolidated seed story. (Partly done — verify.) | S |
| SSE narrative streaming verification (review gap #5) | Confirm the stream carries the iteration *narrative*, not just status transitions; the trace spans (`P11SpanTree`, `execution_trace_events`) exist — surface them live. Ties to `01` §7. | M |
| Embedding "single source of truth" unit test | Lock in the `EMBEDDING_MODEL` one-resolution-per-process fix with a regression test (review M10) before CORTEX extraction moves the resolver. | S |

---

## 7. Things explicitly NOT worth doing in Phase 12

* **RL over the Strategist / per-iteration contextual bandit** — needs ≥3 months
  of post-GA telemetry. The current ε-greedy bandit is sufficient. P13.
* **Cross-tenant skill/intelligence sharing build** — design + privacy review
  only in P12 (`06` §8); build is a product decision for P13.
* **Sync API for CORTEX** — async-only v1 (plan N3).
* **Replacing the AgentLoop** — it is the kernel; deepen, don't rewrite.
