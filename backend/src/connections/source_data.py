"""What came through a connection, and the rules its provider sets on it
(SH-E2, LI-E2, LI-E3, X-E4, YT-E5; docs/phase15/14_connector_approvals/10 §3.1).

A tool reads through a connection with a credential from
``connections.client.credentials_for``, which notes the connection here. When
the call succeeds and was a read, the tool executor marks the run: one
``connector_data_marks`` row per run, connection and tool. The connector's
catalog ``retention`` says what follows:

* ``hours``   — what the run read stays this long in its tool logs, trace
  spans, model prompts and answers, and CORTEX nodes; then ``redact_due``
  (hourly) puts a notice in its place. Disconnecting brings it forward to the
  next pass, whatever the connector.
* ``results`` — the run's own result and working state go too (LinkedIn, X,
  YouTube: their limits cover every copy).
* ``records: false`` — the run may not save records (the Data API refuses its
  token, LI-E3) and leaves no episode in long-term memory.
* ``exempt``  — operations whose data is the account's own (a Page's
  statistics): kept ``exempt_hours`` (none: while connected) and may be saved.

Marks also tell the run views that a run holds connected-account content, which
staff see only under a business's grant (SH-E6, ``auth.support_access``).
"""
from __future__ import annotations

import contextvars
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, Iterator, List, Optional, Sequence

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = logging.getLogger(__name__)

BATCH = 200
# A run still going keeps its result until it ends; its marks are looked at again this much later.
RETRY_UNFINISHED = timedelta(hours=1)

_used: contextvars.ContextVar[Optional[List[Dict[str, str]]]] = contextvars.ContextVar(
    "connector_reads", default=None)


# ── Which connections a call used ───────────────────────────────────────────

def note_use(connection_id: Any, connector_id: str) -> None:
    """``credentials_for`` handed out this connection's credential during a watched call."""
    used = _used.get()
    if used is not None and not any(u["connection_id"] == str(connection_id) for u in used):
        used.append({"connection_id": str(connection_id), "connector_id": connector_id})


@contextmanager
def watch() -> Iterator[List[Dict[str, str]]]:
    """The connections one tool call used (filled while the call runs)."""
    used: List[Dict[str, str]] = []
    token = _used.set(used)
    try:
        yield used
    finally:
        _used.reset(token)


def rule_for(connector_id: str) -> Any:
    """The connector's ``retention`` (a default one for a connector the catalog lacks)."""
    from src.connections.catalog import Retention, specs

    found = specs().get(connector_id)
    return found.retention if found is not None else Retention()


def _name(connector_id: str) -> str:
    from src.connections.catalog import specs

    found = specs().get(connector_id)
    return found.display_name if found is not None else connector_id


def _operation(tool_name: str, args: Any) -> Optional[str]:
    if isinstance(args, dict) and tool_name in ("social_api", "google_drive"):
        return str(args.get("operation") or "") or None
    return None


async def mark(context: Optional[Dict[str, Any]], tool_name: str, args: Any,
               used: Sequence[Dict[str, str]], *, now: Optional[datetime] = None) -> int:
    """Mark the run: it read through ``used``. A write is not marked: what it
    returns is the business's own (an id)."""
    from src.ai.governance.connector_actions import outbound
    from src.common.tenancy.session import tenant_session
    from src.connections.models import ConnectorDataMark

    ctx = context or {}
    run_id, company_id = ctx.get("run_id"), ctx.get("company_id")
    if not run_id or not company_id or not used or outbound(tool_name, args if isinstance(args, dict) else {}):
        return 0
    operation = _operation(tool_name, args)
    at = now or datetime.utcnow()
    rows = []
    for use in used:
        rule = rule_for(use["connector_id"])
        own = bool(operation and operation in rule.exempt)   # the account's own data (a Page's statistics)
        hours = rule.exempt_hours if own else rule.hours
        rows.append({"id": uuid.uuid4(), "run_id": uuid.UUID(str(run_id)), "company_id": uuid.UUID(str(company_id)),
                     "connection_id": uuid.UUID(use["connection_id"]), "connector_id": use["connector_id"],
                     "tool_name": tool_name, "operation": operation or "", "created_at": at,
                     "expires_at": at + timedelta(hours=hours) if hours else None,
                     "results": rule.results and not own, "records": rule.records or own})
    statement = pg_insert(ConnectorDataMark).values(rows)
    # The first read of a run sets the time (the earliest is the strictest); a
    # read after its removal arms the mark again for what came in since.
    statement = statement.on_conflict_do_update(
        index_elements=["run_id", "connection_id", "tool_name", "operation"],
        set_={"redacted_at": None, "expires_at": statement.excluded.expires_at},
        where=ConnectorDataMark.redacted_at.is_not(None))
    async with tenant_session(company_id) as db:
        await db.execute(statement)
        await db.commit()
    return len(rows)


