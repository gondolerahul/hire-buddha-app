"""Weekly database exports (decision D45; tech spec §14 "Backups and restore").

Every week, a full ``pg_dump`` (custom format) of the control database and,
with ``TENANCY_MODE=split``, of every tenant database whose status lets a
session open it, is written to storage by neutral key:

    platform/backups/<ISO week>/<database>.dump      the control (or the single) database
    t-<key>/backups/<ISO week>/<database>.dump       each tenant's own database
    <namespace>/backups/<ISO week>/manifest.json     sizes and SHA-256 of that week's files

Only the last ``BACKUP_KEEP_WEEKS`` weeks are kept per namespace. Flexible
Server's own point-in-time backups run beside this (7 days); these exports
are what a tenant export, a restore into a clean server or another cloud is
made from (P-05: plain ``pg_dump`` files, neutral keys).

    python -m scripts.backup_databases            # this week, as the CronJob runs it
    python -m scripts.backup_databases --dry-run  # list what would be exported

One database failing does not stop the others; the exit code is 1 if any failed.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from sqlalchemy.engine import URL, make_url

logger = logging.getLogger("backup_databases")

CONTROL_NAMESPACE = "platform"
_WEEK = re.compile(r"^\d{4}-W\d{2}$")


@dataclass(frozen=True)
class Target:
    database: str
    url: URL
    namespace: str  # storage namespace: "platform", or the tenant's "t-<key>"


def iso_week(now: Optional[datetime] = None) -> str:
    year, week, _ = (now or datetime.now(timezone.utc)).isocalendar()
    return f"{year}-W{week:02d}"


def export_key(target: Target, week: str) -> str:
    return f"{target.namespace}/backups/{week}/{target.database}.dump"


async def targets() -> List[Target]:
    """The control database, then every ready tenant database (split mode only)."""
    from src.common.config import settings
    from src.common.tenancy.session import is_split

    control = make_url(settings.CONTROL_DATABASE_URL)
    found = [Target(control.database or "control", control, CONTROL_NAMESPACE)]
    if is_split():
        from src.common.tenancy.directory import directory
        from src.common.tenancy.engines import tenant_url

        for company_id in await directory.ready_company_ids():
            location = await directory.get(company_id)
            found.append(Target(location.db_name, tenant_url(location), f"t-{location.key}"))
    return found


async def pg_dump(target: Target, path: Path) -> None:
    """``pg_dump --format=custom`` of the target into ``path``; the password
    (or Entra token) reaches it through the environment, never its arguments."""
    from src.common.config import settings
    from src.common.platform.dbauth import libpq_environment

    env = {**os.environ, **libpq_environment(target.url)}
    process = await asyncio.create_subprocess_exec(
        settings.PG_DUMP_PATH, "--format=custom", "--no-owner", "--no-privileges", "--file", str(path),
        env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"pg_dump of {target.database} failed ({process.returncode}): "
                           f"{stderr.decode(errors='replace').strip()[-500:]}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def prune(storage: Any, namespace: str, keep_weeks: int) -> List[str]:
    """Delete the namespace's exports older than its newest ``keep_weeks`` weeks."""
    keys = await storage.list(f"{namespace}/backups/")
    weeks = sorted({key.split("/")[2] for key in keys if len(key.split("/")) > 3 and _WEEK.match(key.split("/")[2])})
    old = set(weeks[:-keep_weeks]) if keep_weeks > 0 else set()
    removed = [key for key in keys if key.split("/")[2] in old]
    for key in removed:
        await storage.delete(key)
    return removed


async def backup(
    *, now: Optional[datetime] = None,
    dump: Callable[[Target, Path], Awaitable[None]] = pg_dump,
    storage: Any = None,
    keep_weeks: Optional[int] = None,
    found: Optional[List[Target]] = None,
) -> Dict[str, Any]:
    """Export every target for this week, write the manifests, prune; the report."""
    from src.common.config import settings
    from src.common.platform.storage import get_storage

    storage = storage or get_storage()
    keep = settings.BACKUP_KEEP_WEEKS if keep_weeks is None else keep_weeks
    week = iso_week(now)
    found = found if found is not None else await targets()
    report: Dict[str, Any] = {"week": week, "exported": [], "failed": [], "pruned": []}
    manifests: Dict[str, List[Dict[str, Any]]] = {}

    with tempfile.TemporaryDirectory(prefix="hb-backup-") as folder:
        for target in found:
            path = Path(folder) / f"{target.database}.dump"
            try:
                await dump(target, path)
                entry = {"database": target.database, "key": export_key(target, week),
                         "bytes": path.stat().st_size, "sha256": _sha256(path)}
                await storage.put_file(entry["key"], path, content_type="application/octet-stream")
            except Exception as error:  # one database failing does not stop the others
                logger.error("export of %s failed: %s", target.database, error)
                report["failed"].append({"database": target.database, "error": str(error)})
                continue
            finally:
                path.unlink(missing_ok=True)
            report["exported"].append(entry)
            manifests.setdefault(target.namespace, []).append(entry)

    taken_at = (now or datetime.now(timezone.utc)).isoformat()
    for namespace, entries in manifests.items():
        manifest = {"week": week, "taken_at": taken_at, "databases": entries}
        await storage.put(f"{namespace}/backups/{week}/manifest.json",
                          json.dumps(manifest, indent=2).encode(), content_type="application/json")
        report["pruned"] += await prune(storage, namespace, keep)
    return report


async def _main(args: argparse.Namespace) -> int:
    from src.common.platform.storage import get_storage

    found = await targets()
    if args.dry_run:
        week = iso_week()
        print(json.dumps([{"database": t.database, "key": export_key(t, week)} for t in found], indent=2))
        return 0
    storage = get_storage()
    try:
        report = await backup(found=found, storage=storage)
    finally:
        close = getattr(storage, "close", None)  # the Blob client's HTTP sessions
        if close is not None:
            await close()
    print(json.dumps(report, indent=2))
    return 1 if report["failed"] else 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)  # not every HTTP request and header
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="list the exports without taking them")
    sys.exit(asyncio.run(_main(parser.parse_args())))


if __name__ == "__main__":
    main()
