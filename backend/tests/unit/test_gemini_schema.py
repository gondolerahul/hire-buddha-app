"""Gemini sees the same tool contract as every other provider (P9.9 — LP-18).

The translation to ``types.Schema`` kept type, description, string enums,
items and properties. ``oneOf``/``anyOf``, ``pattern``, ``default``,
``format`` and the bounds were dropped, and an integer ``enum`` was sent as
strings, so the model produced arguments the tool then had to rescue.
"""
from __future__ import annotations

from src.ai.llm.gemini_adapter import GeminiAdapter

TOOL = {
    "name": "book",
    "description": "Book a slot",
    "parameters": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "pattern": "^[A-Z]{3}$", "description": "Airport"},
            "when": {"type": "string", "format": "date-time"},
            "email": {"type": "string", "format": "email"},
            "seats": {"type": "integer", "minimum": 1, "maximum": 9, "default": 1},
            "tier": {"type": "integer", "enum": [1, 2, 3], "description": "Fare tier"},
            "cabin": {"type": "string", "enum": ["economy", "business"]},
            "ratio": {"type": "number", "exclusiveMinimum": 0},
            "note": {"anyOf": [{"type": "string", "maxLength": 200}, {"type": "null"}], "description": "Note"},
            "target": {"oneOf": [{"type": "string"}, {"type": "integer"}]},
            "tags": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5},
            "maybe": {"type": ["string", "null"]},
            "who": {"type": "object", "properties": {"name": {"type": "string", "minLength": 2}},
                    "required": ["name"]},
        },
        "required": ["code", "seats"],
    },
}


def _props():
    adapter = GeminiAdapter(api_key="", model_name="gemini-2.5-flash", service_metadata={})
    (decl,) = adapter.get_tool_declarations([TOOL])
    assert decl.parameters.required == ["code", "seats"]
    return decl.parameters.properties


def test_constraints_survive():
    p = _props()
    assert p["code"].pattern == "^[A-Z]{3}$"
    assert (p["seats"].minimum, p["seats"].maximum, p["seats"].default) == (1, 9, 1)
    assert (p["tags"].min_items, p["tags"].max_items) == (1, 5)
    assert p["who"].properties["name"].min_length == 2 and p["who"].required == ["name"]


def test_an_integer_enum_stays_an_integer():
    tier = _props()["tier"]
    assert str(tier.type).endswith("INTEGER")
    assert tier.enum is None
    assert "Allowed values: 1, 2, 3." in tier.description and tier.description.startswith("Fare tier")
    assert _props()["cabin"].enum == ["economy", "business"]


def test_formats_vertex_accepts_are_kept_others_described():
    p = _props()
    assert p["when"].format == "date-time"
    assert p["email"].format is None and "Format: email." in p["email"].description
    assert "Must be > 0." in p["ratio"].description


def test_unions_and_nulls():
    p = _props()
    assert str(p["note"].type).endswith("STRING") and p["note"].nullable and p["note"].max_length == 200
    assert p["note"].description == "Note"
    assert [str(v.type).split(".")[-1] for v in p["target"].any_of] == ["STRING", "INTEGER"]
    assert p["maybe"].nullable and str(p["maybe"].type).endswith("STRING")


def test_every_registered_tool_translates_without_a_fallback(caplog):
    import logging

    import src.ai.tools  # noqa: F401 — registers every tool
    from src.ai.tools.base import ToolRegistry

    adapter = GeminiAdapter(api_key="", model_name="gemini-2.5-flash", service_metadata={})
    with caplog.at_level(logging.WARNING, logger="src.ai.llm.gemini_adapter"):
        decls = adapter.get_tool_declarations([t.get_function_schema() for t in ToolRegistry._tools.values()])
    assert len(decls) == len(ToolRegistry._tools)
    assert "Skipping malformed property" not in caplog.text
