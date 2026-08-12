# Phase 6: Scope of Work — Agentic Architecture Optimization

> **Version**: 1.0  
> **Date**: 2026-05-07  
> **Based On**: [architecture_review.md](./architecture_review.md) (v1) and [architecture_review_v2.md](./architecture_review_v2.md) (v2)  
> **Platform**: HireBuddha — Multi-tenant AI Agent Orchestration Platform

---

## 1. Project Overview

### 1.1 Platform Summary

HireBuddha is a multi-tenant AI agent orchestration platform with:

- **Backend** (FastAPI + Arq + PostgreSQL + Redis):
  - `src/ai/` — Core AI engine: worker.py (3,504 lines), llm_router.py, cortex_service.py, memory_service.py, tool_executor.py, service.py, schemas.py, 17 tool implementations
  - `src/auth/` — Authentication, RBAC, multi-tenant company/user/partner management
  - `src/billing/` — Credit system, usage metering, TB-formula billing
  - `src/config/` — Integration registry, model configuration
  - `src/gateway/` — Unified AI gateway, WebSocket/audio/video streaming
  - `src/voice/` — Telephony (Twilio/Tata), WhatsApp, session management, 25 modules
  - `src/common/` — Shared utilities, middleware, telemetry

- **Frontend** (React + TypeScript + Vite):
  - Entity management (EntityBuilder, EntityFlow, EntityConfigurationTabs, EntityLibrary)
  - Execution monitoring (ExecutionPage, ExecutionDetail, ExecutionHistory)
  - CORTEX memory explorer (CortexExplorer, CortexTreeDetail)
  - HITL approval panel, Template Marketplace, Tool Management
  - Streaming/campaigns (CampaignsPage, StreamingSessionsPage, PhoneNumbersPage)
  - Role-based dashboards (App/Tenant/Partner × Admin/User = 6 dashboards)
  - Billing (WalletPage, BillingSettings), Reports (8 report views), Artifacts
  - 18 API service modules under `src/services/`

### 1.2 Phase 6 Objective

Evolve the platform from a functional prototype to a production-grade, autonomy-capable system by:
1. Fixing critical bugs, race conditions, and data integrity issues
2. Decomposing the monolithic ExecutionEngine into modular services
3. Implementing a goal-centric autonomous execution loop
4. Hardening concurrency, security, and error recovery
5. Optimizing performance bottlenecks
6. Updating frontend components to support new capabilities

---

## 2. Workstream Breakdown

### WS-1: Critical Bug Fixes & Stabilization (Week 1)

**Objective**: Fix all P0 issues from both reviews — data loss risks, runtime crashes, and security vulnerabilities.

#### WS-1.1: Data Integrity Fixes

| Task | Source | File(s) | Effort |
|------|--------|---------|--------|
| Fix `metadata` → `metadata_info` column mismatch in episodic memory writes | DATA-3 | `memory_service.py:157` | 15m |
| Unify embedding model constant (`gemini-embedding-004` vs `text-embedding-004`) | DATA-4 | `memory_service.py:213`, `worker.py:3255`, new `constants.py` | 30m |
| Fix `total_cost_usd` None + int TypeError in child cost rollup | DATA-5 | `worker.py:1948` | 30m |
| Fix `RecursiveReasoningEngine.company_id` missing attribute | G4 | `worker.py:3419` | 15m |
| Fix deprecated `get_event_loop()` → `get_running_loop()` in HITL | C5 | `worker.py:647-650` | 15m |

#### WS-1.2: Concurrency & Race Condition Fixes

| Task | Source | File(s) | Effort |
|------|--------|---------|--------|
| DAG parallel steps: deep-copy `context_state` per step, merge after gather | RACE-1 | `worker.py:453-461` | 2h |
| DAG parallel steps: pass `run.id` instead of ORM object, reload in isolated session | RACE-2 | `worker.py:458` | 4h |
| Wrap HITL pub/sub in `try/finally` to prevent connection leaks | RACE-3 | `worker.py:643-670` | 30m |
| Fix DAG billing gap: add per-step `consume_incremental` + circuit-breaker | C1 | `worker.py:1001-1007` | 2h |

