# Phase 6: Implementation Plan — Part 1 (Phases 1–3)

> **Date**: 2026-05-07  
> **References**: [architecture_review.md](./architecture_review.md), [architecture_review_v2.md](./architecture_review_v2.md), [scope_of_work.md](./scope_of_work.md)  
> **Continues in**: [implementation_plan_part2.md](./implementation_plan_part2.md)

---

## Phase 1: Critical Stabilization (Week 1, Days 1–3)

> **Goal**: Fix all P0 bugs — data loss, race conditions, runtime crashes, security risks.  
> **Principle**: Zero behavioral changes. Pure bug fixes. Every fix gets a regression test.

---

### Step 1.1 — Quick Wins (Day 1, Morning — 2h)

These are < 30-minute fixes that can be batch-committed together.

#### 1.1.1 Fix Episodic Memory Column Name (DATA-3)

**File**: `backend/src/ai/memory_service.py:157`

```diff
- metadata={
+ metadata_info={
      "tools_used": tools_used,
      "step_count": step_count,
  },
```

**Test**: Write an episodic memory record → query it → assert `metadata_info` is populated (not None).

#### 1.1.2 Unify Embedding Model (DATA-4)

**New file**: `backend/src/ai/constants.py`

```python
EMBEDDING_MODEL = "gemini-embedding-004"
```

**Modify** `memory_service.py:213` and `worker.py:3255` to import and use `EMBEDDING_MODEL`.

**Test**: Grep codebase for hardcoded embedding model strings → assert only `constants.py` defines it.

#### 1.1.3 Fix Cost Rollup TypeError (DATA-5)

**File**: `backend/src/ai/worker.py:1948`

```diff
- run.total_cost_usd += child_run.total_cost_usd or 0
+ run.total_cost_usd = (run.total_cost_usd or Decimal("0")) + Decimal(str(child_run.total_cost_usd or 0))
```

**Test**: Create a run with `total_cost_usd=None`, execute child rollup → assert no TypeError.

#### 1.1.4 Fix RecursiveReasoningEngine (G4)

**File**: `backend/src/ai/worker.py:3419`

Add `company_id` parameter to `__init__` and store as `self.company_id`.

#### 1.1.5 Fix Deprecated Event Loop Call (C5)

**File**: `backend/src/ai/worker.py:647,650`

```diff
- deadline = asyncio.get_event_loop().time() + timeout_sec
+ deadline = asyncio.get_running_loop().time() + timeout_sec
- while asyncio.get_event_loop().time() < deadline:
+ while asyncio.get_running_loop().time() < deadline:
```

#### 1.1.6 HITL Pub/Sub Leak Fix (RACE-3)

**File**: `backend/src/ai/worker.py:643-670`

Wrap the entire pub/sub block in `try/finally`:

```python
pubsub = self.redis.client.pubsub()
try:
    await pubsub.subscribe(approval_channel)
    # ... existing polling loop ...
finally:
    await pubsub.unsubscribe(approval_channel)
```

#### 1.1.7 Reset Tool Call Counts Per Step (ERR-3)

**File**: `backend/src/ai/worker.py:2364-2365`

```diff
- if 'tool_call_counts' not in context:
-     context['tool_call_counts'] = {}
+ context['tool_call_counts'] = {}  # Always reset per step
```

---

### Step 1.2 — DAG Concurrency Fixes (Day 1 Afternoon + Day 2 — 8h)

These are the most critical fixes in the entire phase. DAG parallel execution currently has shared mutable state that can cause data corruption.

#### 1.2.1 Fix Shared Context State (RACE-1)

**File**: `backend/src/ai/worker.py:453-461`

**Current problem**: All parallel coroutines share the same `context_state` dict. Writes from one step are visible to siblings mid-execution.

**Implementation**:

```python
async def _isolated_step(step_dict: dict, frozen_ctx: dict) -> dict:
    async with AsyncSessionLocal() as isolated_db:
        isolated_engine = ExecutionEngine(isolated_db, self.redis)
        step_obj = PlanStep(**step_dict)
        return await isolated_engine._execute_step_wrapper(
            run_id, entity_id, step_obj, frozen_ctx  # isolated copy
        )

# Deep-copy context for each parallel step
tasks = [_isolated_step(s, copy.deepcopy(context_state)) for s in ready]
batch_results = await asyncio.gather(*tasks, return_exceptions=True)

# Merge results back into parent context
for i, result in enumerate(batch_results):
    step_id = ready[i]["step_id"]
    if not isinstance(result, Exception) and isinstance(result, dict):
        if "output" in result:
            context_state[ready[i]["name"]] = result["output"]
            context_state[step_id] = result["output"]
```

