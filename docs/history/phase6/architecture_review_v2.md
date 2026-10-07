# Phase 6: Architecture Review v2 — Concurrency, Security & Data Integrity Audit

> **Perspective**: This review approaches the codebase from **concurrency safety, race conditions, security, data integrity, error recovery, and performance** — angles not covered in v1.  
> **Date**: 2026-05-07  
> **Scope**: worker.py, llm_router.py, cortex_service.py, memory_service.py, tool_executor.py, service.py, models.py

---

## 1. Verification of v1 Claims

### ✅ Confirmed Findings

| v1 ID | Claim | Verification |
|-------|-------|-------------|
| R1 | `call_llm_unified` is dead code | **Confirmed**. Only defined at L330; grep shows zero callers outside its own definition. Safe to delete. |
| R2 | `_get_api_key` deprecated but present | **Confirmed** at L2639. No callers found. |
| R5 | `_INTERNAL_KEYS` duplicated | **Confirmed**. L1974 has 7 members, L2334 has 11 members (`input`, `cortex_tree_id`, `subtree_root_id`, `__cortex_knowledge__` added). These filter different things — a latent context-leakage bug. |
| C1 | DAG path skips billing | **Confirmed**. L1001-1007 writes to CORTEX after `_execute_steps_dag` returns, but there's no `consume_incremental` or `get_effective_balance` call in the DAG branch at all. |
| C5 | `get_event_loop()` deprecated | **Confirmed** at L647,650. Should use `get_running_loop()`. |
| A2 | Synchronous child execution | **Confirmed** at L1945: `await self.execute_run(child_run.id)` — recursive in-process, holding parent's DB session open. |
| G4 | `RecursiveReasoningEngine.company_id` missing | **Confirmed**. L3419 calls `self.company_id` but `ExecutionEngine.__init__` never sets it (only `self.db` and `self.redis`). Will crash at runtime. |

### ⚠️ Partially Correct / Nuanced

| v1 ID | Claim | Nuance |
|-------|-------|--------|
| R3 | `_clone_fields` duplicated in `save_as_template` and `clone_template` | **Partially correct**. Both methods define `_clone_fields` and `_remap_entity_refs`, but `clone_template` (L972-1096) uses `copy.deepcopy` + `flag_modified`, while `save_as_template` (L822-853) does `{**planning}` shallow reassignment. The clone_template version is strictly better — the save_as_template version has a **latent mutation bug** on nested dicts. |
| A5 | 40+ `print()` statements | **Confirmed but undercounted**. Grep reveals **55+** print statements in worker.py alone. |
| R4 | Duplicate text extraction | **Confirmed** but `_extract_text_from_file` (L1500) handles XLSX/PPTX/CSV that `process_document` (L3237) does not. They're not identical — they've diverged. |

### ❌ Corrections to v1

| v1 ID | Claim | Correction |
|-------|-------|-----------|
| C4 | "Fix F strips `step_N` keys but not named step keys" | **Incorrect scope**. Fix F at L1891-1900 strips `step_\d+` patterns using regex. Named step keys (e.g. "Research Phase") ARE still passed to the child, which is **intentional** — they carry data the child needs via `{{Research Phase}}` template variables. This is not a bug; it's by design per Fix G (L1874-1889). |
| R6 | `import copy` done redundantly | **Minor correction**. The local `import copy` at L1582 is inside `_get_reconciled_plan` which is correct Python style for optional/rare imports. The `import copy as _copy` at L1032 in service.py is also local-scope. Only the L37 module-level and L1779 `import copy as _copy` in the same worker.py file are technically redundant. |

---

## 2. NEW Findings: Concurrency & Race Conditions

### 🔴 RACE-1: DAG Parallel Steps Share Mutable `context_state`

