# Phase 10C — Memory Consolidation: Implementation Plan

> **Prerequisite:** Phase 10A complete. Can run in parallel with 10B.  
> **Estimated Effort:** 3–4 days  
> **Risk Level:** Medium-High  
> **Goal:** Wire `MemoryAssemblyService` as the primary memory pipeline. Clean up CortexBridge. Add missing memory scope.

---

## Step 1: Add Memory Pipeline Feature Flag

### 1.1 Schema update — Add `memory_pipeline` to entity capabilities

The entity's `capabilities` JSON already supports `memory` config. Add `memory_pipeline` key:

**Location:** Entity creation/update validation (wherever `capabilities.memory` is read)

```python
# In execute_run — after reading memory_config
memory_config = (entity.capabilities or {}).get("memory", {})
memory_pipeline = memory_config.get("memory_pipeline", "v1")  # "v1" or "v2"
```

### 1.2 No schema migration needed

`capabilities` is a JSONB column — the new key is just an additional JSON field.

---

## Step 2: Create Unified Memory Interface

### Target: `ai/memory/assembler.py` (new file)

```python
"""
ai.memory.assembler — Unified memory assembly interface.

Routes memory retrieval through either v1 (MemoryRouter) or v2
(MemoryAssemblyService) based on entity configuration.
"""
import logging
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def assemble_memory(
    db: AsyncSession,
    company_id: UUID,
    entity_id: UUID,
    user_id: Optional[UUID] = None,
    tree_id: Optional[UUID] = None,
    task_description: str = "",
    memory_pipeline: str = "v1",
    memory_scope: str = "FULL",
    runtime_tree=None,
    long_running: bool = False,
) -> Dict[str, Any]:
    """
    Unified entry point for memory retrieval.

    Args:
        memory_pipeline: "v1" (MemoryRouter) or "v2" (MemoryAssemblyService)
        memory_scope: "FULL", "RUN_SCOPED", "INTELLIGENCE_ONLY", "KNOWLEDGE_ONLY", "NONE"

    Returns:
        Dict with memory context ready for injection into context_state.
    """
    if memory_scope == "NONE":
        return {}

    if memory_pipeline == "v2":
        return await _assemble_v2(
            db, company_id, entity_id, user_id,
            task_description, memory_scope, runtime_tree,
        )
    else:
        return await _assemble_v1(
            db, entity_id, user_id, tree_id,
            memory_scope, long_running,
        )


async def _assemble_v1(
    db, entity_id, user_id, tree_id,
    memory_scope, long_running,
) -> Dict[str, Any]:
    """Legacy MemoryRouter path."""
    from src.ai.memory_service import MemoryRouter
    memory_router = MemoryRouter(db)

    if memory_scope == "INTELLIGENCE_ONLY":
        # Only failure patterns
        return await memory_router.retrieve(
            entity_id=entity_id,
            user_id=user_id,
            tree_id=tree_id,
            long_running=long_running,
            include_episodic=False,
        )
    else:
        return await memory_router.retrieve(
            entity_id=entity_id,
            user_id=user_id,
            tree_id=tree_id,
            long_running=long_running,
        )


async def _assemble_v2(
    db, company_id, entity_id, user_id,
    task_description, memory_scope, runtime_tree,
) -> Dict[str, Any]:
    """New MemoryAssemblyService path — 4-domain retrieval."""
    from src.ai.memory_assembly_service import MemoryAssemblyService

    # Map memory_scope to include_domains
    domain_map = {
        "FULL": ["knowledge", "experience", "intelligence", "episodic"],
        "RUN_SCOPED": ["knowledge", "experience", "intelligence", "episodic"],
        "INTELLIGENCE_ONLY": ["intelligence"],
        "KNOWLEDGE_ONLY": ["knowledge", "intelligence"],
    }
    domains = domain_map.get(memory_scope, ["knowledge", "experience", "intelligence", "episodic"])

    assembler = MemoryAssemblyService(db, company_id)
    result = await assembler.assemble_runtime_memory(
        entity_id=entity_id,
        user_id=user_id,
        task_description=task_description,
        runtime_tree=runtime_tree,
        include_domains=domains,
    )

    # Format into the same structure execute_run expects
    memory_context = {}
    if result.formatted_prompt:
        memory_context["__memory__"] = result.formatted_prompt
    if result.intelligence_rules:
        memory_context["__intelligence_rules__"] = result.intelligence_rules
    if result.episodic_context:
        memory_context["__episodic_memory__"] = result.episodic_context

    logger.info(
        f"MemoryAssembly v2: {len(result.knowledge_refs)} knowledge refs, "
        f"{len(result.experience_suggestions)} experience suggestions, "
        f"{len(result.intelligence_rules)} rules, "
        f"{len(result.episodic_context)} episodes"
    )
    return memory_context
```

