# CORTEX Memory System Architecture — Part 2

## 5. The Seven CORTEX Operations

The agent interacts with the tree exclusively through 7 operations, exposed both as step types in the execution plan and as REST API endpoints.

### 5.1 Operation Reference

| # | Operation | Signature | Token Cost | Side Effects |
|---|-----------|-----------|------------|--------------|
| 1 | **CREATE** | `create_tree(entity_id, user_id, task)` | 0 | Creates tree + 4 scaffold nodes |
| 2 | **RESUME** | `resume_tree(tree_id)` | ~600 | Loads viewport at cursor; returns last checkpoint |
| 3 | **NAVIGATE** | `navigate(node_id)` | ~600 | Updates `resume_cursor_id`; returns viewport |
| 4 | **READ** | `read(node_id, page=0)` | ≤8000 | Updates cursor; returns paged content |
| 5 | **WRITE** | `write(parent_id, type, title, content, summary)` | 0 | Creates child node; enforces invariants |
| 6 | **RECURSE** | `recurse(node_id, task, result_slot)` | 0 | Creates task node + child ExecutionRun |
| 7 | **CHECKPOINT** | `checkpoint(tree_id, summary, facts, next_steps)` | 0 | Writes checkpoint node; triggers compaction check |

Additionally, `AWAIT_CHILDREN` collects completed child task results, and `assemble_output()` performs DFS on the Output subtree.

### 5.2 Operation Details

#### NAVIGATE (cortex_service.py:330–375)

```python
async def navigate(self, node_id: UUID) -> Viewport:
```

**Flow**:
1. Load target node via `_get_node(node_id)` (enforces subtree isolation)
2. Update `tree.resume_cursor_id = node_id`
3. Query direct children ordered by `sibling_order`
4. Load parent node (if not root)
5. Build breadcrumb via recursive CTE query (root → current)
6. Return `Viewport` DTO

**Breadcrumb CTE** (cortex_service.py:913–931):
```sql
WITH RECURSIVE ancestors AS (
    SELECT id, parent_id, title, 0 AS depth
    FROM cortex_nodes WHERE id = :node_id
    UNION ALL
    SELECT cn.id, cn.parent_id, cn.title, a.depth + 1
    FROM cortex_nodes cn
    JOIN ancestors a ON cn.id = a.parent_id
)
SELECT id, title FROM ancestors ORDER BY depth DESC
```

**Why CTE?**: The original implementation used an iterative Python loop issuing O(depth) sequential `SELECT` queries. The CTE reduces this to a single round-trip regardless of tree depth. This was a Phase 4 PERF optimization.

#### READ (cortex_service.py:381–414)

```python
async def read(self, node_id: UUID, page: int = 0) -> NodeContent:
```

**Pagination logic**:
- `page_size_chars = tree.page_size_tokens × CHARS_PER_TOKEN` (default: 8000 × 4 = 32,000 chars)
- `total_pages = ceil(len(content) / page_size_chars)`
- Returns slice `[page × page_size_chars : (page+1) × page_size_chars]`

**Why paging?**: A single scraped web page can be 200K+ characters. Without paging, a READ operation would inject the entire content into the LLM prompt, consuming the full context budget in one call. Paging keeps READ cost bounded to `page_size_tokens` (default 8,000).

#### WRITE (cortex_service.py:416–500)

```python
async def write(self, parent_id, node_type, title, content=None,
                summary=None, status="complete", ...) -> UUID:
```

**Invariant enforcement**:

1. **Invariant 1 (Summary Required)**: `if not parent.summary: raise ValueError(...)` — Every node must have a summary before it can accept children. This ensures viewport navigation quality.

2. **Invariant 2 (Bounded Fanout)**: If `child_count >= tree.max_children`, triggers `_schedule_reclustering()` — an inline operation that creates a grouping node and moves the oldest half of children under it. This keeps viewports navigable.

3. **Invariant 4 (Write-Once)**: Content is set at creation time in `_create_node()`. There is no `update_content()` method. Revisions are expressed as child nodes.

**Token estimation**: `content_tokens = len(content) // 4` — a rough 4-chars-per-token approximation used throughout the system.

#### RECURSE (cortex_service.py:506–572)

```python
async def recurse(self, node_id, task, result_slot, ...) -> (UUID, UUID):
```

**Flow**:
1. Creates a `task` node under the target subtree root
2. Creates a child `ExecutionRun` with `input_data = {cortex_tree_id, subtree_root_id, task}`
3. Returns `(task_node_id, child_run_id)` — caller enqueues to Arq

**Key design**: The child run receives `subtree_root_id`, which the `ExecutionEngine` uses to construct a `CortexService` with `scoped_subtree_root_id`. This means the child agent's `_get_node()` calls will reject any access to nodes outside the designated subtree (Gap #18 enforcement).

