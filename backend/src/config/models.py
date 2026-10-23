import uuid
from datetime import datetime
from enum import StrEnum
from sqlalchemy import CheckConstraint, Column, String, Boolean, DateTime, Text, Numeric, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from src.common.tenancy.bases import ControlBase

# ---------------------------------------------------------------------------
# Supported AI task types — drives model routing decisions. The one list: the
# task-defaults API accepts exactly these, and tests/unit/test_task_types.py
# fails when code resolves a task type that is not here (LP-09).
# ---------------------------------------------------------------------------
TASK_TYPES = [
    "text_generation",
    "thinking",
    "goal_validation",
    "embedding",
    "vision",
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


class ServiceCategory(StrEnum):
    """What an integration row is for. The one list (LP-11): the API validates
    against it, the code queries with it, and a CHECK constraint holds the
    column to it. It used to be free text, and the column comment, the create
    modal and the resolvers each named different values (``IMAGE_GEN`` against
    ``IMAGE_GENERATION``), so a row made by the comment was never found."""
    LLM = "LLM"                            # text models: -in / -out token SKUs
    LLM_LIVE = "LLM_LIVE"                  # realtime voice models
    EMBEDDING = "EMBEDDING"
    IMAGE_GENERATION = "IMAGE_GENERATION"
    VIDEO_GENERATION = "VIDEO_GENERATION"
    SPEECH_GENERATION = "SPEECH_GENERATION"  # text to speech (Gemini TTS), priced per second
    MUSIC_GENERATION = "MUSIC_GENERATION"    # music (Lyria), priced per clip
    SANDBOX = "SANDBOX"                    # sandbox seconds
    COMMUNICATION = "COMMUNICATION"        # telephony and messaging providers
    EMAIL = "EMAIL"
    SOCIAL_MEDIA = "SOCIAL_MEDIA"
    API_TOOL = "API_TOOL"                  # priced third-party tool APIs
    # HireBuddha's own app with an outside provider (Meta, LinkedIn, Google, X,
    # GitHub, Microsoft): what businesses connect through (Phase 14 WS5, D40).
    OAUTH_APP = "OAUTH_APP"
    OTHER = "OTHER"


# Providers that authenticate with Google Application Default Credentials (the
# service account) and ignore a stored key: Gemini and Claude through Vertex AI,
# and Gemini Live through AI Studio, which falls back to ADC without one.
ADC_PROVIDERS = frozenset({"google", "gemini", "google_vertex", "anthropic", "anthropic_vertex"})


# service_metadata.auth values meaning "the workload's own identity": an Azure
# OpenAI or Foundry integration with no key gets an Entra token (Phase 14 WS1 1.7).
IDENTITY_AUTH = frozenset({"managed_identity", "entra"})


def needs_api_key(provider_name: str | None, service_metadata: dict | None = None) -> bool:
    """Whether an integration of this provider must store a key (LP-12). An
    ADC provider used to need a placeholder (``vertex-ai-service-account``)
    because the create schema and the router both refused an empty key. One
    whose ``service_metadata.auth`` is ``managed_identity`` needs none either."""
    if str((service_metadata or {}).get("auth") or "").lower() in IDENTITY_AUTH:
        return False
    return (provider_name or "").lower() not in ADC_PROVIDERS


class IntegrationRegistry(ControlBase):
    __tablename__ = "integration_registry"
    # The category CHECK is added NOT VALID by its migration and validated when
    # the table held no other value; see migrations/legacy/versions/p9_service_category.py.
    __table_args__ = (
        UniqueConstraint('company_id', 'service_sku', name='uq_integration_company_sku'),
        CheckConstraint(
            "service_category IN (" + ", ".join(f"'{c.value}'" for c in ServiceCategory) + ")",
            name="ck_integration_registry_service_category",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    provider_name = Column(String, nullable=False)  # e.g., google, anthropic, azure_openai
    model_name = Column(String, nullable=True)       # e.g., gemini-2.0-flash, claude-3-5-sonnet
    service_sku = Column(String, nullable=False)     # e.g., gemini-2.0-flash-in
    service_category = Column(String, nullable=False, default=ServiceCategory.LLM.value)  # a ServiceCategory
    component_type = Column(String, nullable=False)
    # Types: input_token, output_token, analysis, minute, character, flat_fee, image, video_second
    encrypted_api_key = Column(Text, nullable=True)
    # The secret's name in the platform vault (Key Vault on Azure; the
    # environment locally), read at run time instead of encrypted_api_key
    # (Phase 14 WS5 5.7, tech spec §10.2). config/registry_secrets.py reads either.
    secret_ref = Column(Text, nullable=True)
    internal_cost = Column(Numeric(24, 10), nullable=False)  # USD per the unit; exact (T1-5)
    # The price's unit, a code of src.billing.units.CostUnit (Phase 15 T1-2):
    # internal_cost USD per the unit's per_quantity of its dimension.
    cost_unit_code = Column(Text, ForeignKey("cost_units.code"), nullable=False)
    # The old free-text unit, read by nothing since T1-3; dropped one release
    # after control_0007 (plan §4 step 10). Not written any more.
    cost_unit = Column(String, nullable=True)
    service_metadata = Column(JSONB, nullable=True)
    # service_metadata fields by provider:
    #   google/gemini (Vertex AI — default): {"project_id": "...", "region": "us-central1"}
    #   google/gemini (AI Studio — Live models): {"use_ai_studio": true}
    #     Uses ADC (service account), no API key needed.
    #     Requires: generativelanguage.googleapis.com enabled in GCP project.
    #   anthropic (Vertex AI REQUIRED): {"project_id": "...", "region": "us-east5"}
    #   azure_openai: {"azure_endpoint": "https://...", "api_version": "2025-01-01-preview", "deployment_name": "..."}
    status = Column(String, default="active")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship("src.auth.models.Company")


class ModelTaskDefault(ControlBase):
    """
    Maps AI task types to specific model integrations (per company).

    task_type: one of the TASK_TYPES constants above
    integration_id: FK to IntegrationRegistry — the model to use for this task
    fallback_integration_id: the model the router calls when the default's call
        fails after its retries (LP-08); it replaced ``routing_mode``, which
        nothing read
    """
    __tablename__ = "model_task_defaults"
    __table_args__ = (
        UniqueConstraint('company_id', 'task_type', name='uq_task_defaults_company_task'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    task_type = Column(String(50), nullable=False, index=True)       # e.g., "text_generation"
    integration_id = Column(UUID(as_uuid=True), ForeignKey("integration_registry.id"), nullable=False)
    fallback_integration_id = Column(UUID(as_uuid=True), ForeignKey("integration_registry.id", ondelete="SET NULL"),
                                     nullable=True)
    is_default = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship("src.auth.models.Company")
    integration = relationship("IntegrationRegistry", foreign_keys=[integration_id])
