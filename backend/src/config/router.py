from uuid import UUID
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select
from src.common.database import get_db
from src.config.schemas import (
    IntegrationRegistryCreate,
    IntegrationRegistryUpdate,
    IntegrationRegistryResponse,
    ModelResponse,
    ModelTaskDefaultCreate,
    ModelTaskDefaultResponse,
)
from src.config.models import ModelTaskDefault, TASK_TYPES
from src.config.service import ConfigService
from src.auth.dependencies import get_current_user, RoleChecker
from src.auth.models import User

router = APIRouter(prefix="/config", tags=["Integrations"])


# ============================================================================
# Integration Registry CRUD
# ============================================================================

@router.get("/models", response_model=list[ModelResponse])
async def list_models(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all LLM models registered in the integration registry."""
    service = ConfigService(db)
    integrations = await service.get_registry_entries(company_id=current_user.company_id)

    models = []
    seen_models = set()

    for integration in integrations:
        if integration.service_category in ("LLM", "LLM_LIVE") and integration.model_name not in seen_models:
            models.append({
                "model_key": integration.model_name,
                "model_name": integration.model_name,
                "provider": integration.provider_name,
                "model_type": integration.service_category.lower(),
                "is_active": integration.status == "active"
            })
            seen_models.add(integration.model_name)

    return models


# Categories that tenant users are allowed to manage
TENANT_ALLOWED_CATEGORIES = {"EMAIL", "SOCIAL_MEDIA", "API_TOOL", "OTHER"}


@router.post("/integrations", response_model=IntegrationRegistryResponse)
async def create_integration(
    entry_in: IntegrationRegistryCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in ["app_admin", "partner_admin", "tenant_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    if current_user.role != "app_admin" and str(entry_in.company_id) != str(current_user.company_id):
        raise HTTPException(status_code=403, detail="Cannot create integration for another company")

    # Tenant users can only add social media, email, and API tool integrations
    if current_user.role in ("tenant_admin", "tenant_user"):
        if entry_in.service_category not in TENANT_ALLOWED_CATEGORIES:
            raise HTTPException(
                status_code=403,
                detail=f"Tenant users can only add integrations for: {', '.join(sorted(TENANT_ALLOWED_CATEGORIES))}. "
                       f"Contact your platform administrator for AI model or telephony integrations."
            )

    service = ConfigService(db)
    return await service.create_registry_entry(entry_in)


@router.get("/integrations", response_model=list[IntegrationRegistryResponse])
async def list_integrations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    service = ConfigService(db)

    if current_user.role == "app_admin":
        # App admin sees all integrations across all companies
        return await service.get_registry_entries(company_id=None)
    else:
        # All other roles (partner, tenant) see only their own company's entries
        return await service.get_registry_entries(company_id=current_user.company_id)


@router.get("/integrations/{entry_id}", response_model=IntegrationRegistryResponse)
async def get_integration(
    entry_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    service = ConfigService(db)
    entry = await service.get_registry_entry(entry_id)

    if current_user.role != "app_admin" and str(entry.company_id) != str(current_user.company_id):
        raise HTTPException(status_code=403, detail="Access denied")

    return entry


@router.patch("/integrations/{entry_id}", response_model=IntegrationRegistryResponse)
async def update_integration(
    entry_id: UUID,
    entry_in: IntegrationRegistryUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    service = ConfigService(db)
    entry = await service.get_registry_entry(entry_id)
    if current_user.role != "app_admin" and str(entry.company_id) != str(current_user.company_id):
        raise HTTPException(status_code=403, detail="Access denied")

    # Tenant users cannot change category to a restricted one
    if current_user.role in ("tenant_admin", "tenant_user"):
        new_category = entry_in.service_category if entry_in.service_category else entry.service_category
        if new_category not in TENANT_ALLOWED_CATEGORIES:
            raise HTTPException(
                status_code=403,
                detail=f"Tenant users can only manage integrations for: {', '.join(sorted(TENANT_ALLOWED_CATEGORIES))}"
            )

    return await service.update_registry_entry(entry_id, entry_in)


@router.delete("/integrations/{entry_id}", status_code=204)
async def delete_integration(
    entry_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    service = ConfigService(db)
    entry = await service.get_registry_entry(entry_id)
    if current_user.role != "app_admin" and str(entry.company_id) != str(current_user.company_id):
        raise HTTPException(status_code=403, detail="Access denied")

    await service.delete_registry_entry(entry_id)
    return None


# ============================================================================
# Task Defaults — App Admin ONLY
# ============================================================================

def _require_app_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency: only app_admin can manage system task defaults."""
    if current_user.role != "app_admin":
        raise HTTPException(
            status_code=403,
            detail="Only App Administrators can configure AI task defaults"
        )
    return current_user


@router.get("/task-defaults", response_model=list[ModelTaskDefaultResponse])
async def list_task_defaults(
    current_user: User = Depends(_require_app_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    List all task-to-model defaults for the App Admin's company.
    Returns own defaults merged with any inherited platform defaults.
    """
    service = ConfigService(db)
    defaults = await service.get_all_task_defaults(current_user.company_id)

    # Eager-load integrations for response
    result = []
    from src.config.models import IntegrationRegistry
    for d in defaults:
        integ_result = await db.execute(
            select(IntegrationRegistry).where(IntegrationRegistry.id == d.integration_id)
        )
        integ = integ_result.scalar_one_or_none()
        result.append({
            "id": d.id,
            "company_id": d.company_id,
            "task_type": d.task_type,
            "integration_id": d.integration_id,
            "routing_mode": d.routing_mode,
            "is_default": d.is_default,
            "created_at": d.created_at,
            "updated_at": d.updated_at,
            "integration": integ,
        })
    return result


@router.post("/task-defaults", response_model=ModelTaskDefaultResponse)
async def set_task_default(
    body: ModelTaskDefaultCreate,
    current_user: User = Depends(_require_app_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Set (or update) the default model for a specific AI task type.
    Only app_admin can call this endpoint.
    """
    from src.config.models import TASK_TYPES
    if body.task_type not in TASK_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid task_type '{body.task_type}'. Must be one of: {TASK_TYPES}"
        )

    # Use the current user's company if not explicitly specified
    company_id = body.company_id or current_user.company_id

    service = ConfigService(db)
    default = await service.set_task_default(
        company_id=company_id,
        task_type=body.task_type,
        integration_id=body.integration_id,
        routing_mode=body.routing_mode,
    )

    # Load integration for response
    from src.config.models import IntegrationRegistry
    integ_result = await db.execute(
        select(IntegrationRegistry).where(IntegrationRegistry.id == default.integration_id)
    )
    integ = integ_result.scalar_one_or_none()

    return {
        "id": default.id,
        "company_id": default.company_id,
        "task_type": default.task_type,
        "integration_id": default.integration_id,
        "routing_mode": default.routing_mode,
        "is_default": default.is_default,
        "created_at": default.created_at,
        "updated_at": default.updated_at,
        "integration": integ,
    }


@router.delete("/task-defaults/{task_type}", status_code=204)
async def delete_task_default(
    task_type: str,
    current_user: User = Depends(_require_app_admin),
    db: AsyncSession = Depends(get_db)
):
    """Remove a task default. Only app_admin can call this."""
    service = ConfigService(db)
    await service.delete_task_default(current_user.company_id, task_type)
    return None


@router.get("/task-types")
async def list_task_types(
    current_user: User = Depends(get_current_user),
):
    """List all supported AI task types."""
    return {
        "task_types": TASK_TYPES,
        "descriptions": {
            "text_generation": "Generate text, chat, Q&A, summarization",
            "thinking": "Complex reasoning, planning, analysis",
            "text_to_image": "Generate images from text prompts",
            "image_to_image": "Transform or edit existing images",
            "text_to_speech": "Convert text to audio speech",
            "text_to_music": "Generate music or audio from text",
            "text_to_video": "Generate video from text description",
            "text_to_3d": "Generate 3D models from text",
            "image_to_video": "Animate or transform images into video",
            "audio_to_video": "Generate video synchronized with audio",
            "speech_to_speech": "Real-time bidirectional voice conversation",
        }
    }
