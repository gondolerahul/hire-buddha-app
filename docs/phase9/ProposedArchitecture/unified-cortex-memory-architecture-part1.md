# Unified CORTEX Memory Architecture v2.0

**Version**: 2.0  
**Phase**: 9 — Unified Memory Architecture  
**Date**: 2026-05-15  
**Status**: Architecture Proposal  
**Supersedes**: cortex-memory-architecture.md (v1.0)

---

## Table of Contents (Across All Parts)

**Part 1 (this file):**
1. Executive Vision
2. Neuroscience-Inspired Design Philosophy
3. The Four Memory Domains
4. The Six Hierarchical Scoping Levels
5. Unified Core Primitives — CortexTree & CortexNode v2
6. Memory Silo Matrix (4 Domains × 6 Levels)

**Part 2:**
7. Knowledge Domain — Deep Architecture
8. Experience Domain — Deep Architecture
9. Intelligence Domain — Deep Architecture
10. Episodic Domain — Deep Architecture
11. The Semantic Graph Layer (Novel Search Architecture)

**Part 3:**
12. The Learning Algorithm ("Dreaming Process")
13. Runtime Memory Assembly Pipeline
14. Agent Memory Access Protocol
15. Risk Analysis & Feasibility Assessment
16. Migration Strategy from v1.0
17. Database Schema Evolution

---

## 1. Executive Vision

### 1.1 The Problem With v1.0

The current CORTEX system has a **fragmented memory landscape**:

| Memory Type | Storage | Search | Lifecycle | Shared? |
|-------------|---------|--------|-----------|---------|
| Working Memory | CORTEX trees (PostgreSQL) | Tree traversal only | Per-execution | No |
| Episodic Memory | Flat table (`episodic_memories`) | Sequential scan, last-N | Permanent, pruned at 10 | No cross-entity |
| Knowledge Base | `documents` + `document_chunks` | pgvector cosine similarity | Permanent | Per-company only |

**Key deficiencies:**
- Three different storage paradigms for three memory types
- No Experience or Intelligence memory at all
- No hierarchical scoping (APP → PARTNER → TENANT → USER → ENTITY → RUNTIME)
- No learning from past executions
- Knowledge and episodic memory cannot leverage CORTEX's tree navigation
- Vector search is disconnected from tree context
- No cross-level knowledge inheritance

### 1.2 The v2.0 Vision: One Brain, One Structure

**Everything is a CORTEX Tree.**

```
┌──────────────────────────────────────────────────────────────┐
│                    UNIFIED CORTEX MEMORY                      │
│                                                               │
│  ┌─────────┐  ┌────────────┐  ┌──────────────┐  ┌─────────┐ │
│  │KNOWLEDGE│  │ EXPERIENCE │  │ INTELLIGENCE │  │EPISODIC │ │
│  │  Trees  │  │   Trees    │  │    Trees     │  │  Trees  │ │
│  └────┬────┘  └─────┬──────┘  └──────┬───────┘  └────┬────┘ │
│       │             │                │                │      │
│       └─────────────┴────────────────┴────────────────┘      │
│                           │                                   │
│                    Unified CortexNode v2                      │
│              (with embedded semantic vectors)                 │
│                           │                                   │
│              ┌────────────┴────────────┐                     │
│              │   Semantic Graph Layer  │                     │
│              │  (weighted edges +      │                     │
│              │   traversal frequency)  │                     │
│              └─────────────────────────┘                     │
└──────────────────────────────────────────────────────────────┘
```

Every piece of information — documents, past run summaries, learned patterns, distilled instructions, runtime findings — lives as a **CortexNode** inside a **CortexTree**, queryable through both **tree traversal** and **semantic graph search**.

---

## 2. Neuroscience-Inspired Design Philosophy

The unified architecture maps directly to how the human brain organizes memory:

### 2.1 Brain-to-CORTEX Mapping

