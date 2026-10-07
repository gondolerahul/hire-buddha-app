# Phase F: Runtime Assembly — Unified Memory Pipeline

**Timeline**: Week 11–12  
**Risk Level**: HIGH  
**Dependencies**: ALL prior phases (A through E)  
**Goal**: Refactor the execution engine to assemble memory from all four domains at runtime, inject Intelligence rules into planning, and manage runtime tree lifecycle with the full v2 architecture.

---

## F.1 Executive Summary

Phase F is the integration phase that ties everything together. It modifies the core execution pipeline (`worker.py` → `ExecutionEngine`) to:

1. **Assemble** a Runtime Tree from all four memory domains at execution start
2. **Inject** Intelligence rules and Experience suggestions into planning/prompts
3. **Track** node access patterns and co-access for graph learning
4. **Write back** execution results into Episodic and Experience domains
5. **Retire** v1 codepaths (flat episodic, document_chunks-only search)

This is the final phase where the agent transitions from the v1 "three-tier MemoryRouter" to the unified v2 "four-domain assembled memory" architecture.

---

## F.2 Runtime Memory Assembly Pipeline

```
┌──────────────────────────────────────────────────────────────────────┐
│                    RUNTIME MEMORY ASSEMBLY                          │
│                    (Called at execution start)                       │
│                                                                      │
│  1. KNOWLEDGE        2. EXPERIENCE        3. INTELLIGENCE            │
│     Assembly            Retrieval            Injection               │
│                                                                      │
│  Query entity's      Query entity's       Query entity's             │
│  Knowledge Trees     Experience Tree       Intelligence Tree         │
│  by task relevance   for suggestions       for applicable rules      │
│                                                                      │
│  Create REFERENCE    Inject suggestions    Inject rules into         │
│  nodes in Runtime    into context_state    system prompt AND         │
│  Knowledge Root      as advisories         planning prompts          │
│                                                                      │
│  4. EPISODIC         5. ASSEMBLY           6. CONTEXT                │
│     Context             Finalization          Injection              │
│                                                                      │
│  Query recent        Merge all domains     Format for prompt:        │
│  episodes for        into unified          [INTELLIGENCE] rules      │
│  continuity          context dict          [KNOWLEDGE] references    │
│  signals                                   [EXPERIENCE] suggestions  │
│                                             [EPISODIC] recent runs   │
│                                             [CORTEX VIEWPORT]        │
└──────────────────────────────────────────────────────────────────────┘
```

---

## F.3 Detailed Implementation

### F.3.1 Memory Assembly Service

**New file**: `backend/src/ai/memory_assembly_service.py`

This is the central orchestrator replacing the simple `MemoryRouter.retrieve()`:

```python
class MemoryAssemblyService:
    """
    Unified Memory Assembly Pipeline for v2.
    
    Replaces MemoryRouter.retrieve() with a comprehensive assembly
    that draws from all four memory domains:
    - Knowledge (reference nodes from persistent KB trees)
    - Experience (suggestions from learned patterns)
    - Intelligence (distilled rules and strategies)
    - Episodic (recent execution history)
    """
    
    def __init__(self, db: AsyncSession, company_id: UUID):
        self.db = db
        self.company_id = company_id
    
    async def assemble_runtime_memory(
        self,
        entity_id: UUID,
        user_id: UUID = None,
        task_description: str = "",
        runtime_tree: CortexTree = None,
        include_domains: List[str] = None,
    ) -> MemoryAssemblyResult:
        """
        Assemble memory from all four domains for a new execution.
        
        Returns a MemoryAssemblyResult containing:
        - knowledge_refs: Reference nodes from Knowledge Trees
        - experience_suggestions: Suggestions from Experience Tree
        - intelligence_rules: Rules from Intelligence Tree
        - episodic_context: Recent episode summaries
        - formatted_prompt: Pre-formatted text for system prompt injection
        """
        domains = include_domains or ["knowledge", "experience", "intelligence", "episodic"]
        result = MemoryAssemblyResult()
        
        # 1. KNOWLEDGE ASSEMBLY
        if "knowledge" in domains:
            result.knowledge_refs = await self._assemble_knowledge(
                entity_id, task_description, runtime_tree
            )
        
        # 2. EXPERIENCE RETRIEVAL
        if "experience" in domains:
            result.experience_suggestions = await self._retrieve_experience(
                entity_id, task_description
            )
        
        # 3. INTELLIGENCE INJECTION
        if "intelligence" in domains:
            result.intelligence_rules = await self._retrieve_intelligence(
                entity_id, task_description
            )
        
        # 4. EPISODIC CONTEXT
        if "episodic" in domains:
            result.episodic_context = await self._retrieve_episodic(
                entity_id, user_id, task_description
            )
        
        # 5. Format for prompt
        result.formatted_prompt = self._format_assembled_memory(result)
        
        return result
    
    async def _assemble_knowledge(
        self,
        entity_id: UUID,
        task_description: str,
        runtime_tree: CortexTree = None,
    ) -> List[Dict]:
        """
        Find relevant knowledge nodes and create reference nodes
        in the runtime tree's Knowledge Root.
        
        Uses semantic graph search to find relevant knowledge across
        all scope levels visible to this entity.
        """
        graph = SemanticGraphService(self.db, self.company_id)
        
        # Search across Knowledge Trees at all accessible scope levels
        results = await graph.semantic_graph_search(
            query=task_description,
            entity_id=entity_id,
            domains=["knowledge"],
            top_k=10,
            graph_expansion_depth=1,
        )
        
        if not results or not runtime_tree:
            return results or []
        
        # Create reference nodes in runtime tree's Knowledge Root
        cortex = CortexRouter(self.db, self.company_id)
        knowledge_root = await cortex.get_knowledge_root(runtime_tree.id)
        
        if knowledge_root:
            for item in results[:5]:  # Top 5 references
                try:
                    await cortex.write(
                        parent_id=knowledge_root.id,
                        node_type="knowledge",
                        title=f"📎 {item['title'][:100]}",
                        summary=item.get("summary", ""),
                        content=None,  # Reference-not-copy
                        source_ref={
                            "ref_type": "cortex_node",
                            "source_tree_id": item.get("tree_id"),
                            "source_node_id": item.get("node_id"),
                            "relevance_score": item.get("combined_score", 0),
                        },
                    )
                except Exception as e:
                    logger.debug(f"Knowledge reference creation failed: {e}")
        
        return results
    
    async def _retrieve_experience(
        self,
        entity_id: UUID,
        task_description: str,
    ) -> List[Dict]:
        """
        Query Experience Tree for suggestions relevant to the current task.
        Returns suggestions and patterns that might inform execution.
        """
        try:
            experience_service = ExperienceTreeService(self.db, self.company_id)
            experience_tree = await experience_service.get_or_create_experience_tree(
                entity_id, self.company_id
            )
            
            # Semantic search for relevant suggestions and patterns
            graph = SemanticGraphService(self.db, self.company_id)
            results = await graph.semantic_graph_search(
                query=task_description,
                entity_id=entity_id,
                domains=["experience"],
                top_k=5,
            )
            
            return [
                {
                    "suggestion": r.get("summary"),
                    "type": r.get("node_type"),
                    "confidence": r.get("combined_score", 0),
                }
                for r in results
                if r.get("node_type") in ("suggestion", "pattern")
            ]
        except Exception as e:
            logger.debug(f"Experience retrieval failed: {e}")
            return []
    
    async def _retrieve_intelligence(
        self,
        entity_id: UUID,
        task_description: str,
    ) -> List[Dict]:
        """
        Query Intelligence Tree for applicable rules, strategies,
        and preferences. These are injected into both the system
        prompt AND the planning prompt.
        """
        try:
            intelligence_service = IntelligenceTreeService(self.db, self.company_id)
            return await intelligence_service.get_applicable_rules(
                entity_id=entity_id,
                company_id=self.company_id,
                task_description=task_description,
                max_rules=10,
            )
        except Exception as e:
            logger.debug(f"Intelligence retrieval failed: {e}")
            return []
    
    async def _retrieve_episodic(
        self,
        entity_id: UUID,
        user_id: UUID = None,
        task_description: str = "",
    ) -> List[Dict]:
        """
        Retrieve recent and topically relevant episodes.
        Combines temporal recency with semantic relevance.
        """
        try:
            episodic_service = EpisodicTreeService(self.db, self.company_id)
            
            # Recent episodes (last 7 days)
            recent = await episodic_service.query_episodes_by_time(
                entity_id=entity_id,
                company_id=self.company_id,
                start_date=datetime.utcnow() - timedelta(days=7),
                end_date=datetime.utcnow(),
                limit=5,
            )
            
            # Topic-relevant episodes (semantic search)
            relevant = []
            if task_description:
                relevant = await episodic_service.query_episodes_by_topic(
                    entity_id=entity_id,
                    company_id=self.company_id,
                    query=task_description,
                    top_k=3,
                )
            
            # Merge and deduplicate
            seen_ids = set()
            episodes = []
            for ep in recent + relevant:
                ep_id = str(ep.id) if hasattr(ep, 'id') else str(ep.get('id', ''))
                if ep_id not in seen_ids:
                    episodes.append(self._format_episode_node(ep))
                    seen_ids.add(ep_id)
            
            return episodes[:10]
        except Exception as e:
            logger.debug(f"Episodic retrieval failed: {e}")
            return []
    
    def _format_assembled_memory(self, result: 'MemoryAssemblyResult') -> str:
        """
        Format the assembled memory into structured prompt text.
        
        Layout:
        [INTELLIGENCE] — Rules and strategies (highest priority)
        [KNOWLEDGE] — Relevant KB references
        [EXPERIENCE] — Suggestions from past patterns
        [EPISODIC] — Recent execution history
        """
        parts = []
        
        # Intelligence Rules (highest priority — goes first)
        if result.intelligence_rules:
            rule_lines = []
            for rule in result.intelligence_rules:
                confidence = rule.get("confidence", 0.5)
                emoji = "📏" if rule.get("type") == "instruction" else "🎯" if rule.get("type") == "strategy" else "❤️"
                rule_lines.append(f"  {emoji} [{confidence:.0%}] {rule['rule']}")
            parts.append(
                "## Learned Intelligence\n"
                "The following rules have been learned from past experience:\n"
                + "\n".join(rule_lines)
            )
        
        # Knowledge References
        if result.knowledge_refs:
            kb_lines = [
                f"  📎 [{r.get('combined_score', 0):.2f}] {r.get('title', 'Untitled')}: {r.get('summary', '')[:200]}"
                for r in result.knowledge_refs[:5]
            ]
            parts.append("## Relevant Knowledge\n" + "\n".join(kb_lines))
        
        # Experience Suggestions
        if result.experience_suggestions:
            exp_lines = [
                f"  💡 [{s.get('confidence', 0):.2f}] {s['suggestion'][:200]}"
                for s in result.experience_suggestions
            ]
            parts.append("## Experience Suggestions\n" + "\n".join(exp_lines))
        
        # Episodic Context
        if result.episodic_context:
            ep_lines = []
            for ep in result.episodic_context[:5]:
                inp = (ep.get("input") or "")[:150]
                out = (ep.get("output") or "")[:150]
                at = ep.get("at", "")
                ep_lines.append(f"  [{at}] {inp!r} → {out!r}")
            parts.append("## Recent Execution History\n" + "\n".join(ep_lines))
        
        return "\n\n".join(parts)


@dataclass
class MemoryAssemblyResult:
    """Container for assembled memory from all four domains."""
    knowledge_refs: List[Dict] = field(default_factory=list)
    experience_suggestions: List[Dict] = field(default_factory=list)
    intelligence_rules: List[Dict] = field(default_factory=list)
    episodic_context: List[Dict] = field(default_factory=list)
    formatted_prompt: str = ""
```

