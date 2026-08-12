# Autonomous Agent Hardening — Part 2: Tool Resilience & Autonomous Loop

**Date**: 2026-05-19  
**Companion**: [Part 1: Memory Architecture](./autonomous-agent-hardening-part1.md)  
**Prior Analysis**: [Episodic Memory Contamination Analysis](./episodic-memory-contamination-analysis.md)

---

## 3. Tool Failure Resilience

### 3.1 Current State: How Tool Failures Are Handled

The current tool execution infrastructure has **three layers** of failure handling:

#### Layer 1: Tool Executor (`tool_executor.py:88-226`)
- If a tool raises an exception, it returns `ToolResult(success=False, error=str(e))`
- If a tool is not found, returns `ToolResult(success=False, error="Tool not registered")`
- Rate limiting returns `ToolResult(skipped=True, skip_reason="...")`
- **No retry logic at this layer**

#### Layer 2: Self-Healing Retry (`step_executor.py:410-454`)
- Only triggers on **format/parse errors** (keywords: "invalid json", "parse", "format", "delimiter")
- Also triggers on **filesystem I/O errors** (keywords: "no such file", "errno 2")
- Asks the LLM to reformat the input and retries **once**
- Does NOT handle: empty output, network failures, API key errors, timeouts, rate limits

#### Layer 3: Review Mechanism (`worker.py:604-606`)
- If `entity.logic_gate.review_mechanism.enabled`, a critic LLM reviews the step output
- Can trigger retry via `on_failure: "RETRY"`
- **Not currently enabled for any Deep Research entity**

#### What's Missing

| Failure Type | Currently Handled? | Impact |
|---|---|---|
| Tool returns empty output | ❌ NO — silently stored as empty string | **This caused the contamination** |
| Tool API key missing/expired | ❌ NO — generic error logged | Step fails, downstream hallucinates |
| Tool network timeout | ⚠️ Partially — step-level timeout exists | Step marked `[TIMEOUT]` but no retry |
| Tool returns wrong format | ✅ YES — self-healing reformat retry | Works for JSON parse errors |
| Tool not registered | ✅ YES — clear error message | LLM sees the error and can adapt |
| Tool rate limited | ✅ YES — `skipped=True` with reason | LLM informed of the skip |

---

### 3.2 Question 1: Can the Entity Retry with Corrected Parameters?

**Yes, but it requires enhancing the self-healing retry to cover more failure types.**

#### Proposed: Extended Self-Healing Retry

```python
# step_executor.py:_execute_tool_call() — enhanced retry logic

# Current: Only handles FORMAT errors
# Proposed: Handle FORMAT + EMPTY + API + TIMEOUT errors

_RETRIABLE_PATTERNS = {
    "format":   {"invalid json", "parse", "format", "delimiter", "decode"},
    "empty":    {"no results", "empty response", "null", "none"},
    "api":      {"api key", "unauthorized", "403", "401", "invalid api"},
    "timeout":  {"timeout", "timed out", "deadline exceeded"},
    "io":       {"no such file", "errno 2", "errno 22"},
}

tool_output_str = str(tool_result.output).lower()
failure_type = None

if not tool_result.success or not tool_result.output or \
   (isinstance(tool_result.output, str) and not tool_result.output.strip()):
    failure_type = "empty"
else:
    for ftype, keywords in _RETRIABLE_PATTERNS.items():
        if any(kw in tool_output_str for kw in keywords):
            failure_type = ftype
            break

if failure_type:
    logger.warning(f"Tool '{tool_id}' failed ({failure_type}). Attempting LLM-guided retry...")
    
    # Ask LLM to diagnose and fix the input
    reformatted_input = await self._reformat_tool_input(
        run=run, entity=entity, tool_id=tool_id,
        original_input=raw_input,
        error_message=str(tool_result.output),
        step_description=step.description or step.name,
        failure_type=failure_type,  # NEW: tell LLM what kind of failure
    )
    
    if reformatted_input and reformatted_input != raw_input:
        retry_result = await ToolExecutor.execute_tools(
            [{"tool": tool_id, "input": reformatted_input}],
            extra_context=extra_context,
        )
        # Use retry if it improved
        if retry_result[0].success:
            tool_result = retry_result[0]
```

