"""
ai.memory.knowledge_tree_service — host re-export + auto-injection shim.

``KnowledgeTreeService`` moved into the ``cortex_memory`` package (Phase 12 `04` Stage B).
The package class takes a ``cortex_memory.EmbeddingProvider`` via injection; this
shim subclasses it and auto-injects the host ``HostEmbeddingProvider`` so
``KnowledgeTreeService(db, company_id)`` is unchanged.
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from cortex_memory.knowledge_tree import KnowledgeTreeService as _PackageKnowledgeTreeService


class KnowledgeTreeService(_PackageKnowledgeTreeService):
    def __init__(self, db: Any, company_id: UUID, *, embedding: Optional[Any] = None) -> None:
        if embedding is None:
            from src.ai.memory.cortex_providers import HostEmbeddingProvider

            embedding = HostEmbeddingProvider(db, company_id)
        super().__init__(db, company_id, embedding=embedding)


__all__ = ["KnowledgeTreeService"]
