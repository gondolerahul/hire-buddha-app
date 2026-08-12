# Phase D: Experience & Intelligence Trees — The Learning Engine

**Timeline**: Week 6–8  
**Risk Level**: HIGH  
**Dependencies**: Phase A (schema), Phase B (Knowledge Trees), Phase C (Episodic Trees)  
**Goal**: Implement the automated "Dreaming" process that extracts Experience patterns from Episodic Trees and distills Intelligence rules from Experience Trees.

---

## D.1 Executive Summary

Phase D implements the two highest-order memory domains — **Experience** (what works) and **Intelligence** (what to do) — via automated background processes. These trees are populated by the "Dreaming" algorithms: a three-phase learning pipeline that runs asynchronously to consolidate knowledge from raw episodic data into actionable rules and strategies. This is the phase that gives agents genuine learning capabilities.

---

## D.2 Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    DREAMING PIPELINE                        │
│                                                             │
│  Phase 1: Extract      Phase 2: Pattern       Phase 3:     │
│  Observations  ────▶  Recognition    ────▶   Distillation  │
│                                                             │
│  Raw episode           Cross-episode          Actionable    │
│  analysis              pattern matching       rules &       │
│  What happened?        What recurs?           strategies    │
│                                                             │
│  Source: Episodic Tree  Source: Observations   Source:       │
│  Target: Experience     Target: Experience     Patterns     │
│                         (pattern nodes)       Target:       │
│                                               Intelligence  │
└─────────────────────────────────────────────────────────────┘
```

---

## D.3 Experience Tree Structure

```
Experience Tree Root (L4: Entity "Research Assistant")
├── 🔍 Observations
│   ├── OBSERVATION: "web_search returns partial results for complex queries"
│   │   metadata_extra: {
│   │     source_episodes: ["ep-uuid-1", "ep-uuid-2"],
│   │     confidence: 0.7,
│   │     first_observed: "2026-05-10",
│   │     observation_count: 3
│   │   }
│   ├── OBSERVATION: "Decomposing queries into sub-queries improves completeness"
│   │   metadata_extra: {
│   │     source_episodes: ["ep-uuid-3", "ep-uuid-5"],
│   │     confidence: 0.9,
│   │     improvement_metric: 0.35
│   │   }
│   └── ...
├── 🔄 Patterns
│   ├── PATTERN: "Complex research tasks benefit from query decomposition"
│   │   metadata_extra: {
│   │     source_observations: ["obs-uuid-1", "obs-uuid-2"],
│   │     pattern_strength: 0.85,
│   │     recurrence_count: 5,
│   │     success_correlation: 0.90
│   │   }
│   └── ...
└── 💡 Suggestions
    ├── SUGGESTION: "For research tasks, always decompose into 3-5 sub-queries"
    │   metadata_extra: {
    │     source_pattern: "pattern-uuid-1",
    │     applicability: ["research", "analysis"],
    │     expected_improvement: 0.35
    │   }
    └── ...
```

---

## D.4 Intelligence Tree Structure

```
Intelligence Tree Root (L4: Entity "Research Assistant")
├── 📏 Instructions (Distilled Rules)
│   ├── INSTRUCTION: "Always decompose complex queries into 3-5 sub-queries"
│   │   metadata_extra: {
│   │     rule_type: "procedure",
│   │     source_patterns: ["pat-uuid-1", "pat-uuid-2"],
│   │     confidence: 0.92,
│   │     success_rate: 0.88,
│   │     applicability_conditions: ["task_complexity > 'medium'"],
│   │     generation: 3
│   │   }
│   ├── INSTRUCTION: "Cap web_search calls at 5 per step to control costs"
│   │   metadata_extra: {
│   │     rule_type: "constraint",
│   │     source_patterns: ["pat-uuid-3"],
│   │     confidence: 0.75,
│   │     cost_impact: -0.30
│   │   }
│   └── ...
├── 🎯 Strategies (High-level Approaches)
│   ├── STRATEGY: "Research Pipeline: Decompose → Search → Synthesize → Verify"
│   │   metadata_extra: {
│   │     strategy_type: "workflow_template",
│   │     applicability: ["research", "due_diligence"],
│   │     success_rate: 0.85,
│   │     avg_step_count: 12
│   │   }
│   └── ...
└── ❤️ Preferences (User/Entity Behavioral Patterns)
    ├── PREFERENCE: "User prefers markdown tables for data presentation"
    │   metadata_extra: {
    │     preference_type: "output_format",
    │     confidence: 0.80,
    │     observation_count: 7
    │   }
    └── ...
