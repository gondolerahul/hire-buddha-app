# Phase 10B — Domain-Driven Restructuring: Implementation Plan

> **Prerequisite:** Phase 10A (structural decomposition) complete  
> **Estimated Effort:** 4–5 days  
> **Risk Level:** Medium  
> **Goal:** Reorganize flat `ai/` into domain packages. Deduplicate LLM REACT loops. Create shared utilities.

---

## Step 1: Create Domain Packages

```bash
mkdir -p backend/src/ai/memory
mkdir -p backend/src/ai/planning
mkdir -p backend/src/ai/governance
mkdir -p backend/src/ai/llm
mkdir -p backend/src/ai/llm/adapters
mkdir -p backend/src/ai/shared
```

---

## Step 2: Memory Package — `ai/memory/`

### 2.1 Files to Move

| Source | Target | Size |
|--------|--------|------|
| `ai/cortex_service.py` | `ai/memory/cortex_service.py` | 42 KB |
| `ai/cortex_bridge.py` | `ai/memory/cortex_bridge.py` | 26 KB |
| `ai/cortex_models.py` | `ai/memory/cortex_models.py` | 16 KB |
| `ai/cortex_ingestion.py` | `ai/memory/cortex_ingestion.py` | 8 KB |
| `ai/memory_service.py` | `ai/memory/memory_service.py` | 18 KB |
| `ai/memory_assembly_service.py` | `ai/memory/memory_assembly.py` | 12 KB |
| `ai/episodic_tree_service.py` | `ai/memory/episodic_tree_service.py` | 17 KB |
| `ai/experience_tree_service.py` | `ai/memory/experience_tree_service.py` | 9 KB |
| `ai/intelligence_tree_service.py` | `ai/memory/intelligence_tree_service.py` | 10 KB |
| `ai/knowledge_tree_service.py` | `ai/memory/knowledge_tree_service.py` | 18 KB |
| `ai/embedding_service.py` | `ai/memory/embedding_service.py` | 11 KB |
| `ai/graph_service.py` | `ai/memory/graph_service.py` | 14 KB |
| `ai/dreaming_engine.py` | `ai/memory/dreaming_engine.py` | 22 KB |
| `ai/dreaming_prompts.py` | `ai/memory/dreaming_prompts.py` | 2 KB |

### 2.2 `ai/memory/__init__.py`

```python
"""
ai.memory — CORTEX memory system and all memory domain services.

Domains:
  - Knowledge: Persistent reference KB (documents, ingested content)
  - Experience: Observations and patterns learned from execution
  - Intelligence: Distilled rules, strategies, and preferences
  - Episodic: Raw execution history per entity
"""
from src.ai.memory.cortex_service import CortexRouter
from src.ai.memory.cortex_bridge import CortexBridge
from src.ai.memory.memory_service import MemoryRouter
from src.ai.memory.memory_assembly import MemoryAssemblyService

__all__ = ["CortexRouter", "CortexBridge", "MemoryRouter", "MemoryAssemblyService"]
```

### 2.3 Backward-Compatibility Stubs (original locations)

For each moved file, create a stub at the original location:

**Example: `ai/cortex_bridge.py` (stub)**
```python
"""Backward-compat stub. Import from ai.memory.cortex_bridge instead."""
import warnings
warnings.warn(
    "Import from src.ai.memory.cortex_bridge instead of src.ai.cortex_bridge. "
    "This shim will be removed in Phase 12.",
    DeprecationWarning, stacklevel=2,
)
from src.ai.memory.cortex_bridge import *  # noqa: F401,F403
```

Repeat for all 14 files. Each stub is 6 lines.

### 2.4 Internal import updates

All cross-references within the memory package must update:

| File | Old Import | New Import |
|------|-----------|-----------|
| `cortex_bridge.py` | `from src.ai.cortex_service import CortexRouter` | `from src.ai.memory.cortex_service import CortexRouter` |
| `dreaming_engine.py` | `from src.ai.cortex_models import ...` | `from src.ai.memory.cortex_models import ...` |
| `dreaming_engine.py` | `from src.ai.episodic_tree_service import ...` | `from src.ai.memory.episodic_tree_service import ...` |
| `dreaming_engine.py` | `from src.ai.experience_tree_service import ...` | `from src.ai.memory.experience_tree_service import ...` |
| `dreaming_engine.py` | `from src.ai.intelligence_tree_service import ...` | `from src.ai.memory.intelligence_tree_service import ...` |
| `dreaming_engine.py` | `from src.ai.embedding_service import ...` | `from src.ai.memory.embedding_service import ...` |
| `memory_assembly.py` | `from src.ai.graph_service import ...` | `from src.ai.memory.graph_service import ...` |
| `memory_assembly.py` | `from src.ai.intelligence_tree_service import ...` | `from src.ai.memory.intelligence_tree_service import ...` |
| `memory_assembly.py` | `from src.ai.episodic_tree_service import ...` | `from src.ai.memory.episodic_tree_service import ...` |

