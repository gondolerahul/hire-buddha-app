#!/usr/bin/env python3
"""
seed_integration_registry.py
----------------------------
Seeds the APP company's integration registry and model task defaults so a
fresh local database can run agents end to end (LLM + embeddings).

WHAT IT CREATES (APP company, idempotent — existing SKUs are skipped):
  • gemini-2.5-flash-in / -out   LLM on Vertex AI (input + output token SKUs)
  • text-embedding-005-in        Embeddings on Vertex AI (768 dims — matches
                                 the Vector(768) columns)
  • model_task_defaults for text_generation, thinking, vision,
    goal_validation and embedding

Vertex AI authenticates with Application Default Credentials, so no real key is
stored: the router still requires a non-empty key (LP-12), so the documented
placeholder ``vertex-ai-service-account`` is written instead.

Prices are Vertex list prices (USD) and use the cost_unit spellings that
UsageService recognises (``per_million_tokens`` / ``per_million_characters``).

USAGE (from backend/, after seed_admin_user.py):
  VERTEX_PROJECT_ID=my-gcp-project python db-scripts/seed_integration_registry.py

  VERTEX_PROJECT_ID  required — GCP project the Vertex calls are billed to
  VERTEX_REGION      optional — defaults to us-central1
"""

import asyncio
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from sqlalchemy import select

from src.auth.models import Company
from src.common.database import AsyncSessionLocal
from src.config.models import IntegrationRegistry
from src.config.schemas import IntegrationRegistryCreate
from src.config.service import ConfigService

VERTEX_PLACEHOLDER_KEY = "vertex-ai-service-account"

LLM_MODEL = "gemini-2.5-flash"
EMBEDDING_MODEL = "text-embedding-005"

# (sku, model, category, component_type, internal_cost, cost_unit)
ENTRIES = [
    (f"{LLM_MODEL}-in", LLM_MODEL, "LLM", "input_token", Decimal("0.30"), "per_million_tokens"),
    (f"{LLM_MODEL}-out", LLM_MODEL, "LLM", "output_token", Decimal("2.50"), "per_million_tokens"),
    (f"{EMBEDDING_MODEL}-in", EMBEDDING_MODEL, "EMBEDDING", "character", Decimal("0.025"), "per_million_characters"),
]

# task_type -> SKU of the integration that serves it
TASK_DEFAULTS = {
    "text_generation": f"{LLM_MODEL}-in",
    "thinking": f"{LLM_MODEL}-in",
    "vision": f"{LLM_MODEL}-in",
    "goal_validation": f"{LLM_MODEL}-in",
    "embedding": f"{EMBEDDING_MODEL}-in",
}


async def seed(project_id: str, region: str) -> None:
    async with AsyncSessionLocal() as db:
        app_company = (await db.execute(
            select(Company).where(Company.type == "APP")
        )).scalars().first()
        if app_company is None:
            sys.exit("  [FAIL] No APP company — run db-scripts/seed_admin_user.py first")

        svc = ConfigService(db)
        by_sku: dict[str, IntegrationRegistry] = {}
        for sku, model, category, component, cost, unit in ENTRIES:
            existing = (await db.execute(
                select(IntegrationRegistry).where(
                    IntegrationRegistry.company_id == app_company.id,
                    IntegrationRegistry.service_sku == sku,
                )
            )).scalar_one_or_none()
            if existing:
                print(f"  [SKIP] {sku} already registered  → id={existing.id}")
                by_sku[sku] = existing
                continue
            entry = await svc.create_registry_entry(IntegrationRegistryCreate(
                company_id=app_company.id,
                provider_name="google",
                model_name=model,
                service_sku=sku,
                service_category=category,
                component_type=component,
                internal_cost=cost,
                cost_unit=unit,
                service_metadata={"project_id": project_id, "region": region},
                api_key=VERTEX_PLACEHOLDER_KEY,
            ))
            print(f"  [OK]   {sku} ({category}, ${cost} {unit})  → id={entry.id}")
            by_sku[sku] = entry

        for task_type, sku in TASK_DEFAULTS.items():
            await svc.set_task_default(app_company.id, task_type, by_sku[sku].id)
            print(f"  [OK]   task default {task_type:<16} → {sku}")


if __name__ == "__main__":
    project = os.getenv("VERTEX_PROJECT_ID")
    if not project:
        sys.exit("VERTEX_PROJECT_ID is required (the GCP project Vertex calls bill to)")
    region = os.getenv("VERTEX_REGION", "us-central1")
    print("=" * 60)
    print("  HireBuddha — Integration Registry Seed Script")
    print("=" * 60)
    print(f"  Vertex project: {project}  region: {region}")
    print()
    asyncio.run(seed(project, region))
    print()
    print("  Done ✓")
    print("=" * 60)
