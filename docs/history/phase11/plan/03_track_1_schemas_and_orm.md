# Track 1 — Schemas + ORM Split (Week 2)

> **Owner:** App platform engineer.
> **Duration:** 5 working days.
> **Behaviour change:** None — pure refactor with re-export shims.
> **Risk:** Medium. Touches every file in the agent kernel via imports.
> **Goal mapping:** G6 (layout), G1/G3/G4 (every later Track needs typed
>   primitives to land on).

---

## 1. Objectives (functional)

After Track 1:

1. `backend/src/ai/schemas.py` (970 LoC) is split into a `schemas/`
   package with one file per **bounded context** (entity, planning,
   reasoning, capabilities, governance, io_contract, execution, cortex,
   tools, prompts, enums).
2. `backend/src/ai/models.py` is split into an `orm/` package with one
   file per **ORM cluster** (entity, execution, document, memory,
   cortex, campaign, artifact, lead_queue, usage, email).
3. Every existing import (`from src.ai.schemas import ...`,
   `from src.ai.models import ...`) continues to work via a single
   wildcard re-export inside `schemas/__init__.py` and `orm/__init__.py`.
4. `PlanStep.type` becomes a typed `StepType` enum, not `Optional[str]`.
5. `HITLCheckpoint.trigger_type` becomes a typed `HITLTriggerType` enum,
   not a free-text string.
6. `planning/failure_tags.py` adds the new `FailureTag` enum (consumed
   by Track 3).
7. `mypy --strict` passes on every file in the new `schemas/` and `orm/`
   packages.

---

## 2. Scope

### In scope

* File-level split of `schemas.py` and `models.py`.
* Backwards-compat re-export shims.
* Two typed-enum upgrades: `PlanStep.type`, `HITLCheckpoint.trigger_type`.
* New `FailureTag` enum (`planning/failure_tags.py`).
* `mypy --strict` discipline on the new packages.
* Updating direct deep-imports inside `backend/src/ai/` to use the new
  paths (one-shot codemod; `from src.ai.schemas.entity import …`).

### Out of scope

* Renaming any class.
* Changing any field's semantics.
* Any DB migration (this is *pure code reorganisation* of ORM classes;
  Alembic table definitions are unchanged).
* Touching `frontend/`. Frontend talks JSON; field names and shapes do
  not move.

---

## 3. Architecture (technical)

```
backend/src/ai/
├── schemas/                       ← NEW PACKAGE (split of schemas.py)
│   ├── __init__.py                ← wildcard re-export for back-compat
│   ├── enums.py                   ← all str-Enum classes
│   ├── entity.py                  ← HierarchicalEntity{Base,Create,Update,Response}, Hierarchy
│   ├── persona.py                 ← Persona, AgentPersona, PersonalityMatrix, VoiceConfig, PersonaExample
│   ├── planning.py                ← PlanStep, StaticPlan, DynamicPlanning, ExitCondition, AllowedDeviations
│   ├── reasoning.py               ← LogicGate, ReasoningConfig, RetryPolicy, ReviewMechanism, ContextPolicy, SuccessCriterion
│   ├── capabilities.py            ← Capabilities, MemoryConfig, MetaCognitionConfig, ContextEngineering, ContextSource, ToolReference, ToolAuth, ToolDefinition, CortexMemoryConfig
│   ├── governance.py              ← Governance, HITLCheckpoint, ExecutionLimits
│   ├── io_contract.py             ← IOContract, Observability
│   ├── execution.py               ← ExecutionRunCreate, ExecutionRefineRequest, ExecutionRunSummary, ExecutionRunResponse, LLMInteractionLogResponse, ToolInteractionLogResponse, HumanApprovalResponse
│   ├── document.py                ← DocumentUploadResponse, DocumentResponse, DocumentSearchRequest, DocumentSearchResult
│   ├── cortex.py                  ← CortexTree*, CortexNode*, CortexViewport*, CortexCheckpoint*, GoalNode
│   ├── tools.py                   ← ToolRegistryEntry{Create,Update,Response}
│   └── prompts.py                 ← DEFAULT_PLANNING_SYSTEM_PROMPT, DEFAULT_REVIEW_SYSTEM_PROMPT
│
├── orm/                           ← NEW PACKAGE (split of models.py)
│   ├── __init__.py                ← wildcard re-export
│   ├── base.py                    ← Base, declarative_base
│   ├── entity.py                  ← HierarchicalEntity, EntityType (db enum)
│   ├── execution.py               ← ExecutionRun, LLMInteractionLog, ToolInteractionLog, HumanApproval
│   ├── document.py                ← Document, DocumentChunk
│   ├── memory.py                  ← EpisodicMemory (legacy table)
│   ├── cortex.py                  ← CortexTree, CortexNode, CortexEdge
│   ├── campaign.py                ← Campaign, CampaignCall (re-export from campaign_models)
│   ├── artifact.py                ← Artifact (re-export from artifact_models)
│   ├── lead_queue.py              ← (re-export from lead_queue_model)
│   ├── usage.py                   ← UsageLog
│   └── email.py                   ← (re-export from email_models)
│
└── planning/
    └── failure_tags.py            ← NEW (FailureTag enum)
```