### 2.5 External consumer updates (via stubs — no action needed)

`ai/core/execution_engine.py` imports `CortexBridge`, `MemoryRouter`, `CortexService` — these will resolve via the backward-compat stubs until explicitly updated.

---

## Step 3: Planning Package — `ai/planning/`

### 3.1 Files to Move

| Source | Target |
|--------|--------|
| `ai/planner_service.py` | `ai/planning/planner_service.py` |
| `ai/goal_alignment.py` | `ai/planning/goal_alignment.py` |

### 3.2 `ai/planning/__init__.py`

```python
"""
ai.planning — Plan generation, reconciliation, and goal management.
"""
from src.ai.planning.planner_service import PlannerService
from src.ai.planning.goal_alignment import GoalAlignmentVerifier

__all__ = ["PlannerService", "GoalAlignmentVerifier"]
```

### 3.3 Backward-compat stubs at original locations (same pattern as Step 2.3)

---

## Step 4: Governance Package — `ai/governance/`

### 4.1 Files to Move

| Source | Target |
|--------|--------|
| `ai/governance_service.py` | `ai/governance/governance_service.py` |
| `ai/rate_limiter.py` | `ai/governance/rate_limiter.py` |

### 4.2 `ai/governance/__init__.py`

```python
"""
ai.governance — Billing, credit gating, HITL approvals, and safety guardrails.
"""
from src.ai.governance.governance_service import GovernanceService

__all__ = ["GovernanceService"]
```

---

## Step 5: LLM Package — `ai/llm/`

### 5.1 Split `llm_router.py` (1,052 lines) into 5 files

| Target File | Source Lines | Content |
|-------------|-------------|---------|
| `ai/llm/__init__.py` | — | Re-exports |
| `ai/llm/router.py` | Lines 1–31, ~900–1052 | `LLMRouter` class (routing logic) |
| `ai/llm/response.py` | Lines 77–89 | `LLMResponse` dataclass |
| `ai/llm/adapters/base.py` | Lines 95–138 | `BaseLLMAdapter` ABC |
| `ai/llm/adapters/gemini.py` | Lines 145–455 | `GeminiAdapter` + SDK patch |
| `ai/llm/adapters/anthropic.py` | Lines 462–657 | `AnthropicAdapter` |
| `ai/llm/adapters/azure_openai.py` | Lines 664–end | `AzureOpenAIAdapter` |

### 5.2 REACT Loop Deduplication

Create `ai/llm/react_loop.py` with shared logic:

```python
"""
ai.llm.react_loop — Provider-agnostic REACT tool-use loop.

Extracts the duplicated generate→tool_call→result loop that was
copy-pasted across GeminiAdapter, AnthropicAdapter, and AzureOpenAIAdapter.
"""
import logging
import time
from typing import Any, Dict, List, Optional

from src.ai.llm.response import LLMResponse

logger = logging.getLogger(__name__)


async def execute_react_loop(
    adapter,  # BaseLLMAdapter instance
    system_prompt: str,
    initial_messages: List[Dict[str, Any]],
    tool_schemas: List[Dict[str, Any]],
    execute_tool_fn,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    max_react_turns: int = 10,
    **kwargs,
) -> LLMResponse:
    """Execute multi-turn REACT loop using any adapter.

    Each adapter must implement:
      - generate() for single-turn LLM call
      - append_tool_results(messages, response, tool_results) for provider-specific formatting
    """
    total_prompt = 0
    total_completion = 0
    total_latency = 0
    combined_output = ""
    all_function_calls = []
    messages = list(initial_messages)

    for turn in range(max_react_turns):
        response = await adapter.generate(
            system_prompt, messages,
            tools=tool_schemas,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        total_prompt += response.prompt_tokens
        total_completion += response.completion_tokens
        total_latency += response.latency_ms

        if response.function_calls:
            all_function_calls.extend(response.function_calls)
            tool_results = await execute_tool_fn(response.function_calls)
            # Each adapter formats tool results differently
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

Each adapter then implements `generate_with_tools_react` as:

```python
async def generate_with_tools_react(self, system_prompt, initial_messages, tool_schemas, execute_tool_fn, **kwargs):
    from src.ai.llm.react_loop import execute_react_loop
    return await execute_react_loop(self, system_prompt, initial_messages, tool_schemas, execute_tool_fn, **kwargs)