| Human Brain | CORTEX v2 | Function |
|-------------|-----------|----------|
| **Neocortex** (Knowledge) | Knowledge Trees | Factual knowledge, documents, data — "what I know" |
| **Hippocampus** (Episodic) | Episodic Trees | Autobiographical records of past events — "what happened" |
| **Cerebellum** (Experience) | Experience Trees | Procedural patterns, observations, cause-effect — "what I've learned from doing" |
| **Prefrontal Cortex** (Intelligence) | Intelligence Trees | Distilled rules, strategies, instructions — "what I should do" |
| **Sleep/Dreaming** | Learning Algorithm | Consolidation, pattern extraction, memory strengthening |
| **Synapses** | Semantic Graph Edges | Weighted connections between concepts across trees |
| **Attention** | Viewport + Semantic Search | Focused retrieval from the right memory at the right time |
| **Memory Hierarchy** (working → short-term → long-term) | Runtime → Entity → User → Tenant → Partner → App | Scope and persistence levels |

### 2.2 Key Biological Principles Adopted

1. **Consolidation through sleep (Dreaming Process):** The brain strengthens memories during sleep by replaying experiences. Our Learning Algorithm runs as scheduled background processes that extract patterns from raw executions → Experience, and distill instructions from Experience → Intelligence.

2. **Hierarchical memory scoping:** The brain organizes memories at different levels — personal episodic, learned skills, cultural knowledge. Our 6-level hierarchy mirrors this: what an individual entity learns (Entity-level), what patterns emerge across a user's entities (User-level), what a company collectively knows (Tenant-level), etc.

3. **Associative recall through synaptic connections:** The brain doesn't search linearly — it activates related memories through neural connections. Our Semantic Graph Layer provides weighted edges between nodes, enabling associative retrieval.

4. **Zero information loss:** The brain doesn't delete memories — it weakens connections to irrelevant ones. We never delete data; instead, we adjust access frequency weights and traversal priority scores.

---

## 3. The Four Memory Domains

### 3.1 Knowledge — "What I Know"

**Definition:** Factual information, documents, reference data, and structured content that exists independent of any execution.

**Contents:**
- Uploaded documents (PDFs, DOCX, TXT, spreadsheets)
- Web-scraped content and research findings
- System metadata for meta-agents
- Company policies, product manuals, HR handbooks
- API documentation, integration guides
- Any data ingested from SharePoint, Google Drive, network drives, etc.

**Key characteristic:** Knowledge is **input data** — it was not generated by the agent's reasoning. It is objective, factual, and referenceable.

### 3.2 Experience — "What I've Learned From Doing"

**Definition:** Observations, patterns, cause-effect relationships, and reasoning traces extracted from past executions. Experience captures *why* things happened, not just *what* happened.

**Contents:**
- "When the user asked about Q2 revenue, web scraping was more effective than document search"
- "This entity consistently fails when given ambiguous input — adding clarification steps improved success rate from 60% to 95%"
- "The HR policy document required 3 READ operations to find the remote work section — creating a section-level index reduced this to 1"
- Failure patterns, success patterns, efficiency observations
- Suggestions and alternatives to try next time

**Key characteristic:** Experience is **extracted from raw execution data** through the Learning Algorithm. It contains observations + the reasoning behind them.

### 3.3 Intelligence — "What I Should Do"

**Definition:** Distilled, actionable instructions and strategies derived from accumulated Experience. Intelligence is the crystallized wisdom that directly guides future behavior.

**Contents:**
- "Always check the company's fiscal year calendar before analyzing revenue data"
- "For this user, prefer detailed tables over narrative summaries"
- "When entity X is invoked for research, always start with the company's internal knowledge base before web search"
- Decision rules, priority orderings, constraint specifications
- User preferences, behavioral patterns

**Key characteristic:** Intelligence is **derived from Experience** through a second pass of the Learning Algorithm. It is prescriptive, not descriptive — it tells the agent what to DO, not what it observed.

