# Episodic Memory Contamination — Forensic Analysis & Remediation Plan

**Date**: 2026-05-19  
**Investigator**: Antigravity AI  
**Status**: COMPLETE  

---

## 1. Executive Summary

A Deep Research execution on the topic **"Computer Model for human brain"** produced a report containing content about **"AI in Asset Management"** — a topic from a prior unrelated research session. This document presents a forensic root-cause analysis of the contamination, identifies **5 additional architectural vulnerabilities** that could produce similar failures, and proposes **3 tiers of remediation** with risk/impact analysis for each.

### Key Finding

The primary contamination was **NOT caused by episodic memory injection** (which was already mitigated by Fix H). Instead, it was caused by a **cascading data pipeline failure** where a TOOL_CALL step silently failed, leaving a `{{step_1}}` variable unresolved in the downstream ACTION step. The LLM then hallucinated output based on its training data and the agent's persona, which happened to include topics from past research domains.

However, the investigation revealed that the **episodic memory architecture does have latent contamination vectors** that will manifest as the system scales. These are documented below.

---

## 2. Forensic Timeline — The "Computer Model" Run

### 2.1 Execution Chain

```
Run: 375b96e9 (deep-research-process) — Topic: "Computer Model for human brain"
├── Run: abaf22af (deep-research-director)
│   ├── Run: 1659c58e (query-decomposer) → ✅ Correct — produced brain modeling queries
│   ├── Run: 83d098ac (source-discoverer) → ❌ CONTAMINATED — produced "AI Agent Research" results
│   │   └── Step 1: TOOL_CALL (batch_web_search) → SILENTLY FAILED (no output)
│   │   └── Step 2: ACTION (Rank Sources) → {{step_1}} UNRESOLVED → LLM HALLUCINATED
│   ├── Run: 3047a7ce (source-analyzer) → ❌ FED CONTAMINATED INPUT → scraped mordorintelligence.com (Asset Management)
│   ├── Run: 0da3ce5b (query-decomposer) → Wave 2 decomposition from contaminated data
│   ├── Run: d15f2c34 (source-discoverer) → Wave 2 — input had correct topic but damage was done
│   ├── Run: 39907313 (source-analyzer) → Wave 2 analysis
│   ├── Run: c59e4103 (fact-verifier) → ❌ Verified claims about "AI in Asset Management" ($4.27B → $12.34B)
│   └── Run: 5296ae68 (synthesizer) → Mixed contaminated + clean data → PDF with wrong topic
```

### 2.2 Root Cause: Silent TOOL_CALL Failure

**Evidence from LLM Interaction Logs:**

```
Run: 83d098ac (source-discoverer, step "Rank and Deduplicate Sources")
Full prompt length: 2,357 chars
Prompt excerpt: "Given these batch search results: {{step_1}}"
                                                    ^^^^^^^^
                                              UNRESOLVED VARIABLE!
```

**Evidence from Tool Interaction Logs:**
- Zero tool interaction logs exist for run `83d098ac`
- The TOOL_CALL step (step_1) produced **no output** and was silently skipped

**Evidence from Context State:**
```python
# Run 83d098ac context_state after execution:
{
    'step_1': False,     # ← NOT PRESENT
    'step_2': 'Here is a ranked and deduplicated list... AI Agent Research...',
}
```

### 2.3 Why the LLM Hallucinated "AI Agent Research"

When the source-discoverer's step 2 received the literal string `{{step_1}}` (unresolved), the LLM had:
- System prompt: "You are a research librarian specializing in source discovery and evaluation"
- No actual search data to work with
- The task: "Analyze all search results, deduplicate URLs, and rank sources"

The LLM fabricated a plausible-looking source ranking table. The topic "AI Agent Research" likely emerged because:
1. The entity's persona and tools are research-oriented
2. "AI agents" is prominent in the LLM's training data
3. Without real data, the LLM defaulted to a common training-data pattern

---

## 3. Identified Vulnerability Classes

### 3.1 ❌ CRITICAL: Silent TOOL_CALL Failures Propagate Hallucinated Data

**What happens:** When a TOOL_CALL step fails silently (no exception raised, no output stored), downstream steps that reference `{{step_N}}` receive unresolved template strings. The LLM then fills in fabricated content.

