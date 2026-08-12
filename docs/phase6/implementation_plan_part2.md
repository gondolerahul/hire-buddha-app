# Phase 6: Implementation Plan — Part 2 (Phases 4–6)

> **Date**: 2026-05-07  
> **Continues from**: [implementation_plan_part1.md](./implementation_plan_part1.md)

---

## Phase 4: Performance Optimization (Week 3, Days 11–15)

> **Goal**: Fix N+1 queries, unbounded context growth, redundant DB hits, and untracked LLM costs.

---

### Step 4.1 — CORTEX Recursive CTE Queries (3h)

**File**: `backend/src/ai/cortex_service.py`

#### 4.1.1 Replace `_build_breadcrumb()` (L913-928)

**Current**: N sequential `SELECT` queries to walk from node to root. A depth-8 tree × 10 steps = 80 queries per run.

**New implementation**:

```python
async def _build_breadcrumb(self, node_id: UUID) -> List[dict]:
    query = text("""
        WITH RECURSIVE ancestors AS (
            SELECT id, parent_id, title, 0 AS depth
            FROM cortex_nodes WHERE id = :node_id
            UNION ALL
            SELECT cn.id, cn.parent_id, cn.title, a.depth + 1
            FROM cortex_nodes cn
            JOIN ancestors a ON cn.id = a.parent_id
        )
        SELECT id, title FROM ancestors ORDER BY depth DESC
    """)
    result = await self.db.execute(query, {"node_id": str(node_id)})
    return [{"id": str(r.id), "title": r.title} for r in result.fetchall()]
```

#### 4.1.2 Replace `_is_descendant_of()` (L967-982)

Same recursive CTE pattern — single query to check ancestry:

```python
async def _is_descendant_of(self, node_id: UUID, ancestor_id: UUID) -> bool:
    query = text("""
        WITH RECURSIVE ancestors AS (
            SELECT id, parent_id FROM cortex_nodes WHERE id = :node_id
            UNION ALL
            SELECT cn.id, cn.parent_id
            FROM cortex_nodes cn JOIN ancestors a ON cn.id = a.parent_id
        )
        SELECT 1 FROM ancestors WHERE id = :ancestor_id LIMIT 1
    """)
    result = await self.db.execute(query, {
        "node_id": str(node_id), "ancestor_id": str(ancestor_id)
    })
    return result.scalar() is not None
```

**Test**: Create a 10-level tree → assert breadcrumb returns correct path in 1 query. Assert `_is_descendant_of` returns True/False correctly.

---

### Step 4.2 — Context State Growth Cap (DATA-1, 4h)

**File**: `backend/src/ai/worker.py` (or extracted executor)

**Current**: Every step output stored in `context_state` twice (by name + step_id). A 10-step run with 20KB/step = 400KB context, growing quadratically in prompt tokens.

**Implementation**:

```python
MAX_CONTEXT_VALUE_SIZE = 5000  # chars per step output in context

def _store_step_output(context_state: dict, step_name: str, step_id: str, output: str):
    """Store step output with size cap. Large outputs get summarized reference."""
    if len(output) <= MAX_CONTEXT_VALUE_SIZE:
        context_state[step_name] = output
        if step_id and step_id != step_name:
            context_state[step_id] = output
    else:
        truncated = output[:MAX_CONTEXT_VALUE_SIZE] + f"\n... [truncated from {len(output)} chars]"
        context_state[step_name] = truncated
        if step_id and step_id != step_name:
            context_state[step_id] = truncated
```

Also replace the O(n) size estimation at L1082:

```python
# Before: ctx_size = sum(len(str(v)) for v in context_state.values()) // 4
# After: maintain incremental counter
self._context_byte_count += len(output)
ctx_size = self._context_byte_count // CONTEXT_TOKEN_ESTIMATION_DIVISOR
```

---

### Step 4.3 — LLM Adapter Caching (PERF-4, 2h)

**File**: `backend/src/ai/llm_router.py:821-860`

Add per-run caching for `_resolve_adapter()`:

