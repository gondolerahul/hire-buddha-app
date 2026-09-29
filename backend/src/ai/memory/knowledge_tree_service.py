"""
ai.memory.knowledge_tree_service — host re-export + auto-injection shim.

``KnowledgeTreeService`` moved into the ``cortex_memory`` package (Phase 12 `04` Stage B).
The package class takes a ``cortex_memory.EmbeddingProvider`` via injection; this
shim subclasses it and auto-injects the host ``HostEmbeddingProvider`` so
``KnowledgeTreeService(db, company_id)`` is unchanged.

Host additions: the company-wide Knowledge Tree (documents uploaded without an
entity) and company-scoped document search, which back the Knowledge Base page.
"""
from __future__ import annotations

import json
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import select, text

from cortex_memory.knowledge_tree import KnowledgeTreeService as _PackageKnowledgeTreeService
from cortex_memory.embedding import embed_query
from cortex_memory.models import (
    CortexNode, CortexNodeStatus, CortexNodeType, CortexTree, CortexTreeStatus,
    MemoryDomain, ScopeLevel,
)


class KnowledgeTreeService(_PackageKnowledgeTreeService):
    def __init__(self, db: Any, company_id: UUID, *, embedding: Optional[Any] = None) -> None:
        if embedding is None:
            from src.ai.memory.cortex_providers import HostEmbeddingProvider

            embedding = HostEmbeddingProvider(db, company_id)
        super().__init__(db, company_id, embedding=embedding)

    async def get_or_create_company_knowledge_tree(self) -> CortexTree:
        """The company-wide Knowledge Tree (TENANT scope, no entity).

        Holds documents uploaded without an entity. Memory retrieval treats
        tenant-scoped trees as visible to every entity of the company.
        """
        tree = (await self.db.execute(
            select(CortexTree).where(
                CortexTree.company_id == self.company_id,
                CortexTree.entity_id.is_(None),
                CortexTree.memory_domain == MemoryDomain.KNOWLEDGE,
                CortexTree.scope_level == ScopeLevel.TENANT,
                CortexTree.status != CortexTreeStatus.ARCHIVED,
            )
        )).scalars().first()
        if tree:
            return tree

        tree = CortexTree(
            id=uuid4(), entity_id=None, company_id=self.company_id,
            task_description="Company Knowledge Base",
            status=CortexTreeStatus.ACTIVE,
            memory_domain=MemoryDomain.KNOWLEDGE, scope_level=ScopeLevel.TENANT,
            is_persistent=True, total_nodes=1, max_children=50,
        )
        self.db.add(tree)
        await self.db.flush()
        root = CortexNode(
            id=uuid4(), tree_id=tree.id, parent_id=None,
            node_type=CortexNodeType.ROOT, title="📚 Company Knowledge Base",
            summary="Documents shared with every agent in this company.",
            status=CortexNodeStatus.ACTIVE, depth=0, sibling_order=0,
        )
        self.db.add(root)
        await self.db.flush()
        tree.root_node_id = root.id
        await self.db.flush()
        return tree

    async def chunk_embedding_counts(self, tree_id: UUID, document_id: UUID) -> tuple[int, int]:
        """``(total, embedded)`` chunk counts for one ingested document."""
        row = (await self.db.execute(text("""
            SELECT COUNT(*), COUNT(embedding)
            FROM cortex_nodes
            WHERE tree_id = :tree_id AND node_type = 'chunk'
              AND source_ref->>'document_id' = :document_id
        """), {"tree_id": str(tree_id), "document_id": str(document_id)})).one()
        return int(row[0]), int(row[1])

    # ── One document's nodes ─────────────────────────────────────────────
    # Ingestion stamps source_ref.document_id on every node it creates for a
    # document (DOCUMENT, SECTION and CHUNK), so that key finds them all. Every
    # query is confined to this company's Knowledge Trees.

    _DOC_NODES = """
        FROM cortex_nodes cn
        JOIN cortex_trees ct ON ct.id = cn.tree_id
        WHERE ct.company_id = :company_id
          AND ct.memory_domain = 'knowledge'
          AND cn.source_ref->>'document_id' = :document_id
    """

    def _doc_params(self, document_id: UUID) -> dict[str, str]:
        return {"company_id": str(self.company_id), "document_id": str(document_id)}

    async def delete_document(self, document_id: UUID) -> int:
        """Delete every node of a document (their embeddings and edges go with them).

        Returns the number of nodes deleted; tree node counts are adjusted.
        """
        rows = (await self.db.execute(text("""
            DELETE FROM cortex_nodes cn
            USING cortex_trees ct
            WHERE cn.tree_id = ct.id
              AND ct.company_id = :company_id
              AND ct.memory_domain = 'knowledge'
              AND cn.source_ref->>'document_id' = :document_id
            RETURNING cn.tree_id
        """), self._doc_params(document_id))).fetchall()
        per_tree: dict[str, int] = {}
        for (tree_id,) in rows:
            per_tree[str(tree_id)] = per_tree.get(str(tree_id), 0) + 1
        for tree_id, removed in per_tree.items():
            await self.db.execute(text(
                "UPDATE cortex_trees SET total_nodes = GREATEST(COALESCE(total_nodes, 0) - :n, 0) "
                "WHERE id = :tree_id"
            ), {"n": removed, "tree_id": tree_id})
        return len(rows)

    async def rename_document(self, document_id: UUID, filename: str) -> None:
        """Carry a new filename onto the document's nodes (title and source_ref)."""
        await self.db.execute(text(f"""
            UPDATE cortex_nodes n
            SET source_ref = jsonb_set(n.source_ref, '{{filename}}', to_jsonb(CAST(:filename AS text))),
                title = CASE WHEN n.node_type = 'document' THEN :title ELSE n.title END
            WHERE n.id IN (SELECT cn.id {self._DOC_NODES})
        """), {**self._doc_params(document_id), "filename": filename, "title": f"📄 {filename}"})

    async def move_document(self, document_id: UUID, target_tree: CortexTree) -> None:
        """Move a document's nodes into ``target_tree``, under its root."""
        doc_node = (await self.db.execute(text(f"""
            SELECT cn.id, cn.tree_id {self._DOC_NODES} AND cn.node_type = 'document'
        """), self._doc_params(document_id))).first()
        if doc_node is None or str(doc_node[1]) == str(target_tree.id):
            return
        source_tree_id = str(doc_node[1])
        moved = (await self.db.execute(text("""
            UPDATE cortex_nodes SET tree_id = :target
            WHERE tree_id = :source AND source_ref->>'document_id' = :document_id
            RETURNING id
        """), {"target": str(target_tree.id), "source": source_tree_id,
               "document_id": str(document_id)})).fetchall()
        await self.db.execute(text("""
            UPDATE cortex_nodes SET parent_id = :root,
                sibling_order = (SELECT COALESCE(MAX(sibling_order), -1) + 1
                                 FROM cortex_nodes WHERE parent_id = :root)
            WHERE id = :doc_node
        """), {"root": str(target_tree.root_node_id), "doc_node": str(doc_node[0])})
        await self.db.execute(text(
            "UPDATE cortex_trees SET total_nodes = GREATEST(COALESCE(total_nodes, 0) - :n, 0) WHERE id = :t"
        ), {"n": len(moved), "t": source_tree_id})
        await self.db.execute(text(
            "UPDATE cortex_trees SET total_nodes = COALESCE(total_nodes, 0) + :n WHERE id = :t"
        ), {"n": len(moved), "t": str(target_tree.id)})

    async def document_outline(self, document_id: UUID, preview_chars: int = 6000) -> dict[str, Any]:
        """What was ingested: chunk counts, section titles and the opening text."""
        params = self._doc_params(document_id)
        total, embedded = (await self.db.execute(text(f"""
            SELECT COUNT(*), COUNT(cn.embedding) {self._DOC_NODES} AND cn.node_type = 'chunk'
        """), params)).one()
        sections = (await self.db.execute(text(f"""
            SELECT cn.title {self._DOC_NODES} AND cn.node_type = 'section'
            ORDER BY cn.sibling_order
        """), params)).scalars().all()
        chunks = (await self.db.execute(text(f"""
            SELECT cn.content {self._DOC_NODES} AND cn.node_type = 'chunk'
            ORDER BY COALESCE((cn.source_ref->>'section_index')::int, 0), cn.sibling_order
        """), params)).scalars().all()
        preview, used = [], 0
        for chunk in chunks:
            if used >= preview_chars:
                break
            piece = (chunk or "")[: preview_chars - used]
            preview.append(piece)
            used += len(piece)
        return {
            "chunks_total": int(total),
            "chunks_embedded": int(embedded),
            "sections": list(sections),
            "preview": "\n\n".join(preview),
            "preview_truncated": used >= preview_chars,
        }

    async def search_documents(
        self, query: str, *, entity_id: Optional[UUID] = None, top_k: int = 5,
    ) -> Optional[list[dict[str, Any]]]:
        """Semantic search over this company's ingested document chunks.

        With ``entity_id``: that entity's Knowledge Tree plus the company tree.
        Without: every Knowledge Tree in the company. ``None`` when the query
        could not be embedded (so a broken embedding setup is not reported as
        "no results").
        """
        vector = await embed_query(self._embedding, query)
        if not vector:
            return None
        rows = (await self.db.execute(text("""
            SELECT cn.id, cn.content, cn.source_ref,
                   1 - (cn.embedding <=> CAST(:vec AS vector)) AS similarity
            FROM cortex_nodes cn
            JOIN cortex_trees ct ON ct.id = cn.tree_id
            WHERE ct.company_id = :company_id
              AND ct.memory_domain = 'knowledge'
              AND ct.scope_level IN ('entity', 'tenant')
              AND ct.status != 'archived'
              AND (CAST(:entity_id AS uuid) IS NULL
                   OR ct.entity_id = CAST(:entity_id AS uuid)
                   OR ct.scope_level = 'tenant')
              AND cn.node_type = 'chunk'
              AND cn.embedding IS NOT NULL
            ORDER BY cn.embedding <=> CAST(:vec AS vector)
            LIMIT :top_k
        """), {
            "vec": json.dumps(list(vector)),
            "company_id": str(self.company_id),
            "entity_id": str(entity_id) if entity_id else None,
            "top_k": top_k,
        })).fetchall()
        return [
            {
                "chunk_id": str(r[0]),
                "document_id": (r[2] or {}).get("document_id"),
                "filename": (r[2] or {}).get("filename"),
                "content": r[1],
                "similarity": float(r[3]),
            }
            for r in rows
        ]


__all__ = ["KnowledgeTreeService"]
