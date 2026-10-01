"""No column is named "metadata", and an edge keeps the metadata it is given (DM-14).

SQLAlchemy reserves ``metadata`` on a declarative class, so a column of that
name is mapped under another attribute. ``Model(metadata=...)`` is still
accepted — the class has a ``metadata`` attribute — and the value is silently
dropped. ``SemanticGraphService.create_edge`` did that to every edge.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from src.common.orm_models import import_all_models


def test_no_mapped_table_has_a_column_named_metadata():
    import_all_models()
    from cortex_memory.db import Base as CortexBase
    from src.common.database import Base

    offenders = sorted(
        f"{table.name}.{column.name}"
        for metadata in (Base.metadata, CortexBase.metadata)
        for table in metadata.tables.values()
        for column in table.columns
        if column.name == "metadata"
    )
    assert offenders == []


@pytest.mark.asyncio
async def test_create_edge_stores_its_metadata():
    from cortex_memory.graph import SemanticGraphService

    added = []

    class FakeDb:
        async def execute(self, _stmt):
            return SimpleNamespace(scalar_one_or_none=lambda: None)

        def add(self, row):
            added.append(row)

    edge = await SemanticGraphService(FakeDb(), uuid.uuid4()).create_edge(
        uuid.uuid4(), uuid.uuid4(), "co_accessed", metadata={"run_id": "r1"})
    assert added == [edge]
    assert edge.edge_metadata == {"run_id": "r1"}
    assert "metadata" not in vars(edge)
