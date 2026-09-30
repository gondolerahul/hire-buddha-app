"""
ai.services.knowledge_base — the Knowledge Base page's documents, stored in CORTEX.

A knowledge-base document is two things that must stay in step:

  * a ``documents`` row — filename, type, size, scope and ingestion status; and
  * the nodes ``process_document`` ingests into a Knowledge Tree
    (DOCUMENT → SECTION → CHUNK, each chunk embedded): the scoped agent's
    Knowledge Tree, or the company-wide tree every agent of the company reads.

Memory retrieval and document search read the nodes, so every change here —
rename, re-scope, replace, delete — is applied to both. Every operation is
confined to the caller's company.
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from src.ai.memory.knowledge_tree_service import KnowledgeTreeService
from src.ai.orm.document import Document
from src.ai.orm.entity import HierarchicalEntity

logger = logging.getLogger(__name__)


def file_type_of(filename: str) -> str:
    """The extension the ingestion job dispatches on (pdf, docx; anything else is text)."""
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"


class KnowledgeBaseService:
    def __init__(self, db: Any, company_id: UUID, *, embedding: Optional[Any] = None) -> None:
        self.db = db
        self.company_id = company_id
        self._embedding = embedding

    def _trees(self) -> KnowledgeTreeService:
        return KnowledgeTreeService(self.db, self.company_id, embedding=self._embedding)

    # ── Create ───────────────────────────────────────────────────────────

    async def upload(
        self, file_content: bytes, filename: str, file_type: str, entity_id: Optional[UUID] = None,
    ) -> Document:
        if entity_id:
            await self._require_entity(entity_id)
        document = Document(
            company_id=self.company_id, entity_id=entity_id, filename=filename,
            file_type=file_type, file_size=str(len(file_content)), upload_status="processing",
        )
        self.db.add(document)
        await self.db.commit()
        await self.db.refresh(document)
        await self._enqueue_ingestion(document, file_content)
        return document

    # ── Read ─────────────────────────────────────────────────────────────

    async def list(self, entity_id: Optional[UUID] = None) -> list[dict[str, Any]]:
        stmt = (
            select(Document, HierarchicalEntity.display_name, HierarchicalEntity.name)
            .outerjoin(HierarchicalEntity, HierarchicalEntity.id == Document.entity_id)
            .where(Document.company_id == self.company_id)
            .order_by(Document.created_at.desc())
        )
        if entity_id:
            stmt = stmt.where(Document.entity_id == entity_id)
        rows = (await self.db.execute(stmt)).all()
        return [self._as_dict(doc, display or name) for doc, display, name in rows]

    async def get(self, document_id: UUID) -> dict[str, Any]:
        document = await self._load(document_id)
        entity_name = await self._entity_name(document.entity_id)
        outline = await self._trees().document_outline(document.id)
        return {**self._as_dict(document, entity_name), **outline}

    async def search(self, query: str, entity_id: Optional[UUID] = None, top_k: int = 5) -> list[dict[str, Any]]:
        results = await self._trees().search_documents(query, entity_id=entity_id, top_k=top_k)
        if results is None:
            raise HTTPException(
                status_code=500,
                detail="Embedding generation failed. Please check your AI integration configuration.",
            )
        return results

    # ── Update ───────────────────────────────────────────────────────────

    async def update(
        self, document_id: UUID, *, filename: Optional[str] = None,
        move: bool = False, entity_id: Optional[UUID] = None,
    ) -> dict[str, Any]:
        """Rename and/or re-scope. ``move`` with ``entity_id=None`` makes it company-wide."""
        document = await self._load(document_id)
        self._require_settled(document)
        trees = self._trees()

        if filename is not None:
            filename = filename.strip()
            if not filename:
                raise HTTPException(status_code=422, detail="filename must not be empty")
            if filename != document.filename:
                await trees.rename_document(document.id, filename)
                document.filename = filename

        if move and entity_id != document.entity_id:
            if entity_id:
                await self._require_entity(entity_id)
                target = await trees.get_or_create_knowledge_tree(entity_id=entity_id)
            else:
                target = await trees.get_or_create_company_knowledge_tree()
            await trees.move_document(document.id, target)
            document.entity_id = entity_id

        await self.db.commit()
        await self.db.refresh(document)
        return await self.get(document.id)

    async def replace_file(
        self, document_id: UUID, file_content: bytes, filename: str, file_type: str,
    ) -> Document:
        """Swap in new content: the old nodes go now, the new ones are ingested by the job."""
        document = await self._load(document_id)
        self._require_settled(document)
        await self._trees().delete_document(document.id)
        document.filename = filename
        document.file_type = file_type
        document.file_size = str(len(file_content))
        document.upload_status = "processing"
        await self.db.commit()
        await self.db.refresh(document)
        await self._enqueue_ingestion(document, file_content)
        return document

    # ── Delete ───────────────────────────────────────────────────────────

    async def delete(self, document_id: UUID) -> int:
        """Delete the document and every Knowledge Tree node ingested from it."""
        document = await self._load(document_id)
        removed = await self._trees().delete_document(document.id)
        await self.db.delete(document)
        await self.db.commit()
        logger.info(f"Deleted document {document_id} and {removed} Knowledge Tree nodes")
        return removed

    # ── Helpers ──────────────────────────────────────────────────────────

    async def _load(self, document_id: UUID) -> Document:
        document = (await self.db.execute(
            select(Document).where(Document.id == document_id, Document.company_id == self.company_id)
        )).scalar_one_or_none()
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return document

    async def _require_entity(self, entity_id: UUID) -> HierarchicalEntity:
        entity = (await self.db.execute(
            select(HierarchicalEntity).where(
                HierarchicalEntity.id == entity_id,
                HierarchicalEntity.company_id == self.company_id,
            )
        )).scalar_one_or_none()
        if entity is None:
            raise HTTPException(status_code=404, detail="Entity not found in your company")
        return entity

    async def _entity_name(self, entity_id: Optional[UUID]) -> Optional[str]:
        if not entity_id:
            return None
        row = (await self.db.execute(
            select(HierarchicalEntity.display_name, HierarchicalEntity.name)
            .where(HierarchicalEntity.id == entity_id)
        )).first()
        return (row[0] or row[1]) if row else None

    @staticmethod
    def _require_settled(document: Document) -> None:
        # The ingestion job reads the scope and filename when it starts; changing
        # either mid-flight would put nodes in the wrong tree or under the old name.
        if document.upload_status == "processing":
            raise HTTPException(
                status_code=409,
                detail="The document is still being processed. Try again when it is ready.",
            )

    async def _enqueue_ingestion(self, document: Document, file_content: bytes) -> None:
        from src.common.job_queue import enqueue_job

        try:
            await enqueue_job(
                "process_document", str(document.id), file_content,
                document.file_type, document.filename,
            )
        except Exception as exc:
            logger.error(f"Could not enqueue ingestion for document {document.id}: {exc}")
            document.upload_status = "failed"
            await self.db.commit()
            raise HTTPException(status_code=503, detail="Could not queue the document for processing")

    @staticmethod
    def _as_dict(document: Document, entity_name: Optional[str]) -> dict[str, Any]:
        return {
            "id": document.id,
            "company_id": document.company_id,
            "entity_id": document.entity_id,
            "entity_name": entity_name,
            "filename": document.filename,
            "file_type": document.file_type,
            "file_size": document.file_size,
            "upload_status": document.upload_status,
            "created_at": document.created_at,
            "updated_at": document.updated_at,
        }
