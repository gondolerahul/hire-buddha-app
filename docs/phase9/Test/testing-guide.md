# Unified CORTEX Memory v2 — Testing Guide

> All tests run from: `cd backend && source .venv/bin/activate`
> Use `python -c "..."` or save as scripts in `backend/tests/phase9/`

---

## Prerequisites

```bash
# Grab a valid entity_id and company_id from your DB
python -c "
import asyncio
from src.common.database import AsyncSessionLocal
from sqlalchemy import text
async def main():
    async with AsyncSessionLocal() as db:
        r = await db.execute(text('''
            SELECT he.id, he.company_id, he.name
            FROM hierarchical_entities he WHERE he.status = 'ACTIVE' LIMIT 3
        '''))
        for row in r.fetchall():
            print(f'{row[2]}: entity_id={row[0]} company_id={row[1]}')
asyncio.run(main())
"
```

Set these for every test below:

```python
ENTITY_ID  = "YOUR_ENTITY_UUID"
COMPANY_ID = "YOUR_COMPANY_UUID"
```

---

## Phase A — Schema Validation

```bash
# 1. Verify migration applied
python -c "
import asyncio
from src.common.database import AsyncSessionLocal
from sqlalchemy import text
async def main():
    async with AsyncSessionLocal() as db:
        # Check enums exist
        for enum in ['memory_domain','scope_level']:
            r = await db.execute(text(f\"SELECT unnest(enum_range(NULL::memory_domain))\"))
            print(f'{enum}: {[row[0] for row in r.fetchall()]}')
        # Check cortex_edges table
        r = await db.execute(text(\"SELECT column_name FROM information_schema.columns WHERE table_name='cortex_edges' ORDER BY ordinal_position\"))
        print(f'cortex_edges columns: {[row[0] for row in r.fetchall()]}')
        # Check HNSW index
        r = await db.execute(text(\"SELECT indexname FROM pg_indexes WHERE tablename='cortex_nodes' AND indexname LIKE '%hnsw%'\"))
        print(f'HNSW indexes: {[row[0] for row in r.fetchall()]}')
asyncio.run(main())
"
```

**Expected**: All 4 memory_domain values, cortex_edges columns, HNSW index present.

---

## Phase B — Knowledge Trees

### B1. EmbeddingService

```bash
python -c "
import asyncio
from src.common.database import AsyncSessionLocal
from uuid import UUID
COMPANY_ID = 'YOUR_COMPANY_UUID'

async def main():
    async with AsyncSessionLocal() as db:
        from src.ai.embedding_service import EmbeddingService
        svc = EmbeddingService(db, UUID(COMPANY_ID))

        # Test single embed
        vec = await svc.embed_text('Hello world')
        print(f'Single embed: dim={len(vec) if vec else 0}')

        # Test query embed
        qvec = await svc.embed_query('test query')
        print(f'Query embed: dim={len(qvec) if qvec else 0}')

        # Test batch
        vecs = await svc.embed_batch(['Text one', 'Text two', 'Text three'])
        print(f'Batch embed: {len(vecs)} vectors, dims={[len(v) for v in vecs if v]}')

        print(f'Model: {svc.get_model_name()}')
asyncio.run(main())
"
```

**Expected**: 768-dimension vectors, model = `text-embedding-005` or admin-configured.

### B2. KnowledgeTreeService

```bash
python -c "
import asyncio
from src.common.database import AsyncSessionLocal
from uuid import UUID
ENTITY_ID  = 'YOUR_ENTITY_UUID'
COMPANY_ID = 'YOUR_COMPANY_UUID'

async def main():
    async with AsyncSessionLocal() as db:
        from src.ai.knowledge_tree_service import KnowledgeTreeService
        svc = KnowledgeTreeService(db, UUID(COMPANY_ID))

        # Test get_or_create (idempotent)
        tree = await svc.get_or_create_knowledge_tree(UUID(ENTITY_ID))
        print(f'Tree: {tree.id}, nodes={tree.total_nodes}')

        tree2 = await svc.get_or_create_knowledge_tree(UUID(ENTITY_ID))
        assert tree.id == tree2.id, 'FAIL: not idempotent!'
        print('Idempotent: PASS')

        # Test ingest_document
        sample_doc_id = tree.id  # reuse as fake doc_id
        count = await svc.ingest_document(
            tree_id=tree.id,
            document_id=sample_doc_id,
            content='# Introduction\nThis is a test document about AI.\n\n# Methods\nWe used deep learning for analysis.\n\n# Results\nThe results show significant improvement in accuracy.',
            filename='test_paper.md',
            entity_id=UUID(ENTITY_ID),
        )
        print(f'Ingested: {count} nodes created')
        await db.commit()

        # Test search
        results = await svc.search(UUID(ENTITY_ID), 'deep learning', top_k=3)
        print(f'Search results: {len(results)}')
        for r in results:
            print(f'  [{r[\"score\"]:.3f}] {r[\"title\"]}: {r[\"snippet\"][:80]}')

        # Test get_knowledge_references
        refs = await svc.get_knowledge_references(UUID(ENTITY_ID), 'accuracy improvement')
        print(f'References: {len(refs)}')
asyncio.run(main())
"
```

