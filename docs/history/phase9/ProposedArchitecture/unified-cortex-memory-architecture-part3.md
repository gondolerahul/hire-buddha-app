# Unified CORTEX Memory Architecture v2.0 — Part 3

## 12. The Learning Algorithm ("Dreaming Process")

### 12.1 Overview

The Dreaming Process is a scheduled background pipeline that transforms raw execution data into structured Experience and Intelligence. It mirrors how the human brain consolidates memories during sleep.

```
Raw Executions (Episodic Trees + Runtime Trees)
        │
        ▼
┌─────────────────────────────────┐
│   PHASE 1: Experience Extraction │  ← "What patterns do I see?"
│   (Observation → Pattern →       │
│    Suggestion)                   │
└───────────────┬─────────────────┘
                │
                ▼
┌─────────────────────────────────┐
│   PHASE 2: Intelligence Distill  │  ← "What should I do about it?"
│   (Pattern → Instruction →       │
│    Strategy)                     │
└───────────────┬─────────────────┘
                │
                ▼
┌─────────────────────────────────┐
│   PHASE 3: Upward Consolidation  │  ← "What's common across levels?"
│   Entity → User → Tenant →      │
│   Partner → App                  │
└─────────────────────────────────┘
```

### 12.2 Phase 1: Experience Extraction

**Input:** All Runtime trees and Episodic entries for a given entity since last consolidation.

**Process (per entity):**

```python
async def extract_experience(entity_id: UUID, since: datetime):
    """
    Analyze recent executions for a single entity.
    Creates/updates OBSERVATION, PATTERN, and SUGGESTION nodes
    in the entity's Experience tree.
    """
    # 1. Gather raw data
    episodes = await get_episodes(entity_id, since=since)
    runtime_trees = [await load_tree(ep.runtime_tree_id) for ep in episodes]
    
    # 2. Build analysis prompt with structured extraction
    analysis_prompt = f"""
    You are a meta-cognitive analyst. Analyze these {len(episodes)} execution records
    and extract:
    
    A. OBSERVATIONS: Specific, measurable facts about execution behavior
       Format: {{observation, evidence_runs, metric_value, category}}
    
    B. PATTERNS: Recurring themes across multiple observations  
       Format: {{pattern, supporting_observations, confidence, category}}
    
    C. SUGGESTIONS: Actionable improvements based on patterns
       Format: {{suggestion, based_on_pattern, expected_improvement, priority}}
    
    Categories: performance, outcome, interaction, failure, efficiency
    
    Execution Data:
    {format_episodes_for_analysis(episodes, runtime_trees)}
    """
    
    # 3. LLM extraction (using thinking model for deep reasoning)
    result = await llm.generate(analysis_prompt, model="gemini-2.5-pro", 
                                 task_type="thinking")
    
    # 4. Write to Experience tree
    experience_tree = await get_or_create_tree(
        entity_id=entity_id, domain=MemoryDomain.EXPERIENCE, 
        scope_level=ScopeLevel.ENTITY
    )
    
    for obs in result.observations:
        await cortex.write(experience_tree, node_type="observation", ...)
    for pat in result.patterns:
        await cortex.write(experience_tree, node_type="pattern", ...)
    for sug in result.suggestions:
        await cortex.write(experience_tree, node_type="suggestion", ...)
    
    # 5. Create semantic edges between new experience nodes and source episodes
    await create_evidence_edges(new_nodes, source_episodes)
```

### 12.3 Phase 2: Intelligence Distillation

**Input:** Experience trees (observations, patterns, suggestions) for a given entity.