# ── What a mark means for the run ───────────────────────────────────────────

async def run_marks(db: Any, run_id: Any) -> List[Any]:
    from src.connections.models import ConnectorDataMark

    return list((await db.execute(select(ConnectorDataMark).where(
        ConnectorDataMark.run_id == uuid.UUID(str(run_id))))).scalars().all())


async def marked_runs(db: Any, run_ids: Sequence[Any]) -> Dict[str, List[str]]:
    """``{run id: [connector ids]}`` for the runs that read through a connection."""
    from src.connections.models import ConnectorDataMark

    ids = [uuid.UUID(str(r)) for r in run_ids if r]
    if not ids:
        return {}
    found: Dict[str, List[str]] = {}
    for run_id, connector_id in (await db.execute(select(
            ConnectorDataMark.run_id, ConnectorDataMark.connector_id).where(ConnectorDataMark.run_id.in_(ids)))):
        found.setdefault(str(run_id), [])
        if connector_id not in found[str(run_id)]:
            found[str(run_id)].append(connector_id)
    return found


async def records_refusal(db: Any, actor: str) -> Optional[str]:
    """Why a run may not save records, or ``None`` (LI-E3: LinkedIn member data,
    and X and YouTube data, never go into records, and so never into exports
    or the Data API)."""
    from src.connections.models import ConnectorDataMark

    if not actor.startswith("run:"):
        return None
    try:
        run_id = uuid.UUID(actor.split(":", 1)[1])
    except ValueError:
        return None
    connector_id = (await db.execute(select(ConnectorDataMark.connector_id).where(
        ConnectorDataMark.run_id == run_id, ConnectorDataMark.records.is_(False)).limit(1))).scalar()
    if connector_id is None:
        return None
    rule = rule_for(connector_id)
    because = f" ({rule.rule})" if rule.rule else ""
    return (f"This run read data from {_name(connector_id)}, which may not be saved to records{because}. "
            "Use it in this run's answer only.")


async def keeps_no_memory(db: Any, run_id: Any) -> bool:
    """A run that read what may not be kept leaves no episode in long-term memory."""
    from src.connections.models import ConnectorDataMark

    return (await db.execute(select(ConnectorDataMark.id).where(
        ConnectorDataMark.run_id == uuid.UUID(str(run_id)), ConnectorDataMark.records.is_(False)).limit(1))
    ).scalar() is not None


async def expire_connection(db: Any, connection_id: Any, *, now: Optional[datetime] = None) -> int:
    """Disconnected: what every run read through the connection goes on the next pass."""
    from src.connections.models import ConnectorDataMark

    at = now or datetime.utcnow()
    result = await db.execute(update(ConnectorDataMark).where(
        ConnectorDataMark.connection_id == uuid.UUID(str(connection_id)), ConnectorDataMark.redacted_at.is_(None),
        or_(ConnectorDataMark.expires_at.is_(None), ConnectorDataMark.expires_at > at)).values(expires_at=at))
    return int(result.rowcount or 0)


# ── The removal ─────────────────────────────────────────────────────────────

def notice(marks: Sequence[Any], now: datetime) -> str:
    names = ", ".join(sorted({_name(m.connector_id) for m in marks}))
    rules = sorted({rule_for(m.connector_id).rule for m in marks} - {""})
    because = f" ({'; '.join(rules)})" if rules else ""
    return f"[Removed {now:%Y-%m-%d %H:%M} UTC: what this run read from {names} is not kept longer{because}.]"


