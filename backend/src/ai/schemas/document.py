"""schemas/document.py — Document upload, list, and semantic search DTOs."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "DocumentUploadResponse",
    "DocumentResponse",
    "DocumentDetail",
    "DocumentUpdate",
    "DocumentSearchRequest",
    "DocumentSearchResult",
]


class DocumentUploadResponse(BaseModel):
    id: UUID
    filename: str
    file_type: str
    upload_status: str
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentResponse(BaseModel):
    id: UUID
    company_id: UUID
    entity_id: Optional[UUID]
    filename: str
    file_type: str
    file_size: Optional[str]
    upload_status: str
    created_at: datetime
    updated_at: datetime
    # The agent the document is scoped to; None means company-wide.
    entity_name: Optional[str] = None

    class Config:
        from_attributes = True


class DocumentDetail(DocumentResponse):
    """One document plus what was ingested into its Knowledge Tree."""
    chunks_total: int = 0
    chunks_embedded: int = 0
    sections: list[str] = []
    preview: str = ""
    preview_truncated: bool = False


class DocumentUpdate(BaseModel):
    """Rename a document and/or change its scope.

    Send ``entity_id`` to scope the document to that agent, or ``entity_id: null``
    to make it company-wide; omit it to leave the scope unchanged.
    """
    model_config = ConfigDict(extra="forbid")

    filename: Optional[str] = Field(default=None, min_length=1, max_length=255)
    entity_id: Optional[UUID] = None


class DocumentSearchRequest(BaseModel):
    query: str
    entity_id: Optional[UUID] = None
    top_k: int = 5


class DocumentSearchResult(BaseModel):
    chunk_id: UUID
    document_id: UUID
    filename: str
    content: str
    similarity: float