**Where it occurs:** `step_executor.py:_execute_tool_call()` — if the tool execution returns an empty result or fails without raising, the step result may lack an `output` key.

**Impact:** HIGH — Produces confidently wrong data that cascades through the entire pipeline.

**Current state:** Partially mitigated — `_execute_tool_call` has error handling, but the self-healing retry only triggers on format errors, not on empty/missing output.

---

### 3.2 ⚠️ MEDIUM: Episodic Memory Cross-Run Contamination (Latent)

**What happens:** The `MemoryRouter.retrieve()` loads episodic memories for the entity. Since the `deep-research-process` entity has episodic entries from BOTH the "Relevance AI" run AND the "Computer Model" run, a future invocation would inject BOTH episodes into the `__memory__` context.

**Evidence from database:**
```
Entity: deep-research-process
  Episode 1: Input: "Do a mckinsey level market research on startup companies like Relevance AI"
  Episode 2: Input: "Computer Model for human brain"
```

**Where it occurs:** `memory_service.py:_load_episodic()` → retrieves episodes by entity_id without filtering by topic or run_id.

**Why it didn't trigger this time:** Fix H in `step_executor.py:278-294` strips `__memory__` from child context before propagation. However:
1. The **top-level process entity** STILL receives its own episodic memory
2. If the top-level entity's episodic memory contains unrelated past run data, the LLM may be influenced by it during plan generation

**Impact:** MEDIUM — Currently mitigated for child entities, but the top-level entity is vulnerable. Will worsen as more runs accumulate.

---

### 3.3 ⚠️ MEDIUM: Shared CORTEX Tree Cross-Entity Knowledge Bleeding

**What happens:** All entities in a deep research hierarchy share a single CORTEX tree (propagated via `cortex_tree_id` in Fix E, `step_executor.py:240-242`). Knowledge nodes written by one child entity (e.g., source-analyzer scraping mordorintelligence.com) are visible to all other entities through `__cortex_knowledge__`.

**Evidence:**
```python
# worker.py:740-744 — Injects ALL knowledge nodes into context
knowledge_root = await cortex.get_knowledge_root(tree.id)
if knowledge_root:
    knowledge_viewport = await cortex.navigate(knowledge_root.id)
    context_state["__cortex_knowledge__"] = knowledge_viewport.to_prompt_text()
```

**Impact:** MEDIUM — Currently beneficial (enables synthesizer to see all research), but if a child entity writes incorrect knowledge (from hallucinated tool output), it contaminates all subsequent entities.

---

### 3.4 ⚠️ LOW-MEDIUM: Unresolved Template Variables in Prompt

**What happens:** The `parse_variables()` function silently returns unresolved `{{...}}` patterns when the variable doesn't exist in context. The downstream logic in `step_executor.py:381-383` detects this for tool inputs and falls back, but does NOT fall back for ACTION/THOUGHT step prompts.

**Where it occurs:** `step_executor.py:780-781`:
```python
raw_template = step.target.prompt_template if step.target ... else "{{input}}"
user_prompt = parse_variables(raw_template, input_vars)
# No check for unresolved {{...}} in ACTION/THOUGHT steps!
```

**Impact:** LOW-MEDIUM — Causes unpredictable LLM behavior when a prior step's output is missing.

---

### 3.5 ⚠️ LOW: Multiple `deep-research-process` Entity Instances

**What happens:** The database contains **3 separate `deep-research-process` entities** (from multiple cleanup_and_recreate runs), each with their own child hierarchies. Episodic memories are scoped by entity_id, so episodes don't leak BETWEEN instances. However, if a user triggers the wrong instance, they may get unexpected behavior.

**Evidence:**
```
deep-research-process: d30e7df4... (latest, active)
deep-research-process: 1df2f800... (older instance)
deep-research-process: fc451ccc... (oldest, has "Relevance AI" episode)
```

**Impact:** LOW — Doesn't directly cause contamination, but increases confusion.

---

### 3.6 ⚠️ LOW: Episodic Tree Episodes Lack Run-ID Scoping

**What happens:** When `assemble_runtime_memory()` (architecture spec §13.1) is fully implemented, it will query the episodic tree by TIME only (last 30 days, limit 10). There is no filter to exclude episodes from the CURRENT run or to filter by topic relevance.