### 3.4 Episodic — "What Happened"

**Definition:** A chronological record of every execution run, serving as the raw autobiographical memory of the agent system.

**Contents:**
- Input/output summaries of each run
- Execution metadata (cost, tokens, time, status)
- Links to the runtime CORTEX tree for deep-dive
- Tool usage records
- Error traces and recovery actions

**Key characteristic:** Episodic memory is the **raw journal** — it preserves what happened without interpretation. It serves as the source data for the Learning Algorithm to extract Experience, and as a lightweight index for agents to recall past runs.

---

## 4. The Six Hierarchical Scoping Levels

Memory exists at six hierarchical levels, each serving a different scope of accessibility and consolidation:

```
┌────────────────────────────────────────────────────────┐
│  Level 0: GLOBAL APP                                   │
│  (System-wide: meta-agent metadata, platform knowledge)│
│  ┌──────────────────────────────────────────────────┐  │
│  │  Level 1: PARTNER                                │  │
│  │  (Partner-wide: shared across partner's tenants) │  │
│  │  ┌────────────────────────────────────────────┐  │  │
│  │  │  Level 2: TENANT (Company)                 │  │  │
│  │  │  (Company-wide: docs, policies, knowledge) │  │  │
│  │  │  ┌──────────────────────────────────────┐  │  │  │
│  │  │  │  Level 3: USER                       │  │  │  │
│  │  │  │  (User-specific: preferences, hx)    │  │  │  │
│  │  │  │  ┌────────────────────────────────┐  │  │  │  │
│  │  │  │  │  Level 4: ENTITY (Agent)       │  │  │  │  │
│  │  │  │  │  (Agent-specific: its KB, exp) │  │  │  │  │
│  │  │  │  │  ┌──────────────────────────┐  │  │  │  │  │
│  │  │  │  │  │  Level 5: RUNTIME        │  │  │  │  │  │
│  │  │  │  │  │  (Execution-scoped)      │  │  │  │  │  │
│  │  │  │  │  └──────────────────────────┘  │  │  │  │  │
│  │  │  │  └────────────────────────────────┘  │  │  │  │
│  │  │  └──────────────────────────────────────┘  │  │  │
│  │  └────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
```

### 4.1 Level Definitions

| Level | Scope Key | Owner | Example Knowledge | Example Experience | Example Intelligence |
|-------|-----------|-------|-------------------|--------------------|---------------------|
| **L0: App** | `app_id` (singleton) | Platform admin | Platform schema, tool registry, model catalog | "Gemini-2.5-pro is 3x cheaper than Claude for summarization" | "Default to Gemini for summarization, Claude for reasoning" |
| **L1: Partner** | `partner_id` | Partner admin | Partner-specific templates, shared policies | "Partner X's tenants prefer detailed reports" | "Always include executive summary for Partner X tenants" |
| **L2: Tenant** | `company_id` | Tenant admin | Company documents, HR policies, product manuals | "Revenue reports take 45s avg, cost $0.12" | "Use internal KB before web search for this company" |
| **L3: User** | `user_id` | Individual user | User-uploaded documents, personal notes | "This user rejects outputs without tables" | "Always include data tables for this user" |
| **L4: Entity** | `entity_id` | Entity designer | Entity-specific KB, attached documents | "Scraping fails 30% of time for this entity" | "Add retry logic when scraping for this entity" |
| **L5: Runtime** | `run_id` | Execution engine | Scraped pages, tool results, LLM responses | N/A (too granular for learning) | N/A (too granular) |

### 4.2 Inheritance Model

At runtime, an agent assembles memory by **walking up the hierarchy**:

```
Agent Memory Assembly = 
    Runtime(L5)  ← current execution findings
  + Entity(L4)   ← this agent's KB + experience + intelligence
  + User(L3)     ← this user's preferences + patterns
  + Tenant(L2)   ← company knowledge + patterns
  + Partner(L1)  ← partner-wide patterns
  + App(L0)      ← system-wide knowledge + rules
```

