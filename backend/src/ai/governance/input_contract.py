"""governance/input_contract.py — a run's input against the entity's input schema (EP-04).

``io_contract.input_schema`` was authored in the builder, used to draw the run
form, and checked by nothing: a run with the wrong input was created, planned
and paid for, then failed at the first step that needed the missing value.
:func:`input_problems` is checked by ``trigger_execution`` before the run row
exists (a 422).

The check is the subset of JSON Schema the platform writes (D21) — ``type``,
``properties``, ``required``, ``enum`` and an array's ``items`` type; other
keywords are not checked. Names the run page never asks for are not
required either: a step's id or name (``{{research}}`` is that step's output),
``step_N`` references, and the keys the platform fills itself.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

__all__ = ["input_problems"]

_STEP_REF = re.compile(r"^step_\d+")
_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


def _type_ok(value: Any, declared: Any) -> bool:
    kinds = declared if isinstance(declared, list) else [declared]
    for kind in kinds:
        if kind == "null" and value is None:
            return True
        allowed = _TYPES.get(str(kind))
        if allowed is None:
            return True                      # a type this check does not know
        if isinstance(value, bool) and kind in ("number", "integer"):
            continue                         # True is not a number here
        if isinstance(value, allowed):
            return True
    return False


def _plan_names(entity: Any) -> set[str]:
    planning = getattr(entity, "planning", None) or {}
    steps = ((planning.get("static_plan") or {}).get("steps") or []) if isinstance(planning, Mapping) else []
    names: set[str] = set()
    for step in steps:
        if isinstance(step, Mapping):
            names.update(str(v) for v in (step.get("step_id"), step.get("name")) if v)
    return names


def input_problems(entity: Any, input_data: Any) -> list[str]:
    """What is wrong with ``input_data`` for ``entity``'s input schema; [] when fine."""
    from src.ai.schemas.execution import RESERVED_INPUT_KEYS

    contract = getattr(entity, "io_contract", None) or {}
    schema = contract.get("input_schema") if isinstance(contract, Mapping) else None
    if not isinstance(schema, Mapping):
        return []
    data = input_data if isinstance(input_data, Mapping) else {}
    props = schema.get("properties") if isinstance(schema.get("properties"), Mapping) else {}
    exempt = _plan_names(entity)
    problems: list[str] = []

    for name in schema.get("required") or []:
        name = str(name)
        if name in exempt or _STEP_REF.match(name) or name.startswith("__") or name in RESERVED_INPUT_KEYS:
            continue
        value = data.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            problems.append(f"'{name}' is required")

    for name, value in data.items():
        spec = props.get(name) if isinstance(props, Mapping) else None
        if not isinstance(spec, Mapping) or value is None:
            continue
        if "type" in spec and not _type_ok(value, spec["type"]):
            problems.append(f"'{name}' must be {spec['type']}, not {type(value).__name__}")
            continue
        if isinstance(spec.get("enum"), list) and value not in spec["enum"]:
            problems.append(f"'{name}' must be one of {spec['enum']}")
        items = spec.get("items")
        if isinstance(value, list) and isinstance(items, Mapping) and "type" in items:
            bad = [i for i, v in enumerate(value) if not _type_ok(v, items["type"])]
            if bad:
                problems.append(f"'{name}' items {bad} must be {items['type']}")
    return problems
