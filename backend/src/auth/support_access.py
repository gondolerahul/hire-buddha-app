"""Staff and a business's connected-account content (SH-E6;
docs/phase15/14_connector_approvals/10 §3.3).

Google forbids people reading a user's data without the user's agreement, and
the privacy policy says HireBuddha's staff do not read the content of a
business's connected accounts unless the business grants support access for a
limited time. So when platform staff work in a business (``X-Company-Id``) and
open a run that read through a connection (``connections.source_data`` marks),
its content is withheld — the run's input and result, prompts and answers,
tool arguments and results, step outputs, approval details — unless the
business has an active grant. What the run did stays visible: its steps,
tools, timings, costs, errors. A live stream is held back the same way from
the start, since a run may read through a connection at any point.

Every such view is recorded (``support_access_views``): under which grant, or
with the content withheld. The business's admins give a grant (1 hour to 7
days, with a reason), see the views, and end it early.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.auth.models import SupportAccessGrant, SupportAccessView, User
from src.common.database import get_db

logger = logging.getLogger(__name__)

MAX_HOURS = 168
WITHHELD = ("[Withheld: this run read {names}. HireBuddha's staff see that content only when the business "
            "grants support access (Settings → Support access).]")
# Frame and payload keys that carry content; the rest (type, status, kind, name,
# span ids, timings, cost, tokens) describe what happened and stay.
CONTENT_KEYS = frozenset({"payload", "output", "content", "delta", "text", "result", "result_data", "input",
                          "input_data", "prompt", "response", "message", "messages", "arguments", "args",
                          "context", "context_state", "snapshot", "summary"})


def staff_elsewhere(user: Any, company_id: Any) -> bool:
    """A HireBuddha staff member working in another business."""
    from src.billing.money_view import is_staff

    return bool(company_id) and is_staff(getattr(user, "role", None)) and \
        str(company_id) != str(getattr(user, "company_id", ""))


async def active_grant(company_id: Any, *, now: Optional[datetime] = None) -> Optional[SupportAccessGrant]:
    from src.common.tenancy.session import control_session

    at = now or datetime.utcnow()
    async with control_session() as db:
        return (await db.execute(select(SupportAccessGrant).where(
            SupportAccessGrant.company_id == uuid.UUID(str(company_id)), SupportAccessGrant.revoked_at.is_(None),
            SupportAccessGrant.expires_at > at).order_by(SupportAccessGrant.expires_at.desc()).limit(1))
        ).scalar_one_or_none()


async def _record(*, company_id: Any, user_id: Any, grant_id: Any, run_ids: Iterable[Any], path: str,
                  withheld: bool) -> None:
    """One row per run viewed, in a session of its own (never fails the request)."""
    from src.common.tenancy.session import control_session

    try:
        async with control_session() as db:
            for run_id in run_ids:
                db.add(SupportAccessView(company_id=uuid.UUID(str(company_id)), user_id=user_id, grant_id=grant_id,
                                         run_id=uuid.UUID(str(run_id)), path=path[:500], withheld=withheld))
            await db.commit()
    except Exception:  # noqa: BLE001 - the audit is best-effort; the request goes on
        logger.warning("support access view not recorded (%s in %s)", user_id, company_id, exc_info=True)


@dataclass
class Access:
    """What a viewer may see of some runs: the run ids whose content is withheld."""
    withheld: Dict[str, List[str]] = field(default_factory=dict)   # run id → connector ids

    def note(self, run_id: Any) -> str:
        from src.connections.source_data import _name

        names = ", ".join(_name(c) for c in self.withheld.get(str(run_id), [])) or "a connected account"
        return WITHHELD.format(names=names)

    def summary(self, run_id: Any) -> Optional[Dict[str, Any]]:
        if str(run_id) not in self.withheld:
            return None
        return {"connectors": self.withheld[str(run_id)], "message": self.note(run_id)}


async def run_access(db: Any, user: Any, company_id: Any, run_ids: Iterable[Any], *, path: str) -> Access:
    """Which of these runs' content ``user`` may not see; each staff view recorded."""
    from src.connections.source_data import marked_runs

    ids = [r for r in run_ids if r]
    if not staff_elsewhere(user, company_id) or not ids:
        return Access()
    marked = await marked_runs(db, ids)
    if not marked:
        return Access()
    grant = await active_grant(company_id)
    await _record(company_id=company_id, user_id=user.id, grant_id=grant.id if grant else None,
                  run_ids=list(marked), path=path, withheld=grant is None)
    return Access() if grant else Access(withheld=marked)


async def stream_withheld(user: Any, company_id: Any, run_id: Any, *, path: str) -> bool:
    """A live stream is held back for staff without a grant (recorded either way)."""
    if not staff_elsewhere(user, company_id):
        return False
    grant = await active_grant(company_id)
    await _record(company_id=company_id, user_id=user.id, grant_id=grant.id if grant else None,
                  run_ids=[run_id], path=path, withheld=grant is None)
    return grant is None


# ── Withholding ─────────────────────────────────────────────────────────────

def withhold_value(value: Any, note: str) -> Any:
    """``value`` with every content key's value replaced by ``note``."""
    if isinstance(value, dict):
        return {k: (note if k in CONTENT_KEYS and v not in (None, "", [], {}) else withhold_value(v, note))
                for k, v in value.items()}
    if isinstance(value, list):
        return [withhold_value(v, note) for v in value]
    return value


