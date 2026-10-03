"""Tool names are unique per company, and tenants see only their own tools (DM-08).

``tool_registry_entries.name`` was globally unique, but synthesized tools are
written per tenant: a second tenant synthesizing a same-named tool failed. And
``GET /ai/tool-registry`` returned every tenant's synthesized tools — spec,
source and audit in ``configuration`` — to any signed-in user.

Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.needs_db


async def _company(db, kind="TENANT"):
    from src.auth.models import Company
    c = Company(name=f"dm08-{uuid.uuid4().hex[:6]}", type=kind, status="active")
    db.add(c)
    await db.flush()
    return c


async def _platform(db):
    """The APP company: there is at most one (LP-21)."""
    from src.auth.models import Company
    from src.auth.platform import platform_company_id
    found = await platform_company_id(db)
    return await db.get(Company, found) if found else await _company(db, "APP")


def _entry(company_id, name, tool_type="SYNTHESIZED"):
    from src.ai.orm.tools import ToolRegistryEntry
    return ToolRegistryEntry(company_id=company_id, name=name, tool_type=tool_type,
                             configuration={"source": f"secret source of {company_id}"})


@pytest.mark.asyncio
async def test_two_tenants_may_use_the_same_tool_name(db):
    a, b = await _company(db), await _company(db)
    name = f"crm_sync_{uuid.uuid4().hex[:6]}"
    db.add_all([_entry(a.id, name), _entry(b.id, name)])
    await db.flush()


@pytest.mark.asyncio
async def test_one_company_may_not_reuse_a_name(db):
    a = await _company(db)
    name = f"crm_sync_{uuid.uuid4().hex[:6]}"
    db.add(_entry(a.id, name))
    await db.flush()
    db.add(_entry(a.id, name))
    with pytest.raises(IntegrityError):
        await db.flush()


@pytest.mark.asyncio
async def test_built_in_names_stay_unique(db):
    name = f"builtin_{uuid.uuid4().hex[:6]}"
    db.add(_entry(None, name, "BUILT_IN"))
    await db.flush()
    db.add(_entry(None, name, "BUILT_IN"))
    with pytest.raises(IntegrityError):
        await db.flush()


@pytest.mark.asyncio
async def test_a_tenant_lists_its_own_and_platform_tools_only(db):
    from src.ai.tool_management_service import ToolManagementService

    mine, theirs, platform = await _company(db), await _company(db), await _platform(db)
    own, other, shared = (f"t_{uuid.uuid4().hex[:6]}" for _ in range(3))
    db.add_all([_entry(mine.id, own), _entry(theirs.id, other), _entry(platform.id, shared, "CUSTOM")])
    await db.flush()
    viewer = SimpleNamespace(role="tenant_user", company_id=mine.id)
    names = {t["name"] for t in await ToolManagementService(db).list_all_tools(viewer=viewer)}
    assert own in names and shared in names and other not in names
    admin = SimpleNamespace(role="app_admin", company_id=platform.id)
    assert other in {t["name"] for t in await ToolManagementService(db).list_all_tools(viewer=admin)}


@pytest.mark.asyncio
async def test_another_tenants_tool_is_a_404(db):
    from src.ai.tool_management_service import ToolManagementService

    mine, theirs = await _company(db), await _company(db)
    entry = _entry(theirs.id, f"t_{uuid.uuid4().hex[:6]}")
    db.add(entry)
    await db.flush()
    with pytest.raises(HTTPException) as exc:
        await ToolManagementService(db).get_tool(entry.id, viewer=SimpleNamespace(role="tenant_admin", company_id=mine.id))
    assert exc.value.status_code == 404


# ── TL-06 remainder (P3.8): the list carries no configuration ───────────────


@pytest.mark.asyncio
async def test_the_list_never_carries_configuration(db):
    from src.ai.tool_management_service import ToolManagementService

    mine = await _company(db)
    db.add(_entry(mine.id, f"t_{uuid.uuid4().hex[:6]}"))
    await db.flush()
    for viewer in (SimpleNamespace(role="tenant_user", company_id=mine.id),
                   SimpleNamespace(role="app_admin", company_id=mine.id)):
        listed = await ToolManagementService(db).list_all_tools(viewer=viewer)
        assert listed and not any("configuration" in t for t in listed)


@pytest.mark.asyncio
async def test_only_app_admin_reads_a_tools_configuration(db):
    from src.ai.tool_management_router import get_tool

    mine = await _company(db)
    entry = _entry(mine.id, f"t_{uuid.uuid4().hex[:6]}")
    db.add(entry)
    await db.flush()
    owner = SimpleNamespace(role="tenant_admin", company_id=mine.id, id=uuid.uuid4())
    admin = SimpleNamespace(role="app_admin", company_id=mine.id, id=uuid.uuid4())
    assert (await get_tool(entry.id, db=db, current_user=owner)).configuration is None
    assert (await get_tool(entry.id, db=db, current_user=admin)).configuration == entry.configuration
