# CORTEX Memory System — Deep Analysis Part 2

## 3. CORTEX Memory

### 3.1 Do Knowledgebase Documents Become Part of CORTEX Memory?

**Answer**: **Partially correct, with important nuances.**

Documents attached to an agent at creation time are stored as `context_sources` in the entity's `capabilities.context_engineering.context_sources` JSON array. At execution time, here's what happens:

**Step-by-step flow** (from `worker.py:750-870`):

1. **Load context sources** — The worker reads `entity.capabilities.context_engineering.context_sources`
2. **For each source**:
   - If `source_type == "DOCUMENT"` or `"KNOWLEDGE_BASE"`: Load the artifact file from disk, extract text (PDF/DOCX/TXT), and add to `loaded_sources` list
   - If `source_type == "CORTEX_TREE"`: Load the referenced tree's root viewport
3. **Inject into context** — All loaded sources are joined and stored as `context_state["__context_sources__"]`
4. **Auto-ingest into CORTEX tree** — Each loaded source is written as a `knowledge` node under the tree's Knowledge Base root (`worker.py:849-870`):

```python
for _src_text in loaded_sources:
    await cortex.write(
        parent_id=_knowledge_root.id,
        node_type="knowledge",
        title=f"📎 {_title}",
        content=_safe_content[:50000],  # ← TRUNCATED TO 50K CHARS
        summary=_safe_summary[:300],
        status="complete",
        source_ref={"type": "context_source"},
    )
```

**What this means**:
- ✅ Documents **do** become part of the CORTEX tree at execution time
- ⚠️ Content is **truncated to 50,000 characters** per source — large documents lose data
- ⚠️ Summaries are **auto-generated from first 300 characters** — no LLM summary for context sources (unlike scraped web pages which get LLM summaries)
- ⚠️ The original document is **dumped as flat text** into one node — no structural decomposition into sections/chapters
- ❌ The vector embeddings in `document_chunks` are **not used** during CORTEX execution — the agent reads the raw text, not semantic search results

---

### 3.2 Boundaries and Limitations of the CORTEX Memory System

#### A. Number of Nodes

| Limit | Value | Source | Enforced? |
|-------|-------|--------|-----------|
| Per tree | **No hard limit** | No code cap exists | ❌ No |
| Tracked in | `tree.total_nodes` counter | `cortex_service.py:278` | Counter only |

**Reality**: Trees grow unboundedly. The `total_nodes` counter is incremented on writes but never checked against a ceiling. A long-running research agent could generate 500+ nodes.

**Practical limit**: PostgreSQL handles millions of rows, so storage isn't the bottleneck. The bottleneck is **navigation efficiency** — an agent navigating a 500-node tree needs many NAVIGATE steps to find relevant information.

#### B. Depth of the Tree

| Limit | Value | Source | Enforced? |
|-------|-------|--------|-----------|
| Maximum depth | **No hard limit** | No code cap | ❌ No |
| Typical depth | 3-5 levels | Structural: root → subtree anchor → findings/knowledge → children |
| CTE concern | >20 levels may slow CTE queries | PostgreSQL recursive CTE | ⚠️ Performance |

**Practical observation**: The initial scaffold creates depth=0 (root), depth=1 (knowledge/working/output), and writes go to depth=2+. Re-clustering can add intermediate levels. In practice, trees rarely exceed depth 5.

#### C. Width of the Tree (Fanout)

| Limit | Value | Source | Enforced? |
|-------|-------|--------|-----------|
| MAX_CHILDREN | **12** per node (default) | `cortex_service.py:167` | ⚠️ Soft |
| Enforcement | Re-clustering trigger, NOT block | `_schedule_reclustering()` | Soft limit |
| Configurable per tree | Yes | `tree.max_children` column | At creation |

**What happens at 12+**: When a parent exceeds `max_children`, `_schedule_reclustering()` moves the oldest half into a group node. **The write is NOT rejected** — re-clustering happens inline. So the effective width is always ≤ `max_children + 1` (before re-clustering fires).