```python
async def distill_intelligence(entity_id: UUID):
    """
    Transform Experience patterns into actionable Intelligence instructions.
    """
    experience_tree = await get_tree(entity_id, MemoryDomain.EXPERIENCE, ScopeLevel.ENTITY)
    patterns = await get_nodes_by_type(experience_tree.id, [CortexNodeType.PATTERN, 
                                                              CortexNodeType.SUGGESTION])
    
    # Filter to high-confidence patterns only
    high_confidence = [p for p in patterns 
                       if p.metadata_extra.get("confidence_score", 0) >= 0.7]
    
    distill_prompt = f"""
    You are a strategy distiller. Convert these observed patterns and suggestions
    into CONCRETE, ACTIONABLE instructions for the agent.
    
    Rules:
    - Each instruction must be specific and executable
    - Include confidence level based on supporting evidence
    - Mark priority: HIGH (>90% confidence), MEDIUM (70-90%), LOW (<70%)
    - If two patterns contradict, note the contradiction
    
    Patterns:
    {format_patterns(high_confidence)}
    
    Existing Intelligence (to avoid duplicates):
    {format_existing_intelligence(entity_id)}
    """
    
    result = await llm.generate(distill_prompt, model="gemini-2.5-pro",
                                 task_type="thinking")
    
    intelligence_tree = await get_or_create_tree(
        entity_id=entity_id, domain=MemoryDomain.INTELLIGENCE,
        scope_level=ScopeLevel.ENTITY
    )
    
    for inst in result.instructions:
        node_id = await cortex.write(intelligence_tree, node_type="instruction", ...)
        # Link Intelligence back to source Experience
        await create_edge(source=pattern_node_id, target=node_id, 
                         edge_type="derived_from", weight=1.0)
```

### 12.4 Phase 3: Upward Consolidation

Runs **bottom-up** through the hierarchy:

```
Step 1: Entity-level extraction (already done in Phase 1 & 2)

Step 2: User-level consolidation
    Input: All entity-level Experience/Intelligence for entities owned by this user
    Process: Find common patterns across entities
    Output: User-level Experience & Intelligence trees
    
Step 3: Tenant-level consolidation  
    Input: All user-level Experience/Intelligence for users in this tenant
    Process: Find company-wide patterns
    Output: Tenant-level Experience & Intelligence trees

Step 4: Partner-level consolidation
    Input: All tenant-level data for tenants under this partner
    Output: Partner-level trees

Step 5: App-level consolidation
    Input: All partner-level data
    Output: App-level trees (platform-wide patterns)
```

**Consolidation logic:**

```python
async def consolidate_upward(
    source_level: ScopeLevel,  
    target_level: ScopeLevel,
    target_scope_id: UUID,
    source_scope_ids: List[UUID],
):
    """
    Find common patterns across source-level trees and write to target-level tree.
    """
    # Gather all source experience/intelligence
    source_patterns = []
    for scope_id in source_scope_ids:
        trees = await get_trees(scope_id, domain=MemoryDomain.EXPERIENCE, 
                                scope_level=source_level)
        for tree in trees:
            patterns = await get_nodes_by_type(tree.id, [CortexNodeType.PATTERN])
            source_patterns.extend(patterns)
    
    if len(source_patterns) < 3:
        return  # Not enough data to consolidate
    
    consolidation_prompt = f"""
    Analyze these {len(source_patterns)} patterns from {len(source_scope_ids)} 
    {source_level.value}-level sources. Identify patterns that are:
    
    1. COMMON: Appear in 50%+ of sources → HIGH confidence at {target_level.value} level
    2. EMERGING: Appear in 25-50% → MEDIUM confidence  
    3. UNIQUE: Appear in <25% → Keep at source level only (do not promote)
    
    Only promote COMMON and EMERGING patterns.
    
    Source Patterns:
    {format_patterns_with_source(source_patterns)}
    """
    
    result = await llm.generate(consolidation_prompt, ...)
    
    target_tree = await get_or_create_tree(
        scope_id=target_scope_id, domain=MemoryDomain.EXPERIENCE,
        scope_level=target_level
    )
    
    for pattern in result.common_patterns + result.emerging_patterns:
        await cortex.write(target_tree, node_type="pattern", ...)
```

### 12.5 Scheduling

