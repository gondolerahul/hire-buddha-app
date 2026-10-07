# CORTEX Memory System Architecture — Part 3

## 11. Memory Router Integration

### 11.1 MemoryRouter Class (memory_service.py)

The `MemoryRouter` is the unified entry point for all memory access. It orchestrates the three tiers and handles formatting for LLM prompt injection.

```python
class MemoryRouter:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def retrieve(self, entity_id, user_id=None, query=None,
                       tree_id=None, long_running=False, top_k=5):
        """
        Multi-tier memory retrieval.

        Returns: MemoryContext with episodic, semantic, and cortex data
        """
```

**Retrieval flow**:

| Tier | Condition | Data Source | Context Key |
|------|-----------|-------------|-------------|
| Episodic | Always | `episodic_memories` table | `__episodic_memory__` |
| Semantic | `query` provided | `document_chunks` + pgvector | `__semantic_context__` |
| CORTEX | `long_running=True` + `tree_id` | `cortex_trees/nodes` | `__cortex_viewport__` |

### 11.2 Episodic Write (memory_service.py)

At run completion, `write_episodic(run)` persists a summary:

```python
async def write_episodic(self, run: ExecutionRun):
    memory = EpisodicMemory(
        entity_id=run.entity_id,
        company_id=run.company_id,
        user_id=run.user_id,
        run_id=run.id,
        input_summary=str(run.input_data.get("input", ""))[:1000],
        output_summary=str(run.result_data.get("output", ""))[:1000],
        status=run.status.value,
        total_cost_usd=str(run.total_cost_usd),
        total_tokens=run.total_tokens,
        execution_time_ms=run.execution_time_ms,
        tree_id=tree_id,  # Links to CORTEX tree
    )
    self.db.add(memory)
```

### 11.3 Semantic Search (memory_service.py)

```python
async def _semantic_search(self, entity_id, query, top_k=5):
    # 1. Resolve company_id from entity_id
    # 2. Embed query via Vertex AI (gemini-embedding-004, task=RETRIEVAL_QUERY)
    # 3. Cosine similarity search:
    result = await self.db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document.has(company_id=company_id))
        .order_by(DocumentChunk.embedding.cosine_distance(query_embedding))
        .limit(top_k)
    )
```

### 11.4 Prompt Formatting

```python
def format_for_prompt(self, ctx: MemoryContext) -> str:
    parts = []
    if ctx.episodic:
        parts.append("## Recent Execution History")
        for mem in ctx.episodic:
            parts.append(f"- {mem.created_at}: {mem.input_summary} → {mem.output_summary}")
    if ctx.semantic:
        parts.append("## Relevant Knowledge")
        for chunk in ctx.semantic:
            parts.append(f"- {chunk.content[:500]}")
    return "\n".join(parts)
```

---

## 12. Worker Integration & Execution Flow

### 12.1 End-to-End Execution (worker.py:628-1090)

