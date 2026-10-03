"""Drift of the platform surface an agent is shown (MI-19).

``PlatformSchemaCompiler`` hashes what it compiles; this module decides what a
change means. The hash covers content only (it used to include
``compiled_at``, so every compile "drifted"), and the last version each
company's agents were shown is kept in Redis, so drift is seen across
processes and compiler instances — and acted on: the company's cached
manifest is dropped and ``meta.schema.drift`` is emitted.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

__all__ = ["note_schema_version", "schema_version"]

# Redis: the last schema version each company's agents were shown (MI-19).
_VERSION_KEY = "meta:schema_version:{company_id}"
_MANIFEST_KEY = "meta:manifest:{company_id}"


def schema_version(schema: Dict[str, Any]) -> str:
    """Hash of the schema's *content*. It used to include ``compiled_at``, so
    every compile looked like drift (MI-19)."""
    content = {k: v for k, v in schema.items() if k not in ("compiled_at", "schema_version")}
    return hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()[:16]


async def note_schema_version(company_id: Optional[UUID], version: str, redis: Any = None) -> bool:
    """Record the version a company's agents now see. When it differs from the
    last one recorded, the platform surface drifted: the company's cached
    manifest is dropped so the next prompt shows the new surface, and
    ``meta.schema.drift`` is emitted. Returns whether it drifted."""
    if company_id is None:
        return False
    try:
        if redis is None:
            from src.common.redis_client import shared_redis
            redis = shared_redis()
        key = _VERSION_KEY.format(company_id=company_id)
        previous = await redis.getset(key, version)
        previous = previous.decode() if isinstance(previous, bytes) else previous
        if previous is None or previous == version:
            return False
        await redis.delete(_MANIFEST_KEY.format(company_id=company_id))
    except Exception as exc:                                               # noqa: BLE001
        logger.debug("schema version not recorded: %s", exc)
        return False
    from src.ai.core.events import event
    logger.info("Platform schema drift for %s: %s -> %s", company_id, previous, version)
    event("meta.schema.drift", company_id=str(company_id), previous=previous, version=version)
    return True
