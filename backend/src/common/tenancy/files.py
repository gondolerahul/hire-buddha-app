"""The file mover (Phase 14 WS7 7.4, tech spec §15.1).

    python -m src.common.tenancy.files COMPANY_ID [--apply] [--delete-old]

Moves a business's stored files into its tenant namespace ``t-<tenant key>``
and rewrites the rows that name them:

* ``c-<company hex>/<area>/<date>/<name>`` (files since storage keys) →
  ``t-<key>/<area>/<date>/<name>``;
* ``<origin>/<company id>/<date>/<name>`` (files from before them, on local
  disk) → ``t-<key>/<origin>/<date>/<name>``.

Each object is copied through the storage adapter (streamed through a local
file, never whole in memory), its SHA-256 compared on both sides, and only
then is the artifact row moved (``storage_key``, and ``file_path`` where it
named the old key or file). The old objects stay until ``--delete-old``, after
the cutover has been verified. Run it once the business's rows are in their
final database (after ``split``): the artifact rows are read and rewritten in the
business's own database, whatever ``TENANCY_MODE`` is. On Azure, a large business is better copied first with
``azcopy`` between containers and then verified by this tool's dry run.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select

logger = logging.getLogger(__name__)


def new_key_for(old_key: str, company_id: Any, tenant_key: str) -> Optional[str]:
    """Where an old key goes in the tenant namespace; ``None`` when it is not the company's old key."""
    from src.ai.artifact_service import ORIGIN_SYSTEM, ORIGIN_USER
    from src.common.platform.storage import legacy_namespace

    namespace, _, rest = (old_key or "").partition("/")
    if not rest:
        return None
    if namespace == legacy_namespace(company_id):
        return f"t-{tenant_key}/{rest}"
    if namespace in (ORIGIN_SYSTEM, ORIGIN_USER) and rest.startswith(f"{company_id}/"):
        return f"t-{tenant_key}/{namespace}/{rest[len(str(company_id)) + 1:]}"
    return None


async def _sha256(storage: Any, key: str) -> str:
    digest = hashlib.sha256()
    async for chunk in storage.open_stream(key):
        digest.update(chunk)
    return digest.hexdigest()


async def _copy(storage: Any, old: str, new: str, content_type: Optional[str]) -> None:
    from src.common.platform.storage import materialized

    async with materialized(old) as path:
        await storage.put_file(new, path, content_type=content_type)


async def move_files(company_id: Any, *, apply: bool, delete_old: bool = False) -> Dict[str, Any]:
    from src.ai.artifact_models import Artifact
    from src.common.platform.storage import StorageObjectNotFound, get_storage
    from src.common.tenancy.directory import directory

    company_id = uuid.UUID(str(company_id))
    location = await directory.find(company_id)
    if location is None:
        raise SystemExit(f"company {company_id} has no tenant yet: provision (or split) it first")
    storage = get_storage()
    report: Dict[str, Any] = {"company_id": str(company_id), "tenant_key": location.key, "moved": 0,
                              "already": 0, "missing": [], "mismatched": [], "bytes": 0, "deleted": 0,
                              "would_move": 0}
    # The rows in the business's own database whatever the mode: the cutover moves
    # files after its rows (split) and before switching to ``split``.
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.common.tenancy.engines import engines

    async with AsyncSession(engines.get(location), expire_on_commit=False) as db:
        rows = (await db.execute(select(Artifact).where(Artifact.company_id == company_id))).scalars().all()
        for row in rows:
            old = row.storage_key
            if old and old.startswith(f"t-{location.key}/"):
                report["already"] += 1
                continue
            new = new_key_for(old, company_id, location.key) if old else None
            if new is None:
                continue
            if not apply:
                report["would_move"] += 1
                continue
            try:
                if not await storage.exists(new):
                    await _copy(storage, old, new, row.mime_type)
                before, after = await _sha256(storage, old), await _sha256(storage, new)
            except StorageObjectNotFound:
                report["missing"].append({"artifact_id": str(row.id), "key": old})
                continue
            if before != after:
                report["mismatched"].append({"artifact_id": str(row.id), "key": old})
                continue
            old_path = row.file_path
            row.storage_key = new
            if old_path == old:
                row.file_path = new
            else:
                local = storage.local_path(new)
                if local is not None and old_path and storage.local_path(old) is not None:
                    row.file_path = str(local)
            await db.commit()
            report["moved"] += 1
            report["bytes"] += row.file_size or 0
            if delete_old:
                await storage.delete(old)
                report["deleted"] += 1
    return report


async def _cli(args: argparse.Namespace) -> int:
    from src.common import database
    from src.common.orm_models import import_all_models
    from src.common.tenancy.engines import engines

    # Run on its own, nothing else has imported the models an artifact's keys
    # name (campaigns …); the ORM refuses to flush without them.
    import_all_models()

    try:
        report = await move_files(args.company_id, apply=args.apply, delete_old=args.delete_old)
    finally:
        await engines.dispose_all()
        await database.engine.dispose()
    print(json.dumps(report, indent=2))
    return 1 if report["missing"] or report["mismatched"] else 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.common.tenancy.files")
    parser.add_argument("company_id")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--delete-old", action="store_true", help="remove each old object once its copy matches")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(_cli(args))


if __name__ == "__main__":
    sys.exit(main())
