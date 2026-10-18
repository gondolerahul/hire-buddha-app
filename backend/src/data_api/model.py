"""SQLAlchemy Core tables for a blueprint (tech spec §9.1): built when a
version is first used and kept per business and version, so a new version
(``schema.version.activated``) is picked up without a restart and requests in
flight finish on the model they started with."""
from __future__ import annotations

from typing import Any, Dict, Tuple

from sqlalchemy import (Boolean, Column, Date, DateTime, Integer, MetaData, Numeric, String, Table, Text,
                        BigInteger)
from sqlalchemy.dialects.postgresql import UUID

from src.schema_engine import blueprint as bp

_models: Dict[Tuple[str, int], "Model"] = {}


def _type(spec: Dict[str, Any]) -> Any:
    kind = spec["type"]
    if kind == "text":
        return String(spec.get("max_length", 255))
    if kind in ("long_text", "enum", "email", "phone", "url"):
        return Text()
    if kind == "integer":
        return BigInteger()
    if kind == "decimal":
        return Numeric(spec.get("precision", 18), spec.get("scale", 4))
    if kind == "money":
        return Numeric(18, 4)
    if kind == "boolean":
        return Boolean()
    if kind == "date":
        return Date()
    if kind == "datetime":
        return DateTime(timezone=True)
    return UUID(as_uuid=True)  # ref, file


class Model:
    """One blueprint version as tables: ``tables[object]``."""

    def __init__(self, blueprint: Dict[str, Any]) -> None:
        self.blueprint = blueprint
        self.version = int(blueprint.get("version") or 0)
        self.metadata = MetaData()
        self.tables: Dict[str, Table] = {}
        for name, obj in bp.objects(blueprint).items():
            columns = [
                Column("id", UUID(as_uuid=True), primary_key=True),
                Column("created_at", DateTime(timezone=True)), Column("updated_at", DateTime(timezone=True)),
                Column("created_by", Text()), Column("updated_by", Text()), Column("row_version", Integer()),
                Column("archived_at", DateTime(timezone=True)), Column("owner_user_id", UUID(as_uuid=True)),
            ]
            for field_name, spec in bp.fields(obj, include_archived=True).items():
                columns.append(Column(field_name, _type(spec)))
                if spec["type"] == "money":
                    columns.append(Column(f"{field_name}_currency", String(3)))
            self.tables[name] = Table(obj["storage"]["table"], self.metadata, *columns,
                                      schema=obj["storage"]["schema"])

    def object(self, name: str) -> Tuple[str, Dict[str, Any], Table]:
        """An object by its name or a former name: ``(name, definition, table)``."""
        real, obj = bp.resolve_object(self.blueprint, name)
        return real, obj, self.tables[real]


def model_for(company_id: Any, blueprint: Dict[str, Any]) -> Model:
    key = (str(company_id), int(blueprint.get("version") or 0))
    model = _models.get(key)
    if model is None:
        model = _models[key] = Model(blueprint)
        for old in [k for k in _models if k[0] == key[0] and k[1] < key[1] - 1]:
            _models.pop(old, None)  # keep the version in flight and the newest
    return model