```python
class LLMRouter:
    def __init__(self, db, company_id):
        self.db = db
        self.company_id = company_id
        self._adapter_cache: Dict[str, Any] = {}  # task_type -> adapter

    async def _resolve_adapter(self, task_type: str):
        cache_key = f"{self.company_id}:{task_type}"
        if cache_key in self._adapter_cache:
            return self._adapter_cache[cache_key]
        adapter = await self._do_resolve(task_type)  # existing DB query
        self._adapter_cache[cache_key] = adapter
        return adapter
```

---

### Step 4.4 — Track Bridge Paragraph Cost (PERF-5, 30m)

**File**: `backend/src/ai/cortex_service.py:1076-1082`

After the `_generate_bridge_paragraphs()` LLM call, add usage logging:

```python
result = await llm.call_llm(task_type="bridge_generation", ...)
# Add cost tracking (currently missing)
if hasattr(result, 'prompt_tokens'):
    await usage_service.log_usage(
        company_id=self.company_id,
        run_id=run_id,
        model_name=result.model_name,
        tokens=result.prompt_tokens + result.completion_tokens,
        cost=result.cost_usd,
    )
```

---

### Step 4.5 — Batch CORTEX Node Writes (ARCH-3, 3h)

**File**: `backend/src/ai/cortex_bridge.py`

Buffer writes and flush once per step instead of per tool call:

```python
class CortexBridge:
    def __init__(self, ...):
        self._write_buffer: List[dict] = []

    async def buffer_node(self, tree_id, parent_id, node_type, title, content, **kwargs):
        """Buffer a node write. Call flush_buffer() at end of step."""
        self._write_buffer.append({...})

    async def flush_buffer(self, tree_id):
        """Batch-insert all buffered nodes."""
        if not self._write_buffer:
            return
        for node_data in self._write_buffer:
            await self.cortex.write(tree_id, **node_data)
        await self.db.flush()
        self._write_buffer.clear()
```

---

### Step 4.6 — Redis Viewport Caching (2h)

**File**: `backend/src/ai/cortex_bridge.py`

Cache viewport in Redis with 30s TTL:

```python
async def refresh_viewport(self, tree_id, cursor_id) -> dict:
    cache_key = f"cortex:viewport:{tree_id}:{cursor_id}"
    cached = await self.redis.get(cache_key)
    if cached:
        return json.loads(cached)
    viewport = await self.cortex.navigate(tree_id, cursor_id)
    await self.redis.set(cache_key, json.dumps(viewport), ex=30)
    return viewport
```

### Phase 4 Gate

- [ ] Breadcrumb query count reduced from O(depth) to 1
- [ ] `_is_descendant_of` reduced from O(depth) to 1
- [ ] Context state size capped per step
- [ ] Bridge paragraph costs appear in usage logs
- [ ] Benchmark: 10-step run on depth-8 tree shows measurable query reduction

---

## Phase 5: Autonomous Agentic Loop (Week 3–4, Days 16–20)

> **Goal**: Evolve from static plan-execute to goal-centric autonomous reasoning with self-reflection.

---

### Step 5.1 — Schema Extensions for Autonomous Mode (2h)

**File**: `backend/src/ai/schemas.py`

Extend `ReasoningConfig`:

```python
class ExecutionMode(str, Enum):
    STANDARD = "STANDARD"
    AUTONOMOUS = "AUTONOMOUS"

class ReasoningConfig(BaseModel):
    # ... existing fields ...
    execution_mode: ExecutionMode = ExecutionMode.STANDARD
    goal_validation_interval: int = 2      # Validate every N steps
    confidence_threshold: float = 0.85     # Early-exit if goal confidence > this
    max_replanning_attempts: int = 3       # Max mid-execution re-plans
    self_reflection_enabled: bool = False  # Query CORTEX before acting
```

**Frontend**: Update `EntityConfigurationTabs.tsx` to expose these fields in the Logic Gate tab.

---

### Step 5.2 — Goal Validation Gate (4h)

**File**: `backend/src/ai/planner_service.py`

```python
async def validate_goal_progress(
    self, goal: str, completed_steps: List[dict], total_steps: int
) -> dict:
    """Lightweight LLM call to assess goal completion. Returns {score, reasoning}."""
    prompt = f"""Given the original goal and completed work, assess progress.

Goal: {goal}

Completed steps:
{json.dumps([{"name": s["name"], "output_summary": s.get("output", "")[:500]} for s in completed_steps], indent=2)}

Respond with JSON: {{"score": 0-100, "reasoning": "...", "goal_achieved": true/false}}"""

    result = await self.llm.call_llm(
        task_type="goal_validation",
        system_prompt="You assess goal completion progress. Be precise.",
        user_prompt=prompt,
        temperature=0.1,
        max_tokens=200,
    )
    return json.loads(result.output)
```