```
execute_run(run_id)
│
├── 1. Load ExecutionRun + HierarchicalEntity
├── 2. Initialize services (GovernanceService, PlannerService, CortexBridge)
├── 3. Credit balance gate check
│
├── 4. CORTEX Tree Setup
│   ├── New run → create_tree() + navigate(root)
│   ├── Resume → resume_tree(tree_id)
│   └── Child recursive → resume_tree() with scoped_subtree_root_id
│
├── 5. Memory Context Retrieval
│   ├── MemoryRouter.retrieve(entity_id, tree_id, long_running=True)
│   ├── Inject __memory__, __cortex_viewport__, __cortex_tree_id__
│   └── Inject __cortex_knowledge__ (knowledge subtree summary)
│
├── 6. Context Source Loading
│   ├── Load DOCUMENT, KNOWLEDGE_BASE, CORTEX_TREE sources
│   └── Auto-ingest into CORTEX knowledge root
│
├── 7. Plan Generation/Reconciliation
│   └── PlannerService.reconcile(run, entity, context_state)
│
├── 8. Get Working Memory Root
│   └── cortex.get_working_root(tree.id) → sibling_order=1 under root
│
├── 9. Step Execution Loop
│   ├── For each step:
│   │   ├── Check if CORTEX-native (NAVIGATE/READ/WRITE/RECURSE/AWAIT)
│   │   │   └── Yes → CortexBridge.execute_cortex_step()
│   │   │   └── No → _execute_step_wrapper() (THOUGHT/ACTION/TOOL_CALL)
│   │   │
│   │   ├── Write step result to CORTEX working memory
│   │   │   └── CortexBridge.write_step(cortex, working_root_id, result)
│   │   │
│   │   ├── Refresh viewport
│   │   │   └── CortexBridge.refresh_viewport(cortex, tree, context_state)
│   │   │
│   │   ├── Auto-checkpoint (every N steps)
│   │   │   └── CortexBridge.write_checkpoint(cortex, tree, context_state)
│   │   │
│   │   ├── Self-reflection (if autonomous mode)
│   │   │   └── CortexBridge.write_reflection() + get_relevant_knowledge()
│   │   │
│   │   └── Goal validation gate (autonomous mode)
│   │
│   └── Track completed steps in __completed_steps__ set
│
├── 10. Finalize
│   ├── Write final output to Output subtree
│   ├── Write episodic memory (MemoryRouter.write_episodic)
│   ├── Tree stays ACTIVE (not COMPLETE)
│   └── Billing settlement
│
└── 11. Error Handling
    └── Fresh DB session for FAILED status persistence (ERR-1 fix)
```

### 12.2 Context State Keys

The `context_state` dict carries both user data and internal bookkeeping. Internal keys are stripped before LLM prompt injection:

```python
# constants.py
INTERNAL_CONTEXT_KEYS = frozenset({
    "input",
    "cortex_tree_id",
    "subtree_root_id",
    "__memory__",
    "__cortex_viewport__",
    "__cortex_tree_id__",
    "__cortex_cursor__",
    "__cortex_knowledge__",
    "__context_sources__",
    "__episodic_memory__",
    "__semantic_context__",
    "__memory_context__",
    "__completed_steps__",
    "tool_call_counts",
    "company_id",
    "user_id",
})
```

### 12.3 Step-to-CORTEX Mapping

| Step Type | Handler | CORTEX Write |
|-----------|---------|--------------|
| THOUGHT/ACTION | `StepExecutorService._execute_thought()` | Finding node in Working Memory |
| TOOL_CALL | `StepExecutorService._execute_tool_call()` | Finding node + Knowledge node (if scraper) |
| CHILD_ENTITY_INVOCATION | `StepExecutorService._execute_child_invocation()` | Child shares same tree |
| NAVIGATE | `CortexBridge.execute_cortex_step()` | Updates cursor only |
| READ | `CortexBridge.execute_cortex_step()` | Updates cursor only |
| WRITE | `CortexBridge.execute_cortex_step()` | New node in tree |
| RECURSE | `CortexBridge.execute_cortex_step()` | Task node + child run |
| AWAIT_CHILDREN | `CortexBridge.execute_cortex_step()` | Collects results |

---

## 13. Data Invariants & Constraints

| # | Invariant | Enforcement | Location |
|---|-----------|-------------|----------|
| 1 | **Summary Always Exists** | Parent must have summary before accepting children | `write()` — raises `ValueError` |
| 2 | **No Unbounded Viewports** | MAX_CHILDREN limit triggers re-clustering | `write()` → `_schedule_reclustering()` |
| 3 | **Context Budget** | Auto-checkpoint when tokens exceed budget | `check_and_compact()` |
| 4 | **Write-Once Content** | No `update_content()` method exists; revisions are children | `_create_node()` — architectural |
| 5 | **Company Isolation** | All queries filter by `company_id` | `CortexRouter.__init__()` |
| 6 | **Subtree Isolation** | Child runs scoped to subtree via `_get_node()` check | `_is_descendant_of()` CTE |
| 7 | **Tree-Entity Binding** | One tree per execution run | `create_tree()` / `execute_run()` |
| 8 | **Cascade Delete** | Deleting a tree cascades to all nodes | FK `ondelete='CASCADE'` |
| 9 | **Node Ordering** | Children ordered by `sibling_order` | All queries use `ORDER BY sibling_order` |

