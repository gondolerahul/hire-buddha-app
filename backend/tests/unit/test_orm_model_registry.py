"""Every ORM module is in the shared model list, and SQL files split cleanly (DM-21).

``migrations/env.py`` kept its own import list and had lost
``voice.phone_pool_models``, so autogenerate could not see ``phone_numbers``.
Alembic and the schema census now both use ``src.common.orm_models``; this test
fails when a module that declares a table is missing from it.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from src.common.orm_models import MODEL_MODULES

BACKEND = Path(__file__).resolve().parents[2]


def _declaring_modules() -> set[str]:
    found = set()
    for root in ("src", "cortex_memory"):
        for path in (BACKEND / root).rglob("*.py"):
            if "tests" in path.parts:
                continue
            if re.search(r"^\s+__tablename__\s*=", path.read_text(encoding="utf-8"), re.M):
                found.add(".".join(path.relative_to(BACKEND).with_suffix("").parts))
    return found


def test_every_module_that_declares_a_table_is_registered():
    assert sorted(_declaring_modules() - set(MODEL_MODULES)) == []


def test_every_registered_module_declares_a_table():
    assert sorted(set(MODEL_MODULES) - _declaring_modules()) == []


def test_env_py_uses_the_registry():
    env = (BACKEND / "migrations" / "env.py").read_text(encoding="utf-8")
    assert "target_metadata = import_all_models()" in env


def _sql_script():
    spec = importlib.util.spec_from_file_location("_sql_script", BACKEND / "migrations" / "sql_script.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sql_file_splits_into_single_statements():
    sql = """-- header
BEGIN;
SET LOCAL lock_timeout = '5s';
CREATE TABLE t (
    id UUID NOT NULL, -- a comment after code stays
    PRIMARY KEY (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS u ON t (id) WHERE status IN ('a', 'b');
COMMIT;
"""
    statements = _sql_script().split_sql(sql)
    assert [s.split()[0] for s in statements] == ["SET", "CREATE", "CREATE"]
    assert all(";" not in s for s in statements)


@pytest.mark.parametrize("path", ["mobile_dialer_001.sql", "mobile_dialer_002_logs.sql"])
def test_the_mobile_dialer_files_split(path):
    statements = _sql_script().split_sql((BACKEND / "db-scripts" / path).read_text(encoding="utf-8"))
    assert statements and not any(s.upper() in {"BEGIN", "COMMIT"} for s in statements)


def test_dollar_quoted_sql_is_refused():
    with pytest.raises(ValueError):
        _sql_script().split_sql("DO $$ BEGIN PERFORM 1; END $$;")
