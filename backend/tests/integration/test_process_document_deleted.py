"""A document deleted while ``process_document`` ingests it ends the job quietly.

Found on Azure dev (21 Oct): the isolation suite deleted its document while the
worker was still embedding it; marking it ``failed`` then raised
``ObjectDeletedError`` from the job's own error handler and arq logged a failure.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, text

pytestmark = pytest.mark.needs_db


async def test_a_document_deleted_while_it_is_processed_is_left_alone(monkeypatch):
    from src.ai.core import arq_jobs
    from src.ai.memory.knowledge_tree_service import KnowledgeTreeService
    from src.ai.orm.document import Document
    from src.common.database import AsyncSessionLocal

    company_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        doc = Document(company_id=company_id, filename="gone.txt", file_type="txt", file_size=4)
        db.add(doc)
        await db.commit()
        document_id = doc.id

    async def deleted_meanwhile(self, **_):
        async with AsyncSessionLocal() as other:
            await other.execute(delete(Document).where(Document.id == document_id))
            await other.commit()
        return 0

    monkeypatch.setattr(KnowledgeTreeService, "ingest_document", deleted_meanwhile)
    try:
        await arq_jobs.process_document({}, str(document_id), b"text", "txt", "gone.txt")  # does not raise
        async with AsyncSessionLocal() as db:
            assert await db.get(Document, document_id) is None
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Document).where(Document.id == document_id))
            await db.execute(text("DELETE FROM cortex_trees WHERE company_id = :c"), {"c": company_id})
            await db.commit()
