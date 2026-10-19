"""Seed (idempotently) the hosting and database SKUs — Phase 14 WS6 6.12.

Tenant apps and databases are metered against IntegrationRegistry SKUs of the
platform (APP) company (``src/apps/metering.py``):

    app-hosting-vcpu-hour   per vCPU-hour requested
    app-hosting-gb-hour     per GB-hour of memory requested
    app-egress-gb           per GB sent out
    tenant-db-pool-share    a pool server's daily price (split among its tenants)
    tenant-db-dedicated     a dedicated server's daily price

Without a row, use is still recorded in ``app_usage`` and nothing is billed.

    .venv/bin/python -m scripts.seed_app_skus
    APP_SKU_VCPU_HOUR=0.05 .venv/bin/python -m scripts.seed_app_skus
"""
from __future__ import annotations

import asyncio
import os
import uuid

from sqlalchemy import text

from src.common.database import AsyncSessionLocal

SKUS = (
    ("app-hosting-vcpu-hour", "per_vcpu_hour", os.environ.get("APP_SKU_VCPU_HOUR", "0.045")),
    ("app-hosting-gb-hour", "per_gb_hour", os.environ.get("APP_SKU_GB_HOUR", "0.005")),
    ("app-egress-gb", "per_gb", os.environ.get("APP_SKU_EGRESS_GB", "0.087")),
    ("tenant-db-pool-share", "per_day", os.environ.get("TENANT_DB_POOL_DAY", "4.50")),
    ("tenant-db-dedicated", "per_day", os.environ.get("TENANT_DB_DEDICATED_DAY", "9.00")),
)


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        app = (await db.execute(text("SELECT id FROM companies WHERE type='APP' LIMIT 1"))).first()
        if app is None:
            print("No APP company found; cannot seed the hosting SKUs.")
            return
        for sku, unit, cost in SKUS:
            existing = (await db.execute(text(
                "SELECT id FROM integration_registry WHERE company_id = :c AND service_sku = :sku"),
                {"c": str(app[0]), "sku": sku})).first()
            if existing is not None:
                await db.execute(text(
                    "UPDATE integration_registry SET internal_cost = :cost, cost_unit = :unit, status = 'active', "
                    "updated_at = now() WHERE id = :id"), {"cost": cost, "unit": unit, "id": str(existing[0])})
                print(f"Updated {sku} ({cost} {unit})")
                continue
            await db.execute(text(
                "INSERT INTO integration_registry (id, company_id, provider_name, model_name, service_sku, "
                "component_type, service_category, status, internal_cost, cost_unit, created_at, updated_at) "
                "VALUES (:id, :c, 'hirebuddha', :sku, :sku, 'hosting', 'OTHER', 'active', :cost, :unit, now(), now())"),
                {"id": str(uuid.uuid4()), "c": str(app[0]), "sku": sku, "cost": cost, "unit": unit})
            print(f"Seeded {sku} ({cost} {unit})")
        await db.commit()


if __name__ == "__main__":
    asyncio.run(seed())
