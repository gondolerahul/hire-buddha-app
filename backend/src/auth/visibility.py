"""Which companies a user may see (AU-20).

One rule, used everywhere a query is scoped by company:

- ``app_admin``: every company (``None``).
- ``partner_admin``, ``partner_user``: their own company and its tenants
  (companies whose ``parent_id`` is theirs).
- everyone else: their own company.

This is visibility only. What a role may *do* is a separate check at each
route — a ``partner_user`` sees its tenants' entities but may not list users.
Before this module the rule was written out five times (users, companies,
entity create/list/read, phone-number assignment); the entity list ran one
query per child tenant.
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import Company
from src.auth.roles import Role

PARTNER_ROLES: frozenset[Role] = frozenset({Role.PARTNER_ADMIN, Role.PARTNER_USER})


async def company_scope(db: AsyncSession, company_id: UUID, role: Optional[str]) -> Optional[frozenset[UUID]]:
    """The companies a ``role`` user of ``company_id`` may see; ``None`` means all of them."""
    if role == Role.APP_ADMIN:
        return None
    if role in PARTNER_ROLES:
        children = (await db.execute(select(Company.id).where(Company.parent_id == company_id))).scalars().all()
        return frozenset({company_id, *children})
    return frozenset({company_id})


async def visible_company_ids(db: AsyncSession, user: Any) -> Optional[frozenset[UUID]]:
    """``company_scope`` for a signed-in user."""
    return await company_scope(db, user.company_id, user.role)


def in_scope(scope: Optional[frozenset[UUID]], company_id: Optional[UUID]) -> bool:
    return scope is None or company_id in scope