#### WS-1.3: Error Recovery Hardening

| Task | Source | File(s) | Effort |
|------|--------|---------|--------|
| Fix `BaseException` handler: rollback before status write, use fresh session | ERR-1 | `worker.py:1188-1205` | 1h |
| DAG: collect all results before raising, write failed step results to context | ERR-2 | `worker.py:466-468` | 1h |
| Reset `tool_call_counts` per step execution (not per run) | ERR-3 | `worker.py:2364-2365` | 30m |
| Write failed step_id to `context_state` to prevent re-execution on retry | DATA-2 | `worker.py:475-538` | 1h |

#### WS-1.4: Security Hardening

| Task | Source | File(s) | Effort |
|------|--------|---------|--------|
| Strip `__`-prefixed keys and large content before persisting `context_state` | SEC-1 | `worker.py:1096,1199` | 1h |
| Sanitize `context_snapshot` in HITL approvals (remove internal topology) | SEC-3 | `worker.py:617-622` | 30m |

#### WS-1.5: Dead Code Removal & Cleanup

| Task | Source | File(s) | Effort |
|------|--------|---------|--------|
| Remove `call_llm_unified` shim (zero callers) | R1 | `worker.py:330-365` | 30m |
| Remove deprecated `_get_api_key` method | R2 | `worker.py:2639-2651` | 15m |
| Consolidate `_INTERNAL_KEYS` into single module-level constant | R5 | `worker.py:1957,2317` | 30m |
| Replace 55+ `print()` statements with structured `logger.*()` calls | A5 | `worker.py` | 3h |
| Remove redundant local `import copy` statements | R6 | `worker.py:1582,1779` | 15m |

**WS-1 Total Estimated Effort: ~20 hours (2.5 dev-days)**

**Deliverables:**
- All P0 bugs fixed with unit tests
- Zero `print()` statements in worker.py
- Integration test for `execute_run()` happy path (sequential + DAG)

---

### WS-2: Code Deduplication & Refactoring (Week 1-2)

**Objective**: Eliminate code duplication and extract inline logic into testable units.

| Task | Source | File(s) | Effort |
|------|--------|---------|--------|
| Deduplicate `_clone_fields`/`_remap_entity_refs` — use `clone_template`'s deep-copy version, fix `save_as_template` shallow copy bug | R3, v2 nuance | `service.py:812-853, 972-1096` | 2h |
| Consolidate text extraction into shared `text_extractor.py` utility | R4 | `worker.py:1500-1568, 3225-3290` → new `text_extractor.py` | 3h |
| Extract context source loading (120 lines) into `_load_context_sources()` method | R7 | `worker.py:862-981` | 1h |
| Extract hardcoded magic numbers into `constants.py` (`max_react_turns=12`, `ctx_size // 4`, `[:50000]`, `[:6000]`) | A4 | `worker.py` multiple locations, new `constants.py` | 1h |

**WS-2 Total Estimated Effort: ~7 hours (1 dev-day)**

**Deliverables:**
- `src/ai/text_extractor.py` — unified text extraction (PDF/DOCX/XLSX/PPTX/CSV)
- `src/ai/constants.py` — centralized constants (embedding model, limits, internal keys)
- 180 lines of duplication eliminated from `service.py`
- Each extraction includes unit tests

---

### WS-3: Monolith Decomposition — Service Extraction (Week 2-3)

**Objective**: Decompose `ExecutionEngine` (3,504 lines, 25+ methods, 5 responsibility domains) into focused services.

#### WS-3.1: GovernanceService Extraction (lowest coupling — extract first)

**New File**: `src/ai/governance_service.py`

**Methods to extract from worker.py:**
- `_evaluate_hitl_checkpoints()` (L540-690)
- `_safe_eval_hitl_expression()` (L692-726)
- Credit balance gate logic (L770-786)
- Incremental billing deduction + circuit-breaker
- TB billing settlement logic

