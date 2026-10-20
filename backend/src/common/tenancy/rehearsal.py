"""A migration rehearsal and its report (Phase 14 WS7 7.5, plan WS9; tech spec §15).

    python -m src.common.tenancy.rehearsal (--company ID ... | --all) [--server NAME] [--files]

Runs, per business and in the cutover's order, what the switch-over runs —
on a restored copy of production, never on production itself:

1. **credentials** — the old social / e-mail rows and the business's own
   registry keys become connections (``connections.migrate``, applied);
2. **split** — the business is provisioned and its rows copied into its own
   database, with counts and checksums per table (``tenancy.split``);
3. **files** (``--files``) — its stored files copied into ``t-<key>`` and
   verified (``tenancy.files``).

The report — per business: rows and checksum mismatches, the tables that
differ, credentials converted / needing a reconnect / failed, files moved /
missing / mismatched, and each stage's time; overall: totals and the longest
business — is printed and kept as ``platform/rehearsals/<timestamp>/report.json``
and ``report.md``. "Done" for WS7 is a rehearsal with zero unexplained
mismatches within the agreed window (plan §5 WS7, WS9).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def rehearse_company(company_id: Any, *, server_name: Optional[str], files: bool) -> Dict[str, Any]:
    from src.common.tenancy import split as split_mod
    from src.connections.migrate import convert_company

    result: Dict[str, Any] = {"company_id": str(company_id), "timings": {}, "ok": True}
    started = time.monotonic()
    try:
        credentials = await convert_company(company_id, apply=True)
        result["credentials"] = {k: len(v) if isinstance(v, list) else v for k, v in credentials.items()}
        result["credential_failures"] = credentials["failed"]
    except Exception as error:  # noqa: BLE001 - the report says what failed
        result.update(ok=False, credentials_error=f"{type(error).__name__}: {error}"[:500])
    result["timings"]["credentials_s"] = round(time.monotonic() - started, 2)

    stage = time.monotonic()
    try:
        manifest = await split_mod.split_tenant(company_id, server_name=server_name, replace=True)
        result["tenant_key"] = manifest.get("tenant_key")
        result["rows"] = sum(t.get("target_count") or 0 for t in manifest["tables"])
        result["mismatches"] = manifest.get("mismatches", 0)
        result["mismatched_tables"] = [t["table"] for t in manifest["tables"] if not t.get("match", True)]
        result["manifest"] = manifest.get("stored_at")
        result["split_timings"] = manifest.get("timings", {})
        result["ok"] = result["ok"] and not result["mismatches"]
    except Exception as error:  # noqa: BLE001
        result.update(ok=False, split_error=f"{type(error).__name__}: {error}"[:500])
    result["timings"]["split_s"] = round(time.monotonic() - stage, 2)

    if files and result.get("tenant_key"):
        stage = time.monotonic()
        try:
            from src.common.tenancy.files import move_files

            moved = await move_files(company_id, apply=True)
            result["files"] = {k: (len(v) if isinstance(v, list) else v) for k, v in moved.items()
                               if k not in ("company_id", "tenant_key")}
            result["ok"] = result["ok"] and not moved["missing"] and not moved["mismatched"]
        except Exception as error:  # noqa: BLE001
            result.update(ok=False, files_error=f"{type(error).__name__}: {error}"[:500])
        result["timings"]["files_s"] = round(time.monotonic() - stage, 2)
    result["timings"]["total_s"] = round(time.monotonic() - started, 2)
    return result


def render_markdown(report: Dict[str, Any]) -> str:
    lines = [f"# Migration rehearsal {report['started_at']}", "",
             f"Businesses: {report['businesses']} · ok: {report['ok']} · failed: {report['failed']} · "
             f"rows copied: {report['rows']} · checksum mismatches: {report['mismatches']} · "
             f"total time: {report['total_s']} s · longest business: {report['longest_s']} s", "",
             "| Business | Tenant | Rows | Mismatches | Credentials (converted / reconnect / failed) | Files | Time (s) | Result |",
             "|---|---|---|---|---|---|---|---|"]
    for item in report["results"]:
        creds = item.get("credentials") or {}
        files = item.get("files") or {}
        problems = [item.get(k) for k in ("credentials_error", "split_error", "files_error") if item.get(k)]
        if item.get("mismatched_tables"):
            problems.append("tables differ: " + ", ".join(item["mismatched_tables"]))
        lines.append(
            f"| {item['company_id']} | {item.get('tenant_key') or '-'} | {item.get('rows', '-')} | "
            f"{item.get('mismatches', '-')} | {creds.get('converted', 0)} / {creds.get('needs_reconnect', 0)} / "
            f"{creds.get('failed', 0)} | {files.get('moved', '-')} moved, {files.get('missing', 0)} missing | "
            f"{item['timings'].get('total_s')} | {'ok' if item['ok'] else 'FAILED: ' + '; '.join(problems)} |")
    return "\n".join(lines) + "\n"


async def rehearse(company_ids: List[Any], *, server_name: Optional[str] = None, files: bool = False,
                   keep: bool = True) -> Dict[str, Any]:
    started_at = datetime.utcnow()
    started = time.monotonic()
    results = []
    for company_id in company_ids:
        logger.info("rehearsal: company %s", company_id)
        results.append(await rehearse_company(company_id, server_name=server_name, files=files))
    report = {
        "started_at": started_at.isoformat() + "Z", "businesses": len(results),
        "ok": sum(1 for r in results if r["ok"]), "failed": sum(1 for r in results if not r["ok"]),
        "rows": sum(r.get("rows") or 0 for r in results), "mismatches": sum(r.get("mismatches") or 0 for r in results),
        "total_s": round(time.monotonic() - started, 2),
        "longest_s": max((r["timings"].get("total_s", 0) for r in results), default=0), "results": results,
    }
    if keep:
        from src.common.platform.storage import get_storage

        prefix = f"platform/rehearsals/{started_at:%Y%m%dT%H%M%S}"
        try:
            await get_storage().put(f"{prefix}/report.json", json.dumps(report, indent=2, default=str).encode(),
                                    content_type="application/json")
            await get_storage().put(f"{prefix}/report.md", render_markdown(report).encode(),
                                    content_type="text/markdown")
            report["stored_at"] = prefix
        except Exception:  # noqa: BLE001
            logger.warning("rehearsal report not stored", exc_info=True)
    return report


async def _businesses() -> List[uuid.UUID]:
    from sqlalchemy import select

    from src.auth.models import Company
    from src.common.tenancy.session import control_session

    async with control_session() as db:
        return list((await db.execute(select(Company.id).where(Company.type.in_(("TENANT", "PARTNER")),
                                                               Company.status == "active")
                                      .order_by(Company.created_at))).scalars().all())


async def _cli(args: argparse.Namespace) -> int:
    from src.common import database
    from src.common.orm_models import import_all_models
    from src.common.tenancy.engines import engines

    # Run on its own, nothing else has imported the models an artifact's keys
    # name (campaigns …); the ORM refuses to flush without them.
    import_all_models()

    try:
        companies = [uuid.UUID(c) for c in args.company] if args.company else await _businesses()
        report = await rehearse(companies, server_name=args.server, files=args.files)
    finally:
        await engines.dispose_all()
        await database.engine.dispose()
    print(render_markdown(report))
    return 0 if report["failed"] == 0 else 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.common.tenancy.rehearsal")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--company", action="append", help="a business (repeatable)")
    group.add_argument("--all", action="store_true", help="every active business")
    parser.add_argument("--server", help="the pool server to place them on")
    parser.add_argument("--files", action="store_true", help="also move and verify the stored files")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(_cli(args))


if __name__ == "__main__":
    sys.exit(main())