The packages **own no logic**. They are pure declarations.

### 3.1 Re-export shim pattern

`backend/src/ai/schemas/__init__.py`:

```python
"""
schemas/ — Pydantic DTOs split per bounded context.

DO NOT add code here. Add it to the appropriate submodule.
This file is a backwards-compat re-export so existing
`from src.ai.schemas import X` calls continue to work.
"""
# pyright: reportWildcardImportFromLibrary=false
from src.ai.schemas.enums import *           # noqa: F401, F403
from src.ai.schemas.entity import *          # noqa: F401, F403
from src.ai.schemas.persona import *         # noqa: F401, F403
from src.ai.schemas.planning import *        # noqa: F401, F403
from src.ai.schemas.reasoning import *       # noqa: F401, F403
from src.ai.schemas.capabilities import *    # noqa: F401, F403
from src.ai.schemas.governance import *      # noqa: F401, F403
from src.ai.schemas.io_contract import *     # noqa: F401, F403
from src.ai.schemas.execution import *       # noqa: F401, F403
from src.ai.schemas.document import *        # noqa: F401, F403
from src.ai.schemas.cortex import *          # noqa: F401, F403
from src.ai.schemas.tools import *           # noqa: F401, F403
from src.ai.schemas.prompts import *         # noqa: F401, F403
```

Same pattern for `orm/__init__.py`.

Each submodule MUST define `__all__` so the wildcard re-export is
explicit, not accidental:

```python
# schemas/enums.py
__all__ = [
    "EntityType", "RunStatus", "EntityStatus", "RelationshipType",
    "ReasoningMode", "BackoffStrategy", "ValidationType",
    "HITLTriggerType", "StepType", "ExecutionMode", "ContextSourceType",
    "CortexTreeStatus", "CortexNodeType",
]
```

### 3.2 Typed-enum upgrades

#### 3.2.1 `PlanStep.type` (currently `Optional[str]`)

Before (`schemas.py:340`):

```python
class PlanStep(BaseModel):
    step_id: Optional[str] = None
    order: int = 0
    name: str = ""
    description: Optional[str] = None
    type: Optional[str] = None  # ← stringly typed
    ...
```

After (`schemas/planning.py`):

```python
class PlanStep(BaseModel):
    step_id: Optional[str] = None
    order: int = 0
    name: str = ""
    description: Optional[str] = None
    type: StepType = StepType.ACTION   # typed; default ACTION

    @field_validator("type", mode="before")
    @classmethod
    def _coerce_type(cls, v):
        """LLM planners sometimes emit 'tool_call' / 'TOOL_CALL' / etc.
        Accept any case, raise for unknown values."""
        if v is None:
            return StepType.ACTION
        if isinstance(v, StepType):
            return v
        if isinstance(v, str):
            key = v.strip().upper()
            try:
                return StepType[key]
            except KeyError:
                raise ValueError(f"Unknown step type: {v!r}. "
                                 f"Valid: {[s.value for s in StepType]}")
        raise ValueError(f"PlanStep.type must be str or StepType, got {type(v)}")
```

**Backwards compat:** Pydantic's enum serialises to its `value`, so JSON
output is identical to today. Callers reading `.type == "TOOL_CALL"`
continue to work because `StepType("TOOL_CALL") == StepType.TOOL_CALL`
and `StepType.TOOL_CALL == "TOOL_CALL"` via str-Enum equality.

#### 3.2.2 `HITLCheckpoint.trigger_type`

Before (`schemas.py:523-534`):

```python
class HITLCheckpoint(BaseModel):
    trigger_type: HITLTriggerType   # already typed, but...
    ...
```

