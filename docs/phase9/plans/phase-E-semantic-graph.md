# Phase E: Semantic Graph — Associative Memory Layer

**Timeline**: Week 9–10  
**Risk Level**: MEDIUM  
**Dependencies**: Phase A (schema, `cortex_edges` table), Phase B (Knowledge embeddings), Phase D (Experience/Intelligence edges)  
**Goal**: Implement the associative semantic graph that enables hybrid structural-semantic search across all memory domains.

---

## E.1 Executive Summary

Phase E activates the `cortex_edges` table and implements a semantic graph layer that overlays the tree structures from Phases B–D. This graph enables **associative navigation** — finding related concepts across different trees and domains using weighted, typed edges. The graph layer transforms the discrete memory silos into an interconnected knowledge mesh that supports:

1. **Cross-domain search**: A query about "revenue analysis" finds relevant Knowledge documents, past Episodic runs, and applicable Intelligence rules.
2. **Graph-expanded retrieval**: Starting from an initial node hit, expand through edges to find contextually related nodes.
3. **Automatic edge creation**: Edges are created automatically during embedding, dreaming, and execution.
4. **Relevance-weighted traversal**: Edge weights decay or strengthen based on traversal patterns.

---

## E.2 Edge Type Taxonomy

| Edge Type | Direction | Domains | Description | Created By |
|---|---|---|---|---|
| `references` | Source → Target | Knowledge ↔ Knowledge | Document cites or references another | Ingestion |
| `derived_from` | Experience → Episodic | Experience → Episodic | Observation derived from episode | Dreaming Phase 1 |
| `generalizes` | Intelligence → Experience | Intelligence → Experience | Rule generalizes a pattern | Dreaming Phase 3 |
| `semantic_similar` | Any ↔ Any | Cross-domain | High embedding cosine similarity | Embedding pipeline |
| `co_accessed` | Any ↔ Any | Same domain | Accessed together in same execution | Runtime tracking |
| `precedes` | Episode → Episode | Episodic | Temporal sequence in same session | Episodic write |
| `contradicts` | Intelligence ↔ Intelligence | Intelligence | Conflicting rules flagged | Dreaming Phase 3 |
| `supersedes` | Intelligence → Intelligence | Intelligence | Updated rule replaces old one | Dreaming Phase 3 |
| `applies_to` | Intelligence → Knowledge | Cross-domain | Rule applies to specific knowledge domain | Dreaming Phase 3 |

---

## E.3 Detailed Implementation

### E.3.1 Graph Service

**New file**: `backend/src/ai/graph_service.py`