#### 1.2.2 Fix Shared ORM Run Object (RACE-2)

**File**: `backend/src/ai/worker.py:458`

**Current problem**: The `run` ORM object is loaded in the parent session but mutated by isolated sessions, causing `DetachedInstanceError` and lost cost updates.

**Implementation**:
1. Pass `run.id` (UUID) instead of `run` object to `_isolated_step`
2. Inside isolated step, reload run from `isolated_db`
3. Use atomic DB increments for cost accumulation:

```python
# Inside _isolated_step, after step execution:
await isolated_db.execute(
    update(ExecutionRun)
    .where(ExecutionRun.id == run_id)
    .values(
        total_cost_usd=ExecutionRun.total_cost_usd + step_cost,
        total_tokens=ExecutionRun.total_tokens + step_tokens,
    )
)
await isolated_db.commit()
```

4. After `asyncio.gather`, refresh `run` from DB to get accumulated values.

#### 1.2.3 Fix DAG Billing Gap (C1)

**File**: `backend/src/ai/worker.py:1001-1007`

Add per-step billing deduction and credit circuit-breaker inside the DAG path, matching what the sequential path does. Each isolated step must call `consume_incremental` and check balance.

#### 1.2.4 Fix DAG Error Handling (ERR-2)

**File**: `backend/src/ai/worker.py:466-468`

```python
# Collect ALL results first, then decide
failures = []
for i, result in enumerate(batch_results):
    step_id = ready[i]["step_id"]
    if isinstance(result, Exception):
        results_map[step_id] = {"error": str(result), "step": ready[i]["name"]}
        context_state[step_id] = f"[FAILED] {result}"  # Write to context for debugging
        failures.append((step_id, result))
    else:
        results_map[step_id] = result
        completed.add(step_id)

if failures:
    raise failures[0][1]  # Raise first failure after saving all results
```

**Test plan**:
- Create a 3-step DAG where step 2 fails → assert steps 1 and 3 results are preserved
- Create a 3-step parallel batch → assert `context_state` has no cross-contamination
- Create parallel steps with billing → assert `total_cost_usd` reflects all steps

---

### Step 1.3 — Error Recovery & Security (Day 2-3 — 6h)

#### 1.3.1 Fix BaseException Handler (ERR-1)

**File**: `backend/src/ai/worker.py:1188-1205`

```python
except BaseException as e:
    try:
        await self.db.rollback()  # Ensure clean state
        async with AsyncSessionLocal() as fresh_db:
            result = await fresh_db.execute(
                select(ExecutionRun).where(ExecutionRun.id == run.id)
            )
            failed_run = result.scalar_one()
            failed_run.status = RunStatus.FAILED
            failed_run.error_message = str(e)[:2000]
            failed_run.context_state = context_state
            failed_run.completed_at = datetime.utcnow()
            await fresh_db.commit()
    except Exception:
        logger.error(f"Failed to persist FAILED status for run {run.id}")
    raise
```

#### 1.3.2 Write Failed Steps to Context (DATA-2)

**File**: `backend/src/ai/worker.py:507-516`

In the exception handler inside `_execute_step_wrapper`, add:
```python
context_state[step_obj.step_id] = f"[ERROR] {str(e)[:500]}"
```

#### 1.3.3 Strip Sensitive Keys from Persisted Context (SEC-1)

**File**: `backend/src/ai/worker.py:1096,1199`

Create a helper function and call before persisting:

```python
def _sanitize_context_for_persistence(ctx: dict) -> dict:
    """Strip internal keys and truncate large values before DB write."""
    sanitized = {}
    for k, v in ctx.items():
        if k.startswith("__") and k.endswith("__"):
            continue  # Skip __context_sources__, __cortex_knowledge__, etc.
        if isinstance(v, str) and len(v) > 10000:
            sanitized[k] = v[:10000] + "... [truncated]"
        else:
            sanitized[k] = v
    return sanitized
```

#### 1.3.4 Sanitize HITL Context Snapshot (SEC-3)

**File**: `backend/src/ai/worker.py:617-622`

Remove `step_id` from context_snapshot, keep only user-facing info:
```python
context_snapshot={
    "step_name": step_obj.name,
    "message": cp.message or f"Approval required: {trigger_desc}",
}
```

---

### Step 1.4 — Dead Code Removal & Logging (Day 3 — 4h)

#### 1.4.1 Remove Dead Code

