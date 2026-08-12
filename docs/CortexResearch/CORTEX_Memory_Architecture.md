# CORTEX Memory System — Comprehensive Technical Architecture Document

> Reverse-engineered from the source tree at `backend/src/ai/memory/` (v2.0).
> This document is the authoritative architecture reference; it is intended to
> stand on its own so a new engineer can understand every aspect of the memory
> system without reading another file.

---

## Table of Contents

1. Executive Summary
2. Design Inspirations & First Principles
3. Logical Layer Model
4. Data Model (Persistence Layer)
   - 4.1 `cortex_trees` table
   - 4.2 `cortex_nodes` table
   - 4.3 `cortex_edges` table
   - 4.4 Enumerations (TreeStatus, NodeType, NodeStatus, MemoryDomain, ScopeLevel)
   - 4.5 Legacy / Co-Existing Models
   - 4.6 Indexes & Invariants
5. The Cognitive Tree (CORTEX) Engine
   - 5.1 `CortexRouter` (`cortex_service.py`)
   - 5.2 The 7 CORTEX Operations
   - 5.3 Viewport mechanics & DTOs
   - 5.4 Tree invariants
   - 5.5 Subtree isolation
   - 5.6 Re-clustering on viewport overflow
   - 5.7 Output assembly & coherence pass
6. The Four Memory Domains
   - 6.1 Knowledge Domain
   - 6.2 Episodic Domain
   - 6.3 Experience Domain
   - 6.4 Intelligence Domain
7. Scope Hierarchy (App → Partner → Tenant → User → Entity → Runtime)
8. Semantic Graph Layer
   - 8.1 Edge types
   - 8.2 `SemanticGraphService` operations
   - 8.3 Hybrid semantic + graph search
   - 8.4 Graph maintenance & decay
9. Embedding Pipeline
10. Document Ingestion Pipelines
    - 10.1 `CortexIngestionPipeline`
    - 10.2 `KnowledgeTreeService.ingest_document`
    - 10.3 Tool-output ingestion via `CortexBridge`
11. The Dreaming Engine (Consolidation)
    - 11.1 Phase 1 — Observation Extraction
    - 11.2 Phase 2 — Pattern Recognition
    - 11.3 Phase 3 — Intelligence Distillation
    - 11.4 Scheduling & thresholds
12. Memory Retrieval & Assembly
    - 12.1 `MemoryRouter` (v1 — Legacy 3-tier)
    - 12.2 `MemoryAssemblyService` (v2 — 4-domain)
    - 12.3 Unified `assemble_memory` façade
    - 12.4 `MemoryAssemblyResult` & prompt formatting
    - 12.5 `MemoryScope` configuration matrix
13. `CortexBridge` — The Execution Engine Interface
    - 13.1 Responsibilities matrix
    - 13.2 Context-size tracking
    - 13.3 Viewport caching (Redis)
    - 13.4 Reflection & self-awareness
    - 13.5 Co-access tracking
14. Integration With the Execution Engine
    - 14.1 Lifecycle phases C1–C5
    - 14.2 CORTEX-native step types
    - 14.3 Reparenting and recursive children
    - 14.4 Auto-checkpointing
15. Background Jobs & Scheduling
    - 15.1 `dreaming_worker`
    - 15.2 `graph_maintenance_worker`
    - 15.3 `cortex_resume_scheduled` cron
    - 15.4 `resume_execution`
16. API Surface (HTTP / REST)
17. Constants, Tunables, and Internal Keys
18. Storage, Cost, and Performance Characteristics
19. Security, Multi-Tenancy & Isolation
20. Concurrency, Transactions, and Resume Semantics
21. Observability & Diagnostics
22. End-to-End Sequence Diagrams
23. Known Issues, Gaps, and Forward Roadmap
24. Glossary
25. File Map / Source Index

---

## 1. Executive Summary

CORTEX (Cognitive Orchestrated Recursive Tree EXecution) is a persistent,
navigable, writable cognitive memory substrate used by the AI execution
engine. It is not a "context window" — it is a *file system + database +
graph* that the agent reads from and writes to step-by-step. The agent's
LLM context window holds only a **viewport** onto the tree.

The system encodes four orthogonal **memory domains**:

| Domain | Lifetime | Source | Used For |
|---|---|---|---|
| **Knowledge** | Persistent | User-uploaded documents, scraped data | Reference recall |
| **Episodic** | Persistent | Every completed `ExecutionRun` | Recent history |
| **Experience** | Persistent | Distilled by Dreaming Engine | Patterns & suggestions |
| **Intelligence** | Persistent | Distilled by Dreaming Engine | Actionable rules |

A fifth, transient domain — the **runtime tree** — is created per
execution and contains the agent's working memory, knowledge references,
intermediate findings, checkpoints, and final output sections.

All trees share a **single ORM model trio**: `CortexTree`, `CortexNode`,
`CortexEdge`. Trees are disambiguated by two enums (`memory_domain`,
`scope_level`). The edges table is a graph layer overlaying all trees,
enabling cross-domain associative search.

Memory retrieval has **two coexisting implementations**:

- **v1 `MemoryRouter`** (3-tier: WORKING / EPISODIC / SEMANTIC)
- **v2 `MemoryAssemblyService`** (4-domain unified pipeline)

Both are reachable through the unified façade `assemble_memory()`
(`backend/src/ai/memory/assembler.py`) which is selected per-entity by
the `memory.memory_pipeline` capability flag (`"v1"` | `"v2"`).

The **Dreaming Engine** runs as a background arq worker. It is the
"learning loop": Episodic → Observation → Pattern → Rule. The graph
layer is maintained by a daily `graph_maintenance_worker` that decays
edge weights and prunes weak edges.

---

## 2. Design Inspirations & First Principles

Recorded directly in `cortex_models.py`:

- **PageIndex** — Hierarchical tree index for reasoning-based RAG. Inspires
  the navigation model: every parent has a small "summary view" of its
  children (the viewport), and content is *paged* rather than loaded
  whole.
- **RLM (Recursive Language Models)** — Bounded-context recursive
  execution. Inspires the `RECURSE` operation: spawn a child run with its
  own subtree scope, then `AWAIT_CHILDREN` to collect results.
- **Anthropic context engineering** — Compaction, structured note-taking,
  sub-agents. Inspires `CHECKPOINT`, `write_step` as "structured notes,"
  and `recurse()` as a sub-agent.

The four invariants that follow from these inspirations are encoded in
`CortexRouter.write` and `_create_node`:

1. **Summary Always Exists** — a node cannot have children unless its
   `summary` is set. Enforced in `CortexRouter.write()`.
2. **No Unbounded Viewports** — direct children per node ≤ `max_children`
   (default 12). Crossing the limit triggers async re-clustering into a
   `group` node.
3. **Content is Always Paged** — large `content` is read in
   `page_size_tokens` slices (default 8000 tokens ≈ 32 000 chars).
4. **Write-Once Content** — `content` is set at creation. Revisions are
   modelled as child `finding` nodes, not in-place edits.

---

## 3. Logical Layer Model

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       Execution Engine / Step Executor                  │
│                       (ai.core.execution_engine, ai.step_executor)      │
└───────────────┬─────────────────────────────────────────┬───────────────┘
                │                                         │
                ▼                                         ▼
┌──────────────────────────┐                ┌────────────────────────────┐
│      CortexBridge        │                │ assemble_memory (façade)   │
│ (memory/cortex_bridge.py)│                │   memory/assembler.py      │
│  • build_task_description│                │  ┌─────────┐ ┌───────────┐ │
│  • write_step / reflection│               │  │   v1    │ │    v2     │ │
│  • ingest_tool_result    │                │  │MemoryRtr│ │ Assembly  │ │
│  • execute_cortex_step   │                │  └─────────┘ └───────────┘ │
│  • refresh_viewport      │                └──────────┬─────────────────┘
│  • write_checkpoint      │                           │
│  • get_relevant_knowledge│                           ▼
└────────────┬─────────────┘            ┌──────────────────────────────┐
             │                          │   Domain Services            │
             ▼                          │ • KnowledgeTreeService       │
┌────────────────────────────┐          │ • EpisodicTreeService        │
│      CortexRouter          │  ◀───────│ • ExperienceTreeService      │
│  (memory/cortex_service)   │          │ • IntelligenceTreeService    │
│  ▶ 7 CORTEX operations     │          │ • FailurePatternService      │
│  ▶ Tree lifecycle          │          └──────────────────────────────┘
│  ▶ Viewport / paging       │                       │
│  ▶ Subtree isolation       │                       ▼
└────────────┬───────────────┘          ┌──────────────────────────────┐
             │                          │  SemanticGraphService        │
             │                          │   (memory/graph_service.py)  │
             │                          │  • create_edge / upsert      │
             │                          │  • expand_from_node (BFS)    │
             │                          │  • semantic_graph_search     │
             │                          │  • create_similarity_edges   │
             │                          │  • track_co_access           │
             │                          │  • decay/prune maintenance   │
             │                          └──────────────┬───────────────┘
             ▼                                         ▼
┌────────────────────────────────────────────────────────────────────────┐
│         PostgreSQL + pgvector + cortex_trees/nodes/edges               │
│                     (ORM models in memory/cortex_models.py)            │
└────────────────────────────────────────────────────────────────────────┘
             ▲                                         ▲
             │                                         │
             │  Async background workers (arq)         │
             │  • dreaming_worker                       │
             │  • graph_maintenance_worker              │
             │  • cortex_resume_scheduled (cron 5 min)  │
             │  • resume_execution                      │
             │  • process_document                      │
             └──────────────────────────────────────────┘
