"""One platform company, found one way; a provider matched exactly (P9.6 — LP-21).

Six readers took ``WHERE type = 'APP' LIMIT 1`` with no order, so two APP
companies made every tenant's fallback (keys, prices, task defaults)
non-deterministic; and ``get_integration_by_provider`` matched
``ILIKE '%name%'``. Real Postgres, rolled back.
"""
from __future__ import annotations

import pathlib
import re
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from src.auth.models import Company
from src.auth.platform import platform_company_id
from src.config.models import IntegrationRegistry
from src.config.service import ConfigService

pytestmark = pytest.mark.needs_db

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"


def test_only_the_helper_queries_the_app_company():
    query = re.compile(r"""type\s*==\s*["']APP["']""")
    readers = sorted(str(p.relative_to(SRC)) for p in SRC.rglob("*.py") if query.search(p.read_text(encoding="utf-8")))
    assert readers == ["auth\\platform.py"] or readers == ["auth/platform.py"]


@pytest.mark.asyncio
async def test_a_second_app_company_is_refused(db):
    assert await platform_company_id(db) is not None
    db.add(Company(name="second platform", type="APP", status="active"))
    with pytest.raises(IntegrityError):
        await db.flush()


@pytest.mark.asyncio
async def test_a_provider_is_matched_exactly(db, test_company_id):
    db.add(IntegrationRegistry(company_id=test_company_id, provider_name="googleplaces", service_sku="p9-places",
                               service_category="API_TOOL", component_type="flat_fee",
                               internal_cost=Decimal("0.01"), cost_unit="per_request"))
    db.add(IntegrationRegistry(company_id=test_company_id, provider_name="Google", model_name="gemini-x",
                               service_sku="p9-gemini-x-in", service_category="LLM",
                               component_type="input_token", internal_cost=Decimal("0.3"),
                               cost_unit="per_million_tokens"))
    await db.flush()

    svc = ConfigService(db)
    found = await svc.get_integration_by_provider(test_company_id, "google")

    assert found is not None and found.service_sku == "p9-gemini-x-in"  # not "googleplaces"
    assert await svc.get_integration_by_provider(test_company_id, "places") is None
