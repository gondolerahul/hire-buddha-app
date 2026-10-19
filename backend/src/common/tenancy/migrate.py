"""The migration runner (Phase 14 WS2 2.7, 2.10; tech spec §5.4).

    python -m src.common.tenancy.migrate control
    python -m src.common.tenancy.migrate tenants [--tenant KEY ...] [--parallel N]
    python -m src.common.tenancy.migrate all        # control, then (split) tenants: what a deploy runs

Two Alembic trees (``migrations/envlib.py``): ``control`` for the control
tables, ``tenant_platform`` for a tenant's.

``control`` upgrades the control database with the control tree; in
``TENANCY_MODE=single`` the same database is the shared one and holds the
tenant tables too (schema ``public``), so the tenant tree runs there as well.
A database still on the old chain (``migrations/legacy``, ``alembic -n
legacy``) crosses first (:func:`cross_the_cut`): the old chain brings it to its
last revision, it must then equal what the two trees build, and it is stamped
onto their baselines — production's database included, with no manual step.

``tenants`` upgrades the tenant databases (schema ``platform``) to the tenant
tree's head, ``--parallel`` at a time (default 10), and stops after the first
batch with a failure; a tenant already at the head is skipped, so running it
again resumes. Each tenant runs in a process of its own — Alembic's ``op`` and
``context`` are module globals, so two migrations cannot share one — under an
advisory lock on its database. The version reached (the tree's revision) is
recorded in ``tenant_directory.platform_schema_version``.

A tenant database built from the models before the tree existed (tables in
``platform``, no version table) is adopted on its first upgrade: the baseline is
built next to it in a scratch schema, the database gets what it lacks
(``schema_catalog.adoption_plan``: indexes, keys, defaults, the
``kpi_daily_rollup`` view — never dropping a table or column), the two must then
be equal, and it is stamped at the baseline before the upgrade goes on.
"""
from __future__ import annotations

import argparse
import asyncio
import functools
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

from sqlalchemy import text

from src.common.tenancy.bases import TENANT_SCHEMA

logger = logging.getLogger(__name__)

BACKEND = Path(__file__).resolve().parents[3]
DEFAULT_PARALLEL = 10
TENANT_TIMEOUT_SECONDS = 900

CONTROL_TREE = "control"
TENANT_TREE = "tenant_platform"
CONTROL_BASELINE = "control_0001_baseline"
TENANT_BASELINE = "tenant_platform_0001_baseline"
LEGACY_TREE = "legacy"  # the old chain, frozen; deleted once production has crossed
LEGACY_CUT = "p14_run_settlement"  # its last revision: what the baselines squash
TENANT_VERSION_TABLE = "alembic_version_tenant_platform"
BASELINE_SCHEMA = "_hb_baseline"  # where the baselines are built to compare a database with
URL_VARIABLE = "HB_MIGRATION_URL"  # the tenant database a child process migrates
# Held by whoever migrates a tenant database (pg_advisory_lock; any constant, the same everywhere).
LOCK_KEY = 0x48425F4D49475254


class TenantMigrationFailed(RuntimeError):
    """A tenant database's migration process failed; the message ends with its error."""


def alembic_config(tree: str, **attributes: Any) -> Any:
    """``alembic.ini``'s section for ``tree``; ``attributes`` reach ``env.py`` (``url``, ``schema``, ``compare``).

    ``$HB_ALEMBIC_INI`` names another ``alembic.ini`` (child processes inherit
    it): a test points the runner at a copy of a tree with a revision added.
    """
    from alembic.config import Config

    ini = os.environ.get("HB_ALEMBIC_INI") or str(BACKEND / "alembic.ini")
    config = Config(ini, ini_section="alembic" if tree == CONTROL_TREE else tree)
    config.attributes.update(attributes)
    return config


@functools.lru_cache(maxsize=None)
def tree_head(tree: str) -> str:
    """The head revision of ``tree`` (read from its files; one head per tree)."""
    from alembic.script import ScriptDirectory

    heads = ScriptDirectory.from_config(alembic_config(tree)).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"the {tree} tree has {len(heads)} heads {heads}: merge them")
    return heads[0]


def tenant_schema_version() -> str:
    """The version every tenant's platform schema should be at: the tenant tree's head."""
    return tree_head(TENANT_TREE)


# ── The control database ────────────────────────────────────────────────────

def upgrade_control() -> None:
    from alembic import command

    from src.common.tenancy.session import tenancy_mode

    cross_the_cut()
    command.upgrade(alembic_config(CONTROL_TREE), "head")
    if tenancy_mode() == "single":
        command.upgrade(alembic_config(TENANT_TREE, schema="public"), "head")


