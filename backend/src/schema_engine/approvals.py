"""Schema changes in the approvals inbox (plan WS4 4.4, decision D20), and the
owner's policy for them (functional spec §4.4).

An agent's change that waits for a person opens a ``human_approvals`` row on
the run that proposed it (``checkpoint_trigger`` ``SCHEMA_CHANGE: …``,
``context_snapshot.kind`` ``schema_change``), and the business's owners and
admins are told. Answering it in the inbox applies or rejects the change;
deciding it anywhere else (the Data API, the change review screen) closes the
inbox row too. The run does not wait for it: it goes on, and the change shows
up in the business's next runs once applied.

``records_settings.agents_auto_approve_additive`` lets an agent's change that
only adds apply at once; off by default.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import update

logger = logging.getLogger(__name__)

TRIGGER = "SCHEMA_CHANGE"
KIND = "schema_change"


# ── The owner's policy ─────────────────────────────────────────────────────

async def settings_for(engine: Any, company_id: Any) -> Dict[str, Any]:
    from src.schema_engine.engine import session
    from src.schema_engine.models import RecordsSettings

    async with session(engine) as db:
        row = await db.get(RecordsSettings, company_id)
    from src.common.config import settings

    return {"agents_auto_approve_additive": bool(row and row.agents_auto_approve_additive),
            "scratch_retention_days": row.scratch_retention_days if row else None,
            "scratch_retention_default": settings.CODE_SCRATCH_RETENTION_DAYS,
            "public_api_access": bool(row and row.public_api_access),
            "updated_by": row.updated_by if row else None, "updated_at": row.updated_at if row else None}


_UNSET: Any = object()


async def save_settings(engine: Any, company_id: Any, *, agents_auto_approve_additive: Any = _UNSET,
                        scratch_retention_days: Any = _UNSET, public_api_access: Any = _UNSET,
                        updated_by: str) -> Dict[str, Any]:
    """Change what is given; ``scratch_retention_days`` None = the platform's default (1–30 otherwise)."""
    from src.schema_engine.engine import session
    from src.schema_engine.models import RecordsSettings

    if scratch_retention_days is not _UNSET and scratch_retention_days is not None and             not 1 <= int(scratch_retention_days) <= 30:
        raise ValueError("scratch code is kept 1 to 30 days")
    async with session(engine) as db:
        row = await db.get(RecordsSettings, company_id)
        if row is None:
            row = RecordsSettings(company_id=company_id)
            db.add(row)
        if agents_auto_approve_additive is not _UNSET:
            row.agents_auto_approve_additive = bool(agents_auto_approve_additive)
        if scratch_retention_days is not _UNSET:
            row.scratch_retention_days = int(scratch_retention_days) if scratch_retention_days is not None else None
        if public_api_access is not _UNSET:
            row.public_api_access = bool(public_api_access)
        row.updated_by, row.updated_at = updated_by, datetime.utcnow()
        await db.commit()
    return await settings_for(engine, company_id)


# ── The inbox ──────────────────────────────────────────────────────────────

def _summary(view: Dict[str, Any]) -> str:
    parts = []
    for op in view.get("operations") or []:
        name = op.get("object") or ""
        if op.get("field"):
            name = f"{name}.{op['field']}"
        parts.append(f"{str(op.get('op', '')).replace('_', ' ')} {name}".strip())
    return "; ".join(parts) or "a schema change"


async def open_for(company_id: Any, view: Dict[str, Any], *, entity_name: Optional[str] = None) -> Optional[UUID]:
    """A PENDING inbox row for an agent's change waiting for a person (``None``
    when it came from no run of this business). Never raises."""
    from src.ai.orm import ExecutionRun, HierarchicalEntity, HumanApproval
    from src.common.tenancy.session import tenant_session

    run_id = view.get("run_id")
    if not run_id:
        return None
    try:
        async with tenant_session(company_id) as db:
            run = await db.get(ExecutionRun, UUID(str(run_id)))
            if run is None or run.company_id != company_id:
                return None
            if entity_name is None:
                entity = await db.get(HierarchicalEntity, run.entity_id)
                entity_name = entity.name if entity is not None else None
            summary = _summary(view)
            approval = HumanApproval(
                run_id=run.id, company_id=company_id, checkpoint_trigger=f"{TRIGGER}: {summary}"[:255],
                status="PENDING", requested_by=view.get("actor_id"),
                context_snapshot={"kind": KIND, "change_id": view["id"], "entity_name": entity_name,
                                  "message": f"{entity_name or 'An agent'} proposes a change to the business's "
                                             f"data: {summary}." + (f" Why: {view['reason']}" if view.get("reason")
                                                                     else ""),
                                  "reason": view.get("reason"), "operations": view.get("operations"),
                                  "impact": view.get("impact"), "result_version": view.get("result_version")})
            db.add(approval)
            await db.commit()
            approval_id = approval.id
            from src.automation.run_events import emit_approval

            await emit_approval(db, approval)  # approval.requested (W3-1)
    except Exception:  # noqa: BLE001 - the change waits either way; the Data API can decide it
        logger.exception("schema change %s: no inbox row", view.get("id"))
        return None
    await _tell_owners(company_id, view, summary, entity_name)
    return approval_id


async def _tell_owners(company_id: Any, view: Dict[str, Any], summary: str, entity_name: Optional[str]) -> None:
    from src.notifications.service import notify

    await notify(company_id, kind="records.schema_change_proposed", audience="admins", severity="info",
                 dedupe_key=f"records.schema_change:{view['id']}",
                 title=f"{entity_name or 'An agent'} proposes a data change: {summary}"[:200],
                 body=(view.get("reason") or "") + " Review it in Approvals.", link="/ai/approvals")


async def close_for(company_id: Any, change_id: Any, *, approved: bool, decided_by: Optional[str]) -> None:
    """The change was decided outside the inbox: its inbox row is answered too. Never raises."""
    from src.ai.orm import HumanApproval
    from src.common.tenancy.session import tenant_session

    user_id = None
    if decided_by and decided_by.startswith("user:"):
        try:
            user_id = UUID(decided_by[5:])
        except ValueError:
            user_id = None
    try:
        async with tenant_session(company_id) as db:
            await db.execute(update(HumanApproval).where(
                HumanApproval.company_id == company_id, HumanApproval.status == "PENDING",
                HumanApproval.context_snapshot["kind"].astext == KIND,
                HumanApproval.context_snapshot["change_id"].astext == str(change_id),
            ).values(status="APPROVED" if approved else "REJECTED", responded_by=user_id,
                     responded_at=datetime.utcnow(), reviewer_notes="decided on the change itself"))
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("schema change %s: inbox row not closed", change_id)


def change_of(approval: Any) -> Optional[str]:
    """The schema change an inbox row is for, if it is one."""
    snapshot = approval.context_snapshot if isinstance(approval.context_snapshot, dict) else {}
    return str(snapshot["change_id"]) if snapshot.get("kind") == KIND and snapshot.get("change_id") else None



async def decided_in_inbox(company_id: Any, change_id: str, *, approved: bool, user_id: Any) -> Dict[str, Any]:
    """Apply or reject the change an inbox answer was for; its view (with the error if it failed)."""
    from src.schema_engine import engine as schema

    engine, _ = await schema.business_engine(company_id)
    try:
        return await schema.decide(engine, company_id, change_id, approve=approved, decided_by=f"user:{user_id}")
    except schema.ApplyError as error:
        view = await schema.change_view(engine, company_id, change_id)
        return {**view, "error": view.get("error") or str(error)}
