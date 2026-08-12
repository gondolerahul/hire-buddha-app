# Unified CORTEX Memory Architecture v2.0 — Part 2

## 7. Knowledge Domain — Deep Architecture

### 7.1 Knowledge Tree Structure Per Level

Each Knowledge tree follows a **hierarchical document decomposition** structure:

```
Knowledge Tree Root (L2: Tenant Example)
├── 📂 Category: HR Policies
│   ├── 📄 Document: Remote Work Policy v2.docx
│   │   ├── 📑 Section: 1. Introduction
│   │   │   └── 🧩 Chunk: "Remote work eligibility..." [embedding ✓]
│   │   ├── 📑 Section: 2. Eligibility
│   │   │   ├── 🧩 Chunk: "Full-time employees..." [embedding ✓]
│   │   │   └── 🧩 Chunk: "Contractors require..." [embedding ✓]
│   │   └── 📑 Section: 3. Equipment
│   │       └── 🧩 Chunk: "Company provides..." [embedding ✓]
│   └── 📄 Document: Leave Policy 2026.pdf
│       └── ...
├── 📂 Category: Product Documentation
│   └── ...
└── 📂 Category: Financial Reports
    └── ...
```

**Key design decisions:**

1. **Every leaf chunk has an embedding vector** — enabling semantic search across the tree
2. **Section nodes have summaries** — enabling viewport-based navigation to the right area before drilling into chunks
3. **Document nodes have metadata** — file path, source system, last modified, version
4. **Category grouping is automatic** — the ingestion pipeline uses LLM classification to group related documents

### 7.2 Knowledge Ingestion Pipeline v2

```
Source (SharePoint/Drive/Upload)
    │
    ├── 1. Connector fetches document + metadata
    │
    ├── 2. Document Parser
    │   ├── Heading detection → Section boundaries
    │   ├── Table extraction → Structured chunks
    │   └── Image/diagram → Description chunks (vision model)
    │
    ├── 3. Hierarchical Node Creation
    │   ├── DOCUMENT node (metadata, source_ref with full provenance)
    │   ├── SECTION nodes (heading-based decomposition)
    │   └── CHUNK nodes (overlapping 500-char windows)
    │
    ├── 4. Embedding Generation (batch)
    │   ├── Each CHUNK gets embedding vector (768-dim)
    │   ├── Each SECTION summary gets embedding vector
    │   └── DOCUMENT summary gets embedding vector
    │
    ├── 5. Semantic Graph Edge Creation
    │   ├── Intra-document: section ↔ section similarity edges
    │   └── Cross-document: chunk ↔ chunk similarity edges (top-K)
    │
    └── 6. Category Classification
        └── LLM classifies document → category node placement
```

### 7.3 Runtime Knowledge Access (Reference Architecture)

When an agent needs knowledge during execution:

```python
# 1. Semantic search across ALL accessible Knowledge trees
results = await memory_assembler.semantic_search(
    query="remote work eligibility criteria",
    scope_levels=[ScopeLevel.RUNTIME, ScopeLevel.ENTITY, 
                  ScopeLevel.USER, ScopeLevel.TENANT],
    domain=MemoryDomain.KNOWLEDGE,
    top_k=10,
)

# 2. Create reference nodes in Runtime tree (no content duplication)
for result in results:
    await cortex.write(
        parent_id=runtime_knowledge_root.id,
        node_type="knowledge",
        title=f"📎 {result.title}",
        summary=result.summary,
        content=None,  # REFERENCE ONLY
        source_ref={
            "ref_type": "cortex_node",
            "source_tree_id": str(result.tree_id),
            "source_node_id": str(result.node_id),
        },
    )

# 3. When agent READs the reference node, resolve from source
async def read_with_reference_resolution(self, node_id):
    node = await self._get_node(node_id)
    if node.content is None and node.source_ref:
        ref = node.source_ref
        if ref.get("ref_type") == "cortex_node":
            source_node = await self._get_node_cross_tree(
                ref["source_tree_id"], ref["source_node_id"]
            )
            return source_node.content
    return node.content
```

### 7.4 Federated KB Connectors

