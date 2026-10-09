"""
tests.harness.purge — delete the companies a test session created, and every
row that references them.

Used by the suites that commit to the shared dev database: e2e (its own
companies and users) and parity (its ``parity-*`` tenants, TS-16). Walks the
real foreign keys, so a new table is covered without listing it here.
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


async def _delete_rows(conn, foreign_keys, company_scoped, table, where, params, path=()) -> None:
    """Delete the rows of ``table`` matching ``where``, after every row that references them.

    A referencing row that belongs to another company is never deleted: it stays,
    the final DELETE fails on it, and the caller rolls the whole purge back.
    ``ON DELETE SET NULL`` references are left to the database, and a
    self-reference (``companies.parent_id``) ends in the one DELETE that removes
    both ends. A reference back from a table already being purged
    (``hierarchical_entities.active_version_id`` → ``entity_versions``) is set
    to NULL first: those rows are deleted next anyway.
    """
    path = path + (table,)
    for child, child_cols, parent_cols, on_delete in foreign_keys.get(table, ()):
        if on_delete == "n" or child == table:
            continue
        child_where = (
            f"({', '.join(child_cols)}) IN "
            f"(SELECT {', '.join(parent_cols)} FROM {table} WHERE {where})"
        )
        if child in company_scoped:
            child_where += " AND (company_id IS NULL OR company_id = ANY(CAST(:company_ids AS uuid[])))"
        if child in path:
            await conn.execute(
                text(f"UPDATE {child} SET {', '.join(f'{c} = NULL' for c in child_cols)} WHERE {child_where}"),
                params,
            )
            continue
        await _delete_rows(conn, foreign_keys, company_scoped, child, child_where, params, path)
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
    foreign_keys: dict[str, list] = {}
    for child, parent, child_cols, parent_cols, on_delete in await conn.execute(text(_FOREIGN_KEYS_SQL)):
        foreign_keys.setdefault(parent, []).append((child, child_cols, parent_cols, on_delete))
    company_scoped = set((await conn.execute(text(_COMPANY_SCOPED_TABLES_SQL))).scalars().all())
    params = {"company_ids": ids, "pattern": user_email_pattern}
    if user_email_pattern:
        await _delete_rows(conn, foreign_keys, company_scoped, "users", "email LIKE :pattern", params)
    await _delete_rows(
        conn, foreign_keys, company_scoped, "companies", "id = ANY(CAST(:company_ids AS uuid[]))", params,
    )