```

And adds an `append_tool_results()` method for provider-specific formatting:

```python
# GeminiAdapter
def append_tool_results(self, messages, response, tool_results):
    from google.genai import types
    # ... Gemini-specific Part.from_function_response formatting
    return messages

# AnthropicAdapter  
def append_tool_results(self, messages, response, tool_results):
    # ... Anthropic-specific tool_result block formatting
    return messages
```

### 5.3 `ai/llm/__init__.py`

```python
"""
ai.llm — LLM abstraction layer with provider-agnostic routing.
"""
from src.ai.llm.router import LLMRouter
from src.ai.llm.response import LLMResponse

__all__ = ["LLMRouter", "LLMResponse"]
```

---

## Step 6: Shared Utilities — `ai/shared/`

### 6.1 Create `ai/shared/json_utils.py`

Deduplicate JSON parsing from `dreaming_engine.py` (lines 510–551), `goal_alignment.py` (lines 121–155):

```python
"""
ai.shared.json_utils — Shared JSON parsing utilities for LLM output.
"""
import json
import re
from typing import Any, Dict, List, Optional

import logging
logger = logging.getLogger(__name__)


def strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` fences from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = -1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[1:end])
    return text.strip()


def parse_json_array(text: str, warn_label: str = "LLM output") -> List[Dict]:
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
    logger.warning(f"Failed to parse JSON array from {warn_label}: {text[:200]}")
    return []


def parse_json_object(text: str, warn_label: str = "LLM output") -> Optional[Dict]:
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
    logger.warning(f"Failed to parse JSON object from {warn_label}: {text[:200]}")
    return None
```

### 6.2 Update consumers to use shared utilities

| File | Old | New |
|------|-----|-----|
| `dreaming_engine.py` | `self._parse_json_array()` (lines 510–531) | `from src.ai.shared.json_utils import parse_json_array` |
| `dreaming_engine.py` | `self._parse_json_object()` (lines 533–552) | `from src.ai.shared.json_utils import parse_json_object` |
| `goal_alignment.py` | `self._parse_response()` JSON extraction (lines 130–135) | `from src.ai.shared.json_utils import parse_json_object` |

### 6.3 Move remaining shared files

| Source | Target |
|--------|--------|
| `ai/constants.py` | `ai/shared/constants.py` |
| `ai/tool_executor.py` | `ai/shared/tool_executor.py` |
| `ai/usage_service.py` | `ai/shared/usage_service.py` |
| `ai/tool_fallback.py` | `ai/shared/tool_fallback.py` |

---

## Step 7: DreamingEngine DI Cleanup

Fix the triple `LLMRouter` instantiation in `dreaming_engine.py`:

**Before** (lines 152–154, 245–247, 336–338):
```python
from src.ai.llm_router import LLMRouter
llm = LLMRouter(db=self.db, company_id=self.company_id)
```

**After:**
```python
class DreamingEngine:
    def __init__(self, db, company_id, llm_router=None):
        self.db = db
        self.company_id = company_id
        self._llm = llm_router  # Lazy init

    @property
    def llm(self):
        if self._llm is None:
            from src.ai.llm.router import LLMRouter
            self._llm = LLMRouter(db=self.db, company_id=self.company_id)
        return self._llm
```

Then replace all 3 usages with `self.llm`.

---

## Validation Checklist (Phase 10B Complete)

- [ ] All 14 memory files exist in `ai/memory/` and import correctly
- [ ] All 2 planning files exist in `ai/planning/`
- [ ] All 2 governance files exist in `ai/governance/`
- [ ] LLM router split into `ai/llm/router.py` + 3 adapter files
- [ ] `ai/shared/json_utils.py` created and used by `dreaming_engine.py`, `goal_alignment.py`
- [ ] All 18+ backward-compat stubs exist at original file locations
- [ ] `python -c "from src.ai.memory import CortexBridge, MemoryRouter"`
- [ ] `python -c "from src.ai.planning import PlannerService"`
- [ ] `python -c "from src.ai.llm import LLMRouter, LLMResponse"`
- [ ] `python -c "from src.ai.cortex_bridge import CortexBridge"` ← backward compat stub works
- [ ] `python -m arq src.ai.worker.WorkerSettings` starts without errors
- [ ] Trigger test entity execution → verify COMPLETED status

---

> **Next:** [impl_10C_memory_consolidation.md](./impl_10C_memory_consolidation.md)
