"""
Shared fixtures for E2E tests.
Uses httpx.AsyncClient against the real FastAPI app + live PostgreSQL.

The suite writes to the database in ``DATABASE_URL`` (the local dev database).
Everything it creates hangs off companies it made, and the session teardown
(``_e2e_cleanup``) deletes those companies, every row that references them or
their users, and puts back the global billing config that test_08 changes.
Only this session's rows are deleted: its own companies and the users whose
address carries its TEST_ID.
Not undone: the cron calls in test_08 act on every company (credit renewal,
Razorpay reconciliation), and calls made to outside services stay made. The run
test_06 triggers is picked up by a running Arq worker, if there is one; the
teardown deletes it, so a worker still on it at that point logs errors.
Account emails are captured (``sent_account_emails``), never sent.
"""
import os
import sys
import uuid
import warnings
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
import httpx
from pytest_asyncio import is_async_test
from sqlalchemy import select, text, update

# Ensure backend src is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.main import app  # noqa: E402
from src.auth import account_emails  # noqa: E402
from src.auth.models import User  # noqa: E402
from src.common.database import AsyncSessionLocal, engine  # noqa: E402

# ---------------------------------------------------------------------------
# Unique per-session suffix to isolate test data
# ---------------------------------------------------------------------------
TEST_ID = uuid.uuid4().hex[:8]

# Passwords must be 12-128 characters and not the email (AU-07).
PASSWORD = "E2e-Passw0rd-2026"


def _email(role: str) -> str:
    return f"e2e_{role}_{TEST_ID}@test.hirebuddha.com"


# Companies this session created, deleted at teardown: those made through
# POST /api/v1/companies, and the workspace each registration made.
_CREATED_COMPANY_IDS: set[str] = set()


async def _track_created_company(response: httpx.Response) -> None:
    request = response.request
    if request.method == "POST" and request.url.path == "/api/v1/companies" and response.is_success:
        await response.aread()
        _CREATED_COMPANY_IDS.add(str(response.json()["id"]))


# ---------------------------------------------------------------------------
# Event loop
# ---------------------------------------------------------------------------

def pytest_collection_modifyitems(items):
    """Run every e2e test on the session's event loop, the one the session fixtures use.

    The app's connection pool outlives a test, so a test on its own loop is handed
    asyncpg connections bound to an earlier, closed loop ("attached to a different
    loop"). pytest.ini asks for a session loop with asyncio_default_test_loop_scope,
    which pytest-asyncio 0.23 — the version poetry.lock pins — does not read.
    """
    major, minor = (int(p) for p in pytest_asyncio.__version__.split(".")[:2])
    marker = pytest.mark.asyncio(**{"scope" if (major, minor) < (0, 24) else "loop_scope": "session"})
    here = os.path.dirname(os.path.abspath(__file__))
    for item in items:
        if is_async_test(item) and str(item.path).startswith(here):
            item.add_marker(marker, append=False)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session")