#### D. Size of Individual Node Content

| Limit | Value | Source | Enforced? |
|-------|-------|--------|-----------|
| Content max | **50,000 characters** | Various truncation points | ⚠️ Inconsistent |
| Context source ingestion | `content[:50000]` | `worker.py:856` | Truncated |
| Tool result ingestion | `content[:50000]` | `cortex_bridge.py:193` | Truncated |
| Step result writing | `step_output[:50000]` | `cortex_bridge.py:96-98` | Truncated |
| Knowledge ingestion | `content[:50000]` | `cortex_bridge.py:193` | Truncated |
| Summary max | **500 characters** | `summary[:500]` | Truncated |

#### E. Tokens Per Node

| Metric | Calculation | Source |
|--------|------------|--------|
| Token estimation | `len(content) // 4` | `cortex_service.py:170` |
| Max tokens per node | 50,000 / 4 = **12,500 tokens** | Derived from content cap |
| Max per READ page | `page_size_tokens = 8,000` | `cortex_service.py:168` |
| Characters per page | 8,000 × 4 = **32,000 chars** | Derived |

#### F. Information Loss and Retention

**This is the most critical question.** Here's the full information loss chain:

| Stage | Input | Retained | Lost | % Retained |
|-------|-------|----------|------|------------|
| **Document ingestion** | Full document (any size) | First 50K chars | Everything after 50K | Variable — ~100% for small docs, <10% for large docs |
| **Summary generation** | 50K chars content | 300-char auto-summary (no LLM) | Nuance, structure, detail | ~0.6% |
| **Viewport display** | Node summary | Summary only (no content) | Full content | ~0.6% of original |
| **Checkpoint** | Full context_state | Key facts, progress summary | Intermediate step outputs, context | ~5-10% |
| **Step output writing** | Full LLM response | First 50K chars, 500-char summary | Truncated content | ~100% for typical outputs |

**Total information flow**: When an agent navigates its tree via viewport:
- It sees **summaries only** (~300-500 chars each) for the current node and up to 12 children
- To access full content, it must explicitly READ a node (costing one LLM turn)
- Full content is paged at 32K chars per page

**Key insight**: The viewport model is intentionally lossy — it's designed so the agent sees the *index* (summaries) and explicitly requests the *content* (READ). The question is whether the summaries are good enough for the agent to know WHAT to read. Currently, for auto-ingested context sources, the summary is just the first 300 characters — which is often inadequate.

#### G. Runtime Access Depth/Breadth and Token Usage

**Per navigation step**:
| Component | Tokens | Source |
|-----------|--------|--------|
| Breadcrumb | ~5 tokens × depth | `to_prompt_text()` |
| Current node info | ~40 tokens | Title + summary + metadata |
| Children (max 12) | ~40 tokens × 12 = 480 | Summary per child |
| Operations prompt | ~120 tokens | `CORTEX_OPERATIONS_PROMPT` |
| **Total viewport** | **~640 tokens max** | Per step |

**Per READ operation**:
| Component | Tokens | Source |
|-----------|--------|--------|
| Paged content | up to 8,000 tokens | `page_size_tokens` |

**Per execution (entire run)**:
- Each step injects the viewport (~640 tokens) + any READ content
- The viewport is refreshed after every step
- Auto-checkpoint fires every 3 steps
- **Estimated CORTEX overhead per step**: ~700-1,000 tokens (viewport + keys)
- **A 10-step execution**: ~7,000-10,000 tokens of CORTEX overhead

#### H. Other Limitations

| Limitation | Impact |
|-----------|--------|
| **No semantic search within tree** | Agent must navigate manually; cannot ask "find the node about revenue" |
| **No cross-tree queries** | Agent cannot reference nodes from a previous tree |
| **Write-once content** | Cannot update/correct a node; must create revision child |
| **Single cursor** | Only one active viewport position; cannot compare two subtrees side-by-side |
| **No partial node reads** | READ returns a full page; cannot search within a node's content |
| **Summary quality** | Auto-summaries (first 300 chars) are often inadequate for navigation |
| **No deduplication** | Same content ingested multiple times creates duplicate nodes |

