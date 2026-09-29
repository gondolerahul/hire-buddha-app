"""Knowledge Base documents: create, read, update and delete on CORTEX (PO-01).

A document is a ``documents`` row plus the DOCUMENT → SECTION → CHUNK nodes
ingested into a Knowledge Tree. Every operation must keep the two in step:
a deleted document must stop coming back from search and memory, a renamed
one must carry its new name into search results, a re-scoped one must move
to the right tree.

Runs against the real Postgres (the node queries use JSONB and pgvector)
inside the suite's rolled-back transaction, with a deterministic embedder.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import text

from cortex_memory.providers import EmbeddingResult
from tests.fixtures.llm_fixture import deterministic_embedding

pytestmark = pytest.mark.needs_db

DOC_TEXT = (
    "# Refund policy\n"
    "Customers may return any item within 30 days for a full refund. "
    "Refunds are paid to the original payment method within five working days.\n\n"
    "# Shipping\n"
    "Orders over fifty dollars ship free. Express shipping costs twelve dollars "
    "and arrives the next working day.\n"
)


class _Embedder:
    async def embed(self, texts, *, model=None):
        return EmbeddingResult(vectors=[deterministic_embedding(t) for t in texts], model="test-embed")

    def dimension(self) -> int:
        return 768


async def _entity(db, company_id) -> uuid.UUID:
    from src.ai.orm.entity import HierarchicalEntity
    ent = HierarchicalEntity(company_id=company_id, type="AGENT", status="ACTIVE",
                             name=f"kb-agent-{uuid.uuid4().hex[:6]}", display_name="KB Agent")
    db.add(ent)
    await db.flush()
    return ent.id


async def _ingested(db, company_id, filename="policy.md", entity_id=None, body=DOC_TEXT):
    """A settled document, ingested the way process_document does it."""
    from src.ai.orm.document import Document
    from src.ai.services.knowledge_base import KnowledgeBaseService

    doc = Document(company_id=company_id, entity_id=entity_id, filename=filename,
                   file_type="md", file_size=str(len(body)), upload_status="completed")
    db.add(doc)
    await db.flush()
    svc = KnowledgeBaseService(db, company_id, embedding=_Embedder())
    trees = svc._trees()
    tree = (await trees.get_or_create_knowledge_tree(entity_id=entity_id) if entity_id
            else await trees.get_or_create_company_knowledge_tree())
    await trees.ingest_document(tree_id=tree.id, document_id=doc.id, content=body,
                                filename=filename, entity_id=entity_id)
    await db.flush()
    return svc, doc, tree


async def _nodes(db, document_id) -> list[tuple]:
    return (await db.execute(text(
        "SELECT node_type, tree_id, title, source_ref->>'filename' FROM cortex_nodes "
        "WHERE source_ref->>'document_id' = :d"
    ), {"d": str(document_id)})).all()


async def _tree_total(db, tree_id) -> int:
    return (await db.execute(text("SELECT total_nodes FROM cortex_trees WHERE id = :t"),
                             {"t": str(tree_id)})).scalar_one()


@pytest.mark.asyncio
async def test_read_returns_the_ingestion_outline(db, test_company_id):
    svc, doc, _ = await _ingested(db, test_company_id)
    detail = await svc.get(doc.id)
    assert detail["filename"] == "policy.md"
    assert detail["entity_name"] is None  # company-wide
    assert detail["sections"] == ["Refund policy", "Shipping"]
    assert detail["chunks_total"] >= 2 and detail["chunks_embedded"] == detail["chunks_total"]
    assert "30 days for a full refund" in detail["preview"]
    listed = await svc.list()
    assert [d["id"] for d in listed] == [doc.id]


@pytest.mark.asyncio
async def test_delete_removes_the_row_and_every_node(db, test_company_id):
    svc, doc, tree = await _ingested(db, test_company_id)
    _, keep, _ = await _ingested(db, test_company_id, filename="keep.md",
                                 body="# Other\nAn unrelated document that must survive.")
    total_before = await _tree_total(db, tree.id)
    doc_nodes = len(await _nodes(db, doc.id))
    assert doc_nodes >= 4  # document + 2 sections + chunks

    removed = await svc.delete(doc.id)

    assert removed == doc_nodes
    assert await _nodes(db, doc.id) == []
    assert await _tree_total(db, tree.id) == total_before - doc_nodes
    hits = await svc.search("full refund within 30 days", top_k=10)
    assert all(h["document_id"] != str(doc.id) for h in hits)
    assert len(await _nodes(db, keep.id)) > 0  # the other document is untouched
    with pytest.raises(HTTPException) as err:
        await svc.get(doc.id)
    assert err.value.status_code == 404


@pytest.mark.asyncio
async def test_rename_reaches_every_node_and_search(db, test_company_id):
    svc, doc, _ = await _ingested(db, test_company_id)
    detail = await svc.update(doc.id, filename="refunds-2026.md")
    assert detail["filename"] == "refunds-2026.md"
    nodes = await _nodes(db, doc.id)
    assert {n[3] for n in nodes} == {"refunds-2026.md"}
    assert [n[2] for n in nodes if n[0] == "document"] == ["📄 refunds-2026.md"]
    hits = await svc.search("full refund within 30 days", top_k=10)
    assert {h["filename"] for h in hits if h["document_id"] == str(doc.id)} == {"refunds-2026.md"}


@pytest.mark.asyncio
async def test_rescope_moves_the_nodes_between_trees(db, test_company_id):
    svc, doc, company_tree = await _ingested(db, test_company_id)
    entity_id = await _entity(db, test_company_id)
    count = len(await _nodes(db, doc.id))
    company_total = await _tree_total(db, company_tree.id)

    detail = await svc.update(doc.id, move=True, entity_id=entity_id)

    assert detail["entity_id"] == entity_id and detail["entity_name"] == "KB Agent"
    entity_tree = await svc._trees().get_or_create_knowledge_tree(entity_id=entity_id)
    nodes = await _nodes(db, doc.id)
    assert {n[1] for n in nodes} == {entity_tree.id}
    assert await _tree_total(db, company_tree.id) == company_total - count
    doc_node_parent = (await db.execute(text(
        "SELECT parent_id FROM cortex_nodes WHERE node_type = 'document' AND source_ref->>'document_id' = :d"
    ), {"d": str(doc.id)})).scalar_one()
    assert doc_node_parent == entity_tree.root_node_id

    back = await svc.update(doc.id, move=True, entity_id=None)  # company-wide again
    assert back["entity_id"] is None
    assert {n[1] for n in await _nodes(db, doc.id)} == {company_tree.id}


@pytest.mark.asyncio
async def test_replace_file_drops_old_nodes_and_requeues(db, test_company_id, monkeypatch):
    svc, doc, _ = await _ingested(db, test_company_id)
    queued = []

    async def fake_enqueue(self, document, content):
        queued.append((document.id, document.filename, content))

    from src.ai.services import knowledge_base
    monkeypatch.setattr(knowledge_base.KnowledgeBaseService, "_enqueue_ingestion", fake_enqueue)
    replaced = await svc.replace_file(doc.id, b"# New\nFresh content.", "policy-v2.txt", "txt")
    assert replaced.upload_status == "processing" and replaced.filename == "policy-v2.txt"
    assert await _nodes(db, doc.id) == []
    assert queued == [(doc.id, "policy-v2.txt", b"# New\nFresh content.")]


@pytest.mark.asyncio
async def test_no_edits_while_processing(db, test_company_id):
    svc, doc, _ = await _ingested(db, test_company_id)
    doc.upload_status = "processing"
    await db.flush()
    for call in (lambda: svc.update(doc.id, filename="x.md"),
                 lambda: svc.replace_file(doc.id, b"x", "x.txt", "txt")):
        with pytest.raises(HTTPException) as err:
            await call()
        assert err.value.status_code == 409


@pytest.mark.asyncio
async def test_other_companies_cannot_touch_it(db, test_company_id):
    from src.ai.services.knowledge_base import KnowledgeBaseService
    svc, doc, _ = await _ingested(db, test_company_id)
    other_company = uuid.uuid4()
    await db.execute(text(
        "INSERT INTO companies (id, name, type, status, created_at, updated_at) "
        "VALUES (:id, 'kb-other', 'TENANT', 'active', now(), now())"), {"id": str(other_company)})
    other = KnowledgeBaseService(db, other_company, embedding=_Embedder())
    for call in (lambda: other.get(doc.id), lambda: other.delete(doc.id),
                 lambda: other.update(doc.id, filename="stolen.md")):
        with pytest.raises(HTTPException) as err:
            await call()
        assert err.value.status_code == 404
    assert len(await _nodes(db, doc.id)) > 0
    # Nor can a document be scoped to another company's agent.
    foreign_entity = await _entity(db, other_company)
    with pytest.raises(HTTPException) as err:
        await svc.update(doc.id, move=True, entity_id=foreign_entity)
    assert err.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_route_exists_and_deletes(db, test_company_id):
    """The Knowledge Base page's delete button calls DELETE /ai/documents/{id}."""
    from types import SimpleNamespace
    from src.ai import router as ai_router_module
    from src.auth.dependencies import get_current_user
    from src.common.database import get_db

    _, doc, _ = await _ingested(db, test_company_id)
    app = FastAPI()
    app.include_router(ai_router_module.router, prefix="/api/v1")

    async def _user():
        return SimpleNamespace(id=uuid.uuid4(), role="tenant_admin", company_id=test_company_id)

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        res = await c.delete(f"/api/v1/ai/documents/{doc.id}")
    assert res.status_code == 200, res.text
    assert res.json()["deleted"] is True and res.json()["nodes_removed"] > 0
    assert await _nodes(db, doc.id) == []