Inspection shows `HITLTriggerType` IS already typed on the schema. The
**bug** is in usage: `governance/governance_service.evaluate_hitl(...)`
compares `checkpoint.trigger_type == "BEFORE_STEP"` (string) which works
only because str-Enum. We promote those comparisons to enum identity:

```python
# governance/governance_service.py (Track 1 sub-edit)
if checkpoint.trigger_type is HITLTriggerType.BEFORE_STEP:
    ...
```

This is a one-line fix per branch in `evaluate_hitl`.

#### 3.2.3 `FailureTag` enum (new file)

`backend/src/ai/planning/failure_tags.py`:

```python
"""
ai.planning.failure_tags — Closed-enum failure tags emitted by critics.

Used by:
  - CriticPipeline (Track 3) — to tag StepHealthRecord
  - Strategist (Track 2) — to pick a retry strategy
  - IntelligenceTree (Tracks 5-7) — to mine recurring patterns
"""
from enum import Enum


class FailureTag(str, Enum):
    OFF_TOPIC = "OFF_TOPIC"
    HALLUCINATION = "HALLUCINATION"
    INCOMPLETE = "INCOMPLETE"
    WRONG_FORMAT = "WRONG_FORMAT"
    TOOL_FAILURE = "TOOL_FAILURE"
    CONTRADICTION = "CONTRADICTION"
    UNVERIFIABLE = "UNVERIFIABLE"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    UNDER_BUDGET = "UNDER_BUDGET"
    OVER_BUDGET = "OVER_BUDGET"
    BLOCKED_DEPENDENCY = "BLOCKED_DEPENDENCY"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"

    @classmethod
    def from_string(cls, s: str) -> "FailureTag | None":
        """Tolerant parser used when an LLM emits a tag from text."""
        if not s:
            return None
        key = s.strip().upper().replace(" ", "_").replace("-", "_")
        return cls.__members__.get(key)

    @property
    def severity(self) -> int:
        """0 (informational) .. 3 (critical). Drives retry strategy."""
        return _SEVERITY[self]


_SEVERITY = {
    FailureTag.OFF_TOPIC:           2,
    FailureTag.HALLUCINATION:       3,
    FailureTag.INCOMPLETE:          1,
    FailureTag.WRONG_FORMAT:        1,
    FailureTag.TOOL_FAILURE:        2,
    FailureTag.CONTRADICTION:       2,
    FailureTag.UNVERIFIABLE:        2,
    FailureTag.POLICY_VIOLATION:    3,
    FailureTag.UNDER_BUDGET:        0,
    FailureTag.OVER_BUDGET:         2,
    FailureTag.BLOCKED_DEPENDENCY:  1,
    FailureTag.NEEDS_CLARIFICATION: 1,
}
```

---

## 4. Detailed deliverables

### 4.1 Item T1-1 — Generate per-domain `schemas/` files (Day 1)

**Approach:**

1. Create `backend/src/ai/schemas/` directory with `__init__.py`.
2. **Do not delete `schemas.py` yet** — keep it as a re-export shim
   pointing to the new package, to handle internal-import drift.
3. Manually slice each class block from `schemas.py:1-970` into the
   correct submodule (see §3 picture).
4. Each submodule's first lines:

```python
"""schemas/<name>.py — <short description>"""
from __future__ import annotations
from typing import Optional, Dict, Any, List, Literal
from datetime import datetime
from uuid import UUID
from enum import Enum
from pydantic import BaseModel, field_validator, model_validator

from src.ai.schemas.enums import StepType, ReasoningMode, ...   # only what's used

__all__ = ["...", "..."]
```

5. Move the file-level `DEFAULT_PLANNING_SYSTEM_PROMPT` and
   `DEFAULT_REVIEW_SYSTEM_PROMPT` constants into `schemas/prompts.py`.
6. Move the `GoalNode` dataclass (currently lives at `schemas.py:938`)
   into `schemas/cortex.py`. It's only used by `core/recursive_engine.py`,
   but its data shape sits next to CORTEX types.

**Conversion of `schemas.py` to a shim:**

```python
# schemas.py — DEPRECATED shim (will be deleted in Track 9)
"""DEPRECATED. Use `from src.ai.schemas import X` (package), not this module."""
from src.ai.schemas import *      # noqa: F401, F403
```

`schemas.py` and `schemas/` cannot both exist on disk in a Python import
chain — Python will prefer the directory. So in practice we **rename**
the legacy file:

```bash
git mv backend/src/ai/schemas.py backend/src/ai/_schemas_legacy.py
# (only kept as historical reference; do not import. CI lints out
#  imports of _schemas_legacy.)
```

The shim approach is in `schemas/__init__.py` (§3.1).

### 4.2 Item T1-2 — Generate per-domain `orm/` files (Day 2)

Same approach for `models.py`. Notable subtleties:

* The Pydantic `EntityType` enum (in `schemas/enums.py`) and the
  SQLAlchemy `Enum` column type must reference the same string set.
  Use one source of truth: define the enum in `schemas/enums.py`, then
  in `orm/entity.py`:

  ```python
  from src.ai.schemas.enums import EntityType
  ...
  type: Mapped[EntityType] = mapped_column(
      SqlEnum(EntityType, name="entity_type_enum"), nullable=False
  )
  ```

* Some ORM classes already live in their own modules (`campaign_models.py`,
  `artifact_models.py`, `lead_queue_model.py`, `email_models.py`).
  `orm/__init__.py` re-exports those too:

  ```python
  # orm/__init__.py
  from src.ai.orm.entity import *
  from src.ai.orm.execution import *
  ...
  # Re-export already-modular ORM classes:
  from src.ai.campaign_models import Campaign, CampaignCall   # noqa
  from src.ai.artifact_models import Artifact                  # noqa
  from src.ai.lead_queue_model import LeadQueueItem             # noqa
  from src.ai.email_models import EmailRecord                   # noqa
  ```

  (These modules themselves move under `services/` in Track 9; for now
  they stay where they are.)

### 4.3 Item T1-3 — Codemod direct deep-imports inside `ai/` (Day 3)

The wildcard re-exports preserve back-compat at the *package* level
(`from src.ai.schemas import X` keeps working). But Track 1 also takes
the opportunity to **switch internal imports** to deep-imports for
better mypy ergonomics.

Codemod plan (script in `backend/scripts/codemod_schemas_imports.py`):

```python
"""
codemod_schemas_imports.py — rewrites
    from src.ai.schemas import A, B, C
into per-submodule imports
    from src.ai.schemas.entity import A
    from src.ai.schemas.planning import B
    from src.ai.schemas.reasoning import C
based on a single source-of-truth mapping.
"""
SYMBOL_TO_MODULE = {
    "EntityType":      "enums",
    "RunStatus":       "enums",
    "HITLTriggerType": "enums",
    "StepType":        "enums",
    "ReasoningMode":   "enums",
    "EntityStatus":    "enums",
    "ContextSourceType":"enums",
    "BackoffStrategy": "enums",
    "ValidationType":  "enums",
    "RelationshipType":"enums",
    "ExecutionMode":   "enums",
    "CortexTreeStatus":"enums",
    "CortexNodeType":  "enums",
    "HierarchicalEntityBase":   "entity",
    "HierarchicalEntityCreate": "entity",
    "HierarchicalEntityUpdate": "entity",
    "HierarchicalEntityResponse":"entity",
    "Hierarchy":       "entity",
    "HierarchyChild":  "entity",
    "HierarchyChildCondition":"entity",
    "Persona":         "persona",
    "AgentPersona":    "persona",
    "PersonalityMatrix":"persona",
    "VoiceConfig":     "persona",
    "PersonaExample":  "persona",
    "PlanStep":        "planning",
    "PlanStepTarget":  "planning",
    "StaticPlan":      "planning",
    "DynamicPlanning": "planning",
    "AllowedDeviations":"planning",
    "ExitCondition":   "planning",
    "Planning":        "planning",
    "ConvergenceCriterion":"planning",
    "LoopControl":     "planning",
    "LogicGate":       "reasoning",
    "ReasoningConfig": "reasoning",
    "RetryPolicy":     "reasoning",
    "ReviewMechanism": "reasoning",
    "ContextPolicy":   "reasoning",
    "SuccessCriterion":"reasoning",
    "Capabilities":    "capabilities",
    "MemoryConfig":    "capabilities",
    "MetaCognitionConfig":"capabilities",
    "CortexMemoryConfig":"capabilities",
    "ContextEngineering":"capabilities",
    "ContextSource":   "capabilities",
    "ToolReference":   "capabilities",
    "ToolAuth":        "capabilities",
    "ToolDefinition":  "capabilities",
    "Governance":      "governance",
    "HITLCheckpoint":  "governance",
    "ExecutionLimits": "governance",
    "IOContract":      "io_contract",
    "Observability":   "io_contract",
    "ExecutionRunCreate":"execution",
    "ExecutionRefineRequest":"execution",
    "ExecutionRunSummary":"execution",
    "ExecutionRunResponse":"execution",
    "LLMInteractionLogResponse":"execution",
    "ToolInteractionLogResponse":"execution",
    "HumanApprovalResponse":"execution",
    "DocumentUploadResponse":"document",
    "DocumentResponse":"document",
    "DocumentSearchRequest":"document",
    "DocumentSearchResult":"document",
    "CortexTreeCreate":"cortex",
    "CortexTreeResponse":"cortex",
    "CortexTreeListResponse":"cortex",
    "CortexNodeCreate":"cortex",
    "CortexNodeSummary":"cortex",
    "CortexViewportResponse":"cortex",
    "CortexNodeContentResponse":"cortex",
    "CortexCheckpointCreate":"cortex",
    "CortexRecurseRequest":"cortex",
    "CortexNodeDetailResponse":"cortex",
    "GoalNode":        "cortex",
    "ToolRegistryEntryCreate":"tools",
    "ToolRegistryEntryUpdate":"tools",
    "ToolRegistryEntryResponse":"tools",
    "DEFAULT_PLANNING_SYSTEM_PROMPT":"prompts",
    "DEFAULT_REVIEW_SYSTEM_PROMPT":"prompts",
    "VALID_TRANSITIONS":"enums",
    "validate_transition":"enums",
}
```