```

---

## D.5 Detailed Implementation

### D.5.1 Experience Tree Service

**New file**: `backend/src/ai/experience_tree_service.py`

```python
class ExperienceTreeService:
    """Manages persistent Experience Trees per entity."""
    
    async def get_or_create_experience_tree(
        self,
        entity_id: UUID,
        company_id: UUID,
    ) -> CortexTree:
        """Get or create the Experience Tree for this entity."""
        stmt = select(CortexTree).where(
            CortexTree.memory_domain == MemoryDomain.EXPERIENCE,
            CortexTree.scope_level == ScopeLevel.ENTITY,
            CortexTree.entity_id == entity_id,
            CortexTree.company_id == company_id,
        )
        result = await self.db.execute(stmt)
        tree = result.scalar_one_or_none()
        
        if tree:
            return tree
        
        return await self._create_experience_tree(entity_id, company_id)
    
    async def _create_experience_tree(self, entity_id, company_id):
        """Create Experience Tree with three section roots."""
        tree = CortexTree(
            entity_id=entity_id,
            company_id=company_id,
            memory_domain=MemoryDomain.EXPERIENCE,
            scope_level=ScopeLevel.ENTITY,
            task_description=f"Experience memory for entity {entity_id}",
            status=CortexTreeStatus.ACTIVE,
            is_persistent=True,
        )
        self.db.add(tree)
        await self.db.flush()
        
        # Root node
        root = await self._create_node(tree.id, None, "root",
            "🧠 Experience", "Learned patterns and observations from execution history.")
        tree.root_node_id = root.id
        
        # Three section roots
        await self._create_node(tree.id, root.id, "group",
            "🔍 Observations", "Raw observations extracted from individual episodes.")
        await self._create_node(tree.id, root.id, "group",
            "🔄 Patterns", "Recurring patterns identified across multiple observations.")
        await self._create_node(tree.id, root.id, "group",
            "💡 Suggestions", "Actionable suggestions derived from patterns.")
        
        await self.db.flush()
        return tree
```

### D.5.2 Intelligence Tree Service

**New file**: `backend/src/ai/intelligence_tree_service.py`

```python
class IntelligenceTreeService:
    """Manages persistent Intelligence Trees per entity."""
    
    async def get_or_create_intelligence_tree(
        self,
        entity_id: UUID,
        company_id: UUID,
    ) -> CortexTree:
        """Get or create the Intelligence Tree for this entity."""
        # Similar pattern to ExperienceTreeService
        ...
    
    async def _create_intelligence_tree(self, entity_id, company_id):
        """Create Intelligence Tree with three section roots."""
        # Root → Instructions, Strategies, Preferences
        ...
    
    async def get_applicable_rules(
        self,
        entity_id: UUID,
        company_id: UUID,
        task_description: str,
        max_rules: int = 10,
    ) -> List[Dict]:
        """
        Query Intelligence Tree for rules applicable to the current task.
        Uses semantic search on task_description to find relevant instructions,
        strategies, and preferences.
        
        Returns sorted by: confidence × relevance_score
        """
        tree = await self.get_or_create_intelligence_tree(entity_id, company_id)
        
        # Semantic search across instruction/strategy/preference nodes
        embedding_service = EmbeddingService(self.db, company_id)
        query_vector = await embedding_service.embed_text(task_description)
        
        if not query_vector:
            return []
        
        result = await self.db.execute(text("""
            SELECT cn.id, cn.title, cn.summary, cn.node_type, cn.metadata_extra,
                   1 - (cn.embedding <=> CAST(:vec AS vector)) AS relevance
            FROM cortex_nodes cn
            WHERE cn.tree_id = :tree_id
              AND cn.node_type IN ('instruction', 'strategy', 'preference')
              AND cn.embedding IS NOT NULL
            ORDER BY 
                COALESCE((cn.metadata_extra->>'confidence')::numeric, 0.5) * 
                (1 - (cn.embedding <=> CAST(:vec AS vector))) DESC
            LIMIT :max_rules
        """), {
            "tree_id": str(tree.id),
            "vec": json.dumps(query_vector),
            "max_rules": max_rules,
        })
        
        return [
            {
                "rule": row.summary,
                "type": row.node_type,
                "confidence": row.metadata_extra.get("confidence", 0.5),
                "relevance": float(row.relevance),
            }
            for row in result.fetchall()
        ]