def withhold_run(run: Any, access: Access) -> Any:
    """An ``ExecutionRunResponse`` with what its marked runs read withheld (children too)."""
    for child in getattr(run, "child_runs", None) or []:
        withhold_run(child, access)
    summary = access.summary(run.id)
    if summary is None:
        return run
    note = summary["message"]
    run.input_data = {"withheld": note} if run.input_data else run.input_data
    run.result_data = {"withheld": note} if run.result_data else run.result_data
    run.context_state = None
    run.dynamic_plan = withhold_value(run.dynamic_plan, note) if run.dynamic_plan else run.dynamic_plan
    for log in run.llm_logs:
        log.input_prompt, log.output_response = note, note
    for log in run.tool_logs:
        log.input_parameters = {"withheld": note} if log.input_parameters else log.input_parameters
        log.output_result = note
    for approval in run.human_approvals:
        snapshot = approval.context_snapshot or {}
        approval.context_snapshot = {**{k: snapshot[k] for k in ("kind", "tool", "label") if k in snapshot},
                                     "withheld": note}
    run.content_withheld = summary
    return run


STREAM_NOTE = ("[Withheld: HireBuddha's staff see a run's content only when the business grants support access "
               "(Settings → Support access).]")


def withhold_frame(data: str) -> str:
    """One live frame (JSON text) with its content held back."""
    import json

    try:
        frame = json.loads(data)
    except ValueError:
        return json.dumps({"withheld": STREAM_NOTE})
    return json.dumps(withhold_value(frame, STREAM_NOTE), separators=(",", ":"))


def withhold_spans(spans: List[Dict[str, Any]], note: str) -> List[Dict[str, Any]]:
    for span in spans:
        if span.get("payload"):
            span["payload"] = {"withheld": note}
    return spans


# ── The business's grants ───────────────────────────────────────────────────

router = APIRouter(prefix="/api/v1/support-access", tags=["Support access"])


class GrantRequest(BaseModel):
    hours: int = Field(..., ge=1, le=MAX_HOURS, description="How long staff may see the content (1 hour to 7 days)")
    reason: str = Field(..., min_length=3, max_length=500, description="What the support is for")


def _admin(user: User) -> None:
    if str(user.role) != "tenant_admin":
        raise HTTPException(status_code=403, detail="Only the business's administrators give support access")


def _grant_view(grant: SupportAccessGrant, now: datetime) -> Dict[str, Any]:
    active = grant.revoked_at is None and grant.expires_at > now
    return {"id": str(grant.id), "reason": grant.reason, "granted_by": str(grant.granted_by) if grant.granted_by else None,
            "created_at": grant.created_at.isoformat() if grant.created_at else None,
            "expires_at": grant.expires_at.isoformat(), "active": active,
            "revoked_at": grant.revoked_at.isoformat() if grant.revoked_at else None}


@router.get("")
async def support_access(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The business's grants and the staff views of its connected-account content."""
    _admin(current_user)
    now = datetime.utcnow()
    grants = (await db.execute(select(SupportAccessGrant).where(
        SupportAccessGrant.company_id == current_user.company_id)
        .order_by(SupportAccessGrant.created_at.desc()).limit(20))).scalars().all()
    views = (await db.execute(select(SupportAccessView, User.email).join(
        User, User.id == SupportAccessView.user_id, isouter=True).where(
        SupportAccessView.company_id == current_user.company_id)
        .order_by(SupportAccessView.at.desc()).limit(100))).all()
    return {"grants": [_grant_view(g, now) for g in grants],
            "active": next((_grant_view(g, now) for g in grants if g.revoked_at is None and g.expires_at > now), None),
            "views": [{"at": v.at.isoformat(), "staff": email, "run_id": str(v.run_id) if v.run_id else None,
                       "withheld": v.withheld, "under_grant": str(v.grant_id) if v.grant_id else None}
                      for v, email in views]}


@router.post("", status_code=201)
async def give_support_access(body: GrantRequest, db: AsyncSession = Depends(get_db),
                              current_user: User = Depends(get_current_user)):
    """Let HireBuddha's staff see what came through the business's connections, for a while (one grant at a time)."""
    _admin(current_user)
    now = datetime.utcnow()
    await db.execute(update(SupportAccessGrant).where(
        SupportAccessGrant.company_id == current_user.company_id, SupportAccessGrant.revoked_at.is_(None),
        SupportAccessGrant.expires_at > now).values(revoked_at=now, revoked_by=current_user.id))
    grant = SupportAccessGrant(company_id=current_user.company_id, granted_by=current_user.id,
                               reason=body.reason.strip(), expires_at=now + timedelta(hours=body.hours))
    db.add(grant)
    await db.commit()
    await db.refresh(grant)
    return _grant_view(grant, now)


@router.delete("/{grant_id}")
async def end_support_access(grant_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                             current_user: User = Depends(get_current_user)):
    """End a grant now."""
    _admin(current_user)
    grant = (await db.execute(select(SupportAccessGrant).where(
        SupportAccessGrant.id == grant_id, SupportAccessGrant.company_id == current_user.company_id))
    ).scalar_one_or_none()
    if grant is None:
        raise HTTPException(status_code=404, detail="No such grant")
    now = datetime.utcnow()
    if grant.revoked_at is None:
        grant.revoked_at, grant.revoked_by = now, current_user.id
        await db.commit()
    return _grant_view(grant, now)