```python
# Arq cron jobs for the Dreaming Process
DREAMING_SCHEDULE = {
    "experience_extraction": {
        "cron": "0 2 * * *",  # Daily at 2 AM
        "scope": "entity",     # Process each entity
    },
    "intelligence_distillation": {
        "cron": "0 3 * * *",  # Daily at 3 AM (after experience)
        "scope": "entity",
    },
    "user_consolidation": {
        "cron": "0 4 * * 0",  # Weekly, Sunday at 4 AM
        "scope": "user",
    },
    "tenant_consolidation": {
        "cron": "0 5 1 * *",  # Monthly, 1st at 5 AM
        "scope": "tenant",
    },
    "partner_consolidation": {
        "cron": "0 6 1 */3 *",  # Quarterly
        "scope": "partner",
    },
    "app_consolidation": {
        "cron": "0 7 1 */6 *",  # Semi-annually
        "scope": "app",
    },
}
```

---

## 13. Runtime Memory Assembly Pipeline

### 13.1 The Assembly Flow

When an execution starts, the agent's full memory context is assembled:

```python
async def assemble_runtime_memory(
    entity_id: UUID, user_id: UUID, company_id: UUID,
    partner_id: UUID, app_id: UUID,
    task_description: str,
) -> Dict[str, Any]:
    """
    Assemble the complete memory context for an execution run.
    Returns context dict to inject into the agent's prompt.
    """
    context = {}
    
    # ── 1. Intelligence (Instructions) — injected as system prompt ──
    intelligence = await assemble_intelligence_prompt(
        entity_id, user_id, company_id, partner_id, app_id
    )
    context["__intelligence__"] = intelligence
    
    # ── 2. Experience (Relevant patterns) — semantic search ──
    experience = await semantic_graph_search(
        query=task_description,
        domains=[MemoryDomain.EXPERIENCE],
        scope_levels=[ScopeLevel.ENTITY, ScopeLevel.USER, 
                      ScopeLevel.TENANT, ScopeLevel.PARTNER, ScopeLevel.APP],
        scope_ids={...},
        top_k=5,
    )
    context["__experience__"] = format_experience_for_prompt(experience)
    
    # ── 3. Episodic (Recent history) — from entity's episodic tree ──
    episodic_tree = await get_tree(entity_id, MemoryDomain.EPISODIC, ScopeLevel.ENTITY)
    recent_episodes = await query_episodes_by_time(
        episodic_tree.id, 
        start_date=datetime.utcnow() - timedelta(days=30),
        end_date=datetime.utcnow(),
    )
    context["__episodic__"] = format_episodes_for_prompt(recent_episodes[:10])
    
    # ── 4. Knowledge (Relevant KB) — semantic search, reference only ──
    knowledge = await semantic_graph_search(
        query=task_description,
        domains=[MemoryDomain.KNOWLEDGE],
        scope_levels=[ScopeLevel.ENTITY, ScopeLevel.USER, 
                      ScopeLevel.TENANT, ScopeLevel.PARTNER, ScopeLevel.APP],
        scope_ids={...},
        top_k=10,
    )
    # Write reference nodes to runtime tree (no content duplication)
    for k in knowledge:
        await write_reference_node(runtime_tree, k)
    context["__knowledge_refs__"] = format_knowledge_for_prompt(knowledge)
    
    # ── 5. CORTEX Viewport (Runtime tree) — existing mechanism ──
    runtime_tree = await cortex.create_tree(entity_id, user_id, task_description)
    viewport = await cortex.navigate(runtime_tree.root_node_id)
    context["__cortex_viewport__"] = viewport.to_prompt_text()
    context["__cortex_tree_id__"] = str(runtime_tree.id)
    
    return context
```

### 13.2 Token Budget Allocation

```
Total Model Context Window: 200,000 tokens
├── System Prompt:         ~2,000 tokens (1%)
├── Intelligence:          ~1,500 tokens (0.75%) — distilled instructions
├── Experience:            ~1,000 tokens (0.5%) — relevant patterns  
├── Episodic:              ~1,000 tokens (0.5%) — recent history
├── Knowledge References:  ~2,000 tokens (1%) — summaries of relevant KB
├── CORTEX Viewport:       ~600 tokens (0.3%) — current tree position
├── Tools/Functions:       ~3,000 tokens (1.5%)
├── User Input:            ~500 tokens (0.25%)
├── Context Budget (40%):  80,000 tokens — working space for execution
└── Reserved:              ~108,400 tokens (54.2%) — LLM response + overhead
```