**Interface:**
```python
class GovernanceService:
    async def check_credit_gate(company_id, entity_type) -> bool
    async def evaluate_hitl(run, entity, step, context, phase) -> None
    async def consume_incremental(run, step_cost) -> bool  # returns False if circuit-break
    async def settle_billing(run) -> Decimal
```

**Effort**: 1 day

#### WS-3.2: PlannerService Extraction

**New File**: `src/ai/planner_service.py`

**Methods to extract from worker.py:**
- `_get_reconciled_plan()` (L1582+) → `PlannerService.reconcile(entity, context) → Plan`
- Plan validation, CHILD_ENTITY_INVOCATION injection, step_id generation
- `_expand_goal()` from RecursiveReasoningEngine → `PlannerService.decompose(goal)`

**New capability** (WS-5): `adapt_plan(plan, step_results, goal) → RevisedPlan`

**Interface:**
```python
class PlannerService:
    async def reconcile(entity, context, input_data) -> List[PlanStep]
    async def decompose(goal, max_depth) -> List[GoalNode]
    async def adapt_plan(plan, completed, failed_step, goal) -> List[PlanStep]
```

**Effort**: 1 day

#### WS-3.3: CortexBridge Extraction

**New File**: `src/ai/cortex_bridge.py`

**Methods to extract from worker.py:**
- `_write_step_to_cortex()` (L1068+)
- `_ingest_tool_result_to_cortex()` (L2391-2397)
- `_build_task_description()`
- Viewport refresh and checkpointing logic

**New capabilities**: Goal-tree ↔ CORTEX tree sync, garbage collection trigger

**Effort**: 4h

#### WS-3.4: ExecutionEngine Refactor

After extraction, `ExecutionEngine` becomes a thin orchestrator:

```python
class ExecutionEngine:
    def __init__(self, db, redis):
        self.planner = PlannerService(db, redis)
        self.governance = GovernanceService(db, redis)
        self.cortex = CortexBridge(db)
        self.executor = ToolExecutor(db)  # existing
        self.memory = MemoryRouter(db)     # existing
        self.llm = LLMRouter(db)           # existing

    async def execute_run(self, run_id):
        # Thin orchestration: load → gate → plan → execute → settle
```

**Effort**: 4h (rewiring after extractions)

#### WS-3.5: Add Execution State Machine

**Files**: `schemas.py`, `models.py`, `worker.py`

Add formal run statuses: `PAUSED`, `RESUMING`, `PARTIAL_COMPLETE`
- Define valid transitions in a state machine dict
- Validate all status changes through the state machine
- Enable proper checkpoint-resume flow

**Effort**: 2h

#### WS-3.6: Add Idempotency Keys

**Files**: `models.py` (migration), `worker.py`

- Add `idempotency_key` column to `execution_runs` and `tool_interaction_logs`
- Generate deterministic keys from `(run_id, step_id, attempt_number)`
- Check before executing: skip if key exists with completed status
- Prevents duplicate side effects on Arq retry

**Effort**: 4h

**WS-3 Total Estimated Effort: ~5 dev-days**

**Deliverables:**
- `governance_service.py` with unit tests
- `planner_service.py` with unit tests
- `cortex_bridge.py` with unit tests
- `worker.py` reduced from ~3,500 to ~1,500 lines
- Formal execution state machine
- Idempotency support for step execution
- Migration files for new columns

---

### WS-4: Performance Optimization (Week 3)

**Objective**: Fix N+1 queries, unbounded growth, and unnecessary DB hits.

