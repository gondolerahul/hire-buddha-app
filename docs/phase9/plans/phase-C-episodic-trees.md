# Phase C: Episodic Trees — Structured Execution History

**Timeline**: Week 5  
**Risk Level**: LOW–MEDIUM  
**Dependencies**: Phase A (schema), Phase B (Knowledge Trees for `source_ref` patterns)  
**Goal**: Replace the flat `episodic_memories` table with hierarchical Episodic Trees per entity, organized chronologically with deep-dive links to runtime trees.

---

## C.1 Executive Summary

Phase C transforms episodic memory from a flat table (`episodic_memories`) with a fixed 10-row limit per entity into persistent CORTEX Episodic Trees organized as `MONTH → DAY → EPISODE` hierarchies. Each entity gets exactly one Episodic Tree that grows indefinitely with episodes appended after each execution. This eliminates the arbitrary 10-episode limit, enables temporal querying, and allows agents to deep-dive into past runtime trees for detailed recall.

---

## C.2 Current State Analysis

### What Exists Today

| Aspect | Current Implementation |
|---|---|
| Storage | `episodic_memories` flat table |
| Records per entity | Capped at 10 (pruned by `_prune_old_episodes()`) |
| Query pattern | `SELECT ... ORDER BY created_at DESC LIMIT 10` |
| Content | `input_summary` + `output_summary` (1000 chars each) |
| Structure | Flat rows — no grouping, no hierarchy |
| Deep dive | `tree_id` FK exists but never used |
| Cross-entity | Not supported |

### Key Design Decisions (Addressing v1 Objections)

| Original Concern (from deep-analysis-part1) | v2 Solution |
|---|---|
| Different Lifecycles: Episodic is cross-run, trees are per-run | Episodic Trees are persistent (separate from Runtime Trees) |
| Temporal Ordering: Trees are spatial, not temporal | Episode nodes grouped by date (Month → Day), ordered by `created_at` |
| Tree Independence: Loading previous tree for history | Each entity has ONE persistent Episodic Tree — no cross-tree loading |

---

## C.3 Detailed Implementation

### C.3.1 Episodic Tree Structure

```
Episodic Tree Root (L4: Entity "Research Assistant")
├── 📅 2026-05 (Month Group — node_type: EPISODE_GROUP)
│   ├── 📅 2026-05-15 (Day Group — node_type: EPISODE_GROUP)
│   │   ├── 🎬 Episode: "Q3 Revenue Analysis" (node_type: EPISODE)
│   │   │   metadata_extra: {
│   │   │     input: "Analyze Q3 revenue trends for APAC region",
│   │   │     output: "Report generated with 5 sections...",
│   │   │     status: "COMPLETED",
│   │   │     cost_usd: 0.45,
│   │   │     total_tokens: 25000,
│   │   │     execution_time_ms: 32000,
│   │   │     tools_used: ["web_search", "scraper_tool"],
│   │   │     runtime_tree_id: "uuid-of-runtime-tree",
│   │   │     run_id: "uuid-of-execution-run"
│   │   │   }
│   │   └── 🎬 Episode: "Competitor Analysis" (node_type: EPISODE)
│   │       ...
│   └── 📅 2026-05-14 (Day Group)
│       └── ...
└── 📅 2026-04 (Month Group)
    └── ...
```

### C.3.2 Episodic Tree Service

**New file**: `backend/src/ai/episodic_tree_service.py`