---

## 14. Agent Memory Access Protocol

### 14.1 New CORTEX Operations for v2

In addition to the existing 7 operations, agents gain:

| Operation | Signature | Purpose |
|-----------|-----------|---------|
| **SEARCH** | `search(query, domains, scopes, top_k)` | Semantic graph search across all accessible memory |
| **RECALL** | `recall(topic, time_range)` | Retrieve episodic memories by topic and/or time |
| **LEARN** | `learn(observation, evidence)` | Agent explicitly records a learning (written to Experience tree) |
| **INSTRUCT** | `instruct(rule, priority)` | Agent explicitly records an instruction (written to Intelligence tree) |
| **CROSS_REF** | `cross_ref(node_id, target_tree_id)` | Create a reference edge to a node in another tree |

### 14.2 Updated Viewport Prompt

```
## Memory Access Operations
In addition to tree navigation (NAVIGATE, READ, WRITE, RECURSE, CHECKPOINT):

  SEARCH(query, domains=["knowledge","experience"], top_k=5)
    — Semantic search across your accessible memory
  RECALL(topic="revenue analysis", days_back=30) 
    — Retrieve relevant past episodes
  LEARN(observation="Web scraping is 3x slower on .gov sites", evidence="runs 12,15,18")
    — Record a learning for future reference
  INSTRUCT(rule="Always use headless_browser for .gov sites", priority="HIGH")
    — Record an instruction for future runs
```

---

## 15. Risk Analysis & Feasibility Assessment

### 15.1 Risk Matrix

| # | Risk | Severity | Likelihood | Mitigation |
|---|------|----------|------------|------------|
| R1 | **Embedding cost explosion** — embedding every node across all trees | HIGH | HIGH | Batch embedding during ingestion, not real-time. Use cheaper models for low-priority trees. Budget cap per tenant. |
| R2 | **Learning Algorithm hallucination** — LLM extracts incorrect patterns | HIGH | MEDIUM | Confidence scoring, require multiple evidence runs (min 3), human review for HIGH-priority Intelligence, contradiction detection. |
| R3 | **Graph edge explosion** — O(N²) potential edges | MEDIUM | MEDIUM | Cap edges per node (max 20), prune low-weight edges weekly, only create edges above similarity threshold (0.7). |
| R4 | **Query latency** — semantic search across many trees | MEDIUM | MEDIUM | Partitioned indexes by `(scope_level, memory_domain)`, materialized views for hot queries, Redis cache for frequent searches. |
| R5 | **Storage growth** — never deleting data | MEDIUM | HIGH | Tiered storage: hot (PostgreSQL) for recent/important, warm (S3-backed) for old/low-importance. Importance-based archival. |
| R6 | **Conflicting Intelligence** — Entity-level instruction contradicts Tenant-level | MEDIUM | MEDIUM | Lower-level takes precedence. Contradiction detection in Learning Algorithm. Admin override capability. |
| R7 | **Cold start** — new entities have no Experience/Intelligence | LOW | HIGH | Inherit from template entity's Experience/Intelligence. App-level defaults apply immediately. |
| R8 | **Data isolation breach** — tenant A's data leaking to tenant B | CRITICAL | LOW | All queries filter by `company_id`. Scope hierarchy enforced in `get_accessible_trees()`. Security audit on cross-tree access. |
| R9 | **Learning Algorithm cost** — LLM calls for extraction | MEDIUM | MEDIUM | Use smaller/cheaper models for extraction. Batch processing. Cost caps per dreaming cycle. Skip entities with <5 new runs. |
| R10 | **Migration complexity** — moving from v1 to v2 | HIGH | HIGH | Phased migration (see §16). v1 and v2 coexist during transition. Feature flags per tenant. |

### 15.2 Feasibility Assessment

