# Autonomous Agent Hardening — Part 1: Memory Architecture

**Date**: 2026-05-19  
**Companion**: [Part 2: Tool Resilience & Autonomous Loop](./autonomous-agent-hardening-part2.md)  
**Prior Analysis**: [Episodic Memory Contamination Analysis](./episodic-memory-contamination-analysis.md)

---

## 1. Episodic Memory: Purpose, Value & Alternatives

### 1.1 What Episodic Memory Currently Does

The episodic memory system records a summary of every top-level execution run and injects the last N episodes into the entity's prompt at runtime. Currently:

- **Write path**: `MemoryRouter.write_episodic()` dual-writes to both `episodic_memories` (v1 flat table, capped at 10) and `EpisodicTreeService` (v2 CORTEX tree, unlimited).
- **Read path**: `MemoryRouter._load_episodic()` pulls the last 10 episodes and `format_for_prompt()` renders them as:
  ```
  ## Recent Execution History
    [2026-05-18T14:01:42] 'Relevance AI research' → 'Report generated...'
    [2026-05-18T17:07:38] 'Computer Model for brain' → 'Report sections...'
  ```
- **Injection point**: `worker.py:729` injects this block as `__memory__` into `context_state`, which becomes part of the system prompt.

### 1.2 Question 1: Can We Get Rid of Episodic Memory Altogether?

**Yes, we can safely remove episodic memory injection from the runtime prompt.** Here is the analysis:

#### What We Lose

| Capability | Current Value | Actual Impact of Removal |
|---|---|---|
| **Conversation continuity** | Entity sees past interactions | Only relevant for chat-style entities (not Deep Research) |
| **Pattern awareness** | Entity knows "I did X before" | Marginal — the entity doesn't actually learn from seeing raw I/O summaries |
| **Deduplication** | Entity could avoid repeating work | Not implemented — no logic checks past episodes before acting |
| **Context about costs** | Shows past cost/token usage | Never referenced in any entity prompt or logic |

#### What We Gain

| Benefit | Impact |
|---|---|
| **Eliminate cross-run contamination** | HIGH — The primary source of goal diversion is removed |
| **Reduce prompt token usage** | ~500-1000 tokens freed per execution |
| **Simpler architecture** | Fewer moving parts, fewer failure modes |
| **Faster startup** | No DB query + format overhead per run |

#### Recommendation: **REMOVE episodic injection from runtime prompts. KEEP episodic writes for analytics/auditing.**

The episodic write path is valuable for:
- Admin dashboards (execution history views)
- Future dreaming/learning algorithms (Phase D)
- Cost tracking and billing audits

But injecting raw I/O summaries into the LLM prompt provides **near-zero value** for task-oriented entities like Deep Research, and actively causes contamination. The I/O summaries are too short to convey useful patterns, and the entity has no mechanism to act on them.

---

### 1.3 Question 2: Semantic Episodic Memory (Goal-Aligned Only)

If we decide to keep episodic injection, we can make it semantic — only injecting episodes aligned with the current goal.

#### How It Would Work

```
Current: Load last 10 episodes by time → inject all
Proposed: Load episodes by semantic similarity to current task → inject top 3
```

**Implementation**: The `EpisodicTreeService.query_by_topic()` method already exists and uses pgvector cosine similarity. The change would be:

```python
# memory_service.py:_load_episodic() — proposed change
async def _load_episodic(self, entity_id, user_id, task_description=None):
    if task_description:
        # Semantic retrieval: only episodes relevant to current task
        episodes = await episodic_service.query_by_topic(
            entity_id=entity_id, query=task_description, top_k=3
        )
    else:
        # Fallback: time-based with smaller window
        episodes = await episodic_service.query_by_time(
            entity_id=entity_id, start_date=now-7days, end_date=now, limit=3
        )
```

#### Effects

| Aspect | Effect |
|---|---|
| **Cross-topic contamination** | Eliminated — "Relevance AI" episodes won't match "Computer Model for brain" |
| **Relevant history** | Preserved — if user runs the same topic again, past episodes surface |
| **Embedding dependency** | REQUIRED — needs a working embedding model configured via AI Config page |
| **Token budget** | Reduced — 3 episodes instead of 10, ~300 tokens instead of ~1000 |