```

### D.5.3 Dreaming Engine

**New file**: `backend/src/ai/dreaming_engine.py`

The core learning pipeline that runs as a background worker task:

```python
class DreamingEngine:
    """
    Background learning engine that extracts patterns from episodic history
    and distills them into actionable intelligence.
    
    Three-phase pipeline:
      Phase 1: Observation Extraction (Episodic → Experience.Observations)
      Phase 2: Pattern Recognition (Observations → Experience.Patterns)
      Phase 3: Intelligence Distillation (Patterns → Intelligence.Instructions/Strategies)
    """
    
    # Configuration
    MIN_EPISODES_FOR_DREAMING = 5          # Minimum episodes before first dream
    MIN_OBSERVATIONS_FOR_PATTERNS = 3      # Min observations to form a pattern
    MIN_PATTERNS_FOR_DISTILLATION = 2      # Min patterns to distill a rule
    BATCH_SIZE = 20                         # Max episodes per dreaming cycle
    CONSOLIDATION_INTERVAL_HOURS = 24       # How often to run (per entity)
    
    async def dream(
        self,
        entity_id: UUID,
        company_id: UUID,
        force: bool = False,
    ) -> Dict[str, int]:
        """
        Run the full dreaming pipeline for an entity.
        
        Returns: {
            "observations_created": int,
            "patterns_created": int,
            "rules_created": int,
        }
        """
        # Check if enough time has passed since last consolidation
        if not force:
            should_run = await self._should_run(entity_id, company_id)
            if not should_run:
                return {"observations_created": 0, "patterns_created": 0, "rules_created": 0}
        
        logger.info(f"Dreaming engine starting for entity {entity_id}")
        
        # Phase 1: Extract Observations
        observations = await self._extract_observations(entity_id, company_id)
        
        # Phase 2: Pattern Recognition
        patterns = await self._recognize_patterns(entity_id, company_id)
        
        # Phase 3: Intelligence Distillation
        rules = await self._distill_intelligence(entity_id, company_id)
        
        # Update consolidation timestamp
        await self._update_consolidation_timestamp(entity_id, company_id)
        
        result = {
            "observations_created": len(observations),
            "patterns_created": len(patterns),
            "rules_created": len(rules),
        }
        logger.info(f"Dreaming engine completed for entity {entity_id}: {result}")
        return result
    
    # ──────────────────────────────────────────────────────────────────
    # Phase 1: Observation Extraction
    # ──────────────────────────────────────────────────────────────────
    
    async def _extract_observations(
        self,
        entity_id: UUID,
        company_id: UUID,
    ) -> List[UUID]:
        """
        Analyze recent episode nodes and extract observations.
        
        Uses LLM to analyze each episode batch and identify:
        - Tool usage patterns (which tools, in what order)
        - Success/failure correlations
        - Cost efficiency observations
        - Output quality signals
        """
        episodic_service = EpisodicTreeService(self.db, company_id)
        experience_service = ExperienceTreeService(self.db, company_id)
        
        # Get unprocessed episodes
        experience_tree = await experience_service.get_or_create_experience_tree(entity_id, company_id)
        last_consolidated = experience_tree.last_consolidated_at or datetime.min
        
        episodes = await episodic_service.query_episodes_by_time(
            entity_id=entity_id,
            company_id=company_id,
            start_date=last_consolidated,
            end_date=datetime.utcnow(),
            limit=self.BATCH_SIZE,
        )
        
        if len(episodes) < self.MIN_EPISODES_FOR_DREAMING:
            return []
        
        # Build analysis prompt
        episode_summaries = []
        for ep in episodes:
            meta = ep.metadata_extra or {}
            episode_summaries.append({
                "id": str(ep.id),
                "task": ep.summary,
                "status": meta.get("status", "unknown"),
                "tools_used": meta.get("tools_used", []),
                "cost_usd": meta.get("cost_usd", 0),
                "execution_time_ms": meta.get("execution_time_ms", 0),
            })
        
        # LLM Analysis
        llm = LLMRouter(db=self.db, company_id=company_id)
        response = await llm.call_llm(
            task_type="text_generation",
            system_prompt=OBSERVATION_EXTRACTION_PROMPT,
            user_prompt=json.dumps(episode_summaries),
            temperature=0.2,
            max_tokens=2000,
        )
        
        # Parse observations from LLM response
        observations = self._parse_observations(response.output)
        
        # Write observation nodes to Experience Tree
        observations_root = await experience_service.get_observations_root(entity_id, company_id)
        created_ids = []
        
        cortex = CortexRouter(self.db, company_id)
        for obs in observations:
            node_id = await cortex.write(
                parent_id=observations_root,
                node_type="observation",
                title=f"🔍 {obs['title'][:100]}",
                summary=obs["description"],
                content=json.dumps(obs),
                metadata_extra={
                    "source_episodes": obs.get("source_episodes", []),
                    "confidence": obs.get("confidence", 0.5),
                    "first_observed": datetime.utcnow().isoformat(),
                    "observation_count": 1,
                },
                importance_score=obs.get("confidence", 0.5),
            )
            created_ids.append(node_id)
        
        return created_ids
    
    # ──────────────────────────────────────────────────────────────────
    # Phase 2: Pattern Recognition
    # ──────────────────────────────────────────────────────────────────
    
    async def _recognize_patterns(
        self,
        entity_id: UUID,
        company_id: UUID,
    ) -> List[UUID]:
        """
        Cross-reference observations to identify recurring patterns.
        
        Groups semantically similar observations using embedding similarity,
        then uses LLM to synthesize patterns from groups.
        """
        experience_service = ExperienceTreeService(self.db, company_id)
        
        # Load all observations
        observations = await experience_service.get_observations(entity_id, company_id)
        
        if len(observations) < self.MIN_OBSERVATIONS_FOR_PATTERNS:
            return []
        
        # Cluster observations by embedding similarity
        clusters = await self._cluster_observations(observations)
        
        # For each cluster with 2+ members, generate a pattern
        patterns_root = await experience_service.get_patterns_root(entity_id, company_id)
        created_ids = []
        
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            
            # LLM synthesis
            llm = LLMRouter(db=self.db, company_id=company_id)
            cluster_texts = [obs.summary for obs in cluster]
            
            response = await llm.call_llm(
                task_type="text_generation",
                system_prompt=PATTERN_RECOGNITION_PROMPT,
                user_prompt=json.dumps(cluster_texts),
                temperature=0.2,
                max_tokens=500,
            )
            
            pattern = self._parse_pattern(response.output)
            
            cortex = CortexRouter(self.db, company_id)
            node_id = await cortex.write(
                parent_id=patterns_root,
                node_type="pattern",
                title=f"🔄 {pattern['title'][:100]}",
                summary=pattern["description"],
                content=json.dumps(pattern),
                metadata_extra={
                    "source_observations": [str(obs.id) for obs in cluster],
                    "pattern_strength": pattern.get("strength", 0.5),
                    "recurrence_count": len(cluster),
                    "success_correlation": pattern.get("success_correlation", 0.5),
                },
            )
            
            # Create cortex_edges linking pattern to source observations
            for obs in cluster:
                edge = CortexEdge(
                    source_node_id=node_id,
                    target_node_id=obs.id,
                    edge_type="derived_from",
                    weight=1.0 / len(cluster),
                    created_by="dreaming_engine",
                )
                self.db.add(edge)
            
            created_ids.append(node_id)
        
        return created_ids
    
    # ──────────────────────────────────────────────────────────────────
    # Phase 3: Intelligence Distillation
    # ──────────────────────────────────────────────────────────────────
    
    async def _distill_intelligence(
        self,
        entity_id: UUID,
        company_id: UUID,
    ) -> List[UUID]:
        """
        Distill validated patterns into actionable Intelligence rules.
        
        Only patterns with pattern_strength >= 0.7 and recurrence_count >= 3
        are candidates for distillation.
        """
        experience_service = ExperienceTreeService(self.db, company_id)
        intelligence_service = IntelligenceTreeService(self.db, company_id)
        
        # Load strong patterns
        patterns = await experience_service.get_strong_patterns(
            entity_id, company_id,
            min_strength=0.7,
            min_recurrence=self.MIN_PATTERNS_FOR_DISTILLATION,
        )
        
        if not patterns:
            return []
        
        # Load existing rules to avoid duplicates
        existing_rules = await intelligence_service.get_all_rules(entity_id, company_id)
        existing_summaries = [r.summary for r in existing_rules]
        
        # LLM Distillation
        llm = LLMRouter(db=self.db, company_id=company_id)
        response = await llm.call_llm(
            task_type="text_generation",
            system_prompt=INTELLIGENCE_DISTILLATION_PROMPT,
            user_prompt=json.dumps({
                "patterns": [{"summary": p.summary, "strength": p.metadata_extra.get("pattern_strength")} for p in patterns],
                "existing_rules": existing_summaries,
            }),
            temperature=0.1,
            max_tokens=2000,
        )
        
        rules = self._parse_rules(response.output)
        
        # Write new rules to Intelligence Tree
        intelligence_tree = await intelligence_service.get_or_create_intelligence_tree(entity_id, company_id)
        created_ids = []
        
        cortex = CortexRouter(self.db, company_id)
        for rule in rules:
            rule_type = rule.get("type", "instruction")
            node_type = {
                "instruction": "instruction",
                "strategy": "strategy",
                "preference": "preference",
            }.get(rule_type, "instruction")
            
            parent = await intelligence_service.get_section_root(
                entity_id, company_id, node_type
            )
            
            node_id = await cortex.write(
                parent_id=parent,
                node_type=node_type,
                title=f"{'📏' if node_type == 'instruction' else '🎯' if node_type == 'strategy' else '❤️'} {rule['title'][:100]}",
                summary=rule["description"],
                content=json.dumps(rule),
                metadata_extra={
                    "rule_type": rule_type,
                    "source_patterns": rule.get("source_patterns", []),
                    "confidence": rule.get("confidence", 0.5),
                    "success_rate": rule.get("success_rate", 0.0),
                    "generation": (intelligence_tree.consolidation_generation or 0) + 1,
                },
            )
            
            # Generate embedding for semantic retrieval
            node = await cortex._get_node(node_id)
            embedding_service = EmbeddingService(self.db, company_id)
            await embedding_service.embed_node(node)
            
            created_ids.append(node_id)
        
        # Update generation counter
        intelligence_tree.consolidation_generation = (intelligence_tree.consolidation_generation or 0) + 1
        intelligence_tree.last_consolidated_at = datetime.utcnow()
        
        return created_ids
