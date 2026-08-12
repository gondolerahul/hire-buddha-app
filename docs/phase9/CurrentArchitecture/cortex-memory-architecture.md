# CORTEX Memory System Architecture

**Version**: 1.0  
**Phase**: 9 — Deep Architecture Documentation  
**Date**: 2026-05-14  
**Status**: Authoritative Reference

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Design Philosophy & Rationale](#2-design-philosophy--rationale)
3. [Three-Tier Memory Architecture](#3-three-tier-memory-architecture)
4. [Core Data Model](#4-core-data-model)
5. [The Seven CORTEX Operations](#5-the-seven-cortex-operations)
6. [Viewport Navigation Model](#6-viewport-navigation-model)
7. [Tree Lifecycle Management](#7-tree-lifecycle-management)
8. [Recursive Execution (RLM)](#8-recursive-execution-rlm)
9. [Compaction & Checkpointing](#9-compaction--checkpointing)
10. [Knowledge Ingestion Pipeline](#10-knowledge-ingestion-pipeline)
11. [Memory Router Integration](#11-memory-router-integration)
12. [Worker Integration & Execution Flow](#12-worker-integration--execution-flow)
13. [Data Invariants & Constraints](#13-data-invariants--constraints)
14. [Performance Optimizations](#14-performance-optimizations)
15. [Voice Channel Memory](#15-voice-channel-memory)
16. [Database Schema & Migrations](#16-database-schema--migrations)
17. [Configuration Constants](#17-configuration-constants)
18. [Design Trade-offs & Decisions](#18-design-trade-offs--decisions)
19. [Gap Analysis & Future Work](#19-gap-analysis--future-work)

---

## 1. Executive Summary

CORTEX (**C**ognitive **O**rchestrated **R**ecursive **T**ree **EX**ecution) is HireBuddha's proprietary memory system for long-running agentic AI tasks. It replaces the traditional unbounded context window approach with a **navigable, hierarchical, paged cognitive tree** stored in PostgreSQL.

### Core Innovation

Traditional LLM agents accumulate context linearly until they hit the model's context window limit, at which point information is silently lost. CORTEX solves this by:

1. **Externalizing all agent cognition** into a persistent tree structure
2. **Constraining visibility** through a viewport (one-level slice) rather than full-tree dumps
3. **Enabling recursive delegation** where child agents operate on isolated subtrees
4. **Supporting multi-session resumption** via checkpoint/resume cursor semantics

### Source Files

| File | Lines | Purpose |
|------|-------|---------|
| `cortex_service.py` | 1,110 | Core engine — 7 operations, tree lifecycle, CTE queries |
| `cortex_models.py` | 189 | ORM models — `CortexTree`, `CortexNode` |
| `cortex_bridge.py` | 556 | Execution bridge — step writing, viewport refresh, tool ingestion |
| `cortex_router.py` | 314 | FastAPI REST endpoints |
| `cortex_ingestion.py` | 215 | Document → hierarchical node transformation |
| `memory_service.py` | 410 | Three-tier router (Working → Episodic → Semantic) |
| `constants.py` | 54 | Internal context keys, embedding model, execution limits |

---

## 2. Design Philosophy & Rationale

### 2.1 Why Not Just Use a Longer Context Window?

**Problem**: Even with 200K+ token context windows, agents performing multi-step research tasks (web scraping, document analysis, report synthesis) generate 500K–2M tokens of intermediate data. Linear context accumulation fails because:

- **Token cost scales quadratically** with attention-based models
- **Information recall degrades** in long contexts (the "lost in the middle" problem)
- **No resumability** — if a run crashes at step 47 of 50, all context is lost
- **No parallelism** — two sub-agents cannot work on different aspects simultaneously

**CORTEX Solution**: Model agent memory as a **navigable tree** where:
- The agent only sees a **bounded viewport** (~480 tokens max) at any time
- Full content is accessible on-demand via paged READ operations
- Progress is checkpointed to PostgreSQL, enabling crash recovery
- Subtrees can be delegated to child agents with enforced isolation

### 2.2 Design Principles

| Principle | Implementation | Rationale |
|-----------|---------------|-----------|
| **Viewport-First** | Agent receives `Viewport` (current + children summaries), never the full tree | Bounds token cost to O(MAX_CHILDREN × 40) per step |
| **Write-Once Content** | `_create_node()` sets content at creation; revisions are child nodes | Prevents destructive edits; enables audit trail |
| **Summary Always Exists** | Invariant 1: parent must have summary before accepting children | Ensures viewport navigation quality without reading full content |
| **Bounded Fanout** | MAX_CHILDREN=12 default; exceeded → async re-clustering | Prevents viewport explosion; keeps navigation manageable |
| **Subtree Isolation** | `scoped_subtree_root_id` enforced in `_get_node()` | Child runs cannot read/write outside their designated branch |
| **Context Budget** | `context_budget_pct=40` triggers auto-compaction | Prevents unbounded context growth during execution |

### 2.3 Architectural Inspiration

CORTEX draws from three established paradigms:

1. **PageIndex (filesystem navigation)**: Agents navigate trees like a filesystem — `NAVIGATE` is `cd`, `READ` is `cat`, `WRITE` is `touch/echo`
2. **Recursive Language Models (RLM)**: The `RECURSE` operation spawns isolated child executions, analogous to function calls with scoped stack frames
3. **Git's content-addressable store**: Content is immutable once written; "edits" create new nodes (revisions), preserving full history

---

## 3. Three-Tier Memory Architecture

The memory system operates across three tiers, orchestrated by `MemoryRouter` (`memory_service.py`):

```
┌─────────────────────────────────────────────────────────┐
│                    MemoryRouter                          │
│               (memory_service.py)                        │
│                                                          │
│  retrieve(entity_id, user_id, query, tree_id, ...)      │
│         │                                                │
│         ├── Tier 1: WORKING MEMORY (CORTEX Viewport)     │
│         │   └── cortex_service.py → navigate(cursor)     │
│         │                                                │
│         ├── Tier 2: EPISODIC MEMORY (Past Runs)          │
│         │   └── episodic_memories table (last 5 runs)    │
│         │                                                │
│         └── Tier 3: SEMANTIC MEMORY (Vector Search)      │
│             └── document_chunks + pgvector cosine sim    │
└─────────────────────────────────────────────────────────┘
```

### 3.1 Tier 1: Working Memory (CORTEX Viewport)

**When active**: During `long_running=True` executions (all CORTEX-enabled runs).

**What it provides**: A `Viewport` object containing:
- Current node's title, summary, status, depth
- Direct children's titles and summaries (max 12)
- Parent node reference
- Breadcrumb path from root to current position

**Injected as**: `context_state["__cortex_viewport__"]` — the rendered `to_prompt_text()` output.

**Token cost**: ~40 tokens per child × 12 children + overhead ≈ **~600 tokens max**.

**Design rationale**: The viewport is the agent's "field of vision." By constraining it to one level of the tree, we ensure the agent must explicitly navigate to access information, which:
- Forces deliberate information retrieval (no accidental context pollution)
- Keeps per-step LLM costs predictable
- Creates a natural audit trail of what the agent examined

### 3.2 Tier 2: Episodic Memory (Past Run Summaries)

**When active**: Always, for entities with prior execution history.

**What it provides**: Summaries of the last 5 completed execution runs for the same entity+user pair.

**Source**: `episodic_memories` table, populated by `MemoryRouter.write_episodic(run)` at run completion.

**Schema** (per record):
```
id, entity_id, company_id, user_id, run_id,
input_summary, output_summary, status,
total_cost_usd, total_tokens, execution_time_ms,
metadata_info (JSON), channel, tree_id, created_at
```

**Injected as**: `context_state["__memory__"]` via `format_for_prompt()`.

**Design rationale**: Episodic memory gives agents awareness of their own history. A research agent that previously analyzed "Q2 revenue trends" can reference that prior run when asked to do "Q3 analysis," avoiding redundant work and maintaining continuity.

### 3.3 Tier 3: Semantic Memory (Vector Search)

**When active**: When a `query` parameter is provided to `MemoryRouter.retrieve()`.

**What it provides**: Top-K semantically similar document chunks from the company's knowledge base.

**Implementation**:
1. Query is embedded using `gemini-embedding-004` via Vertex AI
2. Cosine similarity search against `document_chunks.embedding` (pgvector)
3. Results filtered by `company_id` ownership
4. Top 5 chunks returned with similarity scores

**Injected as**: Part of the `__memory__` or `__semantic_context__` context key.

**Design rationale**: Semantic memory enables agents to access company-specific knowledge (uploaded documents, past reports) without requiring the full document in context. The vector search provides relevance-ranked retrieval, and the `RETRIEVAL_QUERY` task type in the embedding model optimizes for question-answering scenarios.

### 3.4 Tier Interaction & Priority

```python
# memory_service.py — retrieve() method flow:
async def retrieve(self, entity_id, user_id=None, query=None,
                   tree_id=None, long_running=False, top_k=5):

    ctx = MemoryContext()

    # 1. CORTEX viewport (Tier 1) — only for long-running tasks
    if long_running and tree_id:
        viewport = await self._get_cortex_viewport(tree_id, entity_id)
        ctx.cortex_viewport = viewport

    # 2. Episodic memory (Tier 2) — always loaded
    ctx.episodic = await self._get_episodic(entity_id, user_id, limit=5)

    # 3. Semantic search (Tier 3) — only if query provided
    if query:
        ctx.semantic = await self._semantic_search(entity_id, query, top_k)

    return ctx
```

The tiers are **additive, not exclusive**. A long-running CORTEX execution receives all three tiers simultaneously, with the viewport providing the most immediate/actionable context.

---

## 4. Core Data Model

### 4.1 CortexTree (cortex_models.py)

The tree is the top-level container for a cognitive task. One tree per execution run.

```python
class CortexTree(Base):
    __tablename__ = "cortex_trees"

    id: UUID                    # Primary key
    entity_id: UUID             # FK → hierarchical_entities (the agent)
    user_id: UUID               # FK → users (who triggered the run)
    company_id: UUID            # FK → companies (tenant isolation)

    task_description: str       # Human-readable task summary
    status: CortexTreeStatus    # active | suspended | complete | archived

    # Structural pointers
    total_nodes: int            # Counter for total nodes in tree
    root_node_id: UUID          # FK → cortex_nodes (tree root)
    output_root_id: UUID        # FK → cortex_nodes (output subtree anchor)
    resume_cursor_id: UUID      # FK → cortex_nodes (where to resume)

    # Configuration
    max_children: int = 12      # Viewport fanout limit (Invariant 2)
    page_size_tokens: int = 8000  # Content pagination unit
    context_budget_pct: int = 40  # % of model window before compaction

    # Scheduling (Gap #5)
    resume_schedule: str        # Cron-like schedule for multi-day tasks
    next_resume_at: datetime    # Next scheduled wake-up time

    # Timestamps
    created_at: datetime
    last_active_at: datetime
```

**Design decisions**:

- **`resume_cursor_id`**: Acts as a bookmark. When a run crashes or is suspended, the next `resume_tree()` call navigates to this cursor, enabling seamless continuation. Updated on every `navigate()`, `read()`, and `write()` operation.

- **`output_root_id`**: Separates output from working memory. The `assemble_output()` method performs DFS only on this subtree, cleanly producing the final deliverable without traversing intermediate findings.

- **`context_budget_pct=40`**: The tree claims at most 40% of the model's context window. This leaves 60% for system prompt, tools, episodic memory, and the user's current instruction.

### 4.2 CortexNode (cortex_models.py)

The fundamental unit of the cognitive tree.

```python
class CortexNode(Base):
    __tablename__ = "cortex_nodes"

    id: UUID                    # Primary key
    tree_id: UUID               # FK → cortex_trees (CASCADE delete)
    parent_id: UUID             # FK → self (SET NULL on delete)

    node_type: CortexNodeType   # root|knowledge|finding|task|output|checkpoint
    title: str(500)             # Navigation-quality label
    summary: Text               # ~200 token summary for viewport display
    content: Text               # Full content (paged on read)
    content_tokens: int = 0     # Estimated token count (len/4)

    status: CortexNodeStatus    # pending|active|complete|summarised
    source_ref: JSONB           # {"url": "...", "tool": "scraper_tool"}
    execution_run_id: UUID      # FK → execution_runs

    depth: int = 0              # Distance from root
    sibling_order: int = 0      # Position among siblings

    metadata_extra: JSONB       # Extensible metadata
    created_at: datetime
    updated_at: datetime
```

**Node Type Semantics**:

| Type | Purpose | Created By |
|------|---------|------------|
| `root` | Tree entry point | `create_tree()` — exactly one per tree |
| `knowledge` | Ingested documents, scraped content | `cortex_ingestion.py`, tool result ingestion |
| `finding` | Agent's intermediate reasoning/discoveries | Step execution via `write_step()` |
| `task` | Delegated sub-task for recursive execution | `recurse()` operation |
| `output` | Final deliverable sections | Agent WRITE operations |
| `checkpoint` | Progress snapshot for resumption | `checkpoint()` / auto-compaction |

**Status Lifecycle**:

```
pending → active → complete → summarised
   │                              ↑
   └──────────────────────────────┘
        (direct for ingested nodes)
```

- `pending`: Created but not yet read/processed
- `active`: Currently being worked on (reading or writing children)
- `complete`: Content finalized
- `summarised`: Content compacted; only summary retained (future optimization)

### 4.3 Initial Tree Structure

Every `create_tree()` call produces this 4-node scaffold:

```
Task: {description}          [root, depth=0]
├── 📚 Knowledge Base        [knowledge, depth=1, sibling_order=0]
├── 🔬 Working Memory        [finding, depth=1, sibling_order=1]
└── 📝 Output                [output, depth=1, sibling_order=2]
```

**Why three subtrees?**

1. **Knowledge Base** (sibling_order=0): Stores all ingested external data — scraped web pages, uploaded documents, context sources. Separating knowledge from findings prevents the agent from confusing "what it was told" with "what it discovered."

2. **Working Memory** (sibling_order=1): Stores the agent's intermediate reasoning — step outputs, tool results, reflections. This is the agent's "scratch pad" that grows during execution.

3. **Output** (sibling_order=2): Stores the final deliverable sections. The `assemble_output()` method only traverses this subtree, producing a clean final document without intermediate noise.

This separation mirrors how human researchers work: reference materials (knowledge), notes and analysis (working memory), and the final report (output).

### 4.4 EpisodicMemory (models.py)

```python
class EpisodicMemory(Base):
    __tablename__ = "episodic_memories"

    id: UUID
    entity_id: UUID             # Which agent created this memory
    company_id: UUID            # Tenant isolation
    user_id: UUID               # Which user's context
    run_id: UUID                # FK → execution_runs
    tree_id: UUID               # FK → cortex_trees (links memory to tree)

    input_summary: Text         # What was asked
    output_summary: Text        # What was produced
    status: str(50)             # Run completion status
    total_cost_usd: str(20)     # Execution cost
    total_tokens: int           # Total tokens consumed
    execution_time_ms: int      # Wall-clock time
    metadata_info: JSON         # Extensible metadata
    channel: str(50)            # "text", "voice", "webhook"
    created_at: datetime
```

**Design rationale for `tree_id` FK**: Links episodic memories back to their CORTEX tree, enabling future features like "resume a previous research session" by loading the tree associated with an episodic memory.