---

## Step 3: Wire Into `ExecutionEngine.execute_run()`

### Location: `ai/core/execution_engine.py` (was worker.py lines 797–830)

**Before:**
```python
# Memory retrieval (current code ~lines 797-830)
memory_router = MemoryRouter(self.db)
_memory_scope = memory_config.get("memory_scope", "FULL")
if _memory_scope != "NONE":
    # ... complex branching ...
    memory_ctx = await memory_router.retrieve(...)
    if memory_ctx:
        formatted = memory_router.format_for_prompt(memory_ctx)
        context_state["__memory__"] = formatted
```

**After:**
```python
from src.ai.memory.assembler import assemble_memory

_memory_scope = memory_config.get("memory_scope", "FULL")
_memory_pipeline = memory_config.get("memory_pipeline", "v1")

if _memory_scope != "NONE":
    try:
        memory_ctx = await assemble_memory(
            db=self.db,
            company_id=entity.company_id,
            entity_id=entity.id,
            user_id=run.user_id,
            tree_id=tree.id if tree else None,
            task_description=self._cortex_bridge.build_task_description(entity, context_state),
            memory_pipeline=_memory_pipeline,
            memory_scope=_memory_scope,
            runtime_tree=tree,
            long_running=_is_long_running,
        )
        context_state.update(memory_ctx)
    except Exception as _mem_err:
        logger.warning(f"Memory retrieval failed (non-fatal): {_mem_err}")
```

This replaces ~35 lines of branching with a single function call.

---

## Step 4: Add `KNOWLEDGE_ONLY` Memory Scope

### 4.1 Already handled by the `domain_map` in `assembler.py` (Step 2)

The `KNOWLEDGE_ONLY` scope is defined in the domain map:
```python
"KNOWLEDGE_ONLY": ["knowledge", "intelligence"],
```

### 4.2 Update `schemas.py` to document valid scopes

Add to the `ContextPolicy` or `LogicGate` model docstring:

```python
# Valid memory_scope values:
# "FULL" — All 4 domains (default)
# "RUN_SCOPED" — Same as FULL, scoped to current run
# "INTELLIGENCE_ONLY" — Only distilled rules and strategies
# "KNOWLEDGE_ONLY" — Knowledge + Intelligence, no episodic history
# "NONE" — No memory injection
```

---

## Step 5: Clean Up `CortexBridge` — Separate Read/Write/Step Concerns

### 5.1 Current state

`CortexBridge` has 3 distinct responsibilities:
1. **Reading:** `get_relevant_knowledge()`, `refresh_viewport()`
2. **Writing:** `write_step()`, `write_checkpoint()`, `write_reflection()`, `ingest_tool_result()`
3. **Orchestration:** `execute_cortex_step()` — handles NAVIGATE/READ/WRITE/RECURSE step types

### 5.2 Refactoring approach — Internal method groups, not split classes

Given CortexBridge is only 649 lines (healthy size), splitting into 3 classes would over-engineer it. Instead, clearly group methods with section headers:

```python
class CortexBridge:
    """Manages CORTEX tree reads, writes, navigation, and checkpoints."""

    # ===================================================================
    # Configuration & Initialization
    # ===================================================================
    
    # ===================================================================
    # Reading Operations
    # ===================================================================
    
    async def refresh_viewport(self, cortex, tree, context_state): ...
    async def get_relevant_knowledge(self, tree_id, query): ...
    
    # ===================================================================
    # Writing Operations
    # ===================================================================
    
    async def write_step(self, cortex, working_root_id, step_result, run_id): ...
    async def write_checkpoint(self, cortex, tree, context_state, step_name): ...
    async def write_reflection(self, tree_id, cursor_id, step_name, reflection): ...
    async def ingest_tool_result(self, run, tool_id, tool_output, context): ...
    
    # ===================================================================
    # CORTEX Step Execution
    # ===================================================================
    
    async def execute_cortex_step(self, run, entity, step, cortex, tree, context): ...
```

### 5.3 Route ALL CORTEX operations through CortexBridge

**Location:** `execute_run()` lines 763–793 — direct `CortexService` usage