```

---

## 4. Data Model (Persistence Layer)

All three CORTEX tables are defined in
`backend/src/ai/memory/cortex_models.py`. The database is PostgreSQL with
the `pgvector` extension; embedding vectors are length **768** (matches
the fallback Gemini `text-embedding-005`).

### 4.1 `cortex_trees`

Root container — one row per cognitive tree.

| Column | Type | Purpose |
|---|---|---|
| `id` | `UUID` PK | |
| `entity_id` | `UUID` FK → `hierarchical_entities.id` | Owning agent/entity |
| `user_id` | `UUID` FK → `users.id` (nullable) | Initiating user |
| `company_id` | `UUID` FK → `companies.id` | Tenant scope (always set) |
| `task_description` | `Text` | Free-form description |
| `status` | enum `CortexTreeStatus` | `active`/`suspended`/`complete`/`archived` |
| `total_nodes` | `Integer` | Cached count |
| `root_node_id` | `UUID` | Pointer to the tree's root `CortexNode` |
| `output_root_id` | `UUID` | Root of the Output subtree |
| `resume_cursor_id` | `UUID` | **Where the agent will resume** |
| `max_children` | `Integer` (default 12) | Viewport invariant |
| `page_size_tokens` | `Integer` (default 8000) | Page size for `read()` |
| `context_budget_pct` | `Integer` (default 40) | % of model window before auto-checkpoint |
| `resume_schedule` | `String(100)` | Cron expression for periodic wake-ups |
| `next_resume_at` | `DateTime` | Used by `cortex_resume_scheduled` cron |
| `memory_domain` | enum `MemoryDomain` | `knowledge`/`episodic`/`experience`/`intelligence` |
| `scope_level` | enum `ScopeLevel` | `app`/`partner`/`tenant`/`user`/`entity`/`runtime` |
| `app_id` / `partner_id` | `UUID` FK → companies | Scope hierarchy keys |
| `run_id` | `UUID` FK → `execution_runs.id` | Set only for `runtime` scope |
| `tree_category` | `String(100)` | Free-form (e.g. `"hr_policies"`) |
| `expires_at` | `DateTime` | NULL = never |
| `is_persistent` | `Boolean` (default true) | If false, may be archived after run |
| `last_consolidated_at` | `DateTime` | Last dreaming-engine pass |
| `consolidation_generation` | `Integer` (default 0) | Dream-cycle counter |
| `source_run_ids` | `JSONB` | Runs that contributed |
| `created_at` / `last_active_at` | `DateTime` | |

**Indexes:**
`ix_cortex_trees_entity_id`, `ix_cortex_trees_company_id`,
`ix_cortex_trees_status`, `ix_cortex_trees_domain_scope`,
`ix_cortex_trees_scope_company`.

### 4.2 `cortex_nodes`

The unit of memory. Every piece of information — input document section,
intermediate finding, output paragraph, checkpoint, observation,
pattern, rule, episode — is a node.

| Column | Type | Purpose |
|---|---|---|
| `id` | `UUID` PK | |
| `tree_id` | `UUID` FK ON DELETE CASCADE | Owning tree |
| `parent_id` | `UUID` FK ON DELETE SET NULL | Parent node (NULL for root) |
| `node_type` | enum `CortexNodeType` | See §4.4 |
| `title` | `String(500)` NOT NULL | Shown in viewport |
| `summary` | `Text` | ≈200 tokens, shown in parent's viewport |
| `content` | `Text` | Full content; only loaded by `read()` |
| `content_tokens` | `Integer` | Cached size estimate |
| `status` | enum `CortexNodeStatus` | `pending`/`active`/`complete`/`summarised` |
| `source_ref` | `JSONB` | E.g. `{document_id, page_start, page_end, url, tool}` |
| `execution_run_id` | `UUID` FK | Run that produced the node |
| `depth` | `Integer` | Root = 0 |
| `sibling_order` | `Integer` | Order among siblings |
| `metadata_extra` | `JSONB` | Free-form (step_id, tools_used, cost_usd, ...) |
| `embedding` | `pgvector.Vector(768)` | Semantic vector |
| `embedding_model` | `String(100)` | Model that produced the vector |
| `cross_refs` | `JSONB` | `[{tree_id, node_id, relationship}, ...]` |
| `access_count` | `Integer` (default 0) | Read counter |
| `last_accessed_at` | `DateTime` | |
| `importance_score` | `Numeric(5,3)` (default 0.500) | Learning-engine signal |
| `created_at` / `updated_at` | `DateTime` | |

**Indexes:**
`ix_cortex_nodes_tree_id`, `ix_cortex_nodes_parent_id`,
`ix_cortex_nodes_tree_parent`, `ix_cortex_nodes_tree_type`,
`ix_cortex_nodes_status`, `ix_cortex_nodes_tree_type_status`.

### 4.3 `cortex_edges`

Weighted directed edges forming the semantic graph layer. Edges may
cross trees, domains, and scope levels.

| Column | Type | Purpose |
|---|---|---|
| `id` | `UUID` PK | |
| `source_node_id` / `target_node_id` | `UUID` FK ON DELETE CASCADE | |
| `edge_type` | `String(50)` | See §8.1 |
| `weight` | `Numeric(5,4)` (default 0.5000) | 0..1 |
| `traversal_count` | `Integer` | |
| `last_traversed_at` | `DateTime` | |
| `created_by` | `String(50)` | `"dreaming_engine"`, `"embedding_pipeline"`, `"runtime_tracking"`, ... |
| `edge_metadata` (column name `metadata`) | `JSONB` | E.g. `{run_id}` |
| `created_at` | `DateTime` | |

**Uniqueness:** `(source_node_id, target_node_id, edge_type)` unique
constraint — edges are upserted (`SemanticGraphService.create_edge`),
not duplicated.

**Indexes:** `ix_cortex_edges_source`, `ix_cortex_edges_target`,
`ix_cortex_edges_type_weight` (weight DESC).

### 4.4 Enumerations

```python
class CortexTreeStatus(str, enum.Enum):
    ACTIVE     = "active"
    SUSPENDED  = "suspended"
    COMPLETE   = "complete"
    ARCHIVED   = "archived"

class CortexNodeStatus(str, enum.Enum):
    PENDING     = "pending"
    ACTIVE      = "active"
    COMPLETE    = "complete"
    SUMMARISED  = "summarised"

class CortexNodeType(str, enum.Enum):
    # v1 (foundational)
    ROOT          = "root"
    KNOWLEDGE     = "knowledge"
    FINDING       = "finding"
    TASK          = "task"
    OUTPUT        = "output"
    CHECKPOINT    = "checkpoint"
    # v2 (extensions)
    GROUP         = "group"           # re-clustering container
    DOCUMENT      = "document"
    SECTION       = "section"
    CHUNK         = "chunk"
    OBSERVATION   = "observation"     # Experience
    PATTERN       = "pattern"         # Experience
    SUGGESTION    = "suggestion"      # Experience
    INSTRUCTION   = "instruction"     # Intelligence
    STRATEGY      = "strategy"        # Intelligence
    PREFERENCE    = "preference"      # Intelligence
    EPISODE       = "episode"         # Episodic
    EPISODE_GROUP = "episode_group"   # Episodic (month/day)

class MemoryDomain(str, enum.Enum):
    KNOWLEDGE     = "knowledge"
    EXPERIENCE    = "experience"
    INTELLIGENCE  = "intelligence"
    EPISODIC      = "episodic"

class ScopeLevel(str, enum.Enum):
    APP      = "app"      # L0: platform-wide
    PARTNER  = "partner"  # L1
    TENANT   = "tenant"   # L2 (company)
    USER     = "user"     # L3
    ENTITY   = "entity"   # L4 (agent)
    RUNTIME  = "runtime"  # L5 (single execution)
```

### 4.5 Legacy / Co-Existing Models

Two pre-CORTEX persistence tables are still written by dual-write paths:

- **`episodic_memories`** (`ai/models.py:17 — EpisodicMemory`) — flat
  short-term interaction record. Limited to `MAX_EPISODES = 10` per
  entity/user. Pruned by `MemoryRouter._prune_old_episodes`. Kept in
  sync with the Episodic Tree by `MemoryRouter.write_episodic`.
- **`documents` + `document_chunks`** — pre-CORTEX RAG store. Populated
  by `process_document` arq job alongside Knowledge Tree ingestion.
  Used as a fallback inside `MemoryRouter.search_semantic` when the v2
  graph search returns no results.
- **Failure patterns** are not a separate table — they are inferred
  on-demand from `ExecutionRun` history by `FailurePatternService` using
  keyword classifiers (see §6.4).

### 4.6 Invariants (Enforced in Code)

| Invariant | Where enforced | Behavior |
|---|---|---|
| Parent must have summary | `CortexRouter.write` | Raises `ValueError` |
| `child_count < max_children` | `CortexRouter.write` | Warns, then triggers `_schedule_reclustering` |
| Content is write-once | Convention (no setter); revisions are children | — |
| Subtree isolation for child runs | `CortexRouter._get_node` with `scoped_subtree_root_id` | Raises `ValueError` if requested node is outside |
| One persistent tree per (entity, domain) | `get_or_create_*_tree` queries with `domain + scope_level` filter | — |

---

## 5. The Cognitive Tree (CORTEX) Engine

### 5.1 `CortexRouter` (`memory/cortex_service.py`)

A 1109-line class implementing the seven primitive operations. It is
instantiated per request: `CortexRouter(db, company_id,
scoped_subtree_root_id=None)`.

Class constants:

```python
DEFAULT_MAX_CHILDREN          = 12
DEFAULT_PAGE_SIZE_TOKENS      = 8000
DEFAULT_CONTEXT_BUDGET_PCT    = 40
CHARS_PER_TOKEN               = 4   # rough estimate
```

### 5.2 The 7 CORTEX Operations

Method signatures and behaviors:

| # | Method | Purpose | Side-effects |
|---|---|---|---|
| 1 | `create_tree(entity_id, user_id, task_description, ...) -> CortexTree` | Creates a runtime-scoped tree with **4 nodes**: a ROOT plus three subtree anchors (📚 Knowledge Base, 🔬 Working Memory, 📝 Output) | `total_nodes = 4`; `resume_cursor_id = root` |
| 2 | `resume_tree(tree_id) -> (CortexTree, Viewport, last_checkpoint)` | Re-activate a suspended tree; navigates to `resume_cursor_id` | Status → `active`; touches `last_active_at` |
| 3 | `suspend_tree(tree_id) -> checkpoint_id` | Auto-checkpoints, then sets `status = SUSPENDED` | Writes checkpoint node |
| 4 | `navigate(node_id) -> Viewport` | Move cursor to `node_id`; returns parent + children + breadcrumb | Updates `resume_cursor_id` |
| 5 | `read(node_id, page=0) -> NodeContent` | Returns one page of `node.content` | Sets status `pending → active`; updates cursor |
| 6 | `write(parent_id, node_type, title, content, summary, ...) -> UUID` | Create a child node; enforces invariants 1 & 2 | Updates `total_nodes` and cursor |
| 7 | `recurse(node_id, task, result_slot, ...) -> (task_node_id, child_run_id)` | Spawn child execution scoped to subtree | Creates `task` node and `ExecutionRun` (status PENDING) |

Two additional methods round out the spec:

- `await_children(parent_node_id) -> {result_slot: NodeSummaryDTO}` —
  collect results from completed child task nodes.
- `checkpoint(tree_id, progress_summary, key_facts, next_steps) -> UUID` —
  write a `checkpoint` node at the current cursor; metadata records
  time elapsed and last 20 written node IDs.

Plus the auto-compaction helper:

- `check_and_compact(tree_id, current_token_count, model_context_window=200_000)`
  — if `current_token_count >= context_budget_pct * model_context_window`,
  auto-creates a checkpoint and returns its ID.

Output assembly:

- `assemble_output(tree_id, coherence_pass=True) -> str` — depth-first
  traversal of the Output subtree concatenating `complete` nodes; if
  `coherence_pass` is True and there are ≥2 sections, an LLM
  (`LLMRouter.call_llm("text_generation")`) generates one transition
  paragraph between each pair (cost is logged via `usage_logs`).

### 5.3 Viewport Mechanics & DTOs

The agent never receives the raw tree — it always receives a `Viewport`:

```python
@dataclass
class NodeSummaryDTO:
    id: str
    title: str
    summary: Optional[str]
    status: str
    node_type: str
    sibling_order: int
    depth: int
    content_tokens: int

