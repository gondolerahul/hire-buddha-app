"""
reseed_meta_agent.py — Phase 11 Track 5-4 deferred re-seed helper.

Preserves the existing Meta-Agent entity_id but replaces its
prompts / capabilities / planning / governance with the latest
template returned by `generate_meta_agent_template()`. Use this when
the Meta-Agent template has been updated and you want every tenant to
pick up the new spec without losing the entity_id (which other
metadata may reference).

Usage:
    cd backend && .venv/bin/python -m scripts.migrations.reseed_meta_agent
                    [--company <id>] [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


PRESERVED_FIELDS: tuple[str, ...] = (
    "id", "company_id", "created_by", "created_at",
    "parent_id", "template_source_id", "is_template",
)

REPLACED_FIELDS: tuple[str, ...] = (
    "version", "type", "status", "name", "display_name", "description",
    "goal", "tags",
    "identity", "hierarchy", "logic_gate", "planning",
    "capabilities", "governance", "io_contract",
    "observability", "metadata_extensions",
)


async def reseed(
    target_company_id: Optional[str] = None, dry_run: bool = False,
) -> dict:
    from sqlalchemy import String, or_, select
    from src.ai.meta.meta_agent_template import generate_meta_agent_template
    from src.ai.orm.entity import HierarchicalEntity
    from src.ai.schemas import HierarchicalEntityCreate
    from src.common.database import AsyncSessionLocal

    summary: dict = {"updated": [], "skipped": [], "errors": []}
    template = generate_meta_agent_template()
    ein = HierarchicalEntityCreate.model_validate(template)
    fresh = ein.model_dump(mode="json")

    async with AsyncSessionLocal() as db:
        q = select(HierarchicalEntity).where(
            or_(
                HierarchicalEntity.name == "MetaAgent",
                HierarchicalEntity.tags.cast(String).contains("meta_agent"),
            )
        )
        if target_company_id:
            q = q.where(HierarchicalEntity.company_id == target_company_id)
        rows = (await db.execute(q)).scalars().all()

        if not rows:
            print("No MetaAgent entities found to reseed.")
            return summary

        for ent in rows:
            try:
                changed: list[str] = []
                for key in REPLACED_FIELDS:
                    if key not in fresh:
                        continue
                    new_val = fresh[key]
                    old_val = getattr(ent, key, None)
                    if json.dumps(new_val, default=str, sort_keys=True) != \
                       json.dumps(old_val, default=str, sort_keys=True):
                        if not dry_run:
                            setattr(ent, key, new_val)
                        changed.append(key)
                if changed and not dry_run:
                    ent.updated_at = datetime.utcnow()
                    meta = dict(ent.metadata_extensions or {})
                    history = list(meta.get("reseed_history") or [])
                    history.append({
                        "at": datetime.utcnow().isoformat(),
                        "fields": list(changed),
                        "version": fresh.get("version"),
                    })
                    meta["reseed_history"] = history[-10:]
                    ent.metadata_extensions = meta
                summary["updated"].append({
                    "id": str(ent.id),
                    "company_id": str(ent.company_id),
                    "changed_fields": changed,
                })
            except Exception as exc:                                          # noqa: BLE001
                summary["errors"].append({"id": str(ent.id), "error": str(exc)})

        if not dry_run:
            await db.commit()

    print(f"Re-seeded {len(summary['updated'])} Meta-Agent entit"
          f"{'y' if len(summary['updated']) == 1 else 'ies'} "
          f"({'DRY-RUN' if dry_run else 'committed'}).")
    for u in summary["updated"]:
        if u["changed_fields"]:
            print(f"  {u['id']} (co={u['company_id']}): "
                  f"{', '.join(u['changed_fields'])}")
    if summary["errors"]:
        print(f"Errors: {len(summary['errors'])}")
        for e in summary["errors"]:
            print(f"  {e['id']}: {e['error']}")
    return summary


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--company", help="Only reseed a specific company_id")
    p.add_argument("--dry-run", action="store_true",
                   help="Compute diffs but don't write")
    args = p.parse_args()
    asyncio.run(reseed(args.company, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