### F.3.2 Update ExecutionEngine.execute_run()

**File**: `backend/src/ai/worker.py`

Replace the memory retrieval and context assembly section (lines ~718-846):

```python
# ======== REPLACE THIS SECTION ========
# C2: Retrieve memory context with tree ID
# memory_router = MemoryRouter(self.db)
# memory_ctx = await memory_router.retrieve(...)

# ======== WITH THIS ========
# C2: Assemble unified memory from all four domains
from src.ai.memory_assembly_service import MemoryAssemblyService
memory_assembler = MemoryAssemblyService(self.db, entity.company_id)

task_desc = tree.task_description or self._build_task_description(entity, input_data)
memory_result = await memory_assembler.assemble_runtime_memory(
    entity_id=entity.id,
    user_id=run.user_id,
    task_description=task_desc,
    runtime_tree=tree,
)

# C3: Build context from assembled memory + viewport
context_state = input_data.copy()
if memory_result.formatted_prompt:
    context_state["__memory__"] = memory_result.formatted_prompt
context_state["__cortex_viewport__"] = viewport.to_prompt_text()
context_state["__cortex_tree_id__"] = str(tree.id)

# Inject intelligence rules separately (for planning prompt)
if memory_result.intelligence_rules:
    context_state["__intelligence__"] = json.dumps(memory_result.intelligence_rules)

# Inject experience suggestions
if memory_result.experience_suggestions:
    context_state["__experience__"] = json.dumps(memory_result.experience_suggestions)
```