**Integration in worker.py** (inside step execution loop):

```python
reasoning_config = entity.logic_gate.get("reasoning_config", {})
if reasoning_config.get("execution_mode") == "AUTONOMOUS":
    interval = reasoning_config.get("goal_validation_interval", 2)
    if step_index > 0 and step_index % interval == 0:
        validation = await self._planner.validate_goal_progress(
            goal=entity.goal, completed_steps=completed, total_steps=len(steps)
        )
        if validation.get("score", 0) > reasoning_config.get("confidence_threshold", 0.85) * 100:
            logger.info(f"Goal achieved early at step {step_index}: score={validation['score']}")
            break  # Early exit
        if validation.get("score", 0) < 30 and step_index > len(steps) // 2:
            steps = await self._planner.adapt_plan(steps, completed, current_step, entity.goal)
```

---

### Step 5.3 — Mid-Execution Re-Planning (2 days)

**File**: `backend/src/ai/planner_service.py`

```python
async def adapt_plan(
    self, original_plan: List[dict], completed: List[dict],
    failed_step: dict, goal: str
) -> List[dict]:
    """Generate revised plan based on execution progress and failures."""
    prompt = f"""The original plan partially executed. Revise the remaining steps.

Goal: {goal}

Completed successfully:
{json.dumps([{"name": s["name"], "output": s.get("output", "")[:300]} for s in completed], indent=2)}

Failed step:
{json.dumps({"name": failed_step.get("name"), "error": failed_step.get("error", "")[:500]}, indent=2)}

Original remaining steps:
{json.dumps([s for s in original_plan if s["step_id"] not in {c["step_id"] for c in completed}], indent=2)}

Generate a revised plan (JSON array) for the remaining work. You may add, remove, or modify steps."""

    result = await self.llm.call_llm(
        task_type="plan_adaptation",
        system_prompt=DEFAULT_PLANNING_SYSTEM_PROMPT,
        user_prompt=prompt,
    )
    revised = json.loads(result.output)
    return self._assign_step_ids(revised, start_from=len(completed) + 1)
```

**Worker.py integration**: When a step fails and autonomous mode is enabled, call `adapt_plan()` instead of immediately failing the run. Track re-planning count; abort after `max_replanning_attempts`.

---

### Step 5.4 — Async Child Entity Execution (1 day)

**File**: `backend/src/ai/worker.py` (child invocation section ~L1928)

Replace recursive in-process call with Arq job dispatch:

```python
async def _execute_child_invocation(self, run, entity, step, context):
    # Create child run record
    child_run = ExecutionRun(entity_id=child_entity_id, parent_run_id=run.id, ...)
    self.db.add(child_run)
    await self.db.commit()

    # Dispatch as independent Arq job (non-blocking)
    job = await self.redis.enqueue_job("execute_run", str(child_run.id))

    # Poll for completion via Redis pub/sub
    channel = f"execution:{child_run.id}"
    pubsub = self.redis.client.pubsub()
    try:
        await pubsub.subscribe(channel)
        timeout = (entity.governance or {}).get("timeout_ms", 300000) / 1000
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg and msg["type"] == "message":
                data = json.loads(msg["data"])
                if data.get("status") in ("COMPLETED", "FAILED"):
                    break
            await asyncio.sleep(0.5)
    finally:
        await pubsub.unsubscribe(channel)

    # Reload child run result
    await self.db.refresh(child_run)
    return child_run.result_data
```

---

### Step 5.5 — Self-Reflective CORTEX Loop (1 day)

**File**: `backend/src/ai/cortex_bridge.py`

