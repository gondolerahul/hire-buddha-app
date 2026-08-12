"""
cortex_ingestion.py — Document Ingestion Pipeline for CORTEX Trees

Transforms documents into hierarchical knowledge subtrees instead of
flat vector chunks. This is the PageIndex-inspired layer of CORTEX.

Pipeline:
  1. Parse document structure (headings → sections → paragraphs)
  2. Build CortexNode tree mirroring the document hierarchy
  3. Generate LLM summaries for each node (~200 tokens)
  4. Re-cluster if any node exceeds MAX_CHILDREN

Usage:
    ingestion = CortexIngestionPipeline(db, company_id)
    count = await ingestion.ingest_document(
        tree_id=tree_id,
        parent_node_id=knowledge_root_id,
        document_id=doc_id,
        content=full_text,
        filename="report.pdf",
    )
"""
from __future__ import annotations

import logging
import re
from typing import Any, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from cortex_memory.service import CortexService
from cortex_memory.enums import CortexNodeType

logger = logging.getLogger(__name__)


class CortexIngestionPipeline:
    """
    Ingests documents into a CORTEX tree as hierarchical knowledge nodes.
    
    Gap #15: Uses LLM to generate navigation-quality summaries (~200 tokens)
    instead of simple string truncation.
    """

    def __init__(
        self,
        db: AsyncSession,
        company_id: UUID,
        *,
        llm: Any = None,
        cortex: Any = None,
    ):
        self.db = db
        self.company_id = company_id
        # Injected cortex_memory.LLMProvider for navigation-quality summaries;
        # falls back to truncation when absent (standalone use).
        self._llm = llm
        self.cortex = cortex or CortexService(db, company_id)

    async def ingest_document(
        self,
        tree_id: UUID,
        parent_node_id: UUID,
        document_id: UUID,
        content: str,
        filename: str,
    ) -> int:
        """
        Ingest a document into the CORTEX tree as knowledge nodes.
        
        Returns the number of nodes created.
        """
        if not content or not content.strip():
            logger.warning(f"Empty content for document {document_id}")
            return 0

        # Parse document into sections
        sections = self._parse_sections(content, filename)

        if not sections:
            # Single node for the entire document
            summary = await self._generate_summary(content, filename)
            await self.cortex.write(
                parent_id=parent_node_id,
                node_type="knowledge",
                title=f"📄 {filename}",
                content=content,
                summary=summary,
                status="complete",
                source_ref={"document_id": str(document_id), "filename": filename},
            )
            return 1

        # Create document root node
        doc_summary = await self._generate_summary(
            content[:2000],
            filename,
            context=f"This document has {len(sections)} sections and ~{len(content)} characters."
        )
        doc_node_id = await self.cortex.write(
            parent_id=parent_node_id,
            node_type="knowledge",
            title=f"📄 {filename}",
            content=None,
            summary=doc_summary,
            status="complete",
            source_ref={"document_id": str(document_id), "filename": filename},
        )

        # Create section nodes
        node_count = 1
        for i, (heading, section_content) in enumerate(sections):
            section_summary = await self._generate_summary(section_content, heading)
            await self.cortex.write(
                parent_id=doc_node_id,
                node_type="knowledge",
                title=heading,
                content=section_content,
                summary=section_summary,
                status="complete",
                sibling_order=i,
                source_ref={
                    "document_id": str(document_id),
                    "filename": filename,
                    "section_index": i,
                    "heading": heading,
                },
            )
            node_count += 1

        await self.db.flush()
        logger.info(f"Ingested document {filename} into tree {tree_id}: {node_count} nodes")
        return node_count

    async def _generate_summary(
        self, content: str, title: str, context: str = ""
    ) -> str:
        """
        Gap #15: Generate LLM navigation-quality summary (~200 tokens).
        
        The summary is optimised for helping another LLM decide whether
        this node/section contains information relevant to its current task.
        Falls back to truncation if LLM is unavailable.
        """
        try:
            if self._llm is None:
                raise RuntimeError("no LLM provider injected")

            system_prompt = (
                "Generate a concise ~200 token summary of this document section. "
                "The summary should help an AI agent decide whether this section "
                "contains information relevant to its current task. Focus on the "
                "key topics, entities, and facts covered. Be specific, not generic."
            )

            user_prompt = f"Title: {title}\n"
            if context:
                user_prompt += f"Context: {context}\n"
            user_prompt += f"\nContent:\n{content[:4000]}"

            resp = await self._llm.complete(
                task_type="text_generation",
                system=system_prompt,
                user=user_prompt,
                temperature=0.3,
                max_tokens=300,
            )
            return (resp.text or "")[:500]
        except Exception as e:
            logger.warning(f"LLM summary generation failed for '{title}', using truncation: {e}")
            return content[:400] + "..." if len(content) > 400 else content

    def _parse_sections(
        self, content: str, filename: str
    ) -> List[Tuple[str, str]]:
        """
        Parse document content into (heading, body) sections.
        
        Uses heading detection (markdown # or ALL CAPS lines) to split.
        Falls back to paragraph-based chunking for unstructured text.
        """
        sections: List[Tuple[str, str]] = []

        # Try markdown heading detection first
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

        # Try ALL CAPS heading detection
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

        # Fallback: split into ~2000 char chunks
        chunk_size = 2000
        if len(content) <= chunk_size:
            return []  # Single node will be created

        chunks = []
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i + chunk_size]
            chunk_num = i // chunk_size + 1
            chunks.append((f"Section {chunk_num}", chunk.strip()))

        return chunks
