"""JSON columns are JSONB unless their key order is content (DM-13).

``json`` and ``jsonb`` were split by table age, right through the entity table.
Every column is now ``jsonb`` except the three listed below, whose key order
means something; a new ``json`` column fails this test until it has a reason.
And because ``jsonb`` rejects the ``\\u0000`` escape, the engine drops NUL
characters from the JSON it writes.
"""
from __future__ import annotations

import json

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

from src.common.orm_models import import_all_models

ORDER_IS_CONTENT = {
    "execution_runs.context_state": "step order: the recency trim and a resumed run read it",
    "hierarchical_entities.io_contract": "property order is the Execute form's field order",
    "tool_registry_entries.function_schema": "an authored schema, shown back as written",
}


def test_only_order_sensitive_columns_stay_json():
    plain = sorted(
        f"{table.name}.{column.name}"
        for metadata in import_all_models()
        for table in metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, JSON) and not isinstance(column.type, JSONB)
    )
    assert plain == sorted(ORDER_IS_CONTENT)


def test_the_engine_drops_nul_characters_from_json():
    from src.common.database import engine, json_serializer

    assert engine.dialect._json_serializer is json_serializer
    value = {"out": "a\x00b", "list": ["\x00", {"k\x00": 1}], "n": 2, "none": None}
    assert json.loads(json_serializer(value)) == {"out": "ab", "list": ["", {"k": 1}], "n": 2, "none": None}
    # The common case is untouched, and a literal backslash-u sequence survives.
    assert json_serializer({"text": "a\\u0000b"}) == json.dumps({"text": "a\\u0000b"})
