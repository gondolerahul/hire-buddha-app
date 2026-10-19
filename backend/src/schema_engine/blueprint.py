"""The blueprint (tech spec §8.1, §8.2): a JSON document describing every
business object of one business.

    {"version": 8, "base_pack": "1.0", "objects": {
        "shipment": {"storage": {"schema": "custom", "table": "shipment"},
                     "label": "Shipment", "plural": "Shipments",
                     "fields": {"order": {"type": "ref", "to": "order", "on_delete": "restrict", "required": true},
                                "status": {"type": "enum", "values": ["pending", "delivered"], "default": "pending"}},
                     "indexes": [["status"]], "unique": [], "events": true, "aliases": {}}}}

Every object also has the system columns (``SYSTEM_COLUMNS``). No JSON field
type for business data (D09). Names match ``^[a-z][a-z0-9_]{1,47}$`` and are not
system column names or the Data API's own terms (SQL reserved words are fine:
every identifier is quoted). Pure: no database here.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, Iterable, List, Tuple

NAME = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
SCHEMAS = ("business", "custom")
SYSTEM_COLUMNS = ("id", "created_at", "updated_at", "created_by", "updated_by", "row_version", "archived_at",
                  "owner_user_id")
FIELD_TYPES = ("text", "long_text", "integer", "decimal", "money", "boolean", "date", "datetime", "enum",
               "email", "phone", "url", "ref", "file")
ON_DELETE = ("restrict", "cascade", "set_null")
SENSITIVITY = ("none", "pii", "secret")
MAX_TEXT = 10_000
MAX_OBJECTS = 200
MAX_FIELDS = 200
# Names the Data API keeps for its own query terms and paths. SQL reserved
# words are allowed: every identifier is quoted (§8.2 refused them, but its own
# examples — an ``order`` object — need them).
RESERVED = frozenset({"filter", "fields", "sort", "page", "include", "links", "batch", "reports", "schema",
                      "openapi", "auth", "healthz", "readyz", "v1"})


class BlueprintError(ValueError):
    """A blueprint (or part of one) that is not valid; the message says where."""


def check_name(name: Any, where: str) -> str:
    if not isinstance(name, str) or not NAME.match(name):
        raise BlueprintError(f"{where}: {name!r} must be lower-case letters, digits and _, starting with a letter, "
                             "2–48 characters")
    if name in RESERVED:
        raise BlueprintError(f"{where}: {name!r} is a reserved word")
    if name in SYSTEM_COLUMNS:
        raise BlueprintError(f"{where}: {name!r} is a system column")
    return name


def empty() -> Dict[str, Any]:
    return {"version": 0, "base_pack": None, "objects": {}}


def objects(blueprint: Dict[str, Any], *, include_archived: bool = False) -> Dict[str, Dict[str, Any]]:
    """The blueprint's objects (archived ones only when asked)."""
    return {name: obj for name, obj in (blueprint.get("objects") or {}).items()
            if include_archived or not obj.get("archived")}


def fields(obj: Dict[str, Any], *, include_archived: bool = False) -> Dict[str, Dict[str, Any]]:
    return {name: field for name, field in (obj.get("fields") or {}).items()
            if include_archived or not field.get("archived")}


def resolve_object(blueprint: Dict[str, Any], name: str) -> Tuple[str, Dict[str, Any]]:
    """An object by its name or an alias it had (renamed objects answer to old names)."""
    current = objects(blueprint)
    if name in current:
        return name, current[name]
    for real, obj in current.items():
        if name in (obj.get("former_names") or []):
            return real, obj
    raise BlueprintError(f"no object {name!r}")


def resolve_field(obj: Dict[str, Any], name: str) -> str:
    current = fields(obj)
    if name in current or name in SYSTEM_COLUMNS:
        return name
    aliases = obj.get("aliases") or {}
    if name in aliases and aliases[name] in current:
        return aliases[name]
    raise BlueprintError(f"no field {name!r}")


