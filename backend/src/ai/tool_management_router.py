"""
Tool Management Router — CRUD endpoints for tool registry.

All write operations (create, update, delete, toggle) are restricted
to app_admin role. Read operations are available to all authenticated users.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import List

from src.common.database import get_db
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

@router.get("", response_model=List[dict])
async def list_all_tools(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all tools (built-in + custom), enriched with metadata."""
    service = ToolManagementService(db)
    return await service.list_all_tools()


@router.get("/{tool_id}", response_model=ToolRegistryEntryResponse)
async def get_tool(
    tool_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single tool by ID."""
    service = ToolManagementService(db)
    return await service.get_tool(tool_id)


# ---------------------------------------------------------------------------
# Write endpoints — app_admin only
# ---------------------------------------------------------------------------

@router.post("", response_model=ToolRegistryEntryResponse, status_code=201)
async def create_tool(
    tool_in: ToolRegistryEntryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(app_admin_only),
):
    """Create a new custom tool (app_admin only)."""
    service = ToolManagementService(db)
    return await service.create_tool(tool_in, current_user.company_id, current_user.id)


@router.put("/{tool_id}", response_model=ToolRegistryEntryResponse)
async def update_tool(
    tool_id: UUID,
    tool_in: ToolRegistryEntryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(app_admin_only),
):
    """Update a tool (app_admin only)."""
    service = ToolManagementService(db)
    return await service.update_tool(tool_id, tool_in)


@router.delete("/{tool_id}")
async def delete_tool(
    tool_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(app_admin_only),
):
    """Delete a custom tool (app_admin only). Built-in tools cannot be deleted."""
    service = ToolManagementService(db)
    await service.delete_tool(tool_id)
    return {"status": "success", "message": "Tool deleted"}


@router.post("/{tool_id}/toggle", response_model=ToolRegistryEntryResponse)
async def toggle_tool(
    tool_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(app_admin_only),
):
    """Toggle enabled/disabled state for a tool (app_admin only)."""
    service = ToolManagementService(db)
    return await service.toggle_tool(tool_id)


@router.post("/sync-built-in")
async def sync_built_in_tools(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(app_admin_only),
):
    """Seed/update DB entries for all built-in tools (app_admin only)."""
    service = ToolManagementService(db)
    created = await service.sync_built_in_tools()
    return {"status": "success", "created": created}
