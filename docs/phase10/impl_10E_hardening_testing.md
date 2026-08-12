# Phase 10E — Hardening & Testing: Implementation Plan

> **Prerequisite:** Phase 10B and 10D complete  
> **Estimated Effort:** 3–4 days  
> **Risk Level:** Low  
> **Goal:** Error taxonomy, test scaffolding, observability, cleanup.

---

## Step 1: Error Taxonomy Enforcement

### 1.1 Replace raw `Exception` raises with typed exceptions

**Audit all `raise Exception(...)` in the AI package:**

| File | Line | Current | Replace With |
|------|------|---------|-------------|
| `step_executor.py:214` | `raise Exception(f"Child invocation missing entity_id")` | `raise AgentError(f"Child invocation missing entity_id for step {step.name}")` |
| `step_executor.py:233` | `raise Exception(f"Child entity {entity_id} not found")` | `raise AgentError(f"Child entity {entity_id} not found or deleted")` |
| `execution_engine.py` | Various `raise Exception(...)` | Replace with `AgentError` or more specific subclass |
| `cortex_bridge.py` | `raise Exception(f"CORTEX tree {tree.id} has no working memory root")` | `raise AgentError(f"CORTEX tree {tree_id} has no working memory root")` |

### 1.2 Extend the exception hierarchy (already created in 10A)

```python
# ai/core/exceptions.py — additions

class EntityNotFoundError(AgentError):
    """Referenced entity does not exist or has been deleted."""
    def __init__(self, entity_id, context: str = ""):
        self.entity_id = entity_id
        super().__init__(f"Entity {entity_id} not found. {context}")


class PlanningError(AgentError):
    """Plan generation or reconciliation failed."""
    pass


class CortexError(AgentError):
    """CORTEX memory operation failed."""
    pass


class ToolExecutionError(AgentError):
    """Tool execution failed."""
    def __init__(self, tool_name: str, error: str):
        self.tool_name = tool_name
        super().__init__(f"Tool '{tool_name}' failed: {error}")
```

### 1.3 Catch typed exceptions in `execute_run()`

The outer `except BaseException` in `execute_run()` should differentiate:

```python
except CreditExhaustedError as e:
    # Non-fatal for billing — mark as CREDIT_EXHAUSTED
    failed_run.status = RunStatus.FAILED
    failed_run.error_message = f"Credits exhausted: {e}"

except MetaAgentAbort as e:
    # Meta-Agent decided to abort
    failed_run.status = RunStatus.FAILED
    failed_run.error_message = f"Meta-Agent abort: {e}"

except AgentError as e:
    # Agent-level failure
    failed_run.status = RunStatus.FAILED
    failed_run.error_message = f"{type(e).__name__}: {str(e)[:500]}"

except BaseException as e:
    # Infrastructure failure (timeouts, cancellations)
    failed_run.status = RunStatus.FAILED
    failed_run.error_message = f"Infrastructure: {type(e).__name__}: {str(e)[:500]}"
```

---

## Step 2: Test Scaffolding

### 2.1 Create test directory structure

```bash
mkdir -p backend/tests/ai/core
mkdir -p backend/tests/ai/memory
mkdir -p backend/tests/ai/planning
mkdir -p backend/tests/ai/llm
touch backend/tests/__init__.py
touch backend/tests/ai/__init__.py
touch backend/tests/ai/core/__init__.py
touch backend/tests/ai/memory/__init__.py
touch backend/tests/ai/planning/__init__.py
touch backend/tests/ai/llm/__init__.py
```

### 2.2 Priority test files

#### `tests/ai/core/test_prompt_utils.py`