#### CHECKPOINT (cortex_service.py:604–679)

```python
async def checkpoint(self, tree_id, progress_summary, key_facts, next_steps) -> UUID:
```

**Creates a `checkpoint` node containing**:
```json
{
    "progress_summary": "Completed web scraping phase",
    "key_facts": ["Found 47 relevant sources", "Q2 revenue was $2.3B"],
    "next_steps": ["Synthesize findings", "Generate executive summary"],
    "nodes_written": ["uuid1", "uuid2", ...],
    "time_elapsed_hours": 0.45
}
```

**Auto-compaction** (`check_and_compact`): Called after each step by `CortexBridge.write_checkpoint()`. Calculates `budget_tokens = model_context_window × context_budget_pct / 100`. If current context exceeds budget, auto-creates a checkpoint.

---

## 6. Viewport Navigation Model

### 6.1 Viewport Structure

```python
@dataclass
class Viewport:
    current_node: NodeSummaryDTO    # {id, title, summary, status, type, depth}
    children: List[NodeSummaryDTO]  # Up to MAX_CHILDREN (12)
    parent: Optional[NodeSummaryDTO]
    breadcrumb: List[Dict]          # [{id, title}, ...] root → current
```

### 6.2 Prompt Rendering (to_prompt_text)

The viewport is rendered as structured text for LLM injection:

```
## Navigation Path
Task: Due Diligence Report → 🔬 Working Memory → Revenue Analysis

## Current Node: Revenue Analysis
Type: finding | Status: complete | Depth: 2
Summary: Analysis of Q2 2026 revenue streams across 3 business units.

## Children
  [1] North America Revenue (finding, complete) — $1.2B total, 12% YoY growth
  [2] EMEA Revenue (finding, complete) — €890M total, 8% YoY growth
  [3] APAC Revenue (finding, active) — Analysis in progress

## Available CORTEX Operations
You can perform the following operations on the cognitive tree:
  NAVIGATE(node_id) — Move viewport to a node
  READ(node_id, page=0) — Read full content (paged)
  WRITE(parent_id, node_type, title, content, summary) — Create child node
  RECURSE(node_id, task, result_slot) — Spawn child execution
  AWAIT_CHILDREN() — Collect child execution results
  CHECKPOINT(progress_summary, key_facts, next_steps) — Save progress
```

### 6.3 Viewport Caching (CortexBridge)

**Phase 4 PERF optimization**: Viewports are cached in Redis with a 30-second TTL:

```python
async def refresh_viewport(self, cortex, tree, context_state):
    cursor_id = tree.resume_cursor_id or tree.root_node_id
    cache_key = f"cortex:viewport:{tree.id}:{cursor_id}"

    # Try cache first
    cached = await self.redis.get(cache_key)
    if cached:
        context_state["__cortex_viewport__"] = cached
        return

    # Cache miss: compute and store
    viewport = await cortex.navigate(cursor_id)
    viewport_text = viewport.to_prompt_text()
    context_state["__cortex_viewport__"] = viewport_text
    await self.redis.set(cache_key, viewport_text, ex=30)
```

**Why 30s TTL?**: Steps typically execute in 5-15 seconds. A 30s TTL means the viewport is recomputed at most once per step while avoiding stale data from cursor movements.

---

## 7. Tree Lifecycle Management

### 7.1 Lifecycle States

```
┌──────────┐    create_tree()     ┌────────┐
│          │ ──────────────────→  │ ACTIVE │
│  (none)  │                      │        │
│          │                      └───┬────┘
└──────────┘                          │
                                      │ suspend_tree()
                                      ▼
                                  ┌───────────┐
                                  │ SUSPENDED  │
                                  │            │
                                  └───┬────────┘
                                      │ resume_tree()
                                      │ (or cron wake-up)
                                      ▼
                                  ┌────────┐
                                  │ ACTIVE │ ←── stays ACTIVE after
                                  │        │     run completion (for
                                  └────────┘     future resumption)
```

**Key insight**: Trees stay `ACTIVE` after run completion (`worker.py:1082`), not `COMPLETE`. This enables future resumption — a user can ask the same agent to "continue" or "update" a previous task, and the tree picks up from its last cursor position.

### 7.2 Scheduled Wake-ups (Gap #5)

For multi-day tasks, trees support scheduled resumption:

```python
# cortex_models.py
resume_schedule: str       # e.g., "daily", "weekly"
next_resume_at: datetime   # Next wake-up timestamp
```

An Arq cron job (`cortex_resume_scheduled`) runs every 5 minutes, checking for suspended trees whose `next_resume_at` has arrived. It creates a new `ExecutionRun` with `input_data = {cortex_tree_id}` and enqueues it:

```python
# worker.py:1603-1659
async def cortex_resume_scheduled(ctx):
    trees = await db.execute(
        select(CortexTree).where(
            CortexTree.status == CortexTreeStatus.SUSPENDED,
            CortexTree.next_resume_at <= datetime.utcnow(),
        )
    )
    for tree in trees:
        resume_run = ExecutionRun(
            entity_id=tree.entity_id,
            input_data={"cortex_tree_id": str(tree.id)},
            status="PENDING",
        )
        # ... enqueue to Arq
```

### 7.3 Resume Flow (worker.py:686–734)

When `execute_run()` is called with an existing `cortex_tree_id`:

```python
if cortex_tree_id and subtree_root_id:
    # Child recursive run — scoped to subtree
    cortex = CortexService(db, company_id, scoped_subtree_root_id=UUID(subtree_root_id))
    tree, viewport, last_checkpoint = await cortex.resume_tree(UUID(cortex_tree_id))

elif cortex_tree_id:
    # Resume existing tree
    tree, viewport, last_checkpoint = await cortex.resume_tree(UUID(cortex_tree_id))

else:
    # New execution — create fresh tree
    tree = await cortex.create_tree(entity_id, user_id, task_desc)
    viewport = await cortex.navigate(tree.root_node_id)
```

The `resume_tree()` method:
1. Validates tree status (must be ACTIVE or SUSPENDED)
2. Sets status to ACTIVE
3. Navigates to `resume_cursor_id` (the last position)
4. Loads the last checkpoint data for context restoration

---

## 8. Recursive Execution (RLM)

### 8.1 How RECURSE Works End-to-End

```
Parent Agent (Tree T, Node N)
    │
    ├── 1. cortex.recurse(node_id=N, task="Analyze APAC revenue", result_slot="apac")
    │       → Creates task node T_task under N
    │       → Creates child ExecutionRun with input_data:
    │         {cortex_tree_id: T, subtree_root_id: N, task: "Analyze APAC..."}
    │
    ├── 2. Enqueues child run to Arq worker queue
    │
    ├── 3. Parent continues executing other steps
    │
    ├── 4. At AWAIT_CHILDREN step:
    │       → Queries task nodes under N with status=complete
    │       → Returns {result_slot: NodeSummaryDTO} dict
    │
    └── 5. Parent uses results in subsequent steps

Child Agent (Same Tree T, scoped to subtree N)
    │
    ├── 1. CortexService initialized with scoped_subtree_root_id=N
    │       → All _get_node() calls enforce N is ancestor
    │
    ├── 2. Executes its own plan within the subtree
    │       → WRITE creates nodes under N
    │       → NAVIGATE can only reach descendants of N
    │
    └── 3. On completion: task node status → complete
```

### 8.2 Subtree Isolation Enforcement (Gap #18)

```python
# cortex_service.py:880-898
async def _get_node(self, node_id: UUID) -> CortexNode:
    node = ...  # load from DB
    if self.scoped_subtree_root_id and node_id != self.scoped_subtree_root_id:
        is_descendant = await self._is_descendant_of(node_id, self.scoped_subtree_root_id)
        if not is_descendant:
            raise ValueError(
                f"Node {node_id} is outside scoped subtree {self.scoped_subtree_root_id}. "
                f"Child runs cannot access nodes outside their designated subtree."
            )
    return node
```

The ancestry check uses a **recursive CTE** (cortex_service.py:970-991):

```sql
WITH RECURSIVE ancestors AS (
    SELECT id, parent_id FROM cortex_nodes WHERE id = :node_id
    UNION ALL
    SELECT cn.id, cn.parent_id
    FROM cortex_nodes cn
    JOIN ancestors a ON cn.id = a.parent_id
)
SELECT 1 FROM ancestors WHERE id = :ancestor_id LIMIT 1
```

**Why CTE instead of materialized path?**: A materialized path (`/root/knowledge/node1/node2`) would require path updates on every re-clustering operation (when nodes are re-parented). The CTE approach is read-heavy but write-light, which matches the CORTEX access pattern (many reads per write).

### 8.3 Child Context Propagation (step_executor.py:214-270)

When spawning child entity invocations, several context keys are carefully managed:

1. **CORTEX tree ID propagated**: `child_input["cortex_tree_id"] = context["__cortex_tree_id__"]` — all entities in a process share one tree
2. **Parent step IDs stripped**: `step_N` keys removed to prevent child step-skip collision (Fix F)
3. **Parent memory stripped**: `__memory__`, `__episodic_memory__`, `__semantic_context__` removed to prevent child entities from being confused by parent's history (Fix H)
4. **Input rendered**: The `prompt_template` is resolved with parent context, becoming the child's `input` key (Fix G)

---

## 9. Compaction & Checkpointing

### 9.1 Checkpoint Flow

