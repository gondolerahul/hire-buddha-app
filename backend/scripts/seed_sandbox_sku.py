"""Seed (idempotently) the ``sandbox-runtime`` cost SKU — Phase 12 `02` S6.

Sandbox runtime time is metered against an IntegrationRegistry SKU owned by the
APP (platform) company, with cost_unit ``second`` so UsageService bills
``internal_cost * seconds``. Without this row, sandbox metering logs a warning
and records nothing (same as embedding before its SKU existed).

Run once per environment:

    .venv/bin/python -m scripts.seed_sandbox_sku
    SANDBOX_SKU_COST_PER_SECOND=0.00005 .venv/bin/python -m scripts.seed_sandbox_sku
"""
from __future__ import annotations

import asyncio
import os
import uuid

from sqlalchemy import text

from src.common.config import settings
from src.common.database import AsyncSessionLocal

_COST_PER_SECOND = os.environ.get("SANDBOX_SKU_COST_PER_SECOND", "0.000020")


async def seed() -> None:
    sku = settings.SANDBOX_COST_SKU
    async with AsyncSessionLocal() as db:
        app = (await db.execute(
            text("SELECT id FROM companies WHERE type='APP' LIMIT 1")
        )).first()
        if app is None:
            print("No APP company found; cannot seed the sandbox SKU.")
            return
        app_id = app[0]

        existing = (await db.execute(
            text(
                "SELECT id FROM integration_registry "
                "WHERE company_id = :c AND service_sku = :sku"
            ),
            {"c": str(app_id), "sku": sku},
        )).first()
        if existing is not None:
            await db.execute(
                text(
                    "UPDATE integration_registry "
                    "SET internal_cost = :cost, cost_unit = 'second', "
                    "    status = 'active', updated_at = now() "
                    "WHERE id = :id"
                ),
                {"cost": _COST_PER_SECOND, "id": str(existing[0])},
            )
            await db.commit()
            print(f"Updated sandbox SKU '{sku}' (${_COST_PER_SECOND}/sec) on APP {app_id}")
            return

        await db.execute(
            text(
                """
                INSERT INTO integration_registry (
                    id, company_id, provider_name, model_name, service_sku,
                    component_type, service_category, status,
                    internal_cost, cost_unit, created_at, updated_at
                ) VALUES (
                    :id, :c, 'hirebuddha', 'sandbox-runtime', :sku,
                    'sandbox', 'SANDBOX', 'active',
                    :cost, 'second', now(), now()
                )
                """
            ),
            {"id": str(uuid.uuid4()), "c": str(app_id), "sku": sku, "cost": _COST_PER_SECOND},
        )
        await db.commit()
        print(f"Seeded sandbox SKU '{sku}' (${_COST_PER_SECOND}/sec) on APP {app_id}")


if __name__ == "__main__":
    asyncio.run(seed())