---

## 14. Performance Optimizations

| Phase | Optimization | Before | After | File |
|-------|-------------|--------|-------|------|
| 4 | **CTE Breadcrumb** | O(depth) sequential SELECTs | 1 recursive CTE | `cortex_service.py:913` |
| 4 | **CTE Ancestry Check** | O(depth) sequential SELECTs | 1 recursive CTE | `cortex_service.py:970` |
| 4 | **Viewport Redis Cache** | Recompute on every step | 30s TTL cache | `cortex_bridge.py:411` |
| 6 | **Incremental Size Tracking** | O(n) full scan per checkpoint | O(1) per mutation | `cortex_bridge.py:46` |
| 4 | **Batch Write Buffer** | Individual INSERT per node | Buffered batch flush | `cortex_bridge.py:455` |
| 4 | **Bridge Paragraph Cost Tracking** | Invisible LLM cost | Tracked in usage_logs | `cortex_service.py:1096` |

### 14.1 Database Indexes

```sql
-- cortex_trees
ix_cortex_trees_entity_id    ON (entity_id)
ix_cortex_trees_company_id   ON (company_id)
ix_cortex_trees_status       ON (status)
ix_cortex_trees_next_resume  ON (next_resume_at) WHERE next_resume_at IS NOT NULL

-- cortex_nodes
ix_cortex_nodes_tree_id      ON (tree_id)
ix_cortex_nodes_parent_id    ON (parent_id)
ix_cortex_nodes_tree_parent  ON (tree_id, parent_id)  -- composite for viewport queries
ix_cortex_nodes_tree_type    ON (tree_id, node_type)   -- for get_knowledge_root/working_root
ix_cortex_nodes_status       ON (status)
```

---

## 15. Voice Channel Memory

Voice agents use a **simplified memory model** compared to CORTEX:

### 15.1 Voice Agent Context Loading (voice/agent_loader.py)

Voice sessions do NOT use CORTEX trees. Instead, they use:

1. **Conversation History** (last 10 turns): Loaded from `conversation_history` table, filtered by `customer_id + agent_id + channel`
2. **Context Sources** (injected into system prompt): Documents/artifacts loaded as text and appended under `## Memory Context (Product Knowledge)`
3. **Persona System**: `PersonaService` builds system prompt from `AgentPersona` schema

**Why no CORTEX for voice?**: Voice sessions are real-time (~100ms latency budget). CORTEX's navigate → read → write cycle adds 50-200ms per operation, which is acceptable for async text agents but too slow for real-time speech-to-speech conversations. Voice agents instead rely on the model's native context window (Gemini Live) with pre-loaded knowledge.

### 15.2 Voice Memory Limits

```python
MAX_TOTAL_CHARS = 30_000  # Voice context sources capped at 30K chars
# vs. CORTEX text agents: 50,000 chars per node content
```

---

## 16. Database Schema & Migrations

### 16.1 Migration Chain

```
j1k2l3m4n5o6 (previous)
    │
    └── k1l2m3n4o5p6 — Add CORTEX tables (2026-03-08)
        │   Creates: cortex_trees, cortex_nodes
        │   Adds: tree_id FK to episodic_memories
        │   Enums: cortex_tree_status, cortex_node_type, cortex_node_status
        │
        └── q1r2s3t4u5v6 — Add episodic_memories table (2026-04-07)
            │   Creates: episodic_memories with full schema
            │   Indexes: entity_id, user_id
            │
            └── r1s2t3u4v5w6 — Add CORTEX scheduling (2026-04-10)
                    Adds: resume_schedule, next_resume_at to cortex_trees
                    Index: partial index on next_resume_at WHERE NOT NULL
```

### 16.2 Enum Types

```sql
CREATE TYPE cortex_tree_status AS ENUM ('active', 'suspended', 'complete', 'archived');
CREATE TYPE cortex_node_type AS ENUM ('root', 'knowledge', 'finding', 'task', 'output', 'checkpoint');
CREATE TYPE cortex_node_status AS ENUM ('pending', 'active', 'complete', 'summarised');
```

