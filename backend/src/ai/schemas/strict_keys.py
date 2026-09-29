"""schemas/strict_keys.py — find keys a payload sends that its model does not declare.

Pydantic drops undeclared keys by default. For entity configuration that turns a
typo into a silent no-op: ``retry_polcy`` saves with ``200 OK`` and the entity
runs with the default retry policy. :func:`unknown_keys` walks a raw payload
against a model — through nested models, lists and dicts of models — and returns
the dotted path of every key the model would have dropped.

It is applied to request payloads only (see ``HierarchicalEntityCreateRequest``):
the nested models are also used to read stored entities back, and a key that
predates today's schema must not make an existing entity unreadable.

A model may list keys it accepts without declaring them in a
``extra_accepted_keys: ClassVar[frozenset[str]]`` — a legacy spelling a
validator translates, or a key a client sends that is deliberately not stored.
"""
from __future__ import annotations

import types
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel

__all__ = ["unknown_keys"]


def _model_candidates(annotation: Any) -> list[type[BaseModel]]:
    """The BaseModel types a (possibly Optional/Union) annotation admits directly."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    if get_origin(annotation) in (Union, types.UnionType):
        found: list[type[BaseModel]] = []
        for arg in get_args(annotation):
            found.extend(_model_candidates(arg))
        return found
    return []


def _container_items(annotation: Any, value: Any) -> list[tuple[Any, Any, str]]:
    """(item annotation, item value, path suffix) for list and dict annotations."""
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        items: list[tuple[Any, Any, str]] = []
        for arg in get_args(annotation):
            items.extend(_container_items(arg, value))
        return items
    args = get_args(annotation)
    if origin in (list, tuple, set) and args and isinstance(value, (list, tuple)):
        return [(args[0], item, f"[{i}]") for i, item in enumerate(value)]
    if origin is dict and len(args) == 2 and isinstance(value, dict):
        return [(args[1], item, f".{key}") for key, item in value.items()]
    return []


def _check_value(annotation: Any, value: Any, path: str) -> list[str]:
    if isinstance(value, dict):
        candidates = _model_candidates(annotation)
        if candidates:
            # For a union of models, the payload matches whichever fits best.
            results = [unknown_keys(model, value, path) for model in candidates]
            return min(results, key=len)
    found: list[str] = []
    for item_annotation, item, suffix in _container_items(annotation, value):
        found.extend(_check_value(item_annotation, item, f"{path}{suffix}"))
    return found


def unknown_keys(model: type[BaseModel], data: Any, path: str = "") -> list[str]:
    """Dotted paths of keys in ``data`` that ``model`` (recursively) does not declare."""
    if not isinstance(data, dict) or model.model_config.get("extra") == "allow":
        return []
    fields = model.model_fields
    accepted = getattr(model, "extra_accepted_keys", frozenset())
    by_name: dict[str, Any] = {}
    for name, field in fields.items():
        by_name[name] = field
        if field.alias:
            by_name[field.alias] = field
    found: list[str] = []
    for key, value in data.items():
        key_path = f"{path}.{key}" if path else str(key)
        field = by_name.get(key)
        if field is None:
            if key not in accepted:
                found.append(key_path)
            continue
        found.extend(_check_value(field.annotation, value, key_path))
    return found
