"""
Centralized Google GenAI Client Factory — Vertex AI + AI Studio

This factory creates google.genai.Client instances configured for either:
  1. Vertex AI (default) — using project_id and region from IntegrationRegistry
  2. AI Studio / Gemini Developer API — using Application Default Credentials
     (for models not yet available on Vertex AI, e.g. Live/Native Audio models)

Usage:
    from src.common.genai_factory import build_vertex_genai_client

    # Vertex AI (standard path):
    client = await build_vertex_genai_client(db, company_id)
    client = build_vertex_genai_client_sync(service_metadata)

    # AI Studio (for Live/Native Audio models — uses ADC, no API key):
    client = build_ai_studio_genai_client_sync()
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def build_vertex_genai_client_sync(
    service_metadata: Dict[str, Any],
    http_options: Optional[Dict[str, Any]] = None,
):
    """
    Build a google.genai.Client configured for Vertex AI from pre-resolved
    service_metadata.

    This is the synchronous variant for use when service_metadata is already
    available (e.g. inside LLM adapters or streaming clients).

    Args:
        service_metadata: Dict with 'project_id' and optionally 'region'.
        http_options: Optional HTTP options (e.g. {'api_version': 'v1beta'}).

    Returns:
        google.genai.Client configured for Vertex AI.

    Raises:
        RuntimeError: If google-genai not installed.
        ValueError: If project_id is missing from service_metadata.
    """
    try:
        from google import genai
    except ImportError:
        raise RuntimeError(
            "google-genai package not installed. Run: pip install google-genai"
        )

    project_id = service_metadata.get("project_id")
    region = service_metadata.get("region", "us-central1")

    if not project_id:
        raise ValueError(
            "service_metadata.project_id is required for Vertex AI. "
            "Please configure the Google integration with a project_id "
            "in the Service Integration settings."
        )

    kwargs: Dict[str, Any] = {
        "vertexai": True,
        "project": project_id,
        "location": region,
    }
    if http_options:
        kwargs["http_options"] = http_options

    logger.debug(
        f"Building Vertex AI genai.Client (project={project_id}, region={region})"
    )
    return genai.Client(**kwargs)


async def build_vertex_genai_client(
    db: AsyncSession,
    company_id: UUID,
    http_options: Optional[Dict[str, Any]] = None,
):
    """
    Build a google.genai.Client configured for Vertex AI by looking up the
    Google integration for the given company from IntegrationRegistry.

    This is the async variant for use when you have db + company_id but
    haven't resolved the integration yet.

    Args:
        db: Database session.
        company_id: Company UUID.
        http_options: Optional HTTP options (e.g. {'api_version': 'v1beta'}).

    Returns:
        google.genai.Client configured for Vertex AI.

    Raises:
        RuntimeError: If no Google integration found or google-genai not installed.
        ValueError: If project_id is not configured in service_metadata.
    """
    from src.config.service import ConfigService

    config_svc = ConfigService(db)

    # Try to find a Google integration with Vertex AI config
    integration = await config_svc.get_integration_by_provider(
        company_id, "google"
    )
    if not integration:
        integration = await config_svc.get_integration_by_provider(
            company_id, "gemini"
        )

    if not integration:
        raise RuntimeError(
            "No Google/Gemini integration configured. "
            "Please add a Google Vertex AI integration in Service Integrations."
        )

    meta = integration.service_metadata or {}

    # Ensure project_id is set
    if not meta.get("project_id"):
        raise ValueError(
            f"Integration '{integration.service_sku}' is missing "
            f"'project_id' in service_metadata. "
            f"Please update the integration with your GCP project ID."
        )

    return build_vertex_genai_client_sync(meta, http_options=http_options)


def build_ai_studio_genai_client_sync(
    api_key: str | None = None,
    http_options: Optional[Dict[str, Any]] = None,
):
    """
    Build a google.genai.Client configured for the Gemini Developer API
    (AI Studio).

    When api_key is provided, it's passed directly to the client.
    Otherwise falls back to GOOGLE_API_KEY env var or ADC.

    Args:
        api_key: Google AI API key (from IntegrationRegistry).
        http_options: Optional HTTP options (e.g. {'api_version': 'v1beta'}).

    Returns:
        google.genai.Client configured for AI Studio (Gemini Developer API).

    Raises:
        RuntimeError: If google-genai not installed.
    """
    try:
        from google import genai
    except ImportError:
        raise RuntimeError(
            "google-genai package not installed. Run: pip install google-genai"
        )

    kwargs: Dict[str, Any] = {}
    if api_key:
        kwargs["api_key"] = api_key
    if http_options:
        kwargs["http_options"] = http_options

    logger.debug(
        f"Building AI Studio genai.Client (api_key={'set' if api_key else 'env/ADC'})"
    )
    return genai.Client(**kwargs)