```python
class SemanticGraphService:
    """Manages the cortex_edges graph layer overlaying CORTEX Trees."""
    
    # Weight decay/boost parameters
    DECAY_RATE = 0.95          # Per-day decay for untraversed edges
    BOOST_ON_TRAVERSAL = 0.05  # Weight boost each time edge is traversed
    MIN_WEIGHT = 0.01          # Minimum weight before pruning
    MAX_WEIGHT = 1.0           # Maximum weight cap
    
    # Automatic edge creation thresholds
    SIMILARITY_THRESHOLD = 0.85  # Cosine similarity threshold for auto-edges
    MAX_AUTO_EDGES_PER_NODE = 5  # Cap auto-generated edges per node
    
    def __init__(self, db: AsyncSession, company_id: UUID):
        self.db = db
        self.company_id = company_id
    
    # ──────────────────────────────────────────────────────────────────
    # Edge CRUD
    # ──────────────────────────────────────────────────────────────────
    
    async def create_edge(
        self,
        source_node_id: UUID,
        target_node_id: UUID,
        edge_type: str,
        weight: float = 0.5,
        created_by: str = "system",
        metadata: Dict = None,
    ) -> CortexEdge:
        """Create or update an edge between two nodes."""
        # Upsert: if edge already exists, update weight
        existing = await self.db.execute(
            select(CortexEdge).where(
                CortexEdge.source_node_id == source_node_id,
                CortexEdge.target_node_id == target_node_id,
                CortexEdge.edge_type == edge_type,
            )
        )
        edge = existing.scalar_one_or_none()
        
        if edge:
            edge.weight = min(self.MAX_WEIGHT, edge.weight + self.BOOST_ON_TRAVERSAL)
            edge.traversal_count = (edge.traversal_count or 0) + 1
            edge.last_traversed_at = datetime.utcnow()
            return edge
        
        edge = CortexEdge(
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            edge_type=edge_type,
            weight=weight,
            created_by=created_by,
            metadata=metadata,
        )
        self.db.add(edge)
        return edge
    
    # ──────────────────────────────────────────────────────────────────
    # Graph Traversal
    # ──────────────────────────────────────────────────────────────────
    
    async def expand_from_node(
        self,
        node_id: UUID,
        max_depth: int = 2,
        edge_types: List[str] = None,
        min_weight: float = 0.1,
        max_nodes: int = 20,
    ) -> List[Dict]:
        """
        BFS expansion from a starting node through edges.
        Returns list of {node, edge_type, weight, depth, path} dicts.
        """
        edge_type_filter = ""
        if edge_types:
            types_str = ", ".join(f"'{t}'" for t in edge_types)
            edge_type_filter = f"AND e.edge_type IN ({types_str})"
        
        # Recursive CTE for BFS
        result = await self.db.execute(text(f"""
            WITH RECURSIVE graph_walk AS (
                -- Base case: direct edges from starting node
                SELECT 
                    e.target_node_id AS node_id,
                    e.edge_type,
                    e.weight,
                    1 AS depth,
                    ARRAY[e.source_node_id, e.target_node_id] AS path
                FROM cortex_edges e
                WHERE e.source_node_id = :start_node
                  AND e.weight >= :min_weight
                  {edge_type_filter}
                
                UNION ALL
                
                -- Recursive case: expand further
                SELECT 
                    e.target_node_id,
                    e.edge_type,
                    e.weight * gw.weight AS weight,  -- Compound weight decay
                    gw.depth + 1,
                    gw.path || e.target_node_id
                FROM cortex_edges e
                JOIN graph_walk gw ON e.source_node_id = gw.node_id
                WHERE gw.depth < :max_depth
                  AND e.weight >= :min_weight
                  AND NOT (e.target_node_id = ANY(gw.path))  -- Prevent cycles
                  {edge_type_filter}
            )
            SELECT DISTINCT ON (gw.node_id)
                gw.node_id, gw.edge_type, gw.weight, gw.depth,
                cn.title, cn.summary, cn.node_type, cn.tree_id
            FROM graph_walk gw
            JOIN cortex_nodes cn ON cn.id = gw.node_id
            ORDER BY gw.node_id, gw.weight DESC
            LIMIT :max_nodes
        """), {
            "start_node": str(node_id),
            "min_weight": min_weight,
            "max_depth": max_depth,
            "max_nodes": max_nodes,
        })
        
        return [
            {
                "node_id": str(row.node_id),
                "title": row.title,
                "summary": row.summary,
                "node_type": row.node_type,
                "tree_id": str(row.tree_id),
                "edge_type": row.edge_type,
                "weight": float(row.weight),
                "depth": row.depth,
            }
            for row in result.fetchall()
        ]
    
    # ──────────────────────────────────────────────────────────────────
    # Hybrid Search (Semantic + Graph)
    # ──────────────────────────────────────────────────────────────────
    
    async def semantic_graph_search(
        self,
        query: str,
        entity_id: UUID,
        domains: List[str] = None,
        top_k: int = 5,
        graph_expansion_depth: int = 1,
    ) -> List[Dict]:
        """
        Hybrid search combining:
        1. Embedding similarity (initial seed nodes)
        2. Graph expansion (find related nodes via edges)
        3. Re-ranking by combined score
        
        This is the primary search interface for the v2 memory system.
        """
        embedding_service = EmbeddingService(self.db, self.company_id)
        query_vector = await embedding_service.embed_text(query)
        
        if not query_vector:
            return []
        
        # Step 1: Semantic seed — find top-k nodes by embedding similarity
        domain_filter = ""
        if domains:
            domains_str = ", ".join(f"'{d}'" for d in domains)
            domain_filter = f"AND ct.memory_domain IN ({domains_str})"
        
        seed_result = await self.db.execute(text(f"""
            SELECT cn.id, cn.title, cn.summary, cn.node_type, cn.tree_id,
                   ct.memory_domain,
                   1 - (cn.embedding <=> CAST(:vec AS vector)) AS similarity
            FROM cortex_nodes cn
            JOIN cortex_trees ct ON ct.id = cn.tree_id
            WHERE cn.embedding IS NOT NULL
              AND ct.company_id = :company_id
              AND (ct.entity_id = :entity_id OR ct.scope_level IN ('app', 'tenant'))
              {domain_filter}
            ORDER BY cn.embedding <=> CAST(:vec AS vector)
            LIMIT :top_k
        """), {
            "vec": json.dumps(query_vector),
            "company_id": str(self.company_id),
            "entity_id": str(entity_id),
            "top_k": top_k,
        })
        
        seed_nodes = seed_result.fetchall()
        
        if not seed_nodes:
            return []
        
        # Step 2: Graph expansion — for each seed, find connected nodes
        all_results = []
        seen_ids = set()
        
        for seed in seed_nodes:
            # Add seed to results
            if str(seed.id) not in seen_ids:
                all_results.append({
                    "node_id": str(seed.id),
                    "title": seed.title,
                    "summary": seed.summary,
                    "node_type": seed.node_type,
                    "tree_id": str(seed.tree_id),
                    "memory_domain": seed.memory_domain,
                    "similarity": float(seed.similarity),
                    "graph_weight": 1.0,
                    "combined_score": float(seed.similarity),
                    "source": "semantic",
                })
                seen_ids.add(str(seed.id))
            
            # Expand through graph edges
            if graph_expansion_depth > 0:
                expanded = await self.expand_from_node(
                    UUID(str(seed.id)),
                    max_depth=graph_expansion_depth,
                    max_nodes=5,
                )
                for exp_node in expanded:
                    if exp_node["node_id"] not in seen_ids:
                        combined = float(seed.similarity) * 0.7 + exp_node["weight"] * 0.3
                        all_results.append({
                            **exp_node,
                            "similarity": 0.0,
                            "combined_score": combined,
                            "source": "graph_expansion",
                            "expanded_from": str(seed.id),
                        })
                        seen_ids.add(exp_node["node_id"])
        
        # Step 3: Re-rank by combined score
        all_results.sort(key=lambda x: x["combined_score"], reverse=True)
        return all_results[:top_k * 2]  # Return extra for diversity
    
    # ──────────────────────────────────────────────────────────────────
    # Automatic Edge Creation
    # ──────────────────────────────────────────────────────────────────
    
    async def create_similarity_edges(
        self,
        node_id: UUID,
        tree_id: UUID = None,
    ) -> int:
        """
        After embedding a node, find similar nodes and create
        'semantic_similar' edges automatically.
        """
        node = await self.db.execute(
            select(CortexNode).where(CortexNode.id == node_id)
        )
        node = node.scalar_one_or_none()
        if not node or node.embedding is None:
            return 0
        
        # Find similar nodes (excluding self and same-parent siblings)
        similar = await self.db.execute(text("""
            SELECT cn.id,
                   1 - (cn.embedding <=> CAST(:vec AS vector)) AS similarity
            FROM cortex_nodes cn
            JOIN cortex_trees ct ON ct.id = cn.tree_id
            WHERE cn.id != :node_id
              AND cn.embedding IS NOT NULL
              AND ct.company_id = :company_id
              AND (1 - (cn.embedding <=> CAST(:vec AS vector))) >= :threshold
            ORDER BY cn.embedding <=> CAST(:vec AS vector)
            LIMIT :max_edges
        """), {
            "node_id": str(node_id),
            "vec": json.dumps(list(node.embedding)),
            "company_id": str(self.company_id),
            "threshold": self.SIMILARITY_THRESHOLD,
            "max_edges": self.MAX_AUTO_EDGES_PER_NODE,
        })
        
        count = 0
        for row in similar.fetchall():
            await self.create_edge(
                source_node_id=node_id,
                target_node_id=row.id,
                edge_type="semantic_similar",
                weight=float(row.similarity),
                created_by="embedding_pipeline",
            )
            count += 1
        
        return count
    
    # ──────────────────────────────────────────────────────────────────
    # Co-Access Edge Tracking
    # ──────────────────────────────────────────────────────────────────
    
    async def track_co_access(
        self,
        node_ids: List[UUID],
        execution_run_id: UUID = None,
    ) -> int:
        """
        When multiple nodes are accessed in the same execution step,
        create/strengthen 'co_accessed' edges between them.
        """
        count = 0
        for i, source_id in enumerate(node_ids):
            for target_id in node_ids[i+1:]:
                await self.create_edge(
                    source_node_id=source_id,
                    target_node_id=target_id,
                    edge_type="co_accessed",
                    weight=0.3,
                    created_by="runtime_tracking",
                    metadata={"run_id": str(execution_run_id)} if execution_run_id else None,
                )
                count += 1
        return count
    
    # ──────────────────────────────────────────────────────────────────
    # Graph Maintenance
    # ──────────────────────────────────────────────────────────────────
    
    async def decay_weights(self, days_inactive: int = 30) -> int:
        """
        Decay edge weights that haven't been traversed recently.
        Run as periodic maintenance task.
        """
        result = await self.db.execute(text("""
            UPDATE cortex_edges
            SET weight = GREATEST(:min_weight, weight * :decay_rate)
            WHERE last_traversed_at < NOW() - INTERVAL ':days days'
               OR last_traversed_at IS NULL
            RETURNING id
        """), {
            "min_weight": self.MIN_WEIGHT,
            "decay_rate": self.DECAY_RATE,
            "days": days_inactive,
        })
        return len(result.fetchall())
    
    async def prune_weak_edges(self) -> int:
        """Remove edges below minimum weight threshold."""
        result = await self.db.execute(text("""
            DELETE FROM cortex_edges
            WHERE weight < :min_weight
            RETURNING id
        """), {"min_weight": self.MIN_WEIGHT})
        return len(result.fetchall())
```