#### Enhanced `_reformat_tool_input` Prompt

```python
REFORMAT_PROMPT = """The tool '{tool_id}' failed with a {failure_type} error.

Original input: {original_input}
Error: {error_message}
Step description: {step_description}

{FAILURE_TYPE_SPECIFIC_GUIDANCE}

Please provide a corrected input that will work. Return ONLY the corrected input string."""

FAILURE_GUIDANCE = {
    "empty": "The tool returned no results. Try simplifying the query, using broader search terms, or changing the input format.",
    "format": "The input format was invalid. Check JSON syntax, escaping, and required fields.",
    "api": "The API returned an authentication error. This cannot be fixed by changing input. Return the original input unchanged.",
    "timeout": "The request timed out. Try a shorter/simpler input to reduce processing time.",
}
```

#### Effects

| Aspect | Effect |
|---|---|
| Empty output recovery | The LLM simplifies the query and retries — may recover ~60% of empty results |
| Format error recovery | Already works — extended to cover more patterns |
| API key errors | Not fixable by LLM — properly categorized and escalated |
| Cost | +1 LLM call per retry (~$0.001-0.01) — negligible vs cost of a failed pipeline |
| Latency | +2-5 seconds per retry attempt |

---

### 3.3 Question 2: Can the Entity Switch to an Alternative Tool?

**Yes. This is the most powerful resilience mechanism we can add.** Currently, if `web_search` fails, the entity is stuck — it can't try `headless_browser` or any other alternative. We need a **Tool Fallback Chain**.

#### Available Tools That Can Substitute for Each Other

| Primary Tool | Alternative Tool | When to Switch |
|---|---|---|
| `web_search` / `batch_web_search` | `headless_browser` | Search API returns empty or errors |
| `scraper_tool` (Firecrawl) | `headless_browser` | Scraping blocked, JS-heavy site, or 403 |
| `headless_browser` | `scraper_tool` | Browser tool unavailable |
| `pdf_generator` | `docx_tool` + convert | PDF generation fails |

#### Proposed: Tool Fallback Registry

```python
# New: tool_fallback.py
TOOL_FALLBACK_CHAINS = {
    "web_search": {
        "alternatives": ["headless_browser"],
        "conditions": {
            "headless_browser": "Search returned empty or error. Use browser to search directly."
        },
        "input_transform": {
            "headless_browser": lambda query: f"Navigate to google.com and search for: {query}"
        }
    },
    "batch_web_search": {
        "alternatives": ["web_search"],
        "conditions": {
            "web_search": "Batch search failed. Try individual searches."
        },
        "input_transform": {
            "web_search": lambda queries: queries.split('\n')[0]  # Try first query individually
        }
    },
    "scraper_tool": {
        "alternatives": ["headless_browser"],
        "conditions": {
            "headless_browser": "Scraper blocked or failed. Use headless browser to render page."
        },
        "input_transform": {
            "headless_browser": lambda url: f"Navigate to {url} and extract the page content."
        }
    },
}
```

#### Integration Point: `step_executor.py:_execute_tool_call()`

```python
# After the retry attempt fails:
if failure_type and not tool_result.success:
    from src.ai.tool_fallback import TOOL_FALLBACK_CHAINS
    chain = TOOL_FALLBACK_CHAINS.get(tool_id, {})
    
    for alt_tool_id in chain.get("alternatives", []):
        # Check if alt tool is available and entity has permission
        if alt_tool_id in entity_tool_ids:
            logger.info(f"Falling back from '{tool_id}' to '{alt_tool_id}'")
            
            # Transform input for alternative tool
            transform_fn = chain.get("input_transform", {}).get(alt_tool_id)
            alt_input = transform_fn(raw_input) if transform_fn else raw_input
            
            alt_result = await ToolExecutor.execute_tools(
                [{"tool": alt_tool_id, "input": alt_input}],
                extra_context=extra_context,
            )
            if alt_result[0].success and alt_result[0].output:
                logger.info(f"Fallback to '{alt_tool_id}' succeeded!")
                tool_result = alt_result[0]
                tool_result.tool = f"{tool_id}→{alt_tool_id}"  # Track provenance
                break
```

