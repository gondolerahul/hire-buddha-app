"""No one can raise their own privileges through PATCH /users/{id} (AU-01).

The route applied every field of ``UserUpdate`` to the row once the caller was an
admin of the same company — or the row's owner. ``role`` was an unchecked
string, so a tenant admin (or any user, on their own row) could PATCH
``{"role": "app_admin"}`` and become a platform superuser.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from src.auth import user_router
from src.auth.dependencies import get_current_user
from src.common.database import get_db

APP_CO = uuid.uuid4()
PARTNER_CO = uuid.uuid4()
TENANT_CO = uuid.uuid4()        # a tenant of PARTNER_CO
OTHER_TENANT_CO = uuid.uuid4()  # someone else's tenant
PARENTS = {TENANT_CO: PARTNER_CO, OTHER_TENANT_CO: None, PARTNER_CO: None, APP_CO: None}


def _user(role: str, company_id, **kw):
    return SimpleNamespace(
        id=uuid.uuid4(), email=f"{role}@example.com", full_name=role, company_id=company_id,
        role=role, is_active=True, profile_picture_url=None, **kw,
    )


class _Result:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return self

    def first(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value


class FakeDB:
    """Answers the two queries the route makes: the target user, a company's parent."""

    def __init__(self, users):
        self.users = {u.id: u for u in users}
        self.commits = 0

    async def execute(self, stmt):
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        target = next(iter(stmt.compile().params.values()))
        if "FROM users" in sql:
            return _Result(self.users.get(target))
        if "companies.parent_id" in sql:
            return _Result(PARENTS.get(target))
        raise AssertionError(f"unexpected query: {sql}")

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        pass


def _app(actor, db) -> FastAPI:
    app = FastAPI()
    app.include_router(user_router.router)

    async def _actor():
        return actor

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _actor
    app.dependency_overrides[get_db] = _db
    return app


async def _patch(actor, target, body, others=()):
    db = FakeDB([actor, target, *others])
    transport = httpx.ASGITransport(app=_app(actor, db))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        res = await client.patch(f"/users/{target.id}", json=body)
    return res, db


@pytest.mark.asyncio
@pytest.mark.parametrize("role,company", [
    ("tenant_admin", TENANT_CO), ("tenant_user", TENANT_CO),
    ("partner_admin", PARTNER_CO), ("partner_user", PARTNER_CO), ("app_user", APP_CO),
])
async def test_no_one_changes_their_own_role(role, company):
    me = _user(role, company)
    res, db = await _patch(me, me, {"role": "app_admin"})
    assert res.status_code == 403
    assert me.role == role and db.commits == 0


@pytest.mark.asyncio
async def test_app_admin_cannot_demote_themselves_either():
    me = _user("app_admin", APP_CO)
    res, _ = await _patch(me, me, {"role": "tenant_user"})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_a_user_cannot_reactivate_themselves():
    me = _user("tenant_user", TENANT_CO)
    me.is_active = False
    res, _ = await _patch(me, me, {"is_active": True})
    assert res.status_code == 403 and me.is_active is False


@pytest.mark.asyncio
async def test_anyone_may_rename_themselves_and_resend_their_role():
    me = _user("tenant_user", TENANT_CO)
    res, db = await _patch(me, me, {"full_name": "New Name", "role": "tenant_user", "is_active": True})
    assert res.status_code == 200
    assert me.full_name == "New Name" and db.commits == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("new_role", ["app_admin", "app_user", "partner_admin", "partner_user"])
async def test_tenant_admin_cannot_grant_roles_above_tenant(new_role):
    admin = _user("tenant_admin", TENANT_CO)
    colleague = _user("tenant_user", TENANT_CO)
    res, _ = await _patch(admin, colleague, {"role": new_role})
    assert res.status_code == 403 and colleague.role == "tenant_user"


@pytest.mark.asyncio
async def test_tenant_admin_manages_their_own_company():
    admin = _user("tenant_admin", TENANT_CO)
    colleague = _user("tenant_user", TENANT_CO)
    res, _ = await _patch(admin, colleague, {"role": "tenant_admin", "is_active": False})
    assert res.status_code == 200
    assert colleague.role == "tenant_admin" and colleague.is_active is False


@pytest.mark.asyncio
async def test_a_plain_user_cannot_edit_a_colleague():
    me = _user("tenant_user", TENANT_CO)
    colleague = _user("tenant_user", TENANT_CO)
    res, _ = await _patch(me, colleague, {"full_name": "pwned"})
    assert res.status_code == 403 and colleague.full_name == "tenant_user"


@pytest.mark.asyncio
async def test_partner_admin_manages_their_tenants_users_only():
    partner = _user("partner_admin", PARTNER_CO)
    theirs = _user("tenant_user", TENANT_CO)
    not_theirs = _user("tenant_user", OTHER_TENANT_CO)
    res, _ = await _patch(partner, theirs, {"role": "tenant_admin"})
    assert res.status_code == 200 and theirs.role == "tenant_admin"
    res, _ = await _patch(partner, not_theirs, {"is_active": False})
    assert res.status_code == 403 and not_theirs.is_active is True
    res, _ = await _patch(partner, theirs, {"role": "app_admin"})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_unknown_role_string_is_a_422():
    admin = _user("app_admin", APP_CO)
    target = _user("tenant_user", TENANT_CO)
    res, _ = await _patch(admin, target, {"role": "tenant-admin"})
    assert res.status_code == 422 and target.role == "tenant_user"


@pytest.mark.asyncio
async def test_app_admin_can_promote_someone_else():
    admin = _user("app_admin", APP_CO)
    target = _user("app_user", APP_CO)
    res, _ = await _patch(admin, target, {"role": "app_admin"})
    assert res.status_code == 200 and target.role == "app_admin"