**Expected**: Tree created, 5+ nodes (1 doc + sections + chunks), search returns scored results.

---

## Phase C — Episodic Trees

### C1. EpisodicTreeService

```bash
python -c "
import asyncio
from src.common.database import AsyncSessionLocal
from uuid import UUID
from datetime import datetime, timedelta
ENTITY_ID  = 'YOUR_ENTITY_UUID'
COMPANY_ID = 'YOUR_COMPANY_UUID'

async def main():
    async with AsyncSessionLocal() as db:
        from src.ai.episodic_tree_service import EpisodicTreeService
        svc = EpisodicTreeService(db, UUID(COMPANY_ID))

        # Test get_or_create
        tree = await svc.get_or_create_episodic_tree(UUID(ENTITY_ID))
        print(f'Episodic Tree: {tree.id}, nodes={tree.total_nodes}')

        # Test get_recent_episodes
        recent = await svc.get_recent_episodes(UUID(ENTITY_ID), limit=5)
        print(f'Recent episodes: {len(recent)}')
        for ep in recent[:3]:
            print(f'  [{ep[\"at\"]}] {ep[\"input\"][:60]}')

        # Test query_by_time
        time_results = await svc.query_by_time(
            UUID(ENTITY_ID),
            start_date=datetime.utcnow() - timedelta(days=30),
            end_date=datetime.utcnow(),
            limit=5,
        )
        print(f'Time query: {len(time_results)} episodes')

        # Test query_by_topic (needs episodes with embeddings)
        topic_results = await svc.query_by_topic(UUID(ENTITY_ID), 'research analysis', top_k=3)
        print(f'Topic query: {len(topic_results)} results')
asyncio.run(main())
"
```

**Expected**: Episodes found from migration (43 total), temporal/semantic queries return data.

### C2. Dual-Write Verification

```bash
python -c "
import asyncio
from src.common.database import AsyncSessionLocal
from sqlalchemy import text
ENTITY_ID = 'YOUR_ENTITY_UUID'

async def main():
    async with AsyncSessionLocal() as db:
        # Count v1 flat episodes
        r1 = await db.execute(text(
            'SELECT COUNT(*) FROM episodic_memories WHERE entity_id = :eid'
        ), {'eid': ENTITY_ID})
        v1_count = r1.scalar()

        # Count v2 tree episodes
        r2 = await db.execute(text('''
            SELECT COUNT(*) FROM cortex_nodes cn
            JOIN cortex_trees ct ON cn.tree_id = ct.id
            WHERE ct.entity_id = :eid
              AND ct.memory_domain = 'episodic'
              AND cn.node_type = 'episode'
        '''), {'eid': ENTITY_ID})
        v2_count = r2.scalar()

        print(f'V1 (flat table): {v1_count} episodes')
        print(f'V2 (episodic tree): {v2_count} episodes')
asyncio.run(main())
"
```

---

## Phase D — Experience, Intelligence, Dreaming

### D1. ExperienceTreeService