| Task | Source | File(s) | Effort |
|------|--------|---------|--------|
| Replace N+1 `_build_breadcrumb()` with recursive CTE query | PERF-1 | `cortex_service.py:913-928` | 2h |
| Replace N+1 `_is_descendant_of()` with recursive CTE query | PERF-2 | `cortex_service.py:967-982` | 1h |
| Cap `context_state` growth: store summaries after threshold, not full output | DATA-1 | `worker.py:534-536` | 4h |
| Replace `sum(len(str(v))...)` size estimation with incremental byte counter | PERF-3 | `worker.py:1082` | 1h |
| Cache LLM adapter resolution per `(company_id, task_type)` for run duration | PERF-4 | `llm_router.py:821-860` | 2h |
| Track bridge paragraph LLM cost via `_log_usage()` | PERF-5 | `cortex_service.py:1076-1082` | 30m |
| Batch CORTEX node writes (buffer + flush per step, not per tool call) | ARCH-3 | `cortex_service.py` | 3h |
| Add Redis viewport caching (TTL=30s) to avoid repeated DB queries within step | v1 §6 | `cortex_service.py` | 2h |

**WS-4 Total Estimated Effort: ~16 hours (2 dev-days)**

**Deliverables:**
- Recursive CTE queries for CORTEX ancestry (single query vs N queries)
- Context state growth bounded to configurable limit
- LLM adapter caching eliminates redundant DB queries in REACT loops
- All LLM costs tracked including bridge paragraphs

---

### WS-5: Autonomous Agentic Loop (Week 3-4)

**Objective**: Evolve from static plan-execute to goal-centric autonomous reasoning.

#### WS-5.1: Goal Validation Gate (Low Risk)

After each step, inject a lightweight LLM call:
> "Given the original goal X and the accumulated results Y, is the goal achieved? Score 0-100."

- If score > 85 → early-exit (save compute)
- If score < 30 after 50% of steps → trigger re-planning
- Configurable via entity `logic_gate.reasoning_config`:
  ```json
  {
    "execution_mode": "AUTONOMOUS",
    "goal_validation_interval": 2,
    "confidence_threshold": 0.85
  }
  ```
- Feature-flagged: only active when `execution_mode == "AUTONOMOUS"`

**Files**: `planner_service.py`, `worker.py`  
**Effort**: 4h

#### WS-5.2: Mid-Execution Re-Planning (Medium Risk)

When a step fails or produces unexpected output:
1. Call `PlannerService.adapt_plan()` with original goal, completed steps, failure details
2. LLM generates revised plan for remaining work
3. Max 3 re-planning attempts (configurable)

**Files**: `planner_service.py`  
**Effort**: 2 days

#### WS-5.3: Async Child Entity Execution

Replace recursive in-process `await self.execute_run(child_run.id)` (A2) with Arq job dispatch:
- Parent step enqueues child run as independent Arq task
- Parent polls for completion or subscribes via Redis pub/sub
- Prevents coroutine stacking and DB session leaks in deep hierarchies

**Files**: `worker.py:1928+`  
**Effort**: 1 day

#### WS-5.4: Self-Reflective CORTEX Loop

Before each THOUGHT step:
- Auto-query CORTEX knowledge root: "What have I already learned that's relevant?"
- Prevents redundant research, enables cross-step knowledge reuse

After each step:
- Write a reflection node: "What did I learn? How does this change my approach?"

**Files**: `cortex_bridge.py`, `worker.py`  
**Effort**: 1 day

**WS-5 Total Estimated Effort: ~5 dev-days**

**Deliverables:**
- Goal validation gate with configurable thresholds
- Mid-execution re-planning capability
- Non-blocking child entity execution
- Self-reflective CORTEX memory loop
- Entity config schema extensions for autonomous mode

---

### WS-6: Tool Orchestration Modernization (Week 4)

**Objective**: Upgrade tool system from string-based to typed, add tenant isolation.

#### WS-6.1: Typed Tool Protocol

Migrate from `run(input_data: str) → str` to `run(params: ToolParams) → ToolResult`:
- Define Pydantic `ToolParams` and `ToolResult` base models
- Each tool declares its own typed params (subclass of ToolParams)
- Structured error codes in ToolResult (not string parsing)
- Backward-compatible: keep string fallback during migration

**Files**: `tools/base.py`, `tool_executor.py`, all 17 tool implementations  
**Effort**: 2 days

#### WS-6.2: Tenant-Scoped Tool Registry

