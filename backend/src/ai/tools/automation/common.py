"""What the automation tools share: the call's business, run and agent, and
the two sessions they write through."""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional, Tuple
from uuid import UUID

from src.ai.tools.base import NO_CONTEXT_ERROR, ToolOutput, context_company_id

NOT_IN_A_RUN = "this tool runs only inside an agent's run"


@dataclass(frozen=True)
class Caller:
    company_id: UUID
    run_id: UUID
    entity_id: UUID


def caller_of(ctx: Dict[str, Any]) -> Tuple[Optional[Caller], Optional[ToolOutput]]:
    """The call's company, run and agent — from the platform-built context only."""
    company = context_company_id(ctx)
    if not company:
        return None, ToolOutput.failed(NO_CONTEXT_ERROR, code="no_context")
    run_id, entity_id = ctx.get("run_id"), ctx.get("entity_id") or ctx.get("agent_id")
    try:
        return Caller(UUID(str(company)), UUID(str(run_id)), UUID(str(entity_id))), None
    except (TypeError, ValueError):
        return None, ToolOutput.failed(NOT_IN_A_RUN, code="no_run")


@asynccontextmanager
async def sessions(company_id: UUID) -> AsyncIterator[Tuple[Any, Any]]:
    """The business's tenant session and a control session (triggers and their time index)."""
    from src.common.tenancy.session import control_session, tenant_session

    async with tenant_session(company_id) as db, control_session() as control_db:
        yield db, control_db


async def commit(db: Any, control_db: Any) -> None:
    await db.commit()
    await control_db.commit()