```bash
python -c "
import asyncio
from src.common.database import AsyncSessionLocal
from uuid import UUID
ENTITY_ID  = 'YOUR_ENTITY_UUID'
COMPANY_ID = 'YOUR_COMPANY_UUID'

async def main():
    async with AsyncSessionLocal() as db:
        from src.ai.experience_tree_service import ExperienceTreeService
        svc = ExperienceTreeService(db, UUID(COMPANY_ID))

        tree = await svc.get_or_create_experience_tree(UUID(ENTITY_ID))
        print(f'Experience Tree: {tree.id}, nodes={tree.total_nodes}')

        obs_root = await svc.get_observations_root(UUID(ENTITY_ID))
        pat_root = await svc.get_patterns_root(UUID(ENTITY_ID))
        sug_root = await svc.get_suggestions_root(UUID(ENTITY_ID))
        print(f'Section roots: obs={str(obs_root)[:8]}, pat={str(pat_root)[:8]}, sug={str(sug_root)[:8]}')

        await db.commit()
        print('ExperienceTreeService: PASS')
asyncio.run(main())
"
```

### D2. IntelligenceTreeService

```bash
python -c "
import asyncio
from src.common.database import AsyncSessionLocal
from uuid import UUID
ENTITY_ID  = 'YOUR_ENTITY_UUID'
COMPANY_ID = 'YOUR_COMPANY_UUID'

async def main():
    async with AsyncSessionLocal() as db:
        from src.ai.intelligence_tree_service import IntelligenceTreeService
        svc = IntelligenceTreeService(db, UUID(COMPANY_ID))

        tree = await svc.get_or_create_intelligence_tree(UUID(ENTITY_ID))
        print(f'Intelligence Tree: {tree.id}, nodes={tree.total_nodes}')

        for rtype in ['instruction','strategy','preference']:
            rid = await svc.get_section_root(UUID(ENTITY_ID), rtype)
            print(f'  {rtype} root: {str(rid)[:8]}')

        rules = await svc.get_all_rules(UUID(ENTITY_ID))
        print(f'Rules: {len(rules)}')

        prompt = await svc.get_rules_for_prompt(UUID(ENTITY_ID), 'analyze data')
        print(f'Prompt injection: {len(prompt)} chars')

        await db.commit()
        print('IntelligenceTreeService: PASS')
asyncio.run(main())
"
```

### D3. DreamingEngine

```bash
python -c "
import asyncio
from src.common.database import AsyncSessionLocal
from uuid import UUID
ENTITY_ID  = 'YOUR_ENTITY_UUID'
COMPANY_ID = 'YOUR_COMPANY_UUID'

async def main():
    async with AsyncSessionLocal() as db:
        from src.ai.dreaming_engine import DreamingEngine
        engine = DreamingEngine(db, UUID(COMPANY_ID))

        # Check scheduling
        should = await engine._should_run(UUID(ENTITY_ID))
        print(f'Should dream: {should}')

        # Run dreaming (force=True to bypass schedule)
        result = await engine.dream(UUID(ENTITY_ID), force=True)
        print(f'Dream result: {result}')
        await db.commit()
asyncio.run(main())
"
```

> **Note**: Dreaming requires 5+ episodes with content. If `observations_created=0`, the entity doesn't have enough episodes yet. Run some executions first, then re-test.

---

## Phase E — Semantic Graph

### E1. Graph Service

```bash
python -c "
import asyncio
from src.common.database import AsyncSessionLocal
from uuid import UUID, uuid4
COMPANY_ID = 'YOUR_COMPANY_UUID'

async def main():
    async with AsyncSessionLocal() as db:
        from src.ai.graph_service import SemanticGraphService
        graph = SemanticGraphService(db, UUID(COMPANY_ID))

        # Test edge creation
        n1, n2 = uuid4(), uuid4()
        # (Will fail if nodes don't exist - use real node IDs from cortex_nodes)

        # Test graph stats
        stats = await graph.get_graph_stats()
        print(f'Graph stats: {stats}')

        # Test maintenance
        decayed = await graph.decay_weights(days_inactive=30)
        pruned = await graph.prune_weak_edges()
        print(f'Maintenance: {decayed} decayed, {pruned} pruned')
        await db.commit()
asyncio.run(main())
"
```

### E2. Semantic Graph Search