| Component | Feasibility | Confidence | Key Dependency |
|-----------|-------------|------------|----------------|
| CortexTree v2 schema | ✅ Straightforward | 95% | Alembic migration |
| CortexNode with embeddings | ✅ pgvector already in use | 90% | Fix embedding model (404 bug) |
| CortexEdge table | ✅ Standard relational + pgvector | 90% | Index design critical for performance |
| Knowledge tree ingestion | ✅ Evolution of existing pipeline | 85% | Document parser quality |
| Episodic trees | ✅ Restructuring existing flat table | 90% | Migration of existing data |
| Experience extraction | ⚠️ Requires careful prompt engineering | 70% | LLM extraction quality |
| Intelligence distillation | ⚠️ Requires careful prompt engineering | 65% | Depends on Experience quality |
| Upward consolidation | ⚠️ Complex aggregation logic | 60% | Statistical significance with small N |
| Semantic graph search | ✅ SQL + pgvector, well-understood | 85% | Index tuning for performance |
| Federated KB connectors | ⚠️ Each connector is separate effort | 50% | Third-party API stability |
| Reference resolution (cross-tree READ) | ✅ Straightforward join | 90% | Permission checks |
| Runtime memory assembly | ✅ Evolution of existing MemoryRouter | 85% | Token budget management |

### 15.3 Performance Projections

| Operation | Current v1 | Projected v2 | Notes |
|-----------|-----------|-------------|-------|
| Tree creation | 15ms (4 nodes) | 20ms (4 nodes) | Minimal change |
| Navigate | 5-10ms | 5-10ms | Same mechanism |
| Write | 10-15ms | 15-20ms | +embedding generation (async) |
| Semantic search (single tree) | N/A | 20-50ms | pgvector ANN index |
| Semantic graph search (cross-tree) | N/A | 50-150ms | Depends on # trees |
| Runtime memory assembly | 30ms | 100-200ms | More data sources |
| Experience extraction (per entity) | N/A | 5-30s | LLM call |
| Intelligence distillation (per entity) | N/A | 5-20s | LLM call |

---

## 16. Migration Strategy from v1.0

### 16.1 Phased Approach

```
Phase A: Schema Evolution (Week 1-2)
  - Add new columns to cortex_trees (memory_domain, scope_level, etc.)
  - Add new columns to cortex_nodes (embedding, importance_score, etc.)
  - Create cortex_edges table
  - Default existing trees: memory_domain=KNOWLEDGE, scope_level=RUNTIME
  - NO code changes yet — existing system continues working

Phase B: Knowledge Trees (Week 3-4)  
  - Migrate document_chunks → Knowledge tree nodes with embeddings
  - Build document → section → chunk tree structure from existing flat chunks
  - Create Tenant-level Knowledge trees from existing documents table
  - Update ingestion pipeline to write to trees instead of flat table

Phase C: Episodic Trees (Week 5)
  - Create Entity-level Episodic trees from existing episodic_memories rows
  - Update write_episodic() to write to tree instead of flat table
  - Add temporal query capability

Phase D: Experience & Intelligence (Week 6-8)
  - Implement Learning Algorithm Phase 1 (Experience extraction)
  - Implement Learning Algorithm Phase 2 (Intelligence distillation)
  - Implement upward consolidation
  - Schedule dreaming processes

Phase E: Semantic Graph (Week 7-9)
  - Populate cortex_edges during ingestion
  - Implement semantic_graph_search()
  - Update MemoryRouter to use new search
  - Add SEARCH, RECALL, LEARN, INSTRUCT operations

Phase F: Runtime Assembly (Week 9-10)
  - Update worker.py to use assemble_runtime_memory()
  - Implement reference-not-copy for knowledge nodes
  - Update viewport with new operations prompt
```

### 16.2 Backward Compatibility

- All existing v1 trees continue working (default `memory_domain=KNOWLEDGE, scope_level=RUNTIME`)
- Existing `episodic_memories` table retained as read-only during transition
- Existing `documents`/`document_chunks` tables retained, data migrated to trees
- Feature flags control v2 features per tenant