```python
class EpisodicTreeService:
    """Manages persistent Episodic Trees per entity."""
    
    async def get_or_create_episodic_tree(
        self,
        entity_id: UUID,
        company_id: UUID,
    ) -> CortexTree:
        """
        Get or create the single persistent Episodic Tree for an entity.
        Each entity has exactly one Episodic Tree that grows indefinitely.
        """
        stmt = select(CortexTree).where(
            CortexTree.memory_domain == MemoryDomain.EPISODIC,
            CortexTree.scope_level == ScopeLevel.ENTITY,
            CortexTree.entity_id == entity_id,
            CortexTree.company_id == company_id,
        )
        result = await self.db.execute(stmt)
        tree = result.scalar_one_or_none()
        
        if tree:
            return tree
        
        # Create new Episodic Tree
        tree = CortexTree(
            id=uuid4(),
            entity_id=entity_id,
            company_id=company_id,
            memory_domain=MemoryDomain.EPISODIC,
            scope_level=ScopeLevel.ENTITY,
            task_description=f"Episodic memory for entity {entity_id}",
            status=CortexTreeStatus.ACTIVE,
            is_persistent=True,
            total_nodes=0,
        )
        self.db.add(tree)
        
        # Create root node
        root = CortexNode(
            tree_id=tree.id,
            node_type=CortexNodeType.ROOT,
            title="📚 Execution History",
            summary="Chronological record of all executions for this entity.",
            depth=0,
            status=CortexNodeStatus.ACTIVE,
        )
        self.db.add(root)
        
        tree.root_node_id = root.id
        tree.total_nodes = 1
        await self.db.flush()
        return tree
    
    async def write_episode(
        self,
        entity_id: UUID,
        company_id: UUID,
        run: ExecutionRun,
        runtime_tree_id: UUID = None,
    ) -> UUID:
        """
        Write a completed execution as an Episode node in the Episodic Tree.
        Automatically creates Month and Day group nodes as needed.
        """
        tree = await self.get_or_create_episodic_tree(entity_id, company_id)
        
        now = datetime.utcnow()
        month_key = now.strftime("%Y-%m")
        day_key = now.strftime("%Y-%m-%d")
        
        # Get or create month group
        month_node = await self._get_or_create_group(
            tree_id=tree.id,
            parent_id=tree.root_node_id,
            group_key=month_key,
            title=f"📅 {now.strftime('%B %Y')}",
        )
        
        # Get or create day group
        day_node = await self._get_or_create_group(
            tree_id=tree.id,
            parent_id=month_node,
            group_key=day_key,
            title=f"📅 {now.strftime('%A, %B %d, %Y')}",
        )
        
        # Build episode content
        input_summary = _summarize(run.input_data, max_chars=1000)
        output_summary = _summarize(run.result_data, max_chars=1000)
        
        tools_used = self._extract_tools_used(run.context_state)
        
        episode_title = self._generate_episode_title(run, input_summary)
        
        # Write episode node
        cortex = CortexRouter(self.db, company_id)
        episode_node_id = await cortex.write(
            parent_id=day_node,
            node_type="episode",
            title=f"🎬 {episode_title}",
            summary=f"[{run.status}] {input_summary[:200]} → {output_summary[:200]}",
            content=json.dumps({
                "input": input_summary,
                "output": output_summary,
                "status": str(run.status),
            }),
            metadata_extra={
                "run_id": str(run.id),
                "runtime_tree_id": str(runtime_tree_id) if runtime_tree_id else None,
                "status": str(run.status),
                "cost_usd": float(run.total_cost_usd or 0),
                "total_tokens": run.total_tokens or 0,
                "execution_time_ms": run.execution_time_ms,
                "tools_used": tools_used,
                "channel": run.context_state.get("channel", "text") if run.context_state else "text",
            },
            source_ref={
                "ref_type": "execution_run",
                "run_id": str(run.id),
                "runtime_tree_id": str(runtime_tree_id) if runtime_tree_id else None,
            },
        )
        
        # Generate embedding for the episode
        embedding_service = EmbeddingService(self.db, company_id)
        episode_node = await cortex._get_node(episode_node_id)
        await embedding_service.embed_node(episode_node)
        
        return episode_node_id
    
    async def _get_or_create_group(
        self,
        tree_id: UUID,
        parent_id: UUID,
        group_key: str,
        title: str,
    ) -> UUID:
        """Get or create a date-based group node (Month or Day)."""
        # Check if group already exists
        result = await self.db.execute(
            select(CortexNode).where(
                CortexNode.tree_id == tree_id,
                CortexNode.parent_id == parent_id,
                CortexNode.node_type == CortexNodeType.EPISODE_GROUP,
                CortexNode.title == title,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing.id
        
        # Create new group
        cortex = CortexRouter(self.db, self.company_id)
        return await cortex.write(
            parent_id=parent_id,
            node_type="episode_group",
            title=title,
            summary=f"Execution episodes for {group_key}",
            metadata_extra={"group_key": group_key},
        )
```

