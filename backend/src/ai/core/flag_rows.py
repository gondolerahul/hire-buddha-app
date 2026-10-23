"""Feature-flag rows staff did not write (Phase 15 T0-1, tech design §10.1).

    python -m src.ai.core.flag_rows                      # report (nothing written)
    python -m src.ai.core.flag_rows --delete-undeclared  # remove rows for keys no code reads
    python -m src.ai.core.flag_rows --reset-customer     # also remove customers' company/entity rows

Until T0-1 any tenant or partner admin could write a flag row for its own
company, under any key. Now only ``app_admin`` writes, and each write is in
``admin_audit_log``. This lists the rows left from before:

* ``undeclared`` — a key ``flag_kind`` does not know: nothing reads it;
* ``customer`` — a company or entity row of a company other than the platform's,
  with no staff write of that key for that company in the audit log: it may
  have been set by the customer itself.

Each removal goes through ``FeatureFlags.delete`` (every process drops its
cached value) and leaves an audit row with the actor ``flag_rows``.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text


async def find_rows(db: Any) -> Dict[str, List[Dict[str, Any]]]:
    from src.ai.core.feature_flags import flag_kind
    from src.auth.platform import platform_company_id

    platform = await platform_company_id(db)
    rows = (await db.execute(text(
        "SELECT f.flag_key, f.company_id, f.entity_id, f.enabled, f.value_json, "
        "       EXISTS (SELECT 1 FROM admin_audit_log a WHERE a.object_type = 'feature_flag' "
        "               AND a.object_key = f.flag_key AND a.target_company_id = f.company_id "
        "               AND a.action = 'set') AS staff_set "
        "FROM feature_flags f ORDER BY f.flag_key, f.company_id NULLS FIRST")
    )).all()
    report: Dict[str, List[Dict[str, Any]]] = {"undeclared": [], "customer": []}
    for row in rows:
        item = {"flag_key": row.flag_key, "company_id": row.company_id, "entity_id": row.entity_id,
                "enabled": row.enabled, "value_json": row.value_json}
        if flag_kind(row.flag_key) is None:
            report["undeclared"].append(item)
        elif row.company_id is not None and row.company_id != platform and not row.staff_set:
            report["customer"].append(item)
    return report


async def remove(db: Any, items: List[Dict[str, Any]], reason: str) -> int:
    from src.ai.core.feature_flags import FeatureFlags
    from src.common.admin_audit import record_admin_change

    removed = 0
    for item in items:
        company_id: Optional[UUID] = item["company_id"]
        entity_id: Optional[UUID] = item["entity_id"]
        if await FeatureFlags(db).delete(item["flag_key"], company_id=company_id, entity_id=entity_id):
            record_admin_change(
                db, actor=None, action="delete", object_type="feature_flag", object_key=item["flag_key"],
                target_company_id=company_id,
                scope={"scope": "entity" if entity_id else ("company" if company_id else "global"),
                       "entity_id": str(entity_id) if entity_id else None, "by": "flag_rows"},
                old_value={"enabled": item["enabled"], "value_json": item["value_json"]}, reason=reason,
            )
            removed += 1
    await db.commit()
    return removed


async def _cli(delete_undeclared: bool, reset_customer: bool) -> int:
    from src.common import database
    from src.common.tenancy.session import control_session

    try:
        async with control_session() as db:
            report = await find_rows(db)
            for kind, items in report.items():
                for item in items:
                    print(f"{kind:10} {item['flag_key']:45} company={item['company_id']} "
                          f"entity={item['entity_id']} enabled={item['enabled']} value={item['value_json']}")
            if delete_undeclared or reset_customer:
                doomed = report["undeclared"] + (report["customer"] if reset_customer else [])
                print(f"removed {await remove(db, doomed, 'Phase 15 T0-1: flags are staff-only')} row(s)")
    finally:
        await database.engine.dispose()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.ai.core.flag_rows")
    parser.add_argument("--delete-undeclared", action="store_true", help="remove rows for keys no code reads")
    parser.add_argument("--reset-customer", action="store_true",
                        help="also remove customers' company/entity rows (they return to the global value)")
    args = parser.parse_args(argv)
    return asyncio.run(_cli(args.delete_undeclared, args.reset_customer))


if __name__ == "__main__":
    sys.exit(main())
