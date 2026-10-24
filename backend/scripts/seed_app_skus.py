"""Seed (idempotently) the hosting and database SKUs — Phase 14 WS6 6.12.

Tenant apps and databases are metered against IntegrationRegistry SKUs of the
platform (APP) company (``src/apps/metering.py``):

    app-hosting-vcpu-hour   per vCPU-hour requested
    app-hosting-gb-hour     per GB-hour of memory requested
    app-egress-gb           per GB sent out
    tenant-db-pool-share    a pool server's daily price (split among its tenants)
    tenant-db-dedicated     a dedicated server's daily price
    app-build-second        per second of build (Phase 15 T7-3)
    app-storage-gb-month    per GB-month of app files (sampled daily)
    tenant-db-storage-gb-month  per GB-month of database size (sampled daily)
    tenant-backup-gb-month  per GB-month of kept weekly exports
    custom-domain-month     per verified custom domain a month

The costs are indicative base costs (tech design §9): staff set them from the
Azure invoice; the formula adds the margin.

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
    ("app-hosting-vcpu-hour", "PER_VCPU_HOUR", os.environ.get("APP_SKU_VCPU_HOUR", "0.045")),
    ("app-hosting-gb-hour", "PER_GB_HOUR", os.environ.get("APP_SKU_GB_HOUR", "0.005")),
    ("app-egress-gb", "PER_GB", os.environ.get("APP_SKU_EGRESS_GB", "0.087")),
    ("tenant-db-pool-share", "PER_DAY", os.environ.get("TENANT_DB_POOL_DAY", "4.50")),
    ("tenant-db-dedicated", "PER_DAY", os.environ.get("TENANT_DB_DEDICATED_DAY", "9.00")),
    ("app-build-second", "PER_SECOND", os.environ.get("APP_SKU_BUILD_SECOND", "0.0001")),
    ("app-storage-gb-month", "PER_GB_MONTH", os.environ.get("APP_SKU_STORAGE_GB_MONTH", "0.02")),
    ("tenant-db-storage-gb-month", "PER_GB_MONTH", os.environ.get("TENANT_DB_STORAGE_GB_MONTH", "0.12")),
    ("tenant-backup-gb-month", "PER_GB_MONTH", os.environ.get("TENANT_BACKUP_GB_MONTH", "0.05")),
    ("custom-domain-month", "PER_MONTH", os.environ.get("APP_SKU_CUSTOM_DOMAIN_MONTH", "1.00")),
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
                    "UPDATE integration_registry SET internal_cost = :cost, cost_unit_code = :unit, status = 'active', "
                    "updated_at = now() WHERE id = :id"), {"cost": cost, "unit": unit, "id": str(existing[0])})
                print(f"Updated {sku} ({cost} {unit})")
                continue
            await db.execute(text(
                "INSERT INTO integration_registry (id, company_id, provider_name, model_name, service_sku, "
                "component_type, service_category, status, internal_cost, cost_unit_code, created_at, updated_at) "
                "VALUES (:id, :c, 'hirebuddha', :sku, :sku, 'hosting', 'OTHER', 'active', :cost, :unit, now(), now())"),
                {"id": str(uuid.uuid4()), "c": str(app[0]), "sku": sku, "cost": cost, "unit": unit})
            print(f"Seeded {sku} ({cost} {unit})")
        await db.commit()


if __name__ == "__main__":
    asyncio.run(seed())