Make runtime `ToolRegistry` respect `company_id` scoping:
- Load tools per-tenant from `ToolRegistryEntry` (already has `company_id` column)
- Prevent cross-tenant tool name collisions
- Cache per-tenant registry in memory with TTL

**Files**: `tools/base.py:88+`, `tool_executor.py`  
**Effort**: 4h

#### WS-6.3: Global Rate Limiter

Redis-based sliding window rate limiter shared across concurrent runs:
- Per-tool rate limits (e.g., SerpAPI: 100/minute)
- Per-company rate limits
- Replaces per-run-only `tool_call_counts`

**Files**: `tool_executor.py`, new `rate_limiter.py`  
**Effort**: 4h

**WS-6 Total Estimated Effort: ~3 dev-days**

---

### WS-7: Frontend Updates (Week 4-5)

**Objective**: Update frontend to support new backend capabilities.

#### WS-7.1: Entity Configuration Updates

**File**: `EntityConfigurationTabs.tsx` (117KB — largest frontend file)

- Add "Autonomous Mode" toggle in Logic Gate tab
- Add goal validation interval, confidence threshold, max re-planning attempts controls
- Add execution mode selector: `STANDARD` | `AUTONOMOUS`

**Effort**: 4h

#### WS-7.2: Execution Detail Enhancements

**Files**: `ExecutionDetail.tsx`, `ExecutionDetail.css`

- Display goal validation scores per step (new field from backend)
- Show re-planning events in execution timeline
- Display child run status as async jobs (not inline)
- Show new run statuses: PAUSED, RESUMING

**Effort**: 4h

#### WS-7.3: HITL Panel Improvements

**File**: `HITLPanel.tsx`

- Remove internal topology exposure (step_id, internal cost) from approval view
- Add sanitized context display

**Effort**: 1h

#### WS-7.4: Execution History Filters

**Files**: `ExecutionHistory.tsx`, `ExecutionPage.tsx`

- Filter by new statuses (PAUSED, RESUMING, PARTIAL_COMPLETE)
- Show re-planning count badge

**Effort**: 2h

**WS-7 Total Estimated Effort: ~1.5 dev-days**

---

### WS-8: Observability & Testing (Week 5)

#### WS-8.1: Structured Logging

- Ensure all AI module logging uses `logger.*()` with structured context
- Add correlation IDs (run_id, step_id) to all log entries
- Configure log aggregation format

**Effort**: 1 day

#### WS-8.2: Test Coverage

| Test Type | Target | Effort |
|-----------|--------|--------|
| Unit tests for GovernanceService | Credit gates, HITL evaluation, billing | 4h |
| Unit tests for PlannerService | Plan reconciliation, adaptation | 4h |
| Unit tests for CortexBridge | Node writes, viewport, checkpointing | 3h |
| Integration test: full execute_run (sequential) | End-to-end happy path | 4h |
| Integration test: full execute_run (DAG) | Parallel steps, billing, context merge | 4h |
| Integration test: autonomous loop | Goal validation, re-planning, early exit | 3h |
| Race condition tests | Concurrent DAG steps, shared state | 3h |

**WS-8 Total Estimated Effort: ~4 dev-days**

---

## 3. Timeline Summary

| Week | Workstream | Focus |
|------|-----------|-------|
| **Week 1** | WS-1 + WS-2 | Critical fixes, dead code removal, deduplication |
| **Week 2** | WS-3 (first half) | GovernanceService + PlannerService extraction |
| **Week 3** | WS-3 (second half) + WS-4 | CortexBridge extraction, performance optimization |
| **Week 4** | WS-5 + WS-6 | Autonomous loop, tool modernization |
| **Week 5** | WS-7 + WS-8 | Frontend updates, testing, observability |

**Total Estimated Effort: ~24 dev-days (5 weeks at ~5 days/week)**

---

