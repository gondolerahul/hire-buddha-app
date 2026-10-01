"""Runs stuck in WAITING_ON_CHILDREN (AK-03).

A parent that suspends on its children is resumed when the last child
finalises (``AgentLoop._maybe_resume_parent``). When that resume is lost — the
enqueue failed, Redis lost the job, the worker died — nothing else ever looks
at the parent: it is never finalised, billed or failed, and its credit hold is
never released.

``sweep_waiting_runs`` (a worker cron) closes that gap:

- every child is done and the parent has waited past the grace → the resume
  was lost; enqueue it again (``resume`` is idempotent);
- otherwise, the parent has waited past the timeout → cancel the children still running
  and finalise the parent ``FAILED`` through ``AgentLoop.resume`` with an
  ``expire_reason``, which settles billing and releases the hold like any end.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select, update

from src.ai.orm.execution import ExecutionRun
from src.ai.schemas.enums import TERMINAL_RUN_STATUSES, RunStatus

logger = logging.getLogger(__name__)

SUSPENDED_AT_KEY = "__suspended_at__"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _aware(value: Any) -> Optional[datetime]:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def cancel_open_children(db: Any, state: Any, reason: str) -> None:
    """Cancel the awaited children that are not terminal; fail their steps."""
    open_children = [
        c for c in state.awaiting_children
        if c.get("status") not in TERMINAL_RUN_STATUSES
    ]
    ids = [UUID(str(c["run_id"])) for c in open_children]
    if ids:
        await db.execute(
            update(ExecutionRun)
            .where(ExecutionRun.id.in_(ids),
                   ExecutionRun.status.notin_(TERMINAL_RUN_STATUSES))
            .values(status=RunStatus.CANCELLED.value,
                    completed_at=datetime.now(timezone.utc),
                    error_message=reason[:1000])
            .execution_options(synchronize_session=False)
        )
        await db.commit()
    for child in open_children:
        child["status"] = RunStatus.CANCELLED.value
        state.mark_step_failed(str(child.get("step_id") or ""),
                               f"child run CANCELLED: {reason}")


async def sweep_waiting_runs(
    db: Any,
    redis: Any,
    *,
    grace_s: int,
    timeout_s: int,
    now: Optional[datetime] = None,
) -> dict[str, int]:
    """Re-enqueue lost resumes and expire parents waiting past the timeout."""
    from src.ai.core.agent_loop import AgentLoop
    from src.ai.core.feature_flags import FeatureFlags
    from src.common.job_queue import enqueue_job

    now = now or datetime.now(timezone.utc)
    rows = (await db.execute(
        select(ExecutionRun.id, ExecutionRun.company_id, ExecutionRun.context_state,
               ExecutionRun.started_at, ExecutionRun.created_at)
        .where(ExecutionRun.status == RunStatus.WAITING_ON_CHILDREN.value)
    )).all()

    resumed = expired = 0
    for run_id, company_id, cs, started_at, created_at in rows:
        cs = cs or {}
        since = _aware(cs.get(SUSPENDED_AT_KEY)) or _aware(started_at) or _aware(created_at)
        waited = (now - since).total_seconds() if since else float(timeout_s)
        snapshot = cs.get("__agent_state_snapshot__") or {}
        child_ids = [UUID(str(c["run_id"])) for c in snapshot.get("awaiting_children", [])
                     if c.get("run_id")]
        statuses = [s for (s,) in (await db.execute(
            select(ExecutionRun.status).where(ExecutionRun.id.in_(child_ids))
        )).all()] if child_ids else []
        children_done = len(statuses) == len(child_ids) and all(
            s in TERMINAL_RUN_STATUSES for s in statuses
        )
        try:
            if children_done and waited >= grace_s:
                await enqueue_job("resume_parent_run", str(run_id))
                resumed += 1
            elif waited >= timeout_s:
                loop = AgentLoop(db, redis, company_id=company_id,
                                 feature_flags=FeatureFlags(db, redis=redis))
                await loop.resume(run_id, expire_reason=(
                    f"timed out after waiting {int(waited)}s on its child runs"
                ))
                expired += 1
        except Exception:                                                  # noqa: BLE001
            logger.exception("Stuck-run sweep failed for run %s", run_id)
            await db.rollback()
    if resumed or expired:
        logger.info("Stuck-run sweep: %d resume(s) re-enqueued, %d run(s) expired",
                    resumed, expired)
    return {"resumed": resumed, "expired": expired}