**Location**: [worker.py:453-461](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/worker.py#L453-L461)

```python
async def _isolated_step(step_dict: dict) -> dict:
    async with AsyncSessionLocal() as isolated_db:
        isolated_engine = ExecutionEngine(isolated_db, self.redis)
        step_obj = PlanStep(**step_dict)
        return await isolated_engine._execute_step_wrapper(
            run, entity, step_obj, context_state  # ← SHARED dict
        )
tasks = [_isolated_step(s) for s in ready]
batch_results = await asyncio.gather(*tasks, return_exceptions=True)
```

**Problem**: `context_state` is a shared mutable dict passed to all parallel coroutines. Inside `_execute_step_wrapper` (L534), each step writes `context_state[step_obj.name] = result["output"]`. With `asyncio.gather`, all coroutines run on the same event loop — any `await` point lets another coroutine interleave and mutate the same dict. This causes:
- Non-deterministic context for each step (seeing partial results from siblings)
- `tool_call_counts` dict (L2364-2365) shared across parallel steps — counter corruption

**Fix**: Pass `copy.deepcopy(context_state)` to each isolated step, then merge results after gather.

---

### 🔴 RACE-2: `run` ORM Object Shared Across Isolated Sessions

**Location**: [worker.py:458](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/worker.py#L458)

```python
return await isolated_engine._execute_step_wrapper(run, entity, step_obj, context_state)
```

The `run` ORM object is loaded from `self.db` session, but passed to `isolated_engine` which uses `isolated_db`. When the isolated engine calls `run.total_cost_usd += ...` (L2696) or `self.db.add(log)` where log has `run_id=run.id`, it writes via `isolated_db` while `run` belongs to `self.db`. This can cause:
- **`DetachedInstanceError`** if `run` is accessed after `self.db` transaction boundaries
- **Lost updates**: Two parallel steps both read `run.total_cost_usd = 0.50`, add their cost, write `0.55` — losing one step's cost
- The `run` object accumulations (`total_cost_usd`, `total_tokens`) are **not atomic** across parallel steps

**Fix**: Pass `run.id` to isolated steps and reload run inside each session, or use DB-level atomic increments (`UPDATE SET total_cost_usd = total_cost_usd + :delta`).

---

### 🟡 RACE-3: HITL Pub/Sub Leak on Exception

**Location**: [worker.py:670](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/worker.py#L670)

```python
await pubsub.unsubscribe(approval_channel)
```

If any exception is raised between `subscribe` (L645) and `unsubscribe` (L670) — e.g., a `CancelledError` from Arq timeout — the pub/sub connection leaks. The `unsubscribe` is not in a `finally` block.

**Fix**: Wrap the pub/sub lifecycle in `try/finally` to guarantee cleanup.

---

### 🟡 RACE-4: `MemoryRouter._cortex_viewport` Instance Mutation

**Location**: [memory_service.py:60,103](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/memory_service.py#L60)

```python
self._cortex_viewport = viewport  # Set during retrieve()
```

`MemoryRouter` is instantiated once per `execute_run()` (L830), but if two runs share a `MemoryRouter` instance (which doesn't happen today but could in a future refactor), the cached viewport would cross-contaminate. More importantly, `format_for_prompt()` (L262) checks `self._cortex_viewport` — a stale reference that's never cleared after use.

---

## 3. NEW Findings: Security Vulnerabilities

### 🔴 SEC-1: Context State Persisted with Secrets

**Location**: [worker.py:1096,1199](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/worker.py#L1096)

```python
run.context_state = context_state  # Persisted to DB on both success AND failure
```

`context_state` contains `company_id`, `user_id`, and — critically — `extra_context` from tool execution (L2359-2363) which includes `company_id` as a string. While not a direct API key leak, the `__context_sources__` key (L957) can contain full document contents (up to 50KB per source) that are persisted to the `execution_runs.context_state` JSON column. Any user with run-read access sees all injected documents.

**Fix**: Strip `__`-prefixed keys and large content before persisting `context_state`.

---

### 🟡 SEC-2: `_safe_eval_hitl_expression` String Parsing

**Location**: [worker.py:692-726](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/worker.py#L692)

The method is named "safe" but `has_key` (L720-722) accepts arbitrary key names from entity config — config that could be authored by any tenant admin. While it only does dict lookup (`key in context_state`), the `step_count` and `cost` parsers (L702-718) use `split()` parsing that could be confused by crafted expressions like `"step_count > 0 or __import__('os')"` — the `float(val)` on L704 would fail, but the broad `except Exception: pass` on L724 silently swallows the failure, returning `False`. This is safe today but fragile.

---

### 🟡 SEC-3: `context_snapshot` Exposes Internal State

**Location**: [worker.py:617-622](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/worker.py#L617)

`HumanApproval.context_snapshot` stores the current cost. This is exposed to any user who queries the approvals API. While cost itself isn't sensitive, the step_name and step_id reveal internal execution topology to end users.

---

## 4. NEW Findings: Data Integrity Issues

### 🔴 DATA-1: `context_state` Grows Unbounded

**Location**: [worker.py:534-536](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/worker.py#L534)

```python
context_state[step_obj.name] = step_result["output"]
if step_obj.step_id and step_obj.step_id != step_obj.name:
    context_state[step_obj.step_id] = step_result["output"]
```

Every step's full output is stored in `context_state` — **twice** (once by name, once by step_id). For a 10-step deep research pipeline where each step produces 20KB of output, `context_state` reaches ~400KB. This is then:
1. Passed to `json.dumps()` for every subsequent step's prompt (L2324-2347)
2. Written to `ExecutionRun.context_state` (JSON column) on every commit
3. Passed to `_maybe_summarize_context` which calls another LLM if >20KB (adding more cost)

**Impact**: Quadratic growth in prompt tokens and DB I/O per step.

---

### 🔴 DATA-2: `_execute_step_wrapper` Missing `context_state` Error Key

**Location**: [worker.py:475-538](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/worker.py#L475)

When `_execute_step` raises an exception, the wrapper catches it (L507-516) and returns `{"error": str(e), "step": step_obj.name}`. But **it never writes to `context_state`** — the step_id is not added to `context_state`, so on retry/resume, the step will be re-executed even though it failed with a non-retryable error.

---

### 🟡 DATA-3: Episodic Memory `metadata` Column Name Collision

**Location**: [memory_service.py:157](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/memory_service.py#L157)

```python
episode = EpisodicMemory(
    ...
    metadata={...},  # ← "metadata" attribute name
)
```

But the ORM model (models.py:38) uses `metadata_info` to avoid SQLAlchemy's reserved `metadata`:
```python
metadata_info = Column(JSON, nullable=True)  # avoiding 'metadata' reserved word
```

This means the `metadata={...}` in `write_episodic()` sets a **Python attribute that doesn't map to any DB column**. The tools_used and step_count data is silently discarded.

**Fix**: Change L157 from `metadata=` to `metadata_info=`.

---

### 🟡 DATA-4: Embedding Model Mismatch

**Location**: [worker.py:3255](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/worker.py#L3255) vs [memory_service.py:213](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/memory_service.py#L213)

`process_document()` embeds chunks using `gemini-embedding-004` (L3255), but `search_semantic()` embeds queries using `text-embedding-004` (L213). If these models produce different vector spaces, cosine similarity results will be meaningless.

**Fix**: Use a single constant for the embedding model name, imported by both modules.

---

### 🟡 DATA-5: `total_cost_usd` Type Mismatch

**Location**: [worker.py:2676](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/worker.py#L2676) vs [worker.py:1948](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/worker.py#L1948)

`_log_usage` (L2676) sets `run.total_cost_usd = Decimal("0")` when null, but child rollup (L1948) does `run.total_cost_usd += child_run.total_cost_usd or 0` — adding `int(0)` to a `Decimal`, which works but creates `Decimal("0") + 0 = Decimal("0")` rather than proper Decimal arithmetic. More critically, if `total_cost_usd` is still `None` at L1948 (before any `_log_usage` call in the parent), this becomes `None + 0` → **`TypeError`**.

---

## 5. NEW Findings: Performance Anti-Patterns

### 🔴 PERF-1: N+1 Breadcrumb Queries

**Location**: [cortex_service.py:913-928](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/cortex_service.py#L913)

`_build_breadcrumb()` issues one `SELECT` per tree depth level. A tree 8 levels deep = 8 sequential queries. Called on every `navigate()`, which is called after every step (L1074). For a 10-step run on a depth-8 tree: **80 queries** just for breadcrumbs.

**Fix**: Single recursive CTE query:
```sql
WITH RECURSIVE ancestors AS (
    SELECT id, parent_id, title FROM cortex_nodes WHERE id = :node_id
    UNION ALL
    SELECT cn.id, cn.parent_id, cn.title
    FROM cortex_nodes cn JOIN ancestors a ON cn.id = a.parent_id
) SELECT * FROM ancestors;
```

---

### 🟡 PERF-2: `_is_descendant_of` Also N+1

**Location**: [cortex_service.py:967-982](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/cortex_service.py#L967)

Same pattern — walks up the tree with one query per level. Called on every `_get_node()` when `scoped_subtree_root_id` is set (L890). For child recursive runs, every node access triggers this O(depth) check.

---

### 🟡 PERF-3: Full Context JSON Serialization Per Step

**Location**: [worker.py:1082](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/worker.py#L1082)

```python
ctx_size = sum(len(str(v)) for v in context_state.values()) // 4
```

This iterates and `str()`-converts every value in `context_state` on every checkpoint interval — just to estimate size. For large contexts, this is O(n) string allocation that's immediately discarded.

---

### 🟡 PERF-4: `LLMRouter._resolve_adapter` Hits DB Every Call

**Location**: [llm_router.py:821-860](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/llm_router.py#L821)

Every `call_llm()` and `call_llm_react()` calls `_resolve_adapter()`, which calls `ConfigService.resolve_model_for_task()` — a DB query. In a REACT loop with 10 turns, this is 10 identical DB queries for the same model config. But the REACT loop already resolves the adapter once — this is fine for `call_llm_react` since the adapter is resolved at the top level. However, `_execute_chain_of_thought` and `_execute_reflection` call `call_llm` and `call_llm_react` separately (2 adapter resolutions per reasoning mode).

**Fix**: Cache the adapter per `(company_id, task_type)` for the duration of a run.

---

### 🟡 PERF-5: Bridge Paragraph LLM Call Untracked

**Location**: [cortex_service.py:1076-1082](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/cortex_service.py#L1076)

The `_generate_bridge_paragraphs()` call to `llm.call_llm()` has no `_log_usage()` call — the token cost is invisible in billing. Confirmed from v1 review.

---

## 6. NEW Findings: Error Recovery Gaps

### 🔴 ERR-1: `BaseException` Handler Can Corrupt State

**Location**: [worker.py:1188-1205](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/worker.py#L1188)

```python
except BaseException as e:
    run.status = RunStatus.FAILED
    ...
    run.context_state = context_state
    await self.db.commit()
```

Catching `BaseException` includes `KeyboardInterrupt`, `SystemExit`, and `GeneratorExit`. If the DB session is in a broken state (e.g., mid-transaction rollback), the `commit()` at L1201 will raise again, entering the inner `except Exception: pass` (L1203). The `raise` at L1205 then re-raises the **original** exception, but the run status may not have been persisted — leaving it permanently in `RUNNING` status.

**Fix**: Use `await self.db.rollback()` before attempting the status write, or use a fresh session for the status update.

---

### 🟡 ERR-2: DAG Step Exception Propagation

**Location**: [worker.py:466-468](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/worker.py#L466)

```python
if isinstance(result, Exception):
    print(f"Step {step_id} failed: {result}")
    results_map[step_id] = {"error": str(result), "step": ready[i]["name"]}
    raise result  # ← immediately raises, abandoning other results
```

When one parallel step fails, `raise result` immediately aborts the batch. But `asyncio.gather(*tasks, return_exceptions=True)` already collected all results — including successful ones. The successful step results are discarded because `results_map` only has entries up to the failed step's index.

**Fix**: Collect all results first, then decide whether to raise. Failed step results should still be written to context for debugging.

---

### 🟡 ERR-3: Tool Rate Limit Counter Never Resets

**Location**: [worker.py:2364-2365](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/worker.py#L2364)

```python
if 'tool_call_counts' not in context:
    context['tool_call_counts'] = {}
```

`tool_call_counts` lives in `context_state`, which persists across resumed runs (L1198-1199). On resume, the counter retains the previous run's values — so a resumed run starts with a partially-consumed rate limit. If `max_tool_calls = 5` and the first attempt used 3, the retry only gets 2.

---

## 7. NEW Findings: Architectural Smell

### 🟡 ARCH-1: Tool I/O Bottleneck

**Location**: [tools/base.py:28](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/tools/base.py#L28)

```python
async def run(self, input_data: str) -> str:
```

Every tool receives a single string and returns a single string. The `execute_from_function_calls` method (tool_executor.py:139-146) has to serialize multi-field args to JSON, then the tool has to parse them back. This round-trip is error-prone (L139-146 has 3 branches for different arg formats) and prevents typed validation.

---

### 🟡 ARCH-2: ToolRegistry is Global Singleton Without Tenant Isolation

**Location**: [tools/base.py:88](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/tools/base.py#L88)

```python
class ToolRegistry:
    _tools: Dict[str, Tool] = {}  # Class-level dict — global across all tenants
```

All tenants share the same tool registry. If Tenant A registers a custom tool with the same name as Tenant B's, they collide. The `ToolRegistryEntry` model (models.py:225) supports `company_id` scoping, but the runtime `ToolRegistry` doesn't use it.

---

### 🟡 ARCH-3: No Backpressure on CORTEX Node Writes

Every step result is written to CORTEX via `_write_step_to_cortex` (L1068), and tool results from scraper/browser are also ingested (L2391-2397). A single REACT step with 5 tool calls can create 6+ CORTEX nodes. There's no batching, throttling, or deduplication — each write is a separate `INSERT` + `flush()`.

---

## 8. Consolidated Priority Matrix

### 🔴 P0 — Fix Immediately (Data Loss / Security Risk)

| # | Finding | Category | Effort |
|---|---------|----------|--------|
| 1 | **RACE-1**: DAG parallel steps share mutable `context_state` | Concurrency | 2h |
| 2 | **RACE-2**: `run` ORM object shared across sessions | Concurrency | 4h |
| 3 | **DATA-3**: `metadata` → `metadata_info` column mismatch | Data Loss | 5m |
| 4 | **DATA-4**: Embedding model name mismatch | Data Integrity | 15m |
| 5 | **DATA-5**: `total_cost_usd` None + int TypeError | Runtime Crash | 30m |
| 6 | **ERR-1**: BaseException handler state corruption | Error Recovery | 1h |

### 🟡 P1 — Fix This Sprint

| # | Finding | Category | Effort |
|---|---------|----------|--------|
| 7 | **PERF-1**: Breadcrumb N+1 → recursive CTE | Performance | 2h |
| 8 | **PERF-2**: `_is_descendant_of` N+1 → recursive CTE | Performance | 1h |
| 9 | **DATA-1**: Context state unbounded growth | Performance | 4h |
| 10 | **RACE-3**: Pub/sub connection leak in HITL | Concurrency | 30m |
| 11 | **ERR-2**: DAG discards successful parallel results on failure | Error Recovery | 1h |
| 12 | **ERR-3**: Tool rate limit counter persists across retries | Data Integrity | 30m |
| 13 | **SEC-1**: Strip sensitive keys before persisting context | Security | 1h |
| 14 | **PERF-5**: Bridge paragraph LLM cost untracked | Billing | 30m |
| 15 | v1 `save_as_template._remap_entity_refs` shallow copy bug | Data Integrity | 1h |

### 🟢 P2 — Next Sprint

| # | Finding | Category |
|---|---------|----------|
| 16 | **PERF-4**: Cache LLM adapter resolution per run |
| 17 | **ARCH-1**: Typed tool I/O protocol |
| 18 | **ARCH-2**: Tenant-scoped tool registry at runtime |
| 19 | **ARCH-3**: Batch CORTEX node writes |

---

## 9. Quick Wins (< 30 Minutes Each)

```diff
# 1. DATA-3: Fix episodic metadata column name
# memory_service.py:157
-               metadata={
+               metadata_info={

# 2. DATA-4: Unify embedding model constant
# Create constants.py:
+ EMBEDDING_MODEL = "gemini-embedding-004"
# Update memory_service.py:213 and worker.py:3255

# 3. DATA-5: Null-safe cost rollup
# worker.py:1948
-        run.total_cost_usd += child_run.total_cost_usd or 0
+        run.total_cost_usd = (run.total_cost_usd or Decimal("0")) + Decimal(str(child_run.total_cost_usd or 0))

# 4. RACE-3: Pub/sub cleanup
# worker.py:643-670 — wrap in try/finally
+           try:
                pubsub = self.redis.client.pubsub()
                await pubsub.subscribe(approval_channel)
                # ... existing loop ...
+           finally:
+               await pubsub.unsubscribe(approval_channel)
-           await pubsub.unsubscribe(approval_channel)

# 5. ERR-3: Reset tool counts on resume
# worker.py:2364-2365
-        if 'tool_call_counts' not in context:
-            context['tool_call_counts'] = {}
+        context['tool_call_counts'] = {}  # Always reset per step execution
```