def cross_the_cut(url: Any = None) -> Optional[str]:
    """Bring a database still on the old chain onto the two trees; returns its old revision, or ``None``.

    The old chain (``migrations/legacy``) first takes it to ``LEGACY_CUT``, its
    last revision. Both trees' baselines are then built next to it in a scratch
    schema, and its ``public`` schema must be the same — every column, default,
    constraint, index, enum type and the view — or nothing is stamped (a
    database changed by hand stops here, at ``LEGACY_CUT``, with the
    differences). Then, in one transaction, ``alembic_version`` moves to the
    control baseline and the tenant tree's version table (in ``public``, where
    the shared database keeps the tenant tables) starts at its baseline.
    """
    from alembic import command
    from alembic.script import ScriptDirectory
    from sqlalchemy.engine import make_url

    from src.common.config import settings

    url = make_url(url or settings.CONTROL_DATABASE_URL)
    revision = asyncio.run(_old_chain_revision(url))
    if revision is None:
        return None
    if revision != LEGACY_CUT:
        legacy = ScriptDirectory.from_config(alembic_config(LEGACY_TREE))
        if revision not in {r.revision for r in legacy.walk_revisions()}:
            raise SystemExit(f"{url.database} is at {revision!r}, a revision of neither migration tree "
                             f"nor of the old chain")
        logger.info("%s: the old chain from %s to %s", url.database, revision, LEGACY_CUT)
        command.upgrade(alembic_config(LEGACY_TREE, url=url.render_as_string(hide_password=False),
                                       skip_logging=True), LEGACY_CUT)
    left = asyncio.run(_differences_from_the_trees(url))
    if left:
        raise SystemExit(f"{url.database} is at {LEGACY_CUT!r} but differs from what the trees build; "
                         f"not stamped:\n  " + "\n  ".join(left[:50]))
    asyncio.run(_stamp_baselines(url))
    logger.info("%s: %s stamped as %s and %s", url.database, LEGACY_CUT, CONTROL_BASELINE, TENANT_BASELINE)
    return revision


async def _old_chain_revision(url: Any) -> Optional[str]:
    from alembic.script import ScriptDirectory

    engine = _engine(url)
    try:
        async with engine.connect() as conn:
            if not (await conn.execute(text("SELECT to_regclass('public.alembic_version')"))).scalar():
                return None
            versions = [r[0] for r in await conn.execute(text("SELECT version_num FROM public.alembic_version"))]
    finally:
        await engine.dispose()
    control = {r.revision for r in ScriptDirectory.from_config(alembic_config(CONTROL_TREE)).walk_revisions()}
    old = [v for v in versions if v not in control]
    return old[0] if old else None


async def build_baselines(raw: Any, url: Any, trees: Sequence[str]) -> dict[str, Any]:
    """Build ``trees``' baselines in ``BASELINE_SCHEMA`` of the database (replacing it); returns its catalogue.

    The caller drops the schema (``DROP SCHEMA … CASCADE``) when done with it.
    """
    from alembic import command

    from src.common.tenancy.schema_catalog import catalog

    await raw.execute(f'DROP SCHEMA IF EXISTS "{BASELINE_SCHEMA}" CASCADE')
    for tree in trees:
        baseline = CONTROL_BASELINE if tree == CONTROL_TREE else TENANT_BASELINE
        await asyncio.to_thread(command.upgrade, alembic_config(
            tree, url=url.render_as_string(hide_password=False), schema=BASELINE_SCHEMA,
            skip_logging=True), baseline)
    return await catalog(raw, BASELINE_SCHEMA)


async def _differences_from_the_trees(url: Any) -> list[str]:
    from src.common.tenancy.schema_catalog import catalog, differences

    engine = _engine(url)
    try:
        async with engine.connect() as conn:
            raw = await _raw(conn)
            try:
                want = await build_baselines(raw, url, (CONTROL_TREE, TENANT_TREE))
                return differences(await catalog(raw, "public"), want)
            finally:
                await raw.execute(f'DROP SCHEMA IF EXISTS "{BASELINE_SCHEMA}" CASCADE')
    finally:
        await engine.dispose()


async def _stamp_baselines(url: Any) -> None:
    engine = _engine(url)
    try:
        async with engine.connect() as conn:
            raw = await _raw(conn)
            async with raw.transaction():
                await raw.execute("UPDATE public.alembic_version SET version_num = $1 WHERE version_num = $2",
                                  CONTROL_BASELINE, LEGACY_CUT)
                await raw.execute(f'CREATE TABLE IF NOT EXISTS public."{TENANT_VERSION_TABLE}" '
                                  f'(version_num VARCHAR(32) NOT NULL, '
                                  f'CONSTRAINT "{TENANT_VERSION_TABLE}_pkc" PRIMARY KEY (version_num))')
                await raw.execute(f'INSERT INTO public."{TENANT_VERSION_TABLE}" VALUES ($1)', TENANT_BASELINE)
    finally:
        await engine.dispose()


