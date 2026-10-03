"""A task default's fallback is another active, billable integration (P9.12 — LP-08).

Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

import src.auth.models  # noqa: F401 — registers Company for the relationship
from src.config.models import IntegrationRegistry
from src.config.service import ConfigService

pytestmark = pytest.mark.needs_db


async def _model(db, company_id, model, skus=("in", "out")):
    rows = [IntegrationRegistry(company_id=company_id, provider_name="google", model_name=model,
                                service_sku=f"{model}-{side}", service_category="LLM",
                                component_type=f"{side}put_token", internal_cost=Decimal("0.3"),
                                cost_unit="per_million_tokens") for side in skus]
    db.add_all(rows)
    await db.flush()
    return rows[0]


@pytest.fixture
def svc(db, monkeypatch):
    # set_task_default commits; keep the test's transaction open.
    async def flush():
        await db.flush()
    monkeypatch.setattr(db, "commit", flush)
    return ConfigService(db)


@pytest.mark.asyncio
async def test_a_billable_fallback_is_stored_and_resolved(db, svc, test_company_id):
    primary = await _model(db, test_company_id, f"p9-main-{uuid.uuid4().hex[:6]}")
    spare = await _model(db, test_company_id, f"p9-spare-{uuid.uuid4().hex[:6]}")

    row = await svc.set_task_default(test_company_id, "text_generation", primary.id,
                                     fallback_integration_id=spare.id)

    assert row.fallback_integration_id == spare.id
    integration, _ = await svc.resolve_fallback_for_task(test_company_id, "text_generation")
    assert integration.id == spare.id


@pytest.mark.asyncio
async def test_the_fallback_must_be_another_integration(db, svc, test_company_id):
    primary = await _model(db, test_company_id, f"p9-main-{uuid.uuid4().hex[:6]}")
    with pytest.raises(HTTPException) as err:
        await svc.set_task_default(test_company_id, "text_generation", primary.id,
                                   fallback_integration_id=primary.id)
    assert err.value.status_code == 422


@pytest.mark.asyncio
async def test_an_unbillable_fallback_model_is_refused(db, svc, test_company_id):
    primary = await _model(db, test_company_id, f"p9-main-{uuid.uuid4().hex[:6]}")
    spare = await _model(db, test_company_id, f"p9-spare-{uuid.uuid4().hex[:6]}", skus=("in",))
    with pytest.raises(HTTPException) as err:
        await svc.set_task_default(test_company_id, "text_generation", primary.id,
                                   fallback_integration_id=spare.id)
    assert err.value.status_code == 422 and "-out" in err.value.detail


@pytest.mark.asyncio
async def test_no_fallback_resolves_to_nothing(db, svc, test_company_id):
    primary = await _model(db, test_company_id, f"p9-main-{uuid.uuid4().hex[:6]}")
    await svc.set_task_default(test_company_id, "text_generation", primary.id)
    assert await svc.resolve_fallback_for_task(test_company_id, "text_generation") == (None, None)