### E.3.2 Update Embedding Service for Auto-Edge Creation

**File**: `backend/src/ai/embedding_service.py` (add to existing)

```python
async def embed_node_with_edges(self, node: CortexNode) -> None:
    """Embed a node and automatically create similarity edges."""
    await self.embed_node(node)
    
    if node.embedding is not None:
        graph = SemanticGraphService(self.db, self.company_id)
        await graph.create_similarity_edges(node.id)
```

### E.3.3 Update Memory Service for Graph Search

**File**: `backend/src/ai/memory_service.py`

Replace the existing `search_semantic()` method with a graph-enabled version:

```python
async def search_semantic(
    self,
    entity_id: UUID,
    query: str,
    top_k: int = 5,
    api_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Hybrid semantic + graph search across all memory domains.
    V2: Uses SemanticGraphService for cross-domain search with graph expansion.
    Falls back to V1 (document_chunks) if V2 is unavailable.
    """
    try:
        # V2: Graph-enabled search
        company_id = await self._get_company_id(entity_id)
        if company_id:
            graph = SemanticGraphService(self.db, company_id)
            results = await graph.semantic_graph_search(
                query=query,
                entity_id=entity_id,
                domains=None,  # Search all domains
                top_k=top_k,
                graph_expansion_depth=1,
            )
            if results:
                return [
                    {
                        "content": r.get("summary", ""),
                        "score": r.get("combined_score", 0.0),
                        "node_type": r.get("node_type"),
                        "memory_domain": r.get("memory_domain"),
                        "source": r.get("source", "semantic"),
                    }
                    for r in results
                ]
    except Exception as e:
        logger.debug(f"V2 semantic graph search failed: {e}")
    
    # V1 fallback: document_chunks
    return await self._search_semantic_v1(entity_id, query, top_k, api_key)
```

