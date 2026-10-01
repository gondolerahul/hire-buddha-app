"""Timestamps are stored with their zone, and no code reads the local clock (DM-12).

Every ``DateTime`` column was naive, UTC only by the convention of
``datetime.utcnow`` defaults — and three call sites had already used local
time (the dashboard's "today", the billing period). Columns are now
``timestamptz``; Python keeps naive UTC through a driver codec.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime

from src.common.orm_models import import_all_models

BACKEND = pathlib.Path(__file__).resolve().parents[2]
CORTEX_TABLES = {"cortex_trees", "cortex_nodes", "cortex_edges"}  # the package's own schema


def test_every_host_timestamp_column_has_a_zone():
    naive = sorted(
        f"{table.name}.{column.name}"
        for metadata in import_all_models()
        for table in metadata.tables.values()
        if table.name not in CORTEX_TABLES
        for column in table.columns
        if isinstance(column.type, DateTime) and not column.type.timezone
    )
    assert naive == []


def _local_clock_calls(path: pathlib.Path) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), str(path))):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        owner = node.func.value
        owner_name = owner.id if isinstance(owner, ast.Name) else getattr(owner, "attr", "")
        name, has_tz = node.func.attr, bool(node.args[1:]) or any(k.arg == "tz" for k in node.keywords)
        local = (
            (owner_name == "datetime" and name == "now" and not node.args and not has_tz)
            or (owner_name in ("datetime", "date") and name == "today")
            or (owner_name == "datetime" and name == "fromtimestamp" and not has_tz)
        )
        if local:
            found.append(f"{path.relative_to(BACKEND)}:{node.lineno} {owner_name}.{name}()")
    return found


def test_no_code_reads_the_local_clock():
    sources = [p for root in ("src", "cortex_memory") for p in (BACKEND / root).rglob("*.py")
               if "tests" not in p.parts]
    assert [hit for p in sources for hit in _local_clock_calls(p)] == []


def test_the_driver_codec_round_trips_utc():
    from src.common.database import _decode_utc, _encode_utc

    naive = datetime(2026, 10, 1, 10, 0, 0, 123456)
    assert _decode_utc(_encode_utc(naive)) == naive
    ist = datetime(2026, 10, 1, 15, 30, 0, 123456, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert _decode_utc(_encode_utc(ist)) == naive
    assert _decode_utc(_encode_utc(datetime.max)) == datetime.max
    assert _decode_utc(_encode_utc(datetime.min)) == datetime.min
