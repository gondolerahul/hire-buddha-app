"""The tenant split tool (Phase 14 WS7 7.1, 7.3; tech spec §15.1).

    python -m src.common.tenancy.split COMPANY_ID [--server NAME] [--replace] [--dry-run]

Moves one business's rows from the shared database (``public``, where every
business lives with ``TENANCY_MODE=single``) into its own tenant database
(``platform``):

1. **provision** — the business's tenant is requested and provisioned if it
   is not yet (WS2 2.8): its database exists at the tenant tree's head;
2. **plan** — every tenant-plane table, in foreign-key order; a table with
   ``company_id`` is selected by it, one without (campaign calls, CORTEX
   nodes, connection secrets …) through its parent's key;
3. **copy** — in one transaction on the tenant database: rows streamed from
   the shared database in batches (asyncpg ``COPY``); a column that points
   forward or at its own table (an agent's ``active_version_id``, a run's
   ``parent_run_id``) is copied as ``NULL`` and set once every row is in;
4. **verify** — per table, the count and a checksum (md5 over each row's
   columns, sorted) on both sides; the manifest lists every table and whether
   it matches, and is kept in the tenant's storage
   (``t-<key>/migration/<timestamp>/manifest.json``).

Nothing is deleted from the shared database: the switch to ``split`` mode
(and, later, a purge of the moved rows) is the cutover's decision. Rows the
tenant database already holds for the business — besides what provisioning
itself writes (the base pack's blueprint, its events) — stop the copy unless
``--replace`` (delete them first). Webhook-endpoint bindings already became
triggers (migration ``p14_webhook_triggers``, WS3) and are copied with the
triggers (7.3); phone numbers stay control rows.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

BATCH_ROWS = 5000
# What provisioning writes into a new tenant database itself (base pack v1).
PROVISIONED_TABLES = frozenset({"schema_blueprints", "schema_changes", "events", "audit_log"})


class SplitRefused(RuntimeError):
    pass


@dataclass
class TablePlan:
    name: str
    columns: List[str]
    scope_sql: str                       # a WHERE clause on the table aliased "t", $1 = company id
    deferred: List[str] = field(default_factory=list)   # FK columns set after every row is in
    key: List[str] = field(default_factory=list)        # primary key columns
    # Columns of a type asyncpg's binary COPY cannot encode (pgvector): read as
    # text, written with a cast through INSERT.
    text_cast: Dict[str, str] = field(default_factory=dict)


def _tenant_tables() -> List[Any]:
    from src.common.orm_models import import_all_models
    from src.common.tenancy.bases import TENANT, plane_tables

    import_all_models()
    return plane_tables(TENANT)


def plan(tables: Optional[List[Any]] = None,
         extra_keys: Optional[List[Tuple[str, str, str]]] = None) -> List[TablePlan]:
    """Every tenant table in an order its foreign keys allow, with how to select the business's rows.

    ``extra_keys``: ``(table, column, referred table)`` the database has beyond the models'."""
    tables = tables if tables is not None else _tenant_tables()
    by_name = {t.name: t for t in tables}
    scopes: Dict[str, str] = {}

    def scope(table: Any, seen: Tuple[str, ...] = ()) -> Optional[str]:
        if table.name in scopes:
            return scopes[table.name]
        if "company_id" in table.columns:
            scopes[table.name] = "t.company_id = $1"
            return scopes[table.name]
        # Through a NOT NULL key first: a nullable one would miss the rows where it is empty.
        for fk in sorted(table.foreign_keys, key=lambda f: (f.parent.nullable, f.parent.name)):
            parent = fk.column.table
            if parent.name == table.name or parent.name in seen or parent.name not in by_name:
                continue
            parent_scope = scope(parent, seen + (table.name,))
            if parent_scope:
                inner = parent_scope.replace("t.", "p.")
                scopes[table.name] = (f't."{fk.parent.name}" IN (SELECT p."{fk.column.name}" FROM "{parent.name}" p '
                                      f"WHERE {inner})")
                return scopes[table.name]
        return None

    # Every key between tenant tables: the models' and the database's own (the
    # CORTEX package declares none of its keys to the host's agents and runs).
    edges: Dict[str, Set[Tuple[str, str]]] = {name: set() for name in by_name}  # child -> {(column, parent)}
    for name, table in by_name.items():
        for fk in table.foreign_keys:
            if fk.column.table.name in by_name:
                edges[name].add((fk.parent.name, fk.column.table.name))
    for child, column, parent in extra_keys or []:
        if child in by_name and parent in by_name and column in by_name[child].columns:
            edges[child].add((column, parent))

    def nullable(table: str, column: str) -> bool:
        return bool(by_name[table].columns[column].nullable)

    order: List[str] = []
    placed: Set[str] = set()
    deferred: Dict[str, List[str]] = {name: [] for name in by_name}
    remaining = set(by_name)
    while remaining:
        progress = False
        for name in sorted(remaining):
            needs = {parent for _, parent in edges[name] if parent != name}
            if needs <= placed:
                order.append(name)
                placed.add(name)
                remaining.discard(name)
                progress = True
        if not progress:  # a cycle: place a table whose unmet keys may be NULL for now (set afterwards)
            def unmet(n: str) -> List[Tuple[str, str]]:
                return [(c, parent) for c, parent in edges[n] if parent in remaining and parent != n]

            def in_cycle(begin: str) -> bool:
                stack, seen = [parent for _, parent in unmet(begin)], set()
                while stack:
                    node = stack.pop()
                    if node == begin:
                        return True
                    if node in seen or node not in remaining:
                        continue
                    seen.add(node)
                    stack.extend(parent for _, parent in unmet(node))
                return False

            candidates = [n for n in sorted(remaining)
                          if in_cycle(n) and all(nullable(n, c) for c, _ in unmet(n))]
            if not candidates:
                raise SplitRefused(f"a cycle of NOT NULL keys among {sorted(remaining)}")
            name = min(candidates, key=lambda n: len(unmet(n)))
            deferred[name].extend(c for c, _ in unmet(name))
            order.append(name)
            placed.add(name)
            remaining.discard(name)
    plans = []
    for name in order:
        table = by_name[name]
        selfrefs = [c for c, parent in edges[name] if parent == name]
        where = scope(table)
        if where is None:
            raise SplitRefused(f"table {name} has neither company_id nor a key to a table that has")
        casts = {c.name: "vector" for c in table.columns if type(c.type).__name__ == "Vector"}
        plans.append(TablePlan(name=name, columns=[c.name for c in table.columns], scope_sql=where,
                               deferred=sorted(set(deferred[name] + selfrefs)),
                               key=[c.name for c in table.primary_key.columns], text_cast=casts))
    return plans


