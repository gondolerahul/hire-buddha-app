"""The trigger filter language (tech spec §7.5): safe JSON, evaluated in Python.

A filter is a condition, or ``{"all": [...]}`` / ``{"any": [...]}`` of filters:

    {"all": [
        {"path": "data.platform", "op": "eq", "value": "instagram"},
        {"any": [
            {"path": "data.text", "op": "contains", "value": "price"},
            {"path": "data.text", "op": "contains", "value": "ship"}]}]}

A condition reads ``path`` (dots into the event: ``type``, ``source``,
``data.author.name``, ``data.after.status``…) and compares it by ``op``:

    eq ne in nin gt gte lt lte   compare (numbers with numbers, text with text)
    contains starts_with         text, ignoring case; ``contains`` on a list = membership
    exists                       the path is present (``value`` false: absent)
    changed                      data triggers: ``value`` is a field in ``data.changed``

A missing path makes a comparison false, never an error, so a filter written
for one event shape does not break on another. No code runs: there is no
expression syntax to inject into. Limits: depth 4, 20 conditions.
"""
from __future__ import annotations

from typing import Any, Dict, List

MAX_DEPTH = 4
MAX_CONDITIONS = 20
MAX_PATH_SEGMENTS = 8

OPERATORS = ("eq", "ne", "in", "nin", "gt", "gte", "lt", "lte", "contains", "starts_with", "exists", "changed")
_MISSING = object()


class FilterError(ValueError):
    """A filter that is not valid; the message names what and where."""


def validate(spec: Any) -> Dict[str, Any]:
    """The filter itself, or :class:`FilterError`. ``None`` / ``{}`` matches everything."""
    if spec in (None, {}):
        return {}
    counted = [0]
    _check(spec, depth=1, where="filter", counted=counted)
    return spec


def _check(node: Any, *, depth: int, where: str, counted: List[int]) -> None:
    if depth > MAX_DEPTH:
        raise FilterError(f"{where}: nested deeper than {MAX_DEPTH} levels")
    if not isinstance(node, dict):
        raise FilterError(f"{where}: must be an object")
    groups = [key for key in ("all", "any") if key in node]
    if groups:
        if len(node) != 1:
            raise FilterError(f"{where}: a group has exactly one key, 'all' or 'any'")
        children = node[groups[0]]
        if not isinstance(children, list) or not children:
            raise FilterError(f"{where}.{groups[0]}: must be a non-empty list")
        for index, child in enumerate(children):
            _check(child, depth=depth + 1, where=f"{where}.{groups[0]}[{index}]", counted=counted)
        return
    counted[0] += 1
    if counted[0] > MAX_CONDITIONS:
        raise FilterError(f"more than {MAX_CONDITIONS} conditions")
    unknown = set(node) - {"path", "op", "value"}
    if unknown:
        raise FilterError(f"{where}: unknown key(s) {', '.join(sorted(unknown))}")
    op = node.get("op")
    if op not in OPERATORS:
        raise FilterError(f"{where}: op must be one of {', '.join(OPERATORS)}")
    if op == "changed":
        if not isinstance(node.get("value"), str) or not node["value"]:
            raise FilterError(f"{where}: 'changed' needs the field name as value")
        return
    path = node.get("path")
    if not isinstance(path, str) or not path or len(path.split(".")) > MAX_PATH_SEGMENTS \
            or any(not part for part in path.split(".")):
        raise FilterError(f"{where}: path must be dotted names, like data.text")
    if op == "exists":
        if "value" in node and not isinstance(node["value"], bool):
            raise FilterError(f"{where}: 'exists' takes true or false")
        return
    if "value" not in node:
        raise FilterError(f"{where}: '{op}' needs a value")
    value = node["value"]
    if op in ("in", "nin"):
        if not isinstance(value, list) or not value:
            raise FilterError(f"{where}: '{op}' needs a non-empty list")
    elif op == "starts_with":
        if not isinstance(value, str):
            raise FilterError(f"{where}: 'starts_with' needs a text value")
    elif op == "contains":
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise FilterError(f"{where}: 'contains' needs a text or number value")
    elif op in ("gt", "gte", "lt", "lte"):
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise FilterError(f"{where}: '{op}' needs a number or a text value")


def resolve(event: Dict[str, Any], path: str) -> Any:
    """The value at ``path`` in the event, or a private marker when absent."""
    current: Any = event
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return _MISSING
    return current


def matches(spec: Any, event: Dict[str, Any]) -> bool:
    """Whether the event passes the filter (validate it when the trigger is saved)."""
    if spec in (None, {}):
        return True
    if "all" in spec:
        return all(matches(child, event) for child in spec["all"])
    if "any" in spec:
        return any(matches(child, event) for child in spec["any"])
    return _condition(spec, event)


def _comparable(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return False
    numbers = (int, float)
    return (isinstance(left, numbers) and isinstance(right, numbers)) or (isinstance(left, str) and isinstance(right, str))


def _condition(spec: Dict[str, Any], event: Dict[str, Any]) -> bool:
    op = spec["op"]
    if op == "changed":
        changed = resolve(event, "data.changed")
        return isinstance(changed, list) and spec["value"] in changed
    actual = resolve(event, spec["path"])
    if op == "exists":
        return (actual is not _MISSING) == spec.get("value", True)
    if actual is _MISSING:
        return op in ("ne", "nin")  # an absent value is not the value, and not in the list
    expected = spec["value"]
    if op == "eq":
        return _equal(actual, expected)
    if op == "ne":
        return not _equal(actual, expected)
    if op == "in":
        return any(_equal(actual, item) for item in expected)
    if op == "nin":
        return not any(_equal(actual, item) for item in expected)
    if op in ("gt", "gte", "lt", "lte"):
        if not _comparable(actual, expected):
            return False
        return {"gt": actual > expected, "gte": actual >= expected,
                "lt": actual < expected, "lte": actual <= expected}[op]
    if op == "contains":
        if isinstance(actual, list):
            return any(_text_equal(item, expected) for item in actual)
        return isinstance(actual, str) and str(expected).casefold() in actual.casefold()
    if op == "starts_with":
        return isinstance(actual, str) and actual.casefold().startswith(str(expected).casefold())
    return False


def _equal(left: Any, right: Any) -> bool:
    """JSON equality: 1 and 1.0 are the same number; true is not 1; "1" is not 1."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    return type(left) is type(right) and left == right


def _text_equal(item: Any, expected: Any) -> bool:
    if isinstance(item, str) and isinstance(expected, str):
        return item.casefold() == expected.casefold()
    return _equal(item, expected)