def validate_field(name: str, spec: Any, *, where: str, known_objects: Iterable[str]) -> Dict[str, Any]:
    """One field definition, checked and normalised."""
    if not isinstance(spec, dict):
        raise BlueprintError(f"{where}: a field is an object with a type")
    kind = spec.get("type")
    if kind not in FIELD_TYPES:
        raise BlueprintError(f"{where}: type must be one of {', '.join(FIELD_TYPES)} (no JSON fields: D09)")
    out: Dict[str, Any] = {"type": kind}
    for flag in ("required", "archived"):
        if spec.get(flag):
            out[flag] = True
    if spec.get("label"):
        out["label"] = str(spec["label"])[:120]
    sensitivity = spec.get("sensitivity", "none")
    if sensitivity not in SENSITIVITY:
        raise BlueprintError(f"{where}: sensitivity must be one of {', '.join(SENSITIVITY)}")
    if sensitivity != "none":
        out["sensitivity"] = sensitivity
    if kind == "text":
        length = spec.get("max_length", 255)
        if not isinstance(length, int) or not 1 <= length <= MAX_TEXT:
            raise BlueprintError(f"{where}: max_length must be 1–{MAX_TEXT}")
        out["max_length"] = length
    if kind == "decimal":
        precision, scale = spec.get("precision", 18), spec.get("scale", 4)
        if not (isinstance(precision, int) and isinstance(scale, int) and 1 <= precision <= 38
                and 0 <= scale <= precision):
            raise BlueprintError(f"{where}: precision 1–38 and scale 0–precision")
        out.update(precision=precision, scale=scale)
    if kind == "enum":
        values = spec.get("values")
        if not isinstance(values, list) or not values or len(values) > 200 \
                or not all(isinstance(v, str) and 0 < len(v) <= 100 for v in values) or len(set(values)) != len(values):
            raise BlueprintError(f"{where}: values must be 1–200 distinct texts")
        out["values"] = list(values)
    if kind == "ref":
        target = spec.get("to")
        if target not in set(known_objects):
            raise BlueprintError(f"{where}: to must name an object of the blueprint")
        on_delete = spec.get("on_delete", "restrict")
        if on_delete not in ON_DELETE:
            raise BlueprintError(f"{where}: on_delete must be one of {', '.join(ON_DELETE)}")
        if on_delete == "set_null" and spec.get("required"):
            raise BlueprintError(f"{where}: a required reference cannot be set to null")
        out.update(to=target, on_delete=on_delete)
    if "default" in spec and spec["default"] is not None:
        out["default"] = _check_default(kind, spec["default"], out, where)
    return out


def _check_default(kind: str, value: Any, field: Dict[str, Any], where: str) -> Any:
    ok = {
        "text": isinstance(value, str), "long_text": isinstance(value, str), "email": isinstance(value, str),
        "phone": isinstance(value, str), "url": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "decimal": isinstance(value, (int, float)) and not isinstance(value, bool),
        "money": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool), "enum": value in field.get("values", []),
    }.get(kind, False)
    if not ok:
        raise BlueprintError(f"{where}: default {value!r} does not fit a {kind} field")
    return value