---

## 17. Configuration Constants

| Constant | Value | Source | Purpose |
|----------|-------|--------|---------|
| `MAX_CHILDREN` | 12 | `cortex_service.py:167` | Viewport fanout limit |
| `PAGE_SIZE_TOKENS` | 8,000 | `cortex_service.py:168` | READ page size |
| `CONTEXT_BUDGET_PCT` | 40 | `cortex_service.py:169` | % of model window before compaction |
| `CHARS_PER_TOKEN` | 4 | `cortex_service.py:170` | Token estimation ratio |
| `VIEWPORT_CACHE_TTL` | 30s | `cortex_bridge.py:31` | Redis viewport cache TTL |
| `EMBEDDING_MODEL` | `gemini-embedding-004` | `constants.py:17` | Semantic search embeddings |
| `MAX_REACT_TURNS` | 12 | `constants.py:48` | REACT loop iteration limit |
| `MAX_CONTENT_CHARS` | 50,000 | `constants.py:50` | Node content cap |
| `checkpoint_every_n_steps` | 3 | `worker.py:888` | Auto-checkpoint interval (configurable per entity) |

---

## 18. Design Trade-offs & Decisions

### 18.1 PostgreSQL vs. Dedicated Graph Database

**Decision**: Use PostgreSQL with recursive CTEs.

**Pros**:
- Single database for all data (no operational complexity of a separate Neo4j/DGraph)
- CTEs handle the 2 graph queries needed (breadcrumb, ancestry check) efficiently
- pgvector extension provides semantic search in the same DB
- ACID transactions ensure tree consistency during re-clustering

**Cons**:
- Deep trees (>20 levels) may see CTE performance degradation
- No native graph traversal optimizations

**Rationale**: CORTEX trees are typically shallow (max 5-6 levels deep) with moderate fanout (≤12). The graph operations are limited to breadcrumb (root→cursor) and ancestry check (child→root), both of which PostgreSQL CTEs handle in <5ms for trees up to 1000 nodes.

### 18.2 Viewport-Only vs. Full Tree Context

**Decision**: Agents receive only a viewport (one-level slice), never the full tree.

**Trade-off**: Agents lose global awareness but gain bounded token cost and forced deliberate navigation.

**Rationale**: In testing, agents given full tree context (~5,000 tokens for a 50-node tree) performed worse than viewport-constrained agents because they attempted to address all information simultaneously rather than focusing on the current subtask. The viewport forces a "depth-first" working style that produces more thorough analysis.

### 18.3 Write-Once vs. Mutable Content

**Decision**: Node content is immutable after creation.

**Trade-off**: Revisions require creating a new child node rather than updating in place, increasing tree size.

**Rationale**: Immutability provides a complete audit trail of the agent's reasoning process. It also prevents race conditions during parallel step execution (RACE-1/RACE-2 fixes in worker.py) and simplifies the caching model (cached content never goes stale).

### 18.4 Trees Stay ACTIVE After Completion

**Decision**: Trees are not marked COMPLETE after a run finishes.

**Rationale**: This enables "continuation" workflows where a user asks the same agent to build upon previous work. The tree retains all its knowledge and working memory nodes, and the next run picks up at the `resume_cursor_id`.

### 18.5 Inline Re-clustering vs. Background Job

**Decision**: Re-clustering runs inline during `write()`, not as a background job.

**Trade-off**: Write operations with re-clustering take ~50ms longer.

**Rationale**: Background re-clustering would require handling eventual consistency (the viewport might show 15 children between the write and the re-clustering job). Inline execution ensures the next viewport always reflects the clustered state.

---

## 19. Gap Analysis & Future Work

