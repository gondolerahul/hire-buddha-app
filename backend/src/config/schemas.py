from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, Literal
from datetime import datetime
from uuid import UUID
from decimal import Decimal

from src.billing.units import CostUnit
from src.config.models import ServiceCategory, needs_api_key

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
    # The price's unit by code (Phase 15 T1-2): internal_cost USD per it. The
    # free-text cost_unit and its parser are gone (REQ-CO-2).
    cost_unit_code: str
    service_metadata: Optional[dict] = None
    status: str = "active"
    # A secret's name in the platform vault instead of a stored key (WS5 5.7).
    secret_ref: Optional[str] = None


def _vault_name(value: Optional[str]) -> Optional[str]:
    if value:
        from src.common.platform.secrets import validate_secret_name
        validate_secret_name(value)  # ValueError → 422
    return value or None


class IntegrationRegistryCreate(IntegrationRegistryBase):
    company_id: UUID
    # Written values are one of the list (LP-11); reads stay ``str`` so a row
    # from before the constraint still renders.
    service_category: ServiceCategory = ServiceCategory.LLM
    cost_unit_code: CostUnit  # one of the enumerated units (422 otherwise)
    internal_cost: Decimal = Field(ge=0)
    # Optional for a provider that authenticates with ADC (LP-12); required
    # for every other provider. ``tata_tele`` may carry it in its metadata.
    api_key: Optional[str] = Field(None, alias="api_key")

    _vault_name_valid = field_validator("secret_ref")(_vault_name)

    @model_validator(mode="after")
    def _key_when_needed(self):
        if (not self.api_key and not self.secret_ref and needs_api_key(self.provider_name, self.service_metadata)
                and self.provider_name != "tata_tele"):
            raise ValueError(f"api_key is required for provider '{self.provider_name}'")
        return self

class IntegrationRegistryUpdate(BaseModel):
    provider_name: Optional[str] = None
    model_name: Optional[str] = None
    service_sku: Optional[str] = None
    service_category: Optional[ServiceCategory] = None
    component_type: Optional[str] = None
    internal_cost: Optional[Decimal] = Field(None, ge=0)
    cost_unit_code: Optional[CostUnit] = None
    service_metadata: Optional[dict] = None
    status: Optional[str] = None
    api_key: Optional[str] = None
    secret_ref: Optional[str] = None

    _vault_name_valid = field_validator("secret_ref")(_vault_name)

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
    # Called when the default's call fails after its retries (LP-08).
    fallback_integration_id: Optional[UUID] = None
    company_id: Optional[UUID] = None  # If None, use current user's company

class ModelTaskDefaultUpdate(BaseModel):
    integration_id: Optional[UUID] = None
    fallback_integration_id: Optional[UUID] = None

class ModelTaskDefaultResponse(BaseModel):
    id: UUID
    company_id: UUID
    task_type: str
    integration_id: UUID
    fallback_integration_id: Optional[UUID] = None
    is_default: bool
    created_at: datetime
    updated_at: datetime
    integration: Optional[IntegrationRegistryResponse] = None

    class Config:
        from_attributes = True
