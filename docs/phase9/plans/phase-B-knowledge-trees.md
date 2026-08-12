# Phase B: Knowledge Trees — Structured Document Ingestion

**Timeline**: Week 3–4  
**Risk Level**: MEDIUM  
**Dependencies**: Phase A (schema evolution complete)  
**Goal**: Migrate the existing flat `documents`/`document_chunks` storage into hierarchical CORTEX Knowledge Trees with embedded semantic vectors, preserving backward compatibility.

---

## B.1 Executive Summary

Phase B replaces the flat document storage model with a structured Knowledge Tree architecture where documents are decomposed into `DOCUMENT → SECTION → CHUNK` hierarchies within CORTEX Trees. Each tree is scoped to the appropriate level (Tenant, Entity, User) and every leaf CHUNK node receives an embedding vector for semantic search. This phase also fixes the broken embedding pipeline (404 error on `gemini-embedding-004`).

---

## B.2 Current State Analysis

### What Exists Today

| Component | Location | Status |
|---|---|---|
| `documents` table | `models.py:197-212` | ✅ Working (stores metadata) |
| `document_chunks` table | `models.py:214-224` | ⚠️ Partially working (embeddings broken - 404) |
| `cortex_ingestion.py` | 215 lines | ✅ Working (heading-based section parsing) |
| `process_document()` | `worker.py` | ⚠️ Broken embeddings (sets status "completed" even when all fail) |
| Semantic search | `memory_service.py:180-243` | ❌ Broken (embedding API 404) |

### What Changes

| Current | Phase B |
|---|---|
| Flat `document_chunks` with optional embeddings | Hierarchical `DOCUMENT → SECTION → CHUNK` nodes in Knowledge Trees |
| One-level chunking (500 chars) | Multi-level decomposition with LLM summaries at each level |
| Broken embedding pipeline | Fixed embedding pipeline + embeddings on all CHUNK/SECTION/DOCUMENT nodes |
| Company-scoped documents | Multi-level scoping (Tenant/Entity/User Knowledge Trees) |
| Content duplicated into CORTEX at runtime | Reference-not-copy architecture (runtime nodes point to persistent KB) |

---

## B.3 Detailed Implementation

### B.3.1 Fix Embedding Pipeline (Critical — Unblocks Everything)

**File**: `backend/src/ai/constants.py`

```python
# Fix #1: Update embedding model to current valid name
EMBEDDING_MODEL = "text-embedding-005"  # Verify via: gcloud ai models list --region=us-central1
```

**File**: `backend/src/ai/worker.py` (process_document function)

Fix #2: Set `upload_status = "failed"` when ALL chunks fail embedding:
```python
# After processing all chunks:
if failed_count == total_chunks:
    document.upload_status = "failed"
    logger.error(f"All {total_chunks} chunks failed embedding for document {document.id}")
elif failed_count > 0:
    document.upload_status = "partial"
    logger.warning(f"{failed_count}/{total_chunks} chunks failed embedding")
else:
    document.upload_status = "completed"
```

### B.3.2 Create Knowledge Tree Management Service

**New file**: `backend/src/ai/knowledge_tree_service.py`

This service manages persistent Knowledge Trees at each scope level:

```python
class KnowledgeTreeService:
    """Manages persistent Knowledge Trees at all scope levels."""

    async def get_or_create_knowledge_tree(
        self,
        scope_level: ScopeLevel,
        company_id: UUID,
        entity_id: UUID = None,
        user_id: UUID = None,
        category: str = None,
    ) -> CortexTree:
        """
        Get or create a Knowledge Tree at the specified scope level.
        
        Rules:
        - TENANT: One tree per company (or per category if specified)
        - ENTITY: One tree per entity
        - USER: One tree per user
        """
        # Query for existing tree
        stmt = select(CortexTree).where(
            CortexTree.memory_domain == MemoryDomain.KNOWLEDGE,
            CortexTree.scope_level == scope_level,
            CortexTree.company_id == company_id,
        )
        if entity_id:
            stmt = stmt.where(CortexTree.entity_id == entity_id)
        if user_id:
            stmt = stmt.where(CortexTree.user_id == user_id)
        if category:
            stmt = stmt.where(CortexTree.tree_category == category)
        
        result = await self.db.execute(stmt)
        tree = result.scalar_one_or_none()
        
        if tree:
            return tree
        
        # Create new Knowledge Tree
        return await self._create_knowledge_tree(
            scope_level, company_id, entity_id, user_id, category
        )
```

