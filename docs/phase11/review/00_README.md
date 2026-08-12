# Phase 11 — Architecture & Code Review

> **Reviewer:** Software Architect (20+ yrs, autonomous AI agent systems)
> **Date:** 2026-05-25
> **Scope:** `/backend/src/ai/` — every layer: orchestrator, planner, step executor,
>   meta-agent, CORTEX memory, governance, LLM router, tool registry.
> **Frame of reference:** State-of-the-art autonomous agent platforms
>   (Anthropic Claude Agent SDK, OpenAI Swarm/Assistants, LangGraph, AutoGen, Devin/Cognition,
>   Voyager, Reflexion, ReAct, Tree-of-Thoughts research, RLM/PageIndex/CORTEX).
> **Goal:** A concrete roadmap to make the agents *world-class autonomous loops* with a
>   *world-class Meta-Agent*, world-class dynamic planning / review / meta-cognition,
>   and a maintainable folder structure.

---

## Document Index

| # | File | Scope |
|---|------|-------|
| 01 | [`01_executive_summary.md`](./01_executive_summary.md) | Headline findings, severity matrix, the 12-week roadmap |
| 02 | [`02_redundancy_and_conflicts.md`](./02_redundancy_and_conflicts.md) | Dead files, duplicate modules, conflicting workflows, ghost code |
| 03 | [`03_agentic_loop_redesign.md`](./03_agentic_loop_redesign.md) | The autonomous loop today vs. what world-class looks like; concrete redesign |
| 04 | [`04_meta_agent_blueprint.md`](./04_meta_agent_blueprint.md) | Meta-Agent deep dive + blueprint for a *world-class* Meta-Agent |
| 05 | [`05_planning_review_meta_cognition.md`](./05_planning_review_meta_cognition.md) | Dynamic planning, review/critic mechanism, hierarchical meta abilities |
| 06 | [`06_memory_and_cortex.md`](./06_memory_and_cortex.md) | CORTEX trees, dreaming, four-domain memory; what to keep / kill / replace |
| 07 | [`07_folder_restructure.md`](./07_folder_restructure.md) | Proposed package layout with a migration script outline |
| 08 | [`08_roadmap.md`](./08_roadmap.md) | Prioritised, sized backlog (P0 → P3) with owner hooks and exit criteria |

> Read order: **01 → 02 → 03 → 04 → 05 → 06 → 07 → 08**.
> Each section is self-contained — you can hand 04 to whoever owns the Meta-Agent
> without reading 02 first.

---

## How this review was produced

1. Mapped the agent execution path end-to-end from `core/arq_jobs.py` →
   `ExecutionEngine.execute_run` → `StepExecutorService._execute_*` →
   `LLMRouter.call_llm_react` → `ToolExecutor`.
2. Walked the Meta-Agent stack: `meta/seed_meta_agent.py`,
   `meta/meta_agent_template.py`, `meta/platform_schema_compiler.py`,
   `meta/registry_search_service.py`, `meta/anti_sprawl.py`,
   `tools/meta/*`.
3. Walked the memory stack: `memory/cortex_service.py`,
   `memory/cortex_bridge.py`, `memory/assembler.py`,
   `memory/memory_assembly_service.py`, `memory/memory_service.py`,
   `memory/dreaming_engine.py`, the four "tree" services
   (`episodic_tree_service`, `experience_tree_service`,
   `intelligence_tree_service`, `knowledge_tree_service`),
   `memory/graph_service.py`.
4. Audited `planning/planner_service.py`, `planning/goal_alignment.py`,
   `planning/goal_guard.py`, `core/meta_review.py`,
   `core/recursive_engine.py`.
5. Audited `governance/governance_service.py`,
   `governance/rate_limiter.py`, `llm/router.py`, `tool_executor.py`,
   `tool_fallback.py`, `tools/__init__.py`, the social/meta tool subdirs.
6. Compared against the previous Phase 10 reviews
   (`docs/phase10/01..05`, `ANALYSIS_01/02`, `impl_10A..10E`) to track
   what is already known, what's been fixed, and what regressed.
7. Diffed the **git index vs working tree** to find ghost duplicates
   (Phase-10A move left two parallel namespaces still tracked in git).

---

## TL;DR (60-second read)

* The platform has the **right primitives** — hierarchical entities, CORTEX
  cognitive trees, REACT/CoT/Reflection/ToT, a Meta-Agent, four memory domains,
  goal alignment, dreaming, HITL — but the **glue is brittle** and the
  **autonomy is shallow**.
* The execution loop is still **plan-first, then mostly linear**;
  AUTONOMOUS mode is a thin overlay on STANDARD instead of a true
  goal-directed control loop. **It is not yet a world-class agentic loop.**
* The Meta-Agent is a **prompt-engineered AGENT**, not an architect-grade
  system. It can search → create → test, but it cannot *learn from
  failed generations*, *consolidate its own bloat*, or *evolve its own
  prompt/tools*.
* Memory is **the strongest part** of the stack (CORTEX + dreaming +
  4 domains) but has **2 parallel pipelines** (v1 MemoryRouter and v2
  MemoryAssemblyService) wired in production simultaneously.
* Code organisation is **half-refactored**: `ai/` has ~80 top-level
  files plus the new `core/`, `memory/`, `meta/`, `planning/`,
  `governance/`, `llm/`, `tools/` packages. The duplicates still live in
  the git index, ready to confuse anyone who clones the repo.
* The dynamic planner is **competent but myopic**: it doesn't track its
  own track-record, it doesn't propose alternative *plan strategies*,
  and the *reviewer* is a single LLM JSON pass with no calibration.

The roadmap in **08_roadmap.md** turns this into ~12 focused weeks of
work, structured so you can ship incremental value every week.
