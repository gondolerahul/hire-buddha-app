# Phase 10 — Refactoring Blueprint: Domain-Driven Restructuring

> Companion to [01_executive_summary.md](./01_executive_summary.md)

---

## 1. Target Directory Structure

```
ai/
├── __init__.py                    # Re-exports for backward compatibility
├── worker.py                      # SLIM: Only WorkerSettings + arq cron registration (~80 lines)
│
├── core/                          # 🧠 Orchestration & Execution
│   ├── __init__.py
│   ├── execution_engine.py        # ExecutionEngine class (from worker.py)
│   ├── execution_pipeline.py      # NEW: Phase-based pipeline pattern
│   ├── recursive_engine.py        # RecursiveReasoningEngine (from worker.py)
│   ├── step_executor.py           # StepExecutorService (moved from ai/)
│   ├── arq_jobs.py                # Arq job functions (from worker.py)
│   ├── prompt_utils.py            # parse_variables, build_sandwich_prompt, filter_context_for_step
│   ├── context_utils.py           # _store_step_output, _sanitize_context_for_persistence
│   └── exceptions.py              # UncertaintySignal, AgentError taxonomy
│
├── memory/                        # 🗄️ CORTEX & Memory Systems
│   ├── __init__.py
│   ├── cortex_service.py          # CortexRouter (moved from ai/)
│   ├── cortex_bridge.py           # CortexBridge (moved from ai/)
│   ├── cortex_models.py           # CORTEX ORM models (moved from ai/)
│   ├── cortex_ingestion.py        # Document ingestion to CORTEX (moved)
│   ├── memory_service.py          # MemoryRouter (moved, to be deprecated)
│   ├── memory_assembly.py         # MemoryAssemblyService (moved, promoted to primary)
│   ├── episodic_tree_service.py   # Episodic silo (moved)
│   ├── experience_tree_service.py # Experience silo (moved)
│   ├── intelligence_tree_service.py # Intelligence silo (moved)
│   ├── knowledge_tree_service.py  # Knowledge silo (moved)
│   ├── embedding_service.py       # Embedding operations (moved)
│   ├── graph_service.py           # Semantic graph layer (moved)
│   └── dreaming_engine.py         # Background learning (moved)
│
├── planning/                      # 📋 Planning & Goal Management
│   ├── __init__.py
│   ├── planner_service.py         # PlannerService (moved from ai/)
│   ├── goal_alignment.py          # GoalAlignmentVerifier (moved from ai/)
│   └── goal_guard.py              # NEW: Unified goal validation middleware
│
├── governance/                    # 🛡️ Billing, HITL, Safety
│   ├── __init__.py
│   ├── governance_service.py      # GovernanceService (moved from ai/)
│   └── rate_limiter.py            # Rate limiting (moved from ai/)
│
├── llm/                           # 🤖 LLM Abstraction Layer
│   ├── __init__.py
│   ├── router.py                  # LLMRouter (moved from ai/llm_router.py)
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── base.py                # BaseLLMAdapter
│   │   ├── gemini.py              # GeminiAdapter
│   │   ├── anthropic.py           # AnthropicAdapter
│   │   └── azure_openai.py        # AzureOpenAIAdapter
│   └── react_loop.py             # NEW: Shared REACT loop logic
│
├── meta/                          # 🔮 Meta-Cognition (unchanged)
│   ├── __init__.py
│   ├── meta_agent_template.py
│   ├── platform_schema_compiler.py
│   ├── registry_search_service.py
│   ├── anti_sprawl.py
│   └── seed_meta_agent.py
│
├── tools/                         # 🔧 Tool Implementations (unchanged structure)
│   ├── __init__.py
│   ├── base.py
│   ├── [20+ tool files]
│   └── meta/
│
├── campaigns/                     # 📞 Campaign Domain (extract from ai/)
│   ├── __init__.py
│   ├── campaign_executor.py
│   ├── campaign_models.py
│   ├── campaign_router.py
│   ├── campaign_service.py
│   └── campaign_worker.py
│
├── entities/                      # 📦 Entity Management (extract from ai/)
│   ├── __init__.py
│   ├── service.py                 # Entity CRUD (from ai/service.py)
│   ├── router.py                  # Entity API routes (from ai/router.py)
│   ├── models.py                  # ORM models (from ai/models.py)
│   ├── schemas.py                 # Pydantic schemas (from ai/schemas.py)
│   ├── clone_helpers.py           # Entity cloning (from ai/entity_clone_helpers.py)
│   └── persona_service.py        # Persona management (from ai/persona_service.py)
│
├── documents/                     # 📄 Document Processing
│   ├── __init__.py
│   ├── artifact_models.py
│   ├── artifact_router.py
│   ├── artifact_service.py
│   ├── text_extractor.py
│   └── reports/
│       ├── reports_router.py
│       └── reports_service.py
│
├── shared/                        # 🔗 Shared Utilities
│   ├── __init__.py
│   ├── constants.py               # All constants (from ai/constants.py)
│   ├── json_utils.py              # NEW: JSON parsing helpers (deduplicated)
│   ├── tool_executor.py           # ToolExecutor (from ai/tool_executor.py)
│   └── usage_service.py           # UsageService (from ai/usage_service.py)
│
└── integrations/                  # 🔌 External Integrations
    ├── __init__.py
    ├── email/
    │   ├── email_models.py
    │   └── email_router.py
    └── social/
        ├── social_models.py
        ├── social_router.py
        └── social_connection_service.py
```

