"""
knowledge_tree_service.py — Persistent Knowledge Tree Management (Phase B)

Manages entity-scoped Knowledge Trees that persist across execution runs.
Unlike runtime CORTEX trees (created per execution), Knowledge Trees are
long-lived repositories of ingested documents organized hierarchically.

Architecture:
  Knowledge Tree (per entity, scope=entity, domain=knowledge)
    └── DOCUMENT node (per uploaded file)
         └── SECTION node (per heading/chapter)
              └── CHUNK node (leaf, with embedding vector)

Usage:
    svc = KnowledgeTreeService(db, company_id)
    tree = await svc.get_or_create_knowledge_tree(entity_id, user_id)
    count = await svc.ingest_document(tree.id, document, text)
    results = await svc.search(entity_id, query, top_k=5)
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_memory.models import (
    CortexTree, CortexNode,
    CortexTreeStatus, CortexNodeType, CortexNodeStatus,
    MemoryDomain, ScopeLevel,
)
from cortex_memory.embedding import embed_node, embed_query, embed_texts

logger = logging.getLogger(__name__)


class KnowledgeTreeService:
    """
    Manages persistent, entity-scoped Knowledge Trees.

    Key differences from runtime CORTEX trees:
    - Persistent: survives across execution runs
    - Entity-scoped: one tree per entity (agent)
    - Embedding-first: every CHUNK node has a vector embedding
    - Hierarchical: DOCUMENT → SECTION → CHUNK structure
    """

    CHUNK_SIZE = 500          # Characters per chunk
    CHUNK_OVERLAP = 50        # Overlap between chunks for context continuity
    MAX_SECTION_DEPTH = 3     # Maximum heading nesting depth
    CHARS_PER_TOKEN = 4

    def __init__(self, db: AsyncSession, company_id: UUID, *, embedding: Any = None):
        self.db = db
        self.company_id = company_id
        self._embedding = embedding  # cortex_memory.EmbeddingProvider | None

    # ===================================================================
    # Tree Lifecycle
    # ===================================================================

    async def get_or_create_knowledge_tree(
        self,
        entity_id: UUID,
        user_id: Optional[UUID] = None,
    ) -> CortexTree:
        """
        Get the persistent Knowledge Tree for an entity, creating one if
        it doesn't exist. Each entity has exactly one Knowledge Tree.
        """
        # Look for existing knowledge tree
        result = await self.db.execute(
            select(CortexTree).where(
                CortexTree.entity_id == entity_id,
                CortexTree.company_id == self.company_id,
                CortexTree.memory_domain == MemoryDomain.KNOWLEDGE,
                CortexTree.scope_level == ScopeLevel.ENTITY,
                CortexTree.status != CortexTreeStatus.ARCHIVED,
            )
        )
        tree = result.scalar_one_or_none()
        if tree:
            return tree

        # Create new Knowledge Tree
        tree_id = uuid4()
        tree = CortexTree(
            id=tree_id,
            entity_id=entity_id,
            user_id=user_id,
            company_id=self.company_id,
            task_description="Persistent Knowledge Base",
            status=CortexTreeStatus.ACTIVE,
            memory_domain=MemoryDomain.KNOWLEDGE,
            scope_level=ScopeLevel.ENTITY,
            is_persistent=True,
            total_nodes=0,
            max_children=50,  # Knowledge trees can be wider
            page_size_tokens=8000,
            context_budget_pct=40,
        )
        self.db.add(tree)
        await self.db.flush()

        # Create root node
        root = CortexNode(
            id=uuid4(),
            tree_id=tree_id,
            parent_id=None,
            node_type=CortexNodeType.ROOT,
            title="📚 Knowledge Base",
            summary="Persistent knowledge repository for this entity.",
            content=None,
            status=CortexNodeStatus.ACTIVE,
            depth=0,
            sibling_order=0,
        )
        self.db.add(root)
        await self.db.flush()

        tree.root_node_id = root.id
        tree.total_nodes = 1
        await self.db.flush()

        logger.info(f"Created Knowledge Tree {tree_id} for entity {entity_id}")
        return tree

    # ===================================================================
    # Document Ingestion (DOCUMENT → SECTION → CHUNK)
    # ===================================================================

    async def ingest_document(
        self,
        tree_id: UUID,
        document_id: UUID,
        content: str,
        filename: str,
        entity_id: Optional[UUID] = None,
    ) -> int:
        """
        Ingest a document into the Knowledge Tree with hierarchical decomposition.

        Creates: DOCUMENT → SECTION → CHUNK nodes with embeddings.
        Returns the number of nodes created.
        """
        if not content or not content.strip():
            logger.warning(f"Empty content for document {document_id}")
            return 0

        tree = await self._get_tree(tree_id)
        root_node_id = tree.root_node_id
        if not root_node_id:
            raise ValueError(f"Knowledge Tree {tree_id} has no root node")

        # Create DOCUMENT node
        doc_summary = self._truncate_summary(content, filename)
        doc_node = CortexNode(
            id=uuid4(),
            tree_id=tree_id,
            parent_id=root_node_id,
            node_type=CortexNodeType.DOCUMENT,
            title=f"📄 {filename}",
            summary=doc_summary,
            content=None,  # Sections hold the content
            status=CortexNodeStatus.COMPLETE,
            depth=1,
            sibling_order=await self._next_sibling_order(root_node_id),
            source_ref={"document_id": str(document_id), "filename": filename},
        )
        self.db.add(doc_node)
        await self.db.flush()
        node_count = 1

        # Parse into sections
        sections = self._parse_sections(content, filename)

        if not sections:
            # No structure detected — chunk entire content directly under doc
            chunk_count = await self._create_chunks(
                tree_id, doc_node.id, content, document_id, filename,
                depth=2,
            )
            node_count += chunk_count
        else:
            # Create SECTION → CHUNK hierarchy
            for idx, (heading, body) in enumerate(sections):
                section_node = CortexNode(
                    id=uuid4(),
                    tree_id=tree_id,
                    parent_id=doc_node.id,
                    node_type=CortexNodeType.SECTION,
                    title=heading,
                    summary=body[:400] + "..." if len(body) > 400 else body,
                    content=None,
                    status=CortexNodeStatus.COMPLETE,
                    depth=2,
                    sibling_order=idx,
                    source_ref={
                        "document_id": str(document_id),
                        "filename": filename,
                        "section_index": idx,
                    },
                )
                self.db.add(section_node)
                await self.db.flush()
                node_count += 1

                # Create CHUNK nodes under this section
                chunk_count = await self._create_chunks(
                    tree_id, section_node.id, body, document_id, filename,
                    depth=3,
                    section_index=idx,
                )
                node_count += chunk_count

        # Embed the document node itself
        await embed_node(self._embedding, doc_node)

        # Update tree
        tree.total_nodes = (tree.total_nodes or 0) + node_count
        await self.db.flush()

        logger.info(
            f"Ingested document '{filename}' into Knowledge Tree {tree_id}: "
            f"{node_count} nodes created"
        )
        return node_count

    # ===================================================================
    # Semantic Search across Knowledge Tree
    # ===================================================================

    async def search(
        self,
        entity_id: UUID,
        query: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Semantic search across an entity's Knowledge Tree.

        Returns CHUNK nodes ranked by cosine similarity, with parent
        context (section title, document filename) included.
        """
        query_vector = await embed_query(self._embedding, query)
        if not query_vector:
            return []

        # Find the entity's knowledge tree
        tree_result = await self.db.execute(
            select(CortexTree.id).where(
                CortexTree.entity_id == entity_id,
                CortexTree.company_id == self.company_id,
                CortexTree.memory_domain == MemoryDomain.KNOWLEDGE,
                CortexTree.scope_level == ScopeLevel.ENTITY,
                CortexTree.status != CortexTreeStatus.ARCHIVED,
            )
        )
        tree_id = tree_result.scalar_one_or_none()
        if not tree_id:
            return []

        # Vector similarity search on CHUNK nodes
        import json
        stmt = text("""
            SELECT 
                cn.id,
                cn.title,
                cn.content,
                cn.source_ref,
                1 - (cn.embedding <=> CAST(:vec AS vector)) AS score,
                parent.title AS section_title,
                grandparent.title AS document_title
            FROM cortex_nodes cn
            LEFT JOIN cortex_nodes parent ON cn.parent_id = parent.id
            LEFT JOIN cortex_nodes grandparent ON parent.parent_id = grandparent.id
            WHERE cn.tree_id = :tree_id
              AND cn.node_type = 'chunk'
              AND cn.embedding IS NOT NULL
            ORDER BY cn.embedding <=> CAST(:vec AS vector)
            LIMIT :top_k
        """)

        result = await self.db.execute(stmt, {
            "vec": json.dumps(list(query_vector)),
            "tree_id": str(tree_id),
            "top_k": top_k,
        })
        rows = result.fetchall()

        # Update access tracking
        if rows:
            node_ids = [r[0] for r in rows]
            # Use individual UUID parameters for asyncpg compatibility
            placeholders = ", ".join(f":id_{i}" for i in range(len(node_ids)))
            params = {f"id_{i}": str(nid) for i, nid in enumerate(node_ids)}
            await self.db.execute(text(
                f"UPDATE cortex_nodes SET access_count = access_count + 1, "
                f"last_accessed_at = NOW() "
                f"WHERE id IN ({placeholders})"
            ), params)

        return [
            {
                "node_id": str(r[0]),
                "title": r[1],
                "content": r[2],
                "source_ref": r[3],
                "score": float(r[4]),
                "section_title": r[5],
                "document_title": r[6],
            }
            for r in rows
        ]

    # ===================================================================
    # Reference Resolution for Runtime Trees
    # ===================================================================

    async def get_knowledge_references(
        self,
        entity_id: UUID,
        query: str,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Get knowledge references for injection into a runtime CORTEX tree.

        Returns lightweight reference dicts (node_id, title, summary, score)
        rather than full content — the agent can READ the full content
        via CORTEX operations if needed.
        """
        results = await self.search(entity_id, query, top_k=top_k)
        return [
            {
                "knowledge_node_id": r["node_id"],
                "title": r.get("document_title", "") + " > " + r.get("section_title", ""),
                "snippet": (r["content"] or "")[:300],
                "score": r["score"],
            }
            for r in results
            if r["score"] > 0.3  # Minimum relevance threshold
        ]

    # ===================================================================
    # Internal Helpers
    # ===================================================================

    async def _create_chunks(
        self,
        tree_id: UUID,
        parent_id: UUID,
        text_content: str,
        document_id: UUID,
        filename: str,
        depth: int,
        section_index: int = 0,
    ) -> int:
        """Create CHUNK nodes with embeddings under a parent node."""
        chunks = self._split_into_chunks(text_content)
        if not chunks:
            return 0

        # Batch embed all chunks
        embeddings, model_name = await embed_texts(self._embedding, chunks)

        count = 0
        for idx, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
            node = CortexNode(
                id=uuid4(),
                tree_id=tree_id,
                parent_id=parent_id,
                node_type=CortexNodeType.CHUNK,
                title=f"Chunk {idx + 1}",
                summary=chunk_text[:200] + "..." if len(chunk_text) > 200 else chunk_text,
                content=chunk_text,
                content_tokens=len(chunk_text) // self.CHARS_PER_TOKEN,
                status=CortexNodeStatus.COMPLETE,
                depth=depth,
                sibling_order=idx,
                source_ref={
                    "document_id": str(document_id),
                    "filename": filename,
                    "chunk_index": idx,
                    "section_index": section_index,
                },
                embedding=embedding,
                embedding_model=model_name if embedding else None,
            )
            self.db.add(node)
            count += 1

        await self.db.flush()
        return count

    def _split_into_chunks(self, text_content: str) -> List[str]:
        """Split text into overlapping chunks."""
        if not text_content:
            return []

        chunks = []
        start = 0
        while start < len(text_content):
            end = start + self.CHUNK_SIZE
            chunk = text_content[start:end]
            if chunk.strip():
                chunks.append(chunk.strip())
            start = end - self.CHUNK_OVERLAP
            if start >= len(text_content):
                break

        return chunks

    def _parse_sections(
        self, content: str, filename: str
    ) -> List[Tuple[str, str]]:
        """Parse document into (heading, body) sections."""
        sections: List[Tuple[str, str]] = []

        # Markdown heading detection
        md_pattern = re.compile(r'^(#{1,4})\s+(.+)$', re.MULTILINE)
        headings = list(md_pattern.finditer(content))

        if headings and len(headings) >= 2:
            for i, match in enumerate(headings):
                heading_text = match.group(2).strip()
                start = match.end()
                end = headings[i + 1].start() if i + 1 < len(headings) else len(content)
                body = content[start:end].strip()
                if body:
                    sections.append((heading_text, body))
            return sections

        # ALL CAPS heading detection
        caps_pattern = re.compile(r'^([A-Z][A-Z\s]{4,}[A-Z])$', re.MULTILINE)
        caps_headings = list(caps_pattern.finditer(content))

        if caps_headings and len(caps_headings) >= 2:
            for i, match in enumerate(caps_headings):
                heading_text = match.group(1).strip().title()
                start = match.end()
                end = caps_headings[i + 1].start() if i + 1 < len(caps_headings) else len(content)
                body = content[start:end].strip()
                if body:
                    sections.append((heading_text, body))
            return sections

        # Fallback: paragraph-based splitting for long docs
        if len(content) > 3000:
            chunk_size = 2000
            for i in range(0, len(content), chunk_size):
                chunk = content[i:i + chunk_size]
                sections.append((f"Section {i // chunk_size + 1}", chunk.strip()))
            return sections

        return []  # Short doc — no sections needed

    def _truncate_summary(self, content: str, filename: str) -> str:
        """Generate a basic summary from content (LLM summary done later)."""
        preview = content[:400].replace("\n", " ").strip()
        return f"Document: {filename}. {preview}..." if len(content) > 400 else f"Document: {filename}. {preview}"

    async def _next_sibling_order(self, parent_id: UUID) -> int:
        """Get the next sibling order for children of a node."""
        result = await self.db.execute(
            select(func.coalesce(func.max(CortexNode.sibling_order), -1))
            .where(CortexNode.parent_id == parent_id)
        )
        return int(result.scalar() or -1) + 1

    async def _get_tree(self, tree_id: UUID) -> CortexTree:
        """Load a CortexTree by ID."""
        result = await self.db.execute(
            select(CortexTree).where(CortexTree.id == tree_id)
        )
        tree = result.scalar_one_or_none()
        if not tree:
            raise ValueError(f"CortexTree {tree_id} not found")
        return tree