```python
async def get_relevant_knowledge(self, tree_id, current_task: str) -> str:
    """Query CORTEX knowledge root for relevant prior findings."""
    knowledge_root = await self.cortex.get_knowledge_root(tree_id)
    if not knowledge_root:
        return ""
    children = await self.cortex.get_children(tree_id, knowledge_root.id)
    relevant = [c for c in children if c.status == "complete"]
    if not relevant:
        return ""
    return "\n".join([f"- {c.title}: {c.summary}" for c in relevant[:10]])

async def write_reflection(self, tree_id, cursor_id, step_name, learning: str):
    """Write a reflection node after step execution."""
    await self.cortex.write(
        tree_id=tree_id, parent_id=cursor_id,
        node_type="finding", title=f"Reflection: {step_name}",
        content=learning, summary=learning[:200],
    )
```

**Worker.py integration**: Before THOUGHT steps (when `self_reflection_enabled`), inject knowledge context. After each step, write reflection.

### Phase 5 Gate

- [ ] Entity with `execution_mode=AUTONOMOUS` early-exits when goal is met
- [ ] Re-planning triggers on step failure (autonomous mode)
- [ ] Child entities execute as separate Arq jobs
- [ ] CORTEX knowledge is queried before THOUGHT steps
- [ ] Reflection nodes appear in CORTEX tree after execution
- [ ] `execution_mode=STANDARD` behavior is unchanged (regression test)

---

## Phase 6: Tool Modernization, Frontend & Testing (Week 4–5, Days 21–25)

> **Goal**: Typed tool protocol, tenant isolation, frontend updates, comprehensive testing.

---

### Step 6.1 — Typed Tool Protocol (2 days)

**File**: `backend/src/ai/tools/base.py`

```python
from pydantic import BaseModel

class ToolParams(BaseModel):
    """Base class for typed tool parameters."""
    pass

class ToolResult(BaseModel):
    """Structured tool result with error handling."""
    success: bool = True
    output: str = ""
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = {}

class Tool(ABC):
    name: str
    description: str

    @abstractmethod
    async def run(self, input_data: str) -> str:
        """Legacy string interface — kept for backward compatibility."""

    async def run_typed(self, params: ToolParams) -> ToolResult:
        """New typed interface. Default falls back to string run()."""
        result_str = await self.run(json.dumps(params.model_dump()))
        return ToolResult(output=result_str)
```

**File**: `backend/src/ai/tool_executor.py`

Update `execute_from_function_calls` to prefer `run_typed` when available.

Migrate tools incrementally — start with `search.py` and `scraper.py` as reference implementations, then migrate remaining 15 tools.

---

### Step 6.2 — Tenant-Scoped Tool Registry (4h)

**File**: `backend/src/ai/tools/base.py`

```python
class ToolRegistry:
    _global_tools: Dict[str, Tool] = {}      # System-wide built-in tools
    _tenant_tools: Dict[UUID, Dict[str, Tool]] = {}  # Per-company custom tools

    @classmethod
    def get_tools_for_company(cls, company_id: UUID) -> Dict[str, Tool]:
        merged = dict(cls._global_tools)
        merged.update(cls._tenant_tools.get(company_id, {}))
        return merged

    @classmethod
    def register_tenant_tool(cls, company_id: UUID, tool: Tool):
        if company_id not in cls._tenant_tools:
            cls._tenant_tools[company_id] = {}
        cls._tenant_tools[company_id][tool.name] = tool
```

---

### Step 6.3 — Global Redis Rate Limiter (4h)

**New file**: `backend/src/ai/rate_limiter.py`

```python
class RedisRateLimiter:
    def __init__(self, redis):
        self.redis = redis

    async def check_and_consume(self, key: str, limit: int, window_seconds: int) -> bool:
        """Sliding window rate limiter. Returns True if allowed."""
        now = time.time()
        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(key, 0, now - window_seconds)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, window_seconds)
        results = await pipe.execute()
        count = results[2]
        return count <= limit
```

---

### Step 6.4 — Frontend Updates (1.5 days)

#### EntityConfigurationTabs.tsx — Autonomous Mode Controls

Add to the Logic Gate tab:
- `execution_mode` dropdown: STANDARD | AUTONOMOUS
- `goal_validation_interval` number input (1–10)
- `confidence_threshold` slider (0.0–1.0)
- `max_replanning_attempts` number input (1–5)
- `self_reflection_enabled` toggle

#### ExecutionDetail.tsx — Enhanced Timeline

