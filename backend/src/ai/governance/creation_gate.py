"""The gate an entity an agent creates passes, inside the creation service (MI-02, MI-03, D28).

The anti-sprawl gates used to be advice: ``meta_entity_creator`` checked two of
them in CREATE mode only, and any other path — its own VERSION mode, a future
tool — skipped them all. ``AIService.create_entity(..., origin="agent")`` now
runs this gate, so no agent path can create without it. A person creating
through the API is not gated: the person is the decision these gates stand in
for.

In order:

1. **Burst** — at most ``BURST_LIMIT`` agent creations a minute per company
   (``RedisRateLimiter``); a runaway loop is slowed at once instead of using the
   whole daily allowance in seconds. Redis unreachable → refused.
2. **Daily** — ``AntiSprawlGuard.check_creation_allowed``.
3. **Adaptation chain** — for a new version of an existing entity, refused once
   it has been adapted ``DEFAULT_ADAPTATION_THRESHOLD`` times.
4. **Semantic duplicate** — for a new entity; a check that cannot run refuses (MI-01).
"""
from __future__ import annotations

from typing import Any, Mapping, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["BURST_LIMIT", "BURST_WINDOW_SECONDS", "CreationRefused", "require_agent_creation"]

BURST_LIMIT = 3
BURST_WINDOW_SECONDS = 60


class CreationRefused(Exception):
    """An agent's creation is refused by ``gate``. Maps to a tool error (or 429/409)."""

    def __init__(self, gate: str, message: str, **details: Any):
        self.gate = gate
        self.details = details
        super().__init__(message)


def _limiter() -> Any:
    from src.ai.governance.rate_limiter import RedisRateLimiter
    from src.common.redis_client import shared_redis
    return RedisRateLimiter(shared_redis())


async def require_agent_creation(
    db: AsyncSession,
    company_id: UUID,
    payload: Mapping[str, Any],
    *,
    user_id: Optional[UUID] = None,
    source_entity_id: Optional[UUID] = None,
) -> None:
    """Raise :class:`CreationRefused` unless every gate lets the creation through."""
    from src.ai.meta.anti_sprawl import AntiSprawlGuard
    from src.ai.planning.plan_invariants import declared_tool_ids

    if not await _limiter().check_and_consume(
        key=f"entity_creation:agent:{company_id}", limit=BURST_LIMIT,
        window_seconds=BURST_WINDOW_SECONDS, fail_open=False,
    ):
        raise CreationRefused("burst_limit", (
            f"An agent may create at most {BURST_LIMIT} entities a minute for this company "
            "(or the limit could not be checked). Wait, or reuse an existing entity."))

    guard = AntiSprawlGuard(db, company_id)
    daily = await guard.check_creation_allowed(user_id)
    if not daily["allowed"]:
        raise CreationRefused("daily_limit", str(daily["message"]))

    if source_entity_id is not None:
        chain = await guard.check_consolidation_needed(source_entity_id)
        if chain["needs_consolidation"]:
            raise CreationRefused("adaptation_chain", (
                f"The source entity has been adapted {chain['adaptation_count']} times "
                f"(limit {chain['threshold']}); use one of its versions instead."),
                versions=chain["versions"])
        return

    dup = await guard.check_semantic_duplicate(
        description=str(payload.get("description") or payload.get("goal") or ""),
        required_tools=sorted(declared_tool_ids(payload.get("capabilities") or {})),
        preferred_type=str(payload.get("type") or "") or None,
    )
    if dup.get("is_duplicate"):
        raise CreationRefused(
            "semantic_duplicate_unavailable" if dup.get("unavailable") else "semantic_duplicate",
            str(dup["message"]),
            existing_entity_id=dup.get("existing_entity_id"),
            similarity_score=dup.get("similarity_score"),
        )
