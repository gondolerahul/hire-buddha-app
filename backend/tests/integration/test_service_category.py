"""Integration categories are one list (P9.4 — LP-11).

``integration_registry.service_category`` was free text: the column comment
named ``IMAGE_GEN`` / ``VIDEO_GEN``, the resolvers queried
``IMAGE_GENERATION`` / ``VIDEO_GENERATION``, and the create modal offered a
third list — a row made by the comment was never found. ``ServiceCategory`` is
the list: the API validates against it, the code queries with it, and
``p9_service_category`` holds the column to it. Real Postgres, rolled back.
"""
from __future__ import annotations

import pathlib
import re
import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from src.config.models import IntegrationRegistry, ServiceCategory
from src.config.schemas import IntegrationRegistryCreate, IntegrationRegistryUpdate

pytestmark = pytest.mark.needs_db

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"


def _create(category: str) -> IntegrationRegistryCreate:
    return IntegrationRegistryCreate(
        company_id=uuid.uuid4(), provider_name="google", service_sku="x", service_category=category,
        component_type="image", internal_cost=Decimal("0.04"), cost_unit="per_image", api_key="k")


def test_the_api_accepts_only_the_list():
    assert _create("IMAGE_GENERATION").service_category == ServiceCategory.IMAGE_GENERATION
    for spelling in ("IMAGE_GEN", "VIDEO_GEN", "llm", "API"):
        with pytest.raises(ValidationError):
            _create(spelling)
    with pytest.raises(ValidationError):
        IntegrationRegistryUpdate(service_category="IMAGE_GEN")


def test_the_code_queries_no_category_outside_the_list():
    literal = re.compile(r"""service_category\s*(?:==|!=)\s*["']([A-Za-z_0-9]+)["']""")
    found = {m for p in SRC.rglob("*.py") for m in literal.findall(p.read_text(encoding="utf-8"))}
    assert found - {c.value for c in ServiceCategory} == set()


@pytest.mark.asyncio
async def test_the_database_refuses_a_category_outside_the_list(db, test_company_id):
    db.add(IntegrationRegistry(company_id=test_company_id, provider_name="google", service_sku="p9-img",
                               service_category="IMAGE_GEN", component_type="image",
                               internal_cost=Decimal("0.04"), cost_unit="per_image"))
    with pytest.raises(IntegrityError):
        await db.flush()


@pytest.mark.asyncio
async def test_a_listed_category_is_stored(db, test_company_id):
    row = IntegrationRegistry(company_id=test_company_id, provider_name="google", service_sku="p9-img",
                              service_category=ServiceCategory.IMAGE_GENERATION, component_type="image",
                              internal_cost=Decimal("0.04"), cost_unit="per_image")
    db.add(row)
    await db.flush()
    await db.refresh(row)
    assert row.service_category == "IMAGE_GENERATION"
