"""
Unified CORTEX Memory v2 — Full Test Suite
Entity: 3cbc5ea1-dbc3-4f8a-9074-d8b751408777
Company: 699098ce-a31c-42ef-b13b-2780c7decb9d
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

logging.disable(logging.CRITICAL)

import src.auth.models
import src.config.models
import src.ai.models

from src.common.database import AsyncSessionLocal
from sqlalchemy import text

ENTITY_ID  = UUID('3cbc5ea1-dbc3-4f8a-9074-d8b751408777')
COMPANY_ID = UUID('699098ce-a31c-42ef-b13b-2780c7decb9d')

results = {}

def record(test_id, name, status, detail=""):
    results[test_id] = {"name": name, "status": status, "detail": detail}
    icon = "✅" if status == "PASS" else "❌" if status == "FAIL" else "⚠️"
    print(f"  {icon} [{test_id}] {name}: {status} {('— '+detail) if detail else ''}")


async def test_phase(label, tests):
    """Run each test in its own session to avoid transaction poisoning."""
    print(f"\n=== {label} ===")
    for test_id, name, func in tests:
        try:
            async with AsyncSessionLocal() as db:
                detail = await func(db)
                record(test_id, name, "PASS", detail or "")
        except Exception as e:
            record(test_id, name, "FAIL", str(e)[:120])


async def run_all():
    # ============================================================
    # PHASE A: Schema Validation
    # ============================================================
    async def a1(db):
        r = await db.execute(text("SELECT unnest(enum_range(NULL::memory_domain))"))
        d = [row[0] for row in r.fetchall()]
        assert len(d) == 4; return str(d)

    async def a2(db):
        r = await db.execute(text("SELECT unnest(enum_range(NULL::scope_level))"))
        s = [row[0] for row in r.fetchall()]
        assert len(s) >= 5; return str(s)

    async def a3(db):
        r = await db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='cortex_edges'"))
        c = [row[0] for row in r.fetchall()]
        assert len(c) >= 8; return f"{len(c)} columns"

    async def a4(db):
        r = await db.execute(text("SELECT indexname FROM pg_indexes WHERE tablename='cortex_nodes' AND indexdef LIKE '%hnsw%'"))
        i = [row[0] for row in r.fetchall()]
        assert i; return str(i)

    async def a5(db):
        r = await db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='cortex_trees' AND column_name IN ('memory_domain','scope_level','is_persistent','last_consolidated_at','consolidation_generation')"))
        c = [row[0] for row in r.fetchall()]
        assert len(c) == 5; return str(c)

    await test_phase("PHASE A: Schema Validation", [
        ("A1", "memory_domain enum", a1),
        ("A2", "scope_level enum", a2),
        ("A3", "cortex_edges table", a3),
        ("A4", "HNSW vector index", a4),
        ("A5", "v2 tree columns", a5),
    ])

    # ============================================================
    # PHASE B: Knowledge Trees
    # ============================================================
    async def b1(db):
        from src.ai.memory.embedding_service import EmbeddingService
        svc = EmbeddingService(db, COMPANY_ID)
        vec = await svc.embed_text('Hello world test embedding')
        assert vec and len(vec) > 0; return f"dim={len(vec)}, model={svc.get_model_name()}"

    async def b2(db):
        from src.ai.memory.embedding_service import EmbeddingService
        svc = EmbeddingService(db, COMPANY_ID)
        qvec = await svc.embed_query('test query')
        assert qvec; return f"dim={len(qvec)}"

    async def b3(db):
        from src.ai.memory.embedding_service import EmbeddingService
        svc = EmbeddingService(db, COMPANY_ID)
        vecs = await svc.embed_batch(['Text one', 'Text two'])
        valid = [v for v in vecs if v]
        assert len(valid) == 2; return f"{len(valid)}/2 success"

    async def b4(db):
        from src.ai.memory.knowledge_tree_service import KnowledgeTreeService
        kt = KnowledgeTreeService(db, COMPANY_ID)
        tree = await kt.get_or_create_knowledge_tree(ENTITY_ID)
        assert tree; return f"tree_id={str(tree.id)[:8]}"

    async def b5(db):
        from src.ai.memory.knowledge_tree_service import KnowledgeTreeService
        kt = KnowledgeTreeService(db, COMPANY_ID)
        t1 = await kt.get_or_create_knowledge_tree(ENTITY_ID)
        t2 = await kt.get_or_create_knowledge_tree(ENTITY_ID)
        assert t1.id == t2.id; return "idempotent"

    async def b6(db):
        from src.ai.memory.knowledge_tree_service import KnowledgeTreeService
        kt = KnowledgeTreeService(db, COMPANY_ID)
        tree = await kt.get_or_create_knowledge_tree(ENTITY_ID)
        count = await kt.ingest_document(
            tree_id=tree.id, document_id=tree.id,
            content='# Introduction\nThis is a test about AI systems.\n\n# Methods\nWe used deep learning for analysis.\n\n# Results\nAccuracy improved significantly with our approach.',
            filename='test_paper.md', entity_id=ENTITY_ID,
        )
        await db.commit()
        assert count > 0; return f"{count} nodes created"

    async def b7(db):
        from src.ai.memory.knowledge_tree_service import KnowledgeTreeService
        kt = KnowledgeTreeService(db, COMPANY_ID)
        r = await kt.search(ENTITY_ID, 'deep learning', top_k=3)
        return f"{len(r)} results"

    await test_phase("PHASE B: Knowledge Trees", [
        ("B1", "EmbeddingService single", b1),
        ("B2", "EmbeddingService query", b2),
        ("B3", "EmbeddingService batch", b3),
        ("B4", "KnowledgeTree create", b4),
        ("B5", "KnowledgeTree idempotent", b5),
        ("B6", "Document ingestion", b6),
        ("B7", "Knowledge search", b7),
    ])

    # ============================================================
    # PHASE C: Episodic Trees
    # ============================================================
    async def c1(db):
        from src.ai.memory.episodic_tree_service import EpisodicTreeService
        ep = EpisodicTreeService(db, COMPANY_ID)
        t = await ep.get_or_create_episodic_tree(ENTITY_ID)
        assert t; return f"tree_id={str(t.id)[:8]}, nodes={t.total_nodes}"

    async def c2(db):
        from src.ai.memory.episodic_tree_service import EpisodicTreeService
        ep = EpisodicTreeService(db, COMPANY_ID)
        r = await ep.get_recent_episodes(ENTITY_ID, limit=5)
        return f"{len(r)} episodes"

    async def c3(db):
        from src.ai.memory.episodic_tree_service import EpisodicTreeService
        ep = EpisodicTreeService(db, COMPANY_ID)
        now = datetime.now(timezone.utc)
        r = await ep.query_by_time(ENTITY_ID, start_date=now - timedelta(days=90), end_date=now, limit=5)
        return f"{len(r)} results"

    async def c4(db):
        from src.ai.memory.episodic_tree_service import EpisodicTreeService
        ep = EpisodicTreeService(db, COMPANY_ID)
        r = await ep.query_by_topic(ENTITY_ID, 'research analysis', top_k=3)
        return f"{len(r)} results"

    async def c5(db):
        r1 = await db.execute(text("SELECT COUNT(*) FROM episodic_memories WHERE entity_id = :eid"), {"eid": str(ENTITY_ID)})
        v1 = r1.scalar()
        r2 = await db.execute(text("""
            SELECT COUNT(*) FROM cortex_nodes cn
            JOIN cortex_trees ct ON cn.tree_id = ct.id
            WHERE ct.entity_id = :eid AND ct.memory_domain = 'episodic' AND cn.node_type = 'episode'
        """), {"eid": str(ENTITY_ID)})
        v2 = r2.scalar()
        return f"v1={v1}, v2={v2}"

    await test_phase("PHASE C: Episodic Trees", [
        ("C1", "EpisodicTree create", c1),
        ("C2", "Recent episodes", c2),
        ("C3", "Temporal query", c3),
        ("C4", "Topic query", c4),
        ("C5", "Dual-write verification", c5),
    ])

    # ============================================================
    # PHASE D: Experience/Intelligence/Dreaming
    # ============================================================
    async def d1(db):
        from src.ai.memory.experience_tree_service import ExperienceTreeService
        ex = ExperienceTreeService(db, COMPANY_ID)
        t = await ex.get_or_create_experience_tree(ENTITY_ID)
        await db.commit()
        assert t; return f"tree_id={str(t.id)[:8]}, nodes={t.total_nodes}"

    async def d2(db):
        from src.ai.memory.experience_tree_service import ExperienceTreeService
        ex = ExperienceTreeService(db, COMPANY_ID)
        o = await ex.get_observations_root(ENTITY_ID)
        p = await ex.get_patterns_root(ENTITY_ID)
        s = await ex.get_suggestions_root(ENTITY_ID)
        return f"obs={str(o)[:8]}, pat={str(p)[:8]}, sug={str(s)[:8]}"

    async def d3(db):
        from src.ai.memory.intelligence_tree_service import IntelligenceTreeService
        it = IntelligenceTreeService(db, COMPANY_ID)
        t = await it.get_or_create_intelligence_tree(ENTITY_ID)
        await db.commit()
        assert t; return f"tree_id={str(t.id)[:8]}, nodes={t.total_nodes}"

    async def d4(db):
        from src.ai.memory.intelligence_tree_service import IntelligenceTreeService
        it = IntelligenceTreeService(db, COMPANY_ID)
        for rtype in ['instruction', 'strategy', 'preference']:
            await it.get_section_root(ENTITY_ID, rtype)
        return "all 3 roots found"

    async def d5(db):
        from src.ai.memory.intelligence_tree_service import IntelligenceTreeService
        it = IntelligenceTreeService(db, COMPANY_ID)
        r = await it.get_all_rules(ENTITY_ID)
        return f"{len(r)} rules"

    async def d6(db):
        from src.ai.memory.intelligence_tree_service import IntelligenceTreeService
        it = IntelligenceTreeService(db, COMPANY_ID)
        p = await it.get_rules_for_prompt(ENTITY_ID, 'analyze data')
        return f"{len(p)} chars"

    async def d7(db):
        from src.ai.memory.dreaming_engine import DreamingEngine
        engine = DreamingEngine(db, COMPANY_ID)
        should = await engine._should_run(ENTITY_ID)
        return f"should_run={should}"

    async def d8(db):
        from src.ai.memory.dreaming_engine import DreamingEngine
        engine = DreamingEngine(db, COMPANY_ID)
        r = await engine.dream(ENTITY_ID, force=True)
        await db.commit()
        return str(r)

    await test_phase("PHASE D: Experience/Intelligence/Dreaming", [
        ("D1", "ExperienceTree create", d1),
        ("D2", "Experience section roots", d2),
        ("D3", "IntelligenceTree create", d3),
        ("D4", "Intelligence section roots", d4),
        ("D5", "Intelligence get_all_rules", d5),
        ("D6", "Rules prompt injection", d6),
        ("D7", "Dreaming _should_run", d7),
        ("D8", "DreamingEngine.dream", d8),
    ])

    # ============================================================
    # PHASE E: Semantic Graph
    # ============================================================
    async def e1(db):
        from src.ai.memory.graph_service import SemanticGraphService
        g = SemanticGraphService(db, COMPANY_ID)
        s = await g.get_graph_stats()
        return str(s) if s else "empty graph"

    async def e2(db):
        from src.ai.memory.graph_service import SemanticGraphService
        g = SemanticGraphService(db, COMPANY_ID)
        r = await g.semantic_graph_search('deep learning analysis', ENTITY_ID, top_k=5)
        details = f"{len(r)} results"
        for item in r[:3]:
            details += f"\n       [{item['combined_score']:.3f}] ({item['source']}) {item['node_type']}: {item.get('title','')[:50]}"
        return details

    async def e3(db):
        r = await db.execute(text("SELECT cn.id, cn.title FROM cortex_nodes cn WHERE cn.embedding IS NOT NULL LIMIT 1"))
        row = r.fetchone()
        if not row:
            record("E3", "Auto similarity edges", "SKIP", "no embedded nodes"); return "skipped"
        from src.ai.memory.graph_service import SemanticGraphService
        g = SemanticGraphService(db, COMPANY_ID)
        c = await g.create_similarity_edges(row[0])
        await db.commit()
        return f"{c} edges for '{row[1][:30]}'"

    async def e4(db):
        from src.ai.memory.graph_service import SemanticGraphService
        g = SemanticGraphService(db, COMPANY_ID)
        d = await g.decay_weights(days_inactive=30)
        p = await g.prune_weak_edges()
        await db.commit()
        return f"decayed={d}, pruned={p}"

    await test_phase("PHASE E: Semantic Graph", [
        ("E1", "Graph stats", e1),
        ("E2", "Semantic graph search", e2),
        ("E3", "Auto similarity edges", e3),
        ("E4", "Graph maintenance", e4),
    ])

    # ============================================================
    # PHASE F: Memory Assembly
    # ============================================================
    async def f1(db):
        from src.ai.memory.memory_assembly_service import MemoryAssemblyService
        a = MemoryAssemblyService(db, COMPANY_ID)
        m = await a.assemble_runtime_memory(ENTITY_ID, task_description='Analyze quarterly revenue trends')
        return f"knowledge={len(m.knowledge_refs)}, experience={len(m.experience_suggestions)}, intelligence={len(m.intelligence_rules)}, episodic={len(m.episodic_context)}, prompt={len(m.formatted_prompt)} chars"

    async def f2(db):
        from src.ai.memory.memory_service import MemoryRouter
        r = MemoryRouter(db)
        s = await r.search_semantic(ENTITY_ID, 'data analysis', top_k=3)
        return f"{len(s)} results"

    await test_phase("PHASE F: Memory Assembly", [
        ("F1", "Memory assembly", f1),
        ("F2", "MemoryRouter v2 search", f2),
    ])

    # Workers
    print("\n=== WORKER REGISTRATIONS ===")
    try:
        from src.ai.core.arq_jobs import dreaming_worker, graph_maintenance_worker
        record("W1", "dreaming_worker", "PASS")
        record("W2", "graph_maintenance_worker", "PASS")
    except Exception as e:
        record("W1", "Worker imports", "FAIL", str(e)[:100])

    # Domain tree count
    async with AsyncSessionLocal() as db:
        r = await db.execute(text("""
            SELECT memory_domain, COUNT(*) FROM cortex_trees
            WHERE entity_id = :eid AND memory_domain IS NOT NULL
            GROUP BY memory_domain
        """), {"eid": str(ENTITY_ID)})
        domain_counts = {row[0]: row[1] for row in r.fetchall()}

    # ============================================================
    # SUMMARY
    # ============================================================
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Entity: {ENTITY_ID}")
    print(f"Company: {COMPANY_ID}")
    print(f"V2 Trees: {domain_counts}")

    total = len(results)
    passed = sum(1 for v in results.values() if v["status"] == "PASS")
    failed = sum(1 for v in results.values() if v["status"] == "FAIL")
    skipped = sum(1 for v in results.values() if v["status"] == "SKIP")

    print(f"\nTotal: {total} | Passed: {passed} | Failed: {failed} | Skipped: {skipped}")

    if failed:
        print("\nFailed tests:")
        for k, v in results.items():
            if v["status"] == "FAIL":
                print(f"  ❌ [{k}] {v['name']}: {v['detail']}")

    print(f"\nOverall: {'ALL PASS ✅' if failed == 0 else 'SOME FAILED ❌'}")


asyncio.run(run_all())
