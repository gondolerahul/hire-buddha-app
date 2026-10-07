# Phase 6: Agentic Architecture Review — Autonomy & Scalability Audit

> **Author**: AI Architecture Review  
> **Date**: 2026-05-07  
> **Scope**: `backend/src/ai/` — worker.py, llm_router.py, cortex_service.py, memory_service.py, tool_executor.py, schemas.py, service.py, tools/base.py  
> **Objective**: Identify redundancies, conflicts, gaps, and architectural decisions that limit autonomy, then propose a modular, goal-centric evolution path.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current Architecture Overview](#2-current-architecture-overview)
3. [Critical Findings](#3-critical-findings)
   - 3.1 Redundant & Duplicate Code
   - 3.2 Conflicting Workflows
   - 3.3 Architectural Anti-Patterns
   - 3.4 Gaps & Missing Capabilities
4. [Monolith Decomposition Plan](#4-monolith-decomposition-plan)
5. [Autonomous Agentic Loop Evolution](#5-autonomous-agentic-loop-evolution)
6. [CORTEX Memory System Improvements](#6-cortex-memory-system-improvements)
7. [Tool Orchestration Modernization](#7-tool-orchestration-modernization)
8. [Prioritized Recommendations](#8-prioritized-recommendations)
9. [Migration Strategy](#9-migration-strategy)

---

## 1. Executive Summary

The current system demonstrates a well-engineered foundation: a hierarchical entity model, provider-agnostic LLM routing, three-tier memory, CORTEX cognitive trees, and multi-tenant governance. However, `worker.py` (3,487 lines) has become a monolithic bottleneck that conflates **planning**, **execution**, **governance**, **billing**, and **memory orchestration** into a single class. This creates:

- **Testing impossibility**: Unit-testing the planner requires mocking billing, Redis, CORTEX, and tool execution.
- **Scaling rigidity**: Cannot independently scale planning vs. execution workloads.
- **Autonomy ceiling**: The static DAG executor is the primary execution path; the `RecursiveReasoningEngine` (L3378-3446) is vestigial and unused.

**Top 3 Priorities:**
1. **Decompose `ExecutionEngine`** into `PlannerService`, `ExecutorService`, and `GovernanceService`.
2. **Promote `RecursiveReasoningEngine`** from experimental stub to primary autonomous driver.
3. **Implement self-reflective CORTEX validation** so agents validate actions against tree-level objectives.

---

## 2. Current Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                      Arq Worker                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │            ExecutionEngine (worker.py)             │  │
│  │  ┌──────────┬──────────┬──────────┬────────────┐  │  │
│  │  │ Planning │ DAG Exec │ HITL/Gov │ Billing    │  │  │
│  │  │ _get_    │ _execute │ _eval_   │ CreditSvc  │  │  │
│  │  │ reconcil │ _steps   │ hitl_    │ BillingSvc │  │  │
│  │  │ ed_plan  │ _dag     │ checkpts │ UsageSvc   │  │  │
│  │  └──────────┴──────────┴──────────┴────────────┘  │  │
│  │  ┌──────────┬──────────┬──────────┐               │  │
│  │  │ LLMRouter│ ToolExec │ CORTEX   │               │  │
│  │  │ (extern) │ (extern) │ Service  │               │  │
│  │  └──────────┴──────────┴──────────┘               │  │
│  └───────────────────────────────────────────────────┘  │
│  RecursiveReasoningEngine (unused stub)                  │
└─────────────────────────────────────────────────────────┘
```

### Key Data Flow
1. `execute_run()` → Load entity + run → Credit gate → CORTEX tree init → Memory retrieval
2. → Plan reconciliation (static or LLM-dynamic) → DAG or sequential step execution
3. → Per-step: HITL check → Timeout wrapper → Thought/Tool/ChildInvocation dispatch
4. → Per-step: Billing deduction → CORTEX write → Viewport refresh → Checkpoint
5. → Finalize: Write output → Episodic memory → TB billing settlement → Redis publish

---

## 3. Critical Findings

### 3.1 Redundant & Duplicate Code

| ID | Finding | Location | Impact |
|----|---------|----------|--------|
| R1 | **`call_llm_unified` shim** is dead code — every path requires `db` and `company_id`, making the "no-db" branch unreachable. | `worker.py:330-365` | Confusion, maintenance burden |
| R2 | **`_get_api_key` method** marked deprecated but still present. LLMRouter handles key resolution internally. | `worker.py:2639-2651` | Dead code |
| R3 | **Duplicate `_clone_fields` + `_remap_entity_refs`** — defined identically in both `save_as_template()` (L812) and `clone_template()` (L972). | `service.py:812-853, 972-1096` | 180 lines of exact duplication |
| R4 | **Duplicate text extraction** — `_extract_text_from_file()` in worker.py (L1500-1568) duplicates logic in `process_document()` (L3225-3290). Both parse PDF/DOCX/XLSX independently. | `worker.py` | Divergent behavior risk |
| R5 | **`_INTERNAL_KEYS` set** defined in 3 separate locations with slightly different members. | `worker.py:1957, 2317` | Inconsistent filtering |
| R6 | **`import copy`** done at module level (L37) AND locally inside `_get_reconciled_plan` (L1582) AND inside `_review_step_output` using `copy.deepcopy`. | Multiple | Unnecessary local imports |
| R7 | **Context source loading** (L862-981) — 120-line inline block that should be a standalone method. | `worker.py:862-981` | Readability, testability |

### 3.2 Conflicting Workflows

| ID | Finding | Location | Risk |
|----|---------|----------|------|
| C1 | **DAG vs. Sequential path divergence** — DAG path (L1001-1007) writes results to CORTEX *after* all steps complete, but sequential path (L1008-1088) writes after *each* step. This means DAG steps don't get incremental billing, credit circuit-breaker, or viewport refresh. | `worker.py:1001-1088` | **HIGH**: DAG runs can overspend without circuit-breaker |
| C2 | **Isolated sessions in DAG** create `ExecutionEngine` clones (L456) that don't share `run` state. Cost accumulation from parallel steps won't reflect on the parent `run.total_cost_usd` until after `asyncio.gather` completes. | `worker.py:453-471` | Billing accuracy gap |
| C3 | **`reasoning_mode` dispatch** lives in `_execute_thought()` (L2388-2416) but CoT/Reflection/ToT all route through `call_llm_react` again internally. CoT appends XML instructions to system prompt, creating prompt pollution if the entity already defines structured output. | `worker.py:2467-2503` | Prompt conflicts |
| C4 | **Child entity context collision** — `Fix F` (L1874-1889) strips `step_N` keys but doesn't strip named step keys. If parent step name matches child step name, child inherits stale parent output. | `worker.py:1874-1889` | Subtle data corruption |
| C5 | **HITL timeout uses `asyncio.get_event_loop().time()`** (L647-650) — this is deprecated in Python 3.10+ and can cause issues with `asyncio.run()` contexts. Should use `asyncio.get_running_loop().time()`. | `worker.py:647-650` | Runtime warnings/errors |

### 3.3 Architectural Anti-Patterns

| ID | Anti-Pattern | Details | Severity |
|----|-------------|---------|----------|
| A1 | **God Object** | `ExecutionEngine` has 25+ methods across 5 responsibility domains (planning, execution, governance, billing, memory). | 🔴 Critical |
| A2 | **Synchronous child execution** | `_execute_child_invocation` (L1928) calls `execute_run()` recursively in-process. Deep hierarchies (Process → Agent → Agent) stack coroutines and hold DB sessions open for the full child duration. | 🔴 Critical |
| A3 | **No execution state machine** | Run status transitions (`PENDING→RUNNING→COMPLETED/FAILED`) are ad-hoc, with no formal state machine. There's no `PAUSED`, `RESUMING`, or `PARTIAL_COMPLETE` state despite the codebase supporting checkpointing. | 🟡 High |
| A4 | **Hardcoded magic numbers** | `max_react_turns=12` (L2413), `ctx_size // 4` token estimation (L1082), `[:50000]` content caps, `[:6000]` context truncation — all scattered as literals. | 🟡 High |
| A5 | **Print statements as logging** | 40+ `print()` calls throughout worker.py instead of structured `logger.*()` calls. | 🟡 Medium |
| A6 | **Broad exception swallowing** | Multiple `except Exception: pass` blocks (L1064, L1076, L856) silently hide failures that could mask data corruption. | 🟡 High |
| A7 | **No idempotency** | If a run is retried (e.g., Arq retry on crash), there's no deduplication. Steps with side effects (tool calls, billing) will execute twice. | 🔴 Critical |

### 3.4 Gaps & Missing Capabilities

| ID | Gap | Current State | Impact |
|----|-----|---------------|--------|
| G1 | **No goal validation loop** | Agent executes plan steps linearly without re-evaluating whether the *goal* is being achieved. If step 3/5 already achieves the goal, steps 4-5 still execute. | Wasted compute, lower quality |
| G2 | **No plan adaptation** | Once the plan is generated, it's immutable. If step 2 fails or produces unexpected output, the agent cannot revise the remaining plan. | Fragile execution |
| G3 | **No inter-agent communication** | Child entities can only communicate via context inheritance. No message-passing, shared blackboard, or event bus between sibling agents. | Limits collaborative multi-agent |
| G4 | **`RecursiveReasoningEngine`** has no integration point — `execute_run()` never instantiates it. It references `self.company_id` (L3419) which doesn't exist on `ExecutionEngine`. | Dead code with bugs |
| G5 | **No output quality scoring** | The self-critique mechanism (L2753-2913) is binary (pass/fail) with no cumulative quality score across steps. No learning from past critique patterns. | Ceiling on output quality |
| G6 | **CORTEX tree lacks garbage collection** | Trees grow indefinitely. No pruning, archival, or size-based compaction beyond the `_schedule_reclustering` method. | Storage bloat, slow queries |
| G7 | **No streaming support** | All LLM calls are request-response. No SSE/WebSocket streaming of partial results to the frontend during long-running executions. | Poor UX for long tasks |
| G8 | **Cron job registration** is wrapped in `try/except ImportError: pass` (L3480-3486). If `arq.cron` is unavailable, scheduled CORTEX wake-ups silently fail. | Invisible feature degradation |
| G9 | **No observability metrics** | No Prometheus/OpenTelemetry integration. Monitoring relies entirely on log parsing. | Ops blindness |

---

## 4. Monolith Decomposition Plan

### Target Architecture

```
ExecutionEngine (thin orchestrator)
    ├── PlannerService        — Plan generation, reconciliation, adaptation
    ├── ExecutorService       — Step dispatch, DAG/sequential, tool calls
    ├── GovernanceService     — HITL, credit gates, circuit breakers, billing
    ├── CortexBridge          — CORTEX tree lifecycle, viewport, checkpoints
    └── ObservabilityService  — Structured logging, metrics, tracing
```

### Service Boundaries

**PlannerService** (`planner_service.py`)
- `_get_reconciled_plan()` → `PlannerService.reconcile(entity, context) → Plan`
- `_expand_goal()` from RecursiveReasoningEngine → `PlannerService.decompose(goal) → List[GoalNode]`
- Plan validation, CHILD_ENTITY_INVOCATION injection, step_id generation
- **New**: `adapt_plan(plan, step_results, goal) → RevisedPlan` — mid-execution re-planning

**ExecutorService** (`executor_service.py`)
- `_execute_steps_dag()`, `_execute_step_wrapper()`, `_execute_step()`
- `_execute_thought()`, `_execute_tool_call()`, `_execute_child_invocation()`
- `_execute_cortex_step()`, reasoning mode dispatch (CoT, Reflection, ToT)
- **New**: `_execute_child_async()` — non-blocking child entity execution via Arq

**GovernanceService** (`governance_service.py`)
- `_evaluate_hitl_checkpoints()`, `_safe_eval_hitl_expression()`
- Credit balance gates, incremental deduction, circuit breaker
- TB billing settlement, `_log_usage()`
- **New**: Rate limiting, cost forecasting, automatic budget allocation

**CortexBridge** (`cortex_bridge.py`)
- `_write_step_to_cortex()`, `_ingest_tool_result_to_cortex()`
- `_build_task_description()`, viewport refresh, checkpointing
- **New**: Goal-tree ↔ CORTEX tree synchronization, garbage collection

---

## 5. Autonomous Agentic Loop Evolution

### Current: Static Plan-Execute

```
Goal → Plan (static/LLM) → [Step1 → Step2 → ... → StepN] → Output
         ↑ fixed                    no re-evaluation
```

### Target: Goal-Centric Autonomous Loop

```
┌─────────────────────────────────────────────────┐
│                 AUTONOMOUS LOOP                  │
│                                                  │
│  ┌──────────┐    ┌───────────┐   ┌───────────┐ │
│  │ PERCEIVE │───→│  REASON   │──→│    ACT    │ │
│  │ (Context)│    │ (Plan/    │   │ (Execute  │ │
│  │          │    │  Adapt)   │   │  Step)    │ │
│  └──────────┘    └───────────┘   └─────┬─────┘ │
│       ↑                                │       │
│       │          ┌───────────┐         │       │
│       └──────────│  REFLECT  │←────────┘       │
│                  │ (Validate │                  │
│                  │  vs Goal) │                  │
│                  └───────────┘                  │
│                       │                         │
│                  [Goal Met?]                     │
│                  Yes → EXIT                      │
│                  No  → LOOP                      │
└─────────────────────────────────────────────────┘
```

### Implementation Steps

**Phase 1: Goal Validation Gate** (Low Risk)
- After each step, inject a lightweight LLM call: *"Given the original goal X and the accumulated results Y, is the goal achieved? Score 0-100."*
- If score > 85, early-exit. If score < 30 after 50% of steps, trigger re-planning.

**Phase 2: Mid-Execution Re-Planning** (Medium Risk)
- When a step fails or produces unexpected output, call `PlannerService.adapt_plan()` with:
  - Original goal, completed steps, failed step details, remaining plan
- LLM generates a revised plan for the remaining work.

**Phase 3: Full Recursive Reasoning** (Higher Risk)
- Promote `RecursiveReasoningEngine` with fixes:
  - Add `company_id` property (currently missing — L3419 bug)
  - Integrate with CORTEX tree (each GoalNode maps to a CORTEX task node)
  - Add confidence-based expansion threshold (currently hardcoded 0.7)
  - Wire into `execute_run()` as an alternative execution mode per entity config

**Phase 4: Self-Reflective Memory Loop**
- Before acting, agent queries CORTEX knowledge root: *"What have I already learned that's relevant to this sub-goal?"*
- Prevents redundant research, enables cross-step knowledge reuse
- After acting, agent writes a reflection node: *"What did I learn? How does this change my approach?"*

### Entity Configuration for Autonomous Mode

```json
{
  "logic_gate": {
    "reasoning_config": {
      "execution_mode": "AUTONOMOUS",
      "goal_validation_interval": 2,
      "confidence_threshold": 0.85,
      "max_replanning_attempts": 3,
      "self_reflection_enabled": true
    }
  }
}
```

---

## 6. CORTEX Memory System Improvements

### Current Issues

1. **No GC/Pruning** — Trees grow unbounded. Production trees from deep research runs can have 500+ nodes.
2. **Linear breadcrumb walk** — `_build_breadcrumb()` (cortex_service.py:913-928) does N sequential DB queries to walk to root. Should use a recursive CTE.
3. **`_is_descendant_of()`** (L967-982) — Same N-query walk. O(depth) DB calls per security check.
4. **Bridge paragraph generation** (L1051-1089) — Calls LLM for document coherence but has no cost tracking (missing `_log_usage` call).
5. **Knowledge root assumption** — `get_knowledge_root()` uses `sibling_order=0` which is fragile. Should use `node_type` filter.

### Recommendations

1. **Recursive CTE queries** for ancestry/descendancy checks — single query instead of loop.
2. **Tree compaction job** — Background job that archives nodes older than N days with status=COMPLETE into a summary node.
3. **Viewport caching** — Cache viewport results in Redis with TTL=30s to avoid repeated DB queries within the same step.
4. **Self-reflective context injection** — Before each THOUGHT step, auto-inject a "What I know so far" summary from the CORTEX knowledge subtree.

---

## 7. Tool Orchestration Modernization

### Current Issues

1. **String-based tool I/O** — Tools accept `input_data: str` and return `str`. No typed parameters, no structured error codes.
2. **No tool chaining** — Each tool call is independent. No pipeline composition (e.g., search → scrape → extract → summarize).
3. **Rate limiting is per-run only** — No global rate limiting across concurrent runs for shared resources (e.g., SerpAPI).
4. **Self-healing retry** (L1998-2029) is tool-specific to format errors. No general retry with exponential backoff.

### Recommendations

1. **Typed Tool Protocol** — Migrate from `run(input_data: str) → str` to `run(params: ToolParams) → ToolResult` with Pydantic models.
2. **Tool Pipeline DSL** — Allow entity config to define tool chains: `[{tool: "web_search", pipe_to: "scraper_tool"}, ...]`
3. **Global rate limiter** — Redis-based sliding window rate limiter shared across all runs.
4. **Deprecate `call_llm_unified`** — Remove the shim entirely; all callers already use LLMRouter.

---

## 8. Prioritized Recommendations

### 🔴 P0 — Critical (Do First)

| # | Action | Files | Effort |
|---|--------|-------|--------|
| 1 | **Remove dead code**: `call_llm_unified`, `_get_api_key` | worker.py | 1h |
| 2 | **Fix DAG billing gap**: Add per-step billing + circuit-breaker to DAG path | worker.py:1001-1007 | 2h |
| 3 | **Fix `RecursiveReasoningEngine.company_id`** bug | worker.py:3419 | 15m |
| 4 | **Replace `print()` with `logger`** across worker.py (40+ instances) | worker.py | 2h |
| 5 | **Add idempotency keys** to step execution to prevent duplicate side effects on retry | worker.py, models.py | 4h |
| 6 | **Fix deprecated `get_event_loop()`** in HITL checkpoint | worker.py:647-650 | 15m |

### 🟡 P1 — High (This Sprint)

| # | Action | Files | Effort |
|---|--------|-------|--------|
| 7 | **Extract `GovernanceService`** from ExecutionEngine | New: governance_service.py | 1d |
| 8 | **Extract `PlannerService`** from ExecutionEngine | New: planner_service.py | 1d |
| 9 | **Add goal validation gate** after each step | worker.py, planner_service.py | 4h |
| 10 | **Deduplicate `_clone_fields`/`_remap_entity_refs`** in service.py | service.py | 2h |
| 11 | **Consolidate `_INTERNAL_KEYS`** into a single module constant | worker.py | 30m |
| 12 | **Extract context source loading** into a dedicated method | worker.py:862-981 | 1h |
| 13 | **Add `PAUSED`/`RESUMING` run statuses** to the state machine | schemas.py, models.py | 2h |

### 🟢 P2 — Medium (Next Sprint)

| # | Action | Files | Effort |
|---|--------|-------|--------|
| 14 | **Implement mid-execution re-planning** | planner_service.py | 2d |
| 15 | **Async child entity execution** via Arq instead of recursive in-process | worker.py:1928 | 1d |
| 16 | **CORTEX recursive CTE queries** for breadcrumb/ancestry | cortex_service.py | 4h |
| 17 | **Typed Tool Protocol** migration | tools/base.py, tool_executor.py | 2d |
| 18 | **Self-reflective CORTEX loop** (query knowledge before acting) | worker.py, cortex_bridge.py | 1d |
| 19 | **Consolidate text extraction** into a shared utility | New: text_extractor.py | 3h |

### 🔵 P3 — Future

| # | Action |
|---|--------|
| 20 | Full `RecursiveReasoningEngine` promotion with CORTEX integration |
| 21 | Inter-agent message bus (Redis pub/sub blackboard) |
| 22 | CORTEX tree garbage collection / archival job |
| 23 | OpenTelemetry integration for distributed tracing |
| 24 | Streaming LLM output via SSE to frontend |

---

## 9. Migration Strategy

### Phase 1: Clean & Stabilize (Week 1)
- Execute all P0 items (dead code removal, bug fixes, logging)
- Add integration tests for `execute_run()` happy path
- No behavioral changes — pure cleanup

### Phase 2: Extract Services (Week 2-3)
- Extract `GovernanceService` first (lowest coupling)
- Extract `PlannerService` second
- `ExecutionEngine` becomes a thin orchestrator calling services
- Each extraction includes unit tests for the new service

### Phase 3: Autonomous Loop (Week 3-4)
- Add goal validation gate (P1 #9)
- Add mid-execution re-planning (P2 #14)
- Make async child execution the default (P2 #15)
- Feature-flag new behaviors behind entity config

### Phase 4: Intelligence Layer (Week 5+)
- Self-reflective CORTEX loop
- RecursiveReasoningEngine promotion
- Inter-agent communication
- Quality scoring and learning

---

## Appendix A: File Metrics

| File | Lines | Responsibilities | Coupling |
|------|-------|-----------------|----------|
| `worker.py` | 3,487 | Planning, Execution, Governance, Billing, Memory, Tools, Campaigns | 🔴 Extreme |
| `cortex_service.py` | 1,090 | Tree lifecycle, navigation, read/write, compaction | 🟡 Moderate |
| `service.py` | 1,194 | CRUD, cloning, template management, input schema gen | 🟡 Moderate |
| `llm_router.py` | 930 | Provider dispatch, REACT loop, adapter pattern | 🟢 Clean |
| `schemas.py` | 822 | Type definitions, validation, prompt templates | 🟢 Clean |
| `memory_service.py` | 409 | Three-tier memory retrieval and persistence | 🟢 Clean |
| `tool_executor.py` | 315 | Tool dispatch, rate limiting, result formatting | 🟢 Clean |
| `tools/base.py` | 131 | ABC + registry | 🟢 Clean |

## Appendix B: Key Code References

- **Monolith entry point**: [execute_run()](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/worker.py#L730)
- **DAG executor**: [_execute_steps_dag()](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/worker.py#L380)
- **Thought/Action dispatch**: [_execute_thought()](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/worker.py#L2217)
- **Dead shim**: [call_llm_unified()](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/worker.py#L330)
- **Vestigial engine**: [RecursiveReasoningEngine](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/worker.py#L3378)
- **HITL governance**: [_evaluate_hitl_checkpoints()](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/worker.py#L540)
- **Duplicate clone logic**: [save_as_template](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/service.py#L812) vs [clone_template](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/service.py#L972)
- **CORTEX bridge gap**: [_generate_bridge_paragraphs()](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/cortex_service.py#L1051) (untracked LLM cost)