- Display `goal_validation_score` badge on steps where validation ran
- Show "Re-planned" indicator with diff of original vs revised plan
- Display child runs as linked async jobs with status badges
- Support PAUSED/RESUMING statuses with appropriate UI states

#### HITLPanel.tsx — Sanitized Display

- Remove `step_id` from approval context display
- Show only `step_name` and `message`

#### ExecutionHistory.tsx — New Filters

- Add filter chips for PAUSED, RESUMING, PARTIAL_COMPLETE statuses
- Show re-planning count as a badge on run cards

---

### Step 6.5 — Comprehensive Testing (4 days)

#### Unit Tests

| Test Suite | File | Coverage Target |
|-----------|------|-----------------|
| `test_governance_service.py` | Credit gates, HITL flow, billing settlement | 100% public methods |
| `test_planner_service.py` | Reconcile (static/dynamic/hybrid), goal validation, adapt_plan | 100% public methods |
| `test_cortex_bridge.py` | Write step, checkpoint, viewport, reflection | 100% public methods |
| `test_text_extractor.py` | PDF, DOCX, XLSX, CSV extraction | All file types |
| `test_rate_limiter.py` | Allow/deny, window expiry, concurrent access | Core logic |

#### Integration Tests

| Test | Scenario |
|------|----------|
| `test_sequential_run` | 3-step sequential run → COMPLETED, correct context, billing |
| `test_dag_run` | 3-step parallel DAG → no context cross-contamination, atomic billing |
| `test_dag_partial_failure` | DAG with 1 failing step → successful steps preserved |
| `test_autonomous_early_exit` | Autonomous mode with goal met at step 2/5 → exits at step 2 |
| `test_autonomous_replan` | Autonomous mode with step failure → re-plans remaining steps |
| `test_child_async` | Parent dispatches child as Arq job → polls completion |
| `test_idempotency` | Retry same run_id + step_id → skips duplicate execution |
| `test_state_machine` | Invalid status transitions → rejected |
| `test_race_conditions` | Concurrent DAG steps writing costs → correct total |

#### Manual Verification Checklist

- [ ] Create entity with AUTONOMOUS mode in UI → verify config saves correctly
- [ ] Execute autonomous entity → verify goal scores in ExecutionDetail
- [ ] Trigger HITL checkpoint → verify sanitized context in approval panel
- [ ] Execute DAG entity → verify billing accuracy in WalletPage
- [ ] Execute 10-step deep research → verify CORTEX tree has reflection nodes

### Phase 6 Gate (Final)

- [ ] `worker.py` < 1,500 lines
- [ ] All P0 bugs from v1 and v2 reviews resolved
- [ ] 6 new backend modules with unit tests
- [ ] DAG execution fully isolated (context, billing, ORM)
- [ ] Autonomous mode functional end-to-end
- [ ] Frontend exposes all new configuration options
- [ ] Zero `print()` in production code
- [ ] All LLM costs tracked
- [ ] Integration test suite passes

---

## Appendix: New File Inventory

| File | Phase | Lines (est.) | Purpose |
|------|-------|-------------|---------|
| `src/ai/constants.py` | 1-2 | 50 | Centralized constants |
| `src/ai/text_extractor.py` | 2 | 150 | Unified doc parsing |
| `src/ai/governance_service.py` | 3 | 300 | HITL, billing, credit gates |
| `src/ai/planner_service.py` | 3, 5 | 350 | Plan reconciliation, goal validation, adaptation |
| `src/ai/cortex_bridge.py` | 3, 5 | 250 | CORTEX tree lifecycle |
| `src/ai/rate_limiter.py` | 6 | 60 | Redis sliding window |
| `migrations/add_idempotency_keys.py` | 3 | 30 | DB migration |
| `tests/test_governance_service.py` | 6 | 200 | Unit tests |
| `tests/test_planner_service.py` | 6 | 200 | Unit tests |
| `tests/test_cortex_bridge.py` | 6 | 150 | Unit tests |
| `tests/test_integration_runs.py` | 6 | 300 | Integration tests |

**Total new code**: ~2,040 lines  
**Total removed from worker.py**: ~2,000 lines  
**Net**: worker.py 3,500 → 1,500 lines + 6 focused modules
