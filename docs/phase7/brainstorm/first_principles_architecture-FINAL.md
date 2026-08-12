# Meta-Agent Architecture — First Principles (Revised)

**Status:** Architectural proposal (v2 — addresses "every agent is meta-cognitive")  
**Date:** 2026-05-11

---

## 0. The Requirement That Changes Everything

> *"Every AI Agent (Hierarchical Entity) in my platform should be a Meta Agent. The dynamic plan currently in the entities will not work properly if the agent itself doesn't have any knowledge of the system."*

This invalidates the Compiler Model (Option C from v1 of this document). If **every** agent needs meta-cognition, then the Meta-Agent isn't a separate service — it's a **capability layer that every agent inherits through the execution engine**.

---

## 1. The Root Problem: Dynamic Planning Is Blind

Look at what `PlannerService._generate_dynamic_plan()` currently sends to the LLM ([planner_service.py:250-258](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/planner_service.py#L250-L258)):

```python
user_prompt = f"Entity: {entity.name}\n"
user_prompt += f"Agent Goal: {entity_goal}\n"
user_prompt += f"User Input: {user_input}\n"
user_prompt += f"Available Tools: {tools_list}\n"    # ← just tool IDs, no descriptions
user_prompt += static_steps_ref
user_prompt += "\nGenerate the execution plan."
```

The planner LLM gets:
- ✅ The entity's name and goal
- ✅ A list of tool **IDs** (just strings like `["web_search", "scraper_tool"]`)
- ✅ The static plan as reference
- ❌ **No tool descriptions or schemas** — the LLM doesn't know what each tool does
- ❌ **No knowledge of step types** — doesn't know THOUGHT vs TOOL_CALL vs CHILD_ENTITY_INVOCATION
- ❌ **No knowledge of children** — for PROCESS entities, doesn't know what child agents exist or what they can do
- ❌ **No knowledge of platform constraints** — doesn't know about CORTEX, governance, IO contracts
- ❌ **No ability to search for existing agents** — can't discover children that would help

The same problem exists in `build_sandwich_prompt()` ([worker.py:187](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/worker.py#L187-L212)) — it injects tool schemas but nothing about the broader platform. The agent is executing in a knowledge vacuum.

**This is why dynamic planning produces garbage plans.** The LLM is asked to generate execution plans without understanding the execution environment.

---

## 2. The Solution: Three Tiers of Meta-Cognition

Meta-cognition isn't binary (meta-agent vs regular agent). It's a **spectrum** gated by entity type and governance:

```
┌─────────────────────────────────────────────────────────────────┐
│                 TIER 3: SELF-MODIFICATION                       │
│         PROCESS entities only, requires HITL approval           │
│                                                                 │
│  Can CREATE new child entities on-the-fly                       │
│  Can REORGANIZE children (reorder, skip, add)                   │
│  Can VERSION existing children (adapt them for the task)        │
│  Tools: meta_entity_creator, meta_entity_executor               │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │            TIER 2: REGISTRY AWARENESS                   │    │
│  │      AGENT + PROCESS entities (dynamic planning)        │    │
│  │                                                         │    │
│  │  Can SEARCH the entity registry for reuse candidates    │    │
│  │  Can INVOKE discovered entities as ad-hoc children      │    │
│  │  Tools: meta_registry_search                            │    │
│  │                                                         │    │
│  │  ┌─────────────────────────────────────────────────┐    │    │
│  │  │        TIER 1: PLATFORM AWARENESS               │    │    │
│  │  │           ALL entities                          │    │    │
│  │  │                                                 │    │    │
│  │  │  Platform manifest injected into system prompt  │    │    │
│  │  │  Tool descriptions + schemas + constraints      │    │    │
│  │  │  Step type definitions + behavioral rules       │    │    │
│  │  │  No extra tools — just knowledge injection      │    │    │
│  │  └─────────────────────────────────────────────────┘    │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### What each tier costs:

| Tier | Extra tokens in prompt | Extra LLM calls | Extra latency |
|------|----------------------|-----------------|---------------|
| **T1: Platform Awareness** | ~2-4K tokens (manifest summary) | 0 | 0 |
| **T2: Registry Search** | ~1K tokens (tool schema) | 0-1 per search | ~1-3s per search |
| **T3: Self-Modification** | ~2K tokens (tool schemas) | 1-3 per creation | ~3-10s per creation |

---

## 3. Tier 1: Platform Awareness (ALL Entities)

### What changes

The compiled platform manifest summary gets injected into **two places**:

#### 3.1 — Into `build_sandwich_prompt()` as a new Layer 3.5

Currently `build_sandwich_prompt()` has Layer 3: "Available Tools" which just lists the entity's own tools. We add a new layer between Tools and Few-Shot Examples:

```python
# NEW Layer 3.5: Platform Awareness
# Injected for ALL entities when dynamic_planning.enabled = true
# or when reasoning_mode = REACT
if platform_awareness:
    sections.append(f"## Platform Awareness\n{platform_awareness}")
```

The `platform_awareness` string comes from a **summarized** manifest (~2-4K tokens, not the full 50-200KB):
- Tool names + 1-line descriptions (not full schemas)
- Entity type hierarchy rules (ACTION < SKILL < AGENT < PROCESS)
- Step type definitions with when-to-use guidance
- Key behavioral constraints (3-5 most critical annotations)

#### 3.2 — Into `PlannerService._generate_dynamic_plan()` system prompt

This is the **highest-leverage change**. The dynamic planner currently operates blind. Fix:

```python
# In _generate_dynamic_plan():
system_prompt = dynamic_config.get("planning_system_prompt") or DEFAULT_PLANNING_SYSTEM_PROMPT

# NEW: Inject platform awareness for intelligent planning
platform_manifest = await self._get_platform_summary(entity.company_id)
system_prompt += f"\n\n## Platform Knowledge\n{platform_manifest}"

# NEW: Inject children descriptions for PROCESS entities
if entity.type == EntityType.PROCESS:
    children_desc = await self._describe_children(entity)
    system_prompt += f"\n\n## Available Child Entities\n{children_desc}"
```

#### 3.3 — The Summarized Manifest

Built by `PlatformSchemaCompiler` with a new `compile_summary()` method:

```python
async def compile_summary(self) -> str:
    """~2-4K token summary for injection into every agent's prompt."""
    full = await self.compile()
    lines = ["# Platform Capabilities\n"]

    # Tools: name + 1-line description
    lines.append("## Tools")
    for t in full["tools"]:
        lines.append(f"- **{t['tool_id']}**: {t['description'][:120]}")

    # Step types: what they do
    lines.append("\n## Step Types")
    lines.append("- THOUGHT/ACTION: LLM reasoning/generation")
    lines.append("- TOOL_CALL: Execute a registered tool")
    lines.append("- CHILD_ENTITY_INVOCATION: Delegate to a child entity")

    # Key constraints (top 5 behavioral annotations)
    lines.append("\n## Key Rules")
    for ann in full["behavioral_annotations"][:5]:
        lines.append(f"- {ann['rule']}")

    return "\n".join(lines)
```

**Cost:** ~2-4K tokens added to each agent's system prompt. For a typical REACT agent doing 5 turns, this is ~10-20K extra input tokens total — roughly **$0.01-0.03 extra per run** with Gemini Flash. Acceptable.

---

## 4. Tier 2: Registry Awareness (AGENT + PROCESS)

### What changes

AGENT and PROCESS entities automatically get `meta_registry_search` as an available tool during REACT execution. The tool is **auto-injected** by the worker, not configured per-entity.

#### 4.1 — Auto-injection in `StepExecutorService._execute_thought()`

In [step_executor.py:676-688](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/step_executor.py#L676-L688):

```python
# --- Build tools ---
tool_ids = []
if entity.capabilities and entity.capabilities.get("tools"):
    all_tools = entity.capabilities.get("tools", [])
    autonomous_tools = [
        t for t in all_tools
        if t.get("usage", "AUTONOMOUS") in ("AUTONOMOUS", "BOTH")
    ]
    tool_ids = [t.get("tool_id") for t in autonomous_tools]

# NEW: Auto-inject meta-tools based on entity type
if entity.type in (EntityType.AGENT, EntityType.PROCESS):
    if "meta_registry_search" not in tool_ids:
        tool_ids.append("meta_registry_search")

if entity.type == EntityType.PROCESS:
    for meta_tool in ["meta_entity_creator", "meta_entity_executor"]:
        if meta_tool not in tool_ids:
            tool_ids.append(meta_tool)

tool_schemas = ToolExecutor.get_tool_schemas(tool_ids)
```

#### 4.2 — What this enables

An AGENT running in REACT mode can now:

1. **Discover helpers mid-execution**: "I need to extract data from Apollo. Let me search the registry for an existing agent that does this..." → calls `meta_registry_search` → finds `apollo-lead-enrichment-skill` → invokes it via `CHILD_ENTITY_INVOCATION`

2. **Self-assess capability gaps**: "My task requires Slack integration but I don't have the `slack_send` tool. Let me search for an entity that does..." → finds one → delegates

3. **Plan more intelligently**: The dynamic planner (Tier 1 awareness) knows the registry exists. It can plan steps like "Step 3: Search registry for a sentiment analysis skill" as part of its dynamic plan.

#### 4.3 — Governance guardrail

Registry search is **read-only** — it can't create or modify anything. The only risk is cost (each semantic search = 1 LLM call for scoring). Mitigate with:
- Rate limit: max 3 registry searches per execution run
- This is enforced by the existing `call_counts` mechanism in `ToolExecutor`

---

## 5. Tier 3: Self-Modification (PROCESS Only + HITL)

### What changes

PROCESS entities get `meta_entity_creator` and `meta_entity_executor` auto-injected. But these are **gated by mandatory HITL approval**.

#### 5.1 — Auto-HITL for creation tools

When a PROCESS entity calls `meta_entity_creator`, the tool itself enforces HITL:

```python
# In MetaEntityCreatorTool.run_with_context():
async def run_with_context(self, input_data, context=None):
    # ... existing anti-sprawl checks ...

    # NEW: Mandatory HITL for runtime entity creation
    # (unless the entity is explicitly the Meta-Agent itself)
    is_meta_agent = context.get("__is_meta_agent__", False)
    if not is_meta_agent:
        approval = await self._request_runtime_creation_approval(
            context, entity_payload
        )
        if not approval.approved:
            return json.dumps({
                "success": False,
                "error": "Entity creation rejected by user",
                "suggestion": approval.suggestion,
            })

    # ... proceed with creation ...
```

#### 5.2 — What this enables

A PROCESS entity ("Deep Research Director") that orchestrates 4 child agents discovers mid-execution that none of its children can handle Slack notifications. It:

1. Searches the registry (Tier 2) → finds no exact match
2. Decides to create a simple ACTION entity wrapping `slack_send`
3. HITL fires → user sees: *"Research Director wants to create a Slack notification agent to deliver results. Approve?"*
4. User approves → entity created → PROCESS invokes it as a new child
5. Research results get posted to Slack

Without Tier 3, the PROCESS would fail silently or produce incomplete results.

#### 5.3 — Governance stack

Self-modification has the heaviest governance:

| Gate | Enforcement |
|------|------------|
| Anti-sprawl daily limit | `AntiSprawlGuard.check_creation_allowed()` (existing) |
| Semantic dedup | `AntiSprawlGuard.check_semantic_duplicate()` (existing) |
| HITL approval | Mandatory for all non-Meta-Agent entity creation |
| Cost cap | Creation + test-execution capped at $1.00 (existing) |
| Recursion depth | Max 2 levels of runtime creation (prevents infinite chains) |
| Schema validation | `MetaSchemaValidatorTool` runs before persistence (existing) |

---

## 6. How The "Meta-Agent" Fits In This Model

The dedicated "Meta-Agent" (the entity users interact with to say "build me an agent") is now just a **pre-configured PROCESS entity with Tier 3 enabled and a specialized system prompt**. It's not architecturally special — it's the same machinery every PROCESS entity has, but with:

1. A system prompt focused on agent synthesis
2. All 5 meta-tools explicitly configured (not just auto-injected)
3. A more permissive governance profile (higher daily creation limit, auto-approve on some operations)
4. The `__is_meta_agent__` flag that relaxes the mandatory HITL on creation

```python
# meta_agent_template.py (simplified)
def generate_meta_agent_template():
    """The Meta-Agent is just a PROCESS entity with full Tier 3 access."""
    return {
        "name": "Meta-Agent",
        "type": "AGENT",
        "identity": {
            "system_prompt": META_AGENT_SYSTEM_PROMPT,
            "role": "Agent Architect",
        },
        "capabilities": {
            "tools": [
                {"tool_id": "meta_platform_introspect", "usage": "AUTONOMOUS"},
                {"tool_id": "meta_registry_search", "usage": "AUTONOMOUS"},
                {"tool_id": "meta_schema_validator", "usage": "AUTONOMOUS"},
                {"tool_id": "meta_entity_creator", "usage": "AUTONOMOUS"},
                {"tool_id": "meta_entity_executor", "usage": "AUTONOMOUS"},
            ]
        },
        "logic_gate": {
            "reasoning_config": {
                "reasoning_mode": "REACT",
                "max_turns": 10,
            }
        },
        "governance": {
            "max_cost_usd": 5.00,
            "hitl_checkpoints": [
                # HITL after decision gate
                {"trigger_type": "TOOL_CALL", "tool_ref": "meta_entity_creator",
                 "message": "Approve entity creation?", "auto_approve_on_timeout": False}
            ]
        },
        "metadata_extensions": {
            "is_meta_agent": True,
            "meta_agent_version": "v3",
        }
    }
```

**The key insight: the Meta-Agent is no longer special infrastructure. It's a power-user of the same meta-cognition layer every agent has access to.**

---

## 7. Concrete Code Changes

### 7.1 — Files to modify

| File | Change | Tier |
|------|--------|------|
| [platform_schema_compiler.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/meta/platform_schema_compiler.py) | Add `compile_summary()` method | T1 |
| [worker.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/worker.py) `build_sandwich_prompt()` | Add Layer 3.5: Platform Awareness | T1 |
| [planner_service.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/planner_service.py) `_generate_dynamic_plan()` | Inject manifest + children into planner prompt | T1 |
| [step_executor.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/step_executor.py) `_execute_thought()` | Auto-inject meta-tools by entity type | T2/T3 |
| [entity_creator.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/tools/meta/entity_creator.py) | Add mandatory HITL for runtime creation | T3 |
| [meta_agent_template.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/meta/meta_agent_template.py) | Simplify to "just another PROCESS with meta-tools" | All |
| [schemas.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/schemas.py) | Add `meta_cognition` config to entity schema | All |

### 7.2 — New entity schema field

Add a `meta_cognition` config block to the entity schema that controls tier opt-in:

```python
# In schemas.py or as part of capabilities/governance
class MetaCognitionConfig(BaseModel):
    """Controls meta-cognitive capabilities for this entity."""
    platform_awareness: bool = True    # Tier 1 (default ON for all)
    registry_search: bool = False      # Tier 2 (auto-ON for AGENT/PROCESS)
    self_modification: bool = False    # Tier 3 (auto-ON for PROCESS, requires HITL)
    max_runtime_creations: int = 3     # Tier 3 limit per execution
    max_registry_searches: int = 5     # Tier 2 limit per execution
```

Auto-defaults applied at execution time based on entity type:

```python
def resolve_meta_cognition(entity) -> MetaCognitionConfig:
    explicit = entity.capabilities.get("meta_cognition", {})
    config = MetaCognitionConfig(**explicit)

    # Auto-enable by type (can be overridden to False explicitly)
    if "registry_search" not in explicit:
        config.registry_search = entity.type in (EntityType.AGENT, EntityType.PROCESS)
    if "self_modification" not in explicit:
        config.self_modification = entity.type == EntityType.PROCESS

    return config
```

---

## 8. Data Flow — A Regular AGENT With Tier 1+2

User runs a "Lead Research Agent" (type=AGENT) with dynamic planning enabled:

```
1. Worker loads entity. type=AGENT → resolve_meta_cognition():
     platform_awareness=true, registry_search=true, self_modification=false

2. PlannerService._generate_dynamic_plan():
     System prompt now includes:
       - DEFAULT_PLANNING_SYSTEM_PROMPT (existing)
       - Platform manifest summary (NEW — Tier 1)
       - Tool descriptions with schemas (NEW — Tier 1)
     
     LLM generates a smarter plan because it KNOWS:
       - web_search returns SERP results, not full pages
       - scraper_tool takes a URL and returns Markdown content
       - CHILD_ENTITY_INVOCATION can delegate to child entities
       - CORTEX steps can persist findings for cross-session use

3. StepExecutorService._execute_thought():
     Tool injection:
       - entity's own tools: [web_search, scraper_tool, email_send]
       - auto-injected: [meta_registry_search]  (Tier 2)
     
     Sandwich prompt includes:
       - Identity & Role (existing)
       - Platform Awareness summary (NEW — Tier 1)
       - All tool schemas including meta_registry_search

4. REACT Turn 1: Agent calls web_search("SaaS Series B funding 2026")
5. REACT Turn 2: Agent calls scraper_tool(url_from_results)
6. REACT Turn 3: Agent realizes it needs Apollo data for enrichment.
     Calls meta_registry_search({"intent": "enrich company data with Apollo API"})
     → Returns: apollo-lead-enrichment-skill (score: 0.91)
     
7. REACT Turn 4: Agent DECIDES to delegate to the found entity.
     It would call meta_entity_executor to run it, or the worker can
     handle this as an ad-hoc CHILD_ENTITY_INVOCATION.

8. REACT Turn 5: Agent synthesizes all data, calls email_send with CSV.
```

**Before Tier 1+2:** The agent would have tried to scrape Apollo manually (failing), or skipped enrichment entirely. Dynamic planning would have produced a generic 3-step plan with no awareness of available tools' capabilities.

**After Tier 1+2:** The agent understands the platform, discovers existing specialists, and delegates effectively. Same entity definition, dramatically better execution.

---

## 9. Data Flow — A PROCESS With Tier 3

User runs "Deep Research Director" (type=PROCESS) that orchestrates 4 child agents:

```
1. Worker loads entity. type=PROCESS → resolve_meta_cognition():
     platform_awareness=true, registry_search=true, self_modification=true

2. Dynamic planning generates plan with children awareness:
     System prompt includes descriptions of all 4 children:
       - Research Planner (AGENT): breaks down research into sub-tasks
       - Web Researcher (AGENT): scrapes and summarizes web sources  
       - Data Analyst (SKILL): extracts key metrics from text
       - Report Synthesizer (AGENT): compiles final report

3. Execution proceeds. Step 3 (Data Analyst) fails because the user
   asked for "sentiment analysis" but Data Analyst only does metrics.

4. Worker enters re-planning (adapt_plan). The planner now knows:
     - What failed and why
     - What other entities exist in the registry (Tier 2 awareness)
     - That it CAN create a new child if needed (Tier 3 awareness)

5. Re-planned step: search registry for sentiment analysis capability.
     → meta_registry_search({"intent": "sentiment analysis on text"})
     → Returns: sentiment-analysis-skill (score: 0.78) — ADAPT candidate

6. HITL fires: "Research Director wants to adapt 'sentiment-analysis-skill'
   for this task. Approve?"
   → User approves

7. meta_entity_creator creates a versioned copy adapted for the task.

8. Execution resumes with the new child entity. Report generated with
   sentiment analysis included.
```

---

## 10. What This Architecture Does NOT Do

To be explicit about boundaries:

1. **ACTION and SKILL entities do NOT get Tier 2/3.** They are leaf nodes — they execute their single function. They get Tier 1 (platform awareness in their prompt) but cannot search registries or create entities.

2. **Tier 3 does NOT bypass anti-sprawl.** Runtime entity creation is subject to the same daily limits and semantic dedup as Meta-Agent creation. A PROCESS entity can't create 100 children in one run.

3. **Meta-cognition does NOT mean autonomy.** HITL checkpoints still gate destructive operations. The agent can *reason about* creating an entity, but a human must approve the action (unless it's the dedicated Meta-Agent with relaxed governance).

4. **Platform awareness does NOT mean the agent reads `worker.py`.** Tier 1 injects a summarized manifest (~2-4K tokens), not the codebase. The agent understands *what* the platform can do, not *how* it's implemented.

---

## 11. Implementation Roadmap

### Phase 1: Tier 1 — Platform Awareness (2-3 days)

Highest leverage, lowest risk. Every agent gets smarter immediately.

1. Add `PlatformSchemaCompiler.compile_summary()` → returns ~2-4K token string
2. Modify `build_sandwich_prompt()` → add Layer 3.5 for platform awareness
3. Modify `PlannerService._generate_dynamic_plan()` → inject manifest + children descriptions
4. Add `MetaCognitionConfig` to schemas
5. Add `resolve_meta_cognition()` helper

### Phase 2: Tier 2 — Registry Search (2 days)

AGENT and PROCESS entities can discover existing entities.

6. Modify `StepExecutorService._execute_thought()` → auto-inject `meta_registry_search` for AGENT/PROCESS
7. Add rate limiting for registry searches (max 5 per run via `call_counts`)
8. Ensure `meta_registry_search` tool is registered in global `ToolRegistry`

### Phase 3: Tier 3 — Self-Modification (3-4 days)

PROCESS entities can create children at runtime.

9. Modify `StepExecutorService._execute_thought()` → auto-inject `meta_entity_creator` + `meta_entity_executor` for PROCESS
10. Add mandatory HITL gate in `MetaEntityCreatorTool` for non-Meta-Agent callers
11. Add recursion depth tracking (max 2 levels of runtime creation)
12. Modify `PlannerService.adapt_plan()` → include meta-tool awareness in re-planning prompts

### Phase 4: Meta-Agent Simplification (1-2 days)

The dedicated Meta-Agent becomes "just another entity."

13. Simplify `meta_agent_template.py` → standard AGENT with all meta-tools explicitly configured
14. Update `seed_meta_agent.py` → seed the simplified template
15. Remove any Meta-Agent-specific code paths in the worker

**Total: ~8-11 days**

---

## 12. Open Decisions

> [!IMPORTANT]
> Three decisions needed before implementation:

### Q1: Should Tier 1 be always-on or opt-in?

**Option A:** Always inject manifest summary for ALL entities (2-4K extra tokens, ~$0.01/run).  
**Option B:** Only inject when `dynamic_planning.enabled = true` OR `reasoning_mode = REACT`.

**My recommendation:** Option B. ACTION/SKILL entities with static plans don't benefit from platform awareness. Only inject when the LLM is actually making decisions (dynamic planning or REACT reasoning).

### Q2: Can AGENT entities (not just PROCESS) create children at runtime?

The current proposal limits Tier 3 to PROCESS only. But an AGENT in REACT mode might also benefit from spawning a quick SKILL to handle a sub-task.

**My recommendation:** Start with PROCESS-only. Expand to AGENT as a V2 enhancement after we see usage patterns. The governance overhead of HITL + anti-sprawl is heavier than the benefit for most AGENT use cases.

### Q3: How do we handle the manifest cache?

`PlatformSchemaCompiler.compile()` is not cheap (DB queries + hash computation). If every agent injects the summary, we need to cache it.

**My recommendation:** Per-tenant, TTL-based cache in Redis. Key: `meta:manifest:{company_id}`. TTL: 5 minutes. Invalidate on tool registry changes. The full compile runs once per 5 minutes per tenant; all agents in that window share the cached summary.