```python
"""Tests for prompt utility functions — zero LLM dependency."""
import pytest
from src.ai.core.prompt_utils import parse_variables, build_sandwich_prompt, filter_context_for_step
from src.ai.schemas import PlanStep, StepType


class TestParseVariables:
    def test_double_brace_replacement(self):
        result = parse_variables("Hello {{name}}", {"name": "World"})
        assert result == "Hello World"

    def test_single_brace_replacement(self):
        result = parse_variables("Hello {name}", {"name": "World"})
        assert result == "Hello World"

    def test_nested_variable_resolution(self):
        result = parse_variables("{{step_1.output}}", {"step_1": "result text"})
        assert result == "result text"

    def test_missing_variable_preserved(self):
        result = parse_variables("{{missing}}", {"other": "value"})
        assert result == "{{missing}}"

    def test_json_braces_not_replaced(self):
        result = parse_variables('{"key": "value"}', {"key": "replaced"})
        assert '"key": "value"' in result  # Should NOT replace JSON

    def test_empty_text(self):
        assert parse_variables("", {"x": "y"}) == ""

    def test_none_text(self):
        assert parse_variables(None, {"x": "y"}) == ""


class TestBuildSandwichPrompt:
    def test_minimal_prompt(self):
        result = build_sandwich_prompt(
            identity="I am an assistant",
            current_task="Do something",
        )
        assert "## Identity & Role" in result
        assert "## Current Task" in result
        assert "Do something" in result

    def test_all_layers_present(self):
        result = build_sandwich_prompt(
            identity="Test agent",
            goal="Achieve X",
            tools=[{"name": "search", "description": "Search the web"}],
            current_task="Find Y",
            output_schema={"properties": {"result": {"type": "string"}}},
        )
        assert "## Goal & Objective" in result
        assert "## Available Tools" in result
        assert "## Required Output Format" in result


class TestFilterContextForStep:
    def test_no_policy_returns_full(self):
        ctx = {"a": 1, "b": 2, "c": 3}
        step = PlanStep(name="test", type=StepType.THOUGHT)
        assert filter_context_for_step(step, ctx, None) == ctx

    def test_last_n_policy(self):
        ctx = {"a": 1, "b": 2, "c": 3, "d": 4}
        step = PlanStep(name="test", type=StepType.THOUGHT)
        result = filter_context_for_step(step, ctx, {"type": "LAST_N", "n": 2})
        assert "c" in result
        assert "d" in result
        assert "a" not in result
```

#### `tests/ai/core/test_context_utils.py`

```python
"""Tests for context state utilities."""
import pytest
from src.ai.core.context_utils import store_step_output, sanitize_context_for_persistence


class TestStoreStepOutput:
    def test_stores_by_name_and_id(self):
        ctx = {}
        store_step_output(ctx, "Research", "step_1", "findings text")
        assert ctx["Research"] == "findings text"
        assert ctx["step_1"] == "findings text"

    def test_same_name_and_id_no_duplicate(self):
        ctx = {}
        store_step_output(ctx, "step_1", "step_1", "output")
        assert ctx["step_1"] == "output"
        assert len(ctx) == 1


class TestSanitizeContext:
    def test_strips_sensitive_keys(self):
        ctx = {"input": "hello", "api_key": "secret123", "output": "world"}
        result = sanitize_context_for_persistence(ctx)
        assert "api_key" not in result
        assert result["input"] == "hello"
        assert result["output"] == "world"

    def test_empty_context(self):
        assert sanitize_context_for_persistence({}) == {}
        assert sanitize_context_for_persistence(None) is None

    def test_strips_model_override(self):
        ctx = {"__model_override": "gpt-4", "data": "value"}
        result = sanitize_context_for_persistence(ctx)
        assert "__model_override" not in result
```

#### `tests/ai/core/test_exceptions.py`

```python
"""Tests for the exception hierarchy."""
import pytest
from src.ai.core.exceptions import (
    AgentError, UncertaintySignal, GoalDriftError,
    ParallelStepError, StepTimeoutError,
)


class TestUncertaintySignal:
    def test_basic_creation(self):
        sig = UncertaintySignal("What do you mean?", confidence=0.3)
        assert sig.question == "What do you mean?"
        assert sig.confidence == 0.3
        assert sig.alternatives == []

    def test_is_agent_error(self):
        assert issubclass(UncertaintySignal, AgentError)


class TestParallelStepError:
    def test_formats_failures(self):
        err = ParallelStepError([("step_1", "timeout"), ("step_3", "crash")])
        assert "2 parallel step(s) failed" in str(err)
        assert err.failures == [("step_1", "timeout"), ("step_3", "crash")]
```

#### `tests/ai/planning/test_goal_guard.py`

