"""schemas/document.py — Document upload, list, and semantic search DTOs."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

__all__ = [
    "DocumentUploadResponse",
    "DocumentResponse",
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

    class Config:
        from_attributes = True


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