**Critical design rule:** Higher levels provide context; lower levels provide specificity. When instructions conflict, **lower levels take precedence** (more specific wins).

### 4.3 Mapping to Existing Data Model

| Level | Current DB Entity | Key Column |
|-------|-------------------|------------|
| L0: App | `companies` WHERE `type='APP'` | `id` (singleton) |
| L1: Partner | `companies` WHERE `type='PARTNER'` | `id` |
| L2: Tenant | `companies` WHERE `type='TENANT'` | `id` |
| L3: User | `users` | `id` |
| L4: Entity | `hierarchical_entities` | `id` |
| L5: Runtime | `execution_runs` + `cortex_trees` | `run_id` / `tree_id` |

---

## 5. Unified Core Primitives — CortexTree & CortexNode v2

### 5.1 CortexTree v2 Schema

```python
class CortexTree(Base):
    __tablename__ = "cortex_trees"

    id = Column(UUID, primary_key=True, default=uuid4)
    
    # ── Memory Domain Classification ──
    memory_domain = Column(
        SAEnum(MemoryDomain),  # KNOWLEDGE | EXPERIENCE | INTELLIGENCE | EPISODIC
        nullable=False,
    )
    
    # ── Hierarchical Scoping ──
    scope_level = Column(
        SAEnum(ScopeLevel),  # APP | PARTNER | TENANT | USER | ENTITY | RUNTIME
        nullable=False,
    )
    # Exactly one of these is set based on scope_level:
    app_id = Column(UUID, nullable=True)         # L0 — always the singleton APP company ID
    partner_id = Column(UUID, ForeignKey("companies.id"), nullable=True)  # L1
    company_id = Column(UUID, ForeignKey("companies.id"), nullable=False) # L2 (always set for isolation)
    user_id = Column(UUID, ForeignKey("users.id"), nullable=True)         # L3
    entity_id = Column(UUID, ForeignKey("hierarchical_entities.id"), nullable=True) # L4
    run_id = Column(UUID, ForeignKey("execution_runs.id"), nullable=True) # L5
    
    # ── Tree Metadata ──
    task_description = Column(Text, nullable=True)
    status = Column(SAEnum(CortexTreeStatus), default=CortexTreeStatus.ACTIVE)
    tree_category = Column(String(100), nullable=True)  # e.g., "hr_policies", "revenue_analysis"
    
    # ── Structural Pointers ──
    total_nodes = Column(Integer, default=0)
    root_node_id = Column(UUID, nullable=True)
    output_root_id = Column(UUID, nullable=True)
    resume_cursor_id = Column(UUID, nullable=True)
    
    # ── Configuration ──
    max_children = Column(Integer, default=12)
    page_size_tokens = Column(Integer, default=8000)
    context_budget_pct = Column(Integer, default=40)
    
    # ── Lifecycle ──
    expires_at = Column(DateTime, nullable=True)      # NULL = never expires
    is_persistent = Column(Boolean, default=True)      # Runtime trees may be non-persistent
    
    # ── Scheduling ──
    resume_schedule = Column(String(100), nullable=True)
    next_resume_at = Column(DateTime, nullable=True)
    
    # ── Learning Algorithm Metadata ──
    last_consolidated_at = Column(DateTime, nullable=True)  # When last processed by dreaming
    consolidation_generation = Column(Integer, default=0)   # How many times consolidated
    source_run_ids = Column(JSONB, nullable=True)           # For Experience/Intelligence: which runs contributed
    
    # ── Timestamps ──
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active_at = Column(DateTime, default=datetime.utcnow)
```

### 5.2 New Enums

