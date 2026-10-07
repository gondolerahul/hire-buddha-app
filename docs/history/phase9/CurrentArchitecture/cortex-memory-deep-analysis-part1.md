# CORTEX Memory System — Deep Analysis & Answers

**Date**: 2026-05-15  
**Phase**: 9 — Architecture Q&A  
**Methodology**: Code analysis + live log inspection + architectural review

---

## 1. Episodic Memory

### 1.1 Significance of Tabular Episodic Memory — Billing Relationship

**Answer**: The `episodic_memories` table is **NOT used for billing calculations**. Billing uses a completely separate system:

| Purpose | Table | Service |
|---------|-------|---------|
| **Billing/Cost** | `usage_logs` + `integration_registry` | `UsageService.log_usage()` |
| **Episodic Memory** | `episodic_memories` | `MemoryRouter.write_episodic()` |
| **Run Tracking** | `execution_runs` | `ExecutionEngine` |

**Evidence from code**:

- **`usage_service.py:30-113`**: The `UsageService.log_usage()` method writes to a `UsageLog` table, joining with `IntegrationRegistry` to look up per-SKU pricing (e.g., `gemini-3.1-pro-in` at $X per 1M tokens). This is the **sole source of truth** for billing.

- **`episodic_memories` schema**: Contains `total_cost_usd`, `total_tokens`, `execution_time_ms` — but these are **summary copies** for agent self-awareness, NOT for billing computation. They are denormalized snapshots written at run completion by `MemoryRouter.write_episodic(run)`.

**The real purpose of episodic memory** is giving agents awareness of their own past:
- "Last time you analyzed Q2 revenue, it cost $0.45 and took 12 seconds"
- "Your previous 5 runs for this user were all COMPLETED successfully"

This is injected into the LLM prompt as `__memory__` context, helping agents avoid repeating work and maintaining continuity across sessions.

---

### 1.2 Why Not Store Episodic Memory in CORTEX Trees?

**Answer**: This was a **deliberate architectural choice**, not legacy debt. Here's why:

**Reason 1: Different Lifecycles**

| Aspect | Episodic Memory | CORTEX Tree |
|--------|----------------|-------------|
| **Scope** | Cross-run, cross-tree | Single execution run |
| **Lifetime** | Permanent (survives tree archival) | Tied to tree lifecycle |
| **Owner** | Entity + User pair | Specific execution |
| **Query pattern** | "Last 5 runs for entity X" | "Navigate node Y in tree Z" |

If episodic memories lived inside CORTEX trees, you'd need to query across ALL trees to find "what did this agent do last time?" — an expensive cross-tree traversal vs. a simple `WHERE entity_id = X ORDER BY created_at DESC LIMIT 5`.

**Reason 2: Temporal Ordering**

Episodic memories need **chronological ordering across trees**. A CORTEX tree is a spatial hierarchy (parent → child), not a timeline. Flattening temporal data into a tree structure would lose the natural recency ordering.

**Reason 3: Tree Independence**

A new execution creates a fresh tree. If episodic memories were stored in a tree, you'd need to load a previous tree just to read past history — creating coupling between what should be independent execution contexts.

**Can We Change This?**

Yes, but I wouldn't recommend it for the reasons above. However, there IS a useful middle ground:

> **Proposal**: The `episodic_memories.tree_id` FK (already exists!) enables **hybrid access**: when an agent needs to "dive deeper" into a past run's findings, it can use the `tree_id` to navigate that run's CORTEX tree. The episodic table serves as a lightweight index, and the tree provides the detail.

---

### 1.3 Suggestions to Improve Episodic Memory Architecture

**Current Weaknesses**:

1. **Fixed limit of 5 runs** — Hardcoded in `MemoryRouter.retrieve()`. No relevance ranking.
2. **No semantic search** — Cannot ask "what did I learn about APAC revenue last month?"
3. **Summaries are truncated** — `input_summary` and `output_summary` capped at 1000 chars, losing nuance.
4. **No cross-entity memories** — Agent A doesn't know what Agent B learned in the same process.

**Improvement Proposals**:

| # | Improvement | Impact | Effort |
|---|------------|--------|--------|
| 1 | **Add embedding column** to `episodic_memories` (pgvector). Embed `input_summary + output_summary`. Enable semantic retrieval: "find past runs similar to this task" instead of just "last 5 runs". | High — enables relevance-ranked memory recall | Medium |
| 2 | **Structured metadata_info** — Store key learnings, error patterns, and success factors as structured JSON. Currently `metadata_info` is unused. | Medium — enables pattern detection | Low |
| 3 | **Cross-entity episodic linking** — Add `process_run_id` field to link episodic memories from all entities in a PROCESS run. The synthesizer can then see what the research director learned. | High — enables multi-agent continuity | Low |
| 4 | **Adaptive retrieval count** — Instead of always loading 5 memories, use semantic similarity threshold. Load 1-10 based on relevance to current task. | Medium — reduces noise | Medium |
| 5 | **Memory consolidation** — Periodically merge similar episodic memories into condensed summaries (like human memory consolidation during sleep). | Medium — long-term scalability | High |

