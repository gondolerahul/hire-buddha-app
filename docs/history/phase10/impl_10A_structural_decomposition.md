# Phase 10A — Structural Decomposition: Implementation Plan

> **Prerequisite:** None (first phase)  
> **Estimated Effort:** 5–6 days  
> **Risk Level:** Medium  
> **Goal:** Decompose `worker.py` from 1,992 lines to ~80 lines. Break circular imports.

---

## Step 1: Create `ai/core/` Package

### 1.1 Create directory and `__init__.py`

```bash
mkdir -p backend/src/ai/core
touch backend/src/ai/core/__init__.py
```

### 1.2 `ai/core/__init__.py` content

```python
"""
ai.core — Orchestration and execution layer.

Contains the ExecutionEngine, step execution, prompt utilities,
and exception hierarchy. This is the "brain" of the agentic system.
"""
```

---

## Step 2: Create `ai/core/exceptions.py`

### Source: `worker.py` lines 59–76 (`UncertaintySignal`)

### Target: `ai/core/exceptions.py`

```python
"""
ai.core.exceptions — Unified error taxonomy for the AI engine.

All agent-specific exceptions inherit from AgentError.
"""

class AgentError(Exception):
    """Base exception for all agent-related errors."""
    pass


class UncertaintySignal(AgentError):
    """
    Raised when the LLM explicitly signals it needs clarification.

    The LLM must include the following JSON block in its response:
        {"needs_clarification": true, "question": "...", "confidence": 0.3}

    Attributes:
        question:     The clarifying question the agent wants to ask.
        confidence:   Estimated confidence in completing without input (0–1).
        alternatives: Optional list of alternative interpretations.
    """
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
        msgs = [f"{sid}: {err}" for sid, err in failures]
        super().__init__(f"{len(failures)} parallel step(s) failed: {'; '.join(msgs)}")


class MetaAgentAbort(AgentError):
    """Meta-agent recommended aborting execution."""
    pass


class StepTimeoutError(AgentError):
    """Step exceeded its configured timeout."""
    def __init__(self, step_name: str, timeout_ms: int):
        self.step_name = step_name
        self.timeout_ms = timeout_ms
        super().__init__(f"Step '{step_name}' exceeded {timeout_ms}ms timeout")
```

### Validation:
```bash
python -c "from src.ai.core.exceptions import UncertaintySignal, AgentError, GoalDriftError"
```

---

## Step 3: Create `ai/core/prompt_utils.py`

### Source: `worker.py` lines 139–353

### Target: `ai/core/prompt_utils.py`

Copy these three functions verbatim:

1. **`parse_variables(text, variables)`** — lines 141–184
2. **`build_sandwich_prompt(...)`** — lines 187–290
3. **`filter_context_for_step(step, full_context, context_policy)`** — lines 293–353

### Required imports for the new module:

```python
"""
ai.core.prompt_utils — Prompt construction and variable resolution.

Extracted from worker.py during Phase 10A to break circular imports
and enable independent reuse.
"""
import json
import re
from typing import Dict, List, Optional

from src.ai.schemas import PlanStep
```

### Post-extraction updates:

| File | Change |
|------|--------|
| `worker.py` | Replace function bodies with: `from src.ai.core.prompt_utils import parse_variables, build_sandwich_prompt, filter_context_for_step` |
| `step_executor.py` | Update lazy import (lines 36–41) to import from `ai.core.prompt_utils` directly |
| `cortex_bridge.py` | Update `_parse_variables` wrapper (line 25) to import from `ai.core.prompt_utils` |

### Critical fix — breaking the circular import:

**Before** (`step_executor.py` lines 34–51):
```python
# Lazy imports to avoid circular dependencies with worker.py
def _get_worker_helpers():
    from src.ai.worker import (
        parse_variables, build_sandwich_prompt,
        filter_context_for_step, UncertaintySignal,
        DEFAULT_REVIEW_PROMPT,
    )
    return parse_variables, build_sandwich_prompt, filter_context_for_step, UncertaintySignal, DEFAULT_REVIEW_PROMPT
```

**After:**
```python
# Direct imports — no circular dependency after Phase 10A extraction
from src.ai.core.prompt_utils import parse_variables, build_sandwich_prompt, filter_context_for_step
from src.ai.core.exceptions import UncertaintySignal
from src.ai.schemas import DEFAULT_REVIEW_SYSTEM_PROMPT as DEFAULT_REVIEW_PROMPT
```

This **eliminates the entire lazy-import hack** (lines 34–67 of `step_executor.py`).