```bash
python -c "
import asyncio
from src.common.database import AsyncSessionLocal
from uuid import UUID
ENTITY_ID  = 'YOUR_ENTITY_UUID'
COMPANY_ID = 'YOUR_COMPANY_UUID'

async def main():
    async with AsyncSessionLocal() as db:
        from src.ai.graph_service import SemanticGraphService
        graph = SemanticGraphService(db, UUID(COMPANY_ID))

        results = await graph.semantic_graph_search(
            query='research analysis',
            entity_id=UUID(ENTITY_ID),
            domains=None,  # all domains
            top_k=5,
        )
        print(f'Graph search: {len(results)} results')
        for r in results[:5]:
            print(f'  [{r[\"combined_score\"]:.3f}] ({r[\"source\"]}) {r[\"node_type\"]}: {r[\"title\"][:60]}')
asyncio.run(main())
"
```

### E3. Embed with Auto-Edges

```bash
python -c "
import asyncio
from src.common.database import AsyncSessionLocal
from uuid import UUID
from sqlalchemy import text
COMPANY_ID = 'YOUR_COMPANY_UUID'

async def main():
    async with AsyncSessionLocal() as db:
        # Find a node with an embedding
        r = await db.execute(text('''
            SELECT cn.id, cn.title FROM cortex_nodes cn
            WHERE cn.embedding IS NOT NULL LIMIT 1
        '''))
        row = r.fetchone()
        if not row:
            print('No embedded nodes found - run B2 test first')
            return
        node_id = row[0]
        print(f'Testing auto-edges for node: {row[1][:50]}')

        from src.ai.graph_service import SemanticGraphService
        graph = SemanticGraphService(db, UUID(COMPANY_ID))
        count = await graph.create_similarity_edges(node_id)
        print(f'Auto-edges created: {count}')
        await db.commit()
asyncio.run(main())
"
```

---

## Phase F — Memory Assembly

### F1. MemoryAssemblyService

```bash
python -c "
import asyncio
from src.common.database import AsyncSessionLocal
from uuid import UUID
ENTITY_ID  = 'YOUR_ENTITY_UUID'
COMPANY_ID = 'YOUR_COMPANY_UUID'

async def main():
    async with AsyncSessionLocal() as db:
        from src.ai.memory_assembly_service import MemoryAssemblyService
        assembler = MemoryAssemblyService(db, UUID(COMPANY_ID))

        result = await assembler.assemble_runtime_memory(
            entity_id=UUID(ENTITY_ID),
            task_description='Analyze quarterly revenue trends for APAC region',
        )

        print('=== MEMORY ASSEMBLY RESULT ===')
        print(f'Knowledge refs:     {len(result.knowledge_refs)}')
        print(f'Experience suggest:  {len(result.experience_suggestions)}')
        print(f'Intelligence rules:  {len(result.intelligence_rules)}')
        print(f'Episodic context:    {len(result.episodic_context)}')
        print(f'Formatted prompt:    {len(result.formatted_prompt)} chars')
        print()
        if result.formatted_prompt:
            print('--- PROMPT PREVIEW (first 500 chars) ---')
            print(result.formatted_prompt[:500])
asyncio.run(main())
"
```

### F2. V2 Search in MemoryRouter

```bash
python -c "
import asyncio
from src.common.database import AsyncSessionLocal
from uuid import UUID
ENTITY_ID = 'YOUR_ENTITY_UUID'

async def main():
    async with AsyncSessionLocal() as db:
        from src.ai.memory_service import MemoryRouter
        router = MemoryRouter(db)

        # search_semantic now uses v2 graph search with v1 fallback
        results = await router.search_semantic(UUID(ENTITY_ID), 'data analysis')
        print(f'Semantic search: {len(results)} results')
        for r in results[:3]:
            print(f'  [{r[\"score\"]:.3f}] {r.get(\"node_type\",\"chunk\")}: {r[\"content\"][:80]}')
asyncio.run(main())
"
```

---

## End-to-End Integration Test

