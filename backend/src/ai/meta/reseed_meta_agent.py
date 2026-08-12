"""reseed_meta_agent.py — version-aware Meta-Agent re-seed (Phase 12 `06` §6.3).

``seed_meta_agent.py`` is force-or-skip: ``--force`` purges and recreates, which
**clobbers any per-company prompt bump** produced by prompt-evolution (`06` §6.1).
This module is the idempotent, version-aware alternative: when the bundled
template version is newer than what a company has, it updates the entity *in
place* — refreshing tools / plan / governance / logic — while **preserving the
company's evolved ``identity.system_prompt``**. If the company is already current,
it is a no-op.

The reconcile logic is pure (``reconcile_template``) so it is unit-testable; the
DB driver (``reseed``) just loads entities and applies it.

Usage: cd backend && .venv/bin/python -m src.ai.meta.reseed_meta_agent [--company <id>]
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

logger = logging.getLogger(__name__)

__all__ = ["reconcile_template", "version_tuple", "reseed"]


def version_tuple(v: str) -> tuple[int, ...]:
    """Parse a dotted semver-ish string into a comparable tuple ('3.1.0' → (3,1,0))."""
    parts: list[int] = []
    for chunk in str(v or "0").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def _evolved_prompt(existing: dict[str, Any]) -> Optional[str]:
    """The company's current Meta-Agent system prompt, if present."""
    identity = existing.get("identity")
    if isinstance(identity, dict):
        sp = identity.get("system_prompt")
        if isinstance(sp, str) and sp.strip():
            return sp
    return None


def reconcile_template(
    existing: dict[str, Any],
    new_template: dict[str, Any],
    *,
    preserve_prompt: bool = True,
) -> Optional[dict[str, Any]]:
    """Return an updated payload, or None if the existing entity is already current.

    Refreshes everything from ``new_template`` but keeps the company's evolved
    ``identity.system_prompt`` (so a prompt bump from `06` §6.1 is never lost).
    """
    cur_meta = existing.get("metadata_extensions") or {}
    new_meta = new_template.get("metadata_extensions") or {}
    cur_ver = version_tuple(str(cur_meta.get("meta_agent_version", existing.get("version", "0"))))
    new_ver = version_tuple(str(new_meta.get("meta_agent_version", new_template.get("version", "0"))))
    if cur_ver >= new_ver:
        return None  # already current — idempotent no-op

    merged = dict(new_template)
    if preserve_prompt:
        evolved = _evolved_prompt(existing)
        if evolved is not None:
            identity = dict(merged.get("identity") or {})
            template_prompt = identity.get("system_prompt")
            if evolved != template_prompt:
                identity["system_prompt"] = evolved
                merged["identity"] = identity
                meta = dict(merged.get("metadata_extensions") or {})
                meta["prompt_preserved_on_reseed"] = True
                merged["metadata_extensions"] = meta
    return merged


async def reseed(target_company_id: Optional[str] = None) -> dict[str, int]:
    from sqlalchemy import String, or_, select
    from src.ai.meta.meta_agent_template import generate_meta_agent_template
    from src.ai.models import HierarchicalEntity
    from src.common.database import AsyncSessionLocal

    template = generate_meta_agent_template()
    updated = skipped = 0
    async with AsyncSessionLocal() as db:
        q = select(HierarchicalEntity).where(
            or_(
                HierarchicalEntity.name == "MetaAgent",
                HierarchicalEntity.tags.cast(String).contains("meta_agent"),
            )
        )
        if target_company_id:
            q = q.where(HierarchicalEntity.company_id == target_company_id)
        entities = (await db.execute(q)).scalars().all()

        for ent in entities:
            existing = {
                "version": getattr(ent, "version", "0"),
                "identity": getattr(ent, "identity", None),
                "metadata_extensions": getattr(ent, "metadata_extensions", None),
            }
            merged = reconcile_template(existing, template)
            if merged is None:
                skipped += 1
                continue
            ent.identity = merged.get("identity")
            ent.logic_gate = merged.get("logic_gate")
            ent.planning = merged.get("planning")
            ent.governance = merged.get("governance")
            ent.version = str(merged.get("version") or "")
            ent.metadata_extensions = merged.get("metadata_extensions")
            updated += 1
            logger.info("reseed: updated MetaAgent %s for company %s", ent.id, ent.company_id)
        await db.commit()
    print(f"reseed_meta_agent: updated={updated} skipped(current)={skipped}")
    return {"updated": updated, "skipped": skipped}


if __name__ == "__main__":
    company = None
    for i, arg in enumerate(sys.argv):
        if arg == "--company" and i + 1 < len(sys.argv):
            company = sys.argv[i + 1]
    asyncio.run(reseed(target_company_id=company))