async def _database_keys(conn: Any, schema: str = "platform") -> List[Tuple[str, str, str]]:
    """``(table, column, referred table)`` of every single-column foreign key in ``schema``."""
    rows = await conn.fetch(
        """SELECT c.relname AS child, a.attname AS col, p.relname AS parent
           FROM pg_constraint k
           JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace
           JOIN pg_class p ON p.oid = k.confrelid
           JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = k.conkey[1]
           WHERE k.contype = 'f' AND n.nspname = $1 AND array_length(k.conkey, 1) = 1""", schema)
    return [(r["child"], r["col"], r["parent"]) for r in rows]


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _checksum_sql(p: TablePlan) -> str:
    row = "row(" + ", ".join(f"t.{_q(c)}" + ("::text" if c in p.text_cast else "") for c in p.columns) + ")::text"
    return (f"SELECT count(*), coalesce(md5(string_agg(md5({row}), '' ORDER BY md5({row}))), '') "
            f"FROM {_q(p.name)} t WHERE {p.scope_sql}")


async def _connect(url: Any, *, schema: str) -> Any:
    import asyncpg

    from src.common.platform import adapter_name

    dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)
    extra: Dict[str, Any] = {}
    if adapter_name("db_auth") == "entra_token":  # the workload's Entra token is the password
        from src.common.platform.dbauth import POSTGRES_ENTRA_SCOPE
        from src.common.platform.identity import sync_token

        extra["password"] = await asyncio.to_thread(sync_token, POSTGRES_ENTRA_SCOPE)
    conn = await asyncpg.connect(dsn, **extra)
    await conn.execute(f"SET search_path TO {schema}, public")
    return conn


