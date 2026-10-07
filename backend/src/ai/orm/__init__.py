"""
orm/ — SQLAlchemy ORM clusters (Phase 11 Track 1).

DO NOT add code here. Add it to the appropriate submodule.

Importing this package registers every ORM class with SQLAlchemy's
metadata, which is required before any session.execute() that touches
relationships.
"""
# Ensure auth + config models load first (FK targets).
from src.auth.models import Company, User  # noqa: F401
from src.config.models import IntegrationRegistry  # noqa: F401

from src.ai.orm.entity import HierarchicalEntity
from src.ai.orm.execution import (
    ExecutionRun,
    HumanApproval,
    LLMInteractionLog,
    ToolInteractionLog,
)
from src.ai.orm.document import Document
from src.ai.orm.usage import UsageLog
from src.ai.orm.tools import ToolRegistryEntry
from src.ai.orm.trace import ExecutionTraceEvent
from src.ai.orm.versions import EntityAsset, EntityVersion

# Re-export enums from schemas, so ``from src.ai.orm import RunStatus`` works
# (callers of the deleted ``src.ai.models`` shim imported them with the models).
from src.ai.schemas.enums import EntityType, RunStatus  # noqa: F401

__all__ = [
    "HierarchicalEntity",
    "ExecutionRun",
    "LLMInteractionLog",
    "ToolInteractionLog",
    "HumanApproval",
    "Document",
    "UsageLog",
    "ToolRegistryEntry",
    "ExecutionTraceEvent",
    "EntityVersion",
    "EntityAsset",
    "EntityType",
    "RunStatus",
]