@dataclass
class Viewport:
    current_node: NodeSummaryDTO
    children:     List[NodeSummaryDTO]
    parent:       Optional[NodeSummaryDTO]
    breadcrumb:   List[{id, title}]
```

`Viewport.to_prompt_text()` serializes a viewport for prompt injection
with four sections: **Navigation Path** (breadcrumb), **Current Node**,
**Children**, and **Available CORTEX Operations** (the static prompt
`CORTEX_OPERATIONS_PROMPT`). The agent sees:

```
## Navigation Path
Task: Build Q3 report → 🔬 Working Memory

## Current Node: 🔬 Working Memory
Type: finding | Status: active | Depth: 1
Summary: Agent's intermediate findings, reasoning, and discovered facts.

## Children
  [1] Revenue analysis (finding, complete) — Q3 totals computed
  [2] Competitor scan (finding, active) — In progress

## Available CORTEX Operations
You can perform the following operations on the cognitive tree:
  NAVIGATE(node_id) — Move your viewport to a node; see its title, summary, and children
  READ(node_id, page=0) — Read the full content of a node (paged if large)
  WRITE(parent_id, node_type, title, content, summary) — Create a new child node (finding, output, task)
  RECURSE(node_id, task, result_slot) — Spawn a child execution scoped to a subtree
  AWAIT_CHILDREN() — Wait for all child executions to complete and collect results
  CHECKPOINT(progress_summary, key_facts, next_steps) — Save progress and compress context
```

### 5.4 Tree Invariants

See §2 and §4.6. Invariants 1 and 2 are runtime-checked; 3 and 4 are
structural (paging is in `read()`, write-once is by convention).

### 5.5 Subtree Isolation

When `CortexRouter` is constructed with `scoped_subtree_root_id`, every
call to `_get_node()` runs an ancestry check via a single recursive
CTE — phase-4 performance optimization replacing iterative parent walks:

```sql
WITH RECURSIVE ancestors AS (
  SELECT id, parent_id FROM cortex_nodes WHERE id = :node_id
  UNION ALL
  SELECT cn.id, cn.parent_id
  FROM cortex_nodes cn JOIN ancestors a ON cn.id = a.parent_id
)
SELECT 1 FROM ancestors WHERE id = :ancestor_id LIMIT 1
```

Nodes outside the scope raise `ValueError`. This protects parent
contexts from being mutated by child recursive runs.

### 5.6 Re-clustering on Viewport Overflow

`_schedule_reclustering(parent_id, tree)` is invoked synchronously when
the soft `max_children` cap is exceeded:

1. Load all children of `parent_id` sorted by `sibling_order`.
2. Take the first half (oldest siblings).
3. Create a `group` node inheriting the type of the children.
4. Re-parent the moved children to the group node.
5. Re-number remaining direct children to leave room for the group at
   `sibling_order = 0`.

Total node count is incremented by 1. The grouping `node_type` is the
child type, which lets the system retain semantic grouping
(`observation`s collapse under a group of observations).

### 5.7 Output Assembly & Coherence Pass

`assemble_output(tree_id, coherence_pass=True)`:

1. DFS traversal of the Output subtree (`_dfs_collect`); only `complete`
   nodes with content are emitted.
2. If `coherence_pass` and ≥2 sections, call
   `_generate_bridge_paragraphs` — single LLM call producing exactly
   `len(sections) - 1` transitions. Cost is tracked via the bridge's
   `UsageService` instance.
3. Return `"\n\n".join([section1, bridge1, section2, bridge2, ...])`.

---

## 6. The Four Memory Domains

Each domain is a *persistent, entity-scoped* tree (one tree per
(entity_id, memory_domain) pair when `scope_level = ENTITY`). The
runtime tree (`scope_level = RUNTIME`) is created fresh per execution
and lives alongside.

### 6.1 Knowledge Domain — `KnowledgeTreeService`

File: `memory/knowledge_tree_service.py`. Layout:

```
Knowledge Tree (per entity, scope=entity, domain=knowledge)
└── ROOT ("📚 Knowledge Base")
    └── DOCUMENT ("📄 report.pdf")
        └── SECTION ("Chapter 1")
            └── CHUNK ("Chunk 1") [embedding]
```

Configuration constants:

```python
CHUNK_SIZE         = 500   # chars
CHUNK_OVERLAP      = 50
MAX_SECTION_DEPTH  = 3
CHARS_PER_TOKEN    = 4
```

Key methods:

| Method | Behavior |
|---|---|
| `get_or_create_knowledge_tree(entity_id, user_id=None)` | Idempotent; one tree per entity (filtered by `domain=KNOWLEDGE, scope=ENTITY`, non-archived) |
| `ingest_document(tree_id, document_id, content, filename, ...)` | Parse → sections → chunks; embed chunks via `EmbeddingService.embed_batch`; create DOCUMENT/SECTION/CHUNK nodes |
| `search(entity_id, query, top_k=5)` | pgvector cosine search over CHUNK nodes; updates `access_count` and `last_accessed_at`; returns `[{node_id, title, content, source_ref, score, section_title, document_title}]` |
| `get_knowledge_references(entity_id, query, top_k=3)` | Lightweight references for injection into runtime trees; threshold `score > 0.3` |

Document parsing strategy (`_parse_sections`): try markdown
`^#{1,4}\s+...` first; fall back to `^[A-Z][A-Z\s]{4,}[A-Z]$` ALL-CAPS
heading detection; otherwise paragraph-based 2000-char splits for docs
> 3000 chars.

### 6.2 Episodic Domain — `EpisodicTreeService`

File: `memory/episodic_tree_service.py`. Layout:

```
Episodic Tree (per entity, scope=entity, domain=episodic)
└── ROOT ("📚 Execution History")
    └── EPISODE_GROUP ("📅 May 2026")
        └── EPISODE_GROUP ("📅 Friday, May 16, 2026")
            └── EPISODE ("🎬 <run title>")
```

The hierarchy auto-creates `MONTH → DAY` group nodes on demand via
`_get_or_create_group()`. Configured with `max_children = 100`.

Key methods:

| Method | Behavior |
|---|---|
| `get_or_create_episodic_tree(entity_id)` | Idempotent factory |
| `write_episode(entity_id, run, runtime_tree_id=None)` | Truncates input/output to 1000 chars (`text_utils.truncate_for_storage`), generates a title (entity name + input prefix), stores cost/tokens/exec_time/tools_used in `metadata_extra`, attempts an embedding (non-fatal) |
| `query_by_time(entity_id, start, end, limit=20)` | SQL date-range on `created_at`, newest first |
| `query_by_topic(entity_id, query, top_k=5)` | pgvector cosine search restricted to `node_type='episode'` |
| `get_recent_episodes(entity_id, limit=10)` | Most-recent N (used for v1 prompt injection) |

Each `episode` node carries `source_ref = {ref_type: "execution_run",
run_id, runtime_tree_id}` enabling deep-dives from the episodic log into
the originating runtime tree.

### 6.3 Experience Domain — `ExperienceTreeService`

File: `memory/experience_tree_service.py`. Layout:

```
Experience Tree (per entity, scope=entity, domain=experience)
└── ROOT ("🧠 Experience")
    ├── GROUP ("🔍 Observations") → OBSERVATION nodes
    ├── GROUP ("🔄 Patterns")     → PATTERN nodes
    └── GROUP ("💡 Suggestions")  → SUGGESTION nodes
```

The service does **not** accept direct writes from the agent. It is
populated exclusively by the Dreaming Engine. Reader methods:

| Method | Behavior |
|---|---|
| `get_observations(entity_id, limit=50)` | All observation nodes, newest first |
| `get_strong_patterns(entity_id, min_strength=0.7, min_recurrence=2)` | Patterns filtered by `metadata_extra.pattern_strength` and `recurrence_count` |
| `get_all_patterns(entity_id)` | Unfiltered patterns |
| `get_observations_root/get_patterns_root/get_suggestions_root` | Return the section anchor IDs |

### 6.4 Intelligence Domain — `IntelligenceTreeService` + `FailurePatternService`

File: `memory/intelligence_tree_service.py`. Layout:

```
Intelligence Tree (per entity, scope=entity, domain=intelligence)
└── ROOT ("🎯 Intelligence")
    ├── GROUP ("📏 Instructions") → INSTRUCTION nodes
    ├── GROUP ("🎯 Strategies")    → STRATEGY nodes
    └── GROUP ("❤️ Preferences")   → PREFERENCE nodes
```

Three rule types form distinct subtrees. Lookups go through
`RULE_TYPE_TO_SECTION = {"instruction": "📏 Instructions", ...}`.

Key methods:

| Method | Behavior |
|---|---|
| `get_or_create_intelligence_tree(entity_id)` | Idempotent factory |
| `get_all_rules(entity_id)` | All `INSTRUCTION/STRATEGY/PREFERENCE` nodes |
| `get_applicable_rules(entity_id, task_description, max_rules=10)` | pgvector search with combined score `confidence * cosine_similarity`; updates `access_count`/`last_accessed_at` in a single bulk UPDATE |
| `get_rules_for_prompt(entity_id, task_description, max_rules=5)` | Returns formatted text block (emoji + confidence + rule body) for prompt injection |

**FailurePatternService** (`ai/failure_pattern_service.py`) is a
*derived* intelligence source — it scans the last 30 days of `FAILED` /
`PARTIAL_COMPLETE` runs and classifies error messages with seven
keyword rules:

| Type | Trigger keywords | Suggestion |
|---|---|---|
| `TOOL_EMPTY` | `[tool_empty]`, `returned no results` | Try `headless_browser` instead of `web_search` |
| `TIMEOUT` | `[timeout]`, `timed out` | Lower input complexity or raise timeout budget |
| `FORMAT_ERROR` | `invalid json`, `parse error` | Validate JSON inputs |
| `API_ERROR` | `api key`, `401`, `403` | Configure integration |
| `SCRAPER_BLOCKED` | `cloudflare`, `captcha`, `bot detection` | Use headless browser |
| `DEPENDENCY_FAILED` | `[dependency_failed]` | Ensure upstream steps succeed |
| `DATA_MISSING` | `[data_missing]`, `could not be resolved` | Check `{{step_N}}` references |

Used by `MemoryAssembler._assemble_v1` when `memory_scope` is
`INTELLIGENCE_ONLY` or `KNOWLEDGE_ONLY`.

---

## 7. Scope Hierarchy (Six Levels)

Encoded via `CortexTree.scope_level` (`ScopeLevel` enum).

