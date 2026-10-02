"""Packaging and tool metadata (P6.9 — TL-66, TL-34, TL-35).

- TL-66: ``weasyprint``, ``markdown``, ``ddgs`` and ``playwright`` were not
  declared, so three ACTIVE tools were dead on a clean install. Declared now —
  and a host without WeasyPrint's system libraries (Pango) must not break the
  import of every tool, which installing it did on Windows.
- TL-34: ``sync_built_in_tools`` never updated an existing row, and the list
  preferred the row's description and schema, so the admin page drifted from
  the code forever.
- TL-35: a hand-written map gave 22 of 98 tools a category.

Real Postgres, rolled back.
"""
from __future__ import annotations

import pathlib
import tomllib

import pytest
from sqlalchemy import select

import src.ai.tools  # noqa: F401  (registers every tool)
from src.ai.models import ToolRegistryEntry
from src.ai.tool_management_service import ToolManagementService
from src.ai.tools.base import ToolRegistry, tool_category

BACKEND = pathlib.Path(__file__).resolve().parents[2]


def test_the_tools_dependencies_are_declared():
    deps = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["poetry"]["dependencies"]
    assert {"weasyprint", "markdown", "ddgs", "playwright"} <= set(deps)


def test_a_host_without_pango_still_registers_the_pdf_tool():
    import src.ai.tools.documents.pdf_generator as pdf
    assert "pdf_generator" in ToolRegistry._tools
    if pdf.HTML is None:  # this host has no Pango: the call, not the import, says so
        assert pdf._WEASYPRINT_ERROR


def test_every_tool_has_a_category_from_its_package():
    assert {n: tool_category(t) for n, t in ToolRegistry._tools.items() if tool_category(t) == "general"} == {}
    assert tool_category(ToolRegistry._tools["email_send"]) == "email"
    assert tool_category(ToolRegistry._tools["web_search"]) == "search"        # a tool may refine it


@pytest.mark.asyncio
async def test_sync_brings_existing_rows_up_to_date_and_keeps_the_admins_state(db):
    stale = ToolRegistryEntry(name="calculator", display_name="Calc (admin's name)", description="old words",
                              category="general", tool_type="BUILT_IN", function_schema={"stale": True},
                              is_enabled=False)
    db.add(stale)
    await db.flush()
    svc = ToolManagementService(db)

    counts = await svc.sync_built_in_tools()

    assert counts["updated"] >= 1 and counts["created"] >= 0
    row = (await db.execute(select(ToolRegistryEntry).where(
        ToolRegistryEntry.name == "calculator", ToolRegistryEntry.company_id.is_(None)))).scalar_one()
    tool = ToolRegistry._tools["calculator"]
    assert (row.description, row.category, row.function_schema) == (
        tool.description, "utility", tool.get_function_schema())
    assert (row.is_enabled, row.display_name) == (False, "Calc (admin's name)")
    assert (await svc.sync_built_in_tools()) == {"created": 0, "updated": 0}       # nothing left to do


@pytest.mark.asyncio
async def test_the_list_shows_the_codes_description_whatever_the_row_says(db):
    db.add(ToolRegistryEntry(name="calculator", display_name="calculator", description="old words",
                             category="general", tool_type="BUILT_IN", function_schema={"stale": True},
                             is_enabled=True))
    await db.flush()
    [listed] = [t for t in await ToolManagementService(db).list_all_tools() if t["name"] == "calculator"]
    assert listed["description"] == ToolRegistry._tools["calculator"].description
    assert listed["function_schema"] == ToolRegistry._tools["calculator"].get_function_schema()
    assert listed["category"] == "utility"
