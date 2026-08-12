# 01 — Executive Summary

## 1. System at a glance (May 2026)

| Layer | Module(s) | LoC | State |
|------|-----------|-----|-------|
| Entry / orchestration | `core/arq_jobs.py`, `worker.py`, `core/execution_engine.py` | ~80 + 637 + **1,186** | Heavy: still owns 16 responsibilities |
| Step execution | `step_executor.py` | **1,497** | Heaviest non-orchestrator file; reasoning modes inline |
| Recursive (autonomous) engine | `core/recursive_engine.py` | 349 | Production-promoted but rarely chosen |
| Meta-review | `core/meta_review.py` | 103 | Single LLM JSON call; no calibration |
| Planning | `planning/planner_service.py`, `goal_guard.py`, `goal_alignment.py` | 554 + 115 + 156 | Solid contract; review is myopic |
| Meta-Agent | `meta/meta_agent_template.py`, `meta/platform_schema_compiler.py`, `meta/registry_search_service.py`, `meta/anti_sprawl.py`, `tools/meta/*` | 410 + 839 + 656 + 163 + ~1,200 | Best-engineered subsystem, but still a single prompt + 5 tools |
| Memory / CORTEX | `memory/cortex_service.py`, `cortex_bridge.py`, `assembler.py`, `memory_assembly_service.py`, `memory_service.py`, `dreaming_engine.py`, 4 tree services, `graph_service.py` | **1,109** + 646 + 149 + 322 + 455 + 521 + ~1,500 | Strongest layer; two parallel pipelines wired in parallel |
| Governance | `governance/governance_service.py`, `rate_limiter.py` | 434 + ~150 | Good service; HITL still string-driven |
| LLM router | `llm/router.py` + 3 adapters | ~330 + ~900 | Adequate; no batched / streaming / cache awareness |
| Tools | `tool_executor.py`, `tools/*` (24 files) | 310 + ~7k | Heavy; per-tool cost lookup duplicated across two code paths |
| Schemas | `schemas.py` | 970 | Single mega-file; PlanStep typing partly stringly-typed |

The previous Phase 10 reviews already flagged most structural problems. **Phase 11
re-grades what was actually fixed and identifies what is now blocking further
autonomy and intelligence.**

---

## 2. The four headline problems

### P0 — The "autonomous loop" is not yet a loop

`ExecutionEngine.execute_run` is a *plan → execute steps → finalize* pipeline
(see `core/execution_engine.py:391-994`). AUTONOMOUS execution is a set of
*conditional hooks* layered on top of that pipeline:
re-plan on failure (`:858-878`), MetaReviewer every N steps (`:924-955`),
GoalGuard every N steps (`:957-991`). There is **no top-level perceive →
think → act → observe → reflect cycle**. There is no "agent state machine"
beyond the LLM's own text. There is no concept of *episodic budget*,
*open subgoals*, *outstanding hypotheses*, or *self-issued tasks*.

This puts the platform behind the curve relative to:

* Reflexion / Voyager — explicit memory of past failures gating next action
* LangGraph / OpenAI Swarm — graph-state agents with explicit transitions
* Anthropic Claude Code / Devin — autonomous loops with bounded resources,
  not bounded steps

We propose a **true Agent Control Loop** (`AgentLoop`) in §03. The DAG/Recursive
engines become *executors* invoked by that loop rather than the loop itself.

### P0 — The Meta-Agent is a prompt, not a system

`meta/meta_agent_template.py` is a single AGENT with five meta-tools, gated by
`anti_sprawl.py`. It is well-prompted but:

* It has **no feedback loop**. A failed generation does not become an
  intelligence rule; it dies in the run log.
* It has **no self-evaluation**. Quality of generated agents is never
  scored after their first real run.