```python
class MemoryDomain(str, enum.Enum):
    KNOWLEDGE = "knowledge"
    EXPERIENCE = "experience"
    INTELLIGENCE = "intelligence"
    EPISODIC = "episodic"

class ScopeLevel(str, enum.Enum):
    APP = "app"
    PARTNER = "partner"
    TENANT = "tenant"
    USER = "user"
    ENTITY = "entity"
    RUNTIME = "runtime"
```

### 5.3 CortexNode v2 Schema

```python
class CortexNode(Base):
    __tablename__ = "cortex_nodes"

    id = Column(UUID, primary_key=True, default=uuid4)
    tree_id = Column(UUID, ForeignKey("cortex_trees.id", ondelete="CASCADE"), nullable=False)
    parent_id = Column(UUID, ForeignKey("cortex_nodes.id", ondelete="SET NULL"), nullable=True)

    # ── Core Content ──
    node_type = Column(SAEnum(CortexNodeType), nullable=False)
    title = Column(String(500), nullable=False)
    summary = Column(Text, nullable=True)
    content = Column(Text, nullable=True)
    content_tokens = Column(Integer, default=0)
    
    # ── NOVEL: Embedded Semantic Vector ──
    embedding = Column(Vector(768), nullable=True)  # pgvector — computed from summary+title
    embedding_model = Column(String(100), nullable=True)  # Track which model generated it
    
    # ── Status & Structure ──
    status = Column(SAEnum(CortexNodeStatus), default=CortexNodeStatus.PENDING)
    depth = Column(Integer, default=0)
    sibling_order = Column(Integer, default=0)
    
    # ── Provenance & Cross-References ──
    source_ref = Column(JSONB, nullable=True)  # Origin pointer (document, URL, run, etc.)
    cross_refs = Column(JSONB, nullable=True)  # Pointers to related nodes in OTHER trees
    
    # ── Semantic Graph Metadata ──
    access_count = Column(Integer, default=0)        # How many times this node was READ
    last_accessed_at = Column(DateTime, nullable=True)
    importance_score = Column(Numeric(5, 3), default=0.5)  # 0.0-1.0, updated by learning algo
    
    # ── Execution Linkage ──
    execution_run_id = Column(UUID, ForeignKey("execution_runs.id"), nullable=True)
    
    # ── Extended Metadata ──
    metadata_extra = Column(JSONB, nullable=True)
    
    # ── Timestamps ──
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
```

### 5.4 New Node Types (Extended Enum)

```python
class CortexNodeType(str, enum.Enum):
    # ── Structural ──
    ROOT = "root"
    GROUP = "group"              # NEW: Re-clustering group container
    
    # ── Knowledge Domain ──
    KNOWLEDGE = "knowledge"
    DOCUMENT = "document"        # NEW: Structural — represents an ingested document
    SECTION = "section"          # NEW: Structural — a section/chapter within a document
    CHUNK = "chunk"              # NEW: Leaf-level text chunk with embedding
    
    # ── Working/Runtime Domain ──
    FINDING = "finding"
    TASK = "task"
    OUTPUT = "output"
    CHECKPOINT = "checkpoint"
    
    # ── Experience Domain ──
    OBSERVATION = "observation"  # NEW: A specific observation from execution analysis
    PATTERN = "pattern"          # NEW: A recurring pattern across multiple observations
    SUGGESTION = "suggestion"    # NEW: A suggested approach based on patterns
    
    # ── Intelligence Domain ──
    INSTRUCTION = "instruction"  # NEW: A distilled actionable rule
    STRATEGY = "strategy"        # NEW: A high-level strategic approach
    PREFERENCE = "preference"    # NEW: A user/entity behavioral preference
    
    # ── Episodic Domain ──
    EPISODE = "episode"          # NEW: A single execution episode record
    EPISODE_GROUP = "episode_group"  # NEW: Grouped episodes (by date, topic, etc.)
```

---

## 6. Memory Silo Matrix (4 Domains × 6 Levels)

### 6.1 The Complete Matrix

