import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Text, Numeric, ForeignKey, UniqueConstraint, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from src.common.database import Base

# ---------------------------------------------------------------------------
# Supported AI task types — drives model routing decisions
# ---------------------------------------------------------------------------
TASK_TYPES = [
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


class IntegrationRegistry(Base):
    __tablename__ = "integration_registry"
    __table_args__ = (
        UniqueConstraint('company_id', 'service_sku', name='uq_integration_company_sku'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    provider_name = Column(String, nullable=False)  # e.g., google, anthropic, azure_openai
    model_name = Column(String, nullable=True)       # e.g., gemini-2.0-flash, claude-3-5-sonnet
    service_sku = Column(String, nullable=False)     # e.g., gemini-2.0-flash-in
    service_category = Column(String, nullable=False, default="LLM")
    # Categories: LLM, LLM_LIVE, IMAGE_GEN, AUDIO_GEN, VIDEO_GEN, 3D_GEN, API_TOOL, COMMUNICATION
    component_type = Column(String, nullable=False)
    # Types: input_token, output_token, analysis, minute, character, flat_fee, image, video_second
    encrypted_api_key = Column(Text, nullable=True)
    internal_cost = Column(Numeric(18, 6), nullable=False)
    cost_unit = Column(String, nullable=False)
    service_metadata = Column(JSON, nullable=True)
    # service_metadata fields by provider:
    #   google/gemini (Vertex AI — default): {"project_id": "...", "region": "us-central1"}
    #   google/gemini (AI Studio — Live models): {"use_ai_studio": true}
    #     Uses ADC (service account), no API key needed.
    #     Requires: generativelanguage.googleapis.com enabled in GCP project.
    #   anthropic (Vertex AI REQUIRED): {"project_id": "...", "region": "us-east5"}
    #   azure_openai: {"azure_endpoint": "https://...", "api_version": "2025-01-01-preview", "deployment_name": "..."}
    status = Column(String, default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship("src.auth.models.Company")


class ModelTaskDefault(Base):
    """
    Maps AI task types to specific model integrations (per company).

    task_type: one of the TASK_TYPES constants above
    integration_id: FK to IntegrationRegistry — the model to use for this task
    routing_mode: 'single' (use integration_id model directly) or 'router' (use LLM router logic)
    """
    __tablename__ = "model_task_defaults"
    __table_args__ = (
        UniqueConstraint('company_id', 'task_type', name='uq_task_defaults_company_task'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    task_type = Column(String(50), nullable=False)       # e.g., "text_generation"
    integration_id = Column(UUID(as_uuid=True), ForeignKey("integration_registry.id"), nullable=False)
    routing_mode = Column(String(20), nullable=False, default="single")  # "single" | "router"
    is_default = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship("src.auth.models.Company")
    integration = relationship("IntegrationRegistry")