---

## 17. Database Schema Evolution

### 17.1 New Migration: Add Unified Memory Fields

```sql
-- Migration: add_unified_cortex_memory_v2

-- New enum types
CREATE TYPE memory_domain AS ENUM ('knowledge', 'experience', 'intelligence', 'episodic');
CREATE TYPE scope_level AS ENUM ('app', 'partner', 'tenant', 'user', 'entity', 'runtime');

-- Extend cortex_node_type enum
ALTER TYPE cortex_node_type ADD VALUE 'group';
ALTER TYPE cortex_node_type ADD VALUE 'document';
ALTER TYPE cortex_node_type ADD VALUE 'section';
ALTER TYPE cortex_node_type ADD VALUE 'chunk';
ALTER TYPE cortex_node_type ADD VALUE 'observation';
ALTER TYPE cortex_node_type ADD VALUE 'pattern';
ALTER TYPE cortex_node_type ADD VALUE 'suggestion';
ALTER TYPE cortex_node_type ADD VALUE 'instruction';
ALTER TYPE cortex_node_type ADD VALUE 'strategy';
ALTER TYPE cortex_node_type ADD VALUE 'preference';
ALTER TYPE cortex_node_type ADD VALUE 'episode';
ALTER TYPE cortex_node_type ADD VALUE 'episode_group';

-- Extend cortex_trees
ALTER TABLE cortex_trees ADD COLUMN memory_domain memory_domain DEFAULT 'knowledge';
ALTER TABLE cortex_trees ADD COLUMN scope_level scope_level DEFAULT 'runtime';
ALTER TABLE cortex_trees ADD COLUMN app_id UUID REFERENCES companies(id);
ALTER TABLE cortex_trees ADD COLUMN partner_id UUID REFERENCES companies(id);
ALTER TABLE cortex_trees ADD COLUMN run_id UUID REFERENCES execution_runs(id);
ALTER TABLE cortex_trees ADD COLUMN tree_category VARCHAR(100);
ALTER TABLE cortex_trees ADD COLUMN expires_at TIMESTAMP;
ALTER TABLE cortex_trees ADD COLUMN is_persistent BOOLEAN DEFAULT TRUE;
ALTER TABLE cortex_trees ADD COLUMN last_consolidated_at TIMESTAMP;
ALTER TABLE cortex_trees ADD COLUMN consolidation_generation INTEGER DEFAULT 0;
ALTER TABLE cortex_trees ADD COLUMN source_run_ids JSONB;

-- Extend cortex_nodes  
ALTER TABLE cortex_nodes ADD COLUMN embedding vector(768);
ALTER TABLE cortex_nodes ADD COLUMN embedding_model VARCHAR(100);
ALTER TABLE cortex_nodes ADD COLUMN cross_refs JSONB;
ALTER TABLE cortex_nodes ADD COLUMN access_count INTEGER DEFAULT 0;
ALTER TABLE cortex_nodes ADD COLUMN last_accessed_at TIMESTAMP;
ALTER TABLE cortex_nodes ADD COLUMN importance_score NUMERIC(5,3) DEFAULT 0.500;

-- New table: cortex_edges
CREATE TABLE cortex_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_node_id UUID NOT NULL REFERENCES cortex_nodes(id) ON DELETE CASCADE,
    target_node_id UUID NOT NULL REFERENCES cortex_nodes(id) ON DELETE CASCADE,
    edge_type VARCHAR(50) NOT NULL,
    weight NUMERIC(5,4) DEFAULT 0.5000,
    traversal_count INTEGER DEFAULT 0,
    last_traversed_at TIMESTAMP,
    created_by VARCHAR(50),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(source_node_id, target_node_id, edge_type)
);

-- Indexes for cortex_trees (new fields)
CREATE INDEX ix_cortex_trees_domain_scope ON cortex_trees(memory_domain, scope_level);
CREATE INDEX ix_cortex_trees_scope_entity ON cortex_trees(scope_level, entity_id) 
    WHERE entity_id IS NOT NULL;
CREATE INDEX ix_cortex_trees_scope_user ON cortex_trees(scope_level, user_id) 
    WHERE user_id IS NOT NULL;
CREATE INDEX ix_cortex_trees_scope_company ON cortex_trees(scope_level, company_id);

-- Indexes for cortex_nodes (embeddings + importance)
CREATE INDEX ix_cortex_nodes_embedding ON cortex_nodes 
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX ix_cortex_nodes_importance ON cortex_nodes(importance_score DESC);
CREATE INDEX ix_cortex_nodes_tree_type_status ON cortex_nodes(tree_id, node_type, status);
CREATE INDEX ix_cortex_nodes_created_at ON cortex_nodes(created_at);

-- Indexes for cortex_edges
CREATE INDEX ix_cortex_edges_source ON cortex_edges(source_node_id);
CREATE INDEX ix_cortex_edges_target ON cortex_edges(target_node_id);
CREATE INDEX ix_cortex_edges_type_weight ON cortex_edges(edge_type, weight DESC);

-- Update existing trees to have proper domain/scope
UPDATE cortex_trees SET memory_domain = 'knowledge', scope_level = 'runtime' 
    WHERE memory_domain IS NULL;
```