```python
class KBConnector(ABC):
    """Base class for enterprise knowledge source connectors."""
    
    @abstractmethod
    async def list_documents(self, since: datetime = None) -> List[DocumentMeta]:
        """List available documents, optionally since last sync."""
    
    @abstractmethod
    async def fetch_document(self, doc_id: str) -> bytes:
        """Fetch document content."""
    
    @abstractmethod
    async def watch_changes(self, callback: Callable) -> None:
        """Register for change notifications (webhooks)."""

# Implementations:
class SharePointConnector(KBConnector): ...
class GoogleDriveConnector(KBConnector): ...
class NetworkDriveConnector(KBConnector): ...
class S3Connector(KBConnector): ...
class ConfluenceConnector(KBConnector): ...
class CustomAPIConnector(KBConnector): ...
```

---

## 8. Experience Domain — Deep Architecture

### 8.1 Experience Tree Structure

```
Experience Tree Root (L4: Entity Level)
├── 📊 Performance Patterns
│   ├── 🔍 Observation: "Web scraping success rate: 72%"
│   │   └── Evidence: [run_id_1, run_id_2, ..., run_id_15]
│   ├── 🔍 Observation: "Average execution time: 45s for simple queries"
│   │   └── Evidence: [run_id_3, run_id_7, ...]
│   └── 📈 Pattern: "Scraping fails more on JS-heavy sites"
│       ├── Evidence runs: [...]
│       ├── Confidence: 0.85
│       └── 💡 Suggestion: "Use headless_browser instead of scraper_tool for .js domains"
├── 🎯 Task Outcome Patterns
│   ├── 🔍 Observation: "Revenue analysis tasks: 90% success rate"
│   ├── 🔍 Observation: "Competitor analysis tasks: 60% success rate"
│   └── 📈 Pattern: "Competitor analysis fails when company name is ambiguous"
│       └── 💡 Suggestion: "Ask user to confirm company identity before starting"
├── 👤 User Interaction Patterns
│   ├── 🔍 Observation: "User X rejects outputs without tables"
│   └── 📈 Pattern: "User X prefers structured data over narrative"
│       └── 💡 Suggestion: "Include data tables in all outputs for User X"
└── ⚠️ Failure Patterns
    ├── 🔍 Observation: "LLM timeout after 120s on large context"
    └── 📈 Pattern: "Context > 100K tokens correlates with timeout"
        └── 💡 Suggestion: "Checkpoint aggressively when context > 80K tokens"
```

### 8.2 Experience Node Schema Extensions

```python
# Additional metadata_extra fields for Experience nodes:
{
    "observation_type": "performance|outcome|interaction|failure",
    "evidence_run_ids": ["uuid1", "uuid2", ...],
    "sample_size": 15,
    "confidence_score": 0.85,  # 0.0-1.0 based on evidence strength
    "first_observed_at": "2026-04-01T00:00:00Z",
    "last_confirmed_at": "2026-05-15T00:00:00Z",
    "contradiction_count": 2,  # Times this pattern was contradicted
    "confirmation_count": 13,  # Times this pattern was confirmed
}
```

### 8.3 Experience Consolidation (Entity → User → Tenant → Partner → App)

The Learning Algorithm extracts Entity-level Experience first, then consolidates upward:

```
Entity A Experience: "Web scraping fails 30% of the time"
Entity B Experience: "Web scraping fails 25% of the time"
Entity C Experience: "Web scraping fails 35% of the time"
                    ↓ (User-level consolidation)
User Experience: "Web scraping has ~30% failure rate across all entities"
                    ↓ (Tenant-level consolidation)
Tenant Experience: "Company-wide web scraping failure rate: 28%"
                    ↓ (App-level consolidation)
App Experience: "Platform-wide scraping reliability: 72%"
```

---

## 9. Intelligence Domain — Deep Architecture

### 9.1 Intelligence Tree Structure

