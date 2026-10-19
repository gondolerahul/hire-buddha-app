"""The database apps and code live in (Phase 14 WS6).

Apps sit on a business's records: their users sign in at the Data API, which
reads the business's own database (``schema_engine.business_engine``). So the
app tables are always read and written there — :func:`app_session` — also
in ``TENANCY_MODE=single``, where ``tenant_session`` would open the shared
database instead. Code lanes use the same database when the business has
one, and the shared one when it does not (:func:`code_session`): scratch code
can come from any business, apps only from one with records.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession


class AppsUnavailable(RuntimeError):
    """The business has no database of its own yet, so no apps."""


@asynccontextmanager
async def app_session(company_id: Any, *, require_tenant: bool = True) -> AsyncIterator[AsyncSession]:
    from src.common.tenancy.directory import directory
    from src.common.tenancy.engines import engines
    from src.common.tenancy.session import tenant_session

    location = await directory.find(company_id)
    if location is not None and location.database_ready:
        async with AsyncSession(engines.get(location), expire_on_commit=False) as db:
            yield db
        return
    if require_tenant:
        raise AppsUnavailable("apps need the business on its own database; this one has none yet")
    async with tenant_session(company_id) as db:
        yield db


def code_session(company_id: Any) -> Any:
    return app_session(company_id, require_tenant=False)
