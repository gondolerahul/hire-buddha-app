"""Deleting a company's rows: every row that references it, by the database's own keys.

The walk began as the test suites' clean-up (``tests.harness.purge``, which
re-exports this module) and is the control-plane half of erasure
(docs/phase15/13 §6 step 12, §10):

* ``purge_companies`` — Flow B: the companies and **everything** that refers to
  them, the company rows included;
* ``erase_company_rows`` — Flow A: everything that refers to the company
  **except** the tables kept as its books (``keep``); a kept row that pointed at
  a deleted one loses that pointer (set to NULL), and the company row stays
  (the caller anonymises it).

It walks the real foreign keys, so a new table is covered without listing it
here, and the references between control and tenant tables that are no longer
keys (``bases.cross_plane_references()``, Phase 14 WS2 2.3) — doing their
``ON DELETE`` action itself, as the database did for the keys. A row of another
company that refers to a purged one is never deleted: the purge fails instead
and the caller's transaction rolls it all back.
"""
from __future__ import annotations

from typing import Any, FrozenSet, Iterable, Optional
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

_TABLES_SQL = """
SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()
"""

# The proof of an erasure names its company by id and must outlive it (docs/phase15/13 §12).
PROOF_TABLES = frozenset({"company_offboardings"})

# ``pg_constraint.confdeltype`` of each ON DELETE action a reference records.
_ON_DELETE = {None: "a", "CASCADE": "c", "SET NULL": "n"}


class PurgeRefused(RuntimeError):
    """A row the purge may not delete still refers to one it must."""


async def _graph(conn: Any) -> tuple[dict, set]:
    from src.common.tenancy.bases import cross_plane_references

    foreign_keys: dict[str, list] = {}
    for child, parent, child_cols, parent_cols, on_delete in await conn.execute(text(_FOREIGN_KEYS_SQL)):
        foreign_keys.setdefault(parent, []).append((child, child_cols, parent_cols, on_delete, True))
    # A tenant-plane table is in this database only where tenancy is not split (or from before the split).
    present = set((await conn.execute(text(_TABLES_SQL))).scalars().all())
    for ref in cross_plane_references():
        if ref.table not in present:
            continue
        foreign_keys.setdefault(ref.referred_table, []).append(
            (ref.table, [ref.column], [ref.referred_column], _ON_DELETE[ref.ondelete], False))
    company_scoped = set((await conn.execute(text(_COMPANY_SCOPED_TABLES_SQL))).scalars().all()) - PROOF_TABLES
    return foreign_keys, company_scoped


async def _null_out(conn: Any, child: str, cols: list, where: str, params: dict) -> None:
    await conn.execute(text(f"UPDATE {child} SET {', '.join(f'{c} = NULL' for c in cols)} WHERE {where}"), params)


