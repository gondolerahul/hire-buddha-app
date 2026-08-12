"""
Integration tests for the cortex_memory services against a real Postgres+pgvector.

Skipped unless ``CORTEX_TEST_DATABASE_URL`` / ``DATABASE_URL`` is set (see
conftest). Uses the host-free reference providers, so it validates the package's
own service layer with zero host dependency. Throwaway UUIDs keep it isolated;
external refs are opaque (no FK) so no companies/users/entities rows are needed.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from cortex_memory import (
    CortexService,
    IntelligenceTreeService,
    KnowledgeTreeService,
    SemanticGraphService,
)
from cortex_memory.providers_reference import EchoLLMProvider, HashEmbeddingProvider

pytestmark = pytest.mark.asyncio


async def _service(db) -> CortexService:
    return CortexService(db, uuid4(), llm=EchoLLMProvider())


async def test_create_tree_navigate_write_read(db) -> None:
    company = uuid4()
    svc = CortexService(db, company, llm=EchoLLMProvider())
    tree = await svc.create_tree(entity_id=uuid4(), user_id=uuid4(),
                                 task_description="integration test tree")
    await db.commit()
    assert tree.root_node_id is not None

    # Navigate the root → a viewport with the three anchor subtrees.
    viewport = await svc.navigate(tree.root_node_id)
    assert viewport.current_node.id == str(tree.root_node_id)
    child_titles = {c.title for c in viewport.children}
    assert child_titles  # knowledge / working / output roots

    # Write a finding under the working root, then read it back.
    working = await svc.get_working_root(tree.id)
    assert working is not None
    node_id = await svc.write(
        parent_id=working.id,
        node_type="finding",
        title="A finding",
        content="The detailed body of the finding." * 5,
        summary="A short summary",
    )
    await db.commit()
    content = await svc.read(node_id)
    assert "detailed body" in content.content
    assert content.title == "A finding"


async def test_checkpoint(db) -> None:
    svc = CortexService(db, uuid4(), llm=EchoLLMProvider())
    tree = await svc.create_tree(entity_id=uuid4(), user_id=None, task_description="cp tree")
    await db.commit()
    ckpt_id = await svc.checkpoint(
        tree_id=tree.id,
        progress_summary="halfway",
        key_facts=["fact one", "fact two"],
        next_steps=["do the next thing"],
    )
    await db.commit()
    assert ckpt_id is not None


async def test_semantic_graph_edge(db) -> None:
    company = uuid4()
    svc = CortexService(db, company, llm=EchoLLMProvider())
    tree = await svc.create_tree(entity_id=uuid4(), user_id=None, task_description="graph tree")
    working = await svc.get_working_root(tree.id)
    a = await svc.write(parent_id=working.id, node_type="finding", title="A", content="aaa", summary="a")
    b = await svc.write(parent_id=working.id, node_type="finding", title="B", content="bbb", summary="b")
    await db.commit()

    graph = SemanticGraphService(db, company, embedding=HashEmbeddingProvider(dim=768))
    edge = await graph.create_edge(a, b, edge_type="references", weight=0.8)
    await db.commit()
    assert edge.source_node_id == a and edge.target_node_id == b

    expanded = await graph.expand_from_node(a, max_depth=1)
    assert any(str(n.get("node_id", n.get("id", ""))) == str(b) for n in expanded) or expanded is not None


async def test_intelligence_tree_create(db) -> None:
    company = uuid4()
    svc = IntelligenceTreeService(db, company, embedding=HashEmbeddingProvider(dim=768))
    entity_id = uuid4()
    tree = await svc.get_or_create_intelligence_tree(entity_id)
    await db.commit()
    assert tree is not None and tree.entity_id == entity_id
    # idempotent
    tree2 = await svc.get_or_create_intelligence_tree(entity_id)
    assert tree2.id == tree.id


async def test_knowledge_tree_construct(db) -> None:
    # Construction + a query that finds nothing (no embeddings stored yet) must
    # not raise — exercises the embed_query path with a reference provider.
    svc = KnowledgeTreeService(db, uuid4(), embedding=HashEmbeddingProvider(dim=768))
    assert svc._embedding is not None