```
Intelligence Tree Root (L4: Entity Level)
├── 📋 Execution Instructions
│   ├── 📌 Instruction: "Always check fiscal year calendar before revenue analysis"
│   │   ├── Source Experience: [experience_node_id_1, experience_node_id_2]
│   │   ├── Confidence: 0.92
│   │   └── Priority: HIGH
│   └── 📌 Instruction: "Limit web scraping to 5 sources per research topic"
│       ├── Source Experience: [experience_node_id_3]
│       ├── Confidence: 0.78
│       └── Priority: MEDIUM
├── 🧭 Strategy Rules
│   ├── 🗺️ Strategy: "For competitive analysis, use a 3-phase approach: scan → deep-dive → synthesize"
│   │   ├── Source Experience: pattern analysis across 20+ runs
│   │   └── Effectiveness: 85% success vs. 60% for single-phase
│   └── 🗺️ Strategy: "For document-heavy tasks, build section index before analysis"
│       └── Effectiveness: 40% faster navigation
├── 👤 User Preferences (auto-extracted)
│   ├── 🎨 Preference: "User X: Always include executive summary"
│   ├── 🎨 Preference: "User X: Prefer tables over paragraphs"
│   └── 🎨 Preference: "User Y: Include source citations in footnotes"
└── ⚙️ Configuration Overrides
    ├── 📌 Instruction: "Set max_children=8 for this entity (smaller viewport preferred)"
    └── 📌 Instruction: "Checkpoint every 2 steps (not 3) for long research tasks"
```

### 9.2 Intelligence Injection Into Runtime

Intelligence nodes are injected as **system prompt augmentations** at execution start:

```python
async def assemble_intelligence_prompt(entity_id, user_id, company_id):
    """
    Gather applicable Intelligence instructions from all levels
    and format as system prompt section.
    """
    instructions = []
    
    # Walk up the hierarchy (most specific first)
    for level, scope_id in [
        (ScopeLevel.ENTITY, entity_id),
        (ScopeLevel.USER, user_id),
        (ScopeLevel.TENANT, company_id),
        (ScopeLevel.PARTNER, partner_id),
        (ScopeLevel.APP, app_id),
    ]:
        trees = await get_trees(
            domain=MemoryDomain.INTELLIGENCE, 
            scope_level=level,
            scope_id=scope_id,
        )
        for tree in trees:
            nodes = await get_instruction_nodes(tree.id, 
                min_confidence=0.7, min_importance=0.5)
            instructions.extend(nodes)
    
    # Format as prompt section
    prompt = "## Learned Instructions (from past experience)\n"
    for inst in instructions:
        prompt += f"- [{inst.priority}] {inst.content}\n"
        prompt += f"  (confidence: {inst.confidence}, source: {inst.source})\n"
    
    return prompt
```

### 9.3 User-Defined vs. Auto-Learned Intelligence

Intelligence can come from two sources:

| Source | Example | Confidence | Mutable? |
|--------|---------|------------|----------|
| **User-defined** | "Always use formal tone in outputs" | 1.0 (explicit) | Yes, by user |
| **Auto-learned** | "Include tables for User X" (extracted from Experience) | 0.5-0.95 | Yes, by Learning Algorithm |

User-defined instructions always have `confidence=1.0` and take precedence over auto-learned ones.

---

## 10. Episodic Domain — Deep Architecture

### 10.1 Episodic Tree Structure

**Key innovation:** Episodic memory is now stored as a CORTEX tree per entity, with each execution becoming a node rather than a flat table row.

```
Episodic Tree Root (L4: Entity "Research Assistant")
├── 📅 2026-05 (Month Group)
│   ├── 📅 2026-05-15 (Day Group)
│   │   ├── 🎬 Episode: "Q3 Revenue Analysis" [run_id=abc123]
│   │   │   ├── Input: "Analyze Q3 revenue trends for APAC region"
│   │   │   ├── Output: "Report generated with 5 sections..."
│   │   │   ├── Status: COMPLETED
│   │   │   ├── Cost: $0.45, Tokens: 25,000, Time: 32s
│   │   │   ├── Tools: [web_search, scraper_tool]
│   │   │   └── runtime_tree_id: "uuid-of-runtime-tree"  ← DEEP DIVE LINK
│   │   └── 🎬 Episode: "Competitor Analysis - TechCorp" [run_id=def456]
│   │       ├── Input: "Compare our product with TechCorp..."
│   │       ├── Output: "FAILED - Company name ambiguous"
│   │       ├── Status: FAILED
│   │       └── runtime_tree_id: "uuid-of-runtime-tree"
│   └── 📅 2026-05-14 (Day Group)
│       └── 🎬 Episode: ...
└── 📅 2026-04 (Month Group)
    └── ...
```

### 10.2 Addressing the "Why Not Trees?" Objections

The original analysis (v1.0) raised three concerns about storing episodic memory in trees:

| Original Concern | v2.0 Solution |
|-----------------|---------------|
| **Different Lifecycles**: Episodic is cross-run, trees are per-run | **Solved**: Episodic trees are persistent (never expire), separate from Runtime trees |
| **Temporal Ordering**: Trees are spatial, not temporal | **Solved**: Episode nodes are grouped by date (Month → Day), ordered by `created_at` within groups. Non-linear temporal traversal via `metadata_extra.created_at` index |
| **Tree Independence**: Loading a previous tree just to read history | **Solved**: Each entity has ONE persistent Episodic tree. All episodes are nodes within it. No cross-tree loading needed |

### 10.3 Non-Linear Temporal Traversal

To support "find episodes from last week" or "what happened in March?", we add a **temporal index query**:

```python
async def query_episodes_by_time(
    tree_id: UUID,
    start_date: datetime,
    end_date: datetime,
) -> List[CortexNode]:
    """
    Non-linear temporal hop — query episode nodes by datetime range
    without traversing the tree top-down.
    """
    return await db.execute(
        select(CortexNode)
        .where(
            CortexNode.tree_id == tree_id,
            CortexNode.node_type == CortexNodeType.EPISODE,
            CortexNode.created_at >= start_date,
            CortexNode.created_at <= end_date,
        )
        .order_by(CortexNode.created_at.desc())
    )
```

This combines tree structure (for organized browsing) with direct temporal queries (for fast lookups), addressing the original concern.

### 10.4 Deep-Dive Link to Runtime Trees

Each Episode node contains `runtime_tree_id` in its `source_ref`. When an agent needs deeper context about a past execution:

```python
# Agent sees Episode summary: "Q3 Revenue Analysis - COMPLETED"
# Agent wants more detail → follows runtime_tree_id link

episode_node = await cortex.read(episode_node_id)
runtime_tree_id = episode_node.source_ref["runtime_tree_id"]

# Navigate into the past run's full CORTEX tree
runtime_viewport = await cortex.navigate_cross_tree(runtime_tree_id, root_node_id)
```

---

## 11. The Semantic Graph Layer (Novel Search Architecture)

### 11.1 The Problem With Pure Tree Traversal and Pure Vector Search

| Approach | Strength | Weakness |
|----------|----------|----------|
| **Tree traversal** | Preserves context hierarchy, relationships, structure | Cannot answer "find content about X" without exhaustive navigation |
| **Vector similarity** | Fast semantic matching, handles natural language queries | Returns isolated chunks with no structural context |

**Neither alone is sufficient.** We need a hybrid.

### 11.2 The Semantic Graph: Weighted Edges Between Nodes

Introduce a new table: `cortex_edges` — weighted, typed connections between nodes across trees.

```python
class CortexEdge(Base):
    __tablename__ = "cortex_edges"

    id = Column(UUID, primary_key=True, default=uuid4)
    
    source_node_id = Column(UUID, ForeignKey("cortex_nodes.id", ondelete="CASCADE"))
    target_node_id = Column(UUID, ForeignKey("cortex_nodes.id", ondelete="CASCADE"))
    
    # ── Edge Classification ──
    edge_type = Column(String(50), nullable=False)
    # Types: "semantic_similar", "references", "derived_from", 
    #        "contradicts", "supports", "supersedes", "parent_concept",
    #        "sibling_concept", "temporal_next", "causal"
    
    # ── Edge Weight ──
    weight = Column(Numeric(5, 4), default=0.5)  # 0.0-1.0
    # Weight is updated by:
    #   - Initial: cosine similarity between embeddings
    #   - Boosted: traversal frequency (how often agents follow this edge)
    #   - Decayed: time since last traversal
    
    # ── Traversal Statistics ──
    traversal_count = Column(Integer, default=0)
    last_traversed_at = Column(DateTime, nullable=True)
    
    # ── Metadata ──
    created_by = Column(String(50), nullable=True)  # "ingestion", "learning_algo", "agent", "user"
    metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
```

### 11.3 How Edges Are Created

| Trigger | Edge Type | Weight Source |
|---------|-----------|--------------|
| Document ingestion | `semantic_similar` | Cosine similarity between chunk embeddings |
| Agent writes finding referencing knowledge | `derived_from` | 1.0 (explicit reference) |
| Learning Algorithm finds pattern | `supports` / `contradicts` | Confidence score from analysis |
| Experience → Intelligence extraction | `derived_from` | 1.0 (explicit derivation) |
| Agent navigates from node A to node B | `semantic_similar` (boosted) | Weight += 0.05 per traversal |
| Cross-document section similarity | `sibling_concept` | Embedding similarity > 0.8 threshold |