**Before** (`cortex_bridge.py` lines 23–26):
```python
def _parse_variables(text: str, variables: dict) -> str:
    """Import-free forward ref to worker.parse_variables (avoid circular)."""
    from src.ai.worker import parse_variables
    return parse_variables(text, variables)
```

**After:**
```python
from src.ai.core.prompt_utils import parse_variables as _parse_variables
```

### Validation:
```bash
python -c "from src.ai.core.prompt_utils import parse_variables, build_sandwich_prompt, filter_context_for_step"
python -c "from src.ai.step_executor import StepExecutorService"  # no lazy import needed
python -c "from src.ai.cortex_bridge import CortexBridge"  # no lazy import needed
```

---

## Step 4: Create `ai/core/context_utils.py`

### Source: `worker.py` lines 79–98, 362–379

### Target: `ai/core/context_utils.py`

```python
"""
ai.core.context_utils — Context state management utilities.

Handles step output storage, context sanitization for persistence,
and internal key management.
"""
from typing import Optional
from src.ai.constants import INTERNAL_CONTEXT_KEYS


# SEC-1: Keys to strip before persisting context to DB
_SENSITIVE_CONTEXT_KEYS = frozenset({
    "api_key", "api_secret", "secret", "token", "password",
    "auth", "authorization", "credential", "credentials",
    "__model_override",
})


def store_step_output(
    context_state: dict,
    step_name: str,
    step_id: str,
    output: str,
    cortex_bridge=None,
) -> None:
    """Store step output in context.

    Full output is preserved to ensure inter-step data integrity.
    Context growth for LLM prompt construction is managed separately
    by _maybe_summarize_context().
    """
    value = output
    old_value = context_state.get(step_name, "")
    context_state[step_name] = value
    if cortex_bridge:
        cortex_bridge.update_context_size(step_name, old_value, value)
    if step_id and step_id != step_name:
        old_id_value = context_state.get(step_id, "")
        context_state[step_id] = value
        if cortex_bridge:
            cortex_bridge.update_context_size(step_id, old_id_value, value)


def sanitize_context_for_persistence(ctx: dict) -> dict:
    """Return a shallow copy of ctx with sensitive keys redacted."""
    if not ctx:
        return ctx
    sanitized = {}
    for k, v in ctx.items():
        key_lower = k.lower()
        if any(sk in key_lower for sk in _SENSITIVE_CONTEXT_KEYS):
            continue
        sanitized[k] = v
    return sanitized
```

### Post-extraction updates:

| File | Change |
|------|--------|
| `worker.py` | Replace `_store_step_output` and `_sanitize_context_for_persistence` with imports from `ai.core.context_utils` |
| All call sites of `_store_step_output` in `worker.py` | Update to `store_step_output` (drop leading underscore) |

---

## Step 5: Move `GoalNode` to `ai/schemas.py`

### Source: `worker.py` lines 100–137

### Target: Append to `ai/schemas.py`

```python
# --- Phase 10A: GoalNode for RecursiveReasoningEngine ---

@dataclass
class GoalNode:
    """
    A single node in the goal decomposition tree.

    Used by RecursiveReasoningEngine for autonomous goal breakdown.
    """
    goal: str
    depth: int = 0
    confidence: float = 1.0
    parent: Optional['GoalNode'] = field(default=None, repr=False)
    children: List['GoalNode'] = field(default_factory=list)
    result: Optional[str] = None
    status: str = 'pending'

    def is_leaf(self) -> bool:
        return len(self.children) == 0

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "depth": self.depth,
            "confidence": self.confidence,
            "status": self.status,
            "result": self.result,
            "children": [c.to_dict() for c in self.children],
        }
```

Add `from dataclasses import dataclass, field` to `schemas.py` imports if not already present.

### Post-extraction:
- In `worker.py`, replace the `GoalNode` class with `from src.ai.schemas import GoalNode`.
- `RecursiveReasoningEngine` (line 1935) already references `GoalNode` — import will resolve.

---

## Step 6: Extract `ExecutionEngine` → `ai/core/execution_engine.py`

### Source: `worker.py` lines 384–1307

### Target: `ai/core/execution_engine.py`

### 6.1 Required imports for the new module:

