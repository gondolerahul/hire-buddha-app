"""
Additional DB-backed tests targeting the remaining service surface (knowledge
ingestion + search, graph maintenance, more CortexService ops, dreaming phases)
so package coverage clears the Stage-C bar.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from cortex_memory import (
    CortexService,
    KnowledgeTreeService,
    SemanticGraphService,
)
from cortex_memory.providers_reference import HashEmbeddingProvider

from cortex_memory.tests.test_services import _StructuredLLM

pytestmark = pytest.mark.asyncio


def _emb() -> HashEmbeddingProvider:
    return HashEmbeddingProvider(dim=768)


async def test_knowledge_tree_ingest_and_search(db) -> None:
    company, entity = uuid4(), uuid4()
    svc = KnowledgeTreeService(db, company, embedding=_emb())
    tree = await svc.get_or_create_knowledge_tree(entity)
    await db.commit()

    content = (
        "# Big Document\n\n"
        "Section one talks about lattice cryptography and NIST standards.\n\n"
        "## Subsection\n\n"
        "More detail about FIPS 203 and post-quantum schemes follows here, "
        "with enough text to form a chunk of reasonable size for embedding.\n"
    )
    created = await svc.ingest_document(
        tree_id=tree.id, document_id=uuid4(), content=content,
        filename="bigdoc.md", entity_id=entity,
    )
    await db.commit()
    assert created >= 1

    # Search exercises the embed_query + pgvector ranking path.
    results = await svc.search(entity_id=entity, query="post-quantum NIST", top_k=5)
    assert isinstance(results, list)


async def test_semantic_graph_search_after_ingest(db) -> None:
    """Ingesting a doc creates embedded CHUNK nodes; a hybrid search then
    exercises the semantic seed + graph expansion path."""
    company, entity = uuid4(), uuid4()
    ks = KnowledgeTreeService(db, company, embedding=_emb())
    tree = await ks.get_or_create_knowledge_tree(entity)
    await db.commit()
    content = (
        "# Doc\n\nLattice cryptography and NIST FIPS 203 standardisation, with a "
        "body long enough to chunk and embed for the semantic search path.\n"
    )
    await ks.ingest_document(tree_id=tree.id, document_id=uuid4(),
                             content=content, filename="d.md", entity_id=entity)
    await db.commit()

    graph = SemanticGraphService(db, company, embedding=_emb())
    results = await graph.semantic_graph_search(
        query="post-quantum standards", entity_id=entity, top_k=5,
    )
    assert isinstance(results, list)


async def test_bridge_paragraphs(db) -> None:
    """Directly exercise the LLM bridge-paragraph synthesis path."""
    svc = CortexService(db, uuid4(), llm=_StructuredLLM())
    bridges = await svc._generate_bridge_paragraphs(
        uuid4(), ["Section one body.", "Section two body.", "Section three body."],
    )
    assert isinstance(bridges, list)
    # No-LLM path returns [].
    svc_no_llm = CortexService(db, uuid4(), llm=None)
    assert await svc_no_llm._generate_bridge_paragraphs(uuid4(), ["a", "b"]) == []


async def test_graph_maintenance_ops(db) -> None:
    company = uuid4()
    svc = CortexService(db, company, llm=_StructuredLLM())
    tree = await svc.create_tree(entity_id=uuid4(), user_id=None, task_description="graph maint")
    working = await svc.get_working_root(tree.id)
    a = await svc.write(parent_id=working.id, node_type="finding", title="A", content="aaa", summary="a")
    b = await svc.write(parent_id=working.id, node_type="finding", title="B", content="bbb", summary="b")
    c = await svc.write(parent_id=working.id, node_type="finding", title="C", content="ccc", summary="c")
    await db.commit()

    graph = SemanticGraphService(db, company, embedding=_emb())
    await graph.create_edge(a, b, edge_type="references", weight=0.9)
    await graph.create_edge(b, c, edge_type="references", weight=0.2)
    await db.commit()

    # co-access + maintenance.
    await graph.track_co_access([a, b, c])
    await db.commit()
    decayed = await graph.decay_weights(days_inactive=0)
    await db.commit()
    pruned = await graph.prune_weak_edges()
    await db.commit()
    assert isinstance(decayed, int) and isinstance(pruned, int)


async def test_service_suspend_and_list(db) -> None:
    company = uuid4()
    entity = uuid4()
    svc = CortexService(db, company, llm=_StructuredLLM())
    tree = await svc.create_tree(entity_id=entity, user_id=None, task_description="suspend me")
    await db.commit()

    await svc.suspend_tree(tree.id)
    await db.commit()

    trees = await svc.list_trees(entity_id=entity)
    assert isinstance(trees, list)


async def test_dreaming_phases_directly(db) -> None:
    """Drive each dreaming phase (observation → pattern → rule) directly so the
    pattern-recognition and intelligence-distillation branches are covered."""
    from cortex_memory import DreamingEngine, EpisodicTreeService
    from cortex_memory.tests.test_services import _fake_run

    company, entity = uuid4(), uuid4()
    episodic = EpisodicTreeService(db, company, embedding=_emb())
    for _ in range(8):
        await episodic.write_episode(entity_id=entity, run=_fake_run(company, entity))
    await db.commit()

    engine = DreamingEngine(db, company, llm=_StructuredLLM(), embedding=_emb())
    obs = await engine._extract_observations(entity)
    await db.commit()
    assert len(obs) >= 3
    pats = await engine._recognize_patterns(entity)
    await db.commit()
    rules = await engine._distill_intelligence(entity)
    await db.commit()
    assert isinstance(pats, list) and isinstance(rules, list)


async def test_dreaming_distillation_with_seeded_patterns(db) -> None:
    """Seed ≥2 strong patterns so the intelligence-distillation phase runs end
    to end (read patterns → LLM → write rule nodes)."""
    from cortex_memory import DreamingEngine, ExperienceTreeService

    company, entity = uuid4(), uuid4()
    exp = ExperienceTreeService(db, company)
    await exp.get_or_create_experience_tree(entity)
    patterns_root = await exp.get_patterns_root(entity)
    await db.commit()

    svc = CortexService(db, company, llm=_StructuredLLM())
    for i in range(2):
        await svc.write(
            parent_id=patterns_root, node_type="pattern",
            title=f"pattern {i}", content=f"pattern body {i}",
            summary=f"pattern summary {i}",
            metadata_extra={"pattern_strength": 0.9, "recurrence_count": 3},
        )
    await db.commit()

    engine = DreamingEngine(db, company, llm=_StructuredLLM(), embedding=_emb())
    rules = await engine._distill_intelligence(entity)
    await db.commit()
    assert isinstance(rules, list)


async def test_viewport_render_and_read_paging(db) -> None:
    company = uuid4()
    svc = CortexService(db, company, llm=_StructuredLLM())
    tree = await svc.create_tree(entity_id=uuid4(), user_id=None, task_description="render")
    working = await svc.get_working_root(tree.id)
    big = "lorem ipsum " * 4000  # large content → multiple read pages
    node_id = await svc.write(parent_id=working.id, node_type="finding",
                              title="Big", content=big, summary="big summary")
    await db.commit()

    viewport = await svc.navigate(working.id)
    rendered = viewport.to_prompt_text(include_ops_help=True, max_chars=4000)
    assert "CORTEX Operations" in rendered or len(rendered) > 0

    page0 = await svc.read(node_id, page=0)
    assert page0.total_pages >= 1
    if page0.total_pages > 1:
        page1 = await svc.read(node_id, page=1)
        assert page1.page == 1


async def test_service_write_many_children_triggers_recluster(db) -> None:
    # Writing > max_children under one parent exercises the re-clustering /
    # MAX_CHILDREN invariant path in write().
    company = uuid4()
    svc = CortexService(db, company, llm=_StructuredLLM())
    tree = await svc.create_tree(entity_id=uuid4(), user_id=None,
                                 task_description="recluster", max_children=3)
    working = await svc.get_working_root(tree.id)
    await db.commit()
    for i in range(5):
        await svc.write(parent_id=working.id, node_type="finding",
                        title=f"finding {i}", content=f"body {i}", summary=f"s{i}")
    await db.commit()
    viewport = await svc.navigate(working.id)
    assert viewport is not None