async def split_tenant(company_id: Any, *, server_name: Optional[str] = None, replace: bool = False,
                       dry_run: bool = False) -> Dict[str, Any]:
    from sqlalchemy.engine import make_url

    from src.common.config import settings
    from src.common.tenancy import provisioner
    from src.common.tenancy.directory import directory
    from src.common.tenancy.engines import tenant_url

    company_id = uuid.UUID(str(company_id))
    started = time.monotonic()
    timings: Dict[str, float] = {}
    if not dry_run:
        await provisioner.request_tenant(company_id, server_name=server_name)
        result = await provisioner.provision(company_id)
        if result.get("status") != "active":
            raise SplitRefused(f"the tenant could not be provisioned: {result}")
        timings["provision_s"] = round(time.monotonic() - started, 2)
    directory.invalidate(company_id)
    location = await directory.find(company_id)
    source = await _connect(make_url(settings.CONTROL_DATABASE_URL), schema="public")
    target = await _connect(tenant_url(location), schema="platform") if location and not dry_run else None
    plans = plan(extra_keys=await _database_keys(target if target is not None else source,
                                                 "platform" if target is not None else "public"))
    manifest: Dict[str, Any] = {"company_id": str(company_id), "tenant_key": location.key if location else None,
                                "started_at": datetime.utcnow().isoformat() + "Z", "tables": []}
    try:
        if dry_run:
            for p in plans:
                count, checksum = await source.fetchrow(_checksum_sql(p), company_id)
                manifest["tables"].append({"table": p.name, "source_count": count, "source_checksum": checksum})
            manifest["dry_run"] = True
            return manifest
        present = {}
        for p in plans:
            count = await target.fetchval(f"SELECT count(*) FROM {_q(p.name)} t WHERE {p.scope_sql}", company_id)
            if count and p.name not in PROVISIONED_TABLES:
                present[p.name] = count
        if present and not replace:
            raise SplitRefused(f"the tenant database already holds this business's rows: {present} "
                               "(--replace deletes them first)")
        copy_started = time.monotonic()
        async with target.transaction():
            if replace:
                for p in plans:  # the forward and self references first, or the deletes trip over them
                    if p.deferred and p.name not in PROVISIONED_TABLES:
                        sets = ", ".join(f"{_q(c)} = NULL" for c in p.deferred)
                        await target.execute(f"UPDATE {_q(p.name)} t SET {sets} WHERE {p.scope_sql}", company_id)
                for p in reversed(plans):
                    if p.name not in PROVISIONED_TABLES:
                        await target.execute(f"DELETE FROM {_q(p.name)} t WHERE {p.scope_sql}", company_id)
            for p in plans:
                if p.name in PROVISIONED_TABLES:
                    # Provisioning wrote the base pack's rows; the shared database has none for a
                    # business without its own database (WS4 needed one), but keep both if it does.
                    existing = {tuple(r) for r in await target.fetch(
                        f"SELECT {', '.join(_q(k) for k in p.key)} FROM {_q(p.name)} t WHERE {p.scope_sql}",
                        company_id)}
                else:
                    existing = set()
                columns = p.columns
                select_cols = ", ".join(("NULL" if c in p.deferred else
                                         f"t.{_q(c)}::text" if c in p.text_cast else f"t.{_q(c)}") for c in columns)
                insert_sql = None
                if p.text_cast:
                    params = ", ".join(f"${i + 1}" + (f"::{p.text_cast[c]}" if c in p.text_cast else "")
                                       for i, c in enumerate(columns))
                    insert_sql = (f"INSERT INTO platform.{_q(p.name)} ({', '.join(_q(c) for c in columns)}) "
                                  f"VALUES ({params})")

                async def _write(rows: List[tuple]) -> None:
                    if insert_sql:
                        await target.executemany(insert_sql, rows)
                    else:
                        await target.copy_records_to_table(p.name, records=rows, columns=columns,
                                                           schema_name="platform")
                key_index = [columns.index(k) for k in p.key]
                async with source.transaction():
                    cursor = source.cursor(f"SELECT {select_cols} FROM {_q(p.name)} t WHERE {p.scope_sql}",
                                           company_id, prefetch=BATCH_ROWS)
                    batch: List[tuple] = []
                    async for record in cursor:
                        values = tuple(record)
                        if existing and tuple(values[i] for i in key_index) in existing:
                            continue
                        batch.append(values)
                        if len(batch) >= BATCH_ROWS:
                            await _write(batch)
                            batch = []
                    if batch:
                        await _write(batch)
            for p in plans:   # the forward and self references, now that every row is in
                if not p.deferred:
                    continue
                key_cols = ", ".join(f"t.{_q(k)}" for k in p.key)
                rows = await source.fetch(
                    f"SELECT {key_cols}, {', '.join(f't.{_q(c)}' for c in p.deferred)} FROM {_q(p.name)} t "
                    f"WHERE {p.scope_sql} AND ({' OR '.join(f't.{_q(c)} IS NOT NULL' for c in p.deferred)})",
                    company_id)
                if not rows:
                    continue
                sets = ", ".join(f"{_q(c)} = ${i + 1 + len(p.key)}" for i, c in enumerate(p.deferred))
                where = " AND ".join(f"{_q(k)} = ${i + 1}" for i, k in enumerate(p.key))
                await target.executemany(f"UPDATE {_q(p.name)} SET {sets} WHERE {where}", [tuple(r) for r in rows])
        timings["copy_s"] = round(time.monotonic() - copy_started, 2)
        verify_started = time.monotonic()
        mismatches = 0
        for p in plans:
            source_count, source_sum = await source.fetchrow(_checksum_sql(p), company_id)
            target_count, target_sum = await target.fetchrow(_checksum_sql(p), company_id)
            match = (source_count, source_sum) == (target_count, target_sum)
            if p.name in PROVISIONED_TABLES and not match:
                match = target_count >= source_count   # plus what provisioning wrote
            mismatches += 0 if match else 1
            manifest["tables"].append({"table": p.name, "source_count": source_count, "target_count": target_count,
                                       "source_checksum": source_sum, "target_checksum": target_sum,
                                       "match": match})
        timings["verify_s"] = round(time.monotonic() - verify_started, 2)
        manifest.update(mismatches=mismatches, timings={**timings, "total_s": round(time.monotonic() - started, 2)},
                        finished_at=datetime.utcnow().isoformat() + "Z")
    finally:
        await source.close()
        if target is not None:
            await target.close()
    await _keep(manifest)
    return manifest


