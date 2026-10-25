"""Phase 15 T3-8: ``billing_events`` is retired — read-only for one release, then dropped.

Settlement adds what it bills to ``billing_lines`` (T3-4) and every report
reads those; the old monthly table is neither written nor read. A module that
names ``BillingEvent`` (or the old writer) again fails this test: it would
either double-record a charge or report from a table that stops growing. Only
the model's own definition may name it, until the drop migration (plan §4
step 10) removes it too.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
MODEL = SRC / "billing" / "billing_models.py"
RETIRED = {"BillingEvent", "record_billing_event", "BILLING_EVENT_UNIQUE_KEY"}


def _names(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        name = getattr(node, "id", None) or getattr(node, "attr", None) or getattr(node, "name", None)
        if name in RETIRED:
            found.add(name)
        if isinstance(node, ast.alias) and node.name in RETIRED:
            found.add(node.name)
    return found


def test_nothing_outside_the_model_names_billing_events():
    offenders = {str(path.relative_to(SRC)): sorted(names)
                 for path in SRC.rglob("*.py") if path != MODEL and (names := _names(path))}
    assert offenders == {}


SQL = re.compile(r"\b(from|into|update|join|table)\s+\"?billing_events\b", re.IGNORECASE)


def test_no_sql_text_reads_or_writes_the_table():
    offenders = [str(path.relative_to(SRC)) for path in SRC.rglob("*.py")
                 if path != MODEL and SQL.search(path.read_text(encoding="utf-8"))]
    assert offenders == []
