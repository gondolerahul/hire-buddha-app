"""Phase 11 Track 1 — schemas/ package split + typed-enum upgrade.

These tests freeze the public API of ``src.ai.schemas`` against the
``schemas.py`` shape that existed before the split, then exercise the
``PlanStep.type`` typed-enum coercion added in T1-4.
"""
from __future__ import annotations

import pytest

# These names made up the original schemas.py public surface. Wildcard
# re-export inside ``schemas/__init__.py`` MUST preserve all of them.
EXPECTED_NAMES = [
    # enums
    "EntityType", "RunStatus", "EntityStatus", "RelationshipType",
    "ReasoningMode", "BackoffStrategy", "ValidationType",
    "HITLTriggerType", "StepType", "ExecutionMode",
    "ContextSourceType", "CortexTreeStatus", "CortexNodeType",
    "VALID_TRANSITIONS", "validate_transition",
    # persona
    "PersonaExample", "VoiceConfig", "PersonalityMatrix",
    "AgentPersona", "Persona",
    # reasoning
    "ReasoningConfig", "RetryPolicy", "SuccessCriterion",
    "ReviewMechanism", "ContextPolicy", "LogicGate",
    # planning
    "PlanStepTarget", "PlanStep", "StaticPlan", "AllowedDeviations",
    "DynamicPlanning", "ConvergenceCriterion", "LoopControl",
    "Planning", "ExitCondition",
    # governance
    "ExecutionLimits", "HITLCheckpoint", "Governance",
    # io_contract
    "IOContract", "Observability",
    # capabilities
    "ToolAuth", "ToolDefinition", "ToolReference",
    "CortexMemoryConfig", "MemoryConfig", "ContextSource",
    "ContextEngineering", "MetaCognitionConfig", "Capabilities",
    # entity
    "HierarchyChildCondition", "HierarchyChild", "Hierarchy",
    "HierarchicalEntityBase", "HierarchicalEntityCreate",
    "HierarchicalEntityUpdate", "HierarchicalEntityResponse",
    # execution
    "ExecutionRunCreate", "ExecutionRefineRequest",
    "LLMInteractionLogResponse", "ToolInteractionLogResponse",
    "HumanApprovalResponse", "ExecutionRunSummary", "ExecutionRunResponse",
    # document
    "DocumentUploadResponse", "DocumentResponse",
    "DocumentSearchRequest", "DocumentSearchResult",
    # cortex
    "CortexTreeCreate", "CortexTreeResponse", "CortexTreeListResponse",
    "CortexNodeSummary", "CortexViewportResponse",
    "CortexNodeContentResponse", "CortexNodeCreate",
    "CortexCheckpointCreate", "CortexRecurseRequest",
    "CortexNodeDetailResponse", "GoalNode",
    # tools
    "ToolRegistryEntryCreate", "ToolRegistryEntryUpdate",
    "ToolRegistryEntryResponse",
    # prompts
    "DEFAULT_PLANNING_SYSTEM_PROMPT", "DEFAULT_REVIEW_SYSTEM_PROMPT",
]


def test_schemas_back_compat_all_names_resolve() -> None:
    """Every pre-split name still importable from ``src.ai.schemas``."""
    import src.ai.schemas as schemas

    missing = [name for name in EXPECTED_NAMES if not hasattr(schemas, name)]
    assert not missing, f"schemas package missing: {missing}"


def test_plan_step_type_default_is_action() -> None:
    """``PlanStep()`` without an explicit ``type`` defaults to ``ACTION``."""
    from src.ai.schemas import PlanStep, StepType

    step = PlanStep()
    assert step.type is StepType.ACTION


def test_plan_step_type_coercion_lowercase() -> None:
    """LLMs that emit ``"tool_call"`` get coerced to ``StepType.TOOL_CALL``."""
    from src.ai.schemas import PlanStep, StepType

    step = PlanStep(type="tool_call")
    assert step.type is StepType.TOOL_CALL


def test_plan_step_type_coercion_mixed_case() -> None:
    """Mixed-case input also coerces cleanly."""
    from src.ai.schemas import PlanStep, StepType

    step = PlanStep(type="Child_Entity_Invocation")
    assert step.type is StepType.CHILD_ENTITY_INVOCATION


def test_plan_step_type_coercion_none_defaults_to_action() -> None:
    """Explicit ``None`` coerces back to ``ACTION``."""
    from src.ai.schemas import PlanStep, StepType

    step = PlanStep(type=None)
    assert step.type is StepType.ACTION


def test_plan_step_type_coercion_unknown_raises() -> None:
    """An unknown step type raises rather than silently degrading."""
    from src.ai.schemas import PlanStep

    with pytest.raises(Exception):  # noqa: B017 — Pydantic wraps the ValueError
        PlanStep(type="not-a-valid-type")


def test_plan_step_serialises_to_enum_value() -> None:
    """JSON output is unchanged from pre-Track-1: enum value, not the symbol."""
    from src.ai.schemas import PlanStep

    step = PlanStep(type="TOOL_CALL")
    assert step.model_dump(mode="json")["type"] == "TOOL_CALL"


def test_orm_back_compat_models_module() -> None:
    """The legacy ``src.ai.models`` shim re-exports every ORM class."""
    from src.ai import models as legacy

    for name in (
        "HierarchicalEntity",
        "ExecutionRun",
        "LLMInteractionLog",
        "ToolInteractionLog",
        "HumanApproval",
        "EpisodicMemory",
        "Document",
        "DocumentChunk",
        "UsageLog",
        "ToolRegistryEntry",
        "EntityType",
        "RunStatus",
    ):
        assert hasattr(legacy, name), f"models shim missing: {name}"


def test_orm_canonical_paths() -> None:
    """Canonical imports under ``src.ai.orm.*`` resolve and point to the
    same class objects as the shim."""
    from src.ai import models as legacy
    from src.ai.orm.entity import HierarchicalEntity
    from src.ai.orm.execution import ExecutionRun

    assert HierarchicalEntity is legacy.HierarchicalEntity
    assert ExecutionRun is legacy.ExecutionRun


# ---------------------------------------------------------------------------
# D-3 (Phase 12): REFLECTION + TREE_OF_THOUGHTS deprecated as per-entity modes
# ---------------------------------------------------------------------------


def test_deprecated_reasoning_modes_membership() -> None:
    from src.ai.schemas import ReasoningMode
    from src.ai.schemas.enums import DEPRECATED_REASONING_MODES

    assert ReasoningMode.REFLECTION.value in DEPRECATED_REASONING_MODES
    assert ReasoningMode.TREE_OF_THOUGHTS.value in DEPRECATED_REASONING_MODES
    # The two supported modes must NOT be flagged deprecated.
    assert ReasoningMode.REACT.value not in DEPRECATED_REASONING_MODES
    assert ReasoningMode.CHAIN_OF_THOUGHT.value not in DEPRECATED_REASONING_MODES


def test_deprecated_reasoning_modes_exported() -> None:
    """``DEPRECATED_REASONING_MODES`` is part of the schemas public surface."""
    import src.ai.schemas as schemas
    assert hasattr(schemas, "DEPRECATED_REASONING_MODES")
