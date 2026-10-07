#!/usr/bin/env python3
"""Create the first-party social SKILLs for one company (P6.3).

Usage (from backend/):
    python scripts/seeds/default_entities/SeedSocialSkills/create_social_skills.py --company-id <uuid>

Idempotent: a SKILL whose name the company already has is skipped. The
company must also opt in to ``social_api`` (``tools.experimental.social_api``)
and connect each platform before the SKILLs can act.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from uuid import UUID

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.dirname(__file__))


async def create(company_id: UUID) -> list[str]:
    from sqlalchemy import select

    import src.main  # noqa: F401  (registers every model)
    from src.ai.orm import HierarchicalEntity
    from src.ai.schemas.entity import HierarchicalEntityCreate
    from src.ai.service import AIService
    from src.common.database import AsyncSessionLocal
    from skills import SKILLS

    created = []
    async with AsyncSessionLocal() as db:
        existing = set((await db.execute(select(HierarchicalEntity.name).where(
            HierarchicalEntity.company_id == company_id))).scalars())
        for payload in SKILLS:
            if payload["name"] in existing:
                print(f"  [SKIP] {payload['name']} exists")
                continue
            entity = await AIService(db).create_entity(HierarchicalEntityCreate(**payload), company_id)
            created.append(entity.name)
            print(f"  [OK]   {entity.name} -> {entity.id}")
    return created


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company-id", required=True, type=UUID)
    asyncio.run(create(parser.parse_args().company_id))
