"""Control and tenant sessions (Phase 14 WS2 2.1/2.4, tech spec §5.3).

Code opens a session on the plane whose tables it works with:

* ``control_session()`` — the control database (replaces ``AsyncSessionLocal()``
  for identity, companies, billing, catalogues, the tenant directory);
* ``tenant_session(company_id)`` — the database holding that company's runs,
  agents, memory, documents, campaigns and calls;
* ``get_control_db`` / ``get_tenant_db`` — the same as FastAPI dependencies;
  ``get_tenant_db`` is the caller's own company.
* ``get_acting_tenant_db`` — for a route that reads or changes another
  company's rows (a partner's tenants' agents, any run for a platform admin):
  the **acting company**'s session — the ``X-Company-Id`` header when the
  caller may see that company, else the caller's own.
* ``tenant_db_for(db, company_id)`` — a route that names its company itself
  (a ``company_id`` parameter, the template library).
* ``control_db_for(db)`` — the control rows of a unit of work that started on
  a tenant session (a run's settlement, WS2 2.6) in a transaction of their own.

``TENANCY_MODE=single`` (today): both open on the one database, exactly as
``AsyncSessionLocal()`` did — the factory is looked up when the session
opens, so a test that points ``src.common.database.AsyncSessionLocal``
elsewhere moves them too. ``company_id`` may be ``None`` (a job queued
before jobs carried it, a sweep over every company). The dependencies give a
route the request's one ``get_db`` session, as before, and ignore the header.

``TENANCY_MODE=split``: ``tenant_session`` finds the company in the tenant
directory and opens on its database. Until the foreign keys and the units of
work that cross the planes are gone (WS2 2.3, 2.6), the session also binds the
control classes to the control database, so a run that reads a feature flag
or writes a usage row still works: each class goes to its plane's database
and raw SQL to the tenant's. A commit then commits both, one after the other
— not atomically, which is why 2.6 keys settlement by run id.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.auth.dependencies import get_current_user, get_current_user_and_company, get_current_user_from_query
from src.auth.visibility import in_scope, visible_company_ids
from src.common import database
from src.common.config import settings
from src.common.database import get_db
from src.common.tenancy.bases import CONTROL, TENANT, plane_bases
from src.common.tenancy.directory import TenantLocation, TenantNotReady, directory
from src.common.tenancy.engines import engines


class TenantRequired(RuntimeError):
    """A tenant session in split mode was asked for without a company."""


def tenancy_mode() -> str:
    return settings.TENANCY_MODE


def is_split() -> bool:
    return settings.TENANCY_MODE == "split"


def control_session() -> AsyncSession:
    """A session on the control database (use as ``async with control_session() as db``)."""
    return database.AsyncSessionLocal()


_control_tables: Optional[tuple] = None


def control_tables() -> tuple:
    """Every control-plane table (once per process): a statement built on the
    table itself (``pg_insert(CreditHold.__table__)``) names no mapped class, so
    the class binds alone sent it to the tenant database ("relation credit_holds
    does not exist", Azure dev in split mode)."""
    global _control_tables
    if _control_tables is None:
        from src.common.tenancy.bases import plane_tables

        _control_tables = tuple(plane_tables(CONTROL))
    return _control_tables


def _tenant_factory(location: TenantLocation) -> Callable[[], AsyncSession]:
    tenant_engine = engines.get(location)
    bases = plane_bases()
    binds: dict[Any, Any] = {base: tenant_engine for base in bases[TENANT]}
    binds.update({base: database.engine for base in bases[CONTROL]})
    binds.update({table: database.engine for table in control_tables()})
    return async_sessionmaker(
        bind=tenant_engine, binds=binds, expire_on_commit=False,
        info={"company_id": location.company_id, "tenant_key": location.key},
    )


async def tenant_sessionmaker(company_id: Optional[Any]) -> Callable[[], AsyncSession]:
    """The session factory for ``company_id``'s tenant database."""
    if not is_split():
        return database.AsyncSessionLocal
    if company_id is None:
        raise TenantRequired("TENANCY_MODE=split: a tenant session needs the company it is for")
    location = await directory.get(company_id)
    if not location.database_ready:
        raise TenantNotReady(f"tenant {location.key} is {location.status}; its database is not ready")
    return _tenant_factory(location)


@asynccontextmanager
async def tenant_session(company_id: Optional[Any]) -> AsyncIterator[AsyncSession]:
    """A session on ``company_id``'s tenant database (``async with tenant_session(cid) as db``)."""
    factory = await tenant_sessionmaker(company_id)
    async with factory() as session:
        yield session


async def tenant_scopes() -> list[Optional[UUID]]:
    """What a sweep over every company iterates: ``[None]`` (the one shared
    database, one pass) in single mode, else each company whose database is ready."""
    if not is_split():
        return [None]
    return list(await directory.ready_company_ids())


ACTING_COMPANY_HEADER = "X-Company-Id"


async def acting_company_id(request: Request, user: Any, db: AsyncSession) -> UUID:
    """The company whose data the request works on: ``X-Company-Id`` if the
    user may see that company (``auth.visibility``), else the user's own."""
    raw = (request.headers.get(ACTING_COMPANY_HEADER) or "").strip()
    if not raw:
        return user.company_id
    try:
        company_id = UUID(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{ACTING_COMPANY_HEADER} is not a company id")
    if company_id != user.company_id and not in_scope(await visible_company_ids(db, user), company_id):
        raise HTTPException(status_code=403, detail="Not authorized for this company")
    if company_id != user.company_id and str(user.role) in ("partner_admin", "partner_user"):
        # A partner acts in a tenant only under an access grant, recorded (Phase 15 T8-4).
        from src.partners.access import check_acting
        await check_acting(db, user=user, tenant_id=company_id, method=getattr(request, "method", "GET"),
                           path=request.url.path if hasattr(request, "url") else "")
    return company_id


async def get_control_db(db: AsyncSession = Depends(get_db)) -> AsyncIterator[AsyncSession]:
    """The control database: the request's ``get_db`` session (the one the user
    was read with), so a route has one control session, as before."""
    yield db


def _tenant_db_dependency(user_dependency: Callable[..., Any], *,
                          acting: bool) -> Callable[..., AsyncIterator[AsyncSession]]:
    async def dependency(request: Request, current_user: Any = Depends(user_dependency),
                         db: AsyncSession = Depends(get_db)) -> AsyncIterator[AsyncSession]:
        user = current_user[0] if isinstance(current_user, tuple) else current_user
        if not is_split():
            if acting and (request.headers.get(ACTING_COMPANY_HEADER) or "").strip():
                # The same checks in either mode: the company is visible, a partner holds a grant (T8-4).
                await acting_company_id(request, user, db)
            yield db
            return
        company_id = await acting_company_id(request, user, db) if acting else user.company_id
        async with tenant_session(company_id) as session:
            yield session
    return dependency


# A tenant session after the route's own sign-in check (the same dependency,
# so the user is read once). Single mode: the request's one session, exactly
# what ``get_db`` gives.
get_tenant_db = _tenant_db_dependency(get_current_user, acting=False)
get_tenant_db_with_company = _tenant_db_dependency(get_current_user_and_company, acting=False)
get_acting_tenant_db = _tenant_db_dependency(get_current_user, acting=True)
get_acting_tenant_db_from_query = _tenant_db_dependency(get_current_user_from_query, acting=True)


def is_tenant_session(db: Any) -> bool:
    """Whether ``db`` is a split-mode tenant session (one ``tenant_session`` opened)."""
    return bool(getattr(db, "info", {}).get("tenant_key"))


@asynccontextmanager
async def control_db_for(db: AsyncSession) -> AsyncIterator[AsyncSession]:
    """The control database inside a unit of work that started on ``db``
    (WS2 2.6): ``db`` itself when it is not a tenant session (single mode, or
    a control session), else a control session of its own — so the control
    rows of a run's settlement commit in one transaction of their own."""
    if not is_tenant_session(db):
        yield db
        return
    async with control_session() as session:
        yield session


@asynccontextmanager
async def tenant_db_for(db: AsyncSession, company_id: Optional[Any]) -> AsyncIterator[AsyncSession]:
    """``company_id``'s data inside a request that named the company itself
    (after its own visibility check). Single mode: ``db``, the request's session."""
    if not is_split():
        yield db
        return
    async with tenant_session(company_id) as session:
        yield session
