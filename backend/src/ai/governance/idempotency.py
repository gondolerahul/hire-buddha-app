"""A write happens once per run (TL-39).

A retried, re-planned or resumed step used to re-post, re-send and re-create:
no write tool carried a key, and ``tool_interaction_logs.idempotency_key``
was never written. Now a call that writes gets a key from its run, its tool
and its arguments; when the run already has a successful call with that key,
the earlier result is returned and nothing is written again (or billed).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

__all__ = ["earlier_result", "is_write_call", "write_key"]


def is_write_call(tool: str, args: Any) -> bool:
    """Does this call change something outside the run?"""
    if tool == "social_api":
        from src.ai.tools.social.social_api import writes
        return isinstance(args, dict) and writes(str(args.get("operation") or ""))
    from src.ai.tools.resilience import is_write_tool
    return is_write_tool(tool)


def write_key(run_id: Any, tool: str, args: Any) -> Optional[str]:
    """The call's idempotency key, or None for a read or a call outside a run."""
    if not run_id or not is_write_call(tool, args):
        return None
    canonical = json.dumps({"run": str(run_id), "tool": tool, "args": args},
                           sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def earlier_result(run_id: Any, key: str) -> Optional[Any]:
    """The output of the run's earlier successful call with ``key``, if any."""
    from sqlalchemy import select

    from src.ai.orm.execution import ToolInteractionLog
    from src.common.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(ToolInteractionLog.output_result).where(
                ToolInteractionLog.run_id == run_id,
                ToolInteractionLog.idempotency_key == key,
                ToolInteractionLog.success.is_(True),
            ).order_by(ToolInteractionLog.created_at).limit(1)
        )).scalar_one_or_none()