Each cell represents one or more CORTEX Trees:

| | **L0: App** | **L1: Partner** | **L2: Tenant** | **L3: User** | **L4: Entity** | **L5: Runtime** |
|---|---|---|---|---|---|---|
| **Knowledge** | Platform schema, model catalog, tool docs | Partner templates, shared resources | Company docs, policies, SharePoint data | User uploads, personal KB | Entity-attached docs | Scraped pages, tool results, LLM responses |
| **Experience** | Cross-platform patterns | Cross-tenant patterns | Company-wide execution patterns | User-specific usage patterns | Entity-specific performance data | N/A (source data only) |
| **Intelligence** | System-wide defaults | Partner-wide rules | Company policies as instructions | User preferences as rules | Entity-tuned instructions | N/A (source data only) |
| **Episodic** | System audit log | Partner activity log | Company execution history | User execution history | Entity execution journal | The runtime tree itself |

### 6.2 Tree Creation Rules

| Scenario | Domain | Level | Created By | # Trees |
|----------|--------|-------|------------|---------|
| App startup | Knowledge | App | System bootstrap | 1 (singleton) |
| New partner onboarded | Knowledge | Partner | Onboarding process | 1 per partner |
| Tenant uploads documents | Knowledge | Tenant | Document ingestion pipeline | 1+ (may shard by category) |
| User uploads personal doc | Knowledge | User | User upload API | 1 per user |
| Entity created with KB | Knowledge | Entity | Entity creation flow | 1 per entity |
| Execution starts | Knowledge (Runtime) | Runtime | Worker `execute_run()` | 1 per execution |
| Dreaming process runs | Experience | Entity→App | Learning Algorithm | 1 per level per entity/user/etc. |
| Dreaming process runs | Intelligence | Entity→App | Learning Algorithm | 1 per level per entity/user/etc. |
| Execution completes | Episodic | Entity | `write_episodic()` | 1 per entity (appended to) |

### 6.3 Reference-Not-Copy Architecture

**Critical design principle:** Runtime trees do NOT duplicate knowledge from higher-level trees. Instead, they hold **references** (pointers) to nodes in persistent trees.

```python
# A Runtime Knowledge node that REFERENCES a Tenant-level document section:
runtime_node = CortexNode(
    tree_id=runtime_tree.id,
    node_type=CortexNodeType.KNOWLEDGE,
    title="📎 HR Remote Work Policy §3.2",
    summary="Eligibility criteria for remote work...",
    content=None,  # NO CONTENT DUPLICATION
    source_ref={
        "ref_type": "cortex_node",
        "source_tree_id": "uuid-of-tenant-knowledge-tree",
        "source_node_id": "uuid-of-section-node-in-tenant-tree",
        "source_scope": "tenant",
        "document_path": "//corp-share/HR/policies/remote-work-v2.docx",
        "section": "3.2.1 Eligibility Criteria",
    },
    cross_refs=[
        {"tree_id": "...", "node_id": "...", "relationship": "references"},
    ],
)
```

When the agent performs a READ on this node, the system **resolves the reference** and fetches content from the source tree. This eliminates storage bloat while maintaining full navigability.

### 6.4 Tree Persistence Rules

| Domain | Level | `is_persistent` | `expires_at` | Rationale |
|--------|-------|-----------------|--------------|-----------|
| Knowledge | App-Entity | `true` | `NULL` | Permanent — knowledge is always retained |
| Knowledge | Runtime | `true` | `NULL` | Runtime findings are preserved for learning |
| Experience | All | `true` | `NULL` | Experience never expires — importance scores decay |
| Intelligence | All | `true` | `NULL` | Instructions persist until superseded |
| Episodic | All | `true` | `NULL` | Episodes never deleted — oldest get lower importance |

---

*End of Part 1. Continue to Part 2 for deep architecture of each memory domain, the Semantic Graph Layer, and the novel search architecture.*
