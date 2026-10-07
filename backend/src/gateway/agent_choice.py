"""Which agent an inbound event or a live socket runs (GW-17).

Webhook events and the audio/video sockets used to take ``LIMIT 1`` over the
company's non-archived entities with no order — a different agent, possibly a
child step or a draft, from one delivery to the next. An agent is now chosen
one way only:

1. one named explicitly — a webhook endpoint's binding, an event's ``entity_id``,
   a socket handshake's ``agent_id`` — if it is an active, non-template agent of
   the company; a name that does not resolve is refused, never replaced;
2. otherwise the company's only active top-level agent;
3. otherwise nothing: several candidates is refused with the way to name one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional
from uuid import UUID

from sqlalchemy import select

__all__ = ["AgentChoice", "choose_agent"]

HOW_TO_NAME = ("bind the webhook endpoint to an agent (entity_id), send entity_id in the "
               "event, or agent_id in the socket handshake")


@dataclass(frozen=True)
class AgentChoice:
    entity: Any = None                   # the HierarchicalEntity, when one was chosen
    error: Optional[str] = None          # "unknown_agent" | "ambiguous_agent" | "no_agent"
    detail: str = ""


def _as_uuid(value: Any) -> Optional[UUID]:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


async def choose_agent(db: Any, company_id: UUID, named: Iterable[Any] = ()) -> AgentChoice:
    """The agent for ``company_id``: the first of ``named`` given, else the only one."""
    from src.ai.orm import HierarchicalEntity

    runnable = (
        HierarchicalEntity.company_id == company_id,
        HierarchicalEntity.status == "ACTIVE",
        HierarchicalEntity.is_template.isnot(True),
        HierarchicalEntity.deleted_at.is_(None),
    )
    for raw in named:
        if not raw:
            continue
        entity_id = _as_uuid(raw)
        entity = None
        if entity_id is not None:
            entity = (await db.execute(
                select(HierarchicalEntity).where(HierarchicalEntity.id == entity_id, *runnable)
            )).scalar_one_or_none()
        if entity is None:
            return AgentChoice(error="unknown_agent",
                               detail=f"Agent {raw} is not an active agent of this company")
        return AgentChoice(entity=entity)

    candidates = (await db.execute(
        select(HierarchicalEntity).where(*runnable, HierarchicalEntity.parent_id.is_(None))
        .order_by(HierarchicalEntity.created_at, HierarchicalEntity.id).limit(2)
    )).scalars().all()
    if len(candidates) == 1:
        return AgentChoice(entity=candidates[0])
    if not candidates:
        return AgentChoice(error="no_agent", detail="The company has no active agent")
    return AgentChoice(error="ambiguous_agent",
                       detail=f"The company has several active agents; {HOW_TO_NAME}")