---

### 3.3 What Happens If We Remove All Limitations?

**Removing MAX_CHILDREN (12) limit**:
- Viewports become unbounded → 100+ children summaries injected per step
- Token cost per step: 100 × 40 = 4,000+ tokens just for children
- Agent gets overwhelmed with options, navigation quality degrades
- **Net effect**: Worse performance, higher cost, lower quality decisions

**Removing content size limit (50K chars)**:
- Single node could contain entire 500-page document (~1M chars = 250K tokens)
- READ operation would return pages, but total_pages could be 30+
- Agent would spend many turns paging through one node
- **Net effect**: Impractical for navigation; better to decompose into child nodes

**Removing depth limits**:
- CTE queries for breadcrumb/ancestry could degrade at depth > 50
- Agent loses track of where it is in deeply nested structures
- **Net effect**: Moderate risk; unlikely to hit naturally

**Removing token budget compaction**:
- Context grows indefinitely until model context window is filled
- At 200K tokens, model performance degrades (lost-in-the-middle problem)
- No checkpoints → crash = total loss of progress
- **Net effect**: Catastrophic for long-running tasks

**Summary**: The limitations are **not arbitrary constraints but essential guardrails**. Each one prevents a specific failure mode. Removing them would make the system theoretically unbounded but practically unusable.

---

### 3.4 Log Analysis — Information Storage and Retrieval During Deep Research Execution

**Log evidence from the latest deep research execution** (2026-05-15 09:12-09:27):

#### Step 1: Entity Seeding (09:12:58)

The logs show creation of the deep-research process entities:
- `deep-research-director` (Research Director) — with tools: `web_search`, `scraper_tool`, `headless_browser`
- `deep-research-synthesizer` (Report Synthesizer) — with tool: `pdf_generator`

Both have `"memory": {"enabled": true, "mode": "CORTEX"}` configured.

#### Step 2: Execution Initiation and CORTEX Tree Creation

From the worker logs at 09:27:00:
```
SELECT cortex_trees ... WHERE cortex_trees.id = $1::UUID    ← Resume existing tree
SELECT cortex_nodes ... WHERE tree_id AND parent_id AND sibling_order = 1  ← Get working root
```

This shows the system:
1. Created or resumed a CORTEX tree
2. Located the working memory root (sibling_order=1)

#### Step 3: Knowledge Subtree Injection (09:27:00)

```
INFO src.ai.worker: CORTEX: Injected knowledge subtree (57670c9b-310f-4b2d-aa5c-5d05685d4b63) into context
```

This confirms:
- The knowledge root was found
- Its viewport was injected as `__cortex_knowledge__`
- The synthesizer sees what the director collected

#### Step 4: Plan Generation (09:27:00)

```
INFO src.ai.planner_service: Generating dynamic plan for deep-research-synthesizer with input keys:
  ['topic', '__cortex_viewport__', '__cortex_tree_id__', '__cortex_knowledge__', 
   'Research Phase', 'tool_call_counts', 'Quality Gate', 'cortex_tree_id', 'input']
```

The planner receives ALL CORTEX context:
- `__cortex_viewport__`: Current tree position
- `__cortex_tree_id__`: Tree identifier for operations
- `__cortex_knowledge__`: Knowledge subtree summary

#### Step 5: Execution Failure (09:27:33)

```
ClientError: 404 NOT_FOUND. Publisher Model `projects/hirebuddha-production/locations/us-central1/publishers/google/models/gemini-3.1-pro-preview` is not found
```

**Both child runs FAILED** because the LLM model `gemini-3.1-pro-preview` doesn't exist. This is a model configuration error — the model name is wrong.