**Current** (direct access):
```python
cortex = CortexService(self.db, entity.company_id)
tree = await cortex.get_or_create_runtime_tree(...)
viewport = await cortex.navigate(tree.resume_cursor_id or tree.root_node_id)
```

**After** (routed through bridge):
```python
cortex, tree = await self._cortex_bridge.initialize_tree(entity, run)
viewport = await self._cortex_bridge.get_initial_viewport(tree)
```

Add these two methods to `CortexBridge`:

```python
async def initialize_tree(self, entity, run):
    """Create or resume a CORTEX runtime tree for this execution."""
    cortex = CortexService(self.db, self._company_id)
    
    cortex_tree_id = run.input_data.get("cortex_tree_id")
    subtree_root_id = run.input_data.get("subtree_root_id")
    
    if cortex_tree_id and subtree_root_id:
        tree = await cortex.get_tree(UUID(cortex_tree_id))
        # ... scoped subtree logic ...
    elif cortex_tree_id:
        tree = await cortex.get_tree(UUID(cortex_tree_id))
    else:
        tree = await cortex.get_or_create_runtime_tree(
            entity_id=entity.id,
            company_id=entity.company_id,
        )
    
    return cortex, tree


async def get_initial_viewport(self, tree):
    """Get the initial viewport for the tree."""
    cortex = CortexService(self.db, self._company_id)
    cursor_id = tree.resume_cursor_id or tree.root_node_id
    return await cortex.navigate(cursor_id)
```

---

## Step 6: Fix Episodic Tree Service Dependency

### Location: `ai/episodic_tree_service.py` line 163

```python
from src.ai.memory_service import _summarize
```

This imports a private function. The fix:

1. Move `_summarize` to `ai/shared/text_utils.py`:

```python
# ai/shared/text_utils.py
async def summarize_text(db, company_id, text: str, max_tokens: int = 200) -> str:
    """Summarize text using a cheap LLM call."""
    from src.ai.llm_router import LLMRouter
    llm = LLMRouter(db=db, company_id=company_id)
    response = await llm.call_llm(
        task_type="text_generation",
        system_prompt="Summarize the following text concisely.",
        user_prompt=text[:4000],
        max_tokens=max_tokens,
        temperature=0.1,
    )
    return response.output
```

2. Update both `memory_service.py` and `episodic_tree_service.py` to import from the shared location.

---

## Step 7: Add DreamingEngine Auto-Schedule

### Location: `ai/core/arq_jobs.py` (arq cron registration)

Add dreaming to the cron schedule:

```python
# In WorkerSettings.cron_jobs:
cron(dreaming_cron_trigger, hour={2, 14}),  # Run twice daily (2 AM, 2 PM)
```

```python
# New arq job function
async def dreaming_cron_trigger(ctx: dict) -> dict:
    """Periodic cron job to trigger dreaming for all active entities."""
    from src.common.database import AsyncSessionLocal
    from src.ai.models import HierarchicalEntity
    from sqlalchemy import select

    triggered = 0
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(HierarchicalEntity.id, HierarchicalEntity.company_id).where(
                HierarchicalEntity.status != 'ARCHIVED',
            )
        )
        entities = result.fetchall()

        for entity_id, company_id in entities:
            try:
                from src.ai.dreaming_engine import DreamingEngine
                engine = DreamingEngine(db, company_id)
                if await engine._should_run(entity_id):
                    result = await engine.dream(entity_id=entity_id)
                    triggered += 1
                    await db.commit()
            except Exception as e:
                logger.warning(f"Dreaming cron failed for entity {entity_id}: {e}")

    return {"triggered": triggered, "total_entities": len(entities)}
```

---

## Validation Checklist (Phase 10C Complete)

- [ ] `ai/memory/assembler.py` exists and `assemble_memory()` works for both v1 and v2 pipelines
- [ ] `KNOWLEDGE_ONLY` scope returns knowledge + intelligence, no episodic
- [ ] Test entity with `memory_pipeline: "v1"` executes identically to before
- [ ] Test entity with `memory_pipeline: "v2"` executes correctly with 4-domain assembly
- [ ] All CORTEX tree operations in `execute_run` route through `CortexBridge`
- [ ] `episodic_tree_service.py` no longer imports private `_summarize` from `memory_service.py`
- [ ] Dreaming cron job registered and triggers correctly
- [ ] `python -m arq src.ai.worker.WorkerSettings` starts without errors
- [ ] Trigger test entity execution → verify COMPLETED status

---

> **Next:** [impl_10D_autonomous_reasoning.md](./impl_10D_autonomous_reasoning.md)