### B.3.3 Enhanced Document Ingestion Pipeline v2

**File**: `backend/src/ai/cortex_ingestion.py` (MODIFY)

Transform the existing `CortexIngestionPipeline` into `KnowledgeIngestionPipeline`:

```
Source Document (PDF/DOCX/TXT/...)
    │
    ├── 1. Document Parser (enhanced)
    │   ├── Heading detection → Section boundaries (existing)
    │   ├── Table extraction → Structured chunks (NEW)
    │   └── Metadata extraction (title, author, date) (NEW)
    │
    ├── 2. Hierarchical Node Creation
    │   ├── DOCUMENT node (metadata, source_ref with full provenance)
    │   │   └── node_type = CortexNodeType.DOCUMENT
    │   ├── SECTION nodes (heading-based decomposition)
    │   │   └── node_type = CortexNodeType.SECTION
    │   └── CHUNK nodes (overlapping 500-char windows within sections)
    │       └── node_type = CortexNodeType.CHUNK
    │
    ├── 3. Embedding Generation (batch, async)
    │   ├── Each CHUNK gets embedding vector (768-dim)
    │   ├── Each SECTION summary gets embedding vector
    │   └── DOCUMENT summary gets embedding vector
    │
    ├── 4. LLM Summary Generation
    │   ├── DOCUMENT: Full document summary (~200 tokens)
    │   ├── SECTION: Section summary (~150 tokens)
    │   └── CHUNK: Content is the chunk text itself (no extra summary needed)
    │
    └── 5. Category Classification (NEW)
        └── LLM classifies document → tree_category assignment
```

**Key Changes from v1**:
- Use new `DOCUMENT`, `SECTION`, `CHUNK` node types instead of flat `KNOWLEDGE` nodes
- Generate embeddings at every level (not just chunks)
- Write to persistent Knowledge Trees (not runtime trees)
- Track `importance_score` based on document metadata
- Populate `source_ref` with rich provenance data

### B.3.4 Embedding Service

**New file**: `backend/src/ai/embedding_service.py`

Centralized embedding generation with batching and cost tracking:

```python
class EmbeddingService:
    """Centralized embedding generation with batching and error handling."""
    
    BATCH_SIZE = 100  # Max items per API call
    
    async def embed_batch(
        self,
        texts: List[str],
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> List[Optional[List[float]]]:
        """
        Embed a batch of texts. Returns list of embedding vectors.
        None entries indicate failures (logged, not raised).
        """
        
    async def embed_node(
        self,
        node: CortexNode,
    ) -> None:
        """
        Generate and store embedding for a single node.
        Uses node.summary if available, otherwise node.title.
        Sets node.embedding and node.embedding_model.
        """
        text_to_embed = node.summary or node.title
        if not text_to_embed:
            return
        
        embeddings = await self.embed_batch([text_to_embed])
        if embeddings and embeddings[0]:
            node.embedding = embeddings[0]
            node.embedding_model = EMBEDDING_MODEL
```

### B.3.5 Data Migration: `document_chunks` → Knowledge Trees

**New file**: `backend/src/ai/migrations/migrate_kb_to_trees.py`

A one-time migration script that:

1. Groups existing `documents` by `company_id`
2. For each company, creates a Tenant-level Knowledge Tree
3. For each document:
   a. Creates a `DOCUMENT` node under the Knowledge Tree root
   b. Reconstitutes sections from existing chunks (using heading detection)
   c. Creates `SECTION` and `CHUNK` nodes
   d. Copies existing embeddings from `document_chunks.embedding` to `cortex_nodes.embedding`
   e. Generates missing embeddings in batch
