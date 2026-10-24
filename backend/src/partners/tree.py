"""The company tree and role rules (Phase 15 T8-1, tech design §11.2, §11.9; 04 E2).

* A TENANT's parent is the platform (APP) or a PARTNER; a PARTNER's is the
  platform or the partner that recruited it; the APP company has none, and
  there is one. Partners are at most ``partners.max_depth`` levels below the
  platform (O-9), and the tree has no cycles.
* Roles follow the company: ``app_*`` only in the APP company, ``partner_*``
  only in PARTNER companies, ``tenant_*`` only in TENANT companies.

``violations`` reports what the data breaks today (staff fix them by hand).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

APP, PARTNER, TENANT = "APP", "PARTNER", "TENANT"
COMPANY_TYPES = (APP, PARTNER, TENANT)
PARENTS: Dict[str, tuple] = {TENANT: (APP, PARTNER), PARTNER: (APP, PARTNER), APP: ()}
ROLE_PREFIX = {APP: "app_", PARTNER: "partner_", TENANT: "tenant_"}


class TreeProblem(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=422, detail=detail)


def role_fits(role: str, company_type: Optional[str]) -> bool:
    """Whether ``role`` belongs in a company of ``company_type``."""
    prefix = ROLE_PREFIX.get(str(company_type or "").upper())
    return prefix is not None and str(role).startswith(prefix)


async def require_role_fits(db: Any, role: str, company_id: UUID) -> None:
    from src.auth.models import Company

    kind = (await db.execute(select(Company.type).where(Company.id == company_id))).scalar_one_or_none()
    if not role_fits(role, kind):
        raise TreeProblem(f"a {role} cannot belong to a {kind or 'missing'} company "
                          "(app_* in the platform, partner_* in partners, tenant_* in tenants)")


async def partner_depth(db: Any, partner_id: UUID) -> int:
    """How many partner levels ``partner_id`` is below the platform (1: recruited by it)."""
    from src.auth.models import Company

    depth, seen, current = 0, set(), partner_id
    while current is not None and current not in seen:
        seen.add(current)
        row = (await db.execute(select(Company.type, Company.parent_id).where(Company.id == current))).first()
        if row is None or row.type != PARTNER:
            break
        depth += 1
        current = row.parent_id
    return depth


async def require_valid_parent(db: Any, company_type: str, parent_id: Optional[UUID], *,
                               company_id: Optional[UUID] = None) -> None:
    """422 unless a ``company_type`` company may sit under ``parent_id`` (and, when moving one, no cycle)."""
    from src.auth.models import Company
    from src.billing.settings_catalogue import value

    kind = str(company_type or "").upper()
    if kind not in COMPANY_TYPES:
        raise TreeProblem(f"a company is APP, PARTNER or TENANT, not {company_type!r}")
    if kind == APP:
        raise TreeProblem("there is one platform company; another cannot be created")
    if parent_id is None:
        return                                            # under the platform
    parent = (await db.execute(select(Company.type).where(Company.id == parent_id))).scalar_one_or_none()
    if parent is None:
        raise TreeProblem("the parent company does not exist")
    if parent not in PARENTS[kind]:
        raise TreeProblem(f"a {kind} cannot be under a {parent} (a tenant under the platform or a partner; "
                          "a partner under the platform or its recruiting partner)")
    if company_id is not None:
        current: Optional[UUID] = parent_id
        seen: set = set()
        while current is not None and current not in seen:
            if current == company_id:
                raise TreeProblem("that parent would make a cycle")
            seen.add(current)
            current = (await db.execute(select(Company.parent_id).where(Company.id == current))).scalar_one_or_none()
    if kind == PARTNER:
        limit = int(await value(db, "partners.max_depth"))
        if await partner_depth(db, parent_id) + 1 > limit:
            raise TreeProblem(f"partners are at most {limit} levels below the platform")


async def violations(db: Any) -> List[dict]:
    """What the tree and the roles break today (staff's report, T8-1)."""
    from src.auth.models import Company, User
    from src.billing.settings_catalogue import value

    out: List[dict] = []
    companies = {c.id: c for c in (await db.execute(select(Company))).scalars().all()}
    apps = [c for c in companies.values() if c.type == APP]
    if len(apps) != 1:
        out.append({"kind": "platform", "detail": f"{len(apps)} APP companies (one expected)"})
    limit = int(await value(db, "partners.max_depth"))
    for c in companies.values():
        if c.type not in COMPANY_TYPES:
            out.append({"kind": "type", "company_id": str(c.id), "name": c.name, "detail": f"type {c.type!r}"})
            continue
        parent = companies.get(c.parent_id) if c.parent_id else None
        if c.parent_id and parent is None:
            out.append({"kind": "parent", "company_id": str(c.id), "name": c.name, "detail": "parent missing"})
        elif parent is not None and parent.type not in PARENTS[c.type]:
            out.append({"kind": "parent", "company_id": str(c.id), "name": c.name,
                        "detail": f"a {c.type} under a {parent.type}"})
        seen, current, depth = set(), c, 0
        while current is not None and current.id not in seen:
            seen.add(current.id)
            if current.type == PARTNER:
                depth += 1
            current = companies.get(current.parent_id) if current.parent_id else None
        if current is not None:
            out.append({"kind": "cycle", "company_id": str(c.id), "name": c.name, "detail": "the tree loops"})
        elif c.type == PARTNER and depth > limit:
            out.append({"kind": "depth", "company_id": str(c.id), "name": c.name,
                        "detail": f"{depth} levels below the platform (at most {limit})"})
    for user in (await db.execute(select(User.id, User.email, User.role, User.company_id))).all():
        company = companies.get(user.company_id)
        if company is not None and not role_fits(user.role, company.type):
            out.append({"kind": "role", "user_id": str(user.id), "email": user.email,
                        "detail": f"a {user.role} in a {company.type} company"})
    return out
