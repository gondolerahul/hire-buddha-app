"""Writes to a business's connected accounts wait for a person (SH-E4).

Google's Workspace developer policy (each agentic action confirmed by the
user), YouTube's developer policies (III.E.3.d and III.I.2: express consent
before each upload, comment or edit), X's rule for AI-written replies and the
money a Google Ads change spends all ask the same thing: a person sees exactly
what goes out, and agrees, before it goes. This is a platform rule, not an
option each agent's builder may forget.

A run's call to an outbound action (:func:`outbound`) is not carried out when
the agent makes it. It becomes a PENDING approval (``context_snapshot.kind`` =
``connector_action``) that holds the exact tool and arguments, the business's
admins are told, and the agent is answered that the action waits for a person.
The run goes on. Approving it in the inbox carries out that call — the
arguments approved, with the run's identity — and records the result on the
approval; rejecting it sends nothing. A call nobody approves never runs.

Conversational replies (Messenger, Instagram and WhatsApp messages) are not
held: they follow the messaging rules of META-E4 instead. A person calling a
tool directly, outside a run, is its own approval. Staff may switch the rule
off (``CONNECTOR_ACTION_APPROVAL``) or exempt tools for the platform's own use
(``CONNECTOR_ACTION_APPROVAL_EXEMPT``: ``email_send``, ``social_api``, or
``social_api:<platform>.<operation>``).
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Mapping, Optional

logger = logging.getLogger(__name__)

KIND = "connector_action"
TRIGGER = "CONNECTOR_ACTION"
# Reads hidden in a manage_* operation (``action``), and operations that are
# conversation rather than publication.
READ_ACTIONS = frozenset({"list", "get", "read", "search", "describe"})
CONVERSATION = frozenset({"send_message"})
# Google Drive's writes (GOOG-E4): Google's Workspace rules want a person to confirm an agent's actions.
DRIVE_WRITES = frozenset({"create_file", "update_file"})


def outbound(name: str, args: Any) -> Optional[str]:
    """What the call would do to an outside account (``"publish on linkedin: create post"``),
    or ``None`` when it reads, or converses, or is not a connector tool."""
    if name == "email_send":
        return "send an e-mail"
    if name == "google_drive" and isinstance(args, Mapping) and args.get("operation") in DRIVE_WRITES:
        return f"{str(args['operation']).replace('_', ' ')} in Google Drive"
    if name != "social_api" or not isinstance(args, Mapping):
        return None
    from src.ai.tools.social.social_api import writes

    platform, operation = str(args.get("platform") or ""), str(args.get("operation") or "")
    if not writes(operation) or operation in CONVERSATION:
        return None
    raw = args.get("payload")
    payload: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    if operation.startswith("manage_") and str(payload.get("action") or "").lower() in READ_ACTIONS:
        return None
    return f"{operation.replace('_', ' ')} on {platform}"


def _exempt(name: str, args: Any) -> bool:
    from src.common.config import settings

    names = {item.strip() for item in str(settings.CONNECTOR_ACTION_APPROVAL_EXEMPT or "").split(",") if item.strip()}
    if name in names:
        return True
    if name == "social_api" and isinstance(args, Mapping):
        return f"social_api:{args.get('platform')}.{args.get('operation')}" in names
    return False


def _digest(name: str, args: Any) -> str:
    return hashlib.sha256(json.dumps([name, args], sort_keys=True, default=str).encode()).hexdigest()


def _replayable(context: Mapping[str, Any]) -> Dict[str, Any]:
    """The call's identity to carry it out later: the context's plain values."""
    return {k: v for k, v in context.items() if isinstance(v, (str, int, float, bool)) or v is None}


def preview(name: str, args: Any) -> str:
    """What will go out, as the reviewer reads it."""
    shown = args.get("payload") if name == "social_api" and isinstance(args, Mapping) else args
    try:
        return json.dumps(shown, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(shown)


async def hold(name: str, args: Any, context: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """The answer for an outbound call that now waits for a person, or ``None``
    to run the call now. One approval per exact call and run: asking again for
    the same write finds it."""
    from src.common.config import settings

    ctx = context or {}
    label = outbound(name, args)
    if not label or not settings.CONNECTOR_ACTION_APPROVAL or _exempt(name, args):
        return None
    run_id, company_id = ctx.get("run_id"), ctx.get("company_id")
    if not run_id or not company_id:
        return None
    try:
        approval_id, entity_name, opened = await _open(name, args, label, ctx)
    except Exception:  # noqa: BLE001 - never let the write through because the inbox could not be written
        logger.exception("connector action %s not held for approval", name)
        return {"error": f"This {label} needs a person's approval, and the approval could not be opened. "
                         "Nothing was sent."}
    if opened:
        await _tell_admins(company_id, approval_id, label, entity_name)
    return {"status": "awaiting_approval", "approval_id": str(approval_id),
            "message": (f"Not done yet: a person on the team must approve this ({label}). It will be carried out "
                        "exactly as written once they do, and not at all if they reject it.")}


async def _open(name: str, args: Any, label: str, ctx: Mapping[str, Any]) -> tuple[uuid.UUID, Optional[str], bool]:
    """The approval for this exact call in this run (``opened``: made now)."""
    from sqlalchemy import select

    from src.ai.orm import HumanApproval
    from src.common.tenancy.session import tenant_session

    company_id, run_id = uuid.UUID(str(ctx["company_id"])), uuid.UUID(str(ctx["run_id"]))
    digest = _digest(name, args)
    entity_name = ctx.get("__entity_name__") or None
    async with tenant_session(company_id) as db:
        existing = (await db.execute(select(HumanApproval.id).where(
            HumanApproval.run_id == run_id, HumanApproval.company_id == company_id,
            HumanApproval.status == "PENDING",
            HumanApproval.context_snapshot["kind"].astext == KIND,
            HumanApproval.context_snapshot["digest"].astext == digest))).scalars().first()
        if existing is not None:
            return existing, entity_name, False
        what = f"{name}: {args.get('platform')}.{args.get('operation')}" if name == "social_api" else name
        approval = HumanApproval(
            run_id=run_id, company_id=company_id, checkpoint_trigger=f"{TRIGGER}: {label}"[:255], status="PENDING",
            requested_by=str(ctx.get("agent_id") or "") or None,
            context_snapshot={
                "kind": KIND, "phase": "BEFORE", "tool": name, "args": args, "label": label, "digest": digest,
                "tool_id": what, "entity_name": entity_name, "content": preview(name, args),
                "message": (f"{entity_name or 'An AI employee'} wants to {label}. Approve to carry it out exactly "
                            "as shown; reject to send nothing."),
                "context": _replayable(ctx)})
        db.add(approval)
        await db.commit()
        from src.automation.run_events import emit_approval

        await emit_approval(db, approval)  # approval.requested (W3-1)
        return approval.id, entity_name, True


async def _tell_admins(company_id: Any, approval_id: Any, label: str, entity_name: Optional[str]) -> None:
    from src.notifications.service import notify

    await notify(company_id, kind="connector_action_proposed", audience="admins", severity="info",
                 dedupe_key=f"connector_action:{approval_id}",
                 title=f"{entity_name or 'An AI employee'} wants to {label}"[:200],
                 body="Nothing goes out until a person approves it. Review it in Approvals.", link="/ai/approvals")


def action_of(approval: Any) -> bool:
    """Whether an inbox row holds a connector action."""
    snapshot = approval.context_snapshot if isinstance(getattr(approval, "context_snapshot", None), dict) else {}
    return snapshot.get("kind") == KIND and bool(snapshot.get("tool"))


async def decided(company_id: Any, approval_id: Any, *, approved: bool, user_id: Any) -> Dict[str, Any]:
    """Carry out (approved) or drop (rejected) the held call; the outcome is
    recorded on the approval and returned. A row already carried out is not
    carried out again."""
    from sqlalchemy.orm.attributes import flag_modified

    from src.ai.orm import HumanApproval
    from src.common.tenancy.session import tenant_session

    async with tenant_session(company_id) as db:
        approval = await db.get(HumanApproval, uuid.UUID(str(approval_id)))
        if approval is None or not action_of(approval):
            return {"done": False, "reason": "not a connector action"}
        snapshot = dict(approval.context_snapshot)
        if snapshot.get("outcome"):
            return dict(snapshot["outcome"])
        name, args = snapshot["tool"], snapshot.get("args") or {}
        context = {**(snapshot.get("context") or {}), "__approved_by__": str(user_id)}
    if approved:
        outcome = await _carry_out(name, args, context)
    else:
        outcome = {"done": False, "reason": "rejected: nothing was sent"}
    outcome["decided_at"] = datetime.utcnow().isoformat()
    async with tenant_session(company_id) as db:
        decided_row = await db.get(HumanApproval, uuid.UUID(str(approval_id)))
        if decided_row is not None:
            decided_row.context_snapshot = {**(decided_row.context_snapshot or {}), "outcome": outcome}
            flag_modified(decided_row, "context_snapshot")
            await db.commit()
    return outcome


async def _carry_out(name: str, args: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    import src.ai.tools  # noqa: F401 - registers the tools
    from src.ai.tools.base import Tool, ToolRegistry

    company = context.get("company_id")
    tool = ToolRegistry.get_tool(name, company_id=uuid.UUID(str(company)) if company else None)
    if not isinstance(tool, Tool):
        return {"done": False, "reason": f"the tool {name!r} is not available any more"}
    try:
        out = await tool.invoke(args, context)
    except Exception as failure:  # noqa: BLE001 - the approval records what happened
        logger.exception("approved connector action %s failed", name)
        return {"done": False, "reason": f"failed: {failure}"[:500]}
    output = out.output if isinstance(out.output, (str, int, float, bool, dict, list)) or out.output is None \
        else str(out.output)
    from src.ai.tool_executor import result_error

    problem = (None if out.success else (out.error or "the tool failed")) or result_error(output)
    if problem is None:
        await _bill(name, out, context)
    return {"done": problem is None, "reason": problem, "output": output}


async def _bill(name: str, out: Any, context: Mapping[str, Any]) -> None:
    """The carried-out call is billed to its run like any tool call of the run
    (its own price, and ``also_bill``: X's per-post price, X-E5). Late rows are
    settled by the unsettled-usage sweep."""
    from src.ai.governance.tool_cost_resolver import ToolCostResolver
    from src.ai.orm import ExecutionRun
    from src.common.tenancy.session import tenant_session

    metadata = getattr(out, "metadata", None) or {}
    charges = [(name, float(metadata.get("billable_units", 1)))]
    charges += [(str(k), float(v)) for k, v in (metadata.get("also_bill") or {}).items() if float(v) > 0]
    try:
        async with tenant_session(context["company_id"]) as db:
            run = await db.get(ExecutionRun, uuid.UUID(str(context["run_id"])))
            if run is None:
                return
            resolver = ToolCostResolver(db, run.company_id, run_id=run.id)
            for tool_id, units in charges:
                await resolver.charge(run=run, tool_id=tool_id, units=units)
            await db.commit()
    except Exception:  # noqa: BLE001 - the action is done; a missing charge is logged for staff
        logger.exception("approved connector action %s carried out but not billed", name)