---

## 2. Knowledge Base Memory

### 2.1 Why Not Store Knowledge Base in CORTEX Trees?

**Answer**: This is a **dual-architecture design** — both approaches exist simultaneously, and for good reason:

**What currently happens**:

1. **Standalone KB** (`documents` + `document_chunks` tables): Uploaded documents are chunked, embedded (pgvector), and stored independently. This supports the **Knowledge Base UI page** and semantic search across all company documents.

2. **CORTEX KB subtree** (`cortex_nodes` where `node_type='knowledge'`): At execution time, context sources attached to an agent are **auto-ingested** into the CORTEX tree's Knowledge Base subtree (`worker.py:849-870`). Additionally, scraper/browser tool results are ingested during execution (`cortex_bridge.py:125-210`).

**Why both exist — deliberate separation**:

| Aspect | Standalone KB (`documents`) | CORTEX KB Subtree |
|--------|---------------------------|-------------------|
| **Purpose** | Company-wide knowledge repository | Execution-specific working knowledge |
| **Persistence** | Permanent, survives any execution | Tied to tree lifecycle |
| **Search** | Vector similarity (semantic) | Tree navigation (structural) |
| **Content** | Original documents, chunked | Summaries + full text, hierarchical |
| **Access** | Any agent, any time | Only during active execution |

**Can we merge them?** Technically yes, but it would conflate two different concerns:
- **Static knowledge** (company docs, product manuals) — rarely changes, needs vector search
- **Dynamic knowledge** (scraped pages, research findings) — execution-specific, needs tree navigation

---

### 2.2 Gains vs. Losses of Storing KB in CORTEX Trees

**Potential Gains**:

| Gain | Detail |
|------|--------|
| **Unified navigation** | Agents could navigate ALL knowledge (static + dynamic) through one tree interface |
| **Structural context** | Documents organized hierarchically by topic, not just flat chunks |
| **Cross-reference** | Findings can directly point to the KB node they came from |
| **Version awareness** | Tree immutability creates a natural version history |

**Potential Losses**:

| Loss | Detail | Severity |
|------|--------|----------|
| **Vector search capability** | CORTEX nodes don't have embeddings. You'd lose semantic "find similar" queries | **Critical** |
| **Scale** | 1000 docs × 20 chunks = 20,000 nodes per tree. Tree navigation becomes impractical | **Critical** |
| **Cross-agent access** | Each tree is execution-scoped. Other agents can't query a different tree's KB without explicit linking | **High** |
| **Query performance** | Tree traversal is O(depth × fanout) vs. vector search O(log n) | **High** |
| **Storage bloat** | Each execution would duplicate the entire KB into its tree | **High** |

**Verdict**: The losses outweigh the gains for static knowledge. The current hybrid approach is correct: keep static KB in `documents`/`document_chunks` with vector search, and dynamically ingest relevant subsets into CORTEX trees at execution time.

---

### 2.3 Enterprise-Scale KB Ingestion into CORTEX Trees — Feasibility Analysis

**Scenario**: An enterprise with thousands of documents across SharePoint, network drives, cloud storage, and custom KBs.

**Short answer**: **Not advisable to ingest all into CORTEX trees.** Here's why:

**Scale Analysis**:

| Metric | Value | CORTEX Impact |
|--------|-------|---------------|
| Documents | 10,000 | ~200,000 nodes (20 chunks per doc) |
| Total text | ~5 GB | 5B chars ÷ 4 ≈ 1.25B tokens of content |
| Tree depth | 3-4 levels | Manageable |
| Viewport size | 12 children max | Would need ~16,000 group nodes for re-clustering |
| Navigation steps | To find 1 doc: ~20 navigations | 20 × LLM call = $0.10+ per lookup |

**Problems**:

1. **Tree becomes unusably wide**: 200,000 nodes under a knowledge root → constant re-clustering, viewport pagination through thousands of groups.

2. **No semantic search**: Finding "what does our HR policy say about remote work?" requires the agent to navigate through hundreds of groups instead of a single vector query returning the exact paragraph.

3. **Duplication**: Every execution would need its own copy (trees are execution-scoped), or you'd need a shared "global KB tree" — which breaks the isolation model.