```python
"""
ai.core.execution_engine — Central orchestrator for entity execution.

Manages the full lifecycle: initialization → credit gate → CORTEX setup →
plan reconciliation → step execution → finalization → billing.
"""
import asyncio
import copy
import json
import logging
import re
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from src.common.database import AsyncSessionLocal
from src.ai.models import ExecutionRun, HierarchicalEntity, RunStatus
from src.ai.schemas import PlanStep, StepType, GoalNode
from src.ai.constants import INTERNAL_CONTEXT_KEYS
from src.ai.core.exceptions import UncertaintySignal
from src.ai.core.prompt_utils import parse_variables
from src.ai.core.context_utils import store_step_output, sanitize_context_for_persistence

from src.config.service import ConfigService
from src.ai.usage_service import UsageService
from src.ai.governance_service import GovernanceService
from src.ai.planner_service import PlannerService
from src.ai.cortex_bridge import CortexBridge
from src.ai.step_executor import StepExecutorService
from src.ai.cortex_service import CortexRouter as CortexService
from src.ai.cortex_models import CortexNodeType
from src.ai.memory_service import MemoryRouter

logger = logging.getLogger(__name__)
```

### 6.2 Remove pass-through delegation methods

Delete these 12 methods from the extracted `ExecutionEngine`. Instead, the code that calls them should directly call the composed service:

| Method to Remove | Call sites that need updating |
|-----------------|------------------------------|
| `_execute_step` (line 1277) | `_execute_step_wrapper` calls this → change to `self._step_executor._execute_step(...)` |
| `_execute_child_invocation` (1281) | Only called via `_execute_step` router — handled by StepExecutorService |
| `_execute_tool_call` (1285) | Same as above |
| `_execute_thought` (1289) | Same as above |
| `_log_usage` (1293) | Not called from ExecutionEngine directly |
| `_maybe_summarize_context` (1297) | Not called from ExecutionEngine directly |
| `_review_step_output` (1301) | Called in `_execute_step_wrapper` → `self._step_executor._review_step_output(...)` |
| `_should_exit` (1305) | Called in sequential loop → `self._step_executor._should_exit(...)` |
| `_build_task_description` (1222) | Called once → `self._cortex_bridge.build_task_description(...)` |
| `_write_step_to_cortex` (1226) | Called in loop → `self._cortex_bridge.write_step(...)` |
| `_ingest_tool_result_to_cortex` (1236) | Not called from ExecutionEngine |
| `_execute_cortex_step` (1246) | Called in loop → `self._cortex_bridge.execute_cortex_step(...)` |

### 6.3 The `_has_parallel_steps` and `_get_reconciled_plan` methods

These delegate to `PlannerService` — replace with direct calls:
```python
# Before:
plan = await self._get_reconciled_plan(run, entity, context_state)
if self._has_parallel_steps(steps):

# After:
plan = await self._planner.reconcile(run, entity, context_state)
if self._planner.has_parallel_steps(steps):
```

### Validation:
```bash
python -c "from src.ai.core.execution_engine import ExecutionEngine"
```

---

## Step 7: Extract Arq Jobs → `ai/core/arq_jobs.py`

### Source: `worker.py` lines 1310–1877

### Target: `ai/core/arq_jobs.py`

### 7.1 Functions to move:

| Function | Lines | Notes |
|----------|-------|-------|
| `run_execution_recursive` | 1310–1321 | Import `ExecutionEngine` from `ai.core.execution_engine` |
| `process_gateway_event` | 1324–1440 | Same |
| `_handle_sheet_row_campaign` | 1443–1606 | Helper for `process_gateway_event` |
| `process_document` | 1609–1724 | Standalone |
| `dreaming_worker` | 1733–1757 | Standalone |
| `graph_maintenance_worker` | 1763–1794 | Standalone |
| `resume_execution` | 1799–1811 | Import `ExecutionEngine` |
| `cortex_resume_scheduled` | 1817–1873 | Standalone |

### 7.2 Import updates in `arq_jobs.py`:
```python
from src.ai.core.execution_engine import ExecutionEngine
```

### 7.3 The `import` chain in arq job functions

Each arq job creates its own `AsyncSessionLocal` and `ExecutionEngine`. The import of `ExecutionEngine` must come from the new location.

---

## Step 8: Extract `RecursiveReasoningEngine` → `ai/core/recursive_engine.py`

### Source: `worker.py` lines 1879–1951

### Target: `ai/core/recursive_engine.py`

```python
"""
ai.core.recursive_engine — Experimental goal decomposition engine.

Extends ExecutionEngine with recursive goal tree execution.
Phase 10D will promote this to production-ready status.
"""
from src.ai.core.execution_engine import ExecutionEngine
from src.ai.schemas import GoalNode, PlanStep
# ... rest of class
```