Run mode: parse Python files with `libcst`, find
`ImportFrom(module="src.ai.schemas")`, rewrite each imported name to
the corresponding submodule.

Run on `backend/src/ai/**/*.py` only. **Do not codemod tests** in this
Track — keep test imports going through `src.ai.schemas` to verify the
wildcard re-export works.

### 4.4 Item T1-4 — Typed-enum upgrades (Day 4 AM)

* `schemas/planning.py::PlanStep` — see §3.2.1.
* `governance/governance_service.py::evaluate_hitl` — rewrite the
  `trigger_type == "STRING"` comparisons to `is HITLTriggerType.X`
  identity. Every branch.

```bash
# Quick survey of affected sites:
grep -RIn "trigger_type ==" backend/src/ai/governance/
```

### 4.4 Item T1-5 — `FailureTag` enum (Day 4 PM)

Create `backend/src/ai/planning/failure_tags.py` per §3.2.3.

Update `backend/src/ai/planning/__init__.py`:

```python
from src.ai.planning.planner_service import PlannerService
from src.ai.planning.goal_alignment import GoalAlignmentVerifier
from src.ai.planning.goal_guard import GoalGuard
from src.ai.planning.failure_tags import FailureTag

__all__ = ["PlannerService", "GoalAlignmentVerifier", "GoalGuard", "FailureTag"]
```

### 4.5 Item T1-6 — mypy --strict gate (Day 5)

* Add `pyproject.toml` section:

```toml
[tool.mypy]
files = [
    "backend/src/ai/schemas",
    "backend/src/ai/orm",
    "backend/src/ai/planning/failure_tags.py",
]
strict = true
plugins = ["pydantic.mypy", "sqlalchemy.ext.mypy.plugin"]
```

* CI step:

```yaml
- name: mypy strict (schemas + orm + new types)
  run: mypy --config-file=backend/pyproject.toml
```

* Tighten signatures in the new files until clean. Common issues to
  expect:
  * `Dict[str, Any]` → narrow to specific shapes where possible.
  * `Optional[str] = None` for fields that should be `str = ""`.

---

## 5. Database / schema changes

**N/A — pure file split.** SQLAlchemy `__tablename__` and column shapes
are unchanged. Alembic migrations untouched.

---

## 6. API changes

**N/A.** JSON shape unchanged. `StepType` already serialises to its
string value via Pydantic's str-Enum behaviour.

> Caveat: if any HTTP client was sending `"type": null` for a step (to
> default to ACTION), the new validator coerces `None` → `StepType.ACTION`.
> No client should be doing this — but watch for 422s after deploy.

---

## 7. Telemetry events

**N/A — no new events.**

---

## 8. Feature flags

**N/A.** This is a pure-refactor Track. No runtime branching.

---

## 9. Tests

### 9.1 Existing tests

All existing tests MUST pass unchanged.

### 9.2 New tests

