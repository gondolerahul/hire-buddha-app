"""schemas/entity.py — HierarchicalEntity DTOs and the hierarchy structure."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator

from src.ai.schemas.capabilities import Capabilities
from src.ai.schemas.enums import EntityStatus, EntityType
from src.ai.schemas.governance import Governance
from src.ai.schemas.io_contract import IOContract, Observability
from src.ai.schemas.planning import Planning
from src.ai.schemas.reasoning import LogicGate
from src.ai.schemas.strict_keys import unknown_keys

logger = logging.getLogger(__name__)

__all__ = [
    "HierarchyChildCondition",
    "HierarchyChild",
    "Hierarchy",
    "HierarchicalEntityBase",
    "HierarchicalEntityCreate",
    "HierarchicalEntityUpdate",
    "HierarchicalEntityCreateRequest",
    "HierarchicalEntityUpdateRequest",
    "HierarchicalEntityResponse",
]


class HierarchyChildCondition(BaseModel):
    enabled: bool = False
    expression: Optional[str] = None
    description: Optional[str] = None


class HierarchyChild(BaseModel):
    child_id: Optional[str] = None  # Accept string IDs from frontend
    child_type: Optional[str] = None  # Accept string type from frontend
    relationship: Optional[str] = None  # Accept string relationship from frontend
    condition: Optional[HierarchyChildCondition] = None


class Hierarchy(BaseModel):
    parent_id: Optional[UUID] = None
    children: List[HierarchyChild] = []
    is_atomic: bool = True
    composition_depth: int = 0


class HierarchicalEntityBase(BaseModel):
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    goal: Optional[str] = None  # Used in prompt generation as the entity's objective
    type: EntityType
    version: str = "1.0.0"
    status: EntityStatus = EntityStatus.ACTIVE
    tags: List[str] = []

    identity: Optional[Any] = None  # Accept Persona or {persona: Persona} format
    hierarchy: Optional[Hierarchy] = None
    logic_gate: Optional[LogicGate] = None
    planning: Optional[Planning] = None
    capabilities: Optional[Capabilities] = None
    governance: Optional[Governance] = None
    io_contract: Optional[IOContract] = None
    observability: Optional[Observability] = None
    metadata_extensions: Optional[Dict[str, Any]] = None

    # Template fields
    is_template: bool = False  # True = blueprint entity, not executable
    template_source_id: Optional[UUID] = None  # ID of template this was cloned from


class HierarchicalEntityCreate(HierarchicalEntityBase):
    parent_id: Optional[UUID] = None


class HierarchicalEntityUpdate(BaseModel):
    name: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    goal: Optional[str] = None
    type: Optional[EntityType] = None  # Added to allow type updates
    status: Optional[EntityStatus] = None
    version: Optional[str] = None
    tags: Optional[List[str]] = None  # Added to allow tags updates
    identity: Optional[Any] = None  # Accept Any format like create (Persona or {persona: Persona})
    hierarchy: Optional[Hierarchy] = None
    logic_gate: Optional[LogicGate] = None
    planning: Optional[Planning] = None
    capabilities: Optional[Capabilities] = None
    governance: Optional[Governance] = None
    io_contract: Optional[IOContract] = None
    observability: Optional[Observability] = None
    metadata_extensions: Optional[Dict[str, Any]] = None
    parent_id: Optional[UUID] = None
    is_template: Optional[bool] = None
    template_source_id: Optional[UUID] = None


def _reject_unknown_keys(model: type[BaseModel], data: Any) -> Any:
    unknown = unknown_keys(model, data)
    if unknown:
        raise ValueError(
            "Unknown configuration key(s), which would be ignored: " + ", ".join(unknown)
            + ". Check the spelling and where the key belongs."
        )
    return data


class HierarchicalEntityCreateRequest(HierarchicalEntityCreate):
    """The API's create payload: an undeclared key anywhere in it is a 422.

    ``HierarchicalEntityCreate`` itself stays lenient — the meta-agent tools and
    template cloning validate stored or generated JSON with it.
    """

    @model_validator(mode="before")
    @classmethod
    def _no_unknown_keys(cls, data: Any) -> Any:
        return _reject_unknown_keys(HierarchicalEntityCreate, data)


class HierarchicalEntityUpdateRequest(HierarchicalEntityUpdate):
    """The API's update payload: an undeclared key anywhere in it is a 422."""

    @model_validator(mode="before")
    @classmethod
    def _no_unknown_keys(cls, data: Any) -> Any:
        return _reject_unknown_keys(HierarchicalEntityUpdate, data)


class HierarchicalEntityResponse(HierarchicalEntityBase):
    id: UUID
    company_id: UUID
    parent_id: Optional[UUID]
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @field_validator("type", mode="before")
    @classmethod
    def coerce_unknown_type(cls, v):
        """Tolerate a `type` outside EntityType on the read path.

        The list endpoint returns `List[HierarchicalEntityResponse]`, so one row
        with an unknown type would fail the *entire* response with a 500 and
        blank the Entity Library. ``ck_hierarchical_entities_type`` keeps new
        rows to the six levels; a database that held other values when the
        constraint was added keeps it ``NOT VALID``, and those rows are
        presented as PROCESS here rather than taking the screen down.

        Writes are unaffected: HierarchicalEntityCreate/Update reject anything
        outside EntityType.
        """
        raw = getattr(v, "value", v)
        if not isinstance(raw, str):
            return v
        try:
            return EntityType(raw)
        except ValueError:
            logger.warning(
                "Entity type %r is not one of the six levels; presenting it as "
                "PROCESS.", raw,
            )
            return EntityType.PROCESS

    @field_validator("identity", mode="before")
    @classmethod
    def parse_identity(cls, v):
        if isinstance(v, dict) and "persona" in v:
            return v["persona"]
        return v

    @field_validator("tags", mode="before")
    @classmethod
    def parse_tags(cls, v):
        if v is None:
            return []
        return v