| Action | Location |
|--------|----------|
| Delete `call_llm_unified()` function | `worker.py:330-365` |
| Delete `_get_api_key()` method | `worker.py:2639-2651` |
| Remove redundant local `import copy` | `worker.py:1582, 1779` |

#### 1.4.2 Consolidate _INTERNAL_KEYS

**File**: `backend/src/ai/constants.py` (append to file created in 1.1.2)

```python
INTERNAL_CONTEXT_KEYS = frozenset({
    "input", "cortex_tree_id", "subtree_root_id",
    "__cortex_knowledge__", "__context_sources__",
    "tool_call_counts", "company_id", "user_id",
    "__cortex_viewport__", "__episodic_memory__",
    "__semantic_context__", "__memory_context__",
})
```

Replace both `_INTERNAL_KEYS` definitions in `worker.py` with this import.

#### 1.4.3 Replace print() with logger

Replace all 55+ `print()` calls in `worker.py` with appropriate `logger.info()`, `logger.warning()`, or `logger.debug()` calls. Add structured context (run_id, step_name) where available.

**Verification**: `grep -n "print(" backend/src/ai/worker.py | wc -l` should return 0.

---

### Phase 1 Gate

Before proceeding to Phase 2, verify:
- [ ] All unit tests pass
- [ ] `grep -rn "print(" backend/src/ai/worker.py` returns 0 hits
- [ ] Sequential execute_run happy path test passes
- [ ] DAG execute_run with 3 parallel steps test passes
- [ ] No `_get_api_key` or `call_llm_unified` references remain

---

## Phase 2: Code Deduplication & Refactoring (Week 1–2, Days 4–5)

> **Goal**: Eliminate duplication, extract reusable modules, centralize constants.

---

### Step 2.1 — Deduplicate Clone Logic (2h)

**File**: `backend/src/ai/service.py`

1. Create a shared private function `_clone_and_remap(entity, new_company_id)` using the `clone_template` deep-copy approach (which correctly uses `copy.deepcopy` + `flag_modified`)
2. Refactor `save_as_template()` (L812-853) to call the shared function
3. Refactor `clone_template()` (L972-1096) to call the shared function
4. **Critical**: Fix the shallow-copy mutation bug in `save_as_template` by using `copy.deepcopy` for nested dicts (planning, hierarchy, capabilities)

**Test**: Clone an entity with nested planning steps containing child references → assert original entity's planning is unmodified.

---

### Step 2.2 — Extract Text Extractor (3h)

**New file**: `backend/src/ai/text_extractor.py`

Extract and unify text extraction from:
- `worker.py:_extract_text_from_file()` (L1500-1568) — handles PDF/DOCX/XLSX/PPTX/CSV
- `worker.py:process_document()` (L3225-3290) — handles PDF/DOCX only

```python
class TextExtractor:
    @staticmethod
    async def extract(file_path: str, file_type: str) -> str:
        """Unified text extraction for all supported formats."""
        extractors = {
            "pdf": TextExtractor._extract_pdf,
            "docx": TextExtractor._extract_docx,
            "xlsx": TextExtractor._extract_xlsx,
            "pptx": TextExtractor._extract_pptx,
            "csv": TextExtractor._extract_csv,
            "txt": TextExtractor._extract_txt,
        }
        extractor = extractors.get(file_type.lower())
        if not extractor:
            raise ValueError(f"Unsupported file type: {file_type}")
        return await extractor(file_path)
```

Replace both call sites in `worker.py` with `TextExtractor.extract()`.

---

### Step 2.3 — Extract Context Source Loading (1h)

**File**: `backend/src/ai/worker.py:862-981`

Extract the 120-line inline block into `async def _load_context_sources(self, entity, context_state) -> None`.

This method handles: DOCUMENT sources, KNOWLEDGE_BASE semantic search, CORTEX_TREE viewport injection, and DB_RECORDS queries.

---

### Step 2.4 — Centralize Magic Numbers (1h)

**File**: `backend/src/ai/constants.py` (append)

```python
MAX_REACT_TURNS = 12
CONTEXT_TOKEN_ESTIMATION_DIVISOR = 4
MAX_CONTENT_CHARS = 50000
MAX_CONTEXT_TRUNCATION_CHARS = 6000
CONTEXT_SUMMARIZE_THRESHOLD = 20000
DEFAULT_TIMEOUT_MS = 60000
```

Replace all hardcoded literals in `worker.py` with these constants.

### Phase 2 Gate

