from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal
from datetime import datetime
from uuid import UUID
from decimal import Decimal

# ---------------------------------------------------------------------------
# Task Types for AI model routing
# ---------------------------------------------------------------------------
TaskType = Literal[
    "text_generation",
    "thinking",
    "text_to_image",
    "image_to_image",
    "text_to_speech",
    "text_to_music",
    "text_to_video",
    "text_to_3d",
    "image_to_video",
    "audio_to_video",
    "speech_to_speech",
]

# ---------------------------------------------------------------------------
# Integration Registry schemas
# ---------------------------------------------------------------------------

class IntegrationRegistryBase(BaseModel):
    provider_name: str
    model_name: Optional[str] = None
    service_sku: str
    service_category: str = "LLM"
    component_type: str
    internal_cost: Decimal
    cost_unit: str
    service_metadata: Optional[dict] = None
    status: str = "active"

def _known_cost_unit(value: Optional[str]) -> Optional[str]:
    """A registry price must name a unit the billing code can divide by;
    an unknown one used to price "per one" and over-bill (LP-01)."""
    if value is not None:
        from src.ai.usage_service import parse_cost_unit
        parse_cost_unit(value)  # ValueError → 422
    return value


class IntegrationRegistryCreate(IntegrationRegistryBase):
    company_id: UUID
    api_key: str = Field(..., alias="api_key")

    _cost_unit_known = field_validator("cost_unit")(_known_cost_unit)

class IntegrationRegistryUpdate(BaseModel):
    provider_name: Optional[str] = None
    model_name: Optional[str] = None
    service_sku: Optional[str] = None
    service_category: Optional[str] = None
    component_type: Optional[str] = None
    internal_cost: Optional[Decimal] = None
    cost_unit: Optional[str] = None
    service_metadata: Optional[dict] = None
    status: Optional[str] = None
    api_key: Optional[str] = None

    _cost_unit_known = field_validator("cost_unit")(_known_cost_unit)

class IntegrationRegistryResponse(IntegrationRegistryBase):
    id: UUID
    company_id: UUID
    created_at: datetime
    updated_at: datetime

    @field_validator("service_metadata")
    @classmethod
    def _hide_secrets(cls, value):
        # Encrypted secrets (Tata's auth_token, login_password…) are named, never sent.
        from src.voice.tata_credentials import redact_secrets
        return redact_secrets(value)

    class Config:
        from_attributes = True
        populate_by_name = True

class ModelResponse(BaseModel):
    model_key: str
    model_name: str
    provider: str
    model_type: str
    is_active: bool

# ---------------------------------------------------------------------------
# Model Task Default schemas
# ---------------------------------------------------------------------------

class ModelTaskDefaultCreate(BaseModel):
    task_type: str  # One of TASK_TYPES values
    integration_id: UUID
    routing_mode: Literal["single", "router"] = "single"
    company_id: Optional[UUID] = None  # If None, use current user's company

class ModelTaskDefaultUpdate(BaseModel):
    integration_id: Optional[UUID] = None
    routing_mode: Optional[Literal["single", "router"]] = None

class ModelTaskDefaultResponse(BaseModel):
    id: UUID
    company_id: UUID
    task_type: str
    integration_id: UUID
    routing_mode: str
    is_default: bool
    created_at: datetime
    updated_at: datetime
    integration: Optional[IntegrationRegistryResponse] = None

    class Config:
        from_attributes = True