* It cannot **evolve its own prompt** or its own *available tool set*.
* It cannot **consolidate sprawl** (it can be blocked by anti-sprawl, but it
  can't merge duplicates).
* Its "ADAPT" path is a *clone + diff*, not a *learn-from-traces* path.
* It has **no peer review**: there is no second Meta-Agent / critic /
  red-team validating the spec before `meta_entity_creator` persists.

§04 redesigns the Meta-Agent as a **multi-role architecture board**
(Requirement → Architect → Critic → Validator → Curator) with a feedback
loop into a *Meta-Intelligence Tree* that improves its own taste over time.

### P1 — Two memory pipelines, two CORTEX namespaces, both live

`memory/assembler.py:42-53` literally branches on `memory_pipeline = "v1" |
"v2"`. Production entities currently use v1 (MemoryRouter) while the
Meta-Agent uses CORTEX. The four "tree" services (`knowledge_tree_service`,
`episodic_tree_service`, `experience_tree_service`,
`intelligence_tree_service`) are mostly used only via `MemoryAssemblyService`.

Concurrent maintenance of both paths is expensive. We need to **pick CORTEX-v2
as canonical** and fold v1 into a *legacy read-only adapter* for old episodic
rows. §06 has the cut plan.

### P1 — The package is half-restructured; ghost duplicates pollute the index

`git status` shows seven legacy files still tracked in the index:

```
backend/src/ai/goal_alignment.py        ← superseded by planning/goal_alignment.py
backend/src/ai/governance_service.py    ← superseded by governance/governance_service.py
backend/src/ai/graph_service.py         ← superseded by memory/graph_service.py
backend/src/ai/llm_router.py            ← superseded by llm/router.py
backend/src/ai/memory_service.py        ← superseded by memory/memory_service.py
backend/src/ai/planner_service.py       ← superseded by planning/planner_service.py
backend/src/ai/rate_limiter.py          ← superseded by governance/rate_limiter.py
```

And several more files were deleted on disk but tracked in git
(`cortex_*.py`, `dreaming_*.py`, `embedding_service.py`, `*tree_service.py`,
`memory_assembly_service.py`).
These will reappear next time someone does `git reset --hard`.

§07 proposes the final layout and a one-shot commit to lock it in.

---

## 3. Severity matrix

### 🔴 P0 — Blocking world-class autonomy

| ID | Finding | Anchor | Impact |
|----|---------|--------|--------|
| **F-01** | No top-level Agent Control Loop. AUTONOMOUS is hooks over a linear executor. | `core/execution_engine.py:391-994` | Cannot run truly open-ended tasks; loop is bounded by static plan. |
| **F-02** | `RecursiveReasoningEngine` exists but is rarely chosen and uses **fresh** LLM calls for confidence/expand/synthesize that ignore CORTEX and ignore memory. | `core/recursive_engine.py:173-298` | Recursive mode is dumber than DAG mode despite being the "autonomous" path. |
| **F-03** | Meta-Agent has no learning feedback. Failed/poor-quality entities never inform future generations. | `meta/meta_agent_template.py`, `tools/meta/entity_creator.py`, no `meta_self_eval` tool | Bloat over time; same mistakes repeat. |
| **F-04** | Meta-Review (`core/meta_review.py`) is one LLM call returning `CONTINUE/REPLAN/ABORT`. No calibration, no chain of thought, no cost-vs-progress modelling. | `core/meta_review.py:32-102` | Cannot reliably intervene on a drifting agent. |
| **F-05** | Review/critic loop in `step_executor._review_step_output` re-runs the **same** model and **same** prompt with feedback appended. Easy to converge to the same wrong answer. | `step_executor.py:1325-1486` | Reviews look smart but cost 2-3x for ~5% lift. |
| **F-06** | Dynamic planner has no track-record telemetry. Each plan generation starts from zero priors. | `planning/planner_service.py:240-389` | Same plan style chosen even when it consistently fails. |

### 🟠 P1 — Significant design debt

| ID | Finding | Anchor | Impact |
|----|---------|--------|--------|
| **F-07** | Dual memory pipelines `v1/v2` selected per entity config. | `memory/assembler.py:19-148` | Two test surfaces, two bug surfaces. |
| **F-08** | Ghost duplicate files still tracked in git index (7 legacy modules). | `git ls-files` | Onboarding confusion; risk of accidental revert. |
| **F-09** | `step_executor.py` mixes step routing, REACT loop, three reasoning modes (CoT / Reflection / ToT), reformat-retry, fallback chain, tool cost lookup, context summarization, critic loop, and exit conditions in a single 1,497-line class. | `step_executor.py:40-1496` | Hard to test, hard to extend, the natural place for "smarter" features to land never has room. |
| **F-10** | Tool cost lookup logic for the IntegrationRegistry is **duplicated verbatim** in two code paths in `step_executor.py` (`:520-580` and `:913-957`). | `step_executor.py` | Tool cost drift; one site fixes, the other doesn't. |
| **F-11** | The CORTEX `Viewport` is rendered with the **operations help text** appended every navigation (`memory/cortex_service.py:46-53` + every viewport). This is ~250 tokens of fixed boilerplate per step. | `memory/cortex_service.py:46-122` | Wastes ~10-20% of context budget on every step. |
| **F-12** | Anti-sprawl is **hard daily limits**, not a *learned* policy. No semantic merge / migration. | `meta/anti_sprawl.py:33-163` | Either too lax or too strict; never just right. |
| **F-13** | `meta_cognition` auto-enables `self_modification` for every AGENT/PROCESS by default (`platform_schema_compiler.resolve_meta_cognition`). Every agent can create more agents. | `meta/platform_schema_compiler.py:783-838` | Sprawl risk; should be opt-in, not opt-out. |
| **F-14** | `ExecutionEngine.execute_run` is still 600+ lines with branching for RECURSIVE / DAG / autonomous-loop / refinement / HITL / credit-circuit, all in one body. | `core/execution_engine.py:391-994` | Phase 10A succeeded in extracting helpers, but the *orchestration logic itself* is unfactored. |
| **F-15** | `schemas.py` is one 970-line file with execution schemas, persona, planning, CORTEX, tools, response DTOs. | `schemas.py` | Modifying one Pydantic model risks ripple; impossible to reason about API surface. |
| **F-16** | Reasoning mode is **per entity**, not per step. Reflection on cheap THOUGHT steps is wasteful; CoT on cheap TOOL_CALL is meaningless. | `schemas.py:227-241`, `step_executor.py:974-1001` | Coarse-grained reasoning policy. |
| **F-17** | HITL is wired but `trigger_type` is **stringly-typed** at multiple sites (`HITLTriggerType` enum exists but JSON config uses strings). | `core/execution_engine.py:_evaluate_hitl_checkpoints` → `governance/governance_service.evaluate_hitl` | Bug-bait. |
| **F-18** | LLM cost is tracked per call, but the *attribution* (planner vs. step vs. critic vs. meta-review vs. refomat-retry vs. dreaming) is muddled in a single `total_cost_usd` field; we can't tell which loop spent the money. | `step_executor._log_usage`, `planner_service._log_planner_usage`, `meta_review` (no logging at all) | Hard to tune cost/perf. |

### 🟡 P2 — Maintenance / clarity

| ID | Finding | Anchor | Impact |
|----|---------|--------|--------|
| **F-19** | Many "Phase N" comments and "Fix B/D/E/F/G/H" labels remain in code (`step_executor.py`, `execution_engine.py`). They are stale change-log narration, not contracts. | many | Cognitive load; comments will rot. |
| **F-20** | "Backward-compat re-exports" remain in `worker.py:51-67`. They were the right call during 10A but should now be removed. | `worker.py` | Confusing import paths. |
| **F-21** | `tools/social/*` (15 files) and `tools/social_*` services are barely orchestrated by any agent; some look unfinished. | `tools/social/*` | Dead-ish code at scale. |
| **F-22** | `migrate_documents_to_knowledge_trees.py`, `migrate_episodic_to_trees.py` are migration scripts living in the package root next to runtime code. | `backend/src/ai/migrate_*.py` | Confusing; move to `scripts/`. |
| **F-23** | `DeepResearchSetup/` (deleted from disk but tracked) appears to be an ad-hoc bootstrap. There is now `SeedEntities/` doing similar work. | repo root | Confusing seed story. |
| **F-24** | Cortex `to_prompt_text()` mixes structure + viewport + operations help. Hard to A/B prompts. | `memory/cortex_service.py:92-123` | Coupling. |

---

## 4. What the platform already does *well* (keep, don't disturb)

* **CORTEX cognitive tree** is the right abstraction for unbounded context.
  Viewport-based navigation, knowledge/working/output subtrees, scoped subtree
  isolation for recursive children — all sound.
* **Hierarchical Entity** with `identity / planning / capabilities /
  logic_gate / governance / io_contract / observability / hierarchy` is a
  *very* expressive contract — better than most open-source platforms.
* **Platform Schema Compiler** turning the platform's own surface into a
  prompt-injectable manifest is excellent — it's what makes Tier-1 awareness
  work.
* **Four-domain memory** (knowledge / experience / intelligence / episodic) is
  the right ontology — most platforms only have "memory."
* **Per-tool fallback chain + LLM reformat-retry** is impressively defensive.
* **Goal-alignment + GoalGuard** layered checks are a real innovation.
* **HITL checkpoints** are wired end-to-end.
* **Credit gating + circuit breakers** are correct (most platforms run cost
  open-loop and bankrupt themselves).

These should *survive* the refactor — they are not the problem.

---

## 5. The roadmap (12 weeks, summarised)

| Week | Theme | Deliverable |
|------|-------|-------------|
| 1 | Index cleanup | `git rm` legacy duplicates; collapse to single namespace |
| 2 | Schema split | `schemas/` package; typed HITLTrigger; typed StepType union |
| 3-4 | Agent Control Loop | New `core/agent_loop.py`; DAG + Recursive become *executors* |
| 5 | Meta-Review v2 | Multi-pass review w/ progress score, calibration, cost-vs-value |
| 6 | Critic v2 | Separate critic model (or higher-tier prompt), no same-model loop |
| 7-8 | Meta-Agent v4 | Architect/Critic/Validator/Curator split; feedback to Meta-Intelligence Tree |
| 9 | Memory v2 canonical | Kill v1 pipeline; route everything through `MemoryAssemblyService`; legacy adapter |
| 10 | Planner with priors | Plan-style track-record per entity-class; bandit over plan strategies |
| 11 | Tool / cost consolidation | Single tool-cost service; ToolResult enrichment; cost telemetry by attribution |
| 12 | Hardening | Type-checking pass; remove "Phase N" narration; doc all internal context keys |

Full breakdown with exit criteria in [`08_roadmap.md`](./08_roadmap.md).

---

## 6. How to read the remainder of this review

* If you own **execution** — start at [03](./03_agentic_loop_redesign.md).
* If you own **the Meta-Agent** — start at [04](./04_meta_agent_blueprint.md).
* If you own **memory** — start at [06](./06_memory_and_cortex.md).
* If you own **the repo layout / DX** — start at
  [02](./02_redundancy_and_conflicts.md) then [07](./07_folder_restructure.md).
* If you're the **tech lead** — read [01](./01_executive_summary.md) and
  [08](./08_roadmap.md) and trust the section owners on the rest.