| Level | Value | Set By | Reading Behavior |
|---|---|---|---|
| L0 | `app` | Bootstrap / admin | Shared across all partners (rare; used for system prompts) |
| L1 | `partner` | Partner setup | Shared across tenants under a partner |
| L2 | `tenant` | Tenant config | Shared across all users in a tenant |
| L3 | `user` | User-specific | Per-user (rare; preferences) |
| L4 | `entity` | Default for persistent trees | Per-agent — typical for KB/Episodic/Experience/Intelligence trees |
| L5 | `runtime` | `create_tree` default | One per `ExecutionRun` (working memory) |

`SemanticGraphService.semantic_graph_search` filters by
`(ct.entity_id = :entity_id OR ct.scope_level IN ('app', 'tenant'))`,
which is the engine's "inheritance" mechanism — entity-scoped trees plus
shared app/tenant knowledge are visible.

---

## 8. Semantic Graph Layer

File: `memory/graph_service.py`. The graph **overlays** all CORTEX
trees; an edge's source and target may live in different trees, scopes,
or domains.

### 8.1 Edge Types

Listed as a controlled vocabulary in the `CortexEdge` docstring (not as
an enum — `edge_type` is a `String(50)`):

| Edge type | Meaning | Created by |
|---|---|---|
| `references` | Document cites another | Authoring tools |
| `derived_from` | Pattern derived from observation | `dreaming_engine` (phase 2) |
| `generalizes` | Rule generalizes a pattern | `dreaming_engine` (phase 3) — *interface defined but not yet wired* |
| `semantic_similar` | Cosine similarity above threshold | `embedding_pipeline` (auto) |
| `co_accessed` | Accessed together in same run | `runtime_tracking` |
| `precedes` | Temporal sequence | Reserved |
| `contradicts` | Conflicting rules | Reserved |
| `supersedes` | New rule replaces old | Reserved |
| `applies_to` | Rule applies to KB domain | Reserved |

### 8.2 `SemanticGraphService` Operations

Class constants:

```python
DECAY_RATE                  = 0.95
BOOST_ON_TRAVERSAL          = 0.05
MIN_WEIGHT                  = 0.01
MAX_WEIGHT                  = 1.0
SIMILARITY_THRESHOLD        = 0.85
MAX_AUTO_EDGES_PER_NODE     = 5
```

(also mirrored in `ai/constants.py` as `GRAPH_*`.)

| Method | Behavior |
|---|---|
| `create_edge(source, target, edge_type, weight=0.5, created_by, metadata=None)` | Upsert by `(source, target, edge_type)`; on hit, `weight += BOOST_ON_TRAVERSAL` (capped at `MAX_WEIGHT`), `traversal_count += 1`, `last_traversed_at = now()` |
| `expand_from_node(node_id, max_depth=2, edge_types=None, min_weight=0.1, max_nodes=20)` | BFS via recursive CTE with cycle protection (`NOT (target_node_id = ANY(path))`); weights multiplicatively decay along the path |
| `semantic_graph_search(query, entity_id, domains, top_k, graph_expansion_depth=1)` | Embed query → pgvector seed search → graph BFS → re-rank; **combined_score = 0.7 × similarity + 0.3 × edge_weight**; returns up to `top_k * 2` items |
| `create_similarity_edges(node_id)` | After embedding a node, find similar nodes (≥ 0.85) and create up to 5 `semantic_similar` edges weighted by similarity |
| `track_co_access(node_ids, execution_run_id)` | Pairwise upsert of `co_accessed` edges (weight 0.3) between all nodes accessed in the same step |
| `decay_weights(days_inactive=30)` | `UPDATE cortex_edges SET weight = GREATEST(min, weight * 0.95) WHERE last_traversed_at < NOW() - INTERVAL :days days OR last_traversed_at IS NULL` |
| `prune_weak_edges()` | `DELETE FROM cortex_edges WHERE weight < MIN_WEIGHT` |
| `get_graph_stats()` | Aggregate counts and avg/min/max weight grouped by `edge_type` |

### 8.3 Hybrid Search Algorithm (Detailed)

`semantic_graph_search` in pseudocode:

```python
async def semantic_graph_search(query, entity_id, domains, top_k, graph_expansion_depth):
    qvec = await EmbeddingService.embed_query(query)
    if not qvec: return []

    # Step 1: Semantic seed — pgvector cosine search
    seeds = SQL("""
        SELECT cn.*, ct.memory_domain,
               1 - (cn.embedding <=> :vec) AS similarity
          FROM cortex_nodes cn JOIN cortex_trees ct ON ct.id=cn.tree_id
         WHERE cn.embedding IS NOT NULL
           AND ct.company_id = :company_id
           AND (ct.entity_id = :entity_id OR ct.scope_level IN ('app','tenant'))
           AND ct.memory_domain IN (:domains)
         ORDER BY cn.embedding <=> :vec
         LIMIT :top_k
    """)

    # Step 2: Graph expansion via expand_from_node BFS (depth ≤ 2)
    results = seeds.copy()
    for seed in seeds:
        expanded = await expand_from_node(seed.id, max_depth=expansion_depth, max_nodes=5)
        for n in expanded:
            n.combined_score = 0.7 * seed.similarity + 0.3 * n.weight
            n.source = "graph_expansion"; n.expanded_from = seed.id
            results.append(n)

    # Step 3: Re-rank and truncate
    results.sort(key=lambda r: r.combined_score, reverse=True)
    return results[: 2 * top_k]
```

### 8.4 Graph Maintenance

Daily arq job `graph_maintenance_worker` (`ai/core/arq_jobs.py:477`):

```python
for company in SELECT DISTINCT company_id FROM cortex_trees WHERE status='active':
    graph = SemanticGraphService(db, company.id)
    decayed = await graph.decay_weights(days_inactive=30)
    pruned  = await graph.prune_weak_edges()
```

---

## 9. Embedding Pipeline

File: `memory/embedding_service.py`.

### Model Resolution (Priority Order)

1. `ModelTaskDefault` row where `task_type == "embedding"` for the
   company (the **AI Config** admin page sets this).
2. `IntegrationRegistry` where `service_category == "EMBEDDING"` and
   `status == "active"`.
3. `IntegrationRegistry` where `provider_name IN ("google", "gemini")`
   AND `model_name ILIKE '%embed%'` AND `status='active'`.
4. Fallback constant `EMBEDDING_MODEL = "text-embedding-005"` from
   `ai/constants.py`.

The Vertex AI client is built by `src.common.genai_factory.build_vertex_genai_client`.

### Key Methods

| Method | Behavior |
|---|---|
| `embed_text(text, task_type="RETRIEVAL_DOCUMENT")` | One-text wrapper |
| `embed_query(query)` | Uses `task_type="RETRIEVAL_QUERY"` |
| `embed_batch(texts, task_type)` | Internal batching at `BATCH_SIZE = 100`; truncates each text to 8000 chars; returns `List[Optional[List[float]]]` — `None` indicates per-text failure (logged, not raised) |
| `embed_node(node)` | Sets `node.embedding` from `summary || title || content[:2000]` |
| `embed_nodes_batch(nodes)` | Bulk embed; returns count of successes |
| `embed_node_with_edges(node)` | `embed_node` + `SemanticGraphService.create_similarity_edges(node.id)` to auto-create `semantic_similar` edges |
| `get_model_name()` | The resolved model (for `embedding_model` field) |

Embeddings are nullable on the database side — code defensively skips
nodes lacking embeddings. A failure in embedding generation never aborts
a write; the node is created without an embedding (recoverable later).

---

## 10. Document Ingestion Pipelines

Three pipelines write into the system, distinguished by source.

### 10.1 `CortexIngestionPipeline` (`memory/cortex_ingestion.py`)

Ingests a document into a *runtime* tree's knowledge subtree (i.e. the
agent has a tree open and the user uploads a document mid-task). Tree
structure produced:

```
parent_node_id
└── knowledge ("📄 filename")
    ├── knowledge ("Section A")    # title from heading detection
    ├── knowledge ("Section B")
    └── ...
```

Summaries are generated by `LLMRouter.call_llm("text_generation")` with
a prompt that biases towards navigation usefulness (~200 tokens).
Falls back to truncation on LLM failure.

### 10.2 `KnowledgeTreeService.ingest_document`

Ingests into a *persistent entity-scoped* Knowledge Tree. Uses the
richer `DOCUMENT → SECTION → CHUNK` node-type hierarchy with embeddings
at the CHUNK level. Triggered by `process_document` arq job and by the
HTTP REST ingestion endpoint.

### 10.3 Tool-Output Ingestion via `CortexBridge.ingest_tool_result`

After every tool call in `step_executor._execute_tool_call`, if the
context has `__cortex_tree_id__` set, the bridge:

1. Parses the tool output (JSON or fallback).
2. Iterates up to 10 results (URL + content pairs, e.g. from scraper).
3. For each result, calls `LLMRouter.call_llm` with a navigation-quality
   prompt to generate a ~200-token summary (cost tracked through
   `UsageService.log_usage`).
4. Writes a `knowledge` node under the runtime tree's Knowledge Base
   root, with `source_ref = {url, tool}` and
   `metadata_extra = {run_id, char_count, artifact_id, tool_success,
   verified, provenance_chain: "tool_id→cortex_bridge"}`.

This is the Phase-9 *provenance tracking* layer: every fact the agent
later cites is traceable to its tool source.

---

## 11. The Dreaming Engine (Consolidation)

File: `memory/dreaming_engine.py`. Three-phase background pipeline that
turns *episodes → observations → patterns → rules*.

### Class constants

```python
MIN_EPISODES_FOR_DREAMING        = 5
MIN_OBSERVATIONS_FOR_PATTERNS    = 3
MIN_PATTERNS_FOR_DISTILLATION    = 2
BATCH_SIZE                       = 20
CONSOLIDATION_INTERVAL_HOURS     = 24
OBSERVATION_CONFIDENCE_THRESHOLD = 0.5
PATTERN_STRENGTH_THRESHOLD       = 0.7
```

These thresholds are duplicated in `ai/constants.py` as `DREAMING_*` for
admin override.

### Entry Point

```python
async def dream(entity_id, force=False) -> {
    "observations_created": int,
    "patterns_created": int,
    "rules_created": int,
}
```