| Test | File | What it asserts |
|------|------|-----------------|
| `test_schemas_back_compat` | `backend/tests/test_schemas.py` | `from src.ai.schemas import HierarchicalEntityCreate, PlanStep, StepType, …` (every name from old `__all__`) — succeeds |
| `test_orm_back_compat` | `backend/tests/test_orm.py` | Same for `src.ai.models` symbols |
| `test_plan_step_type_coercion` | `backend/tests/test_schemas.py` | `PlanStep(type="tool_call")` → `StepType.TOOL_CALL`; `PlanStep(type="bogus")` → ValueError |
| `test_plan_step_type_default` | `backend/tests/test_schemas.py` | `PlanStep()` → `.type == StepType.ACTION` |
| `test_failure_tag_from_string` | `backend/tests/test_failure_tags.py` | `FailureTag.from_string("off-topic")` returns `FailureTag.OFF_TOPIC` |
| `test_failure_tag_severity` | same | Every member of `FailureTag` has a severity in `[0,3]` |
| `test_hitl_trigger_type_enum_compare` | `backend/tests/test_governance.py` | `evaluate_hitl` with `HITLTriggerType.BEFORE_STEP` matches a `BEFORE` phase |
| `test_mypy_strict_passes` | `backend/tests/test_mypy.py` (slow, optional) | Shells out to `mypy --strict` on the new packages |

### 9.3 Smoke

* Boot worker, run one entity execution.
* Confirm Meta-Agent's seed still works (uses
  `HierarchicalEntityCreate` from `schemas` imports).

---

## 10. Acceptance criteria

Track 1 is **done** when:

1. `backend/src/ai/schemas/` is a directory with the files listed in §3.
2. `backend/src/ai/orm/` is a directory with the files listed in §3.
3. `from src.ai.schemas import X` works for every X in the original
   `schemas.py` `__all__`.
4. `from src.ai.models import X` works for every X in the original
   `models.py`.
5. `PlanStep().type is StepType.ACTION`.
6. `mypy --strict` passes on the listed paths.
7. `backend/src/ai/planning/failure_tags.py` exists; `FailureTag` is
   importable as `from src.ai.planning import FailureTag`.
8. The codemod has been applied: `grep -RIn "from src.ai.schemas import" backend/src/ai/`
   shows no remaining imports (every internal site uses deep-imports).
9. CI green; full test suite green.

---

## 11. Effort breakdown (5 working days)

| Day | Work |
|-----|------|
| 1 | T1-1: build `schemas/` package; populate each submodule; back-compat shim |
| 2 | T1-2: build `orm/` package similarly |
| 3 | T1-3: write + run codemod for internal imports |
| 4 AM | T1-4: typed-enum upgrades |
| 4 PM | T1-5: `FailureTag` |
| 5 | T1-6: `mypy --strict` shake-out + buffer + PR |

---

## 12. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| A class with same name is defined in two submodules (e.g. by mistake) | M | Wildcard re-export raises ImportError on package init | `__all__` discipline + `tools/check_no_dup_symbols.py` lint |
| Frontend sends `"type": "ToolCall"` instead of `"TOOL_CALL"` | M | 422 Validation Error | The case-insensitive coercion in §3.2.1 handles this |
| Pydantic v2 picks the wrong validator order for `PlanStep.type` | M | Edge-case parse fails | `mode="before"` validator + explicit tests |
| Codemod misses an import (e.g. inside a comment / docstring) | L | Slightly stale doc references | Run the lint script (`grep -RIn "from src.ai.schemas import" backend/`) in PR review; expected hits are tests-only |
| `mypy --strict` finds a wave of latent bugs | M | Track 1 timeline slips | Time-box: anything beyond schemas / orm gets a `# type: ignore[…]` with a TODO and is fixed in a follow-up PR |

---

## 13. Dependencies

* **Upstream:** Track 0 (clean index).
* **Downstream:** every later Track relies on `FailureTag` and the typed
  `PlanStep.type`. Track 3 (CriticPipeline) cannot start until T1-5 is
  done.

---

## 14. Open questions

* Should `schemas/__init__.py` use explicit re-exports instead of
  wildcards? Trade-off: explicit = mypy/IDE-friendly but verbose;
  wildcard = matches today's `from src.ai.schemas import *` ergonomics.
  **Resolution for Track 1:** wildcards initially, then a Track 9
  follow-up converts to explicit when we have a finalised public API
  surface.
