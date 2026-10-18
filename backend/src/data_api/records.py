"""Reading and writing a business's records (tech spec §9.2, §9.4).

Reads: ``filter[field][op]=value`` (``eq ne in nin gt gte lt lte contains
starts_with is_null``), ``sort=-created_at,name``, ``page[size]`` (≤ 500),
``page[after]`` (an opaque cursor), ``fields=a,b``; archived records are left
out unless asked. Writes, in one transaction: the row (``row_version`` + 1),
an ``audit_log`` row and a ``record.<object>.<created|updated|archived>``
event whose data carries the record's id, the changed field names and the
record after the change — never a ``pii`` or ``secret`` field's value. The
router is nudged after the commit. Values are checked against the blueprint
(type, length, enum, format, required); a reference that does not exist, a
unique value taken, are 422s.
"""
from __future__ import annotations

import base64
import json
import re
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import and_, asc, desc, func, insert, literal, select, update
from sqlalchemy.exc import IntegrityError

from src.data_api.model import Model
from src.schema_engine import blueprint as bp

MAX_PAGE = 500
DEFAULT_PAGE = 50
OPERATORS = ("eq", "ne", "in", "nin", "gt", "gte", "lt", "lte", "contains", "starts_with", "is_null")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE = re.compile(r"^\+?[0-9 ()\-.]{6,20}$")
URL = re.compile(r"^https?://\S+$")
SYSTEM_READ_ONLY = ("id", "created_at", "updated_at", "created_by", "updated_by", "row_version", "archived_at")


class RecordError(Exception):
    """A request the records cannot serve; ``status`` and ``code`` for the problem response."""

    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


# ── Values ─────────────────────────────────────────────────────────────────

def _parse(kind: str, spec: Dict[str, Any], value: Any, name: str) -> Any:
    """A value for a field, as stored (raises :class:`RecordError` 422)."""
    if value is None:
        return None
    try:
        if kind in ("text", "long_text"):
            value = str(value)
            if kind == "text" and len(value) > spec.get("max_length", 255):
                raise ValueError(f"at most {spec.get('max_length', 255)} characters")
            return value
        if kind == "email":
            if not EMAIL.match(str(value)):
                raise ValueError("not an e-mail address")
            return str(value).strip().lower()
        if kind == "phone":
            if not PHONE.match(str(value)):
                raise ValueError("not a phone number")
            return str(value).strip()
        if kind == "url":
            if not URL.match(str(value)):
                raise ValueError("not an http(s) address")
            return str(value)
        if kind == "enum":
            if value not in spec["values"]:
                raise ValueError(f"must be one of {', '.join(spec['values'])}")
            return value
        if kind == "integer":
            if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
                raise ValueError("not a whole number")
            return int(value)
        if kind in ("decimal", "money"):
            if isinstance(value, bool):
                raise ValueError("not a number")
            return Decimal(str(value))
        if kind == "boolean":
            if isinstance(value, bool):
                return value
            if str(value).lower() in ("true", "false"):
                return str(value).lower() == "true"
            raise ValueError("not true or false")
        if kind == "date":
            return value if isinstance(value, date) else date.fromisoformat(str(value))
        if kind == "datetime":
            if isinstance(value, datetime):
                moment = value
            else:
                moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if moment.tzinfo is not None:
                from datetime import timezone

                moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
            return moment
        if kind in ("ref", "file"):
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, TypeError, InvalidOperation) as error:
        raise RecordError(422, "invalid_value", f"{name}: {error}") from None
    raise RecordError(422, "invalid_value", f"{name}: unsupported type")