async def _delete_rows(conn, foreign_keys, company_scoped, table, where, params, path=(),
                       keep: FrozenSet[str] = frozenset()) -> None:
    """Delete the rows of ``table`` matching ``where``, after every row that references them.

    A referencing row that belongs to another company is never deleted: it stays,
    the final DELETE fails on it (a reference that is not a key: this function
    fails), and the caller rolls the whole purge back. ``ON DELETE SET NULL`` is
    left to the database (done here for a reference), ``ON DELETE CASCADE`` of a
    reference deletes every referencing row as the database would, and a
    self-reference (``companies.parent_id``) ends in the one DELETE that removes
    both ends. A reference back from a table already being purged
    (``hierarchical_entities.active_version_id`` → ``entity_versions``) is set
    to NULL first: those rows are deleted next anyway. A table in ``keep`` is
    never deleted from: its reference is set to NULL.
    """
    # No row matches: nothing to delete, and nothing can refer to it — the whole subtree is skipped.
    if (await conn.execute(text(f"SELECT 1 FROM {table} WHERE {where} LIMIT 1"), params)).first() is None:
        return
    path = path + (table,)
    refused = []
    for child, child_cols, parent_cols, on_delete, is_key in foreign_keys.get(table, ()):
        if child == table or (on_delete == "n" and is_key):
            continue
        referencing = (
            f"({', '.join(child_cols)}) IN "
            f"(SELECT {', '.join(parent_cols)} FROM {table} WHERE {where})"
        )
        if on_delete == "n" or child in keep:
            await _null_out(conn, child, child_cols, referencing, params)
            continue
        child_where = referencing
        if child in company_scoped and not (on_delete == "c" and not is_key):
            child_where += " AND (company_id IS NULL OR company_id = ANY(CAST(:company_ids AS uuid[])))"
        if child in path:
            await _null_out(conn, child, child_cols, child_where, params)
            continue
        await _delete_rows(conn, foreign_keys, company_scoped, child, child_where, params, path, keep)
        if not is_key and on_delete != "c":
            refused.append((child, referencing))
    for child, referencing in refused:
        if (await conn.execute(text(f"SELECT 1 FROM {child} WHERE {referencing} LIMIT 1"), params)).first():
            raise PurgeRefused(f"rows of {child} outside the purged companies still reference {table}")
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
    foreign_keys, company_scoped = await _graph(conn)
    params = {"company_ids": ids, "pattern": user_email_pattern}
    if user_email_pattern:
        await _delete_rows(conn, foreign_keys, company_scoped, "users", "email LIKE :pattern", params)
    # Tenant rows that keep their company as a plain id with no reference marker
    # (the automation tables: events, triggers, waits, the time index) go too.
    covered = {child for child, cols, *_ in foreign_keys.get("companies", ()) if list(cols) == ["company_id"]}
    for table in sorted(company_scoped - covered):
        await _delete_rows(conn, foreign_keys, company_scoped, table,
                           "company_id = ANY(CAST(:company_ids AS uuid[]))", params)
    await _delete_rows(
        conn, foreign_keys, company_scoped, "companies", "id = ANY(CAST(:company_ids AS uuid[]))", params,
    )


async def erase_company_rows(conn: Any, company_id: UUID, *, keep: FrozenSet[str]) -> dict:
    """Flow A: delete every row that refers to the company except the tables in ``keep``
    (the company row is never deleted here); the number of rows removed per table."""
    foreign_keys, company_scoped = await _graph(conn)
    params = {"company_ids": [company_id]}
    before = await row_counts(conn, company_id, company_scoped)
    for child, child_cols, parent_cols, on_delete, is_key in foreign_keys.get("companies", ()):
        if child in keep or child == "companies":
            continue
        where = " OR ".join(f"{col} = ANY(CAST(:company_ids AS uuid[]))" for col in child_cols)
        if on_delete == "n" and is_key:
            continue          # the database sets it NULL when the company goes; it does not go here
        await _delete_rows(conn, foreign_keys, company_scoped, child, f"({where})", params, keep=keep)
    covered = {child for child, cols, *_ in foreign_keys.get("companies", ()) if list(cols) == ["company_id"]}
    for table in sorted(company_scoped - covered - keep - {"companies"}):
        await _delete_rows(conn, foreign_keys, company_scoped, table,
                           "company_id = ANY(CAST(:company_ids AS uuid[]))", params, keep=keep)
    after = await row_counts(conn, company_id, company_scoped)
    return {t: before.get(t, 0) - after.get(t, 0) for t in before if before.get(t, 0) != after.get(t, 0)}


async def row_counts(conn: Any, company_id: UUID, company_scoped: Optional[set] = None) -> dict:
    """Rows per table that carry ``company_id`` (the inventory; verification)."""
    if company_scoped is None:
        company_scoped = set((await conn.execute(text(_COMPANY_SCOPED_TABLES_SQL))).scalars().all()) - PROOF_TABLES
    tables = sorted(company_scoped)
    if not tables:
        return {}
    union = " UNION ALL ".join(f"SELECT '{t}' AS t, count(*) AS n FROM {t} WHERE company_id = :c" for t in tables)
    return {t: n for t, n in (await conn.execute(text(union), {"c": company_id})).all() if n}