---

## 2. Migration Strategy: Backward-Compatible Shims

To avoid breaking all imports at once, `ai/__init__.py` will re-export everything:

```python
# ai/__init__.py — Backward compatibility shims (remove after 1 release cycle)

# Core
from ai.core.execution_engine import ExecutionEngine
from ai.core.step_executor import StepExecutorService
from ai.core.prompt_utils import parse_variables, build_sandwich_prompt
from ai.core.exceptions import UncertaintySignal

# Memory
from ai.memory.cortex_service import CortexRouter
from ai.memory.cortex_bridge import CortexBridge
from ai.memory.memory_service import MemoryRouter

# Planning
from ai.planning.planner_service import PlannerService
from ai.planning.goal_alignment import GoalAlignmentVerifier

# ... etc
```

Each original file location gets a stub:

```python
# ai/cortex_bridge.py (stub — backward compat)
import warnings
warnings.warn(
    "Import from ai.memory.cortex_bridge instead of ai.cortex_bridge",
    DeprecationWarning, stacklevel=2
)
from ai.memory.cortex_bridge import *  # noqa
```

---

## 3. Phase 10A: Structural Decomposition (Detail)

### Step 1: Create `ai/core/exceptions.py`

```python
# ai/core/exceptions.py

class AgentError(Exception):
    """Base exception for all agent-related errors."""
    pass

class UncertaintySignal(AgentError):
    """LLM signals it needs clarification before proceeding."""
    def __init__(self, question: str, confidence: float = 0.0, alternatives: list = None):
        super().__init__(question)
        self.question = question
        self.confidence = confidence
        self.alternatives = alternatives or []

class GoalDriftError(AgentError):
    """Step output misaligned with entity goal."""
    pass

class CreditExhaustedError(AgentError):
    """Execution stopped due to insufficient credits."""
    pass

class ParallelStepError(AgentError):
    """One or more parallel steps failed."""
    def __init__(self, failures: list):
        self.failures = failures
        super().__init__(f"{len(failures)} parallel step(s) failed")

class MetaAgentAbort(AgentError):
    """Meta-agent recommended aborting execution."""
    pass
```

### Step 2: Create `ai/core/prompt_utils.py`

Move from `worker.py`:
- `parse_variables` (lines 141–184)
- `build_sandwich_prompt` (lines 187–290)
- `filter_context_for_step` (lines 293–353)

### Step 3: Create `ai/core/context_utils.py`

Move from `worker.py`:
- `_store_step_output` (lines 79–98)
- `_sanitize_context_for_persistence` (lines 369–379)

### Step 4: Extract `ExecutionEngine` → `ai/core/execution_engine.py`

Move the class (lines 384–1307) with these changes:
- Import from `ai.core.prompt_utils` instead of local functions
- Import from `ai.core.exceptions` instead of local class
- **Remove all 12 pass-through delegation methods** — callers use composed services directly

### Step 5: Extract arq jobs → `ai/core/arq_jobs.py`

Move lines 1310–1877 (event handlers, arq job functions).

### Step 6: Slim `worker.py` to ~80 lines

```python
# worker.py — Arq worker entrypoint (post-refactor)
from arq.connections import RedisSettings
from ai.core.arq_jobs import (
    run_execution_recursive,
    process_gateway_event,
    process_document,
    execute_campaign_task,
    pause_campaign_task,
    stop_campaign_task,
    resume_execution,
)

class WorkerSettings:
    functions = [
        run_execution_recursive,
        process_gateway_event,
        process_document,
        execute_campaign_task,
        pause_campaign_task,
        stop_campaign_task,
        resume_execution,
    ]
    job_timeout = 7200
    # ... Redis settings ...
```

---

## 4. Phase 10B: LLM Router Deduplication

### Problem: REACT Loop Copy-Paste

All three adapters implement nearly identical `generate_with_tools_react()` methods:

```
GeminiAdapter.generate_with_tools_react     → Lines 348–455  (108 lines)
AnthropicAdapter.generate_with_tools_react  → Lines 572–657  (86 lines)
AzureOpenAIAdapter.generate_with_tools_react → Lines 785–900 (116 lines)
```

### Solution: Extract shared REACT loop to `BaseLLMAdapter`