4. Marks migration status in a tracking table

```python
async def migrate_company_documents(company_id: UUID):
    """Migrate all documents for a company into Knowledge Trees."""
    
    # 1. Create or get Tenant-level Knowledge Tree
    kb_tree = await knowledge_tree_service.get_or_create_knowledge_tree(
        scope_level=ScopeLevel.TENANT,
        company_id=company_id,
    )
    
    # 2. Load all documents for this company
    documents = await db.execute(
        select(Document).where(Document.company_id == company_id)
    )
    
    for doc in documents:
        # 3. Create DOCUMENT node
        doc_node_id = await cortex.write(
            parent_id=kb_tree.root_node_id,
            node_type="document",
            title=f"📄 {doc.filename}",
            summary=None,  # Will be generated
            source_ref={
                "document_id": str(doc.id),
                "filename": doc.filename,
                "file_type": doc.file_type,
                "original_table": "documents",
            },
        )
        
        # 4. Load existing chunks
        chunks = await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc.id)
            .order_by(DocumentChunk.chunk_index)
        )
        
        # 5. Group chunks into sections (heuristic: heading detection in content)
        sections = _group_chunks_into_sections(chunks)
        
        for section_title, section_chunks in sections:
            # Create SECTION node
            section_node_id = await cortex.write(
                parent_id=doc_node_id,
                node_type="section",
                title=section_title,
                summary=None,  # LLM summary generated later
            )
            
            for chunk in section_chunks:
                # Create CHUNK node with existing embedding
                chunk_node_id = await cortex.write(
                    parent_id=section_node_id,
                    node_type="chunk",
                    title=f"Chunk {chunk.chunk_index}",
                    content=chunk.content,
                    summary=chunk.content[:200],
                )
                
                # Copy existing embedding if available
                if chunk.embedding is not None:
                    node = await cortex._get_node(chunk_node_id)
                    node.embedding = chunk.embedding
                    node.embedding_model = EMBEDDING_MODEL
```

### B.3.6 Update Document Upload Flow

**File**: `backend/src/ai/worker.py` (process_document function)

Modify the document processing pipeline to write to Knowledge Trees instead of (or in addition to) the flat `document_chunks` table:

```python
async def process_document(ctx, document_id: str, content: bytes):
    # ... existing parsing logic ...
    
    # NEW: Write to Knowledge Tree (v2)
    from src.ai.knowledge_tree_service import KnowledgeTreeService
    kb_service = KnowledgeTreeService(db, company_id)
    
    # Determine scope level based on document ownership
    if document.entity_id:
        scope_level = ScopeLevel.ENTITY
    else:
        scope_level = ScopeLevel.TENANT
    
    kb_tree = await kb_service.get_or_create_knowledge_tree(
        scope_level=scope_level,
        company_id=document.company_id,
        entity_id=document.entity_id,
    )
    
    # Use enhanced ingestion pipeline
    pipeline = KnowledgeIngestionPipeline(db, company_id, embedding_service)
    node_count = await pipeline.ingest_document_v2(
        tree=kb_tree,
        document_id=document.id,
        content=text_content,
        filename=document.filename,
    )
    
    # BACKWARD COMPAT: Also write to document_chunks (dual-write during transition)
    # ... existing chunking + embedding logic ...
```

### B.3.7 Update Runtime Knowledge Access

**File**: `backend/src/ai/cortex_bridge.py`

When an execution starts, instead of copying full content into runtime nodes, create reference nodes:

```python
async def write_knowledge_reference(
    self,
    runtime_tree: CortexTree,
    source_node: CortexNode,
    knowledge_root_id: UUID,
) -> UUID:
    """Write a reference node in the runtime tree pointing to a Knowledge Tree node."""
    return await self.cortex.write(
        parent_id=knowledge_root_id,
        node_type="knowledge",
        title=f"📎 {source_node.title}",
        summary=source_node.summary,
        content=None,  # NO CONTENT DUPLICATION
        source_ref={
            "ref_type": "cortex_node",
            "source_tree_id": str(source_node.tree_id),
            "source_node_id": str(source_node.id),
            "source_scope": "tenant",
        },
        cross_refs=[{
            "tree_id": str(source_node.tree_id),
            "node_id": str(source_node.id),
            "relationship": "references",
        }],
    )
```

### B.3.8 Reference Resolution on READ

**File**: `backend/src/ai/cortex_service.py`

Update the `read()` method to support reference resolution:

```python
async def read(self, node_id: UUID, page: int = 0) -> NodeContent:
    node = await self._get_node(node_id)
    content = node.content or ""
    
    # NEW: Reference resolution — if content is empty but source_ref exists
    if not content and node.source_ref:
        ref = node.source_ref
        if ref.get("ref_type") == "cortex_node":
            try:
                source_node = await self._get_node_cross_tree(
                    UUID(ref["source_tree_id"]),
                    UUID(ref["source_node_id"]),
                )
                content = source_node.content or ""
            except Exception as e:
                logger.warning(f"Reference resolution failed for node {node_id}: {e}")
    
    # Update access tracking (NEW)
    node.access_count = (node.access_count or 0) + 1
    node.last_accessed_at = datetime.utcnow()
    
    # ... existing paging logic ...
```

---

## B.4 Files Changed

| File | Action | Changes |
|---|---|---|
| `backend/src/ai/constants.py` | MODIFY | Fix `EMBEDDING_MODEL` |
| `backend/src/ai/cortex_models.py` | MODIFY | Import new enums (already added in Phase A) |
| `backend/src/ai/cortex_ingestion.py` | MODIFY | Enhanced ingestion pipeline with DOCUMENT/SECTION/CHUNK decomposition |
| `backend/src/ai/cortex_service.py` | MODIFY | Add reference resolution in `read()`, `_get_node_cross_tree()` |
| `backend/src/ai/cortex_bridge.py` | MODIFY | Add `write_knowledge_reference()` |
| `backend/src/ai/knowledge_tree_service.py` | NEW | Knowledge Tree lifecycle management |
| `backend/src/ai/embedding_service.py` | NEW | Centralized embedding generation |
| `backend/src/ai/migrations/migrate_kb_to_trees.py` | NEW | Data migration script |
| `backend/src/ai/worker.py` | MODIFY | Fix process_document, dual-write to trees |
| `backend/src/ai/memory_service.py` | MODIFY | Update semantic search to query cortex_nodes embeddings |

---

## B.5 Backward Compatibility Strategy

| Feature | During Phase B | After Phase B |
|---|---|---|
| Document upload | Dual-write to both `document_chunks` AND Knowledge Trees | Both active |
| Semantic search | Query `cortex_nodes.embedding` first, fall back to `document_chunks.embedding` | Both active |
| Runtime knowledge ingestion | Keep existing behavior + add reference nodes | Both active |
| `documents` table | Retained, still updated | Read-only (Phase F) |
| `document_chunks` table | Retained, still updated | Read-only (Phase F) |

---

## B.6 Validation Criteria

- [ ] Embedding model fixed — new documents get valid embeddings
- [ ] `upload_status = "failed"` when all embeddings fail
- [ ] Existing documents migrated to Knowledge Trees (Tenant-level)
- [ ] Document → Section → Chunk hierarchy visible in tree
- [ ] LLM summaries generated at DOCUMENT and SECTION levels
- [ ] Embeddings present on all CHUNK nodes
- [ ] Semantic search returns results from `cortex_nodes` embeddings
- [ ] Reference nodes in runtime trees correctly resolve on READ
- [ ] Access tracking (`access_count`, `last_accessed_at`) works
- [ ] Existing `document_chunks`-based flow still works (backward compat)
