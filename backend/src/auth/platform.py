"""The platform (APP) company: one place to find it (LP-21).

The APP company owns the platform's integrations, prices and task defaults;
every tenant falls back to it. Six places used to read it with
``WHERE type = 'APP' LIMIT 1`` and no order, so two APP companies meant a
non-deterministic fallback — a run could use either one's key and cost basis.
The partial unique index ``uq_companies_one_app`` (migration
``p9_one_app_company``) keeps a second one out; the order makes the answer
deterministic on a database the index could not be built on.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import Company


def platform_company_query() -> Select:
    """``SELECT id`` of the APP company, oldest first, one row."""
    return (select(Company.id).where(Company.type == "APP")
            .order_by(Company.created_at, Company.id).limit(1))


async def platform_company_id(db: AsyncSession) -> Optional[UUID]:
    return (await db.execute(platform_company_query())).scalar_one_or_none()