```
Step N completes
    │
    ├── CortexBridge.write_checkpoint(cortex, tree, context_state, step_name)
    │       │
    │       ├── Calculate ctx_size = _context_size_bytes // 4  (O(1) — incremental)
    │       │
    │       └── cortex.check_and_compact(tree_id, ctx_size)
    │               │
    │               ├── budget_tokens = model_context_window × context_budget_pct / 100
    │               │                 = 200,000 × 0.40 = 80,000 tokens
    │               │
    │               ├── IF ctx_size >= budget_tokens:
    │               │       └── checkpoint(tree_id, auto_summary, [], ["Continue..."])
    │               │               → Writes checkpoint node
    │               │               → Captures nodes_written, time_elapsed
    │               │
    │               └── ELSE: return None (within budget)
    │
    └── Periodic forced checkpoint: every N steps (configurable)
        governance.checkpoint_every_n_steps (default: 3)
```

### 9.2 Context Size Tracking (PERF-3)

Instead of scanning the entire `context_state` dict on every checkpoint, `CortexBridge` uses **incremental tracking**:

```python
# Called by _store_step_output() on every context mutation
def update_context_size(self, key, old_value="", new_value=""):
    self._context_size_bytes -= len(str(old_value))
    self._context_size_bytes += len(str(new_value))
    self._context_size_bytes = max(0, self._context_size_bytes)
```

This reduces checkpoint overhead from O(n) (scanning all context values) to O(1) per mutation.

### 9.3 Re-clustering (Gap #9)

When a node exceeds `MAX_CHILDREN` (default 12):

```python
# cortex_service.py:1006-1058
async def _schedule_reclustering(self, parent_id, tree):
    children = await db.execute(
        select(CortexNode).where(parent_id=parent_id).order_by(sibling_order)
    )
    half = len(children) // 2
    children_to_move = children[:half]

    # Create grouping node
    group_node = await _create_node(
        title=f"📂 Group ({half} items)",
        node_type=children_to_move[0].node_type,
        ...
    )

    # Re-parent oldest children under group
    for i, child in enumerate(children_to_move):
        child.parent_id = group_node.id
        child.sibling_order = i

    # Reorder remaining direct children
    for i, child in enumerate(children[half:]):
        child.sibling_order = i + 1
```

**Effect**: A node with 14 children becomes a node with 8 children (7 remaining + 1 group containing the 7 oldest). This keeps viewport size bounded while preserving all data.

---

## 10. Knowledge Ingestion Pipeline

### 10.1 Automatic Tool Result Ingestion (cortex_bridge.py:125-210)

When `scraper_tool` or `headless_browser` tools execute during a CORTEX run, their results are automatically ingested into the Knowledge Base subtree:

```
Tool Result (JSON)
    │
    ├── Parse: extract URL + content from results array
    │
    ├── For each result (capped at 10 per call):
    │   │
    │   ├── Generate LLM summary (~200 tokens, temp=0.3)
    │   │   └── "Concise summary that helps an AI research agent
    │   │        decide if this source contains relevant data"
    │   │
    │   └── cortex.write(
    │         parent_id=knowledge_root.id,
    │         node_type="knowledge",
    │         title="📄 {url}",
    │         content=content[:50000],
    │         summary=llm_summary,
    │         source_ref={"url": url, "tool": tool_id},
    │       )
    │
    └── Track LLM summary cost in usage_logs
```

### 10.2 Context Source Auto-Ingestion (worker.py:849-870)

At execution start, all entity `context_sources` (documents, artifacts, knowledge bases) are automatically ingested into the Knowledge Base:

```python
for src_text in loaded_sources:
    title = src_text.split("\n")[0][:100]
    await cortex.write(
        parent_id=knowledge_root.id,
        node_type="knowledge",
        title=f"📎 {title}",
        content=src_text[:50000],
        summary=src_text[:300],
        source_ref={"type": "context_source"},
    )
```

### 10.3 Document Ingestion (cortex_ingestion.py)

The `CortexIngestionService` transforms uploaded documents into hierarchical knowledge nodes:

1. **Document chunking**: Splits text into sections based on heading detection
2. **Section summarization**: Each chunk gets an LLM-generated summary
3. **Tree insertion**: Chunks are written as `knowledge` nodes under the Knowledge Base root
4. **Embedding generation**: Document chunks are also embedded for semantic search (Tier 3)

### 10.4 Self-Reflection Knowledge (cortex_bridge.py:495-556)

During autonomous execution (Phase 5), the agent writes **reflection nodes** after each step:

```python
async def write_reflection(self, tree_id, cursor_id, step_name, learning):
    await cortex.write(
        parent_id=cursor_id,
        node_type="finding",
        title=f"🔍 Reflection: {step_name}",
        content=learning,
        summary=learning[:200],
        metadata_extra={"reflection": True},
    )
```

Before each THOUGHT step, `get_relevant_knowledge()` retrieves the 10 most recent knowledge nodes, giving the agent awareness of what it has already learned.