4. **Cost**: Summarizing 200,000 nodes at ingestion (LLM summary per node) = ~$200-500 in LLM costs alone.

**What SHOULD happen instead** (see 2.4 for the pointer architecture):

```
Enterprise KB (source of truth)
    │
    ├── Documents → document_chunks + pgvector embeddings
    │   (searchable, permanent, shared across all agents)
    │
    └── At execution time:
        ├── Semantic search retrieves top-K relevant chunks
        └── Only those K chunks are ingested as CORTEX knowledge nodes
            with source_ref pointers back to original documents
```

---

### 2.4 Can CORTEX Nodes Point to Original Sources?

**Answer**: **Yes, this capability already exists** via the `source_ref` JSONB column on `cortex_nodes`:

```python
# cortex_bridge.py:189-202 — current implementation
await cortex.write(
    parent_id=knowledge_root.id,
    node_type="knowledge",
    title=f"📄 {title}",
    content=content[:50000],
    summary=summary,
    source_ref={"url": url, "tool": tool_id},  # ← POINTER TO SOURCE
    metadata_extra={
        "run_id": str(run.id),
        "char_count": len(content),
        "artifact_id": item.get("artifact_id"),
    },
)
```

**Extending this for enterprise KB**:

The `source_ref` JSONB can store granular provenance:

```json
{
    "source_type": "sharepoint",
    "document_id": "uuid-of-document-in-documents-table",
    "chunk_id": "uuid-of-document-chunk",
    "file_path": "//corp-share/HR/policies/remote-work-v2.docx",
    "page_number": 14,
    "section": "3.2.1 Eligibility Criteria",
    "paragraph_offset": 3,
    "sharepoint_url": "https://corp.sharepoint.com/sites/HR/...",
    "last_modified": "2026-03-15T10:00:00Z"
}
```

This architecture allows CORTEX nodes to serve as **lightweight index entries** pointing to original enterprise sources, rather than duplicating the full content. The agent would:
1. Navigate the CORTEX knowledge tree (summaries only)
2. READ a specific node to get the content + `source_ref`
3. Use `source_ref` to cite or fetch the original document

---

### 2.5 Is PGVector Knowledge Base Search Actually Working?

**Answer**: **No. It is currently broken.** 

**Evidence from live logs**:

```
# arq_worker.log — Document upload at 08:45:51
08:45:51:   0.24s → process_document('6ba6bab9-...', b'%PDF-1.7...')
Embedding error for chunk 0: 404 Not Found. {'message': '', 'status': 'Not Found'}
Embedding error for chunk 1: 404 Not Found. {'message': '', 'status': 'Not Found'}
...
Embedding error for chunk 20: 404 Not Found. {'message': '', 'status': 'Not Found'}
08:45:53:   1.86s ← process_document ●
```

**ALL 21 chunks failed to embed** with `404 Not Found`. This means:
- The document was parsed successfully (PDF extracted into text, split into 21 chunks of 500 chars each)
- But the embedding API call to `gemini-embedding-004` failed with a 404
- **No embeddings were stored** — the `document_chunks` table has rows with NULL embeddings

**Search also fails**:
```
# backend_api.log — User searched on KB page
POST /api/v1/ai/documents/search?query=what+is+the+training+all+about%3F&top_k=5 → 500 Internal Server Error
POST /api/v1/ai/documents/search?query=training&top_k=5 → 500 Internal Server Error
```

The search endpoint (`service.py:619-678`) tries to embed the query using the same failing model, resulting in a 500 error.

**Root Cause Analysis**:

The embedding model `gemini-embedding-004` is being called via Vertex AI with `api_version: v1beta`. The 404 error indicates one of:

1. **Model deprecation**: `gemini-embedding-004` may have been deprecated/renamed in the Vertex AI API. Google frequently updates model names (e.g., `text-embedding-004` → `gemini-embedding-004`).

2. **Region mismatch**: The Vertex AI project may be configured in a region where this model isn't available.

3. **API version**: The `v1beta` API version in `http_options` may not support this model name.

**Impact**: 
- ⚠️ **ALL document uploads since this breakage produce chunks with no embeddings**
- ⚠️ **ALL semantic searches return 500 errors**
- ⚠️ **Tier 3 (Semantic Memory) is completely non-functional**
- The document upload shows "completed" status because `worker.py:1571` sets `upload_status = "completed"` even when ALL embeddings fail (the embedding errors are caught and `continue`d past)

**Recommended Fix**:
1. Update `EMBEDDING_MODEL` in `constants.py` to the current model name (verify via `gcloud ai models list`)
2. Fix `process_document()` to set `upload_status = "failed"` if ALL chunks fail embedding
3. Re-process all existing documents with valid embeddings
