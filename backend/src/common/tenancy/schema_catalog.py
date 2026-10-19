"""One schema of a database as Postgres prints it, and how to make one schema match another (Phase 14 WS2 2.7).

``catalog(conn, schema)`` reads, from the catalogue: each table's columns
(type, NOT NULL, default), constraints (``pg_get_constraintdef``) and indexes
(``pg_get_indexdef``), the enum types with their labels, and the materialised
views with their indexes — with the schema's own name taken out, so schema
``platform`` of a tenant database and ``public`` of the shared database compare
equal when they hold the same things. Version tables are left out.

``differences(a, b)`` lists what differs. ``adoption_plan(have, want)`` is the
DDL that turns ``have`` into ``want`` without losing data — it refuses
(:class:`AdoptionRefused`) a table or column ``want`` lacks, or a column of
another type. ``migrate.py`` adopts a tenant database built from the models
before the tenant tree existed this way: the tree's baseline is built in a
scratch schema next to it, the plan runs, and the two must then be equal.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

VERSION_TABLES = frozenset({"alembic_version", "alembic_version_tenant_platform"})


class AdoptionRefused(RuntimeError):
    """A database that cannot be brought to the baseline without losing data."""


def _strip(text: str, schema: str) -> str:
    return text.replace(f'"{schema}".', "").replace(f"{schema}.", "")


async def catalog(conn: Any, schema: str, tables: Optional[Iterable[str]] = None) -> dict[str, Any]:
    """``{"tables": {name: {"columns", "constraints", "indexes"}}, "enums", "views"}`` of ``schema``.

    ``conn`` is an asyncpg connection; its ``search_path`` is set to ``schema``
    (then ``public``) so definitions name that schema's objects unqualified.
    ``tables``: only these tables.
    """
    only = set(tables) if tables is not None else None
    await conn.execute(f'SET search_path TO "{schema}", public')
    result: dict[str, Any] = {"tables": {}, "enums": {}, "views": {}}
    rows = await conn.fetch(
        """SELECT c.relname AS table, a.attname AS column, format_type(a.atttypid, a.atttypmod) AS type,
                  a.attnotnull AS not_null, pg_get_expr(d.adbin, d.adrelid) AS "default"
           FROM pg_attribute a
           JOIN pg_class c ON c.oid = a.attrelid
           JOIN pg_namespace n ON n.oid = c.relnamespace
           LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
           WHERE n.nspname = $1 AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
           ORDER BY c.relname, a.attnum""", schema)
    for row in rows:
        if row["table"] in VERSION_TABLES or (only is not None and row["table"] not in only):
            continue
        table = result["tables"].setdefault(row["table"], {"columns": {}, "constraints": {}, "indexes": {}})
        table["columns"][row["column"]] = (_strip(row["type"], schema), row["not_null"],
                                           _strip(row["default"], schema) if row["default"] else None)
    constraints = await conn.fetch(
        """SELECT c.relname AS table, k.conname AS name, k.contype AS kind, pg_get_constraintdef(k.oid) AS definition
           FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid
           JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = $1""", schema)
    for row in constraints:
        if row["table"] in result["tables"]:
            result["tables"][row["table"]]["constraints"][row["name"]] = (row["kind"],
                                                                          _strip(row["definition"], schema))
    indexes = await conn.fetch(
        """SELECT i.tablename AS table, i.indexname AS name, i.indexdef,
                  EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conindid = (quote_ident(i.schemaname) || '.'
                          || quote_ident(i.indexname))::regclass) AS of_constraint
           FROM pg_indexes i WHERE i.schemaname = $1""", schema)
    views = {row["name"]: row["definition"] for row in await conn.fetch(
        "SELECT matviewname AS name, definition FROM pg_matviews WHERE schemaname = $1", schema)}
    for name, definition in views.items():
        result["views"][name] = {"definition": _strip(definition, schema), "indexes": {}}
    for row in indexes:
        definition = _strip(row["indexdef"], schema)
        if row["table"] in result["tables"]:
            result["tables"][row["table"]]["indexes"][row["name"]] = (row["of_constraint"], definition)
        elif row["table"] in result["views"]:
            result["views"][row["table"]]["indexes"][row["name"]] = definition
    enums = await conn.fetch(
        """SELECT t.typname AS name, array_agg(e.enumlabel ORDER BY e.enumsortorder) AS labels
           FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid
           JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = $1 GROUP BY t.typname""", schema)
    result["enums"] = {row["name"]: list(row["labels"]) for row in enums}
    return result


def differences(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    """What differs between two catalogues, one line each (empty: the same)."""
    found: list[str] = []
    for name in sorted(set(left["tables"]) | set(right["tables"])):
        a, b = left["tables"].get(name), right["tables"].get(name)
        if a is None or b is None:
            found.append(f"table {name}: only in the {'second' if a is None else 'first'}")
            continue
        for part in ("columns", "constraints", "indexes"):
            for key in sorted(set(a[part]) | set(b[part])):
                if a[part].get(key) != b[part].get(key):
                    found.append(f"{name} {part[:-1]} {key}: {a[part].get(key)!r} != {b[part].get(key)!r}")
    for part in ("enums", "views"):
        for key in sorted(set(left[part]) | set(right[part])):
            if left[part].get(key) != right[part].get(key):
                found.append(f"{part[:-1]} {key}: {left[part].get(key)!r} != {right[part].get(key)!r}")
    return found


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _column_ddl(name: str, spec: tuple) -> str:
    type_, not_null, default = spec
    return f"{_q(name)} {type_}" + (f" DEFAULT {default}" if default else "") + (" NOT NULL" if not_null else "")


def adoption_plan(have: dict[str, Any], want: dict[str, Any]) -> list[str]:
    """The statements that turn the schema ``have`` describes into ``want`` (run with that schema first on
    the ``search_path``). Raises :class:`AdoptionRefused` where only losing data would do it."""
    refused = sorted(f"table {t}" for t in set(have["tables"]) - set(want["tables"]))
    for name in sorted(set(have["tables"]) & set(want["tables"])):
        columns, wanted = have["tables"][name]["columns"], want["tables"][name]["columns"]
        refused += [f"column {name}.{c}" for c in sorted(set(columns) - set(wanted))]
        refused += [f"column {name}.{c}: {columns[c][0]}, the baseline has {wanted[c][0]}"
                    for c in sorted(set(columns) & set(wanted)) if columns[c][0] != wanted[c][0]]
    for enum in sorted(set(have["enums"]) & set(want["enums"])):
        if have["enums"][enum] != want["enums"][enum]:
            refused.append(f"enum {enum}: {have['enums'][enum]}, the baseline has {want['enums'][enum]}")
    if refused:
        raise AdoptionRefused("cannot adopt without losing data: " + "; ".join(refused))

    empty = {"columns": {}, "constraints": {}, "indexes": {}}
    first: list[str] = []      # drops, foreign keys first
    then: list[str] = []
    last: list[str] = []       # foreign keys, after every other constraint
    for enum in sorted(set(want["enums"]) - set(have["enums"])):
        labels = ", ".join("'" + label.replace("'", "''") + "'" for label in want["enums"][enum])
        then.append(f"CREATE TYPE {_q(enum)} AS ENUM ({labels})")
    for name in sorted(set(want["tables"]) - set(have["tables"])):
        columns = ", ".join(_column_ddl(c, spec) for c, spec in want["tables"][name]["columns"].items())
        then.append(f"CREATE TABLE {_q(name)} ({columns})")
    drop_keys: list[str] = []
    drop_other: list[str] = []
    for name in sorted(want["tables"]):
        a, b = have["tables"].get(name, empty), want["tables"][name]
        for column, spec in b["columns"].items():
            if name in have["tables"] and column not in a["columns"]:
                then.append(f"ALTER TABLE {_q(name)} ADD COLUMN {_column_ddl(column, spec)}")
            elif column in a["columns"] and a["columns"][column] != spec:
                _, not_null, default = spec
                if a["columns"][column][2] != default:
                    then.append(f"ALTER TABLE {_q(name)} ALTER COLUMN {_q(column)} "
                                + (f"SET DEFAULT {default}" if default else "DROP DEFAULT"))
                if a["columns"][column][1] != not_null:
                    then.append(f"ALTER TABLE {_q(name)} ALTER COLUMN {_q(column)} "
                                + ("SET NOT NULL" if not_null else "DROP NOT NULL"))
        for constraint, (kind, definition) in a["constraints"].items():
            if b["constraints"].get(constraint) != (kind, definition):
                (drop_keys if kind == "f" else drop_other).append(
                    f"ALTER TABLE {_q(name)} DROP CONSTRAINT {_q(constraint)}")
        backed = set(a["constraints"]) | set(b["constraints"])
        for index, (_, definition) in a["indexes"].items():
            if index not in backed and b["indexes"].get(index, (None, None))[1] != definition:
                drop_other.append(f"DROP INDEX {_q(index)}")
        for constraint, (kind, definition) in b["constraints"].items():
            if a["constraints"].get(constraint) != (kind, definition):
                (last if kind == "f" else then).append(
                    f"ALTER TABLE {_q(name)} ADD CONSTRAINT {_q(constraint)} {definition}")
        for index, (_, definition) in b["indexes"].items():
            if index not in backed and a["indexes"].get(index, (None, None))[1] != definition:
                then.append(definition)
    for view, spec in want["views"].items():
        if have["views"].get(view) != spec:
            if view in have["views"]:
                first.append(f"DROP MATERIALIZED VIEW {_q(view)}")
            last.append(f"CREATE MATERIALIZED VIEW {_q(view)} AS {spec['definition'].rstrip(';')}")
            last.extend(spec["indexes"].values())
    return first + drop_keys + drop_other + then + last