async def _redact_run(db: Any, run_id: Any, marks: Sequence[Any], now: datetime) -> Dict[str, int]:
    """Remove what the run read; ``{"deferred": 1}`` when its result must wait for the run to end."""
    from cortex_memory.models import CortexNode
    from src.ai.orm.execution import ExecutionRun, LLMInteractionLog, ToolInteractionLog
    from src.ai.orm.trace import ExecutionTraceEvent
    from src.ai.schemas.enums import TERMINAL_RUN_STATUSES

    text = notice(marks, now)
    # The calls that read it: a tool, or one operation of a tool that has them (social_api).
    calls = [and_(ToolInteractionLog.tool_name == m.tool_name,
                  ToolInteractionLog.input_parameters["operation"].astext == m.operation) if m.operation
             else ToolInteractionLog.tool_name == m.tool_name for m in marks]
    done = {"tool_logs": int((await db.execute(update(ToolInteractionLog).where(
        ToolInteractionLog.run_id == run_id, or_(*calls)).values(output_result=text))).rowcount or 0)}
    # A step's span holds its output, an LLM span its prompt: every payload of the
    # run goes; what the spans say about the run (kind, name, timings, cost) stays.
    done["spans"] = int((await db.execute(update(ExecutionTraceEvent).where(
        ExecutionTraceEvent.run_id == run_id, ExecutionTraceEvent.payload.is_not(None))
        .values(payload={"removed": text}))).rowcount or 0)
    done["llm_logs"] = int((await db.execute(update(LLMInteractionLog).where(LLMInteractionLog.run_id == run_id)
                                             .values(input_prompt=text, output_response=text))).rowcount or 0)
    done["memory_nodes"] = int((await db.execute(update(CortexNode).where(or_(
        CortexNode.execution_run_id == run_id, CortexNode.metadata_extra["run_id"].astext == str(run_id)))
        .values(content=text, summary=text[:500], embedding=None))).rowcount or 0)
    if any(m.results for m in marks):
        status = (await db.execute(select(ExecutionRun.status).where(ExecutionRun.id == run_id))).scalar()
        if status is not None and str(status) not in TERMINAL_RUN_STATUSES:
            return {**done, "deferred": 1}   # its result is not final yet
        done["results"] = int((await db.execute(update(ExecutionRun).where(ExecutionRun.id == run_id).values(
            result_data={"output": text, "removed": True}, context_state=None))).rowcount or 0)
    return done


async def redact_due(db: Any, *, now: Optional[datetime] = None, batch: int = BATCH) -> Dict[str, int]:
    """One pass over the database's marks whose time is up; returns what was removed."""
    from src.connections.models import ConnectorDataMark

    at = now or datetime.utcnow()
    due = (await db.execute(select(ConnectorDataMark).where(
        ConnectorDataMark.redacted_at.is_(None), ConnectorDataMark.expires_at.is_not(None),
        ConnectorDataMark.expires_at <= at).order_by(ConnectorDataMark.expires_at).limit(batch))).scalars().all()
    by_run: Dict[Any, List[Any]] = {}
    for item in due:
        by_run.setdefault(item.run_id, []).append(item)
    totals: Dict[str, int] = {"runs": 0, "due": len(due)}
    for run_id, marks in by_run.items():
        done = await _redact_run(db, run_id, marks, at)
        for key, count in done.items():
            totals[key] = totals.get(key, 0) + count
        ids = [m.id for m in marks]
        if done.get("deferred"):   # looked at again later, so it never holds up the marks behind it
            await db.execute(update(ConnectorDataMark).where(ConnectorDataMark.id.in_(ids))
                             .values(expires_at=at + RETRY_UNFINISHED))
            continue
        totals["runs"] += 1
        await db.execute(update(ConnectorDataMark).where(ConnectorDataMark.id.in_(ids)).values(redacted_at=at))
    totals["events"] = await _prune_events(db, at)
    await db.commit()
    return totals


async def _prune_events(db: Any, now: datetime) -> int:
    """Events a connection delivered (comments, messages) go after the same limit."""
    from sqlalchemy import delete

    from src.automation.models import Event, TriggerFiring
    from src.connections.catalog import specs
    from src.connections.models import Connection

    limited = {cid: s.retention.hours for cid, s in specs().items() if s.retention.hours}
    if not limited:
        return 0
    removed = 0
    for connection_id, company_id, connector_id in (await db.execute(select(
            Connection.id, Connection.company_id, Connection.connector_id).where(
            Connection.connector_id.in_(list(limited))))).all():
        came_through = (Event.company_id == company_id, Event.subject == f"connection:{connection_id}",
                        Event.source != "connections",
                        Event.received_at < now - timedelta(hours=limited[connector_id]))
        await db.execute(update(TriggerFiring).where(TriggerFiring.event_id.in_(
            select(Event.id).where(*came_through))).values(event_id=None))
        removed += int((await db.execute(delete(Event).where(*came_through))).rowcount or 0)
    return removed


async def redact_connector_data(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """arq cron (hourly): every tenant database's marks whose time is up."""
    from src.common.tenancy.session import tenant_scopes, tenant_session

    totals: Dict[str, int] = {}
    for scope in await tenant_scopes():
        try:
            async with tenant_session(scope) as db:
                while True:
                    done = await redact_due(db)
                    for key, count in done.items():
                        totals[key] = totals.get(key, 0) + count
                    if done.get("due", 0) < BATCH:   # the last batch: nothing more is due
                        break
        except Exception:  # one tenant database away must not stop the others
            logger.exception("connector data removal in tenant %s failed", scope)
    if totals.get("runs") or totals.get("events"):
        logger.info("connector data removed: %s", totals)
    return {"removed": totals}
