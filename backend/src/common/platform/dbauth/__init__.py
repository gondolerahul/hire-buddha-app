"""Database authentication (Phase 14, tech spec §5.3, §19.3 ``DbCredentialProvider``).

How a platform process proves who it is to PostgreSQL:

* ``password`` — the password in the URL (local Docker Postgres, tests).
* ``entra_token`` — Azure Database for PostgreSQL with Microsoft Entra ID: the
  URL names the workload's database principal (``id-hb-<env>-api``) and no
  password; every new connection gets a current Entra access token as its
  password (P-07: no stored database credential). Tokens live about an hour
  and are refreshed five minutes before they expire.

``DB_AUTH`` chooses (default from ``PLATFORM_PROFILE``). The same provider
serves the tenant engines of WS2.
"""
from __future__ import annotations

from typing import Any

from src.common.platform import AdapterNotAvailable, adapter_name

# Microsoft Entra scope of Azure Database for PostgreSQL.
POSTGRES_ENTRA_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"


def install(engine: Any, method: str | None = None) -> str:
    """Make ``engine`` (sync or async) authenticate by ``method``; returns the method used."""
    method = method or adapter_name("db_auth")
    if method == "password":
        return method
    if method != "entra_token":
        raise AdapterNotAvailable(f"DB_AUTH={method!r} has no adapter (password, entra_token)")

    from sqlalchemy import event

    from src.common.platform.identity import sync_token

    sync_engine = getattr(engine, "sync_engine", engine)

    @event.listens_for(sync_engine, "do_connect")
    def _entra_password(dialect: Any, connection_record: Any, cargs: Any, cparams: dict) -> None:
        # Runs for each new physical connection only; the pool reuses them.
        cparams["password"] = sync_token(POSTGRES_ENTRA_SCOPE)

    return method


def libpq_environment(url: Any, method: str | None = None) -> dict:
    """``PG*`` environment variables that let a libpq tool (``pg_dump``,
    ``psql``) sign in where ``url`` (a SQLAlchemy URL) points, by ``method``.

    The password never goes on a command line, where any process could read it.
    """
    from sqlalchemy.engine import make_url

    url = make_url(url)
    method = method or adapter_name("db_auth")
    env = {
        "PGHOST": url.host or "localhost",
        "PGPORT": str(url.port or 5432),
        "PGDATABASE": url.database or "",
    }
    if url.username:
        env["PGUSER"] = url.username
    ssl = url.query.get("ssl") or url.query.get("sslmode")
    if ssl:
        env["PGSSLMODE"] = "require" if ssl in ("require", "true", "True") else str(ssl)
    if method == "entra_token":
        from src.common.platform.identity import sync_token

        env["PGPASSWORD"] = sync_token(POSTGRES_ENTRA_SCOPE)
        env.setdefault("PGSSLMODE", "require")
    elif method == "password":
        if url.password:
            env["PGPASSWORD"] = url.password
    else:
        raise AdapterNotAvailable(f"DB_AUTH={method!r} has no adapter (password, entra_token)")
    return env