- [ ] `service.py` has zero duplicated clone logic
- [ ] `text_extractor.py` passes unit tests for PDF, DOCX, XLSX, CSV
- [ ] `constants.py` contains all centralized values
- [ ] No hardcoded embedding model strings outside `constants.py`

---

## Phase 3: Monolith Decomposition (Week 2–3, Days 6–15)

> **Goal**: Extract GovernanceService, PlannerService, CortexBridge from ExecutionEngine. Reduce worker.py from ~3,500 to ~1,500 lines.

---

### Step 3.1 — GovernanceService Extraction (Days 6–7)

**New file**: `backend/src/ai/governance_service.py`

#### Methods to Extract

| From worker.py | To GovernanceService | Lines Moved |
|---------------|---------------------|-------------|
| `_evaluate_hitl_checkpoints()` | `evaluate_hitl()` | ~150 |
| `_safe_eval_hitl_expression()` | `_safe_eval_expression()` | ~35 |
| Credit gate logic (L770-786) | `check_credit_gate()` | ~20 |
| Incremental billing (scattered) | `consume_incremental()` | ~40 |
| TB settlement (in finalize block) | `settle_billing()` | ~30 |

#### Interface

```python
class GovernanceService:
    def __init__(self, db: AsyncSession, redis):
        self.db = db
        self.redis = redis
        self.credit_service = CreditService(db)
        self.billing_service = BillingService(db)

    async def check_credit_gate(self, company_id: UUID, entity_type: str) -> dict:
        """Pre-execution credit balance check. Raises InsufficientCreditsError."""

    async def evaluate_hitl(self, run, entity, step, context, phase: str) -> None:
        """Evaluate HITL checkpoints. Blocks on approval if triggered."""

    async def consume_incremental(self, run_id: UUID, step_cost: Decimal) -> bool:
        """Deduct step cost from credits. Returns False if circuit-break triggered."""

    async def settle_billing(self, run_id: UUID) -> Decimal:
        """Final TB-formula billing settlement. Returns billed amount."""
```

#### Worker.py Changes

Replace direct calls with service delegation:
```python
# Before
await self._evaluate_hitl_checkpoints(run, entity, step_obj, context_state, phase="BEFORE")
# After
await self.governance.evaluate_hitl(run, entity, step_obj, context_state, phase="BEFORE")
```

**Tests**: Unit test each method with mocked DB/Redis. Test credit gate with sufficient/insufficient balance. Test HITL with approval/rejection/timeout.

---

### Step 3.2 — PlannerService Extraction (Days 8–9)

**New file**: `backend/src/ai/planner_service.py`

#### Methods to Extract

| From worker.py | To PlannerService | Lines Moved |
|---------------|-------------------|-------------|
| `_get_reconciled_plan()` | `reconcile()` | ~200 |
| Plan validation logic | `_validate_plan()` | ~50 |
| CHILD_ENTITY_INVOCATION injection | `_inject_child_steps()` | ~40 |
| step_id generation | `_assign_step_ids()` | ~20 |
| GoalNode expansion (from RecursiveReasoningEngine) | `decompose()` | ~60 |

#### Interface

```python
class PlannerService:
    def __init__(self, db: AsyncSession, company_id: UUID):
        self.db = db
        self.company_id = company_id
        self.llm = LLMRouter(db=db, company_id=company_id)

    async def reconcile(self, entity, context: dict, input_data: dict) -> List[dict]:
        """Generate reconciled plan from static + dynamic planning config."""

    async def decompose(self, goal: str, max_depth: int = 3) -> List[GoalNode]:
        """Decompose a high-level goal into a tree of sub-goals."""

    async def adapt_plan(self, original_plan, completed_steps, failed_step, goal) -> List[dict]:
        """Mid-execution re-planning (implemented in Phase 5)."""
        raise NotImplementedError("Phase 5 - Autonomous Loop")
```

---

### Step 3.3 — CortexBridge Extraction (Day 10)

**New file**: `backend/src/ai/cortex_bridge.py`

#### Methods to Extract

| From worker.py | To CortexBridge | Lines Moved |
|---------------|-----------------|-------------|
| `_write_step_to_cortex()` | `write_step()` | ~40 |
| `_ingest_tool_result_to_cortex()` | `ingest_tool_result()` | ~30 |
| `_build_task_description()` | `build_task_description()` | ~25 |
| Viewport refresh logic | `refresh_viewport()` | ~20 |
| Checkpoint logic | `write_checkpoint()` | ~30 |

#### Interface