def _json(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat() + "Z" if value.tzinfo is None else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def to_json(row: Any, obj: Dict[str, Any], wanted: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """A row as the API returns it: system columns and the live fields."""
    data = dict(row._mapping)
    names = list(bp.SYSTEM_COLUMNS)
    for name, spec in bp.fields(obj).items():
        names.append(name)
        if spec["type"] == "money":
            names.append(f"{name}_currency")
    if wanted:
        names = ["id", "row_version"] + [n for n in names if n in wanted and n not in ("id", "row_version")]
    return {n: _json(data.get(n)) for n in names}


def _values(obj: Dict[str, Any], body: Any, *, creating: bool) -> Dict[str, Any]:
    """The columns a create or update writes, checked against the blueprint."""
    if not isinstance(body, dict):
        raise RecordError(422, "invalid_body", "the body is a JSON object of fields")
    live = bp.fields(obj)
    out: Dict[str, Any] = {}
    for key, value in body.items():
        if key in SYSTEM_READ_ONLY:
            raise RecordError(422, "read_only", f"{key} is set by the platform")
        if key == "owner_user_id":
            out[key] = _parse("ref", {}, value, key)
            continue
        if key.endswith("_currency") and key[:-9] in live and live[key[:-9]]["type"] == "money":
            if value is not None and not re.match(r"^[A-Z]{3}$", str(value)):
                raise RecordError(422, "invalid_value", f"{key}: a three-letter currency code")
            out[key] = value
            continue
        try:
            name = bp.resolve_field(obj, key)
        except bp.BlueprintError:
            raise RecordError(422, "unknown_field", f"{key} is not a field of this object") from None
        spec = live[name]
        if value is None and spec.get("required"):
            raise RecordError(422, "required", f"{name} is required")
        out[name] = _parse(spec["type"], spec, value, name)
    if creating:
        missing = [n for n, s in live.items() if s.get("required") and n not in out and s.get("default") is None]
        if missing:
            raise RecordError(422, "required", f"required: {', '.join(missing)}")
    return out


# ── Reads ──────────────────────────────────────────────────────────────────

def _column(obj: Dict[str, Any], table: Any, name: str) -> Tuple[Any, str]:
    try:
        real = bp.resolve_field(obj, name)
    except bp.BlueprintError:
        raise RecordError(422, "unknown_field", f"{name} is not a field of this object") from None
    return table.c[real], real


def _condition(obj: Dict[str, Any], table: Any, field_name: str, op: str, raw: Any) -> Any:
    if op not in OPERATORS:
        raise RecordError(422, "invalid_filter", f"operator {op} is not one of {', '.join(OPERATORS)}")
    column, real = _column(obj, table, field_name)
    spec = bp.fields(obj).get(real) or {"type": {"id": "ref", "owner_user_id": "ref", "row_version": "integer"}
                                         .get(real, "datetime")}
    if op == "is_null":
        return column.is_(None) if str(raw).lower() in ("true", "1", "") else column.isnot(None)
    if op in ("in", "nin"):
        values = raw if isinstance(raw, list) else [v for v in str(raw).split(",") if v != ""]
        parsed = [_parse(spec["type"], spec, v, real) for v in values]
        return column.in_(parsed) if op == "in" else column.notin_(parsed)
    if op in ("contains", "starts_with"):
        pattern = str(raw).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return column.ilike(f"%{pattern}%" if op == "contains" else f"{pattern}%", escape="\\")
    value = _parse(spec["type"], spec, _relative(spec["type"], raw), real)
    return {"eq": column == value, "ne": column != value, "gt": column > value, "gte": column >= value,
            "lt": column < value, "lte": column <= value}[op]


RELATIVE = re.compile(r"^(now|today)(?:([+-])(\d+)([mhdw]))?$")
UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


def _relative(kind: str, raw: Any) -> Any:
    """A filter's ``now``, ``now-7d``, ``today+1w`` (UTC) for a date or date-time field."""
    match = RELATIVE.match(raw.strip()) if kind in ("date", "datetime") and isinstance(raw, str) else None
    if not match:
        return raw
    base = datetime.utcnow()
    if match.group(1) == "today":
        base = base.replace(hour=0, minute=0, second=0, microsecond=0)
    if match.group(2):
        step = timedelta(**{UNITS[match.group(4)]: int(match.group(3))})
        base = base + step if match.group(2) == "+" else base - step
    return base.date() if kind == "date" else base


def filters_from_query(items: Sequence[Tuple[str, str]]) -> List[Tuple[str, str, str]]:
    """``filter[field][op]=value`` pairs from a query string."""
    out = []
    for key, value in items:
        match = re.match(r"^filter\[([a-z][a-z0-9_]*)\](?:\[([a-z_]+)\])?$", key)
        if match:
            out.append((match.group(1), match.group(2) or "eq", value))
    return out


def where(obj: Dict[str, Any], table: Any, conditions: Sequence[Tuple[str, str, Any]],
          include_archived: bool = False) -> List[Any]:
    clauses = [] if include_archived else [table.c.archived_at.is_(None)]
    clauses += [_condition(obj, table, f, op, v) for f, op, v in conditions]
    return clauses


def _cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"o": offset}).encode()).decode().rstrip("=")