#### Effects

| Aspect | Effect |
|---|---|
| Web search resilience | If SerpAPI fails, browser searches Google directly |
| Scraping resilience | If Firecrawl is blocked, Playwright renders the page |
| Entity autonomy | Entity doesn't need to know about fallbacks — happens transparently |
| Tool permission | Only falls back to tools the entity already has in its `capabilities.tools` |
| Cost tracking | Both attempts tracked; fallback tool cost added to run total |

---

### 3.4 Question 3: Making the Agentic Loop Truly Autonomous

This is the fundamental question: **How can the parent entity detect when a step's output has deviated from the goal, and re-execute with corrected instructions?**

#### Current Gap Analysis

The current execution flow is "fire and forget" — each step executes, its output is stored in `context_state`, and the next step consumes it without validation. There is no mechanism to:

1. **Validate** that a step's output aligns with the entity's goal
2. **Detect** topic drift (e.g., "AI in Asset Management" when goal is "Brain Modeling")
3. **Re-execute** a step with corrected instructions
4. **Escalate** to the parent if self-correction fails

#### Proposed: Goal Alignment Verification Layer

This adds a lightweight LLM-based verification after each critical step:

```python
# New: goal_alignment.py

class GoalAlignmentVerifier:
    """
    Post-step verification: checks that step output aligns with the entity's 
    declared goal. Runs after critical steps (configurable).
    """
    
    VERIFICATION_PROMPT = """You are a quality control checker. 
    
The entity's GOAL is: {goal}
The entity's current TASK is: {task_description}

A step just completed with the following output (first 2000 chars):
{step_output}

Does this output align with the stated goal and task? Consider:
1. Is the topic/subject matter correct?
2. Does the output contain relevant data for the goal?
3. Are there any signs of topic drift or hallucination?

Respond with JSON:
{{
    "aligned": true/false,
    "confidence": 0.0-1.0,
    "issues": ["list of detected issues"],
    "correction_hint": "if misaligned, suggest what the step should have produced"
}}"""

    async def verify_step_alignment(
        self, llm_router, entity_goal: str, task_desc: str, 
        step_output: str, step_name: str
    ) -> Dict:
        prompt = self.VERIFICATION_PROMPT.format(
            goal=entity_goal,
            task_description=task_desc,
            step_output=step_output[:2000],
        )
        response = await llm_router.call_llm(
            task_type="text_generation",
            system_prompt="You are a strict quality control verifier.",
            user_prompt=prompt,
            temperature=0.1,  # Low temperature for consistent judgments
            max_tokens=500,
        )
        return parse_json(response.output)
```

#### Integration into the Execution Loop