def _engine(url: Any) -> Any:
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from src.common.platform.dbauth import install as install_db_auth

    engine = create_async_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    install_db_auth(engine)
    return engine


async def _raw(conn: Any) -> Any:
    """The asyncpg connection under a SQLAlchemy one."""
    return (await conn.get_raw_connection()).driver_connection


# ── One tenant database (in a process of its own) ──────────────────────────

async def _platform_state(raw: Any) -> str:
    """``versioned`` (the tree's), ``built_from_models`` (tables, no version table) or ``empty``."""
    if await raw.fetchval("SELECT to_regclass($1)", f"{TENANT_SCHEMA}.{TENANT_VERSION_TABLE}"):
        return "versioned"
    tables = await raw.fetchval("SELECT count(*) FROM pg_tables WHERE schemaname = $1", TENANT_SCHEMA)
    return "built_from_models" if tables else "empty"


async def adopt(raw: Any, url: Any) -> list[str]:
    """Bring a database built from the models to the baseline and stamp it there; returns the DDL run."""
    from src.common.tenancy.schema_catalog import AdoptionRefused, adoption_plan, catalog, differences

    try:
        want = await build_baselines(raw, url, (TENANT_TREE,))
        async with raw.transaction():
            plan = adoption_plan(await catalog(raw, TENANT_SCHEMA), want)
            await raw.execute(f'SET LOCAL search_path TO "{TENANT_SCHEMA}", public')
            for statement in plan:
                await raw.execute(statement)
            left = differences(await catalog(raw, TENANT_SCHEMA), want)
            if left:
                raise AdoptionRefused("still differs from the baseline after adoption: " + "; ".join(left[:20]))
            await raw.execute(f'CREATE TABLE "{TENANT_SCHEMA}"."{TENANT_VERSION_TABLE}" '
                              f'(version_num VARCHAR(32) NOT NULL, '
                              f'CONSTRAINT "{TENANT_VERSION_TABLE}_pkc" PRIMARY KEY (version_num))')
            await raw.execute(f'INSERT INTO "{TENANT_SCHEMA}"."{TENANT_VERSION_TABLE}" VALUES ($1)',
                              TENANT_BASELINE)
        return plan
    finally:
        await raw.execute(f'DROP SCHEMA IF EXISTS "{BASELINE_SCHEMA}" CASCADE')


async def migrate_tenant_database(url: Any) -> str:
    """Adopt the database if it was built from the models, then upgrade it to the head; returns its version."""
    from alembic import command

    engine = _engine(url)
    try:
        async with engine.connect() as conn:
            raw = await _raw(conn)
            await raw.execute("SELECT pg_advisory_lock($1)", LOCK_KEY)
            try:
                if await _platform_state(raw) == "built_from_models":
                    plan = await adopt(raw, url)
                    logger.info("%s: adopted at %s (%d statements)", url.database, TENANT_BASELINE, len(plan))
                await asyncio.to_thread(command.upgrade, alembic_config(
                    TENANT_TREE, url=url.render_as_string(hide_password=False), schema=TENANT_SCHEMA,
                    skip_logging=True), "head")
                return await raw.fetchval(
                    f'SELECT version_num FROM "{TENANT_SCHEMA}"."{TENANT_VERSION_TABLE}"')
            finally:
                await raw.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY)
    finally:
        await engine.dispose()


