"""
tests.harness.purge — delete the companies a test session created, and every
row that references them.

Used by the suites that commit to the shared dev database: e2e (its own
companies and users) and parity (its ``parity-*`` tenants, TS-16). Walks the
real foreign keys, so a new table is covered without listing it here, and the
references between control and tenant tables that are no longer keys
(``bases.cross_plane_references()``, Phase 14 WS2 2.3) — doing their
``ON DELETE`` action itself, as the database did for the keys.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional
from uuid import UUID

from sqlalchemy import text

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


# ``pg_constraint.confdeltype`` of each ON DELETE action a reference records.
_ON_DELETE = {None: "a", "CASCADE": "c", "SET NULL": "n"}


async def _delete_rows(conn, foreign_keys, company_scoped, table, where, params, path=()) -> None:
    """Delete the rows of ``table`` matching ``where``, after every row that references them.

    A referencing row that belongs to another company is never deleted: it stays,
    the final DELETE fails on it (a reference that is not a key: this function
    fails), and the caller rolls the whole purge back. ``ON DELETE SET NULL`` is
    left to the database (done here for a reference), ``ON DELETE CASCADE`` of a
    reference deletes every referencing row as the database would, and a
    self-reference (``companies.parent_id``) ends in the one DELETE that removes
    both ends. A reference back from a table already being purged
    (``hierarchical_entities.active_version_id`` → ``entity_versions``) is set
    to NULL first: those rows are deleted next anyway.
    """
    path = path + (table,)
    refused = []
    for child, child_cols, parent_cols, on_delete, is_key in foreign_keys.get(table, ()):
        if child == table or (on_delete == "n" and is_key):
            continue
        referencing = (
            f"({', '.join(child_cols)}) IN "
            f"(SELECT {', '.join(parent_cols)} FROM {table} WHERE {where})"
        )
        if on_delete == "n":
            await conn.execute(
                text(f"UPDATE {child} SET {', '.join(f'{c} = NULL' for c in child_cols)} WHERE {referencing}"),
                params,
            )
            continue
        child_where = referencing
        if child in company_scoped and not (on_delete == "c" and not is_key):
            child_where += " AND (company_id IS NULL OR company_id = ANY(CAST(:company_ids AS uuid[])))"
        if child in path:
            await conn.execute(
                text(f"UPDATE {child} SET {', '.join(f'{c} = NULL' for c in child_cols)} WHERE {child_where}"),
                params,
            )
            continue
        await _delete_rows(conn, foreign_keys, company_scoped, child, child_where, params, path)
        if not is_key and on_delete != "c":
            refused.append((child, referencing))
    for child, referencing in refused:
        if (await conn.execute(text(f"SELECT 1 FROM {child} WHERE {referencing} LIMIT 1"), params)).first():
            raise RuntimeError(f"rows of {child} outside the purged companies still reference {table}")
    await conn.execute(text(f"DELETE FROM {table} WHERE {where}"), params)


async def purge_companies(
    conn: Any,
    company_ids: Iterable[UUID],
    *,
    user_email_pattern: Optional[str] = None,
) -> None:
    """Delete ``company_ids`` and everything that references them, in ``conn``'s
    transaction. With ``user_email_pattern`` (a ``LIKE`` pattern), users whose
    address matches go first, wherever they are now."""
    ids = list(company_ids)
    if not ids:
        return
    from src.common.tenancy.bases import cross_plane_references

    foreign_keys: dict[str, list] = {}
    for child, parent, child_cols, parent_cols, on_delete in await conn.execute(text(_FOREIGN_KEYS_SQL)):
        foreign_keys.setdefault(parent, []).append((child, child_cols, parent_cols, on_delete, True))
    for ref in cross_plane_references():
        foreign_keys.setdefault(ref.referred_table, []).append(
            (ref.table, [ref.column], [ref.referred_column], _ON_DELETE[ref.ondelete], False))
    company_scoped = set((await conn.execute(text(_COMPANY_SCOPED_TABLES_SQL))).scalars().all())
    params = {"company_ids": ids, "pattern": user_email_pattern}
    if user_email_pattern:
        await _delete_rows(conn, foreign_keys, company_scoped, "users", "email LIKE :pattern", params)
    await _delete_rows(
        conn, foreign_keys, company_scoped, "companies", "id = ANY(CAST(:company_ids AS uuid[]))", params,
    )
