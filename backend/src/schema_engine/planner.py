"""Change operations → the next blueprint and its DDL plan (tech spec §8.3).

| Operation | Plan |
|-----------|------|
| ``add_object``, ``add_field`` (optional, or with a default), ``add_relation`` (a ``ref`` field), ``add_index`` | additive DDL |
| ``rename_field``, ``rename_object`` | physical rename + an alias the API accepts for 2 more versions |
| ``widen_field`` (longer text, larger numeric) | ``ALTER COLUMN … TYPE`` |
| ``make_required``, ``add_unique`` | a check (no violating rows) runs first; refused if any |
| ``archive_field``, ``archive_object`` | hidden from the API at once; no DDL (the physical drop is a later, approved purge) |
| ``change_type`` | refused: add a new field, backfill, switch, archive the old one |

Names follow §8.2: a business's own objects live in schema ``custom``; the
fields it adds to platform objects start with ``x_``; platform objects and
their platform fields are renamed or archived only by the platform. Pure:
the planner reads the blueprint and the operations, never the database
(row counts, for concurrent indexes, are passed in).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.schema_engine import blueprint as bp

ADDITIVE = ("add_object", "add_field", "add_relation", "add_index", "widen_field")
CHECKED = ("make_required", "add_unique")
RENAMES = ("rename_field", "rename_object")
ARCHIVES = ("archive_field", "archive_object")
OPERATIONS = ADDITIVE + CHECKED + RENAMES + ARCHIVES + ("change_type",)
BIG_TABLE_ROWS = 100_000
ALIAS_VERSIONS = 2


class PlanError(ValueError):
    """An operation that cannot be planned; the message says which and why."""


@dataclass
class Statement:
    sql: str
    concurrently: bool = False   # CREATE INDEX CONCURRENTLY: outside the transaction


@dataclass
class Check:
    """A query that must return 0 before the plan applies (rows that would break it)."""
    sql: str
    message: str


@dataclass
class Plan:
    blueprint: Dict[str, Any]
    statements: List[Statement] = field(default_factory=list)
    checks: List[Check] = field(default_factory=list)
    summary: List[str] = field(default_factory=list)
    kinds: List[str] = field(default_factory=list)

    @property
    def additive(self) -> bool:
        return all(kind in ADDITIVE for kind in self.kinds)

    def as_dict(self) -> Dict[str, Any]:
        return {"statements": [{"sql": s.sql, "concurrently": s.concurrently} for s in self.statements],
                "checks": [{"sql": c.sql, "message": c.message} for c in self.checks],
                "summary": list(self.summary), "additive": self.additive}


def q(name: str) -> str:
    return f'"{name}"'


def table_ref(obj: Dict[str, Any]) -> str:
    return f'{q(obj["storage"]["schema"])}.{q(obj["storage"]["table"])}'


def _literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def column_type(spec: Dict[str, Any]) -> str:
    kind = spec["type"]
    return {
        "text": f"varchar({spec.get('max_length', 255)})", "long_text": "text", "integer": "bigint",
        "decimal": f"numeric({spec.get('precision', 18)},{spec.get('scale', 4)})", "money": "numeric(18,4)",
        "boolean": "boolean", "date": "date", "datetime": "timestamptz", "enum": "text", "email": "text",
        "phone": "text", "url": "text", "ref": "uuid", "file": "uuid",
    }[kind]


SYSTEM_DDL = [
    '"id" uuid PRIMARY KEY DEFAULT gen_random_uuid()',
    '"created_at" timestamptz NOT NULL DEFAULT now()',
    '"updated_at" timestamptz NOT NULL DEFAULT now()',
    '"created_by" text',
    '"updated_by" text',
    '"row_version" integer NOT NULL DEFAULT 1',
    '"archived_at" timestamptz',
    '"owner_user_id" uuid',
]


def _column_ddl(name: str, spec: Dict[str, Any]) -> List[str]:
    parts = [f"{q(name)} {column_type(spec)}"]
    if spec.get("default") is not None:
        parts.append(f"DEFAULT {_literal(spec['default'])}")
    if spec.get("required"):
        parts.append("NOT NULL")
    columns = [" ".join(parts)]
    if spec["type"] == "money":
        columns.append(f'{q(name + "_currency")} char(3)')
    return columns


def _constraints(table: str, name: str, spec: Dict[str, Any], objects: Dict[str, Any]) -> List[str]:
    out = []
    if spec["type"] == "enum":
        values = ", ".join(_literal(v) for v in spec["values"])
        out.append(f"CONSTRAINT {q(f'ck_{table}_{name}'[:63])} CHECK ({q(name)} IN ({values}))")
    if spec["type"] == "ref":
        target = objects[spec["to"]]
        action = {"restrict": "RESTRICT", "cascade": "CASCADE", "set_null": "SET NULL"}[spec["on_delete"]]
        out.append(f"CONSTRAINT {q(f'fk_{table}_{name}'[:63])} FOREIGN KEY ({q(name)}) "
                   f"REFERENCES {table_ref(target)} (\"id\") ON DELETE {action}")
    if spec["type"] == "file":
        out.append(f"CONSTRAINT {q(f'fk_{table}_{name}'[:63])} FOREIGN KEY ({q(name)}) "
                   f'REFERENCES "platform"."artifacts" ("id") ON DELETE SET NULL')
    return out


def _index_name(prefix: str, table: str, columns: List[str]) -> str:
    return f"{prefix}_{table}_{'_'.join(columns)}"[:63]


def _index(obj: Dict[str, Any], columns: List[str], *, unique: bool, rows: int) -> Statement:
    table = obj["storage"]["table"]
    concurrently = rows > BIG_TABLE_ROWS
    name = _index_name("uq" if unique else "ix", table, columns)
    sql = (f"CREATE {'UNIQUE ' if unique else ''}INDEX {'CONCURRENTLY ' if concurrently else ''}"
           f"IF NOT EXISTS {q(name)} ON {table_ref(obj)} ({', '.join(q(c) for c in columns)})")
    return Statement(sql, concurrently=concurrently)


def _object(next_bp: Dict[str, Any], name: str) -> Dict[str, Any]:
    try:
        real, obj = bp.resolve_object(next_bp, name)
    except bp.BlueprintError:
        raise PlanError(f"no object {name!r}") from None
    return next_bp["objects"][real]


def plan(current: Dict[str, Any], operations: List[Dict[str, Any]], *, actor: str = "user",
         row_counts: Optional[Dict[str, int]] = None) -> Plan:
    """The plan for ``operations`` on ``current`` (``actor``: ``platform`` may touch platform objects)."""
    if not isinstance(operations, list) or not operations:
        raise PlanError("operations must be a non-empty list")
    if len(operations) > 50:
        raise PlanError("at most 50 operations in one change")
    next_bp = copy.deepcopy(current)
    next_bp.setdefault("objects", {})
    next_bp["version"] = int(current.get("version") or 0) + 1
    out = Plan(blueprint=next_bp)
    rows = row_counts or {}
    for index, operation in enumerate(operations):
        where = f"operations[{index}]"
        if not isinstance(operation, dict) or operation.get("op") not in OPERATIONS:
            raise PlanError(f"{where}: op must be one of {', '.join(OPERATIONS)}")
        try:
            _apply(out, operation, actor=actor, rows=rows)
        except bp.BlueprintError as error:
            raise PlanError(f"{where}: {error}") from None
        except PlanError as error:
            raise PlanError(f"{where}: {error}") from None
        out.kinds.append(operation["op"])
    try:
        out.blueprint = bp.validate(next_bp)
    except bp.BlueprintError as error:
        raise PlanError(f"the result is not a valid blueprint: {error}") from None
    _expire_aliases(out.blueprint)
    return out


def _platform_guard(obj: Dict[str, Any], field_name: Optional[str], actor: str, what: str) -> None:
    if actor == "platform" or not obj.get("platform"):
        return
    if field_name is None or not field_name.startswith("x_"):
        raise PlanError(f"{what}: platform objects and their platform fields are changed only by the platform")


def _apply(out: Plan, operation: Dict[str, Any], *, actor: str, rows: Dict[str, int]) -> None:
    op = operation["op"]
    next_bp = out.blueprint
    objects = next_bp["objects"]

    if op == "change_type":
        raise PlanError("a type cannot be changed in place: add a new field, backfill it, switch to it, "
                        "then archive the old one")

    if op == "add_object":
        name = bp.check_name(operation.get("object"), "object")
        if name in objects:
            raise PlanError(f"object {name!r} exists")
        definition = dict(operation.get("definition") or {})
        storage = definition.get("storage") or {"schema": "custom", "table": name}
        if storage.get("schema") == "business" and actor != "platform":
            raise PlanError("a business's own objects live in schema custom")
        definition["storage"] = storage
        if actor != "platform":
            definition.pop("platform", None)
        obj = bp.validate_object(name, definition, known_objects=list(objects) + [name])
        objects[name] = obj
        table = obj["storage"]["table"]
        columns = list(SYSTEM_DDL)
        constraints = []
        for field_name, spec in obj["fields"].items():
            columns += _column_ddl(field_name, spec)
            constraints += _constraints(table, field_name, spec, objects)
        out.statements.append(Statement(f"CREATE TABLE {table_ref(obj)} ({', '.join(columns + constraints)})"))
        for column_set in obj["indexes"]:
            out.statements.append(_index(obj, column_set, unique=False, rows=0))
        for column_set in obj["unique"]:
            out.statements.append(_index(obj, column_set, unique=True, rows=0))
        out.summary.append(f"add object {name} ({len(obj['fields'])} fields) as {table_ref(obj)}")
        return

    obj = _object(next_bp, str(operation.get("object") or ""))
    table = obj["storage"]["table"]
    count = rows.get(table, 0)

    if op in ("add_field", "add_relation"):
        name = bp.check_name(operation.get("field"), "field")
        if obj.get("platform") and actor != "platform" and not name.startswith("x_"):
            raise PlanError(f"a field a business adds to the platform object {table} starts with x_")
        if name in obj["fields"]:
            raise PlanError(f"field {name!r} exists")
        spec = dict(operation.get("definition") or {})
        if op == "add_relation":
            spec.setdefault("type", "ref")
        spec = bp.validate_field(name, spec, where=f"field {name}", known_objects=list(objects))
        if spec.get("required") and spec.get("default") is None and count:
            raise PlanError("a required field needs a default on a table with rows; add it optional, "
                            "backfill, then make it required")
        obj["fields"][name] = spec
        for column in _column_ddl(name, spec):
            out.statements.append(Statement(f"ALTER TABLE {table_ref(obj)} ADD COLUMN {column}"))
        for constraint in _constraints(table, name, spec, objects):
            out.statements.append(Statement(f"ALTER TABLE {table_ref(obj)} ADD {constraint}"))
        if spec["type"] == "ref":
            out.statements.append(_index(obj, [name], unique=False, rows=count))
        out.summary.append(f"add field {table}.{name} ({spec['type']})")
        return

    if op in ("add_index", "add_unique"):
        columns = operation.get("columns")
        if not isinstance(columns, list) or not columns:
            raise PlanError("columns: a list of field names")
        columns = [bp.resolve_field(obj, c) for c in columns]
        unique = op == "add_unique"
        (obj["unique"] if unique else obj["indexes"]).append(columns)
        if unique:
            cols = ", ".join(q(c) for c in columns)
            out.checks.append(Check(
                f"SELECT count(*) FROM (SELECT {cols} FROM {table_ref(obj)} WHERE archived_at IS NULL "
                f"GROUP BY {cols} HAVING count(*) > 1) d",
                f"{table}: rows share {', '.join(columns)}; make them unique first"))
        out.statements.append(_index(obj, columns, unique=unique, rows=count))
        out.summary.append(f"add {'unique ' if unique else ''}index on {table}({', '.join(columns)})")
        return

    if op == "widen_field":
        name = bp.resolve_field(obj, str(operation.get("field") or ""))
        _platform_guard(obj, name, actor, "widen_field")
        spec = obj["fields"][name]
        if spec["type"] == "text":
            length = operation.get("max_length")
            if not isinstance(length, int) or not spec["max_length"] < length <= bp.MAX_TEXT:
                raise PlanError(f"max_length must be larger than {spec['max_length']} and at most {bp.MAX_TEXT}")
            spec["max_length"] = length
        elif spec["type"] == "decimal":
            precision, scale = operation.get("precision", spec["precision"]), operation.get("scale", spec["scale"])
            if precision < spec["precision"] or scale < spec["scale"] or precision - scale < spec["precision"] - spec["scale"]:
                raise PlanError("a wider decimal keeps at least as many digits before and after the point")
            spec.update(precision=precision, scale=scale)
        else:
            raise PlanError("only text and decimal fields widen")
        out.statements.append(Statement(f"ALTER TABLE {table_ref(obj)} ALTER COLUMN {q(name)} TYPE {column_type(spec)}"))
        out.summary.append(f"widen {table}.{name} to {column_type(spec)}")
        return

    if op == "make_required":
        name = bp.resolve_field(obj, str(operation.get("field") or ""))
        _platform_guard(obj, name, actor, "make_required")
        obj["fields"][name]["required"] = True
        out.checks.append(Check(f"SELECT count(*) FROM {table_ref(obj)} WHERE {q(name)} IS NULL",
                                f"{table}.{name} is empty in some rows; fill them first"))
        out.statements.append(Statement(f"ALTER TABLE {table_ref(obj)} ALTER COLUMN {q(name)} SET NOT NULL"))
        out.summary.append(f"make {table}.{name} required")
        return

    if op == "rename_field":
        name = bp.resolve_field(obj, str(operation.get("field") or ""))
        _platform_guard(obj, name, actor, "rename_field")
        to = bp.check_name(operation.get("to"), "to")
        if obj.get("platform") and actor != "platform" and not to.startswith("x_"):
            raise PlanError("a business's field on a platform object keeps its x_ prefix")
        if to in obj["fields"]:
            raise PlanError(f"field {to!r} exists")
        obj["fields"][to] = obj["fields"].pop(name)
        for column_sets in (obj["indexes"], obj["unique"]):
            for column_set in column_sets:
                column_set[:] = [to if c == name else c for c in column_set]
        obj.setdefault("aliases", {})[name] = to
        obj.setdefault("alias_until", {})[name] = next_bp["version"] + ALIAS_VERSIONS
        out.statements.append(Statement(f"ALTER TABLE {table_ref(obj)} RENAME COLUMN {q(name)} TO {q(to)}"))
        out.summary.append(f"rename {table}.{name} to {to} (the old name works for {ALIAS_VERSIONS} more versions)")
        return

    if op == "rename_object":
        _platform_guard(obj, None, actor, "rename_object")
        old = next(n for n, o in objects.items() if o is obj)
        to = bp.check_name(operation.get("to"), "to")
        if to in objects:
            raise PlanError(f"object {to!r} exists")
        objects[to] = objects.pop(old)
        obj.setdefault("former_names", []).append(old)
        obj.setdefault("former_until", {})[old] = next_bp["version"] + ALIAS_VERSIONS
        for other in objects.values():
            for spec in other["fields"].values():
                if spec.get("type") == "ref" and spec.get("to") == old:
                    spec["to"] = to
        new_table = to
        out.statements.append(Statement(f"ALTER TABLE {table_ref(obj)} RENAME TO {q(new_table)}"))
        obj["storage"] = {"schema": obj["storage"]["schema"], "table": new_table}
        out.summary.append(f"rename object {old} to {to}")
        return

    if op == "archive_field":
        name = bp.resolve_field(obj, str(operation.get("field") or ""))
        _platform_guard(obj, name, actor, "archive_field")
        spec = obj["fields"][name]
        spec["archived"] = True
        if spec.get("required"):  # writes stop sending it
            spec.pop("required")
            out.statements.append(Statement(f"ALTER TABLE {table_ref(obj)} ALTER COLUMN {q(name)} DROP NOT NULL"))
        out.summary.append(f"archive {table}.{name} (hidden now; dropped only by a later purge)")
        return

    if op == "archive_object":
        _platform_guard(obj, None, actor, "archive_object")
        name = next(n for n, o in objects.items() if o is obj)
        for other_name, other in objects.items():
            if other is obj or other.get("archived"):
                continue
            for field_name, spec in other["fields"].items():
                if spec.get("type") == "ref" and spec.get("to") == name and not spec.get("archived"):
                    raise PlanError(f"{other_name}.{field_name} refers to {name}; archive or change it first")
        obj["archived"] = True
        out.summary.append(f"archive object {name} (hidden now; dropped only by a later purge)")
        return


def _expire_aliases(blueprint: Dict[str, Any]) -> None:
    """Old names stop working ``ALIAS_VERSIONS`` versions after a rename."""
    version = blueprint["version"]
    for obj in blueprint["objects"].values():
        for old, until in list((obj.get("alias_until") or {}).items()):
            if version > until:
                obj["aliases"].pop(old, None)
                obj["alias_until"].pop(old)
        for old, until in list((obj.get("former_until") or {}).items()):
            if version > until:
                obj["former_names"] = [n for n in obj.get("former_names", []) if n != old]
                obj["former_until"].pop(old)
