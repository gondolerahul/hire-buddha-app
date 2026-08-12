"""
cortex_memory.db — the package's own SQLAlchemy declarative base.

The package owns its ``Base`` (plan `04` decision K4) so it can ship its own
schema + Alembic migrations and be installed standalone. The host shares this
metadata during the in-host phase (its Alembic ``target_metadata`` is a list
including ``cortex_memory.db.metadata``) so host autogenerate never drops the
CORTEX tables.

External references (company/user/entity/run) are **opaque nullable UUIDs**
(decision K5): no ``ForeignKey`` to host tables, so the package's schema stands
alone. The host enforces referential integrity in its own schema.
"""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """The package's declarative base (SQLAlchemy 2.0, typed)."""


metadata = Base.metadata

__all__ = ["Base", "metadata"]