### F.3.3 Intelligence-Aware Planning

**File**: `backend/src/ai/planner_service.py`

Inject Intelligence rules into the planning prompt:

```python
async def generate_plan(self, entity, input_data, context_state):
    """Generate a plan with Intelligence-aware prompt injection."""
    
    # Existing planning logic...
    
    # NEW: Inject learned rules into planning system prompt
    intelligence_json = context_state.get("__intelligence__")
    if intelligence_json:
        try:
            rules = json.loads(intelligence_json)
            rules_text = "\n".join([
                f"- [{r.get('type', 'rule')}] {r['rule']}"
                for r in rules
            ])
            system_prompt += (
                "\n\n## Learned Rules (from past execution analysis)\n"
                "Apply these rules when creating the plan:\n"
                f"{rules_text}\n"
            )
        except Exception:
            pass
    
    # ... rest of planning logic
```

### F.3.4 Runtime Access Tracking

**File**: `backend/src/ai/cortex_bridge.py`

Add access pattern tracking during execution:

```python
async def track_node_access(
    self,
    node_ids: List[UUID],
    run_id: UUID,
) -> None:
    """Track which nodes were accessed together in this step."""
    try:
        graph = SemanticGraphService(self.db, self.company_id)
        await graph.track_co_access(node_ids, run_id)
    except Exception as e:
        logger.debug(f"Co-access tracking failed: {e}")
```

### F.3.5 Post-Execution Writebacks

**File**: `backend/src/ai/worker.py` (in `execute_run()`, after finalization)

```python
# After successful completion (line ~1084):

# V2 Writebacks
try:
    # 1. Write episodic tree entry (replaces MemoryRouter.write_episodic)
    from src.ai.episodic_tree_service import EpisodicTreeService
    episodic = EpisodicTreeService(self.db, entity.company_id)
    await episodic.write_episode(
        entity_id=entity.id,
        company_id=entity.company_id,
        run=run,
        runtime_tree_id=tree.id,
    )
    
    # 2. Schedule dreaming if threshold met
    from src.ai.dreaming_engine import DreamingEngine
    dreamer = DreamingEngine(self.db, entity.company_id)
    if await dreamer._should_run(entity.id, entity.company_id):
        try:
            arq_redis = ArqRedis(self.redis.client)
            await arq_redis.enqueue_job(
                "dreaming_worker",
                str(entity.id),
                str(entity.company_id),
            )
        except Exception:
            pass
    
    # 3. Mark runtime tree as complete (or keep active for resume)
    if not run.context_state.get("__pending_resume__"):
        tree.status = CortexTreeStatus.COMPLETE
    
except Exception as e:
    logger.warning(f"V2 post-execution writebacks failed: {e}")
```

### F.3.6 V1 Deprecation Path

**File**: `backend/src/ai/memory_service.py`

Mark the old `MemoryRouter` as deprecated:

```python
class MemoryRouter:
    """
    DEPRECATED: Use MemoryAssemblyService instead.
    
    This class is retained for backward compatibility during the transition
    period. It will be removed in the next major version.
    
    Routes memory reads/writes across three tiers: WORKING → EPISODIC → SEMANTIC.
    """
    
    _DEPRECATION_WARNING_ISSUED = False
    
    def __init__(self, db):
        if not MemoryRouter._DEPRECATION_WARNING_ISSUED:
            logger.warning(
                "MemoryRouter is deprecated. Use MemoryAssemblyService for v2 memory."
            )
            MemoryRouter._DEPRECATION_WARNING_ISSUED = True
        self.db = db
        ...
```

---

## F.4 Data Flow: Before and After