### C.3.3 Temporal Query Support

**File**: `backend/src/ai/episodic_tree_service.py`

```python
async def query_episodes_by_time(
    self,
    entity_id: UUID,
    company_id: UUID,
    start_date: datetime,
    end_date: datetime,
    limit: int = 20,
) -> List[CortexNode]:
    """
    Non-linear temporal hop — query episode nodes by datetime range
    without traversing the tree top-down. Direct SQL query.
    """
    tree = await self.get_or_create_episodic_tree(entity_id, company_id)
    
    result = await self.db.execute(
        select(CortexNode)
        .where(
            CortexNode.tree_id == tree.id,
            CortexNode.node_type == CortexNodeType.EPISODE,
            CortexNode.created_at >= start_date,
            CortexNode.created_at <= end_date,
        )
        .order_by(CortexNode.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()

async def query_episodes_by_topic(
    self,
    entity_id: UUID,
    company_id: UUID,
    query: str,
    top_k: int = 5,
) -> List[CortexNode]:
    """
    Semantic search across episode nodes — find past runs
    related to a topic.
    """
    tree = await self.get_or_create_episodic_tree(entity_id, company_id)
    
    embedding_service = EmbeddingService(self.db, company_id)
    query_embedding = await embedding_service.embed_text(query)
    
    if not query_embedding:
        return []
    
    result = await self.db.execute(text("""
        SELECT cn.*
        FROM cortex_nodes cn
        WHERE cn.tree_id = :tree_id
          AND cn.node_type = 'episode'
          AND cn.embedding IS NOT NULL
        ORDER BY cn.embedding <=> CAST(:vec AS vector)
        LIMIT :top_k
    """), {
        "tree_id": str(tree.id),
        "vec": json.dumps(query_embedding),
        "top_k": top_k,
    })
    return result.fetchall()
```

### C.3.4 Update `MemoryRouter.write_episodic()`

**File**: `backend/src/ai/memory_service.py`

```python
async def write_episodic(self, run: Any) -> Optional[UUID]:
    """
    Write episodic memory — DUAL WRITE during transition:
    1. Existing flat table (backward compat)
    2. New Episodic Tree (v2)
    """
    if getattr(run, "parent_run_id", None) is not None:
        return None
    
    # --- V1: Write to flat table (existing behavior) ---
    episode_record = await self._write_episodic_v1(run)
    
    # --- V2: Write to Episodic Tree ---
    try:
        from src.ai.episodic_tree_service import EpisodicTreeService
        episodic_service = EpisodicTreeService(self.db, run.company_id)
        
        # Extract runtime tree ID from context
        ctx = run.context_state or {}
        runtime_tree_id = ctx.get("__cortex_tree_id__")
        
        episode_node_id = await episodic_service.write_episode(
            entity_id=run.entity_id,
            company_id=run.company_id,
            run=run,
            runtime_tree_id=UUID(runtime_tree_id) if runtime_tree_id else None,
        )
        logger.info(f"Episodic Tree: Written episode {episode_node_id} for run {run.id}")
    except Exception as e:
        logger.warning(f"Episodic Tree write failed for run {run.id}: {e}")
    
    return episode_record
```

### C.3.5 Update `MemoryRouter.retrieve()` for Episodic Trees

**File**: `backend/src/ai/memory_service.py`

```python
async def _load_episodic(self, entity_id, user_id) -> List[Dict]:
    """
    Load episodic memories — prefers Episodic Tree (v2), falls back to flat table (v1).
    """
    # Try v2 first
    try:
        from src.ai.episodic_tree_service import EpisodicTreeService
        company_id = await self._get_company_id(entity_id)
        if company_id:
            episodic_service = EpisodicTreeService(self.db, company_id)
            episodes = await episodic_service.query_episodes_by_time(
                entity_id=entity_id,
                company_id=company_id,
                start_date=datetime.utcnow() - timedelta(days=30),
                end_date=datetime.utcnow(),
                limit=10,
            )
            if episodes:
                return [self._format_episode_node(ep) for ep in episodes]
    except Exception as e:
        logger.debug(f"Episodic Tree load failed, falling back to flat table: {e}")
    
    # Fall back to v1 flat table
    return await self._load_episodic_v1(entity_id, user_id)
```

