"""ai.core.flag_explain — every declared flag's value for a company, and why (GH-20).

The flags page showed a value with no way to tell which tier produced it:
"why is this off for this tenant?" meant querying ``feature_flags`` by hand at
three scopes and then reading the process environment. :func:`explain_flags`
resolves every flag in ``DEFAULTS`` and ``NUMERIC_DEFAULTS`` the way
``FeatureFlags`` does — entity row → company row → global row →
``AI_FLAG_<KEY>`` → code default — from one query, uncached, and says which
tier answered. ``tests/unit/test_flag_explain.py`` holds it to the resolver's
answers tier by tier.

An entity's own ``metadata_extensions.feature_flags`` (the highest tier, read
from the run's entity) is not shown: this explains a company, not a run.
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from src.ai.core.feature_flags import DEFAULTS, NUMERIC_DEFAULTS, _env_float, _env_lookup

__all__ = ["explain_flags", "explain_rows"]


def _number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def explain_rows(rows: list[dict[str, Any]], company_id: Optional[UUID] = None,
                 entity_id: Optional[UUID] = None) -> list[dict[str, Any]]:
    """Resolve every declared flag from these ``feature_flags`` rows (each a
    dict with ``flag_key``, ``company_id``, ``entity_id``, ``enabled``,
    ``value_json``) plus the environment and the defaults."""
    company = str(company_id) if company_id else None
    entity = str(entity_id) if entity_id else None
    tiers: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        row_company = str(row["company_id"]) if row.get("company_id") else None
        row_entity = str(row["entity_id"]) if row.get("entity_id") else None
        if entity and row_entity == entity:
            tiers[(row["flag_key"], "entity_row")] = row
        elif row_entity is None and company and row_company == company:
            tiers[(row["flag_key"], "company")] = row
        elif row_entity is None and row_company is None:
            tiers[(row["flag_key"], "global")] = row

    out: list[dict[str, Any]] = []
    for key in sorted(DEFAULTS):
        value, source = DEFAULTS[key], "default"
        for tier in ("entity_row", "company", "global"):
            hit = tiers.get((key, tier))
            if hit is not None:
                value, source = bool(hit.get("enabled")), tier
                break
        else:
            env_bool = _env_lookup(key)
            if env_bool is not None:
                value, source = env_bool, "env"
        out.append({"flag_key": key, "kind": "boolean", "value": bool(value), "source": source})

    for key in sorted(NUMERIC_DEFAULTS):
        number, source = float(NUMERIC_DEFAULTS[key]), "default"
        for tier in ("entity_row", "company", "global"):
            hit = tiers.get((key, tier))
            found = _number(hit.get("value_json")) if hit is not None else None
            if found is not None:
                number, source = found, tier
                break
        else:
            env_number = _env_float(key)
            if env_number is not None:
                number, source = env_number, "env"
        out.append({"flag_key": key, "kind": "numeric", "value": number, "source": source})
    return out


async def explain_flags(db: Any, company_id: Optional[UUID] = None,
                        entity_id: Optional[UUID] = None) -> list[dict[str, Any]]:
    """Every declared flag for this company (and entity): value and tier, from one query."""
    from sqlalchemy import text

    from src.ai.orm.feature_flags import FeatureFlag

    rows = (await db.execute(text(
        "SELECT flag_key, company_id, entity_id, enabled, value_json FROM feature_flags "
        "WHERE (company_id IS NULL AND entity_id IS NULL) "
        "   OR (CAST(:c AS uuid) IS NOT NULL AND company_id = CAST(:c AS uuid) AND entity_id IS NULL) "
        "   OR (CAST(:e AS uuid) IS NOT NULL AND entity_id = CAST(:e AS uuid))"
    ), {"c": str(company_id) if company_id else None,
        "e": str(entity_id) if entity_id else None},
        bind_arguments={"mapper": FeatureFlag})).mappings().all()  # control plane
    return explain_rows([dict(r) for r in rows], company_id, entity_id)
