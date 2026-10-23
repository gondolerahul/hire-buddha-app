"""What ``control_0007_registry_unit_codes`` would do to a database — changing nothing (Phase 15 T1-2).

    python -m src.billing.unit_codes_report

Lists every registry row with the code its old ``cost_unit`` maps to, and the
rows that map to nothing — those stop the migration. Run it against production
(read-only) before the release that carries the migration. It reads the
mapping from the revision itself, so the two cannot disagree. Delete it with
the ``cost_unit`` column (plan §4 step 10).
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Any, List, Optional

from sqlalchemy import text

REVISION = (Path(__file__).resolve().parents[2] / "migrations" / "control" / "versions"
            / "control_0007_registry_unit_codes.py")


def revision_module() -> Any:
    spec = importlib.util.spec_from_file_location("control_0007_registry_unit_codes", REVISION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def report(db: Any) -> dict:
    revision = revision_module()
    rows = (await db.execute(text(
        "SELECT id, service_sku, cost_unit FROM integration_registry ORDER BY service_sku"))).all()
    mapped, unmapped = revision.plan(rows)
    units = {str(r.id): (r.service_sku, r.cost_unit) for r in rows}
    return {
        "mapped": [{"id": i, "service_sku": units[i][0], "cost_unit": units[i][1], "code": c} for i, c in mapped],
        "unmapped": [{"id": i, "service_sku": s, "cost_unit": u} for i, s, u in unmapped],
    }


async def _cli() -> int:
    from src.common import database
    from src.common.tenancy.session import control_session

    try:
        async with control_session() as db:
            result = await report(db)
    finally:
        await database.engine.dispose()
    for item in result["mapped"]:
        print(f"mapped    {item['service_sku']:45} {item['cost_unit']!r:28} -> {item['code']}")
    for item in result["unmapped"]:
        print(f"UNMAPPED  {item['service_sku']:45} {item['cost_unit']!r:28} (stops the migration)")
    print(f"{len(result['mapped'])} mapped, {len(result['unmapped'])} unmapped")
    return 1 if result["unmapped"] else 0


def main(argv: Optional[List[str]] = None) -> int:
    return asyncio.run(_cli())


if __name__ == "__main__":
    sys.exit(main())
