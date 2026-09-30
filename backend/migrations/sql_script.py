"""Run a ``db-scripts/*.sql`` file from inside an Alembic revision.

Some revisions keep their DDL in a ``.sql`` file so the same statements can be
applied with ``psql`` on databases whose ``alembic_version`` is not on this
repository's history. ``op.execute(whole_file)`` does not work here: ``env.py``
runs migrations on asyncpg, which prepares every statement, and a prepared
statement holds one command — ``cannot insert multiple commands into a prepared
statement``. So the file is split and each statement executed on its own.

The splitter is deliberately simple: it drops ``--`` comment lines and splits on
a ``;`` that ends a line. It refuses dollar-quoted bodies (``DO $$ … $$``,
functions), where a ``;`` inside the body would be split wrongly.
"""
from __future__ import annotations

from pathlib import Path

from alembic import op

# Alembic already runs the migration inside a transaction.
_TRANSACTION_CONTROL = {"BEGIN", "COMMIT"}


def split_sql(sql: str) -> list[str]:
    """Return the statements in ``sql``, without comments or BEGIN/COMMIT."""
    if "$$" in sql:
        raise ValueError("dollar-quoted SQL cannot be split safely; write the revision in Python")
    lines = [line for line in sql.splitlines() if not line.lstrip().startswith("--")]
    statements: list[str] = []
    current: list[str] = []
    for line in lines:
        current.append(line)
        if line.rstrip().endswith(";"):
            statement = "\n".join(current).strip().rstrip(";").strip()
            current = []
            if statement and statement.upper() not in _TRANSACTION_CONTROL:
                statements.append(statement)
    leftover = "\n".join(current).strip()
    if leftover:
        raise ValueError(f"SQL does not end with ';': {leftover[:80]!r}")
    return statements


def execute_sql_file(path: Path) -> None:
    """Execute every statement in ``path``, in order."""
    for statement in split_sql(path.read_text(encoding="utf-8")):
        op.execute(statement)