**Note:** The `__init__` bug (doesn't pass `company_id` to parent) should be fixed here:
```python
def __init__(self, db, redis_pool, company_id=None):
    super().__init__(db, redis_pool, company_id=company_id)  # Fix: pass company_id
```

---

## Step 9: Slim `worker.py` to ~80 Lines

### Final `worker.py` content:

```python
"""
worker.py — Arq worker entrypoint.

This file is intentionally minimal. All execution logic lives in:
  - ai.core.execution_engine (ExecutionEngine)
  - ai.core.arq_jobs (job functions)
  - ai.core.step_executor (StepExecutorService)

Only WorkerSettings and cron registration remain here because arq
requires them at module level for worker discovery.
"""
from arq.connections import RedisSettings
from src.ai.core.arq_jobs import (
    run_execution_recursive,
    process_gateway_event,
    process_document,
    dreaming_worker,
    graph_maintenance_worker,
    resume_execution,
    cortex_resume_scheduled,
)
from src.ai.campaign_worker import (
    execute_campaign_task,
    pause_campaign_task,
    stop_campaign_task,
)

# --- Backward compatibility re-exports ---
# These allow existing code to `from src.ai.worker import X` without breaking.
# Deprecated: import from src.ai.core.* directly.
from src.ai.core.execution_engine import ExecutionEngine  # noqa: F401
from src.ai.core.exceptions import UncertaintySignal  # noqa: F401
from src.ai.core.prompt_utils import parse_variables, build_sandwich_prompt, filter_context_for_step  # noqa: F401
from src.ai.core.context_utils import sanitize_context_for_persistence  # noqa: F401
from src.ai.core.context_utils import store_step_output as _store_step_output  # noqa: F401
from src.ai.schemas import GoalNode  # noqa: F401
from src.ai.schemas import DEFAULT_REVIEW_SYSTEM_PROMPT as DEFAULT_REVIEW_PROMPT  # noqa: F401


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
    cron_jobs = []

    job_timeout = 7200

    @staticmethod
    def _parse_redis_url():
        from src.common.config import settings
        from urllib.parse import urlparse
        parsed = urlparse(settings.REDIS_URL or "redis://localhost:6379")
        return parsed.hostname or "localhost", parsed.port or 6379

    _host, _port = _parse_redis_url.__func__()
    redis_settings = RedisSettings(host=_host, port=_port)


# Register cron jobs after class definition (arq pattern)
try:
    from arq.cron import cron
    WorkerSettings.cron_jobs = [
        cron(cortex_resume_scheduled, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
    ]
except ImportError:
    pass
```

---

## Step 10: Update External Consumers

### 10.1 `src/gateway/dispatcher.py` (line 270)

**Before:**
```python
from src.ai.worker import ExecutionEngine
```

**After (no change needed — backward compat shim handles it):**
The re-export in `worker.py` ensures this continues to work.
Optionally update to `from src.ai.core.execution_engine import ExecutionEngine` for clarity.

### 10.2 `step_executor.py` — Complete lazy-import removal

**Delete lines 34–67** (the entire lazy import hack) and replace with direct imports at the top of the file:

```python
from src.ai.core.prompt_utils import parse_variables, build_sandwich_prompt, filter_context_for_step
from src.ai.core.exceptions import UncertaintySignal
from src.ai.schemas import DEFAULT_REVIEW_SYSTEM_PROMPT as DEFAULT_REVIEW_PROMPT
```

---

## Validation Checklist (Phase 10A Complete)

- [ ] `python -c "from src.ai.core.exceptions import UncertaintySignal, AgentError"`
- [ ] `python -c "from src.ai.core.prompt_utils import parse_variables, build_sandwich_prompt"`
- [ ] `python -c "from src.ai.core.context_utils import store_step_output, sanitize_context_for_persistence"`
- [ ] `python -c "from src.ai.core.execution_engine import ExecutionEngine"`
- [ ] `python -c "from src.ai.core.arq_jobs import run_execution_recursive"`
- [ ] `python -c "from src.ai.worker import ExecutionEngine"` ← backward compat
- [ ] `python -c "from src.ai.step_executor import StepExecutorService"` ← no lazy import
- [ ] `python -c "from src.ai.cortex_bridge import CortexBridge"` ← no lazy import
- [ ] `python -m arq src.ai.worker.WorkerSettings` starts without errors
- [ ] Trigger test entity execution → verify COMPLETED status
- [ ] `wc -l backend/src/ai/worker.py` → should be ~80 lines

---

> **Next:** [impl_10B_domain_restructuring.md](./impl_10B_domain_restructuring.md)