| Gap # | Description | Status | Priority |
|-------|-------------|--------|----------|
| 3 | Auto-compaction token budget triggers | ✅ Implemented | — |
| 5 | Scheduled CORTEX wake-ups (cron) | ✅ Implemented | — |
| 7 | Coherence pass (bridge paragraphs) | ✅ Implemented | — |
| 9 | Async re-clustering on MAX_CHILDREN | ✅ Implemented (inline) | — |
| 12 | Checkpoint time tracking | ✅ Implemented | — |
| 18 | Subtree isolation enforcement | ✅ Implemented | — |
| 19 | Operations prompt in viewport | ✅ Implemented | — |
| — | **Summarised status** | 🔲 Not yet used | Low |
| — | **Node content updates** (breaking write-once) | 🔲 Intentionally omitted | N/A |
| — | **Cross-tree linking** | 🔲 Not implemented | Medium |
| — | **Tree archival/cleanup** | 🔲 Not implemented | Medium |
| — | **Semantic search over CORTEX nodes** | 🔲 Not implemented | High |
| — | **Voice channel CORTEX integration** | 🔲 Not implemented | Low |
| — | **Tree visualization frontend** | 🔲 Not implemented | Medium |

### 19.1 High-Priority Future Work

**Semantic Search Over CORTEX Nodes**: Currently, knowledge retrieval within a tree is limited to querying the last 10 children of the knowledge root. Adding pgvector embeddings to `cortex_nodes` would enable semantic search across the entire tree, dramatically improving the agent's ability to find relevant prior findings in large trees (100+ nodes).

**Cross-Tree Linking**: Currently, each run creates an isolated tree. Enabling agents to reference nodes from previous trees (via `source_ref` pointers) would support long-term knowledge accumulation across multiple research sessions.

---

## Appendix A: REST API Endpoints (cortex_router.py)

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| POST | `/cortex/trees` | `create_tree` | Create new tree |
| GET | `/cortex/trees` | `list_trees` | List trees (filter by entity/status) |
| GET | `/cortex/trees/{id}` | `get_tree` | Get tree status |
| POST | `/cortex/trees/{id}/resume` | `resume_tree` | Resume suspended tree |
| POST | `/cortex/trees/{id}/suspend` | `suspend_tree` | Suspend active tree |
| POST | `/cortex/navigate/{node_id}` | `navigate` | Navigate to node |
| GET | `/cortex/nodes/{id}/content` | `read_node_content` | Read paged content |
| POST | `/cortex/nodes` | `create_node` | Write new node |
| POST | `/cortex/trees/{id}/checkpoint` | `create_checkpoint` | Manual checkpoint |
| POST | `/cortex/recurse` | `recurse` | Spawn child execution |
| GET | `/cortex/nodes/{id}` | `get_node_details` | Get node metadata |
| GET | `/cortex/trees/{id}/output` | `assemble_output` | DFS output assembly |

## Appendix B: File Cross-Reference

```
backend/src/ai/
├── cortex_service.py      ← Core engine (7 ops, CTE queries, invariants)
├── cortex_models.py       ← ORM: CortexTree, CortexNode, enums
├── cortex_bridge.py       ← Worker↔CORTEX adapter (step writing, viewport, ingestion)
├── cortex_router.py       ← REST API (FastAPI endpoints)
├── cortex_ingestion.py    ← Document → node transformation
├── memory_service.py      ← 3-tier router (Working/Episodic/Semantic)
├── models.py              ← EpisodicMemory ORM model
├── schemas.py             ← Pydantic DTOs (CortexCheckpointCreate, etc.)
├── constants.py           ← INTERNAL_CONTEXT_KEYS, EMBEDDING_MODEL
├── worker.py              ← ExecutionEngine (CORTEX integration points)
├── step_executor.py       ← Step handlers (THOUGHT, TOOL_CALL, etc.)
└── persona_service.py     ← AgentPersona (voice memory context)

backend/migrations/versions/
├── k1l2m3n4o5p6_add_cortex_tables.py          ← cortex_trees, cortex_nodes
├── q1r2s3t4u5v6_add_episodic_memories_table.py ← episodic_memories
└── r1s2t3u4v5w6_add_cortex_scheduling.py       ← resume_schedule, next_resume_at
```

---

*End of CORTEX Memory System Architecture Document — Phase 9*