```

### D.5.4 LLM Prompts for Dreaming

**New file**: `backend/src/ai/dreaming_prompts.py`

```python
OBSERVATION_EXTRACTION_PROMPT = """You are analyzing execution history for an AI agent.
Given a batch of recent execution episodes, extract concrete OBSERVATIONS about:

1. TOOL PATTERNS: Which tools are used, in what order, and their effectiveness
2. SUCCESS FACTORS: What conditions correlate with successful outcomes
3. FAILURE PATTERNS: What conditions or sequences lead to failures
4. COST PATTERNS: What drives cost up or down
5. TIME PATTERNS: What affects execution time

For each observation, provide:
- title: A concise name (max 100 chars)
- description: A detailed description (max 500 chars)
- confidence: 0.0 to 1.0 indicating how confident this observation is
- source_episodes: List of episode IDs that support this observation

Return as JSON array: [{"title": "...", "description": "...", "confidence": 0.8, "source_episodes": ["..."]}]
"""

PATTERN_RECOGNITION_PROMPT = """You are identifying patterns from multiple observations.
Given a cluster of related observations, synthesize them into a PATTERN:

A pattern is a recurring behavior or correlation that appears across multiple observations.
It should be generalizable and actionable.

Return as JSON: {
  "title": "...",
  "description": "...",
  "strength": 0.0 to 1.0,
  "success_correlation": 0.0 to 1.0,
  "actionability": "The pattern suggests..."
}
"""

