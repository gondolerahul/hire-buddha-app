"""
migrate_documents_to_knowledge_trees.py — Data Migration Script

Migrates existing document_chunks data into the v2 Knowledge Tree structure.
This is a one-time migration that creates Knowledge Trees for entities with
existing documents and populates them with DOCUMENT→SECTION→CHUNK nodes.

Usage:
    cd backend
    source .venv/bin/activate
    python -m src.ai.migrate_documents_to_knowledge_trees

The script is idempotent — it skips entities that already have a Knowledge Tree
with documents ingested.
"""
import asyncio
import logging
import sys
from uuid import UUID

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("knowledge_tree_migration")


async def migrate_entity_documents(
    db: AsyncSession,
    entity_id: UUID,
    company_id: UUID,
) -> int:
    """Migrate all documents for an entity into a Knowledge Tree."""
    from src.ai.models import Document, DocumentChunk
    from src.ai.memory.knowledge_tree_service import KnowledgeTreeService
    from src.ai.memory.cortex_models import CortexTree, CortexNode, MemoryDomain, ScopeLevel

    # Check if entity already has a knowledge tree with document nodes
    existing = await db.execute(
        select(func.count(CortexNode.id))
        .join(CortexTree, CortexNode.tree_id == CortexTree.id)
        .where(
            CortexTree.entity_id == entity_id,
            CortexTree.memory_domain == MemoryDomain.KNOWLEDGE,
            CortexTree.scope_level == ScopeLevel.ENTITY,
            CortexNode.node_type == "document",
        )
    )
    existing_count = existing.scalar() or 0
    if existing_count > 0:
        logger.info(f"  Entity {entity_id}: already has {existing_count} document nodes, skipping")
        return 0

    # Get all completed documents for this entity
    result = await db.execute(
        select(Document).where(
            Document.entity_id == entity_id,
            Document.company_id == company_id,
            Document.upload_status.in_(["completed", "partial"]),
        ).order_by(Document.created_at)
    )
    documents = result.scalars().all()
    if not documents:
        return 0

    kt_service = KnowledgeTreeService(db, company_id)
    tree = await kt_service.get_or_create_knowledge_tree(entity_id)

    total_nodes = 0
    for doc in documents:
        # Load chunks for this document
        chunks_result = await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc.id)
            .order_by(DocumentChunk.chunk_index)
        )
        chunks = chunks_result.scalars().all()
        if not chunks:
            continue

        # Reconstruct the full text from chunks
        full_text = "\n".join(c.content for c in chunks if c.content)
        if not full_text.strip():
            continue

        try:
            node_count = await kt_service.ingest_document(
                tree_id=tree.id,
                document_id=doc.id,
                content=full_text,
                filename=doc.filename,
                entity_id=entity_id,
            )
            total_nodes += node_count
            logger.info(f"  Migrated document '{doc.filename}': {node_count} nodes")
        except Exception as e:
            logger.error(f"  Failed to migrate document '{doc.filename}': {e}")

    await db.commit()
    return total_nodes


async def run_migration():
    """Main migration entry point."""
    from src.common.database import AsyncSessionLocal
    from src.ai.models import Document

    logger.info("=" * 60)
    logger.info("Knowledge Tree Migration — document_chunks → Knowledge Trees")
    logger.info("=" * 60)

    async with AsyncSessionLocal() as db:
        # Find all entities with documents
        result = await db.execute(
            select(
                Document.entity_id,
                Document.company_id,
                func.count(Document.id).label("doc_count"),
            )
            .where(
                Document.entity_id.isnot(None),
                Document.upload_status.in_(["completed", "partial"]),
            )
            .group_by(Document.entity_id, Document.company_id)
        )
        entity_docs = result.all()

        if not entity_docs:
            logger.info("No entities with documents found. Nothing to migrate.")
            return

        logger.info(f"Found {len(entity_docs)} entities with documents to migrate.")

        total_migrated = 0
        for entity_id, company_id, doc_count in entity_docs:
            logger.info(f"\nMigrating entity {entity_id} ({doc_count} documents)...")
            try:
                nodes = await migrate_entity_documents(db, entity_id, company_id)
                total_migrated += nodes
            except Exception as e:
                logger.error(f"  Entity {entity_id} migration failed: {e}")
                await db.rollback()

        logger.info(f"\n{'=' * 60}")
        logger.info(f"Migration complete: {total_migrated} total nodes created")
        logger.info(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(run_migration())