#### Prerequisite: Embedding Task Type in AI Config

The current AI Model Config page (`AIModelConfigPage.tsx`) has these task types:
```
text_generation, thinking, speech_to_speech, text_to_image, 
image_to_image, text_to_speech, text_to_music, text_to_video, 
image_to_video, audio_to_video, text_to_3d
```

**Missing: `embedding` task type.** The `EmbeddingService._resolve_embedding_model()` currently uses a separate lookup (`service_category == 'EMBEDDING'` in IntegrationRegistry), bypassing the task-type routing system. This should be unified.

**Required changes:**
1. Add `{ id: 'embedding', name: 'Embedding', icon: Search, category: 'llm', description: 'Vector embedding generation for semantic search and memory.' }` to `TASK_TYPES` in `AIModelConfigPage.tsx`
2. Update `EmbeddingService._resolve_embedding_model()` to also check `ModelTaskDefault` for task_type `embedding`
3. Admin configures embedding model via the AI Config page like any other task

---

### 1.4 Question 3: Learnings-Only Memory (Instructions, Not Data)

This is the **most architecturally sound approach**. Instead of injecting raw episode data, we inject:

1. **Distilled instructions** ("learnings") derived from past episodes
2. **Execution failure patterns** so the entity can avoid known pitfalls

#### Proposed Architecture: "Intelligence-First Memory"

```
┌──────────────────────────────────────────────────────┐
│                    RUNTIME PROMPT                     │
│                                                       │
│  ┌─────────────────────────────────────────────────┐ │
│  │ ## Learned Instructions (from Intelligence Tree) │ │
│  │ 📏 [95%] Always use batch_web_search, not       │ │
│  │    web_search, for multi-query research          │ │
│  │ 📏 [90%] .gov sites require headless_browser    │ │
│  │    instead of scraper_tool                       │ │
│  │ 🎯 [85%] Verify all URLs are accessible before  │ │
│  │    passing to source analyzer                    │ │
│  └─────────────────────────────────────────────────┘ │
│                                                       │
│  ┌─────────────────────────────────────────────────┐ │
│  │ ## Known Failure Patterns (from Execution Logs)  │ │
│  │ ⚠️ batch_web_search sometimes returns empty     │ │
│  │   results — retry with simplified queries        │ │
│  │ ⚠️ scraper_tool fails on JavaScript-heavy       │ │
│  │   sites — fall back to headless_browser          │ │
│  └─────────────────────────────────────────────────┘ │
│                                                       │
│  ❌ NO raw episodic data (no I/O summaries)          │
│  ❌ NO knowledge/content from past runs              │
└──────────────────────────────────────────────────────┘
```

#### How Execution Failure Logs Would Work

Instead of injecting full episode data, we extract **structural metadata** about past failures:

```python
# Proposed: failure_pattern_service.py
async def get_failure_patterns(entity_id: UUID, limit: int = 5) -> List[Dict]:
    """Extract actionable failure patterns from recent execution history."""
    # Query episodic tree for FAILED or PARTIAL_COMPLETE episodes
    failed_episodes = await episodic_service.query_by_time(
        entity_id=entity_id,
        start_date=now - timedelta(days=30),
        end_date=now,
        limit=20,
    )
    
    patterns = []
    for ep in failed_episodes:
        metadata = ep.get("metadata", {})
        if metadata.get("status") in ("FAILED", "PARTIAL_COMPLETE"):
            patterns.append({
                "tool": metadata.get("tools_used", []),
                "error_type": _classify_error(ep),  # "TOOL_EMPTY", "TIMEOUT", "FORMAT_ERROR"
                "frequency": _count_similar_failures(entity_id, ep),
                "suggestion": _generate_suggestion(ep),  # LLM-generated or rule-based
            })
    return patterns[:limit]
```

**Formatted for prompt:**
```
## Known Failure Patterns
⚠️ batch_web_search returned empty results in 2 of last 5 runs.
   Mitigation: Simplify queries or use individual web_search calls as fallback.
⚠️ scraper_tool failed with timeout on 3 URLs in last run.
   Mitigation: Use headless_browser for sites that block automated scraping.
```