def validate_object(name: str, spec: Any, *, known_objects: Iterable[str]) -> Dict[str, Any]:
    where = f"objects.{name}"
    check_name(name, where)
    if not isinstance(spec, dict):
        raise BlueprintError(f"{where}: an object is a JSON object")
    storage = spec.get("storage") or {"schema": "custom", "table": name}
    if storage.get("schema") not in SCHEMAS:
        raise BlueprintError(f"{where}: storage.schema must be business or custom")
    check_name(storage.get("table"), f"{where}.storage.table")
    known = set(known_objects) | {name}
    raw_fields = spec.get("fields") or {}
    if not isinstance(raw_fields, dict) or len(raw_fields) > MAX_FIELDS:
        raise BlueprintError(f"{where}: fields is an object of at most {MAX_FIELDS} fields")
    out_fields = {}
    for field_name, field_spec in raw_fields.items():
        check_name(field_name, f"{where}.fields")
        out_fields[field_name] = validate_field(field_name, field_spec, where=f"{where}.fields.{field_name}",
                                                known_objects=known)
    out: Dict[str, Any] = {
        "storage": {"schema": storage["schema"], "table": storage["table"]},
        "label": str(spec.get("label") or name.replace("_", " ").title())[:120],
        "plural": str(spec.get("plural") or (spec.get("label") or name.replace("_", " ").title()) + "s")[:120],
        "fields": out_fields,
        "indexes": _column_sets(spec.get("indexes"), out_fields, f"{where}.indexes"),
        "unique": _column_sets(spec.get("unique"), out_fields, f"{where}.unique"),
        "events": bool(spec.get("events", True)),
        "aliases": dict(spec.get("aliases") or {}),
    }
    for key in ("archived", "platform", "former_names", "description", "alias_until", "former_until"):
        if spec.get(key):
            out[key] = copy.deepcopy(spec[key])
    if spec.get("row_policy"):
        out["row_policy"] = row_policy(spec["row_policy"], out_fields, where)
    return out


def row_policy(value: Any, out_fields: Dict[str, Any], where: str) -> Dict[str, str]:
    """``{"owner_field": <text or email field>, "match": "email" | "id"}``: the field that
    says whose a record is, for app users limited to their own rows (§11.6)."""
    if not isinstance(value, dict):
        raise BlueprintError(f"{where}.row_policy: an object")
    owner = value.get("owner_field")
    match = value.get("match", "email")
    if owner not in out_fields or out_fields[owner]["type"] not in ("text", "email"):
        raise BlueprintError(f"{where}.row_policy.owner_field: a text or email field of the object")
    if match not in ("email", "id"):
        raise BlueprintError(f"{where}.row_policy.match: email or id")
    return {"owner_field": owner, "match": match}


def _column_sets(value: Any, out_fields: Dict[str, Any], where: str) -> List[List[str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise BlueprintError(f"{where}: a list of column lists")
    sets = []
    for columns in value:
        if not isinstance(columns, list) or not columns or len(columns) > 5:
            raise BlueprintError(f"{where}: each is a list of 1–5 columns")
        for column in columns:
            if column not in out_fields and column not in SYSTEM_COLUMNS:
                raise BlueprintError(f"{where}: {column!r} is not a field")
        sets.append(list(columns))
    return sets


def validate(document: Any) -> Dict[str, Any]:
    """A whole blueprint, checked and normalised (raises :class:`BlueprintError`)."""
    if not isinstance(document, dict):
        raise BlueprintError("a blueprint is a JSON object")
    raw = document.get("objects") or {}
    if not isinstance(raw, dict) or len(raw) > MAX_OBJECTS:
        raise BlueprintError(f"objects: at most {MAX_OBJECTS}")
    names = list(raw)
    out = {"version": int(document.get("version") or 0), "base_pack": document.get("base_pack"),
           "objects": {name: validate_object(name, raw[name], known_objects=names) for name in names}}
    tables = [(o["storage"]["schema"], o["storage"]["table"]) for o in out["objects"].values()]
    if len(tables) != len(set(tables)):
        raise BlueprintError("two objects use the same table")
    for name, obj in out["objects"].items():
        if obj["storage"]["schema"] == "business" and not obj.get("platform"):
            raise BlueprintError(f"objects.{name}: only platform objects live in schema business")
    return out


def sensitive_fields(obj: Dict[str, Any]) -> List[str]:
    """Fields whose values never leave the row into events (§9.4)."""
    return [n for n, f in fields(obj, include_archived=True).items() if f.get("sensitivity") in ("pii", "secret")]