## 4. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Service extraction breaks existing execution flows | Medium | High | Feature-flag new services, keep old paths as fallback |
| DAG concurrency fixes cause performance regression | Low | Medium | Benchmark before/after with 5-step parallel plan |
| Autonomous loop increases LLM costs significantly | Medium | Medium | Goal validation is lightweight call; configurable interval |
| Frontend EntityConfigurationTabs (117KB) edit causes regressions | Medium | Medium | Test all 7 tab sections after changes |
| Database migrations on production data | Low | High | Additive-only migrations (new columns, no drops) |

---

## 5. Success Criteria

1. **Worker.py** reduced from ~3,500 lines to ~1,500 lines
2. **Zero** P0 bugs remaining from v1 and v2 reviews
3. **Unit test coverage** for all extracted services (GovernanceService, PlannerService, CortexBridge)
4. **DAG execution** correctly isolates context, billing, and ORM objects across parallel steps
5. **Goal validation gate** demonstrably saves compute on early-achievable goals
6. **CORTEX breadcrumb queries** reduced from O(depth) to O(1) via recursive CTE
7. **No** `print()` statements in production code paths
8. **All** LLM costs tracked (including bridge paragraphs)
9. **Idempotent** step execution — retry-safe with no duplicate side effects

---

## 6. Out of Scope (Future Phases)

| Item | Source | Rationale |
|------|--------|-----------|
| Full RecursiveReasoningEngine promotion with CORTEX integration | P3 #20 | Depends on WS-5 stabilization |
| Inter-agent message bus (Redis pub/sub blackboard) | G3, P3 #21 | Requires architectural design spike |
| CORTEX tree garbage collection / archival job | G6, P3 #22 | Operational concern, not blocking |
| OpenTelemetry distributed tracing integration | G9, P3 #23 | Infrastructure dependency |
| Streaming LLM output via SSE to frontend | G7, P3 #24 | Requires gateway changes |
| Tool pipeline DSL (tool chaining) | v1 §7 | Post-typed-tool-protocol |

---

## 7. File Impact Matrix

### Backend — Files Modified

| File | Workstream | Change Type |
|------|-----------|-------------|
| `worker.py` | WS-1,2,3,5 | Major refactor (3500→1500 lines) |
| `cortex_service.py` | WS-4 | CTE queries, batching, caching |
| `memory_service.py` | WS-1 | Fix metadata column, embedding model |
| `service.py` | WS-2 | Deduplicate clone logic |
| `llm_router.py` | WS-4 | Adapter caching |
| `tool_executor.py` | WS-6 | Typed protocol, tenant scoping |
| `tools/base.py` | WS-6 | New ToolParams/ToolResult, scoped registry |
| `schemas.py` | WS-3,5 | New statuses, autonomous config |
| `models.py` | WS-3 | Idempotency key, new statuses |

### Backend — New Files

| File | Workstream | Purpose |
|------|-----------|---------|
| `governance_service.py` | WS-3 | HITL, billing, credit gates |
| `planner_service.py` | WS-3,5 | Plan reconciliation, adaptation |
| `cortex_bridge.py` | WS-3 | CORTEX tree lifecycle |
| `constants.py` | WS-2 | Centralized constants |
| `text_extractor.py` | WS-2 | Unified document parsing |
| `rate_limiter.py` | WS-6 | Redis sliding window |

### Frontend — Files Modified

| File | Workstream | Change Type |
|------|-----------|-------------|
| `EntityConfigurationTabs.tsx` | WS-7 | Autonomous mode controls |
| `ExecutionDetail.tsx` | WS-7 | Goal scores, re-planning events |
| `HITLPanel.tsx` | WS-7 | Sanitized context display |
| `ExecutionHistory.tsx` | WS-7 | New status filters |

### Database Migrations

| Migration | Workstream | Description |
|-----------|-----------|-------------|
| Add `idempotency_key` to `execution_runs` | WS-3 | Retry-safe execution |
| Add `idempotency_key` to `tool_interaction_logs` | WS-3 | Retry-safe tool calls |
| Index on `(run_id, step_id, idempotency_key)` | WS-3 | Fast dedup lookup |