async def _keep(manifest: Dict[str, Any]) -> None:
    from src.common.platform.storage import get_storage

    if not manifest.get("tenant_key"):
        return
    key = f"t-{manifest['tenant_key']}/migration/{datetime.utcnow():%Y%m%dT%H%M%S}/manifest.json"
    try:
        await get_storage().put(key, json.dumps(manifest, indent=2, default=str).encode(),
                                content_type="application/json")
        manifest["stored_at"] = key
    except Exception:  # noqa: BLE001 - the manifest is also returned
        logger.warning("split manifest not stored", exc_info=True)


async def _cli(args: argparse.Namespace) -> int:
    from src.common import database
    from src.common.tenancy.engines import engines

    try:
        manifest = await split_tenant(args.company_id, server_name=args.server, replace=args.replace,
                                      dry_run=args.dry_run)
    except SplitRefused as error:
        print(f"refused: {error}")
        return 2
    finally:
        await engines.dispose_all()
        await database.engine.dispose()
    for row in manifest["tables"]:
        print(f"{row['table']:28} {row.get('source_count', 0):>9} -> {row.get('target_count', '-'):>9} "
              f"{'ok' if row.get('match', True) else 'MISMATCH'}")
    print(json.dumps({k: v for k, v in manifest.items() if k != "tables"}, default=str))
    return 1 if manifest.get("mismatches") else 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.common.tenancy.split")
    parser.add_argument("company_id")
    parser.add_argument("--server")
    parser.add_argument("--replace", action="store_true", help="delete the business's rows in the tenant database first")
    parser.add_argument("--dry-run", action="store_true", help="count and checksum the source only")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(_cli(args))


if __name__ == "__main__":
    sys.exit(main())
