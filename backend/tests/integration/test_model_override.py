"""An entity's model override resolves through the registry (P4.4, LP-05).

Before: the override replaced only the model name and kept the task default's
provider and key, so ``gpt-4o`` was sent to Vertex; and a model with no
``-in``/``-out`` SKU ran and billed $0. Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from src.ai.llm.router import LLMRouter
from src.common.security import encrypt_api_key
from src.config.models import IntegrationRegistry

pytestmark = pytest.mark.needs_db


async def _company(db):
    from src.auth.models import Company
    c = Company(name=f"p44-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    return c.id


def _row(company, model, sku_suffix, provider="anthropic", key="sk-test"):
    return IntegrationRegistry(
        company_id=company, provider_name=provider, service_sku=f"{model}-{sku_suffix}",
        model_name=model, component_type=f"{sku_suffix}put_token", internal_cost=Decimal("1"),
        cost_unit="per_1M_tokens", status="active", service_category="LLM",
        encrypted_api_key=encrypt_api_key(key),
    )


@pytest.mark.asyncio
async def test_an_override_brings_its_own_provider_and_key(db):
    company = await _company(db)
    model = f"claude-p44-{uuid.uuid4().hex[:4]}"
    db.add_all([_row(company, model, "in"), _row(company, model, "out")])
    await db.flush()
    from src.ai.llm.anthropic_adapter import AnthropicAdapter

    adapter = await LLMRouter(db=db, company_id=company)._resolve_adapter(
        "text_generation", model_override=model)
    assert isinstance(adapter, AnthropicAdapter)
    assert adapter.model_name == model


@pytest.mark.asyncio
async def test_an_override_with_no_billing_skus_is_refused(db):
    company = await _company(db)
    with pytest.raises(RuntimeError, match="no active, billable integration"):
        await LLMRouter(db=db, company_id=company)._resolve_adapter(
            "text_generation", model_override="gpt-4o-not-configured")


@pytest.mark.asyncio
async def test_an_override_billed_on_input_only_is_refused(db):
    company = await _company(db)
    model = f"half-billed-{uuid.uuid4().hex[:4]}"
    db.add(_row(company, model, "in"))
    await db.flush()
    with pytest.raises(RuntimeError, match="no active, billable integration"):
        await LLMRouter(db=db, company_id=company)._resolve_adapter(
            "text_generation", model_override=model)