```python
# worker.py:_execute_step_wrapper() — after step execution

step_result = await self._execute_step(run, entity, step_obj, context_state)

# Goal Alignment Check (configurable per entity)
reasoning_config = (entity.logic_gate or {}).get("reasoning_config", {})
if reasoning_config.get("goal_validation_interval", 0) > 0:
    step_count = len([k for k in context_state if k.startswith("step_")])
    interval = reasoning_config["goal_validation_interval"]
    
    if step_count % interval == 0:  # Check every N steps
        verifier = GoalAlignmentVerifier()
        alignment = await verifier.verify_step_alignment(
            llm_router=LLMRouter(self.db, run.company_id),
            entity_goal=entity.goal or "",
            task_desc=context_state.get("input", ""),
            step_output=step_result.get("output", ""),
            step_name=step_obj.name,
        )
        
        if not alignment.get("aligned", True):
            logger.warning(
                f"Step '{step_obj.name}' output MISALIGNED with goal! "
                f"Issues: {alignment.get('issues')}"
            )
            
            # Re-execute with correction hint
            correction = alignment.get("correction_hint", "")
            context_state["__alignment_correction__"] = (
                f"⚠️ The previous attempt at '{step_obj.name}' produced "
                f"off-topic results. Issues: {alignment['issues']}. "
                f"Correction: {correction}. "
                f"Please re-execute this step focusing strictly on the goal."
            )
            
            # Re-execute (max 1 retry to avoid infinite loops)
            if not context_state.get(f"__retry_{step_obj.step_id}__"):
                context_state[f"__retry_{step_obj.step_id}__"] = True
                step_result = await self._execute_step(
                    run, entity, step_obj, context_state
                )
                del context_state["__alignment_correction__"]
```

#### Step-Level Awareness: Context Accumulation

The entity should also be **aware of all step results** during execution. Currently, the `## Available Context from Previous Steps` block (step_executor.py:793-801) already does this — it appends all previous step outputs to the user prompt. However, this needs enhancement:

```python
# Enhanced context block with step status tracking
context_block = "\n\n## Execution Progress\n"
for ctx_key, ctx_val in step_outputs.items():
    val_str = str(ctx_val)
    # Detect failed/empty steps
    if val_str.startswith("[FAILED]") or val_str.startswith("[TOOL_EMPTY]"):
        context_block += f"\n### ❌ {ctx_key} (FAILED)\n{val_str[:500]}\n"
    elif val_str.startswith("[TIMEOUT]"):
        context_block += f"\n### ⏱️ {ctx_key} (TIMED OUT)\n{val_str[:500]}\n"
    else:
        context_block += f"\n### ✅ {ctx_key}\n{val_str[:30000]}\n"
```

This makes the entity explicitly aware of which upstream steps failed, enabling it to:
- Skip processing of known-bad data
- Report data gaps in its output
- Request re-execution of failed dependencies

---

## 4. Complete Architecture: Autonomous Self-Correcting Loop

Combining all the recommendations into a unified execution architecture:

```
┌──────────────────────────────────────────────────────────┐
│                 ENTITY EXECUTION LOOP                     │
│                                                           │
│  1. PLAN: Generate/load execution steps                   │
│     └── Inject Intelligence Rules + Failure Patterns      │
│         (NO raw episodic data)                            │
│                                                           │
│  2. EXECUTE: For each step:                               │
│     ├── [TOOL_CALL] Execute with retry chain:             │
│     │   ├── Try primary tool                              │
│     │   ├── If FORMAT error → LLM reformat + retry        │
│     │   ├── If EMPTY output → LLM simplify + retry        │
│     │   ├── If still failing → Try fallback tool          │
│     │   └── If all fail → Mark [TOOL_FAILED] in context   │
│     │                                                     │
│     ├── [ACTION/THOUGHT] Execute with safeguards:         │
│     │   ├── Detect unresolved {{variables}} → append      │
│     │   │   [DATA_MISSING] warning to prompt              │
│     │   └── If upstream step failed → skip or warn        │
│     │                                                     │
│     ├── [CHILD_ENTITY] Execute with isolation:            │
│     │   ├── Strip parent episodic memory (Fix H)          │
│     │   ├── Strip parent step_id keys (Fix F)             │
│     │   └── Propagate CORTEX tree ID (Fix E)              │
│     │                                                     │
│     └── POST-STEP: Goal Alignment Check                   │
│         ├── Every N steps, verify output matches goal     │
│         ├── If misaligned → re-execute with correction    │
│         └── If still misaligned → escalate to parent      │
│                                                           │
│  3. DEPENDENCY VALIDATION: Before each step:              │
│     ├── Check all {{step_N}} dependencies exist           │
│     ├── If missing → skip with [DEPENDENCY_MISSING]       │
│     └── If upstream FAILED → inject failure context       │
│                                                           │
│  4. COMPLETION:                                           │
│     ├── Write episode (for analytics, NOT for injection)  │
│     ├── Extract failure patterns → Intelligence Tree      │
│     └── Update CORTEX knowledge nodes                     │
└──────────────────────────────────────────────────────────┘
```