```python
"""Tests for GoalGuard middleware."""
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestGoalGuard:
    @pytest.mark.asyncio
    async def test_continue_on_no_issues(self):
        """GoalGuard should return CONTINUE when step output is aligned."""
        from src.ai.planning.goal_guard import GoalGuard

        # Mock DB and services
        db = AsyncMock()
        guard = GoalGuard(
            db=db,
            company_id="00000000-0000-0000-0000-000000000001",
            entity_goal="Research AI",
            task_description="Find papers on AI",
        )

        result = await guard.check(
            step_result={"output": "Found 5 papers on AI"},
            step_name="Search",
            step_idx=0,
            all_results=[],
            total_steps=5,
        )
        # With mocked verifier, default is CONTINUE
        assert result["action"] == "CONTINUE"
```

### 2.3 Test runner configuration

Create `backend/pytest.ini`:

```ini
[pytest]
testpaths = tests
asyncio_mode = auto
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

Or add to existing `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

### 2.4 Running tests

```bash
cd backend
python -m pytest tests/ai/core/ -v
python -m pytest tests/ai/planning/ -v
```

---

## Step 3: Observability Improvements

### 3.1 Structured logging for execution phases

Add phase markers to `execute_run()`:

```python
# At each phase boundary:
logger.info(f"[RUN:{run.id}] Phase 1/7: Initialization complete")
logger.info(f"[RUN:{run.id}] Phase 2/7: Credit gate passed")
logger.info(f"[RUN:{run.id}] Phase 3/7: CORTEX tree {tree.id} ready")
logger.info(f"[RUN:{run.id}] Phase 4/7: {len(loaded_sources)} context sources loaded")
logger.info(f"[RUN:{run.id}] Phase 5/7: Plan reconciled ({len(steps)} steps)")
logger.info(f"[RUN:{run.id}] Phase 6/7: Step {step_idx+1}/{len(steps)} '{step_obj.name}' → {step_result.get('status', 'ok')}")
logger.info(f"[RUN:{run.id}] Phase 7/7: Finalized (cost=${run.total_cost_usd})")
```

### 3.2 Execution timing for each phase

```python
import time

_phase_start = time.monotonic()
# ... phase code ...
_phase_ms = int((time.monotonic() - _phase_start) * 1000)
logger.info(f"[RUN:{run.id}] Phase 3/7 completed in {_phase_ms}ms")
```

### 3.3 Add `__execution_metadata__` to context

```python
context_state["__execution_metadata__"] = {
    "engine_type": engine_type,  # "DAG" or "RECURSIVE"
    "memory_pipeline": memory_pipeline,  # "v1" or "v2"
    "memory_scope": _memory_scope,
    "total_steps": len(steps),
    "parallel_mode": self._planner.has_parallel_steps(steps),
    "autonomous": is_autonomous,
    "meta_review_enabled": meta_review_enabled,
}
```