#### Effects

| Aspect | Effect |
|---|---|
| **Goal contamination** | ELIMINATED — no past topic data injected |
| **Actionable guidance** | HIGH — entity learns from failures |
| **Token efficiency** | EXCELLENT — ~200 tokens for 3-5 patterns vs ~1000 for raw episodes |
| **Implementation complexity** | MEDIUM — requires the Dreaming Process (Phase D) OR a simpler rule-based extractor |
| **Cold start** | No patterns on first run — graceful degradation |

---

### 1.5 Question 4: Other Architectural Approaches

#### Approach A: "Memory Domains as Separate Prompt Sections"

Instead of a single `__memory__` blob, separate memory into distinct prompt sections with clear priority ordering:

```
1. [HIGHEST] Intelligence Rules — distilled instructions (always injected)
2. [HIGH]    Failure Patterns — actionable warnings (always injected)  
3. [MEDIUM]  Knowledge References — relevant KB snippets (semantic search)
4. [LOW]     Experience Suggestions — observed patterns (semantic search)
5. [NEVER]   Raw Episodic Data — removed from runtime injection entirely
```

This is essentially what `MemoryAssemblyService` was designed to do (see lines 264-322), but it's not yet wired into the main execution path. The current worker.py still uses the older `MemoryRouter.retrieve()`.

#### Approach B: "Run-Scoped Memory Domains"

Add a `memory_scope` field to entity configuration:

```python
class MemoryConfig(BaseModel):
    memory_scope: str = "FULL"  # FULL | RUN_SCOPED | INTELLIGENCE_ONLY | NONE
```

| Scope | Episodic | Intelligence | Knowledge | Experience |
|---|---|---|---|---|
| `FULL` | ✅ Last 10 episodes | ✅ | ✅ | ✅ |
| `RUN_SCOPED` | ✅ Current run only | ✅ | ✅ | ✅ |
| `INTELLIGENCE_ONLY` | ❌ | ✅ | ✅ | ❌ |
| `NONE` | ❌ | ❌ | ❌ | ❌ |

For Deep Research entities, we'd set `memory_scope = "INTELLIGENCE_ONLY"`.

#### Approach C: "Episodic Memory as a Tool, Not Context"

Instead of injecting episodes into the prompt, expose a `RECALL` tool that the entity can optionally invoke:

```python
# New tool: recall_tool.py
class RecallTool(Tool):
    """Search past execution history for relevant context."""
    name = "recall_past_runs"
    description = "Search your past execution history for relevant patterns or results."
    
    async def run(self, query: str) -> str:
        episodes = await episodic_service.query_by_topic(entity_id, query, top_k=3)
        return format_episodes(episodes)
```

This gives the entity **agency over its own memory access** — it only recalls when it decides it needs historical context, rather than being force-fed all past episodes. This aligns with the CORTEX v2 spec's proposed `RECALL` operation (§14.1).

#### Recommended Approach

**Combine B + C**: Set Deep Research entities to `INTELLIGENCE_ONLY` scope and add `RECALL` as an optional tool. This:
- Eliminates contamination by default
- Preserves the ability to recall when genuinely needed
- Keeps intelligence/learnings always available
- Requires minimal code changes (mostly configuration)

---

## 2. Summary of Episodic Memory Recommendations

| # | Recommendation | Priority | Effort |
|---|---|---|---|
| 1 | **Remove episodic injection from Deep Research entities** — set `memory_scope: INTELLIGENCE_ONLY` | HIGH | 30 min |
| 2 | **Keep episodic write path** — valuable for analytics, dreaming, auditing | — | No change |
| 3 | **Add `embedding` task type** to AI Model Config page | MEDIUM | 1 hr |
| 4 | **Implement failure pattern extraction** — inject tool/step failure history as warnings | HIGH | 2-3 hrs |
| 5 | **Wire `MemoryAssemblyService`** into the main execution path (replace `MemoryRouter.retrieve()`) | MEDIUM | 2 hrs |
| 6 | **Add `RECALL` tool** for on-demand episodic access | LOW | 1 hr |

---

*Continue to [Part 2: Tool Resilience & Autonomous Loop](./autonomous-agent-hardening-part2.md)*