**Key observation about retry behavior** — despite the failure:
- The CORTEX tree was created with 4 scaffold nodes
- The knowledge subtree was injected
- But NO step outputs were written (failure happened during plan generation, before any steps executed)

#### Step 6: Scheduling Cron (09:30:00)

```
cron:cortex_resume_scheduled()
SELECT cortex_trees WHERE status = 'suspended' AND next_resume_at <= now()
→ {'resumed': 0}
```

The cron job runs every 5 minutes, checking for trees to wake up. None were scheduled, so 0 resumed.

**Summary of what the logs show about information flow**:

| Phase | Data Stored | Data Retrieved | Status |
|-------|------------|----------------|--------|
| Tree creation | 4 scaffold nodes in PostgreSQL | ✅ | Working |
| Knowledge injection | Viewport of knowledge root | ✅ Retrieved at context build | Working |
| Context key injection | `__cortex_viewport__`, `__cortex_tree_id__` | ✅ Passed to planner | Working |
| Step execution | ❌ Never reached | ❌ | Failed (model 404) |
| Step → CORTEX writes | ❌ Never reached | ❌ | Failed |
| Episodic memory | ❌ Never written (run failed) | ❌ | Failed |
| Embedding/semantic | ❌ Embedding API returns 404 | ❌ | **Broken** |

**Conclusion**: The CORTEX tree lifecycle (create → inject → navigate) is working correctly. The failures are in the LLM model configuration and the embedding API, not in the memory system itself.

---

### 3.5 Retry/Resume/Re-execute — Does Retry Ignore Previous CORTEX Trees?

**Answer**: **Your assumption is partially incorrect.** The retry DOES attempt to resume the CORTEX tree.

**Evidence from `service.py:435-501`** (`retry_execution` method):

```python
async def retry_execution(self, execution_id, company_id, user_id):
    # 1. Load the failed run
    failed_run = ...
    
    # 2. Build input_data — PASSES CORTEX TREE ID
    retry_input = dict(failed_run.input_data or {})
    ctx = failed_run.context_state or {}
    if "__cortex_tree_id__" in ctx:
        retry_input["cortex_tree_id"] = ctx["__cortex_tree_id__"]  # ← RESUME, NOT FRESH
    
    # 3. Create retry run with carried-forward context
    retry_run = ExecutionRun(
        entity_id=failed_run.entity_id,
        input_data=retry_input,
        context_state=ctx,  # Carry forward completed step markers
        parent_run_id=failed_run.id,  # Link for traceability
    )
```

**What the retry button actually does**:
1. ✅ Passes `cortex_tree_id` from the failed run's context → tree IS resumed
2. ✅ Carries forward `context_state` with completed step markers → already-completed steps are skipped
3. ✅ Links via `parent_run_id` for traceability
4. ❌ **No mechanism to capture user improvement instructions** — the retry just re-runs with the same `input_data`

**However, your concern about "improvement instructions" IS valid**:

The frontend's retry button (`ExecutionDetail.tsx:518-528`) calls:
```typescript
const { data } = await apiClient.post(`/ai/executions/${run.id}/retry`);
```

There is **no UI for the user to provide feedback/corrections**. The retry is a blind re-run. This is a real gap:

| Feature | Status | Gap |
|---------|--------|-----|
| Resume CORTEX tree on retry | ✅ Implemented | — |
| Skip completed steps | ✅ Implemented | — |
| User feedback capture on retry | ❌ Missing | **Real gap** |
| User-guided re-planning | ❌ Missing | **Real gap** |
| "Continue from here with these changes" | ❌ Missing | **Real gap** |

**What should be built**: A "Retry with Instructions" modal that captures user feedback (corrections, new priorities, additional context) and injects it as a special context key that the planner uses when re-generating the plan.

---

### 3.6 How Does Scheduling Work? How Can a User Configure It?

**Current Implementation**:

**Backend** (`worker.py:1603-1659`):
- An Arq cron job `cortex_resume_scheduled` runs every 5 minutes
- It queries: `SELECT cortex_trees WHERE status = 'suspended' AND next_resume_at <= now()`
- For each matching tree, it creates a new `ExecutionRun` and enqueues it
- After enqueuing, it clears `next_resume_at` to prevent re-triggering

**Database schema** (`cortex_trees`):
```sql
resume_schedule VARCHAR(100)  -- e.g., "daily", "weekly" (not yet used for recurrence)
next_resume_at  TIMESTAMP     -- one-time wake-up timestamp
```

**How it's set**: Currently only programmatically. There are two ways:

1. **API endpoint** (`cortex_router.py`): POST `/cortex/trees/{id}/suspend` can set `next_resume_at`
2. **Agent self-scheduling**: An agent can modify its own tree's `resume_schedule` and `next_resume_at` via tool calls

**User Configuration — NOT YET AVAILABLE**:

| Feature | Backend | Frontend | Gap |
|---------|---------|----------|-----|
| One-time wake-up | ✅ `next_resume_at` column | ❌ No UI | **Major gap** |
| Recurring schedule | ⚠️ `resume_schedule` column exists but cron doesn't read it | ❌ No UI | **Major gap** |
| Schedule picker | ❌ No API endpoint for user scheduling | ❌ No UI | **Major gap** |
| Cancel schedule | ❌ No explicit cancel endpoint | ❌ No UI | **Gap** |

**The `resume_schedule` field is a dead letter**: The cron job (`cortex_resume_scheduled`) only checks `next_resume_at`. It does NOT read `resume_schedule` to compute the next wake-up after triggering. So recurring schedules are not functional — only one-time wake-ups work.

**To make scheduling user-configurable, you need**:
1. A frontend schedule picker (date/time + optional recurrence pattern)
2. An API endpoint to set `next_resume_at` on a suspended tree
3. Update the cron job to compute the next `next_resume_at` from `resume_schedule` after each wake-up

---

### 3.7 Suggestions to Make CORTEX World-Class (TB-Scale Per Tenant)

Here is a tiered roadmap from highest to lowest impact:

---

#### Tier 1: Critical Fixes (Unblock Current System)

| # | Fix | Impact | Effort |
|---|-----|--------|--------|
| 1 | **Fix embedding model (404)** — Update `EMBEDDING_MODEL` to a valid Vertex AI model name | Unblocks ALL semantic search | 1 hour |
| 2 | **Fix document upload status** — Set `upload_status = "failed"` when all embeddings fail | Stops false "completed" signals | 30 min |
| 3 | **Fix LLM model config** — `gemini-3.1-pro-preview` doesn't exist; update to valid model | Unblocks ALL execution | 30 min |

---

#### Tier 2: Architecture Improvements (Production Quality)

| # | Improvement | Detail | Effort |
|---|------------|--------|--------|
| 4 | **Add embeddings to CORTEX nodes** | New `embedding` vector column on `cortex_nodes`. Embed node summary at write time. Enable `SELECT ... ORDER BY embedding <=> query_embedding` across the tree. Agent gains semantic search within its own tree. | 2 days |
| 5 | **LLM-quality summaries for all ingestion** | Replace 300-char truncation with LLM summary for context source ingestion (like scraper ingestion already does). Better viewport navigation quality. | 1 day |
| 6 | **Structural document decomposition** | Instead of dumping full doc as one node, use heading detection to create child nodes per section. A 50-page doc becomes 15-20 navigable knowledge nodes. | 3 days |
| 7 | **User feedback on retry** | Add "Retry with Instructions" modal. New `improvement_instructions` field in retry `input_data`. Planner incorporates user feedback into re-planning. | 2 days |
| 8 | **Scheduling UI** | Date/time picker for `next_resume_at`. Recurrence support. Calendar view of scheduled wake-ups. | 3 days |

---