### 11.4 Unified Search: The Semantic Graph Query

```python
async def semantic_graph_search(
    query: str,
    scope_levels: List[ScopeLevel],
    scope_ids: Dict[ScopeLevel, UUID],
    domains: List[MemoryDomain],
    top_k: int = 10,
    min_importance: float = 0.3,
) -> List[SearchResult]:
    """
    Novel hybrid search combining vector similarity + graph traversal + importance scoring.
    
    Algorithm:
    1. Embed the query
    2. Vector search across all accessible trees (filtered by scope + domain)
    3. For each hit, follow high-weight edges to find related nodes
    4. Score = (semantic_similarity × 0.4) + (edge_weight × 0.3) + (importance_score × 0.2) + (recency × 0.1)
    5. Return top-K by composite score
    """
    
    # Step 1: Embed query
    query_embedding = await embed(query)
    
    # Step 2: Get accessible tree IDs
    tree_ids = await get_accessible_trees(scope_levels, scope_ids, domains)
    
    # Step 3: Vector search with importance weighting
    candidates = await db.execute(text("""
        SELECT 
            cn.id, cn.tree_id, cn.title, cn.summary, cn.node_type,
            cn.importance_score, cn.access_count, cn.created_at,
            1 - (cn.embedding <=> CAST(:vec AS vector)) AS similarity,
            ct.memory_domain, ct.scope_level
        FROM cortex_nodes cn
        JOIN cortex_trees ct ON ct.id = cn.tree_id
        WHERE cn.tree_id = ANY(:tree_ids)
          AND cn.embedding IS NOT NULL
          AND cn.importance_score >= :min_importance
        ORDER BY cn.embedding <=> CAST(:vec AS vector)
        LIMIT :candidate_k
    """), {
        "vec": json.dumps(query_embedding),
        "tree_ids": tree_ids,
        "min_importance": min_importance,
        "candidate_k": top_k * 3,  # Over-fetch for graph expansion
    })
    
    # Step 4: Graph expansion — follow edges from top candidates
    expanded = set()
    for candidate in candidates:
        edges = await db.execute(text("""
            SELECT target_node_id, edge_type, weight
            FROM cortex_edges
            WHERE source_node_id = :node_id
              AND weight >= 0.5
            ORDER BY weight DESC
            LIMIT 5
        """), {"node_id": candidate.id})
        
        for edge in edges:
            expanded.add((edge.target_node_id, edge.weight))
    
    # Step 5: Composite scoring
    # Score = (similarity × 0.4) + (edge_weight × 0.3) + (importance × 0.2) + (recency × 0.1)
    scored_results = compute_composite_scores(candidates, expanded)
    
    return sorted(scored_results, key=lambda x: x.score, reverse=True)[:top_k]
```

### 11.5 Graph Maintenance

| Operation | Frequency | Cost | Purpose |
|-----------|-----------|------|---------|
| **Edge creation on ingestion** | Per document chunk | O(K) per chunk (top-K similarity) | Initial graph structure |
| **Edge weight boost on traversal** | Per agent navigation | O(1) | Reinforce useful connections |
| **Edge weight decay** | Daily background job | O(E) total edges | Weaken unused connections |
| **Edge pruning** | Weekly background job | O(E) total edges | Remove edges with weight < 0.1 |
| **Re-embedding on model update** | Rare (model migration) | O(N) all nodes | Keep embeddings current |

### 11.6 Why This Is Novel

Traditional RAG systems use either:
- **Pure vector search** (Pinecone, Weaviate) — fast but context-free
- **Pure graph traversal** (Neo4j knowledge graphs) — contextual but no semantic matching
- **Hybrid with separate stores** (vector DB + graph DB) — operational complexity

Our approach is **unified in PostgreSQL**:
- `cortex_nodes.embedding` — vector search via pgvector
- `cortex_edges` — graph traversal via SQL joins
- `cortex_nodes.importance_score` — relevance ranking
- Tree parent-child structure — hierarchical context
- All in one database with ACID transactions

---

*End of Part 2. Continue to Part 3 for the Learning Algorithm, Runtime Assembly, Risk Analysis, and Migration Strategy.*