### 17.2 Improvements from cortex-memory-deep-analysis-part2.md (Incorporated)

All improvements from the deep analysis are incorporated:

| Original Recommendation | Where Addressed in v2 |
|------------------------|----------------------|
| **Add embeddings to CORTEX nodes** (Tier 2, #4) | §5.3 — `CortexNode.embedding` column |
| **LLM-quality summaries for all ingestion** (#5) | §7.2 — Ingestion pipeline generates LLM summaries for all levels |
| **Structural document decomposition** (#6) | §7.1 — Document → Section → Chunk hierarchy |
| **User feedback on retry** (#7) | §14.1 — LEARN and INSTRUCT operations |
| **Hybrid Storage — CORTEX as index, object store as content** (#9) | §6.3 — Reference-not-copy architecture |
| **Global Knowledge Graph** (#11) | §11 — Semantic Graph Layer with weighted edges |
| **Multi-Resolution Summarization** (#13) | §7.1 — Document, Section, Chunk each have their own summary level |
| **Cross-Tree Knowledge Inheritance** (#14) | §4.2 — Hierarchical inheritance model |
| **Federated KB Connectors** (#15) | §7.4 — Connector abstraction |
| **Adaptive Memory Consolidation** (#17) | §12 — Learning Algorithm (Dreaming Process) |
| **Memory Importance Scoring** (#19) | §5.3 — `importance_score` on CortexNode |
| **Natural Language Tree Queries** (#20) | §14.1 — SEARCH operation |

---

## 18. Summary: What Makes This Architecture Novel

1. **Unified storage primitive** — Everything is a CortexNode in a CortexTree. No separate tables for different memory types.

2. **Hierarchical scoping** — 6-level inheritance (App → Runtime) ensures knowledge flows downward while patterns consolidate upward.

3. **Four distinct memory domains** — Knowledge (facts), Experience (observations), Intelligence (instructions), Episodic (history) mirror neuroscience.

4. **Semantic Graph Layer** — Weighted edges between nodes enable associative recall, combining tree structure with vector search in a single PostgreSQL database.

5. **Reference-not-copy** — Runtime trees reference persistent knowledge trees, eliminating storage bloat while maintaining full navigability.

6. **Learning Algorithm** — Scheduled "dreaming" processes extract patterns from raw executions, consolidate upward through the hierarchy, and produce actionable instructions.

7. **Zero information loss** — Nothing is deleted. Importance scores decay, access frequencies drive relevance, but all data persists.

8. **Backward compatible** — v1 trees continue working unchanged; migration is phased and non-destructive.

---

*End of Unified CORTEX Memory Architecture v2.0*
*Files: unified-cortex-memory-architecture-part1.md, part2.md, part3.md*
*Total scope: ~2,500 lines across 3 documents*