This metadata is automatically stripped before persistence (it's in `INTERNAL_CONTEXT_KEYS`).

---

## Step 4: Deprecation Warnings

### 4.1 Add deprecation warnings to backward-compat stubs

Each stub file created in Phase 10B should emit a warning:

```python
import warnings
warnings.warn(
    "Direct import from src.ai.cortex_bridge is deprecated. "
    "Use src.ai.memory.cortex_bridge instead. "
    "This shim will be removed in Phase 12.",
    DeprecationWarning,
    stacklevel=2,
)
```

### 4.2 Add `INTERNAL_CONTEXT_KEYS` to include new keys

Update `constants.py` to add any new internal keys:

```python
INTERNAL_CONTEXT_KEYS = frozenset({
    # ... existing keys ...
    "__execution_metadata__",
    "__intelligence_rules__",
    "__subgoal_*",   # Pattern — handled via prefix check
})
```

---

## Step 5: Code Quality Cleanup

### 5.1 Remove dead code

| File | Dead Code | Action |
|------|-----------|--------|
| `worker.py` (post-slim) | All extracted functions/classes | Already removed in 10A |
| `step_executor.py` | Lazy import hack (lines 34–67) | Removed in 10A |
| `cortex_bridge.py` | `_parse_variables` wrapper (lines 23–26) | Removed in 10A |

### 5.2 Docstring audit

Ensure every public class and method in `ai/core/`, `ai/memory/`, `ai/planning/` has:
- One-line summary
- Args section (with types)
- Returns section
- Raises section (if applicable)

### 5.3 `__all__` exports in each package

Every `__init__.py` should have an explicit `__all__` list to prevent import pollution.

---

## Step 6: `CreditService` Routing Cleanup

### Location: `step_executor.py` line 28

**Before:**
```python
from src.billing.credit_service import CreditService, InsufficientCreditsError
```

The `step_executor.py` uses `CreditService` directly for pre-child-spawn credit checks (line 300).

**After:** Route through `GovernanceService`:

```python
# In StepExecutorService.__init__, accept governance:
def __init__(self, db, redis, company_id, usage_service, cortex_bridge=None, execute_run_fn=None, governance=None):
    ...
    self._governance = governance

# Replace direct CreditService usage (line 296-314):
if self._governance:
    await self._governance.check_credit_gate(run)
```

---

## Final Validation Checklist (Phase 10E Complete — Phase 10 Done)

### Import Resolution
- [ ] `python -c "from src.ai.core.exceptions import AgentError, UncertaintySignal, GoalDriftError, ParallelStepError"`
- [ ] `python -c "from src.ai.core.execution_engine import ExecutionEngine"`
- [ ] `python -c "from src.ai.core.recursive_engine import RecursiveReasoningEngine"`
- [ ] `python -c "from src.ai.core.meta_review import MetaReviewer"`
- [ ] `python -c "from src.ai.planning.goal_guard import GoalGuard"`
- [ ] `python -c "from src.ai.memory.assembler import assemble_memory"`
- [ ] `python -c "from src.ai.llm import LLMRouter"`
- [ ] `python -c "from src.ai.shared.json_utils import parse_json_array, parse_json_object"`

### Backward Compatibility
- [ ] `python -c "from src.ai.worker import ExecutionEngine"` (shim)
- [ ] `python -c "from src.ai.cortex_bridge import CortexBridge"` (shim)
- [ ] `python -c "from src.ai.memory_service import MemoryRouter"` (shim)
- [ ] `python -c "from src.ai.planner_service import PlannerService"` (shim)
- [ ] `python -c "from src.ai.llm_router import LLMRouter"` (shim)

### Worker Functionality
- [ ] `python -m arq src.ai.worker.WorkerSettings` starts without errors
- [ ] `wc -l backend/src/ai/worker.py` < 100 lines
- [ ] Trigger entity execution (SKILL type) → COMPLETED
- [ ] Trigger entity execution (PROCESS type with children) → COMPLETED
- [ ] Trigger entity execution (AGENT type with tools) → COMPLETED
- [ ] Deep Research pipeline executes end-to-end
- [ ] CORTEX tree created with correct structure

### Tests
- [ ] `python -m pytest tests/ai/core/ -v` — all pass
- [ ] `python -m pytest tests/ai/planning/ -v` — all pass

### Code Quality
- [ ] No raw `raise Exception(...)` in ai/core/, ai/memory/, ai/planning/
- [ ] All `__init__.py` files have `__all__` exports
- [ ] All public methods have docstrings
- [ ] Zero deprecation warnings from internal code (only from stubs)

---

## Summary: Phase 10 Complete File Manifest

| Phase | New Files | Modified Files | Deleted Files |
|-------|-----------|---------------|---------------|
| **10A** | 5 new (exceptions, prompt_utils, context_utils, execution_engine, arq_jobs) | 3 modified (worker.py, step_executor.py, cortex_bridge.py) | 0 |
| **10B** | 6 new (__init__.py files, json_utils.py, react_loop.py) + 18 stubs | 14+ import updates | 0 |
| **10C** | 2 new (assembler.py, text_utils.py) | 3 modified (execution_engine, cortex_bridge, episodic_tree_service) | 0 |
| **10D** | 3 new (recursive_engine rewrite, meta_review.py, goal_guard.py) | 1 modified (execution_engine loop) | 0 |
| **10E** | 5 new (test files, pytest config) | 3+ (exception upgrades, docstrings, cleanup) | 0 |
| **Total** | **~21 new files** | **~24 modified** | **0 deleted** |

---

> End of Phase 10 Implementation Plans. Return to [impl_00_overview.md](./impl_00_overview.md) for the master plan.
