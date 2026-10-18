"""Condition triggers' checks (plan WS4 4.10; tech spec §7.5): "every hour,
if stock < 10 → the re-order agent".

A condition trigger is a schedule (``cron``) with a ``condition``: one number
from the business's records — a count, or a sum / average / min / max of a
field over the records that pass a filter — compared with a value:

    {"object": "product", "filter": [{"field": "stock", "op": "lt", "value": 10}],
     "measure": {"fn": "count"}, "op": "gt", "value": 0}

(``measure`` defaults to count, ``op`` to gt and ``value`` to 0: "any record
matches".) The router checks it when the schedule fires, with the Data API's
report query and no model call; false is a ``skipped_condition_false`` firing,
true starts the run with the result in its input (``condition``) and in the
input template (``{{ trigger.condition.value }}``). Filters take the Data
API's operators and relative times (``now-7d``).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict

MEASURES = ("count", "sum", "avg", "min", "max")
COMPARISONS = {"gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "eq": "=", "ne": "≠"}
FILTER_OPERATORS = ("eq", "ne", "in", "nin", "gt", "gte", "lt", "lte", "contains", "starts_with", "is_null")
MAX_FILTERS = 20
CHECK_TIMEOUT = "10s"


class ConditionError(ValueError):
    """A condition that cannot be saved or checked; the message says why."""


@dataclass(frozen=True)
class Checked:
    holds: bool
    value: Any
    summary: str

    def view(self) -> Dict[str, Any]:
        return {"holds": self.holds, "value": self.value, "summary": self.summary}


def validate(spec: Any) -> Dict[str, Any]:
    """The condition in its stored form (raises :class:`ConditionError`)."""
    if not isinstance(spec, dict):
        raise ConditionError("a condition trigger needs a condition: {object, filter, measure, op, value}")
    obj = str(spec.get("object") or "").strip()
    if not obj:
        raise ConditionError("condition.object names the records to check, e.g. product")
    rules = spec.get("filter") or []
    if not isinstance(rules, list) or len(rules) > MAX_FILTERS:
        raise ConditionError(f"condition.filter is a list of at most {MAX_FILTERS} conditions")
    out_filter = []
    for rule in rules:
        if isinstance(rule, (list, tuple)) and len(rule) == 3:
            rule = {"field": rule[0], "op": rule[1], "value": rule[2]}
        if not isinstance(rule, dict) or not rule.get("field"):
            raise ConditionError("each condition.filter entry is {field, op, value}")
        op = rule.get("op") or "eq"
        if op not in FILTER_OPERATORS:
            raise ConditionError(f"condition.filter op is one of {', '.join(FILTER_OPERATORS)}")
        out_filter.append([str(rule["field"]), op, rule.get("value")])
    measure = spec.get("measure") or {"fn": "count"}
    if not isinstance(measure, dict) or measure.get("fn", "count") not in MEASURES:
        raise ConditionError(f"condition.measure.fn is one of {', '.join(MEASURES)}")
    fn = measure.get("fn", "count")
    if fn != "count" and not measure.get("field"):
        raise ConditionError(f"condition.measure: {fn} needs a field")
    op = spec.get("op") or "gt"
    if op not in COMPARISONS:
        raise ConditionError(f"condition.op is one of {', '.join(COMPARISONS)}")
    value = spec.get("value", 0)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConditionError("condition.value is a number")
    try:
        Decimal(str(value))
    except Exception:  # noqa: BLE001
        raise ConditionError("condition.value is a number") from None
    out_measure = {"fn": fn} if fn == "count" else {"fn": fn, "field": str(measure["field"])}
    return {"object": obj, "filter": out_filter, "measure": out_measure, "op": op, "value": value}


def _compare(actual: Any, op: str, expected: Any) -> bool:
    if actual is None:
        return False  # a sum or average over no records is no number: the condition does not hold
    left, right = Decimal(str(actual)), Decimal(str(expected))
    return {"gt": left > right, "gte": left >= right, "lt": left < right, "lte": left <= right,
            "eq": left == right, "ne": left != right}[op]


def describe(spec: Dict[str, Any], value: Any = None) -> str:
    measure = spec["measure"]
    what = "count" if measure["fn"] == "count" else f"{measure['fn']} of {measure['field']}"
    where = " and ".join(f"{f} {op} {v}" for f, op, v in spec.get("filter") or [])
    told = f"{what} of {spec['object']}" + (f" where {where}" if where else "")
    is_now = f" is {value}" if value is not None else ""
    return f"{told}{is_now} ({COMPARISONS[spec['op']]} {spec['value']})"


async def check(company_id: Any, spec: Dict[str, Any]) -> Checked:
    """The condition against the business's records now (raises :class:`ConditionError`)."""
    from sqlalchemy import text

    from src.data_api import records
    from src.data_api.model import model_for
    from src.schema_engine import engine as schema

    spec = validate(spec)
    try:
        engine, _ = await schema.business_engine(company_id)
    except schema.RecordsUnavailable as error:
        raise ConditionError(str(error)) from None
    blueprint = await schema.active_blueprint(engine, company_id)
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL statement_timeout = '{CHECK_TIMEOUT}'"))
            report = await records.report(conn, model_for(company_id, blueprint), {
                "object": spec["object"], "measures": [spec["measure"]], "filter": spec["filter"]})
    except records.RecordError as error:
        raise ConditionError(f"the check failed: {error.detail}") from None
    row = report["rows"][0] if report["rows"] else {}
    value = next(iter(row.values()), None)  # no grouping: the one measure
    holds = _compare(value, spec["op"], spec["value"])
    return Checked(holds=holds, value=value, summary=describe(spec, value))