**Current state:** The spec's `query_episodes_by_time()` implementation does not filter by `run_id` or task similarity:
```python
# phase-C-episodic-trees.md:255-266 — No run_id or topic filter
result = await self.db.execute(
    select(CortexNode)
    .where(
        CortexNode.tree_id == tree.id,
        CortexNode.node_type == CortexNodeType.EPISODE,
        CortexNode.created_at >= start_date,
        CortexNode.created_at <= end_date,
    )
    .order_by(CortexNode.created_at.desc())
    .limit(limit)
)
```

**Impact:** LOW now (v2 retrieval not fully active), HIGH when enabled.

---

## 4. Remediation Options

### Option A: Targeted Fix — Resolve the Immediate Pipeline Failure

**Scope:** Fix the silent TOOL_CALL failure that caused the hallucinated output.

**Changes:**

#### A.1: Fail-Fast on Empty Tool Output
**File:** `step_executor.py:_execute_tool_call()`

Add validation after tool execution to ensure output is non-empty:

```python
# After tool execution (line ~408):
tool_result = result[0]

# NEW: Fail-fast on empty/null tool output
if not tool_result.output or (isinstance(tool_result.output, str) and not tool_result.output.strip()):
    logger.warning(f"Tool '{tool_id}' returned empty output for step '{step.name}'")
    return {
        "step": step.name,
        "output": f"[TOOL_EMPTY] Tool '{tool_id}' returned no results. The search may have failed.",
        "error": f"Tool '{tool_id}' produced empty output",
        "success": False,
    }
```

#### A.2: Detect Unresolved Variables in ACTION/THOUGHT Steps
**File:** `step_executor.py:_execute_thought()`

Add unresolved variable detection before sending to LLM:

```python
# After parse_variables (line ~781):
user_prompt = parse_variables(raw_template, input_vars)

# NEW: Detect unresolved {{...}} in the prompt
import re
unresolved = re.findall(r'\{\{(.+?)\}\}', user_prompt)
if unresolved:
    logger.warning(
        f"Unresolved variables in prompt for step '{step.name}': {unresolved}. "
        f"This may produce hallucinated output."
    )
    # Option: append warning to prompt so LLM knows data is missing
    user_prompt += (
        f"\n\n⚠️ WARNING: The following data references were not available: "
        f"{', '.join(unresolved)}. If you cannot complete this task without "
        f"this data, respond with: [DATA_MISSING] and explain what is needed."
    )
```

**Pros:**
- Minimal code change, low risk
- Directly addresses the root cause of the observed contamination
- Fast to implement (~1 hour)

**Cons:**
- Does not address latent episodic memory vulnerabilities
- Does not prevent future architectural contamination vectors

**Risk:** LOW — These are additive checks with no behavior change for happy-path executions.

---

### Option B: Episodic Memory Scoping — Prevent Cross-Run Context Leakage

**Scope:** Fix the episodic memory retrieval to be run-scoped and topic-filtered.

**Changes:**

#### B.1: Add Relevance-Based Episodic Filtering
**File:** `memory_service.py:_load_episodic()`

Replace time-only querying with topic-relevance filtering:

```python
async def _load_episodic(self, entity_id, user_id, task_description: str = None) -> List[Dict]:
    """Load episodic memories with optional relevance filtering."""
    try:
        from src.ai.episodic_tree_service import EpisodicTreeService
        company_id = await self._get_company_id(entity_id)
        if company_id:
            episodic_service = EpisodicTreeService(self.db, company_id)
            
            if task_description:
                # Semantic search: only return episodes relevant to current task
                episodes = await episodic_service.query_episodes_by_topic(
                    entity_id=entity_id,
                    company_id=company_id,
                    query=task_description,
                    top_k=5,  # Reduced from 10 to limit noise
                )
            else:
                # Fallback: time-based with strict limit
                episodes = await episodic_service.query_episodes_by_time(
                    entity_id=entity_id,
                    company_id=company_id,
                    start_date=datetime.utcnow() - timedelta(days=7),  # Reduced from 30
                    end_date=datetime.utcnow(),
                    limit=5,
                )
            if episodes:
                return [self._format_episode_node(ep) for ep in episodes]
    except Exception as e:
        logger.debug(f"Episodic Tree load failed: {e}")
    
    return await self._load_episodic_v1(entity_id, user_id)
```