---

## 5. Integrated Recommendations from Prior Analysis

From [episodic-memory-contamination-analysis.md](./episodic-memory-contamination-analysis.md):

| Fix ID | Description | Status in This Document |
|---|---|---|
| A.1 | Fail-fast on empty tool output | ✅ Expanded to "Extended Self-Healing Retry" (§3.2) |
| A.2 | Detect unresolved template variables | ✅ Included in "Step-Level Awareness" (§3.4) |
| B.1 | Relevance-based episodic filtering | ✅ Superseded by "Learnings-Only Memory" (Part 1, §1.4) |
| B.2 | Token budget cap | ⏸️ Deferred per user request |
| C.1 | Pipeline dependency halt | ✅ Included in "Dependency Validation" (§3.4) |
| C.2 | Knowledge node provenance | ✅ Included — add `verified` field to knowledge nodes |
| C.3 | Process entity isolation | ✅ Superseded by `memory_scope: INTELLIGENCE_ONLY` (Part 1, §1.5) |
| C.4 | Context firewall for child propagation | ✅ Already implemented as Fix H |

---

## 6. Complete Priority Matrix

| # | Change | Priority | Effort | Risk | File(s) |
|---|---|---|---|---|---|
| 1 | Remove episodic injection from Deep Research entities | P0 | 30m | LOW | `worker.py`, entity config |
| 2 | Fail-fast on empty tool output | P0 | 30m | LOW | `step_executor.py` |
| 3 | Detect unresolved `{{variables}}` in prompts | P0 | 30m | LOW | `step_executor.py` |
| 4 | Pipeline dependency validation | P0 | 1h | LOW | `worker.py` |
| 5 | Tool fallback chains | P1 | 2h | MED | New `tool_fallback.py`, `step_executor.py` |
| 6 | Goal alignment verification | P1 | 3h | MED | New `goal_alignment.py`, `worker.py` |
| 7 | Failure pattern extraction | P1 | 3h | MED | New `failure_pattern_service.py`, `worker.py` |
| 8 | Add `embedding` task type to AI Config | P1 | 1h | LOW | `AIModelConfigPage.tsx`, `embedding_service.py` |
| 9 | Wire `MemoryAssemblyService` into execution | P2 | 2h | MED | `worker.py`, `memory_assembly_service.py` |
| 10 | `RECALL` tool for on-demand memory | P2 | 1h | LOW | New `recall_tool.py` |
| 11 | Redesign Deep Research entities | P1 | 4h | MED | `cleanup_and_recreate.py` |
| 12 | Clean up duplicate entity instances | P0 | 15m | LOW | DB cleanup script |

---

## 7. Deep Research Entity Redesign (User Requested)

The current Deep Research hierarchy has accumulated technical debt from multiple iterations. A fresh redesign from first principles should:

1. **Simplify the hierarchy** — reduce from 15 entities to 8-10 focused entities
2. **Use `memory_scope: INTELLIGENCE_ONLY`** on all entities
3. **Add `headless_browser` as fallback tool** on source-discoverer and source-analyzer
4. **Enable goal alignment verification** on the director entity
5. **Use `batch_web_search`** (not `web_search`) for source discovery
6. **Add explicit `input_dependencies`** in all step targets to enable dependency validation

This redesign should be done AFTER implementing fixes #1-5, so the new entities benefit from the hardened execution infrastructure.

---

*End of Part 2. See [Part 1: Memory Architecture](./autonomous-agent-hardening-part1.md) for episodic memory analysis.*
