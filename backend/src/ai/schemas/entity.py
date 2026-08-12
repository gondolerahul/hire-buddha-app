"""schemas/entity.py — HierarchicalEntity DTOs and the hierarchy structure."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator

from src.ai.schemas.capabilities import Capabilities
from src.ai.schemas.enums import EntityStatus, EntityType
from src.ai.schemas.governance import Governance
from src.ai.schemas.io_contract import IOContract, Observability
from src.ai.schemas.planning import Planning
from src.ai.schemas.reasoning import LogicGate

__all__ = [
    "HierarchyChildCondition",
    "HierarchyChild",
    "Hierarchy",
    "HierarchicalEntityBase",
    "HierarchicalEntityCreate",
    "HierarchicalEntityUpdate",
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


class HierarchicalEntityResponse(HierarchicalEntityBase):
    id: UUID
    company_id: UUID
    parent_id: Optional[UUID]
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

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