#### B.2: Add Token Budget Cap for Episodic Context
**File:** `worker.py` or `memory_assembly_service.py`

```python
# After memory_text is built (line ~729-731):
memory_text = memory_router.format_for_prompt(memory_ctx)
if memory_text:
    # Cap episodic memory at ~1000 tokens (~4000 chars) per architecture spec §13.2
    MAX_EPISODIC_CHARS = 4000
    if len(memory_text) > MAX_EPISODIC_CHARS:
        memory_text = memory_text[:MAX_EPISODIC_CHARS] + "\n... (episodic context truncated)"
        logger.info(f"Episodic memory truncated to {MAX_EPISODIC_CHARS} chars")
    context_state["__memory__"] = memory_text
```

#### B.3: Pass Task Description to Episodic Retrieval
**File:** `worker.py:720-725`

```python
# C2: Retrieve memory context with tree ID AND task description
memory_router = MemoryRouter(self.db)
task_desc = self._build_task_description(entity, input_data)
memory_ctx = await memory_router.retrieve(
    entity_id=entity.id,
    user_id=run.user_id,
    tree_id=tree.id,
    long_running=True,
    task_description=task_desc,  # NEW: enables relevance filtering
)
```

**Pros:**
- Addresses the latent episodic contamination vector
- Aligns with architecture spec §13 token budget allocation
- Topic-filtered retrieval significantly reduces irrelevant context

**Cons:**
- Requires updating the `MemoryRouter.retrieve()` signature (propagation needed)
- Semantic search for episodes requires working embeddings (the embedding model 404 bug from the roadmap)
- May need embedding backfill for existing episodes

**Risk:** MEDIUM — Changes retrieval behavior, could miss relevant historical context if filtering is too aggressive.

---

### Option C: Full Architecture Hardening — Defense in Depth

**Scope:** Comprehensive multi-layer protection against all identified contamination vectors.

**Includes ALL of Option A + B, plus:**

#### C.1: Pipeline Halt on Upstream Failure
**File:** `worker.py:_execute_steps_dag()` and the sequential loop

Add a "data dependency validation" step that checks whether a step's input dependencies actually produced valid output:

```python
# Before executing a step, validate its data dependencies
if step_obj.target and step_obj.target.prompt_template:
    template = step_obj.target.prompt_template
    required_vars = re.findall(r'\{\{(.+?)\}\}', template)
    for var in required_vars:
        base_var = var.split('.')[0]
        if base_var.startswith('step_') and base_var not in context_state:
            error_msg = (
                f"Step '{step_obj.name}' requires data from '{base_var}' "
                f"which has not been produced. Upstream step may have failed."
            )
            logger.error(error_msg)
            step_result = {
                "step": step_obj.name,
                "output": f"[DEPENDENCY_MISSING] {error_msg}",
                "error": error_msg,
                "success": False,
            }
            # Skip this step and record the failure
            all_step_results.append(step_result)
            continue  # Don't execute the step
```

#### C.2: Knowledge Node Provenance Tracking
**File:** `cortex_bridge.py:ingest_tool_result()`

Tag all knowledge nodes with their source run_id AND the tool's success status:

```python
# Add provenance metadata to knowledge nodes
metadata_extra={
    "run_id": str(run.id),
    "source_tool": tool_id,
    "tool_success": tool_result.success,  # NEW
    "provenance": "tool_scrape",           # NEW
    "verified": False,                      # NEW: requires fact-verification
}
```

#### C.3: Episodic Memory Domain Isolation for Process Entities
**File:** `memory_service.py` or `episodic_tree_service.py`

For PROCESS-type entities (which orchestrate multiple runs), scope episodic memory to only show metadata (run status, cost, timing) rather than content:

```python
async def _load_episodic_for_process(self, entity_id, entity_type):
    """For PROCESS entities, only load structural metadata, not content."""
    if entity_type == 'PROCESS':
        episodes = await self._load_episodic(entity_id, ...)
        # Strip content details, keep only operational metadata
        return [
            {
                "date": ep["date"],
                "status": ep["status"],
                "input_topic": ep["input"][:100],  # Just the topic, not content
                "cost": ep.get("cost_usd"),
                "duration": ep.get("execution_time_ms"),
            }
            for ep in episodes
        ]
    return await self._load_episodic(entity_id, ...)
```