```python
class CortexBridge:
    def __init__(self, db: AsyncSession, company_id: UUID):
        self.db = db
        self.cortex = CortexService(db=db, company_id=company_id)

    async def init_tree(self, entity, run, input_data) -> tuple:
        """Create or resume a CORTEX tree. Returns (tree, cursor_node)."""

    async def write_step(self, tree_id, cursor_id, step_name, result, step_type) -> str:
        """Write step result to CORTEX tree. Returns new node_id."""

    async def ingest_tool_result(self, tree_id, cursor_id, tool_name, result) -> None:
        """Ingest tool output as a CORTEX finding node."""

    async def refresh_viewport(self, tree_id, cursor_id) -> dict:
        """Get current viewport for context injection."""

    async def write_checkpoint(self, tree_id, cursor_id, summary, key_facts) -> None:
        """Write a checkpoint node for resume capability."""
```

---

### Step 3.4 — ExecutionEngine Rewiring (Days 11–12)

**File**: `backend/src/ai/worker.py`

Refactor `ExecutionEngine.__init__` to compose the new services:

```python
class ExecutionEngine:
    def __init__(self, db: AsyncSessionLocal, redis_pool):
        self.db = db
        self.redis = redis_pool
        self.config_service = ConfigService(db)
        self.usage_service = UsageService(db)
        # New service composition
        self._governance = None  # Lazy init (needs company_id)
        self._planner = None
        self._cortex_bridge = None

    def _init_services(self, company_id: UUID):
        """Initialize services that require company_id (known after entity load)."""
        self._governance = GovernanceService(self.db, self.redis)
        self._planner = PlannerService(self.db, company_id)
        self._cortex_bridge = CortexBridge(self.db, company_id)
```

Update `execute_run()` flow:
1. Load entity → `_init_services(entity.company_id)`
2. Credit gate → `self._governance.check_credit_gate(...)`
3. Plan → `self._planner.reconcile(...)`
4. Per-step HITL → `self._governance.evaluate_hitl(...)`
5. Per-step CORTEX → `self._cortex_bridge.write_step(...)`
6. Settle → `self._governance.settle_billing(...)`

---

### Step 3.5 — Execution State Machine (Day 13)

**Files**: `schemas.py`, `models.py`

Add new statuses to `RunStatus`:
```python
class RunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"          # NEW: Waiting for HITL approval
    RESUMING = "RESUMING"      # NEW: Resuming from checkpoint
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PARTIAL_COMPLETE = "PARTIAL_COMPLETE"  # NEW: Some steps done, others failed
    REPAIRING = "REPAIRING"
```

Add transition validation:
```python
VALID_TRANSITIONS = {
    "PENDING": {"RUNNING"},
    "RUNNING": {"PAUSED", "COMPLETED", "FAILED", "PARTIAL_COMPLETE"},
    "PAUSED": {"RUNNING", "RESUMING", "FAILED"},
    "RESUMING": {"RUNNING", "FAILED"},
    "PARTIAL_COMPLETE": {"RUNNING", "COMPLETED", "FAILED"},
}
```

---

### Step 3.6 — Idempotency Keys (Day 14)

**Migration**: Add columns to `execution_runs` and `tool_interaction_logs`:

```sql
ALTER TABLE execution_runs ADD COLUMN idempotency_key VARCHAR(255);
ALTER TABLE tool_interaction_logs ADD COLUMN idempotency_key VARCHAR(255);
CREATE INDEX idx_exec_runs_idemp ON execution_runs(idempotency_key) WHERE idempotency_key IS NOT NULL;
```

**Worker.py**: Before executing any step, generate and check key:

```python
idemp_key = f"{run.id}:{step.step_id}:{attempt}"
existing = await self.db.execute(
    select(ToolInteractionLog).where(ToolInteractionLog.idempotency_key == idemp_key)
)
if existing.scalar_one_or_none():
    logger.info(f"Skipping duplicate step execution: {idemp_key}")
    return cached_result
```

---

### Phase 3 Gate

- [ ] `worker.py` is < 1,800 lines
- [ ] `governance_service.py` has 100% unit test coverage on public methods
- [ ] `planner_service.py` has unit tests for reconcile() with static/dynamic/hybrid plans
- [ ] `cortex_bridge.py` has unit tests for write_step and checkpoint
- [ ] All existing execute_run integration tests still pass
- [ ] Database migration applies cleanly
- [ ] State machine rejects invalid transitions

---

> **Continued in [implementation_plan_part2.md](./implementation_plan_part2.md)** — Phases 4–6 covering Performance Optimization, Autonomous Loop, Tool Modernization, Frontend Updates, and Testing.
