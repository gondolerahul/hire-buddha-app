"""
Tool Management Router — CRUD endpoints for tool registry.

All write operations (create, update, delete, toggle) are restricted
to app_admin role. Read operations are available to all authenticated users.

``GET /api/v1/ai/tool-registry`` is the one tool list (API-19): the entity
builder's picker and the registry page both read it. ``GET /api/v1/ai/tools``
returned the same list under a name that suggested otherwise — and, when the
database failed, every built-in tool regardless of what the caller may see —
and is gone.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import List

from src.common.tenancy.session import get_control_db
from src.auth.dependencies import get_current_user, RoleChecker
from src.auth.models import User
from src.ai.schemas import (
    ToolRegistryEntryCreate,
    ToolRegistryEntryUpdate,
    ToolRegistryEntryResponse,
)
from src.ai.tool_management_service import ToolManagementService

router = APIRouter(
    prefix="/api/v1/ai/tool-registry",
    tags=["Tool Registry Management"],
)

app_admin_only = RoleChecker(["app_admin"])


# ---------------------------------------------------------------------------
# Read endpoints — all authenticated users
# ---------------------------------------------------------------------------

@router.get("", response_model=List[dict], summary="The tools you may see — the one tool list")
async def list_all_tools(
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(get_current_user),
):
    """Every tool the caller may see: the built-in tools, and the custom and
    synthesized tools of their company (``app_admin``: of every company), each
    with its registry metadata and ``is_enabled`` — disabled ones included, so a
    picker filters them. Any signed-in user."""
    service = ToolManagementService(db)
    return await service.list_all_tools(viewer=current_user)


@router.get("/{tool_id}", response_model=ToolRegistryEntryResponse,
            summary="One tool's registry entry (configuration: app_admin only)")
async def get_tool(
    tool_id: UUID,
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single tool by ID (404 for another tenant's tool).

    ``configuration`` — a synthesized tool's source and audit trail, a custom
    tool's endpoint and key references — goes to ``app_admin`` only, the role
    that edits tools (TL-06).
    """
    service = ToolManagementService(db)
    entry = await service.get_tool(tool_id, viewer=current_user)
    body = ToolRegistryEntryResponse.model_validate(entry)
    if current_user.role != "app_admin":
        body.configuration = None
    return body


# ---------------------------------------------------------------------------
# Write endpoints — app_admin only
# ---------------------------------------------------------------------------

@router.post("", response_model=ToolRegistryEntryResponse, status_code=201,
             summary="Create a custom tool (app_admin)")
async def create_tool(
    tool_in: ToolRegistryEntryCreate,
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(app_admin_only),
):
    """Create a new custom tool (app_admin only)."""
    service = ToolManagementService(db)
    return await service.create_tool(tool_in, current_user.company_id, current_user.id)


@router.put("/{tool_id}", response_model=ToolRegistryEntryResponse, summary="Update a tool (app_admin)")
async def update_tool(
    tool_id: UUID,
    tool_in: ToolRegistryEntryUpdate,
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(app_admin_only),
):
    """Update a tool (app_admin only)."""
    service = ToolManagementService(db)
    return await service.update_tool(tool_id, tool_in)


@router.delete("/{tool_id}", summary="Delete a custom tool (app_admin)")
async def delete_tool(
    tool_id: UUID,
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(app_admin_only),
):
    """Delete a custom tool (app_admin only). Built-in tools cannot be deleted."""
    service = ToolManagementService(db)
    await service.delete_tool(tool_id)
    return {"status": "success", "message": "Tool deleted"}


@router.post("/{tool_id}/toggle", response_model=ToolRegistryEntryResponse,
             summary="Enable or disable a tool (app_admin)")
async def toggle_tool(
    tool_id: UUID,
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(app_admin_only),
):
    """Toggle enabled/disabled state for a tool (app_admin only)."""
    service = ToolManagementService(db)
    return await service.toggle_tool(tool_id)


@router.post("/sync-built-in", summary="Write the built-in tools into the registry (app_admin)")
async def sync_built_in_tools(
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(app_admin_only),
):
    """Seed/update DB entries for all built-in tools (app_admin only)."""
    service = ToolManagementService(db)
    counts = await service.sync_built_in_tools()
    return {"status": "success", **counts}
