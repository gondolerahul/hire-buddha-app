"""Schemas of the entity versions API (R2, EP-10)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.ai.schemas.entity import HierarchicalEntityUpdateRequest

__all__ = [
    "AssetBody",
    "AssetInfo",
    "AssetPut",
    "EntityVersionDetail",
    "EntityVersionSummary",
    "VersionDraftCreate",
    "VersionTestRun",
]


class EntityVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    entity_id: UUID
    version_number: int
    label: Optional[str] = None
    content_hash: str
    published: bool
    published_at: Optional[datetime] = None
    published_by: Optional[UUID] = None
    created_by: Optional[UUID] = None
    created_at: Optional[datetime] = None
    is_head: bool = False          # the version the entity's new runs execute
    asset_count: int = 0


class AssetInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    path: str
    size_bytes: int
    language: Optional[str] = None
    content_hash: str


class EntityVersionDetail(EntityVersionSummary):
    snapshot: dict[str, Any]
    assets: list[AssetInfo] = Field(default_factory=list)


class AssetBody(AssetInfo):
    body: str


class VersionDraftCreate(BaseModel):
    """A draft: a base version (the head when omitted) plus changes to its definition."""
    model_config = ConfigDict(extra="forbid")

    base_version_id: Optional[UUID] = None
    changes: HierarchicalEntityUpdateRequest = Field(default_factory=HierarchicalEntityUpdateRequest)


class AssetPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str


class VersionTestRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_data: dict[str, Any] = Field(default_factory=dict)