#### C.4: Context Firewall for Child Entity Propagation
**File:** `step_executor.py:_execute_child_invocation()`

Enhance Fix H to also validate that the `input` key doesn't contain stale episodic data:

```python
# After Fix H stripping (line ~294):
# NEW: Validate child input doesn't contain stale episodic summaries
child_input_text = str(child_input.get("input", ""))
if "## Recent Execution History" in child_input_text:
    # Episodic data leaked into the input key — strip it
    idx = child_input_text.find("## Recent Execution History")
    child_input["input"] = child_input_text[:idx].strip()
    logger.warning("Stripped leaked episodic history from child input")
```

**Pros:**
- Multi-layered defense against all identified vectors
- Handles both current and future contamination scenarios
- Aligns with architectural vision (reference-not-copy, token budgets)

**Cons:**
- Larger change surface (5+ files)
- C.1 (pipeline halt) could cause false positives if step_id naming is inconsistent
- C.3 (process isolation) may hide useful context from process-level planning

**Risk:** MEDIUM-HIGH — More moving parts, requires careful testing of each layer.

---

## 5. Recommendation

### Immediate (Today)
Implement **Option A** (targeted fix). This resolves the root cause of the observed contamination with minimal risk.

### Short-term (This Week)
Implement **Option B** (episodic scoping). This prevents the latent contamination vector from manifesting as the system accumulates more episodic data.

### Medium-term (Phase 10)
Implement **Option C** components (C.1 pipeline halt, C.2 provenance) as part of the broader CORTEX hardening initiative.

---

## 6. Impact Matrix

| Fix | Risk | Effort | Prevents |
|-----|------|--------|----------|
| A.1: Fail-fast empty tool output | LOW | 30 min | Silent TOOL_CALL failures |
| A.2: Unresolved variable detection | LOW | 30 min | Hallucinated step outputs |
| B.1: Relevance-based episodic filter | MEDIUM | 2 hrs | Cross-topic memory injection |
| B.2: Token budget cap | LOW | 15 min | Context window overflow |
| B.3: Task description propagation | LOW | 30 min | Enables B.1 |
| C.1: Pipeline dependency halt | MEDIUM | 1 hr | Cascading bad data |
| C.2: Knowledge provenance | LOW | 30 min | Unverified knowledge nodes |
| C.3: Process entity isolation | MEDIUM | 1 hr | Process-level memory leakage |
| C.4: Context firewall | LOW | 30 min | Episodic data in input key |

---

## 7. Test Plan

### Reproduction Test
1. Trigger a deep research run on Topic A
2. Wait for completion
3. Trigger a deep research run on Topic B (completely unrelated)
4. Verify that:
   - No content from Topic A appears in Topic B's output
   - The fact-verifier only checks claims from Topic B
   - The synthesizer's PDF is purely about Topic B

### Episodic Isolation Test
1. After 2+ runs, check `__memory__` in the top-level process entity's context
2. Verify that episodic content is limited to relevant entries only
3. Verify token budget is enforced

### Pipeline Resilience Test
1. Mock a TOOL_CALL step that returns empty output
2. Verify that downstream steps either halt or receive an explicit error message
3. Verify that no hallucinated data enters the pipeline

---

## Appendix A: Database Evidence

### Episodic Trees by Entity
```
deep-research-process:    2 trees (8 total nodes)
dinesh:                   1 tree (4 nodes)  
document-director:        1 tree (6 nodes)
dynamic-instruction-executor: 3 trees (13 nodes)
```

### V1 Episodic Memories (Flat Table)
```
deep-research-process: "Computer Model for human brain" (2026-05-18)
deep-research-process: "Relevance AI market research" (2026-05-18)
document-director: "HireBuddha pitchdeck" (2026-05-14)
```

### Entity Instances
```
deep-research-process: 3 instances (d30e7df4, 1df2f800, fc451ccc)
deep-research-director: 4 instances
deep-research-source-discoverer: 5+ instances
```