INTELLIGENCE_DISTILLATION_PROMPT = """You are distilling patterns into actionable intelligence rules.
Given strong, validated patterns, create RULES the agent should follow:

Types of rules:
- instruction: A specific, concrete action to take or avoid
- strategy: A high-level approach or workflow template
- preference: A learned user/context preference

IMPORTANT: Do NOT duplicate existing rules. Check the provided list of existing rules.

Return as JSON array: [{"type": "instruction|strategy|preference", "title": "...", 
"description": "...", "confidence": 0.0-1.0, "applicability_conditions": ["..."]}]
"""
```

### D.5.5 Background Worker Registration

**File**: `backend/src/ai/worker.py` (add new worker function)

```python
async def dreaming_worker(ctx, entity_id: str, company_id: str, force: bool = False):
    """
    Background worker task for the Dreaming Engine.
    Scheduled to run periodically per entity (default: every 24h).
    """
    async with AsyncSessionLocal() as db:
        engine = DreamingEngine(db, UUID(company_id))
        result = await engine.dream(
            entity_id=UUID(entity_id),
            company_id=UUID(company_id),
            force=force,
        )
        await db.commit()
        return result
```

### D.5.6 Trigger Dreaming After Execution

**File**: `backend/src/ai/worker.py` (in `execute_run()`, after successful completion)

```python
# After run completion (line ~1084):
# Schedule dreaming if enough episodes have accumulated
try:
    from src.ai.dreaming_engine import DreamingEngine
    dreaming = DreamingEngine(self.db, entity.company_id)
    should_dream = await dreaming._should_run(entity.id, entity.company_id)
    if should_dream:
        # Enqueue as background task (non-blocking)
        await self.redis.enqueue_job(
            "dreaming_worker",
            str(entity.id),
            str(entity.company_id),
        )
        logger.info(f"Dreaming scheduled for entity {entity.id}")
