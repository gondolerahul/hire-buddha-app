"""
cortex_memory.dtos — CORTEX data-transfer objects.

Tree-level CRUD/list shapes, node summaries, viewport, content pages, node
creates, checkpoint writes, recurse requests; the ``Provenance`` block attached
to knowledge writes; and the ``GoalNode`` goal-decomposition unit. Moved out of
the host ``schemas/cortex.py`` (Phase 12 `04`); the host re-exports them.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel

from cortex_memory.enums import CortexNodeType


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class SourceType(str, Enum):
    TOOL = "tool"
    USER_UPLOAD = "user_upload"
    REFLECTION = "reflection"
    DREAMING = "dreaming"
    EXTERNAL_LINK = "external_link"
    MANUAL = "manual"
    CONTEXT_SOURCE = "context_source"


# Per-source-type default trust scores.
DEFAULT_TRUST_BY_SOURCE: Dict[str, float] = {
    SourceType.USER_UPLOAD.value:    1.0,
    SourceType.MANUAL.value:         0.9,
    SourceType.DREAMING.value:       0.8,
    SourceType.TOOL.value:           0.7,
    SourceType.REFLECTION.value:     0.6,
    SourceType.CONTEXT_SOURCE.value: 0.6,
    SourceType.EXTERNAL_LINK.value:  0.4,
}


class Provenance(BaseModel):
    """Typed source-tracking block attached to CORTEX knowledge writes."""

    source_type: SourceType
    tool_id: Optional[str] = None
    url: Optional[str] = None
    upload_ref: Optional[str] = None
    fetched_at: Optional[datetime] = None
    trust_score: Optional[float] = None
    run_id: Optional[UUID] = None
    step_id: Optional[str] = None
    notes: Optional[str] = None

    def effective_trust_score(self) -> float:
        if self.trust_score is not None:
            return max(0.0, min(1.0, float(self.trust_score)))
        return float(DEFAULT_TRUST_BY_SOURCE.get(self.source_type.value, 0.5))

    def to_source_ref(self) -> Dict[str, Any]:
        """Serialise into the CortexNode.source_ref JSON blob."""
        return {
            "source_type": self.source_type.value,
            "tool_id": self.tool_id,
            "url": self.url,
            "upload_ref": self.upload_ref,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "trust_score": self.effective_trust_score(),
            "run_id": str(self.run_id) if self.run_id else None,
            "step_id": self.step_id,
            "notes": self.notes,
        }

    @classmethod
    def from_source_ref(cls, raw: Optional[Dict[str, Any]]) -> Optional["Provenance"]:
        if not raw or "source_type" not in raw:
            return None
        try:
            fetched_at = raw.get("fetched_at")
            if isinstance(fetched_at, str):
                try:
                    fetched_at = datetime.fromisoformat(fetched_at)
                except Exception:
                    fetched_at = None
            return cls(
                source_type=SourceType(raw["source_type"]),
                tool_id=raw.get("tool_id"),
                url=raw.get("url"),
                upload_ref=raw.get("upload_ref"),
                fetched_at=fetched_at,
                trust_score=raw.get("trust_score"),
                run_id=UUID(raw["run_id"]) if raw.get("run_id") else None,
                step_id=raw.get("step_id"),
                notes=raw.get("notes"),
            )
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Tree / node DTOs
# ---------------------------------------------------------------------------


class CortexTreeCreate(BaseModel):
    entity_id: UUID
    task_description: str
    max_children: int = 12
    page_size_tokens: int = 8000
    context_budget_pct: int = 40


class CortexTreeResponse(BaseModel):
    id: UUID
    entity_id: UUID
    task_description: Optional[str]
    status: str
    total_nodes: int = 0
    root_node_id: Optional[str] = None
    output_root_id: Optional[str] = None
    resume_cursor_id: Optional[str] = None
    max_children: int = 12
    created_at: Optional[datetime] = None
    last_active_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CortexTreeListResponse(BaseModel):
    id: UUID
    entity_id: UUID
    task_description: Optional[str]
    status: str
    total_nodes: int = 0
    created_at: Optional[datetime] = None
    last_active_at: Optional[datetime] = None


class CortexNodeSummary(BaseModel):
    id: str
    title: str
    summary: Optional[str]
    status: str
    node_type: str
    sibling_order: int = 0
    depth: int = 0
    content_tokens: int = 0


class CortexViewportResponse(BaseModel):
    current_node: CortexNodeSummary
    children: List[CortexNodeSummary]
    parent: Optional[CortexNodeSummary] = None
    breadcrumb: List[Dict[str, str]]


class CortexNodeContentResponse(BaseModel):
    node_id: str
    title: str
    content: str
    page: int
    total_pages: int
    content_tokens: int


class CortexNodeCreate(BaseModel):
    parent_id: UUID
    node_type: CortexNodeType
    title: str
    content: Optional[str] = None
    summary: Optional[str] = None
    status: str = "complete"
    source_ref: Optional[Dict[str, Any]] = None
    metadata_extra: Optional[Dict[str, Any]] = None


class CortexCheckpointCreate(BaseModel):
    progress_summary: str
    key_facts: List[str] = []
    next_steps: List[str] = []


class CortexRecurseRequest(BaseModel):
    node_id: UUID
    task: str
    result_slot: str


class CortexNodeDetailResponse(BaseModel):
    id: str
    tree_id: str
    parent_id: Optional[str] = None
    node_type: str
    title: str
    summary: Optional[str]
    content_tokens: int = 0
    status: str
    depth: int = 0
    sibling_order: int = 0
    source_ref: Optional[Dict[str, Any]] = None
    metadata_extra: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# GoalNode — unit of the goal-decomposition tree.
# ---------------------------------------------------------------------------


@dataclass
class GoalNode:
    """A single node in the goal-decomposition tree."""

    goal: str
    depth: int = 0
    confidence: float = 1.0
    parent: Optional["GoalNode"] = dataclass_field(default=None, repr=False)
    children: List["GoalNode"] = dataclass_field(default_factory=list)
    result: Optional[str] = None
    status: str = "pending"

    def is_leaf(self) -> bool:
        return len(self.children) == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "depth": self.depth,
            "confidence": self.confidence,
            "status": self.status,
            "result": self.result,
            "children": [c.to_dict() for c in self.children],
        }


__all__ = [
    "SourceType",
    "DEFAULT_TRUST_BY_SOURCE",
    "Provenance",
    "CortexTreeCreate",
    "CortexTreeResponse",
    "CortexTreeListResponse",
    "CortexNodeSummary",
    "CortexViewportResponse",
    "CortexNodeContentResponse",
    "CortexNodeCreate",
    "CortexCheckpointCreate",
    "CortexRecurseRequest",
    "CortexNodeDetailResponse",
    "GoalNode",
]
