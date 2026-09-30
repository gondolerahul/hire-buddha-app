"""
Tool Management Service — CRUD for tool registry entries.

Merges built-in tools (from ToolRegistry) with DB-backed custom tools.
Provides create/read/update/delete operations for admin-managed tools.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, List, Optional
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException

from src.ai.models import ToolRegistryEntry
from src.ai.schemas import (
    ToolRegistryEntryCreate,
    ToolRegistryEntryUpdate,
    ToolRegistryEntryResponse,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool category mapping for built-in tools
# ---------------------------------------------------------------------------
_BUILTIN_CATEGORIES = {
    "calculator": "utility",
    "web_search": "search",
    "excel_tool": "document",
    "scraper_tool": "browser",
    "pdf_generator": "document",
    "file_writer": "document",
    "email_ingest": "email",
    "email_classify": "email",
    "email_draft": "email",
    "email_send": "email",
    "image_generation": "media",
    "video_generate": "media",
    "video_edit": "media",
    "video_add_sound": "media",
    "sandbox_code": "execution",
    "terminal": "execution",
    "headless_browser": "browser",
    "docx_tool": "document",
    "pptx_tool": "document",
    "document_save": "document",
}


class ToolManagementService:
    """Service for managing the tool registry."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # List all tools (built-in + custom from DB)
    # ------------------------------------------------------------------

    async def _visible_entries(self, viewer: Any = None):
        """A SELECT of the entries ``viewer`` may see (DM-08).

        Built-in rows (no company) and the platform's own custom tools (the APP
        company's) for everyone; otherwise only the companies the viewer can see
        (``auth.visibility``). ``app_admin`` — and internal callers passing no
        viewer — see every row. Before this, any signed-in user listed every
        tenant's synthesized tools, source and audit included.
        """
        from sqlalchemy import or_
        from src.auth.models import Company
        from src.auth.visibility import visible_company_ids

        stmt = select(ToolRegistryEntry)
        if viewer is None:
            return stmt
        scope = await visible_company_ids(self.db, viewer)
        if scope is None:
            return stmt
        platform = select(Company.id).where(Company.type == "APP")
        return stmt.where(or_(
            ToolRegistryEntry.company_id.is_(None),
            ToolRegistryEntry.company_id.in_(platform),
            ToolRegistryEntry.company_id.in_(scope),
        ))

    async def list_all_tools(self, viewer: Any = None) -> List[dict]:
        """
        Return a merged list of the tools ``viewer`` may see.
        - Built-in tools from the in-memory ToolRegistry, with their DB row's
          metadata (e.g. is_enabled) when there is one
        - Custom and synthesized tools from the DB
        """
        from src.ai.tools import ToolRegistry

        # 1. DB entries: built-in rows keyed by name; every other row listed as is
        #    (a name is unique per company, so two tenants may share one).
        result = await self.db.execute(await self._visible_entries(viewer))
        rows = result.scalars().all()
        db_entries = {entry.name: entry for entry in rows if entry.company_id is None}
        other_entries = [entry for entry in rows if entry.company_id is not None]

        # 2. Get built-in tools
        built_in_tools = ToolRegistry.list_tools()  # [{name, description}]
        all_schemas = {
            t.name: t.get_function_schema()
            for t in ToolRegistry._tools.values()
        }

        merged = []

        # 3. Merge built-in tools with DB entries
        for tool_info in built_in_tools:
            name = tool_info["name"]
            db_entry = db_entries.pop(name, None)

            if db_entry:
                merged.append({
                    "id": str(db_entry.id),
                    "name": db_entry.name,
                    "display_name": db_entry.display_name or name,
                    "description": db_entry.description or tool_info["description"],
                    "category": db_entry.category or _BUILTIN_CATEGORIES.get(name, "general"),
                    "tool_type": "BUILT_IN",
                    "function_schema": db_entry.function_schema or all_schemas.get(name),
                    "is_enabled": db_entry.is_enabled,
                    "created_at": db_entry.created_at.isoformat() if db_entry.created_at else None,
                    "updated_at": db_entry.updated_at.isoformat() if db_entry.updated_at else None,
                })
            else:
                merged.append({
                    "id": None,
                    "name": name,
                    "display_name": name,
                    "description": tool_info["description"],
                    "category": _BUILTIN_CATEGORIES.get(name, "general"),
                    "tool_type": "BUILT_IN",
                    "function_schema": all_schemas.get(name),
                    "is_enabled": True,
                    "created_at": None,
                    "updated_at": None,
                })

        # 4. Add remaining DB-only entries (custom and synthesized tools)
        for db_entry in [*db_entries.values(), *other_entries]:
            name = db_entry.name
            merged.append({
                "id": str(db_entry.id),
                "company_id": str(db_entry.company_id) if db_entry.company_id else None,
                "name": db_entry.name,
                "display_name": db_entry.display_name or name,
                "description": db_entry.description,
                "category": db_entry.category or "custom",
                "tool_type": db_entry.tool_type,
                "function_schema": db_entry.function_schema,
                "is_enabled": db_entry.is_enabled,
                "configuration": db_entry.configuration,
                "created_at": db_entry.created_at.isoformat() if db_entry.created_at else None,
                "updated_at": db_entry.updated_at.isoformat() if db_entry.updated_at else None,
            })

        return merged

    # ------------------------------------------------------------------
    # CRUD for custom tools
    # ------------------------------------------------------------------

    async def create_tool(
        self,
        data: ToolRegistryEntryCreate,
        company_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> ToolRegistryEntry:
        """Create a new custom tool entry."""
        # Check if name conflicts with a built-in tool
        from src.ai.tools import ToolRegistry
        if ToolRegistry.get_tool(data.name):
            raise HTTPException(
                status_code=409,
                detail=f"Tool name '{data.name}' conflicts with a built-in tool. Choose a different name.",
            )

        entry = ToolRegistryEntry(
            id=uuid.uuid4(),
            company_id=company_id,
            name=data.name,
            display_name=data.display_name or data.name,
            description=data.description,
            category=data.category,
            tool_type="CUSTOM",
            function_schema=data.function_schema,
            is_enabled=data.is_enabled,
            configuration=data.configuration,
            created_by=user_id,
        )
        self.db.add(entry)
        try:
            await self.db.commit()
            await self.db.refresh(entry)
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"Tool with name '{data.name}' already exists.",
            )
        return entry

    async def get_tool(self, tool_id: uuid.UUID, viewer: Any = None) -> ToolRegistryEntry:
        """Get a tool entry by ID; 404 when ``viewer`` may not see it."""
        result = await self.db.execute(
            (await self._visible_entries(viewer)).where(ToolRegistryEntry.id == tool_id)
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise HTTPException(status_code=404, detail="Tool not found")
        return entry

    async def get_built_in_entry(self, name: str) -> Optional[ToolRegistryEntry]:
        """The DB row of built-in tool ``name`` (company_id NULL), if seeded."""
        result = await self.db.execute(
            select(ToolRegistryEntry).where(
                ToolRegistryEntry.name == name,
                ToolRegistryEntry.company_id.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def update_tool(
        self,
        tool_id: uuid.UUID,
        data: ToolRegistryEntryUpdate,
    ) -> ToolRegistryEntry:
        """Update a tool entry (custom tools only for most fields)."""
        entry = await self.get_tool(tool_id)

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(entry, key, value)
        entry.updated_at = datetime.utcnow()

        await self.db.commit()
        await self.db.refresh(entry)
        return entry

    async def delete_tool(self, tool_id: uuid.UUID) -> None:
        """Delete a custom tool entry. Built-in tools cannot be deleted."""
        entry = await self.get_tool(tool_id)
        if entry.tool_type == "BUILT_IN":
            raise HTTPException(
                status_code=403,
                detail="Built-in tools cannot be deleted. You can disable them instead.",
            )
        await self.db.delete(entry)
        await self.db.commit()

    async def toggle_tool(self, tool_id: uuid.UUID) -> ToolRegistryEntry:
        """Toggle the enabled state of a tool."""
        entry = await self.get_tool(tool_id)
        entry.is_enabled = not entry.is_enabled
        entry.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(entry)
        return entry

    # ------------------------------------------------------------------
    # Sync built-in tools to DB
    # ------------------------------------------------------------------

    async def sync_built_in_tools(self) -> int:
        """
        Seed/update DB rows for all built-in tools.
        Returns number of new entries created.
        """
        from src.ai.tools import ToolRegistry

        built_in_tools = ToolRegistry._tools
        created = 0

        for name, tool in built_in_tools.items():
            existing = await self.get_built_in_entry(name)
            if not existing:
                entry = ToolRegistryEntry(
                    id=uuid.uuid4(),
                    name=name,
                    display_name=name,
                    description=tool.description,
                    category=_BUILTIN_CATEGORIES.get(name, "general"),
                    tool_type="BUILT_IN",
                    function_schema=tool.get_function_schema(),
                    is_enabled=True,
                )
                self.db.add(entry)
                created += 1

        if created:
            await self.db.commit()

        return created