async def client():
    """Async HTTP client bound to the FastAPI app."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        event_hooks={"response": [_track_created_company]},
    ) as c:
        yield c


@pytest.fixture(scope="session", autouse=True)
def sent_account_emails():
    """Account emails (verification, password reset) the API sent, instead of sending them.

    Each entry is ``{"to", "subject", "link"}``; ``link`` is the URL the user would click.
    """
    sent: list[dict] = []

    async def capture(to_email: str, subject: str, body: str, link: str) -> None:
        sent.append({"to": to_email, "subject": subject, "link": link})

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(account_emails, "_send", capture)
        yield sent


def link_token(link: str) -> str:
    """The ``token`` query parameter of an emailed link."""
    return parse_qs(urlparse(link).query)["token"][0]


# -- helper: register + login -------------------------------------------------

async def set_user_fields(email: str, **values) -> None:
    """Update a user row directly, remembering the workspace its registration created."""
    async with AsyncSessionLocal() as db:
        workspace_id = await db.scalar(select(User.company_id).where(User.email == email))
        if workspace_id is not None:
            _CREATED_COMPANY_IDS.add(str(workspace_id))
        await db.execute(update(User).where(User.email == email).values(**values))
        await db.commit()


async def register_and_login(
    client: httpx.AsyncClient, email: str, password: str, full_name: str, **user_fields
):
    """Register a user, mark them verified in the DB, then login and return (access, refresh).

    Registration sends a verification email and returns no tokens, and an unverified
    account cannot sign in (AU-08), so the address is verified directly rather than
    through the emailed link. ``user_fields`` (role, company_id) are set at the same time.
    """
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )
    assert resp.status_code == 201, f"Register {email} failed: {resp.status_code} {resp.text}"
    await set_user_fields(email, is_verified=True, **user_fields)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, f"Login {email} failed: {resp.status_code} {resp.text}"
    data = resp.json()
    return data["access_token"], data["refresh_token"]


def auth_headers(token: str) -> dict:
    """Return headers dict with Bearer token."""
    return {"Authorization": f"Bearer {token}"}


# -- bootstrap an app_admin user -----------------------------------------------
# Registration creates a TENANT workspace with the user as its tenant_admin.
# The role is then patched to app_admin directly in the DB.

@pytest_asyncio.fixture(scope="session")
async def app_admin_token(client: httpx.AsyncClient):
    """Register the app_admin user and return the access_token."""
    token, _ = await register_and_login(
        client, _email("appadmin"), PASSWORD, "E2E App Admin", role="app_admin"
    )
    return token


@pytest_asyncio.fixture(scope="session")
async def app_admin_company_id(app_admin_token, client: httpx.AsyncClient):
    """Return the company_id of the app_admin user."""
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(app_admin_token))
    return resp.json()["company_id"]


# -- partner setup ------------------------------------------------------------

@pytest_asyncio.fixture(scope="session")
async def test_partner(app_admin_token, client: httpx.AsyncClient):
    """Create a PARTNER company. Returns dict with id."""
    resp = await client.post(
        "/api/v1/companies",
        headers=auth_headers(app_admin_token),
        json={"name": f"E2E Partner {TEST_ID}", "type": "PARTNER", "status": "active"},
    )
    assert resp.status_code == 200, f"Failed to create partner: {resp.text}"
    return resp.json()


@pytest_asyncio.fixture(scope="session")
async def partner_admin_token(test_partner, app_admin_token, client: httpx.AsyncClient):
    """Register a partner_admin user and return access_token."""
    token, _ = await register_and_login(
        client, _email("partneradmin"), PASSWORD, "E2E Partner Admin",
        role="partner_admin", company_id=test_partner["id"],
    )
    return token


# -- tenant setup ------------------------------------------------------------

@pytest_asyncio.fixture(scope="session")
async def test_tenant(app_admin_token, test_partner, client: httpx.AsyncClient):
    """Create a TENANT company under the partner. Returns dict."""
    resp = await client.post(
        "/api/v1/companies",
        headers=auth_headers(app_admin_token),
        json={
            "name": f"E2E Tenant {TEST_ID}",
            "type": "TENANT",
            "status": "active",
            "parent_id": test_partner["id"],
        },
    )
    assert resp.status_code == 200, f"Failed to create tenant: {resp.text}"
    return resp.json()


@pytest_asyncio.fixture(scope="session")
async def tenant_admin_token(test_tenant, client: httpx.AsyncClient):
    """Register a tenant_admin user and return access_token."""
    token, _ = await register_and_login(
        client, _email("tenantadmin"), PASSWORD, "E2E Tenant Admin",
        role="tenant_admin", company_id=test_tenant["id"],
    )
    return token


@pytest_asyncio.fixture(scope="session")
async def tenant_admin_company_id(test_tenant):
    return test_tenant["id"]


# -- regular user token -------------------------------------------------------

@pytest_asyncio.fixture(scope="session")
async def user_token(test_tenant, client: httpx.AsyncClient):
    """Register a regular user (role=tenant_user) and return access_token."""
    token, _ = await register_and_login(
        client, _email("regularuser"), PASSWORD, "E2E Regular User",
        role="tenant_user", company_id=test_tenant["id"],
    )
    return token


# ---------------------------------------------------------------------------
# Teardown: delete what the session created
# ---------------------------------------------------------------------------

_FOREIGN_KEYS_SQL = """
SELECT c.conrelid::regclass::text AS child,
       c.confrelid::regclass::text AS parent,
       ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(n, i)
             JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.n ORDER BY k.i) AS child_cols,
       ARRAY(SELECT a.attname FROM unnest(c.confkey) WITH ORDINALITY k(n, i)
             JOIN pg_attribute a ON a.attrelid = c.confrelid AND a.attnum = k.n ORDER BY k.i) AS parent_cols,
       c.confdeltype AS on_delete