```bash
python -c "
import asyncio
from src.common.database import AsyncSessionLocal
from uuid import UUID
from sqlalchemy import text
ENTITY_ID  = 'YOUR_ENTITY_UUID'
COMPANY_ID = 'YOUR_COMPANY_UUID'

async def main():
    async with AsyncSessionLocal() as db:
        results = {}

        # 1. Knowledge Tree
        from src.ai.knowledge_tree_service import KnowledgeTreeService
        kt = KnowledgeTreeService(db, UUID(COMPANY_ID))
        tree = await kt.get_or_create_knowledge_tree(UUID(ENTITY_ID))
        results['knowledge_tree'] = 'PASS' if tree else 'FAIL'

        # 2. Episodic Tree
        from src.ai.episodic_tree_service import EpisodicTreeService
        ep = EpisodicTreeService(db, UUID(COMPANY_ID))
        etree = await ep.get_or_create_episodic_tree(UUID(ENTITY_ID))
        results['episodic_tree'] = 'PASS' if etree else 'FAIL'

        # 3. Experience Tree
        from src.ai.experience_tree_service import ExperienceTreeService
        ex = ExperienceTreeService(db, UUID(COMPANY_ID))
        xtree = await ex.get_or_create_experience_tree(UUID(ENTITY_ID))
        results['experience_tree'] = 'PASS' if xtree else 'FAIL'

        # 4. Intelligence Tree
        from src.ai.intelligence_tree_service import IntelligenceTreeService
        it = IntelligenceTreeService(db, UUID(COMPANY_ID))
        itree = await it.get_or_create_intelligence_tree(UUID(ENTITY_ID))
        results['intelligence_tree'] = 'PASS' if itree else 'FAIL'

        # 5. Graph Service
        from src.ai.graph_service import SemanticGraphService
        graph = SemanticGraphService(db, UUID(COMPANY_ID))
        stats = await graph.get_graph_stats()
        results['graph_service'] = 'PASS'

        # 6. Memory Assembly
        from src.ai.memory_assembly_service import MemoryAssemblyService
        asm = MemoryAssemblyService(db, UUID(COMPANY_ID))
        mem = await asm.assemble_runtime_memory(
            entity_id=UUID(ENTITY_ID),
            task_description='test integration',
        )
        results['memory_assembly'] = 'PASS' if mem else 'FAIL'

        # 7. V2 Trees count
        r = await db.execute(text('''
            SELECT memory_domain, COUNT(*) FROM cortex_trees
            WHERE entity_id = :eid AND memory_domain IS NOT NULL
            GROUP BY memory_domain
        '''), {'eid': ENTITY_ID})
        domains = {row[0]: row[1] for row in r.fetchall()}

        await db.commit()

        print('=== E2E INTEGRATION TEST ===')
        for k, v in results.items():
            print(f'  {k}: {v}')
        print(f'  domains: {domains}')
        all_pass = all(v == 'PASS' for v in results.values())
        print(f'  OVERALL: {\"ALL PASS ✅\" if all_pass else \"SOME FAILED ❌\"}')
asyncio.run(main())
"
```

---

## Worker Tests (require running Arq/Redis)

### Dreaming Worker
```bash
python -c "
from src.ai.worker import dreaming_worker
print(f'dreaming_worker registered: {dreaming_worker.__name__}')
print(f'Signature: entity_id_str, company_id_str, force=False')
"
```

### Graph Maintenance Worker
```bash
python -c "
from src.ai.worker import graph_maintenance_worker
print(f'graph_maintenance_worker registered: {graph_maintenance_worker.__name__}')
"
```

---

## Checklist

| # | Test | Phase | Status |
|---|---|---|---|
| 1 | Schema enums + tables exist | A | ☐ |
| 2 | HNSW index present | A | ☐ |
| 3 | EmbeddingService generates vectors | B | ☐ |
| 4 | KnowledgeTree creation idempotent | B | ☐ |
| 5 | Document ingestion creates hierarchy | B | ☐ |
| 6 | Knowledge search returns scored results | B | ☐ |
| 7 | EpisodicTree creation works | C | ☐ |
| 8 | Recent episodes retrieved | C | ☐ |
| 9 | Temporal query works | C | ☐ |
| 10 | Dual-write v1+v2 verified | C | ☐ |
| 11 | ExperienceTree with 3 section roots | D | ☐ |
| 12 | IntelligenceTree with 3 section roots | D | ☐ |
| 13 | DreamingEngine._should_run works | D | ☐ |
| 14 | DreamingEngine.dream completes | D | ☐ |
| 15 | Graph stats query works | E | ☐ |
| 16 | Semantic graph search returns results | E | ☐ |
| 17 | Auto similarity edges created | E | ☐ |
| 18 | Graph maintenance runs | E | ☐ |
| 19 | MemoryAssembly returns all domains | F | ☐ |
| 20 | formatted_prompt is non-empty | F | ☐ |
| 21 | MemoryRouter.search_semantic uses v2 | F | ☐ |
| 22 | E2E integration test passes | ALL | ☐ |