### E.3.4 Graph Maintenance Worker

**File**: `backend/src/ai/worker.py` (add new worker function)

```python
async def graph_maintenance_worker(ctx):
    """
    Periodic maintenance for the semantic graph.
    Run daily via cron scheduler.
    
    Tasks:
    1. Decay weights on stale edges
    2. Prune edges below minimum weight
    3. Log graph statistics
    """
    async with AsyncSessionLocal() as db:
        # Get all companies with active trees
        companies = await db.execute(text("""
            SELECT DISTINCT company_id FROM cortex_trees WHERE status = 'active'
        """))
        
        total_decayed = 0
        total_pruned = 0
        
        for row in companies.fetchall():
            graph = SemanticGraphService(db, row.company_id)
            decayed = await graph.decay_weights(days_inactive=30)
            pruned = await graph.prune_weak_edges()
            total_decayed += decayed
            total_pruned += pruned
        
        await db.commit()
        logger.info(f"Graph maintenance: {total_decayed} edges decayed, {total_pruned} pruned")
        return {"decayed": total_decayed, "pruned": total_pruned}
```

---

## E.4 Files Changed

| File | Action | Changes |
|---|---|---|
| `backend/src/ai/graph_service.py` | NEW | Semantic graph search, edge management, graph traversal |
| `backend/src/ai/embedding_service.py` | MODIFY | Add auto-edge creation after embedding |
| `backend/src/ai/memory_service.py` | MODIFY | Replace `search_semantic()` with graph-enabled version |
| `backend/src/ai/worker.py` | MODIFY | Add graph_maintenance_worker |
| `backend/src/ai/dreaming_engine.py` | MODIFY | Create edges during pattern/rule creation |

---

## E.5 Performance Considerations

| Concern | Mitigation |
|---|---|
| Graph BFS can be expensive with many edges | `max_depth` cap (default 2), `max_nodes` cap (20) |
| Embedding similarity search across all nodes | IVFFlat/HNSW index on `cortex_nodes.embedding` |
| Edge table growth | Periodic pruning of low-weight edges |
| Cross-domain queries touching many trees | Scope filtering via `company_id` + `entity_id` |
| CTE recursion depth | PostgreSQL max_recursion_depth = 2 |

---

## E.6 Validation Criteria

- [ ] `cortex_edges` populated with edges from Dreaming (Phase D)
- [ ] Automatic `semantic_similar` edges created during embedding
- [ ] Graph expansion returns connected nodes from different domains
- [ ] Hybrid search combines embedding similarity + graph expansion
- [ ] Co-access tracking creates edges during runtime
- [ ] Weight decay reduces stale edge weights
- [ ] Pruning removes edges below MIN_WEIGHT
- [ ] Memory service uses graph search with V1 fallback
- [ ] Performance: graph search completes < 500ms for typical queries