except Exception as e:
    logger.debug(f"Dreaming scheduling failed: {e}")
```

---

## D.6 Files Changed

| File | Action | Changes |
|---|---|---|
| `backend/src/ai/experience_tree_service.py` | NEW | Experience Tree management |
| `backend/src/ai/intelligence_tree_service.py` | NEW | Intelligence Tree management, rule querying |
| `backend/src/ai/dreaming_engine.py` | NEW | Three-phase learning pipeline |
| `backend/src/ai/dreaming_prompts.py` | NEW | LLM prompt templates |
| `backend/src/ai/worker.py` | MODIFY | Add dreaming_worker, trigger after execution |
| `backend/src/ai/cortex_models.py` | MODIFY | Import CortexEdge model (added in Phase A) |

---

## D.7 Configuration Parameters

| Parameter | Default | Description |
|---|---|---|
| `MIN_EPISODES_FOR_DREAMING` | 5 | Minimum episodes before first dream cycle |
| `MIN_OBSERVATIONS_FOR_PATTERNS` | 3 | Min observations to form a pattern |
| `MIN_PATTERNS_FOR_DISTILLATION` | 2 | Min patterns to distill a rule |
| `CONSOLIDATION_INTERVAL_HOURS` | 24 | Hours between dreaming cycles |
| `BATCH_SIZE` | 20 | Max episodes processed per cycle |
| `OBSERVATION_CONFIDENCE_THRESHOLD` | 0.5 | Min confidence to keep an observation |
| `PATTERN_STRENGTH_THRESHOLD` | 0.7 | Min strength to be a distillation candidate |

---

## D.8 Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| LLM hallucinations in pattern extraction | HIGH | Confidence scoring, threshold filtering, human review flags |
| Circular patterns (learning from own learning) | HIGH | Generation tracking prevents self-referential loops |
| Cost of LLM calls in dreaming | MEDIUM | Batch processing, configurable intervals, use cheaper models |
| Pattern drift (old patterns become irrelevant) | MEDIUM | Importance decay via `last_accessed_at`, configurable TTL |
| Large observation sets | LOW | BATCH_SIZE limiting, pagination |

---

## D.9 Validation Criteria

- [ ] Experience Tree created per entity with three section roots
- [ ] Intelligence Tree created per entity with three section roots
- [ ] Dreaming Phase 1: Observations extracted from 5+ episodes
- [ ] Dreaming Phase 2: Patterns formed from 3+ similar observations
- [ ] Dreaming Phase 3: Rules distilled from 2+ strong patterns
- [ ] Cortex edges created between patterns and source observations
- [ ] Intelligence rules retrievable via semantic search
- [ ] Background worker runs without blocking execution
- [ ] Consolidation timestamp updated after each cycle
- [ ] No duplicate rules created across dream cycles