#### Tier 3: Scale Architecture (TB-Scale Per Tenant)

For truly enterprise-scale (TB of data per tenant), CORTEX needs architectural evolution:

| # | Enhancement | Detail |
|---|------------|--------|
| 9 | **Hybrid Storage — CORTEX as Index, Object Store as Content** | Store node summaries + metadata in PostgreSQL (fast navigation). Store full content in S3/GCS (cheap, unlimited). READ operation fetches from object store on demand. Reduces PostgreSQL storage by 95%. |
| 10 | **Tiered Embedding Store** | Hot tier: pgvector for recent/active trees (last 30 days). Warm tier: Pinecone/Weaviate for historical trees. Cold tier: Archived embeddings in Parquet on S3. Query routing based on tree age. |
| 11 | **Global Knowledge Graph** | Separate from per-execution trees. A persistent, company-wide graph of entities, concepts, and relationships extracted from all documents. CORTEX trees link to graph nodes via `source_ref`. Enables "what do we know about X across all research?" |
| 12 | **Streaming Ingestion Pipeline** | Replace synchronous `process_document()` with an event-driven pipeline: Upload → Chunk → Embed → Index → Notify. Supports concurrent ingestion of 1000s of documents. Use message queue (Redis Streams or Kafka). |
| 13 | **Multi-Resolution Summarization** | Each document gets summaries at multiple resolutions: 1-line, 1-paragraph, 1-page, full. Viewport shows 1-line summaries for children. READ(page=0) shows 1-paragraph. READ(page=1+) shows full content. Dramatically improves navigation with minimal token cost. |
| 14 | **Cross-Tree Knowledge Inheritance** | When creating a new tree, optionally "inherit" knowledge nodes from a previous tree by the same entity. Agent starts with accumulated knowledge rather than from scratch. Implement via lazy copy-on-write references. |
| 15 | **Federated KB Connectors** | Plugin architecture for enterprise sources: SharePoint connector, Google Drive connector, Confluence connector, etc. Each connector implements: list() → fetch() → chunk() → embed(). Source changes detected via webhooks → incremental re-index. |
| 16 | **Materialized Views for Common Queries** | Pre-compute "knowledge summary for entity X" as a materialized view. Refresh on tree writes. Eliminates repeated knowledge root navigation at execution start. |

---

#### Tier 4: Aspirational (Next-Gen Memory Architecture)

| # | Vision | Detail |
|---|--------|--------|
| 17 | **Adaptive Memory Consolidation** | Like human sleep: periodically merge related findings across trees into consolidated knowledge. "You've researched APAC revenue 5 times; here's the consolidated understanding." |
| 18 | **Collaborative Trees** | Multiple agents simultaneously navigating and writing to the same tree. Requires optimistic concurrency control on node writes. Enables true parallel research. |
| 19 | **Memory Importance Scoring** | Not all nodes are equally valuable. Score nodes by: recency, access frequency, citation count, and relevance to current task. Prioritize important nodes in viewport. Auto-archive low-importance nodes. |
| 20 | **Natural Language Tree Queries** | Replace manual NAVIGATE/READ with: "Find all findings about competitor pricing in the last 3 research sessions." Translates to CTE + semantic search + temporal filter. |

---

**Priority Order for Implementation**:

```
IMMEDIATE (this week):
  #1 Fix embedding model → Unblocks semantic search
  #2 Fix upload status reporting
  #3 Fix LLM model config

SHORT TERM (next 2 weeks):
  #4 Embeddings on CORTEX nodes
  #5 LLM summaries for all ingestion
  #7 User feedback on retry

MEDIUM TERM (next month):
  #6 Structural document decomposition
  #8 Scheduling UI
  #9 Hybrid storage (S3 for content)

LONG TERM (next quarter):
  #10-16 Scale architecture
```

This roadmap progressively transforms CORTEX from a "working prototype with broken search" to a world-class cognitive memory system capable of handling enterprise-scale knowledge.