If `force=False`, `_should_run` returns True iff
`now() - Experience.last_consolidated_at >= CONSOLIDATION_INTERVAL_HOURS`
(or the tree doesn't exist yet).

### 11.1 Phase 1 — Observation Extraction

1. `EpisodicTreeService.query_by_time(start = experience.last_consolidated_at, end = now, limit = BATCH_SIZE)`.
2. Skip if `len(episodes) < MIN_EPISODES_FOR_DREAMING`.
3. Build episode summaries `{id, task, status, tools_used, cost_usd, execution_time_ms}`.
4. LLM call: `system_prompt = OBSERVATION_EXTRACTION_PROMPT` with the
   episode JSON as user prompt; temperature 0.2, max_tokens 2000.
5. Parse the resulting JSON array; reject entries with `confidence <
   OBSERVATION_CONFIDENCE_THRESHOLD`.
6. For each surviving observation, write an `OBSERVATION` node under the
   Observations section root with `importance_score = confidence` and
   `metadata_extra.source_episodes` populated. Embed via
   `EmbeddingService.embed_node`.

The prompt (`dreaming_prompts.OBSERVATION_EXTRACTION_PROMPT`) asks for
five categories: TOOL PATTERNS, SUCCESS FACTORS, FAILURE PATTERNS, COST
PATTERNS, TIME PATTERNS.

### 11.2 Phase 2 — Pattern Recognition

1. Load all observations via `ExperienceTreeService.get_observations`.
2. Cluster by embedding cosine similarity > 0.75 — greedy O(n²) pairwise
   (`_cluster_observations`).
3. For each cluster of size ≥ 2:
   - LLM call: `PATTERN_RECOGNITION_PROMPT` with the cluster's
     summaries; temperature 0.2, max_tokens 500.
   - Write a `PATTERN` node under the Patterns section root with
     `metadata_extra = {source_observations, pattern_strength,
     recurrence_count = len(cluster), success_correlation}`.
   - For each source observation, create a `CortexEdge(edge_type =
     "derived_from", weight = 1/len(cluster), created_by =
     "dreaming_engine")` from the pattern → observation.

### 11.3 Phase 3 — Intelligence Distillation

1. `ExperienceTreeService.get_strong_patterns(min_strength = 0.7,
   min_recurrence = MIN_PATTERNS_FOR_DISTILLATION)`.
2. Load existing rule summaries for de-duplication.
3. LLM call: `INTELLIGENCE_DISTILLATION_PROMPT` with `{patterns,
   existing_rules}`; temperature 0.1, max_tokens 2000.
4. Parse JSON array of rules `{type ∈ {instruction|strategy|preference},
   title, description, confidence, applicability_conditions}`.
5. Resolve the section root by `rule_type` and write an
   `INSTRUCTION/STRATEGY/PREFERENCE` node. Embed it.
6. Increment `intelligence_tree.consolidation_generation` and set
   `last_consolidated_at`.

### 11.4 Scheduling

`dreaming_worker(ctx, entity_id_str, company_id_str, force=False)` is an
arq job (`ai/core/arq_jobs.py:447`). At time of writing, no automatic
trigger enqueues this — it must be enqueued explicitly. (Documented as
Gap #2 in §23.) Manually triggerable via the HTTP API (admin path).

---

## 12. Memory Retrieval & Assembly

Two complete retrieval implementations coexist behind a façade.

### 12.1 `MemoryRouter` (v1 — Legacy 3-tier)

File: `memory/memory_service.py`. The three tiers:

| Tier | Source | Behavior |
|---|---|---|
| WORKING | `context_state` dict / CORTEX viewport | Loaded in `retrieve()` when `long_running=True` and `tree_id` is set |
| EPISODIC | Episodic Tree (v2) preferred, falls back to flat `episodic_memories` table | Last 10 per entity/user pair |
| SEMANTIC | `SemanticGraphService.semantic_graph_search` (v2), falls back to `document_chunks` pgvector | Top 5 cosine matches |

Class constants:

```python
MAX_EPISODES    = 10
MAX_SEMANTIC    = 5
EPISODIC_CHARS  = 300
```

The retrieved bundle is formatted by `format_for_prompt(memory)`. When a
CORTEX viewport is present, the format follows the spec §4.3:

```
## Task
<task_description>

## Recent Episodes
  [<ts>] '<input>' → '<output>'

## Navigation Path / Current Node / Children / Operations  (from viewport)

## Last Checkpoint
<progress_summary>
Key facts: ...
Next steps: ...
```

`write_episodic(run)` performs a **dual write**:

1. Insert into `episodic_memories` table.
2. Call `EpisodicTreeService.write_episode` to add an EPISODE node.

Top-level runs only — child runs (`parent_run_id != None`) are skipped.

### 12.2 `MemoryAssemblyService` (v2 — 4-domain)

File: `memory/memory_assembly_service.py`. Single entry point:

```python
async def assemble_runtime_memory(
    entity_id, user_id, task_description,
    runtime_tree=None,
    include_domains=None,  # subset of {knowledge, experience, intelligence, episodic}
) -> MemoryAssemblyResult
```

For each requested domain:

| Domain | Implementation |
|---|---|
| `knowledge` | `SemanticGraphService.semantic_graph_search(domains=["knowledge"], top_k=10, expansion_depth=1)`; optionally writes lightweight reference nodes into the runtime tree's Knowledge Base root via `_create_runtime_knowledge_refs` |
| `experience` | `SemanticGraphService.semantic_graph_search(domains=["experience"], top_k=5)` filtered to `node_type ∈ {observation, pattern, suggestion}` |
| `intelligence` | `IntelligenceTreeService.get_applicable_rules(top_k=10)` — confidence-weighted vector search |
| `episodic` | `EpisodicTreeService.get_recent_episodes(5)` merged with `query_by_topic(3)`; deduped by `at + input[:50]`; capped at 10 |

Result dataclass:

```python
@dataclass
class MemoryAssemblyResult:
    knowledge_refs:           List[Dict] = []
    experience_suggestions:   List[Dict] = []
    intelligence_rules:       List[Dict] = []
    episodic_context:         List[Dict] = []
    formatted_prompt:         str       = ""
```

### 12.3 Unified `assemble_memory` Façade

File: `memory/assembler.py`. The façade is the only entry point used by
`ExecutionEngine.execute_run`:

```python
async def assemble_memory(
    db, company_id, entity_id, user_id=None, tree_id=None,
    task_description="",
    memory_pipeline: "v1" | "v2" = "v1",
    memory_scope: "FULL"|"RUN_SCOPED"|"INTELLIGENCE_ONLY"|"KNOWLEDGE_ONLY"|"NONE" = "FULL",
    runtime_tree=None,
    long_running=False,
) -> Dict[str, Any]
```

It returns a dict ready to merge into `context_state`. Keys produced
(internal):

- `__memory__` — formatted text block
- `__intelligence_rules__` — structured list (v2 only or v1 KO/IO modes)
- `__episodic_memory__` — structured list (v2 only)

(see `ai/constants.py:INTERNAL_CONTEXT_KEYS` for the full set of keys
that are stripped from prompts/persistence.)

### 12.4 Prompt Formatting

`MemoryAssemblyService._format_assembled_memory` emits sections in
priority order:

```
## Learned Intelligence              ← highest priority (instructions/strategies/preferences)
The following rules have been learned from past experience:
  📏 [82%] Always check whether the user has uploaded a doc first
  🎯 [76%] Prefer headless_browser for protected sites
  ❤️ [90%] User prefers concise, structured outputs

## Relevant Knowledge                ← per-task KB snippets
  📎 [0.81] Q2 Revenue Report > Headline: Q2 totals stood at ...

## Experience Suggestions            ← from patterns
  💡 [0.72] Pattern: long scraping chains exceed token budget

## Recent Execution History          ← last 5 episodes
  [<ts>] 'analyze Q3' → '...'
```

### 12.5 Memory Scope Matrix

`memory_scope` (in `entity.capabilities.memory.memory_scope`) is mapped
inside the façade to a domain subset:

| Scope | v2 domains included | v1 behavior |
|---|---|---|
| `FULL` | knowledge, experience, intelligence, episodic | Episodic + semantic, full format |
| `RUN_SCOPED` | knowledge, experience, intelligence, episodic | Same as FULL (TODO: filter to current run tree) |
| `INTELLIGENCE_ONLY` | intelligence | Failure patterns instead of episodes |
| `KNOWLEDGE_ONLY` | knowledge, intelligence | Knowledge + failure patterns as rules |
| `NONE` | — (returns `{}`) | — (returns `{}`) |

---

## 13. `CortexBridge` — The Execution Engine Interface

File: `memory/cortex_bridge.py` (646 lines). The bridge is the
*single* object that the execution engine touches for memory
operations. It composes a private `CortexRouter`, a `UsageService`, and
optionally a Redis client.

### 13.1 Responsibilities Matrix

| Method | Used By | Purpose |
|---|---|---|
| `build_task_description(entity, input_data)` | `ExecutionEngine.execute_run` (twice) | Construct the CORTEX tree's task description — entity name + first 5 input keys |
| `write_step(cortex, working_root_id, step_result, run_id)` | `ExecutionEngine._write_step_to_cortex` | After every step, persist `step_result` as a `finding` node |
| `ingest_tool_result(run, tool_id, tool_output, context)` | `step_executor._ingest_tool_result_to_cortex` | After tool call, parse JSON results and write `knowledge` nodes |
| `execute_cortex_step(run, entity, step, cortex, tree, context)` | `ExecutionEngine._execute_cortex_step` | Handle `NAVIGATE/READ/WRITE/RECURSE/AWAIT_CHILDREN` step types |
| `resolve_node_id(target, context)` | Internal | Resolves a node ID from `target.node_id`, `target.prompt_template`, or `context["__cortex_cursor__"]` |
| `refresh_viewport(cortex, tree, context_state)` | After every step | Re-navigate to cursor; update `__cortex_viewport__`; **Redis cache** with 30 s TTL keyed by `cortex:viewport:{tree.id}:{cursor_id}` |
| `write_checkpoint(cortex, tree, context_state, step_name)` | Every `checkpoint_every_n_steps` (default 3) | Calls `check_and_compact` using `_context_size_bytes // 4` as estimated tokens |
| `write_reflection(tree_id, cursor_id, step_name, learning)` | Autonomous-mode self-reflection | Writes a `finding` node `🔍 Reflection: {step_name}` with `metadata_extra.reflection=True` |
| `get_relevant_knowledge(tree_id, current_task)` | Before THOUGHT steps in autonomous mode | Lists last 10 complete children of the knowledge root, formatted as `- title: summary` lines |
| `get_knowledge_tree_references(entity_id, query, top_k=3)` | Optional pre-step KB lookup | Bridges to `KnowledgeTreeService.get_knowledge_references` |
| `write_knowledge_reference(cortex, knowledge_root_id, knowledge_node_id, title, snippet)` | When linking persistent KB into runtime | Creates `knowledge` reference node with `metadata_extra = {is_reference: True, knowledge_node_id}` |
| `track_node_access(node_ids, run_id)` | Phase-E runtime tracking | Delegates to `SemanticGraphService.track_co_access` |
| `buffer_node(...)` / `flush_buffer(cortex)` | Reserved (Phase 4 ARCH-3) | Batched writes — currently called as individual writes |
| `update_context_size(key, old, new)` / `reset_context_size(ctx)` | Step orchestration | Maintains `_context_size_bytes` O(1) incremental counter |

### 13.2 Context-Size Tracking

Pre-Phase-4 code computed `sum(len(str(v)) for v in context.values())`
on every checkpoint check — O(n) per step. Now `update_context_size` is
called inside `store_step_output` (`ai/core/context_utils.py`) for each
mutation:

```python
def store_step_output(context_state, step_name, step_id, output, cortex_bridge=None):
    old = context_state.get(step_name, "")
    context_state[step_name] = output
    if cortex_bridge:
        cortex_bridge.update_context_size(step_name, old, output)
    if step_id and step_id != step_name:
        ...
```

The bridge's `check_and_compact` call uses `_context_size_bytes // 4` as
the token estimate (CHARS_PER_TOKEN ≈ 4).

### 13.3 Viewport Caching (Redis)

`refresh_viewport` writes the rendered viewport text into Redis under
`cortex:viewport:{tree.id}:{cursor_id}` with a 30 s TTL
(`VIEWPORT_CACHE_TTL = 30`). Cache miss falls through to
`CortexRouter.navigate`. Cache write failure is non-fatal (`except
Exception: pass`).

### 13.4 Reflection & Self-Awareness (Phase 5 — Autonomous)

In autonomous mode (`reasoning_config.execution_mode == "AUTONOMOUS"`
+ `self_reflection_enabled = True`), before every `THOUGHT` step the
engine calls `bridge.get_relevant_knowledge(tree_id, step.description)`
and injects the result into `__cortex_knowledge__`. After every step
(error or success), it calls `bridge.write_reflection` to persist what
was learned. This forms a self-bootstrapping knowledge loop entirely
inside the runtime tree.

### 13.5 Co-Access Tracking

`bridge.track_node_access(node_ids, run_id)` (Phase E). When the agent
reads multiple nodes in a single step (e.g. during a synthesis step), a
pairwise `co_accessed` edge is upserted for every pair (boosting weight
by 0.05 on every re-traversal). Over time the graph self-organizes
along "nodes that get accessed together in the same task" trajectories.

---

## 14. Integration With the Execution Engine

The engine is `ExecutionEngine.execute_run` in
`ai/core/execution_engine.py`. Memory-related phases are labeled in the
code as C1–C5.

### 14.1 Lifecycle Phases C1–C5

```
┌─── C1: Create or resume CORTEX tree ───────────────────────────────────┐
│  if input_data["cortex_tree_id"] and input_data["subtree_root_id"]:    │
│      cortex = CortexRouter(db, company_id,                              │
│                            scoped_subtree_root_id=UUID(subtree_root_id))│
│      tree, viewport, ckpt = await cortex.resume_tree(...)               │
│  elif input_data["cortex_tree_id"]:                                     │
│      tree, viewport, ckpt = await cortex.resume_tree(...)               │
│  else:                                                                  │
│      tree = await cortex.create_tree(entity_id, user_id, task_desc)     │
│      viewport = await cortex.navigate(tree.root_node_id)                │
└─────────────────────────────────────────────────────────────────────────┘

┌─── C2: Memory assembly (façade) ────────────────────────────────────────┐
│  memory_config = entity.capabilities.get("memory", {})                  │
│  _memory_scope    = memory_config.get("memory_scope",    "FULL")        │
│  _memory_pipeline = memory_config.get("memory_pipeline", "v1")          │
│  memory_context = await assemble_memory(db, company_id, entity_id, ...) │
│  context_state.update(memory_context)                                   │
└─────────────────────────────────────────────────────────────────────────┘

┌─── C3: Build context from viewport ─────────────────────────────────────┐
│  context_state["__cortex_viewport__"]  = viewport.to_prompt_text()      │
│  context_state["__cortex_tree_id__"]   = str(tree.id)                    │
│  # Plus Knowledge Base viewport for tree-sharing entities                │
│  context_state["__cortex_knowledge__"] = ...                             │
│  # Plus loaded context_sources (artifacts/CORTEX_TREE/KNOWLEDGE_BASE)    │
│  context_state["__context_sources__"] = ...                              │
└─────────────────────────────────────────────────────────────────────────┘

┌─── C4: Locate working memory root ──────────────────────────────────────┐
│  working_root = await cortex.get_working_root(_tree_id)                 │
│  working_root_id = working_root.id    # cached to avoid MissingGreenlet │
└─────────────────────────────────────────────────────────────────────────┘

┌─── C5: Step execution loop ─────────────────────────────────────────────┐
│  for step_idx, step in enumerate(steps):                                │
│      step_obj = PlanStep(**step)                                        │
│      if step_obj.type in {NAVIGATE, READ, WRITE, RECURSE,                │
│                           AWAIT_CHILDREN}:                              │
│          step_result = await bridge.execute_cortex_step(...)            │
│      else:                                                              │
│          step_result = await step_executor._execute_step_wrapper(...)   │
│      await bridge.write_step(cortex, working_root_id, sr, _run_id)      │
│      if autonomous and self_reflect:                                     │
│          await bridge.write_reflection(_tree_id, cursor, name, summary) │
│      await bridge.refresh_viewport(cortex, tree, context_state)          │
│      if (step_idx + 1) % checkpoint_every_n == 0:                        │
│          await bridge.write_checkpoint(...)                              │
│          await db.commit()                                              │
└─────────────────────────────────────────────────────────────────────────┘
```

After the loop:

```
final_output = last_step_result["output"]
await cortex.write(parent_id=tree.output_root_id, node_type="output",
                   title="Final Output", content=final_output[:50000], ...)
await MemoryRouter(db).write_episodic(run)   # dual-write episodic
tree.last_active_at = now()     # tree stays ACTIVE for future resumption
```

The tree's `status` is **deliberately left ACTIVE** — even after a
successful run, the tree remains resumable for follow-ups. Trees only
move to `complete`/`archived` via explicit admin action or expiry
sweeps.

### 14.2 CORTEX-Native Step Types

The planner can emit step types that map directly to CORTEX operations:

| `StepType` | Handler | Operation |
|---|---|---|
| `NAVIGATE` | `bridge.execute_cortex_step` → `cortex.navigate` | Move cursor; cache viewport |
| `READ` | → `cortex.read(node_id, page)` | Returns paged content (max 5000 chars in step output) |
| `WRITE` | → `cortex.write(parent_id, node_type, title, content[:20000], summary[:300])` | Returns new node UUID |
| `RECURSE` | → `cortex.recurse(node_id, task, result_slot)` + arq enqueue `execute_run(child_run_id)` | Child run scoped to subtree |
| `AWAIT_CHILDREN` | → `cortex.await_children(cursor_id)` | Returns dict of `{result_slot: NodeSummaryDTO}` |

Plus three implicit ones implemented as engine-level behaviors (not
step types): the per-step `write` of findings, the periodic
`checkpoint`, and the per-tool `ingest_tool_result`.

### 14.3 Reparenting and Recursive Children

When `cortex.recurse` is invoked:

1. A `task` node is created under `node_id` with content
   `{task, result_slot, scoped_to}` and metadata `{result_slot,
   model_override, priority, execution_run_id}`.
2. A new `ExecutionRun` is created (`parent_run_id = current run`)
   with `input_data = {cortex_tree_id, subtree_root_id, task,
   task_node_id, result_slot}` and `status = PENDING`.
3. The bridge enqueues `arq.enqueue_job("execute_run",
   str(child_run_id))` to begin asynchronous child execution.
4. The child's `CortexRouter` is constructed with
   `scoped_subtree_root_id = subtree_root_id`, isolating it.

`step_executor._execute_child_invocation` (for `CHILD_ENTITY_INVOCATION`
steps, distinct from RECURSE) also propagates `__cortex_tree_id__` into
the child's input but **strips parent-scoped memory keys** to prevent
the child from inheriting parent's episodic / semantic context:

```python
PARENT_SCOPED_KEYS = {
    "__memory__", "__episodic_memory__", "__semantic_context__",
    "__memory_context__", "__context_sources__",
}
```

### 14.4 Auto-Checkpointing

Two mechanisms:

1. **Time/step-based**: Every `governance.checkpoint_every_n_steps`
   (default 3), `bridge.write_checkpoint` is invoked. This calls
   `cortex.check_and_compact(tree.id, ctx_bytes//4)` which writes a
   checkpoint only if the running context exceeds
   `context_budget_pct × model_context_window` (default 40 % × 200 000).
2. **Suspend-triggered**: `cortex.suspend_tree` always writes a
   checkpoint before flipping status to `SUSPENDED`.

Checkpoint nodes carry a JSON `content` of `CheckpointData` —
`progress_summary, key_facts, next_steps, nodes_written (last 20 IDs),
time_elapsed_hours`. They are excluded from `_get_recent_node_ids` so
checkpoints don't reference themselves.

---

## 15. Background Jobs & Scheduling

File: `ai/core/arq_jobs.py`, registered in `ai/worker.py`.

### 15.1 `dreaming_worker(ctx, entity_id_str, company_id_str, force=False)`

Wraps `DreamingEngine(db, company_id).dream(entity_id, force)`. Returns
`{observations_created, patterns_created, rules_created}` or
`{error: ...}`.

### 15.2 `graph_maintenance_worker(ctx)`

Iterates distinct `company_id` values from active `cortex_trees`, runs
`decay_weights(days_inactive=30)` and `prune_weak_edges()` per company.
Returns `{decayed, pruned}`.

### 15.3 `cortex_resume_scheduled(ctx)`

Registered as a **cron job** in `WorkerSettings.cron_jobs`:

```python
cron(cortex_resume_scheduled, minute={0, 5, 10, 15, ..., 55})  # every 5 min
```

For every suspended tree whose `next_resume_at <= now()`:

1. Create a new `ExecutionRun(entity_id, company_id, user_id,
   input_data={cortex_tree_id}, status=PENDING)`.
2. Clear `tree.next_resume_at` to prevent re-triggering.
3. Enqueue `arq.enqueue_job("execute_run", str(resume_run.id))`.

Returns `{resumed: <count>}`.

### 15.4 `resume_execution(ctx, run_id_str)`

Manual / chained resume. Loads the existing run, instantiates an
`ExecutionEngine`, and calls `execute_run(run_id)` — which on entry
sees `input_data["cortex_tree_id"]` and resumes the tree at its
`resume_cursor_id`.

### 15.5 `process_document` (Dual-Write)

After embedding chunks into `document_chunks` it ingests the document
into the entity's persistent Knowledge Tree:

```python
if document.entity_id:
    kt_service = KnowledgeTreeService(db, document.company_id)
    tree = await kt_service.get_or_create_knowledge_tree(entity_id=document.entity_id)
    await kt_service.ingest_document(tree.id, document.id, text, filename, entity_id=document.entity_id)
```

This ensures every uploaded document is searchable via the v2 pipeline.

---

## 16. API Surface (HTTP / REST)

File: `memory/cortex_router.py`. Mounted at `/api/v1/cortex` in
`main.py`. All endpoints require authentication
(`Depends(get_current_user)`); `company_id` is taken from the user.

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/trees` | `CortexTreeCreate` | tree status |
| `GET`  | `/trees?entity_id=&status=` | — | list |
| `GET`  | `/trees/{tree_id}` | — | tree status |
| `POST` | `/trees/{tree_id}/resume` | — | `{tree, viewport, last_checkpoint}` |
| `POST` | `/trees/{tree_id}/suspend` | — | `{status: "suspended", checkpoint_id}` |
| `POST` | `/trees/{tree_id}/navigate/{node_id}` | — | viewport dict |
| `GET`  | `/trees/{tree_id}/nodes/{node_id}?page=N` | — | `NodeContent` |
| `GET`  | `/trees/{tree_id}/nodes/{node_id}/detail` | — | full node fields |
| `POST` | `/trees/{tree_id}/nodes` | `CortexNodeCreate` | `{id}` |
| `POST` | `/trees/{tree_id}/checkpoint` | `CortexCheckpointCreate` | `{id}` |
| `GET`  | `/trees/{tree_id}/output?coherence_pass=true` | — | `{output}` |
| `POST` | `/trees/{tree_id}/recurse` | `CortexRecurseRequest` | `{task_node_id, child_run_id}` |
| `POST` | `/trees/{tree_id}/ingest` | `IngestDocumentRequest` | `{nodes_created}` |

All endpoints commit the transaction at the boundary. Errors surface as
`HTTPException(404)` when a tree/node is missing or scope-isolated.

---

## 17. Constants, Tunables, and Internal Keys

File: `ai/constants.py`. The single source of truth for tunables that
affect memory:

```python
EMBEDDING_MODEL_FALLBACK = "text-embedding-005"
EMBEDDING_MODEL          = EMBEDDING_MODEL_FALLBACK

INTERNAL_CONTEXT_KEYS = frozenset({
    "input", "cortex_tree_id", "subtree_root_id",
    "__memory__", "__cortex_viewport__", "__cortex_tree_id__",
    "__cortex_cursor__", "__cortex_knowledge__", "__context_sources__",
    "__episodic_memory__", "__semantic_context__", "__memory_context__",
    "__completed_steps__", "tool_call_counts", "company_id", "user_id",
    "__intelligence__", "__experience__", "__episodic__", "__knowledge_refs__",
    "__execution_metadata__", "__intelligence_rules__",
    "__alignment_correction__", "__goal_check_counter__",
})

MAX_REACT_TURNS                   = 12
CONTEXT_TOKEN_ESTIMATION_DIVISOR  = 4
MAX_CONTENT_CHARS                 = 50_000
MAX_CONTEXT_TRUNCATION_CHARS      = 6_000
CONTEXT_SUMMARIZE_THRESHOLD       = 20_000
DEFAULT_TIMEOUT_MS                = 60_000

DREAMING_CONSOLIDATION_INTERVAL_HOURS         = 24
DREAMING_MIN_EPISODES                         = 5
DREAMING_BATCH_SIZE                           = 20
DREAMING_OBSERVATION_CONFIDENCE_THRESHOLD     = 0.5
DREAMING_PATTERN_STRENGTH_THRESHOLD           = 0.7

GRAPH_SIMILARITY_THRESHOLD     = 0.85
GRAPH_MAX_AUTO_EDGES_PER_NODE  = 5
GRAPH_WEIGHT_DECAY_RATE        = 0.95
GRAPH_MIN_EDGE_WEIGHT          = 0.01
GRAPH_MAX_EXPANSION_DEPTH      = 2
```

Two distinct *internal key* sets serve different purposes:

| Set | File | Purpose |
|---|---|---|
| `INTERNAL_CONTEXT_KEYS` | `ai/constants.py` | Keys stripped from LLM prompts (avoid leaking bookkeeping into prompts) |
| `_SENSITIVE_CONTEXT_KEYS` | `ai/core/context_utils.py` | Keys redacted (by *substring match*: `api_key`, `secret`, `token`, ...) before persisting `context_state` to the `execution_runs.context_state` JSON column |

`sanitize_context_for_persistence(ctx)` is called whenever
`run.context_state` is persisted (on success, failure, and infrastructure
crashes).

---

## 18. Storage, Cost, and Performance Characteristics

| Resource | Cost dimension | Mitigation |
|---|---|---|
| `cortex_nodes.content` (`Text`) | Bytes stored per node | `content_tokens` cached; agents fetch via paged `read()` only on demand |
| `cortex_nodes.embedding` (`vector(768)`) | ~3 KB per node | Nullable; sparse storage by design |
| `cortex_edges.weight` | Self-trimming via `MIN_WEIGHT` | `prune_weak_edges` removes below threshold |
| pgvector indexes | Build cost; query cost is O(log N) IVF or O(N) brute | Implicit cosine index — assume IVFFlat or HNSW configured in DB |
| Recursive CTEs (`_build_breadcrumb`, `_is_descendant_of`, `expand_from_node`) | Single round-trip; cycle protection in graph BFS | Replaces O(depth) iterative parent walks (Phase-4 optimization) |
| LLM cost (bridge paragraphs, summaries, dreaming, ingestion) | Tracked via `UsageService.log_usage` per response | Logged with `model_name + in/out token counts`; aggregated into `ExecutionRun.total_cost_usd` |
| Viewport caching | Redis 30 s TTL | Non-fatal cache miss; reduces repeated navigation queries |
| Context size tracking | O(1) incremental via `update_context_size` | Replaces O(n) full-context scan |
| Re-clustering | Synchronous when triggered (`_schedule_reclustering`) | Logged as warning; could be moved async in future |

Database connection pool concerns: `db.refresh(run)` is called inside
the step loop to guard against `MissingGreenlet` errors caused by pool
recycling during long runs. UUIDs of `working_root_id`,
`_tree_output_root_id`, `_tree_id` are cached on locals **before** the
first session commit, since ORM-attribute access after `commit()`
expires those attributes.

---

## 19. Security, Multi-Tenancy & Isolation

| Boundary | Enforcement |
|---|---|
| **Tenant isolation** | Every CortexRouter call includes `company_id` (constructor); all SQL queries filter by `company_id`. `SemanticGraphService.semantic_graph_search` joins `cortex_trees ct` and asserts `ct.company_id = :company_id` |
| **Entity isolation** | `(ct.entity_id = :entity_id OR ct.scope_level IN ('app','tenant'))` — entities cannot read each other's runtime/episodic/experience/intelligence trees |
| **Subtree isolation for children** | `scoped_subtree_root_id` in `CortexRouter` raises `ValueError` for any node outside the subtree (recursive-CTE ancestry check) |
| **Sensitive context redaction** | `_SENSITIVE_CONTEXT_KEYS` strips substrings like `api_key`, `secret`, `token` before DB write |
| **Parent → child memory leak prevention** | `step_executor._execute_child_invocation` strips parent-scoped memory keys before invoking the child entity |
| **Null-byte sanitization** | `_safe_content = src_text.replace("\x00", "")` before writing to PostgreSQL UTF-8 columns |
| **Auth on REST endpoints** | All `/api/v1/cortex/*` routes require `current_user`; `company_id` is taken from the authenticated user, never from the request body |

The system does **not** currently enforce ACLs at the node level (i.e.
all nodes in a tree are readable by anyone who can reach the tree); the
unit of access is the tree itself.

---

## 20. Concurrency, Transactions, and Resume Semantics

### Transaction Boundaries

- The CORTEX router uses `db.flush()` between operations, batching
  changes inside the caller's transaction. The execution engine
  commits at well-defined boundaries (`db.commit()` after each
  `checkpoint`, after the final tree update, and at the end of the
  run).
- API endpoints commit after every mutation (`await db.commit()`).
- Background workers (`dreaming_worker`, `graph_maintenance_worker`)
  open their own `AsyncSessionLocal()` and commit at the end.

### Resume Semantics

The cursor field `tree.resume_cursor_id` is the **single source of
truth** for "where the agent is." Every `navigate`, `read`, and `write`
moves it. On resume:

1. `resume_tree(tree_id)` flips status to `ACTIVE`, navigates to
   `resume_cursor_id`, and loads the **latest checkpoint** under that
   cursor.
2. The execution engine pulls `__completed_steps__` from the previous
   run's `context_state` (sanitized for persistence) into a set; steps
   whose `step_id` is in this set are skipped (`Skipping
   already-completed step`).
3. The next checkpoint window starts from the resumption point.

This makes resumption **idempotent and deterministic** at the
step-granularity.

### Concurrent Writes

Two concurrent writes under the same parent are serialized by
PostgreSQL row-level locks on the parent and (effectively) by the
`sibling_order` `MAX + 1` query. No SELECT FOR UPDATE is used today; the
race is small but not formally prevented.

---

## 21. Observability & Diagnostics

| Signal | Where |
|---|---|
| `logger.info` on tree create/resume/suspend, checkpoint, ingest | `CortexRouter` and `CortexBridge` |
| LLM cost tracking | `CortexBridge._generate_summary` → `UsageService.log_usage`; `CortexRouter._generate_bridge_paragraphs` logs token counts |
| Dreaming counters | `dream()` returns `{observations_created, patterns_created, rules_created}` |
| Graph statistics | `SemanticGraphService.get_graph_stats()` returns per-edge-type counts and weight stats |
| Access tracking | `cortex_nodes.access_count`, `last_accessed_at`; `cortex_edges.traversal_count`, `last_traversed_at` |
| Importance | `cortex_nodes.importance_score` (Decimal, default 0.500); used by dreaming engine for observations |
| Execution metadata | `context_state["__execution_metadata__"] = {engine_type, memory_pipeline, memory_scope, total_steps, autonomous}` |
| Provenance | `metadata_extra.provenance_chain` on knowledge nodes (e.g. `"scraper_tool→cortex_bridge"`) |

---

## 22. End-to-End Sequence Diagrams

### A) Cold-start execution with v2 memory

```
User Request
   │
   ▼
ExecutionEngine.execute_run
   │
   ├─ C1: cortex.create_tree(entity, user, task_desc)
   │      └─ inserts: ROOT, 📚 Knowledge, 🔬 Working, 📝 Output
   │
   ├─ C2: assemble_memory(pipeline="v2", scope="FULL")
   │      ├─ SemanticGraphService.semantic_graph_search(knowledge)
   │      ├─ SemanticGraphService.semantic_graph_search(experience)
   │      ├─ IntelligenceTreeService.get_applicable_rules
   │      └─ EpisodicTreeService.get_recent_episodes + query_by_topic
   │
   ├─ C3: context_state[__cortex_viewport__] = viewport.to_prompt_text()
   │      + load context_sources, auto-ingest into knowledge_root
   │
   ├─ C4: working_root = cortex.get_working_root(tree.id)
   │
   ├─ C5: for step in plan.steps:
   │        ├─ if step.type ∈ {NAVIGATE,READ,WRITE,RECURSE,AWAIT_CHILDREN}:
   │        │     bridge.execute_cortex_step(...)
   │        ├─ else:
   │        │     step_executor._execute_step_wrapper(...)
   │        │       └─ if TOOL_CALL: bridge.ingest_tool_result(...)
   │        ├─ bridge.write_step(cortex, working_root_id, sr, run_id)
   │        ├─ bridge.refresh_viewport(cortex, tree, context_state)  ── Redis cache
   │        └─ every N: bridge.write_checkpoint(...) + db.commit()
   │
   ├─ cortex.write(parent=output_root, node_type="output", content=final)
   ├─ MemoryRouter(db).write_episodic(run)   # dual-write episodic + tree
   ├─ tree.last_active_at = now()             # tree stays ACTIVE
   ├─ db.commit()
   └─ Governance.settle_billing(run, entity.name)
```

### B) Background Dreaming pipeline

```
arq.dreaming_worker(entity_id, company_id, force=False)
   └─ DreamingEngine(db, company_id).dream(entity_id, force):
        ├─ _should_run(entity_id):
        │   experience.last_consolidated_at older than 24 h? else skip.
        │
        ├─ Phase 1: _extract_observations(entity_id)
        │   ├─ EpisodicTreeService.query_by_time(last_consolidated, now, limit=20)
        │   ├─ if episodes < 5: return []
        │   ├─ LLM(OBSERVATION_EXTRACTION_PROMPT, episodes JSON)
        │   ├─ parse JSON array → filter confidence ≥ 0.5
        │   └─ write OBSERVATION nodes; embed each
        │
        ├─ Phase 2: _recognize_patterns(entity_id)
        │   ├─ load observations; cluster cosine > 0.75
        │   ├─ for each cluster ≥2:
        │   │     LLM(PATTERN_RECOGNITION_PROMPT)
        │   │     write PATTERN node; embed
        │   │     for each source obs: edge derived_from(weight = 1/|cluster|)
        │   └─ ...
        │
        ├─ Phase 3: _distill_intelligence(entity_id)
        │   ├─ get_strong_patterns(strength≥0.7, recurrence≥2)
        │   ├─ existing_rules → de-dup hint
        │   ├─ LLM(INTELLIGENCE_DISTILLATION_PROMPT, {patterns, existing_rules})
        │   ├─ parse rules → write INSTRUCTION/STRATEGY/PREFERENCE
        │   └─ embed each; bump consolidation_generation
        │
        └─ _update_consolidation_timestamp(experience_tree)
```

### C) Document upload → dual-write knowledge ingestion

```
HTTP POST /api/v1/documents/upload  (file bytes)
   ▼
process_document(ctx, doc_id, file_content, file_type, filename) [arq]
   ├─ parse file → text
   ├─ chunk text (500 chars)
   ├─ EmbeddingService.embed_text(...) for each chunk
   ├─ INSERT INTO document_chunks (content, embedding)
   ├─ document.upload_status = completed/partial/failed
   └─ if document.entity_id:
        KnowledgeTreeService.get_or_create_knowledge_tree(entity_id)
        KnowledgeTreeService.ingest_document(tree.id, doc.id, text, filename)
        # → builds DOCUMENT → SECTION → CHUNK with embeddings
```

### D) RECURSE → child run isolation

```
Parent run, step.type = RECURSE
   ▼
bridge.execute_cortex_step → cortex.recurse(node_id, task, result_slot)
   ├─ cortex.write(parent_id=node_id, node_type=task, content={task,scoped_to,result_slot})
   ├─ ExecutionRun(parent_run_id=current, input_data={cortex_tree_id, subtree_root_id})
   └─ arq.enqueue_job("execute_run", str(child_run_id))
              │
              ▼
Child run picks up: cortex = CortexRouter(db, company_id,
                                          scoped_subtree_root_id=subtree_root_id)
   ├─ Any attempt to navigate/read/write outside subtree → ValueError
   └─ On completion, parent does cortex.await_children(cursor) → collects results
```

---

## 23. Known Issues, Gaps, and Forward Roadmap

(Mirrors `docs/phase10/05_memory_architecture.md` and adds findings
from this audit.)

| # | Issue | Severity |
|---|---|---|
| 1 | `MemoryAssemblyService` (v2) is implemented but the default pipeline is still `v1` (set per-entity via `memory.memory_pipeline`) | P1 |
| 2 | Dreaming engine has **no automatic trigger** — `dreaming_worker` must be enqueued explicitly; no post-run hook chains it after `MemoryRouter.write_episodic` | P0 |
| 3 | `_cluster_observations` is greedy O(n²) — degrades past a few hundred observations | P2 |
| 4 | No de-duplication in observation/pattern/rule extraction beyond LLM-prompt hints | P2 |
| 5 | `LLMRouter` instantiated three times per `dream()` call (once per phase) | P2 |
| 6 | `RUN_SCOPED` memory scope is identical to `FULL` (filter not implemented) | P1 |
| 7 | `CortexBridge.execute_cortex_step` instantiates `ArqRedis(self.redis.client if hasattr(self,'redis') else None)` — fragile path, may break under non-`aioredis` clients | P2 |
| 8 | Re-clustering runs synchronously during `write()`; could block step execution under high write pressure | P2 |
| 9 | `INTERNAL_CONTEXT_KEYS` and `_SENSITIVE_CONTEXT_KEYS` serve distinct purposes but their naming overlaps | P3 |
| 10 | `cortex_resume_scheduled` cron has wide schedule (every 5 min); under load the same suspended tree could be processed in overlapping cycles. `next_resume_at = NULL` is the only guard | P2 |
| 11 | No quality gate on Intelligence rules (low-confidence rules pollute the Intelligence tree if the LLM produces them) | P2 |
| 12 | `tree.status = "active"` after success — never moves to `complete`. Long-term, archive sweeps need to be designed | P2 |
| 13 | No node-level ACLs — the unit of access is the tree | Design-as-is |
| 14 | No formal lock between concurrent writes under the same parent; `MAX(sibling_order)+1` races possible | P3 |

---

## 24. Glossary

| Term | Definition |
|---|---|
| **CORTEX** | Cognitive Orchestrated Recursive Tree EXecution — the umbrella name for the memory substrate |
| **Tree** | A `CortexTree` row + its `CortexNode` rows; the unit of cognitive state |
| **Node** | A `CortexNode` row — any addressable piece of information |
| **Viewport** | What the agent sees: current node + children summaries + parent + breadcrumb + ops |
| **Cursor** | `tree.resume_cursor_id` — the node the agent is "at" |
| **Subtree anchor** | Direct child of root (Knowledge / Working / Output) — created on `create_tree` |
| **Working memory** | The 🔬 subtree where step `finding` nodes are written |
| **Knowledge base** | The 📚 subtree where ingested/referenced knowledge lives within a runtime tree |
| **Output canvas** | The 📝 subtree assembled into the run's final output |
| **Episode** | One row in the persistent Episodic Tree representing a completed run |
| **Observation** | LLM-extracted insight about an episode (Experience.Observations) |
| **Pattern** | Clustered observations synthesized into a recurring pattern (Experience.Patterns) |
| **Rule (Intelligence)** | Actionable instruction/strategy/preference distilled from patterns |
| **Domain** | One of `knowledge / episodic / experience / intelligence` |
| **Scope** | Six-level hierarchy `app / partner / tenant / user / entity / runtime` |
| **Dreaming** | Background consolidation pipeline: episodes → observations → patterns → rules |
| **Bridge** | `CortexBridge` — the execution engine's single point of contact with CORTEX |
| **Semantic graph** | The `cortex_edges` overlay enabling associative cross-tree search |
| **Memory Pipeline v1/v2** | v1 = `MemoryRouter` (3 tiers); v2 = `MemoryAssemblyService` (4 domains) |
| **Memory Scope** | Per-entity flag: `FULL / RUN_SCOPED / INTELLIGENCE_ONLY / KNOWLEDGE_ONLY / NONE` |

---

## 25. File Map / Source Index

```
backend/src/ai/
├── memory/
│   ├── __init__.py                      # Public API: CortexRouter, CortexBridge, MemoryRouter, MemoryAssemblyService
│   ├── cortex_models.py                 # ORM: CortexTree, CortexNode, CortexEdge + 5 enums
│   ├── cortex_service.py                # CortexRouter — 7 CORTEX operations
│   ├── cortex_bridge.py                 # CortexBridge — execution engine interface
│   ├── cortex_router.py                 # FastAPI HTTP endpoints under /api/v1/cortex
│   ├── cortex_ingestion.py              # CortexIngestionPipeline — runtime-tree document ingest
│   ├── memory_service.py                # MemoryRouter v1 — 3-tier retrieval + dual-write episodic
│   ├── memory_assembly_service.py       # MemoryAssemblyService v2 — 4-domain assembly
│   ├── assembler.py                     # assemble_memory façade routing v1/v2 by entity config
│   ├── knowledge_tree_service.py        # KnowledgeTreeService — persistent KB + DOCUMENT/SECTION/CHUNK
│   ├── episodic_tree_service.py         # EpisodicTreeService — Month/Day/Episode hierarchy
│   ├── experience_tree_service.py       # ExperienceTreeService — Observation/Pattern/Suggestion
│   ├── intelligence_tree_service.py     # IntelligenceTreeService — Instruction/Strategy/Preference
│   ├── graph_service.py                 # SemanticGraphService — edges, BFS, hybrid search
│   ├── embedding_service.py             # EmbeddingService — model resolution + batched embed
│   ├── dreaming_engine.py               # DreamingEngine — 3-phase consolidation
│   └── dreaming_prompts.py              # Prompts for the 3 dreaming phases
├── constants.py                          # EMBEDDING_MODEL, INTERNAL_CONTEXT_KEYS, GRAPH_*, DREAMING_*
├── failure_pattern_service.py            # Keyword classifier over FAILED runs (Intelligence-derived)
├── models.py                             # Legacy: EpisodicMemory, Document, DocumentChunk
├── core/
│   ├── execution_engine.py               # ExecutionEngine.execute_run — phases C1–C5 + CORTEX integration
│   ├── arq_jobs.py                       # arq jobs: dreaming_worker, graph_maintenance_worker,
│   │                                     #          cortex_resume_scheduled, resume_execution, process_document
│   └── context_utils.py                  # store_step_output, sanitize_context_for_persistence
├── step_executor.py                      # StepExecutorService — tool calls invoke bridge.ingest_tool_result
├── worker.py                             # arq WorkerSettings + cron registration
└── schemas.py                            # StepType enum (incl. NAVIGATE/READ/WRITE/RECURSE/AWAIT_CHILDREN);
                                          # CortexTreeCreate, CortexNodeCreate, CortexCheckpointCreate, etc.

# Backward-compat shims (deprecated direct imports — all re-export from memory/*):
backend/src/ai/cortex_service.py, cortex_bridge.py, cortex_router.py,
backend/src/ai/cortex_models.py, cortex_ingestion.py, memory_service.py,
backend/src/ai/dreaming_engine.py, dreaming_prompts.py, embedding_service.py,
backend/src/ai/knowledge_tree_service.py, episodic_tree_service.py,
backend/src/ai/experience_tree_service.py, intelligence_tree_service.py,
backend/src/ai/graph_service.py, memory_assembly_service.py
```

---

*End of CORTEX Memory System Architecture document.*