def _offset(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        return max(0, int(json.loads(base64.urlsafe_b64decode(padded))["o"]))
    except Exception:  # noqa: BLE001
        raise RecordError(400, "invalid_cursor", "page[after] is not a cursor this API gave") from None


async def list_records(conn: Any, model: Model, object_name: str, *, conditions: Sequence[Tuple[str, str, Any]] = (),
                       sort: Optional[str] = None, size: int = DEFAULT_PAGE, after: Optional[str] = None,
                       fields: Optional[Sequence[str]] = None, include_archived: bool = False) -> Dict[str, Any]:
    name, obj, table = model.object(object_name)
    size = max(1, min(int(size or DEFAULT_PAGE), MAX_PAGE))
    order = []
    for part in (sort or "-created_at").split(","):
        part = part.strip()
        if not part:
            continue
        column, _ = _column(obj, table, part.lstrip("-"))
        order.append(desc(column) if part.startswith("-") else asc(column))
    order.append(asc(table.c.id))
    offset = _offset(after)
    query = (select(table).where(and_(*where(obj, table, conditions, include_archived)))
             .order_by(*order).offset(offset).limit(size + 1))
    rows = (await conn.execute(query)).all()
    more = len(rows) > size
    return {"object": name, "items": [to_json(r, obj, fields) for r in rows[:size]],
            "next": _cursor(offset + size) if more else None}


async def get_record(conn: Any, model: Model, object_name: str, record_id: Any) -> Tuple[Dict[str, Any], int]:
    name, obj, table = model.object(object_name)
    rid = _parse("ref", {}, record_id, "id")
    row = (await conn.execute(select(table).where(table.c.id == rid))).first()
    if row is None:
        raise RecordError(404, "not_found", f"no {name} {record_id}")
    return to_json(row, obj), row.row_version


# ── Links (one level of ``ref`` fields, tech spec §9.2) ──────────────────────

MAX_INCLUDE = 3
MAX_LINKS = 100


def relation_of(model: Model, object_name: str, relation: str) -> Tuple[str, str, str]:
    """``("forward", object, field)``: ``relation`` is a link field of the object (an
    order's ``account``); ``("reverse", other, field)``: the records of ``other`` whose
    ``field`` links to it (an order's ``shipment``, or ``shipment.order`` to name the field)."""
    name, obj, _ = model.object(object_name)
    spec = bp.fields(obj).get(relation)
    if spec is not None:
        if spec["type"] != "ref":
            raise RecordError(422, "not_a_link", f"{name}.{relation} is not a link to another object")
        return "forward", name, relation
    other_name, _, field = relation.partition(".")
    try:
        other, other_obj, _ = model.object(other_name)
    except bp.BlueprintError:
        raise RecordError(404, "unknown_relation", f"{name} has no link or linked object {relation!r}") from None
    refs = [f for f, s in bp.fields(other_obj).items() if s["type"] == "ref" and s.get("to") == name
            and (not field or f == field)]
    if not refs:
        raise RecordError(404, "unknown_relation", f"no field of {other} links to {name}")
    if len(refs) > 1:
        raise RecordError(422, "ambiguous_relation", f"{other} links to {name} by {', '.join(refs)}: "
                                                     f"name one, e.g. {other}.{refs[0]}")
    return "reverse", other, refs[0]


async def current_version(conn: Any, model: Model, object_name: str, record_id: Any) -> int:
    """A record's ``row_version`` now (a link changes the record as it is)."""
    _, version = await get_record(conn, model, object_name, record_id)
    return version


async def include(conn: Any, model: Model, object_name: str, items: List[Dict[str, Any]],
                  relations: Sequence[str]) -> None:
    """Each item's linked records under ``_included`` (link fields, one level, at most 3)."""
    if len(relations) > MAX_INCLUDE:
        raise RecordError(422, "too_many_includes", f"include at most {MAX_INCLUDE} links")
    for relation in relations:
        kind, _, field = relation_of(model, object_name, relation)
        if kind != "forward":
            raise RecordError(422, "invalid_include", f"include names a link field; {relation} is not one "
                                                      f"(read /links/{relation} instead)")
        name, obj, _ = model.object(object_name)
        target_name, target_obj, target = model.object(bp.fields(obj)[field]["to"])
        ids = {item[field] for item in items if item.get(field)}
        found = {}
        if ids:
            rows = (await conn.execute(select(target).where(target.c.id.in_([uuid.UUID(i) for i in ids]),
                                                            target.c.archived_at.is_(None)))).all()
            found = {str(r.id): to_json(r, target_obj) for r in rows}
        for item in items:
            item.setdefault("_included", {})[field] = found.get(item.get(field)) if item.get(field) else None


# ── Writes ─────────────────────────────────────────────────────────────────

def _event_data(obj: Dict[str, Any], record: Dict[str, Any], changed: Sequence[str]) -> Dict[str, Any]:
    hidden = set(bp.sensitive_fields(obj))
    after = {k: v for k, v in record.items() if k not in hidden}
    return {"id": record["id"], "changed": sorted(changed), "after": after}


async def _record_event(db: Any, company_id: Any, name: str, verb: str, obj: Dict[str, Any],
                        record: Dict[str, Any], changed: Sequence[str], actor: str) -> Optional[uuid.UUID]:
    from src.automation import store
    from src.automation.events import Envelope

    if not obj.get("events", True):
        return None
    row, created = await store.record(db, company_id, Envelope(
        type=f"record.{name}.{verb}", source=f"data_api:{actor}", trust="internal",
        dedupe_key=f"record:{record['id']}:{record['row_version']}:{verb}", subject=f"{name}:{record['id']}",
        data=_event_data(obj, record, changed)))
    return row.id if created else None


async def _audit(db: Any, company_id: Any, actor: str, action: str, name: str, record_id: Any,
                 changed: Sequence[str]) -> None:
    from src.schema_engine.models import AuditLog

    db.add(AuditLog(id=uuid.uuid4(), company_id=company_id, actor=actor, action=action, object=name,
                    record_id=record_id, changed_fields=sorted(changed)))
    await db.flush()


def _integrity(error: IntegrityError) -> RecordError:
    message = str(getattr(error, "orig", error)).splitlines()[0]
    if "foreign key" in message.lower():
        return RecordError(422, "invalid_reference", f"a referenced record does not exist ({message})")
    if "unique" in message.lower():
        return RecordError(422, "duplicate", f"a unique value is taken ({message})")
    if "not-null" in message.lower() or "null value" in message.lower():
        return RecordError(422, "required", message)
    return RecordError(422, "constraint", message)


async def create_record(db: Any, model: Model, company_id: Any, object_name: str, body: Any, *,
                        actor: str) -> Tuple[Dict[str, Any], Optional[uuid.UUID]]:
    """Insert, audit and emit in ``db``'s transaction (the caller commits, then nudges)."""
    name, obj, table = model.object(object_name)
    values = _values(obj, body, creating=True)
    try:
        async with db.begin_nested():
            row = (await db.execute(insert(table).values(
                id=uuid.uuid4(), created_by=actor, updated_by=actor, **values).returning(*table.c))).first()
    except IntegrityError as error:
        raise _integrity(error) from None
    record = to_json(row, obj)
    await _audit(db, company_id, actor, "created", name, row.id, list(values))
    event_id = await _record_event(db, company_id, name, "created", obj, record, list(values), actor)
    return record, event_id


async def update_record(db: Any, model: Model, company_id: Any, object_name: str, record_id: Any, body: Any, *,
                        actor: str, if_match: Optional[int]) -> Tuple[Dict[str, Any], Optional[uuid.UUID]]:
    """Update one record if ``if_match`` is its ``row_version`` (else 412)."""
    name, obj, table = model.object(object_name)
    rid = _parse("ref", {}, record_id, "id")
    values = _values(obj, body, creating=False)
    if not values:
        raise RecordError(422, "invalid_body", "nothing to change")
    if if_match is None:
        raise RecordError(428, "if_match_required", "send If-Match with the record's ETag")
    try:
        async with db.begin_nested():
            row = (await db.execute(update(table).where(
                table.c.id == rid, table.c.row_version == if_match, table.c.archived_at.is_(None)).values(
                updated_by=actor, updated_at=func.now(), row_version=table.c.row_version + 1, **values)
                .returning(*table.c))).first()
    except IntegrityError as error:
        raise _integrity(error) from None
    if row is None:
        current = (await db.execute(select(table.c.row_version, table.c.archived_at)
                                    .where(table.c.id == rid))).first()
        if current is None:
            raise RecordError(404, "not_found", f"no {name} {record_id}")
        if current.archived_at is not None:
            raise RecordError(409, "archived", f"{name} {record_id} is archived")
        raise RecordError(412, "stale", f"{name} {record_id} changed since (now version {current.row_version})")
    record = to_json(row, obj)
    await _audit(db, company_id, actor, "updated", name, row.id, list(values))
    event_id = await _record_event(db, company_id, name, "updated", obj, record, list(values), actor)
    return record, event_id


async def archive_record(db: Any, model: Model, company_id: Any, object_name: str, record_id: Any, *,
                         actor: str) -> Tuple[Dict[str, Any], Optional[uuid.UUID]]:
    name, obj, table = model.object(object_name)
    rid = _parse("ref", {}, record_id, "id")
    row = (await db.execute(update(table).where(table.c.id == rid, table.c.archived_at.is_(None)).values(
        archived_at=func.now(), updated_by=actor, updated_at=func.now(), row_version=table.c.row_version + 1)
        .returning(*table.c))).first()
    if row is None:
        exists = (await db.execute(select(literal(1)).select_from(table).where(table.c.id == rid))).first()
        raise RecordError(404 if exists is None else 409, "not_found" if exists is None else "archived",
                          f"no {name} {record_id}" if exists is None else f"{name} {record_id} is archived")
    record = to_json(row, obj)
    await _audit(db, company_id, actor, "archived", name, row.id, ["archived_at"])
    event_id = await _record_event(db, company_id, name, "archived", obj, record, ["archived_at"], actor)
    return record, event_id


# ── Reports ────────────────────────────────────────────────────────────────

MEASURES = ("count", "sum", "avg", "min", "max")
BUCKETS = ("day", "week", "month", "year")
REPORT_ROWS = 10_000


async def report(conn: Any, model: Model, spec: Any) -> Dict[str, Any]:
    """``{object, group_by: [..], measures: [{fn, field}], filter: [[field, op, value]], bucket: {field, unit}}``."""
    if not isinstance(spec, dict):
        raise RecordError(422, "invalid_report", "a report is a JSON object")
    name, obj, table = model.object(str(spec.get("object") or ""))
    groups, labels = [], []
    for field_name in spec.get("group_by") or []:
        column, real = _column(obj, table, field_name)
        groups.append(column.label(real))
        labels.append(real)
    bucket = spec.get("bucket")
    if bucket:
        if bucket.get("unit") not in BUCKETS:
            raise RecordError(422, "invalid_report", f"bucket.unit is one of {', '.join(BUCKETS)}")
        column, real = _column(obj, table, bucket.get("field") or "created_at")
        groups.append(func.date_trunc(bucket["unit"], column).label(f"{real}_{bucket['unit']}"))
        labels.append(f"{real}_{bucket['unit']}")
    measures = []
    for measure in spec.get("measures") or [{"fn": "count"}]:
        fn = measure.get("fn")
        if fn not in MEASURES:
            raise RecordError(422, "invalid_report", f"fn is one of {', '.join(MEASURES)}")
        if fn == "count":
            measures.append(func.count().label("count"))
            continue
        column, real = _column(obj, table, measure.get("field") or "")
        measures.append(getattr(func, fn)(column).label(f"{fn}_{real}"))
    conditions = [tuple(c) for c in spec.get("filter") or []]
    query = select(*groups, *measures).where(and_(*where(obj, table, conditions)))
    if groups:
        query = query.group_by(*groups).order_by(*groups)
    rows = (await conn.execute(query.limit(REPORT_ROWS + 1))).all()
    return {"object": name, "rows": [{k: _json(v) for k, v in r._mapping.items()} for r in rows[:REPORT_ROWS]],
            "truncated": len(rows) > REPORT_ROWS}