### C.3.6 Data Migration: `episodic_memories` → Episodic Trees

**New file**: `backend/src/ai/migrations/migrate_episodic_to_trees.py`

```python
async def migrate_entity_episodes(entity_id: UUID, company_id: UUID):
    """Migrate existing episodic_memories rows into an Episodic Tree."""
    
    episodic_service = EpisodicTreeService(db, company_id)
    tree = await episodic_service.get_or_create_episodic_tree(entity_id, company_id)
    
    # Load all existing episodic memories for this entity
    result = await db.execute(
        select(EpisodicMemory)
        .where(EpisodicMemory.entity_id == entity_id)
        .order_by(EpisodicMemory.created_at)
    )
    memories = result.scalars().all()
    
    for mem in memories:
        # Create episode node with historical timestamp
        cortex = CortexRouter(db, company_id)
        
        # Get/create month and day groups
        month_key = mem.created_at.strftime("%Y-%m")
        day_key = mem.created_at.strftime("%Y-%m-%d")
        
        month_node = await episodic_service._get_or_create_group(
            tree.id, tree.root_node_id, month_key,
            f"📅 {mem.created_at.strftime('%B %Y')}"
        )
        day_node = await episodic_service._get_or_create_group(
            tree.id, month_node, day_key,
            f"📅 {mem.created_at.strftime('%A, %B %d, %Y')}"
        )
        
        # Write episode
        await cortex.write(
            parent_id=day_node,
            node_type="episode",
            title=f"🎬 {(mem.input_summary or 'Execution')[:100]}",
            summary=f"[{mem.status}] {(mem.input_summary or '')[:200]} → {(mem.output_summary or '')[:200]}",
            content=json.dumps({
                "input": mem.input_summary,
                "output": mem.output_summary,
                "status": mem.status,
            }),
            metadata_extra={
                "run_id": str(mem.run_id) if mem.run_id else None,
                "runtime_tree_id": str(mem.tree_id) if mem.tree_id else None,
                "status": mem.status,
                "cost_usd": float(mem.total_cost_usd or 0),
                "total_tokens": mem.total_tokens or 0,
                "execution_time_ms": mem.execution_time_ms,
                "migrated_from": "episodic_memories",
                "original_id": str(mem.id),
            },
            source_ref={
                "ref_type": "execution_run",
                "run_id": str(mem.run_id) if mem.run_id else None,
                "runtime_tree_id": str(mem.tree_id) if mem.tree_id else None,
            },
        )
```

---

## C.4 Files Changed

| File | Action | Changes |
|---|---|---|
| `backend/src/ai/episodic_tree_service.py` | NEW | Episodic Tree management, temporal & semantic queries |
| `backend/src/ai/memory_service.py` | MODIFY | Dual-write episodic, v2 retrieval with fallback |
| `backend/src/ai/migrations/migrate_episodic_to_trees.py` | NEW | Data migration script |
| `backend/src/ai/worker.py` | MODIFY | Pass `runtime_tree_id` to `write_episodic()` |

---

## C.5 Backward Compatibility

- `episodic_memories` table retained as read-only fallback
- `write_episodic()` dual-writes to both v1 table and v2 tree
- `_load_episodic()` tries v2 first, falls back to v1
- No pruning in v2 (episodes are never deleted — importance scores handle relevance)

---

## C.6 Validation Criteria

- [ ] Episodic Tree created per entity on first execution
- [ ] Episodes correctly organized in Month → Day hierarchy
- [ ] Temporal query returns correct date-range results
- [ ] Semantic query returns topically relevant past episodes
- [ ] Deep-dive link (`runtime_tree_id`) resolves correctly
- [ ] Existing `episodic_memories` data migrated to trees
- [ ] Fallback to flat table works when Episodic Tree doesn't exist
- [ ] No episode limit (unlimited growth, importance-based relevance)