```python
# ai/llm/react_loop.py

async def execute_react_loop(
    adapter: BaseLLMAdapter,
    system_prompt: str,
    initial_messages: list,
    tool_schemas: list,
    execute_tool_fn,
    max_turns: int = 10,
    **kwargs,
) -> LLMResponse:
    """Provider-agnostic REACT loop.
    
    Each adapter only needs to implement:
    - generate() for single-turn
    - _build_tool_result_message() for provider-specific tool result formatting
    """
    total_prompt = total_completion = total_latency = 0
    combined_output = ""
    all_function_calls = []
    messages = adapter.prepare_messages(system_prompt, initial_messages)
    
    for turn in range(max_turns):
        response = await adapter.generate(
            system_prompt, messages, tools=tool_schemas, **kwargs
        )
        total_prompt += response.prompt_tokens
        total_completion += response.completion_tokens
        total_latency += response.latency_ms
        
        if response.function_calls:
            all_function_calls.extend(response.function_calls)
            tool_results = await execute_tool_fn(response.function_calls)
            messages = adapter.append_tool_results(messages, response, tool_results)
            combined_output += response.output
            continue
        else:
            combined_output += response.output
            break
    
    return LLMResponse(
        output=combined_output,
        function_calls=all_function_calls,
        prompt_tokens=total_prompt,
        completion_tokens=total_completion,
        latency_ms=total_latency,
        model_name=adapter.model_name,
        provider=adapter._provider_name,
    )
```

---

## 5. Phase 10C: Memory System Consolidation

### Current State: Two Retrieval Paths

```python
# Path A (active in execute_run):
memory_router = MemoryRouter(self.db)
memory_ctx = await memory_router.retrieve(entity_id, user_id, tree_id, long_running=True)

# Path B (not integrated):
assembler = MemoryAssemblyService(db, company_id)
result = await assembler.assemble_runtime_memory(entity_id, task_description=task_desc)
```

### Consolidation Plan

1. **Feature flag:** Add `memory_pipeline` to entity capabilities:
   ```json
   {"memory": {"memory_pipeline": "v2"}}  // "v1" = MemoryRouter, "v2" = MemoryAssemblyService
   ```

2. **Unified interface:**
   ```python
   # ai/memory/__init__.py
   async def assemble_memory(db, company_id, entity_id, **kwargs) -> MemoryContext:
       entity = await get_entity(db, entity_id)
       pipeline = (entity.capabilities or {}).get("memory", {}).get("memory_pipeline", "v1")
       if pipeline == "v2":
           svc = MemoryAssemblyService(db, company_id)
           return await svc.assemble_runtime_memory(entity_id, **kwargs)
       else:
           router = MemoryRouter(db)
           return await router.retrieve(entity_id, **kwargs)
   ```

3. **Deprecation timeline:** v1 (`MemoryRouter`) deprecated in Phase 11, removed in Phase 12.

---

## 6. Phase 10D: Shared Utility Extraction

### JSON Parsing Helpers

Currently duplicated in `dreaming_engine.py`, `goal_alignment.py`, and pattern used in `planner_service.py`:

```python
# ai/shared/json_utils.py

import json
import re
from typing import Any, Dict, List, Optional

def parse_json_array(text: str) -> List[Dict]:
    """Parse JSON array from LLM output, handling markdown fences."""
    text = strip_markdown_fences(text)
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return []

def parse_json_object(text: str) -> Optional[Dict]:
    """Parse JSON object from LLM output, handling markdown fences."""
    text = strip_markdown_fences(text)
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None

def strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` fences from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = -1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[1:end])
    return text
```

---

## 7. Migration Execution Checklist

### Phase 10A (Structural Decomposition)
- [ ] Create `ai/core/` package with `__init__.py`
- [ ] Create `ai/core/exceptions.py` — move `UncertaintySignal`, add error taxonomy
- [ ] Create `ai/core/prompt_utils.py` — move 3 helper functions
- [ ] Create `ai/core/context_utils.py` — move 2 helper functions
- [ ] Move `GoalNode` to `ai/schemas.py`
- [ ] Extract `ExecutionEngine` → `ai/core/execution_engine.py`
- [ ] Extract arq jobs → `ai/core/arq_jobs.py`
- [ ] Slim `worker.py` to ~80 lines
- [ ] Update all imports across codebase
- [ ] Verify arq worker starts and processes jobs

### Phase 10B (Domain Packages)
- [ ] Create `ai/memory/`, `ai/planning/`, `ai/governance/`, `ai/llm/`
- [ ] Move files to domain packages
- [ ] Add backward-compat shims in original locations
- [ ] Extract LLM adapters to `ai/llm/adapters/`
- [ ] Deduplicate REACT loop
- [ ] Create `ai/shared/json_utils.py`

### Phase 10C (Memory Consolidation)
- [ ] Add `memory_pipeline` feature flag
- [ ] Wire `MemoryAssemblyService` into `execute_run` behind flag
- [ ] Deprecate `MemoryRouter` with warning
- [ ] Validate 4-domain assembly produces equivalent or better context

### Phase 10D (Autonomous Reasoning)
- [ ] Production-ize `RecursiveReasoningEngine` (depth limit, cost tracking, CORTEX)
- [ ] Add Meta-Agent review hooks to execution loop
- [ ] Implement `GoalGuard` middleware
- [ ] Add error taxonomy to all step handlers

---

> **Next:** See [05_memory_architecture.md](./05_memory_architecture.md) for the CORTEX and memory system deep-dive.