### Before (v1)
```
ExecutionRun Start
  ├── MemoryRouter.retrieve()
  │   ├── _load_episodic() → SELECT FROM episodic_memories LIMIT 10
  │   ├── search_semantic() → embed query → document_chunks cosine search
  │   └── Load CORTEX viewport (if tree_id)
  ├── Execute steps
  │   └── Write findings to runtime CORTEX tree
  └── MemoryRouter.write_episodic()
      └── INSERT INTO episodic_memories (prune to 10)
```

### After (v2)
```
ExecutionRun Start
  ├── MemoryAssemblyService.assemble_runtime_memory()
  │   ├── _assemble_knowledge() → Graph search across Knowledge Trees → Reference nodes
  │   ├── _retrieve_experience() → Semantic search in Experience Tree → Suggestions
  │   ├── _retrieve_intelligence() → Semantic search in Intelligence Tree → Rules
  │   ├── _retrieve_episodic() → Temporal + semantic query in Episodic Tree
  │   └── _format_assembled_memory() → Structured prompt injection
  ├── Intelligence-Aware Planning
  │   └── Rules injected into planning system prompt
  ├── Execute steps
  │   ├── Write findings to runtime CORTEX tree
  │   ├── Track co-accessed nodes → cortex_edges
  │   └── Reference resolution on READ (cross-tree)
  └── Post-Execution Writebacks
      ├── EpisodicTreeService.write_episode() → Episodic Tree
      ├── Schedule DreamingEngine → Background worker
      └── Mark runtime tree COMPLETE/ACTIVE
```

---

## F.5 Files Changed

| File | Action | Changes |
|---|---|---|
| `backend/src/ai/memory_assembly_service.py` | NEW | Central memory assembly orchestrator |
| `backend/src/ai/worker.py` | MODIFY | Replace MemoryRouter with MemoryAssemblyService |
| `backend/src/ai/planner_service.py` | MODIFY | Intelligence-aware planning |
| `backend/src/ai/cortex_bridge.py` | MODIFY | Access tracking, co-access edges |
| `backend/src/ai/memory_service.py` | MODIFY | Deprecation warning, v1 retained as fallback |

---

## F.6 Rollback Strategy

| Component | Rollback Method |
|---|---|
| Memory Assembly | Feature flag: `USE_V2_MEMORY=false` → falls back to `MemoryRouter.retrieve()` |
| Intelligence Planning | Remove rules from planning prompt → no behavior change |
| Episodic Trees | Dual-write still writes to flat table → revert to flat table read |
| Graph Search | Fallback to `search_semantic_v1()` (document_chunks) |

### Feature Flag Implementation

```python
# In worker.py execute_run():
USE_V2_MEMORY = os.environ.get("USE_V2_MEMORY", "true").lower() == "true"

if USE_V2_MEMORY:
    memory_assembler = MemoryAssemblyService(self.db, entity.company_id)
    memory_result = await memory_assembler.assemble_runtime_memory(...)
    # ... v2 context injection
else:
    memory_router = MemoryRouter(self.db)
    memory_ctx = await memory_router.retrieve(...)
    # ... v1 context injection
```

---

## F.7 Validation Criteria

- [ ] Memory assembly draws from all four domains
- [ ] Intelligence rules appear in system prompts
- [ ] Intelligence rules influence planning decisions
- [ ] Knowledge references resolve correctly on READ
- [ ] Co-access edges created during multi-node execution
- [ ] Episodic writebacks write to Episodic Trees
- [ ] Dreaming scheduled after execution completion
- [ ] Feature flag works: `USE_V2_MEMORY=false` falls back to v1
- [ ] Runtime tree lifecycle (ACTIVE → COMPLETE) works correctly
- [ ] Overall execution latency increase < 500ms from memory assembly
- [ ] No regressions in existing test suite

---

## F.8 Post-Phase F: Cleanup Tasks

After Phase F is stable in production (2–4 weeks):

1. **Remove dual-write**: Stop writing to `episodic_memories` flat table
2. **Remove dual-write**: Stop writing to `document_chunks` table for new documents
3. **Deprecate MemoryRouter**: Replace all remaining imports with MemoryAssemblyService
4. **Archive tables**: Mark `episodic_memories` and `document_chunks` as read-only legacy
5. **Performance optimization**: Profile memory assembly latency, optimize queries
6. **Dashboard**: Build admin dashboard for Experience/Intelligence tree inspection
