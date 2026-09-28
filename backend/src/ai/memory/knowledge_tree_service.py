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
