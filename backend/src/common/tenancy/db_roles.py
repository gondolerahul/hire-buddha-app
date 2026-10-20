"""Who may do what in a tenant database (Phase 14 M2; tech spec §5.2).

On a pool server (Azure) the provisioner sets this up itself, so nothing is
run by hand:

* **Server-wide, once** (``ensure_server_roles``, on the ``postgres`` database):
  the group roles ``hb_runtime`` (API, workers, Connection Service),
  ``hb_dataapi`` (a tenant's own Data API) and the DDL role
  (``TENANT_DB_DDL_ROLE``, ``hb_migrator``); the Entra sign-ins of the
  workloads (``TENANT_DB_RUNTIME_PRINCIPALS``, ``TENANT_DB_MIGRATOR_PRINCIPAL``)
  as members; and the provisioner itself as a member of the DDL role.
* **Per tenant database** (``secure_database``): only ``hb_runtime`` and the
  DDL role may connect; schema ``platform`` belongs to the DDL role; every
  table, sequence and schema the DDL role makes is usable by ``hb_runtime``
  (default privileges).
* **The tenant's own identity** (``grant_tenant_principal``, identity_ready):
  a sign-in for its Data API, in ``hb_dataapi``, allowed into this database only.

Every DDL in a tenant database runs as the DDL role (``SET ROLE``, see
``engines.create_tenant_engine`` and the migration runner), so its objects
have one owner whether the provisioner or the migrator made them.

Locally (no ``TENANT_DB_DDL_ROLE``) none of this applies: one user owns
everything. Where Azure's ``pgaadauth_*`` functions are missing (tests on
plain PostgreSQL), principals are made as ordinary login roles.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from sqlalchemy import text

RUNTIME = "hb_runtime"
DATA_API = "hb_dataapi"

_NAME = re.compile(r"^[A-Za-z0-9_.@-]{1,63}$")


def ddl_role() -> Optional[str]:
    from src.common.config import settings

    return (settings.TENANT_DB_DDL_ROLE or "").strip() or None


def _names(value: str) -> List[str]:
    return [n.strip() for n in (value or "").split(",") if n.strip()]


def _q(name: str) -> str:
    """A role or database name, checked and quoted (they come from settings and tenant keys)."""
    if not _NAME.match(name):
        raise ValueError(f"not a role or database name: {name!r}")
    return '"' + name + '"'


async def _exists(conn: Any, role: str) -> bool:
    return (await conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})).first() is not None


async def _has_aad(conn: Any) -> bool:
    found = await conn.execute(text("SELECT 1 FROM pg_proc WHERE proname = 'pgaadauth_create_principal'"))
    return found.first() is not None


async def _principal(conn: Any, name: str, *, object_id: Optional[str] = None) -> bool:
    """An Entra sign-in (a login role locally); ``True`` when it was made now."""
    if await _exists(conn, name):
        return False
    if await _has_aad(conn):
        if object_id:
            await conn.execute(text("SELECT pgaadauth_create_principal_with_oid(:n, :o, 'service', false, false)"),
                               {"n": name, "o": object_id})
        else:
            await conn.execute(text("SELECT pgaadauth_create_principal(:n, false, false)"), {"n": name})
    else:
        await conn.execute(text(f"CREATE ROLE {_q(name)} LOGIN"))
    return True


async def ensure_server_roles(conn: Any) -> Dict[str, Any]:
    """The group roles and workload sign-ins on a pool server (once; safe to repeat)."""
    from src.common.config import settings

    role = ddl_role()
    if role is None:
        return {"skipped": "no TENANT_DB_DDL_ROLE (one user owns everything)"}
    made: List[str] = []
    for group in (RUNTIME, DATA_API, role):
        if not await _exists(conn, group):
            await conn.execute(text(f"CREATE ROLE {_q(group)} NOLOGIN"))
            made.append(group)
    runtime = _names(settings.TENANT_DB_RUNTIME_PRINCIPALS)
    migrator = (settings.TENANT_DB_MIGRATOR_PRINCIPAL or "").strip()
    for name in runtime + ([migrator] if migrator else []):
        if await _principal(conn, name):
            made.append(name)
    for name in runtime:
        await conn.execute(text(f"GRANT {_q(RUNTIME)} TO {_q(name)}"))
    if migrator:
        await conn.execute(text(f"GRANT {_q(role)} TO {_q(migrator)}"))
    # The provisioner runs DDL as the role too (SET ROLE needs membership).
    me = (await conn.execute(text("SELECT current_user"))).scalar_one()
    if me != role:
        await conn.execute(text(f"GRANT {_q(role)} TO {_q(me)}"))
    return {"made": made, "runtime": runtime, "migrator": migrator or None, "ddl_role": role}


async def secure_database(conn: Any, db_name: str) -> Dict[str, Any]:
    """A tenant database's access, on a connection to it (as the provisioner)."""
    role = ddl_role()
    if role is None:
        return {"skipped": "no TENANT_DB_DDL_ROLE"}
    db, owner, runtime = _q(db_name), _q(role), _q(RUNTIME)
    for statement in (
        f"REVOKE CONNECT, TEMPORARY ON DATABASE {db} FROM PUBLIC",
        f"GRANT CONNECT, TEMPORARY ON DATABASE {db} TO {runtime}, {owner}",
        f"GRANT CREATE ON DATABASE {db} TO {owner}",
        f"CREATE SCHEMA IF NOT EXISTS platform AUTHORIZATION {owner}",
        f"ALTER SCHEMA platform OWNER TO {owner}",
        f"GRANT USAGE ON SCHEMA platform TO {runtime}",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLES TO {runtime}",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {runtime}",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} GRANT USAGE ON SCHEMAS TO {runtime}",
    ):
        await conn.execute(text(statement))
    return {"database": db_name, "owner": role, "runtime": RUNTIME}


async def grant_tenant_principal(conn: Any, db_name: str, name: str, object_id: Optional[str]) -> Dict[str, Any]:
    """The tenant's own sign-in (its Data API's identity): ``hb_dataapi``, this database only."""
    made = await _principal(conn, name, object_id=object_id)
    if await _exists(conn, DATA_API):
        await conn.execute(text(f"GRANT {_q(DATA_API)} TO {_q(name)}"))
    await conn.execute(text(f"GRANT CONNECT ON DATABASE {_q(db_name)} TO {_q(name)}"))
    return {"principal": name, "made": made, "database": db_name}
