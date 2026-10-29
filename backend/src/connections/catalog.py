"""The connector catalog (Phase 14 WS5 5.1, 5.8; tech spec §10.2; E09-S11).

``catalog/*.yaml`` is the source of truth — one file per connector — and is
synced to the control table ``connector_catalog`` on deploy
(``python -m src.connections.catalog sync``, run by the migrations Job after
the trees) and when the API starts. Platform staff can switch a connector's
status (``status_override``) and record its provider review (``approval``)
without a deploy; a sync keeps both.

Statuses: ``available`` (Connect), ``preview`` (works, limited support),
``unavailable`` and ``planned`` (Coming soon). Only ``available`` and
``preview`` connectors can be connected.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from src.connections.models import AUTH_TYPES, CATALOG_STATUSES

logger = logging.getLogger(__name__)

CATALOG_DIR = Path(__file__).resolve().parent / "catalog"
CONNECTABLE = frozenset({"available", "preview"})


class FormField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    label: str
    kind: str = "text"                     # text, secret, email, url, number, select
    required: bool = False
    default: Optional[Any] = None
    options: List[Dict[str, str]] = Field(default_factory=list)   # select: [{value, label}]
    help: Optional[str] = None


class ConnectorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    provider: str
    display_name: str
    category: str
    auth_type: str
    icon: Optional[str] = None
    oauth_app_ref: Optional[str] = None
    status: str
    scopes: List[str] = Field(default_factory=list)
    capabilities: Dict[str, Any] = Field(default_factory=dict)
    approval: Dict[str, Any] = Field(default_factory=dict)
    version: int = 1

    @field_validator("auth_type")
    @classmethod
    def _auth(cls, value: str) -> str:
        if value not in AUTH_TYPES:
            raise ValueError(f"auth_type {value!r} is not one of {AUTH_TYPES}")
        return value

    @field_validator("status")
    @classmethod
    def _status(cls, value: str) -> str:
        if value not in CATALOG_STATUSES:
            raise ValueError(f"status {value!r} is not one of {CATALOG_STATUSES}")
        return value

    @property
    def form(self) -> List[FormField]:
        return [FormField(**f) for f in self.capabilities.get("form", [])]


def load_specs(directory: Path = CATALOG_DIR) -> Dict[str, ConnectorSpec]:
    """Every connector the YAML files declare, by id (each file's id must be its name)."""
    specs: Dict[str, ConnectorSpec] = {}
    for path in sorted(directory.glob("*.yaml")):
        spec = ConnectorSpec(**(yaml.safe_load(path.read_text(encoding="utf-8")) or {}))
        if spec.id != path.stem:
            raise ValueError(f"{path.name}: id {spec.id!r} must be the file's name")
        if spec.auth_type in ("oauth2", "github_app", "meta_embedded_signup") and not spec.oauth_app_ref:
            raise ValueError(f"{path.name}: an {spec.auth_type} connector needs oauth_app_ref")
        specs[spec.id] = spec
    return specs


_specs: Optional[Dict[str, ConnectorSpec]] = None


def specs() -> Dict[str, ConnectorSpec]:
    global _specs
    if _specs is None:
        _specs = load_specs()
    return _specs


def spec(connector_id: str) -> ConnectorSpec:
    found = specs().get(connector_id)
    if found is None:
        raise KeyError(f"no connector {connector_id!r}")
    return found


async def sync_catalog(db: Any) -> Dict[str, List[str]]:
    """Upsert every YAML connector into ``connector_catalog`` (staff overrides and
    approvals kept); a row the YAML no longer has becomes ``unavailable``."""
    from src.connections.models import ConnectorCatalogEntry

    rows = {row.id: row for row in (await db.execute(select(ConnectorCatalogEntry))).scalars().all()}
    added, updated = [], []
    now = datetime.utcnow()
    for connector_id, item in specs().items():
        row = rows.get(connector_id)
        values = dict(provider=item.provider, display_name=item.display_name, category=item.category,
                      auth_type=item.auth_type, scopes=item.scopes, capabilities=item.capabilities,
                      oauth_app_ref=item.oauth_app_ref, status=item.status, icon=item.icon,
                      version=item.version, synced_at=now)
        if row is None:
            db.add(ConnectorCatalogEntry(id=connector_id, approval=item.approval, **values))
            added.append(connector_id)
            continue
        for key, value in values.items():
            setattr(row, key, value)
        # The YAML's approval fills in what staff have not recorded.
        row.approval = {**item.approval, **(row.approval or {})}
        updated.append(connector_id)
    retired = [cid for cid in rows if cid not in specs()]
    for connector_id in retired:
        rows[connector_id].status = "unavailable"
        rows[connector_id].synced_at = now
    await db.commit()
    return {"added": added, "updated": updated, "retired": retired}


async def catalog_rows(db: Any) -> List[Any]:
    from src.connections.models import ConnectorCatalogEntry

    rows = (await db.execute(select(ConnectorCatalogEntry).order_by(ConnectorCatalogEntry.category,
                                                                    ConnectorCatalogEntry.display_name))).scalars().all()
    if not rows:  # a fresh database before its first sync
        await sync_catalog(db)
        rows = (await db.execute(select(ConnectorCatalogEntry))).scalars().all()
    return list(rows)


async def catalog_row(db: Any, connector_id: str) -> Any:
    from src.connections.models import ConnectorCatalogEntry

    row = await db.get(ConnectorCatalogEntry, connector_id)
    if row is None and connector_id in specs():
        await sync_catalog(db)
        row = await db.get(ConnectorCatalogEntry, connector_id)
    return row


def connector_view(row: Any) -> Dict[str, Any]:
    from src.common.config import settings

    item = specs().get(row.id)
    capabilities = row.capabilities or {}
    return {
        "id": row.id, "provider": row.provider, "display_name": row.display_name, "category": row.category,
        "auth_type": row.auth_type, "icon": row.icon, "status": row.effective_status,
        "connectable": row.effective_status in CONNECTABLE, "scopes": list(row.scopes or []),
        "actions": list(capabilities.get("actions", [])),
        "events": list(capabilities.get("events", [])),
        "form": [f.model_dump() for f in item.form] if item else [],
        # What the person reads before the provider's window opens (SH-13), and the form's help.
        "disclosure": capabilities.get("disclosure"), "help": capabilities.get("help"),
        "privacy_url": settings.PRIVACY_POLICY_URL,
    }


def after_disconnect(row: Any) -> Optional[str]:
    """What the person can still do at the provider once disconnected (MAIL-E4, MS-E4)."""
    return (row.capabilities or {}).get("after_disconnect") if row is not None else None


async def _cli(command: str) -> int:
    from src.common import database
    from src.common.tenancy.session import control_session

    try:
        async with control_session() as db:
            if command == "sync":
                print(await sync_catalog(db))
            else:
                for row in await catalog_rows(db):
                    print(f"{row.id:22} {row.effective_status:12} {row.display_name}")
        return 0
    finally:
        await database.engine.dispose()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.connections.catalog")
    parser.add_argument("command", choices=("sync", "list"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(_cli(args.command))


if __name__ == "__main__":
    sys.exit(main())