FROM pg_constraint c
WHERE c.contype = 'f'
"""

_COMPANY_SCOPED_TABLES_SQL = """
SELECT table_name FROM information_schema.columns
WHERE table_schema = current_schema() AND column_name = 'company_id'
"""


async def _delete_rows(conn, foreign_keys, company_scoped, table, where, params, path=()) -> None:
    """Delete the rows of ``table`` matching ``where``, after every row that references them.

    Walks the real foreign keys, so a new table is covered without listing it here.
    A referencing row that belongs to another company is never deleted: it stays,
    the final DELETE fails on it, and the caller rolls the whole teardown back.
    ``ON DELETE SET NULL`` references are left to the database, and a cycle
    (``companies.parent_id``) ends in the one DELETE that removes both ends.
    """
    path = path + (table,)
    for child, child_cols, parent_cols, on_delete in foreign_keys.get(table, ()):
        if on_delete == "n" or child in path:
            continue
        child_where = (
            f"({', '.join(child_cols)}) IN "
            f"(SELECT {', '.join(parent_cols)} FROM {table} WHERE {where})"
        )
        if child in company_scoped:
            child_where += " AND (company_id IS NULL OR company_id = ANY(CAST(:company_ids AS uuid[])))"
        await _delete_rows(conn, foreign_keys, company_scoped, child, child_where, params, path)
    await conn.execute(text(f"DELETE FROM {table} WHERE {where}"), params)


async def _purge_session_rows() -> None:
    """Delete this session's users and companies and everything that references them."""
    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT DISTINCT company_id FROM users WHERE email LIKE :pattern AND company_id IS NOT NULL"
        ), {"pattern": f"e2e\\_%\\_{TEST_ID}@test.hirebuddha.com"})).scalars().all()
        company_ids = [uuid.UUID(c) for c in _CREATED_COMPANY_IDS | {str(r) for r in rows}]
        if not company_ids:
            return
        foreign_keys: dict[str, list] = {}
        for child, parent, child_cols, parent_cols, on_delete in await conn.execute(text(_FOREIGN_KEYS_SQL)):
            foreign_keys.setdefault(parent, []).append((child, child_cols, parent_cols, on_delete))
        company_scoped = set((await conn.execute(text(_COMPANY_SCOPED_TABLES_SQL))).scalars().all())
        params = {"company_ids": company_ids, "pattern": f"e2e\\_%\\_{TEST_ID}@test.hirebuddha.com"}
        # Users first, by address, in case one was moved out of the session's companies.
        await _delete_rows(conn, foreign_keys, company_scoped, "users", "email LIKE :pattern", params)
        await _delete_rows(
            conn, foreign_keys, company_scoped, "companies",
            "id = ANY(CAST(:company_ids AS uuid[]))", params,
        )


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _e2e_cleanup():
    """Delete the session's data at the end, and restore the global billing config.

    test_08 updates the global billing config (``company_id IS NULL``), so it is
    saved here first and written back afterwards. If the delete fails — a row of
    another company references the session's data — nothing is deleted and a
    warning names the session's TEST_ID.
    """
    async with engine.connect() as conn:
        global_billing = [
            dict(row._mapping)
            for row in await conn.execute(text("SELECT * FROM billing_config WHERE company_id IS NULL"))
        ]
    yield
    try:
        await _purge_session_rows()
    except Exception as exc:  # noqa: BLE001 — report it; the test results stand
        warnings.warn(f"E2E teardown left the data of TEST_ID {TEST_ID} in the database: {exc}")
    async with engine.begin() as conn:
        for row in global_billing:
            columns = [c for c in row if c != "id"]
            await conn.execute(
                text(f"UPDATE billing_config SET {', '.join(f'{c} = :{c}' for c in columns)} WHERE id = :id"),
                row,
            )
        await conn.execute(
            text("DELETE FROM billing_config WHERE company_id IS NULL AND NOT (id = ANY(CAST(:ids AS uuid[])))"),
            {"ids": [row["id"] for row in global_billing]},
        )