def _run_tenant_process(url: Any) -> str:
    """``migrate_tenant_database(url)`` in a child process; returns the version it printed."""
    env = {**os.environ, URL_VARIABLE: url.render_as_string(hide_password=False), "PYTHONUTF8": "1"}
    try:
        done = subprocess.run([sys.executable, "-m", "src.common.tenancy.migrate", "tenant-db"], cwd=BACKEND,
                              env=env, capture_output=True, text=True, timeout=TENANT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise TenantMigrationFailed(f"{url.database}: no result in {TENANT_TIMEOUT_SECONDS}s") from exc
    lines = done.stdout.strip().splitlines()
    if done.returncode != 0 or not lines or not lines[-1].startswith("version "):
        error = (done.stderr or done.stdout).strip().splitlines()[-12:]
        raise TenantMigrationFailed(f"{url.database}: exit {done.returncode}: " + "\n".join(error))
    return lines[-1].split(" ", 1)[1]


# ── The tenant databases ────────────────────────────────────────────────────

async def upgrade_tenant(location: Any) -> str:
    """Bring one tenant database to the tenant tree's head and record it in the directory; returns the version."""
    from sqlalchemy import update

    from src.common.tenancy.directory import directory
    from src.common.tenancy.engines import tenant_url
    from src.common.tenancy.models import TenantDirectoryEntry
    from src.common.tenancy.session import control_session

    version = await asyncio.to_thread(_run_tenant_process, tenant_url(location))
    async with control_session() as db:
        await db.execute(update(TenantDirectoryEntry)
                         .where(TenantDirectoryEntry.company_id == location.company_id)
                         .values(platform_schema_version=version))
        await db.commit()
    directory.invalidate(location.company_id)
    return version


async def _migratable(keys: Optional[Sequence[str]]) -> list[Any]:
    from sqlalchemy import select

    from src.common.tenancy.directory import TenantLocation
    from src.common.tenancy.models import DATABASE_READY_STATUSES, TenantDbServer, TenantDirectoryEntry
    from src.common.tenancy.session import control_session

    statuses = sorted(DATABASE_READY_STATUSES | {"db_created"})
    query = (select(TenantDirectoryEntry, TenantDbServer.host)
             .join(TenantDbServer, TenantDbServer.id == TenantDirectoryEntry.server_id)
             .where(TenantDirectoryEntry.status.in_(statuses))
             .order_by(TenantDirectoryEntry.tenant_key))
    if keys:
        query = query.where(TenantDirectoryEntry.tenant_key.in_(list(keys)))
    async with control_session() as db:
        rows = (await db.execute(query)).all()
    return [TenantLocation(company_id=e.company_id, key=e.tenant_key, server_host=host, db_name=e.db_name,
                           status=e.status, schema_version=e.platform_schema_version,
                           automation_state=e.automation_state, timezone=e.timezone)
            for e, host in rows]


async def upgrade_tenants(keys: Optional[Sequence[str]] = None,
                          parallel: int = DEFAULT_PARALLEL) -> dict[str, Any]:
    """Upgrade tenant databases in batches; ``{"version", "upgraded", "skipped", "failed", "not_run"}``."""
    target = tenant_schema_version()
    locations = await _migratable(keys)
    result: dict[str, Any] = {"version": target, "upgraded": [], "skipped": [], "failed": {}, "not_run": []}
    pending = []
    for location in locations:
        (result["skipped"] if location.schema_version == target else pending).append(location)
    result["skipped"] = [loc.key for loc in result["skipped"]]
    batch_size = max(1, parallel)
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        outcomes = await asyncio.gather(*(upgrade_tenant(loc) for loc in batch), return_exceptions=True)
        for location, outcome in zip(batch, outcomes):
            if isinstance(outcome, BaseException):
                logger.error("tenant %s: migration failed: %s", location.key, outcome)
                result["failed"][location.key] = f"{type(outcome).__name__}: {outcome}"
            else:
                result["upgraded"].append(location.key)
        if result["failed"]:
            result["not_run"] = [loc.key for loc in pending[start + batch_size:]]
            break
    return result


async def _run_tenants(keys: Optional[Sequence[str]], parallel: int) -> dict[str, Any]:
    from src.common import database
    from src.common.tenancy.engines import engines

    try:
        return await upgrade_tenants(keys, parallel)
    finally:
        await engines.dispose_all()
        await database.engine.dispose()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.common.tenancy.migrate",
                                     description="Upgrade the control database or the tenant databases.")
    sub = parser.add_subparsers(dest="target", required=True)
    sub.add_parser("control", help="the control tree (and, in single mode, the tenant tree) on the "
                                   "control database")
    tenants = sub.add_parser("tenants", help="every tenant database (or --tenant KEY) to the tenant tree's head")
    tenants.add_argument("--tenant", action="append", dest="keys", metavar="KEY",
                         help="only this tenant key (repeatable)")
    tenants.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL,
                         help=f"tenants upgraded at a time (default {DEFAULT_PARALLEL})")
    sub.add_parser("all", help="control, then in TENANCY_MODE=split every tenant database (what a deploy runs)")
    sub.add_parser("tenant-db", help=f"one tenant database, the URL in ${URL_VARIABLE} (what `tenants` runs)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.target in ("control", "all"):
        from src.common.tenancy.session import tenancy_mode

        upgrade_control()
        if args.target == "control" or tenancy_mode() != "split":
            return 0
        args.keys, args.parallel = None, DEFAULT_PARALLEL
    if args.target == "tenant-db":
        from sqlalchemy.engine import make_url

        url = os.environ.get(URL_VARIABLE)
        if not url:
            parser.error(f"tenant-db needs ${URL_VARIABLE}")
        print(f"version {asyncio.run(migrate_tenant_database(make_url(url)))}")
        return 0
    result = asyncio.run(_run_tenants(args.keys, args.parallel))
    print(f"target {result['version']}: upgraded {len(result['upgraded'])}, "
          f"already current {len(result['skipped'])}, failed {len(result['failed'])}, "
          f"not run {len(result['not_run'])}")
    for key, error in result["failed"].items():
        print(f"  {key}: {error}")
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
