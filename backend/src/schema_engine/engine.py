"""Running schema changes in a business's own database (tech spec §8.4).

    proposal → validate → plan (+ row counts) → impact → approval → apply → vN+1 active
                                                                          → schema.version.activated

* **Where.** Records live in the business's own database (WS2's tenant
  directory). A business still on the shared database has no records yet:
  :class:`RecordsUnavailable`.
* **Approval** (D20, §8.4): a person's change (owner, admin, an app key with
  the schema scope) applies after its preview; an agent's change waits for a
  person, unless it is additive and the business allows agents' additive
  changes; a person decides with :func:`decide`.
* **Apply.** One transaction with ``lock_timeout`` 5 s and
  ``statement_timeout`` 60 s: the checks (no violating rows), the DDL, the new
  blueprint version active, the change applied, the event. Anything failing
  rolls it all back and leaves the active blueprint as it was. An index on a
  big table is built ``CONCURRENTLY`` afterwards, outside the transaction.
* **First use** applies base pack v1 (``base_pack``) as version 1.
* **Who runs the DDL** (Phase 14 M2). A tenant database's objects belong to
  the DDL role (``TENANT_DB_DDL_ROLE``, ``tenancy/db_roles``). A member of it
  (the provisioner, the migrator, a local superuser) applies the change as that
  role (``SET LOCAL ROLE``). The API and workers are not members: with a
  provisioning queue (Azure) the change is applied by the provisioning worker
  (``apply_schema_change``) and the caller waits for its outcome; without one
  (local, one user) it is applied here as before.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from src.schema_engine import base_pack, planner
from src.schema_engine import blueprint as bp
from src.schema_engine.models import SchemaBlueprint, SchemaChange

logger = logging.getLogger(__name__)

LOCK_TIMEOUT = "5s"
STATEMENT_TIMEOUT = "60s"
# How long a caller waits for the provisioning worker to apply its change.
DELEGATED_APPLY_TIMEOUT = 180
_cache: Dict[str, Tuple[int, Dict[str, Any]]] = {}


class RecordsUnavailable(RuntimeError):
    """The business has no database of its own yet, so no records."""


class ApplyError(RuntimeError):
    """A change that could not be applied; the message says why. Nothing changed."""


async def business_engine(company_id: Any) -> Tuple[AsyncEngine, Any]:
    """The engine of the business's own database, and its directory location."""
    from src.common.tenancy.directory import directory
    from src.common.tenancy.engines import engines

    location = await directory.find(company_id)
    if location is None or not location.database_ready:
        raise RecordsUnavailable("records need the business on its own database; this one has none yet")
    return engines.get(location), location


def session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


async def active_row(db: AsyncSession, company_id: Any) -> Optional[SchemaBlueprint]:
    return (await db.execute(select(SchemaBlueprint).where(
        SchemaBlueprint.company_id == company_id, SchemaBlueprint.status == "active"))).scalar_one_or_none()


async def active_blueprint(engine: AsyncEngine, company_id: Any) -> Dict[str, Any]:
    """The business's active blueprint (base pack v1 applied on first use)."""
    async with session(engine) as db:
        row = await active_row(db, company_id)
        if row is not None:
            _cache[str(company_id)] = (row.version, row.document)
            return row.document
    await _apply_base_pack(engine, company_id)
    async with session(engine) as db:
        row = await active_row(db, company_id)
        return row.document


async def _apply_base_pack(engine: AsyncEngine, company_id: Any) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS business"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS custom"))
    try:
        await propose(engine, company_id, base_pack.operations(), actor_kind="platform", actor_id="base_pack",
                      reason=f"base pack {base_pack.VERSION}", base=bp.empty(), base_pack_version=base_pack.VERSION)
    except ApplyError:
        async with session(engine) as db:  # another request applied it first
            if await active_row(db, company_id) is None:
                raise


async def row_counts(db: AsyncSession, blueprint: Dict[str, Any]) -> Dict[str, int]:
    """Estimated rows per business table (planner: concurrent indexes on big tables)."""
    rows = (await db.execute(text(
        "SELECT c.relname, c.reltuples::bigint FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname IN ('business', 'custom') AND c.relkind = 'r'"))).all()
    return {name: max(0, int(count)) for name, count in rows}


def _planner_actor(actor_kind: str) -> str:
    return "platform" if actor_kind == "platform" else "user"


async def impact(db: AsyncSession, company_id: Any, current: Dict[str, Any], result: planner.Plan) -> Dict[str, Any]:
    """What a change touches beyond its tables: triggers on the objects' records,
    app keys granted on them (and, with WS4 4.8, agents' declared records)."""
    from src.automation.models import Trigger
    from src.schema_engine.models import ApiKey

    names = {name for name in (current.get("objects") or {})} | set(result.blueprint["objects"])
    changed = [n for n in names if (current.get("objects") or {}).get(n) != result.blueprint["objects"].get(n)]
    triggers = (await db.execute(select(Trigger.id, Trigger.name, Trigger.event_type).where(
        Trigger.company_id == company_id, Trigger.event_type.like("record.%")))).all()
    keys = (await db.execute(select(ApiKey.id, ApiKey.name, ApiKey.scopes).where(
        ApiKey.company_id == company_id, ApiKey.revoked_at.is_(None)))).all()
    return {
        "objects": sorted(changed),
        "triggers": [{"id": str(t.id), "name": t.name, "event_type": t.event_type} for t in triggers
                     if any(str(t.event_type).startswith(f"record.{n}.") or t.event_type == f"record.{n}.*"
                            for n in changed)],
        "api_keys": [{"id": str(k.id), "name": k.name} for k in keys
                     if any(n in ((k.scopes or {}).get("objects") or {}) for n in changed)],
    }


async def propose(engine: AsyncEngine, company_id: Any, operations: List[Dict[str, Any]], *, actor_kind: str,
                  actor_id: Optional[str] = None, run_id: Any = None, reason: Optional[str] = None,
                  dry_run: bool = False, agents_auto_additive: Optional[bool] = None,
                  base: Optional[Dict[str, Any]] = None, base_pack_version: Optional[str] = None) -> Dict[str, Any]:
    """Plan a change; apply it, or leave it awaiting a person. Returns the change's view
    (a preview with ``dry_run``). Raises :class:`planner.PlanError` for a change that
    cannot be planned and :class:`ApplyError` for one that could not be applied.

    An agent's change waits for a person — in the approvals inbox too — unless it
    only adds and the owner lets such changes through (``agents_auto_additive``;
    default: the business's ``records_settings``)."""
    from src.schema_engine import approvals

    current = base if base is not None else await active_blueprint(engine, company_id)
    if actor_kind == "agent" and agents_auto_additive is None:
        agents_auto_additive = (await approvals.settings_for(engine, company_id))["agents_auto_approve_additive"]
    async with session(engine) as db:
        result = planner.plan(current, operations, actor=_planner_actor(actor_kind),
                              row_counts=await row_counts(db, current))
        if base_pack_version:
            result.blueprint["base_pack"] = base_pack_version
        effects = await impact(db, company_id, current, result)
        needs_person = actor_kind == "agent" and not (result.additive and agents_auto_additive)
        preview = {"plan": result.as_dict(), "impact": effects, "needs_approval": needs_person,
                   "base_version": int(current.get("version") or 0), "result_version": result.blueprint["version"]}
        if dry_run:
            return {"status": "preview", **preview}
        change = SchemaChange(id=uuid.uuid4(), company_id=company_id, operations=operations, reason=reason,
                              actor_kind=actor_kind, actor_id=actor_id, run_id=run_id,
                              base_version=int(current.get("version") or 0), plan=result.as_dict(), impact=effects,
                              status="awaiting_approval" if needs_person else "proposed")
        db.add(change)
        await db.commit()
        change_id = change.id
    if needs_person:
        view = await change_view(engine, company_id, change_id)
        await approvals.open_for(company_id, view)
        return view
    await apply(engine, company_id, change_id, current=current, base_pack_version=base_pack_version)
    return await change_view(engine, company_id, change_id)


async def decide(engine: AsyncEngine, company_id: Any, change_id: Any, *, approve: bool, decided_by: str) -> Dict[str, Any]:
    """A person's decision on a change awaiting approval."""
    async with session(engine) as db:
        change = await db.get(SchemaChange, UUID(str(change_id)))
        if change is None or change.company_id != company_id:
            raise LookupError("no such change")
        if change.status != "awaiting_approval":
            raise ApplyError(f"the change is {change.status}, not awaiting a decision")
        change.decided_by, change.decided_at = decided_by, datetime.utcnow()
        if not approve:
            change.status = "rejected"
        await db.commit()
    from src.schema_engine import approvals

    await approvals.close_for(company_id, change_id, approved=approve, decided_by=decided_by)
    if approve:
        await apply(engine, company_id, change_id)
    return await change_view(engine, company_id, change_id)


async def _ddl_mode(engine: AsyncEngine) -> Tuple[str, Optional[str]]:
    """``("member", role)``: this connection's user may act as the DDL role;
    ``("delegate", role)``: it may not, and the provisioning worker can;
    ``("here", None)``: no DDL role (one user owns everything)."""
    from src.common.config import settings
    from src.common.tenancy.db_roles import ddl_role

    role = ddl_role()
    if role is None:
        return "here", None
    async with engine.connect() as conn:
        member = (await conn.execute(text(
            "SELECT current_user = :r OR (EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :r) "
            "AND pg_has_role(current_user, :r, 'MEMBER'))"), {"r": role})).scalar()
    if member:
        return "member", role
    return ("delegate", role) if settings.PROVISIONING_QUEUE else ("here", None)


async def _apply_elsewhere(company_id: Any, change_id: UUID, base_pack_version: Optional[str]) -> None:
    """The provisioning worker applies the change as the DDL role; wait for its outcome."""
    from src.common.config import settings
    from src.common.job_queue import arq_pool, enqueue_on

    async with arq_pool() as pool:
        job = await enqueue_on(pool, "apply_schema_change", str(company_id), str(change_id), base_pack_version,
                               _queue_name=settings.PROVISIONING_QUEUE)
        if job is None:
            raise ApplyError("the change could not be queued")
        try:
            await job.result(timeout=DELEGATED_APPLY_TIMEOUT, poll_delay=0.3)
        except ApplyError:
            raise
        except Exception as error:  # the worker's error, or no answer in time
            raise ApplyError(str(error) or type(error).__name__) from None
    _cache.pop(str(company_id), None)


async def apply_schema_change(ctx: Any, company_id: str, change_id: str,
                              base_pack_version: Optional[str] = None) -> Dict[str, Any]:
    """arq job on the provisioning queue: apply a change in the tenant's database as the DDL role."""
    from src.common.tenancy.db_roles import ddl_role
    from src.common.tenancy.directory import directory
    from src.common.tenancy.engines import create_tenant_engine, tenant_url

    location = await directory.find(UUID(company_id))
    if location is None or not location.database_ready:
        raise ApplyError("the business has no database of its own")
    engine = create_tenant_engine(tenant_url(location), role=ddl_role())
    try:
        await apply(engine, UUID(company_id), change_id, base_pack_version=base_pack_version)
    finally:
        await engine.dispose()
    return {"applied": str(change_id)}


async def apply(engine: AsyncEngine, company_id: Any, change_id: Any, *, current: Optional[Dict[str, Any]] = None,
                base_pack_version: Optional[str] = None) -> None:
    """Apply one change in one transaction; on failure it is ``failed`` and nothing changed."""
    from src.automation import store
    from src.automation.events import Envelope

    change_id = UUID(str(change_id))
    mode, role = await _ddl_mode(engine)
    if mode == "delegate":
        await _apply_elsewhere(company_id, change_id, base_pack_version)
        return
    concurrent: List[str] = []
    try:
        async with session(engine) as db:
            change = await db.get(SchemaChange, change_id)
            row = await active_row(db, company_id)
            if current is None:
                current = row.document if row is not None else bp.empty()
            if row is not None and base_pack_version and row.version >= 1:
                raise ApplyError("a blueprint is already active")
            # Re-planned on what is active now: another change may have landed since the proposal.
            result = planner.plan(current, change.operations, actor=_planner_actor(change.actor_kind),
                                  row_counts=await row_counts(db, current))
            if base_pack_version:
                result.blueprint["base_pack"] = base_pack_version
            await db.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
            await db.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
            if role:  # its objects belong to the DDL role (tenancy/db_roles)
                await db.execute(text(f'SET LOCAL ROLE "{role}"'))
            for check in result.checks:
                if (await db.execute(text(check.sql))).scalar():
                    raise ApplyError(check.message)
            for statement in result.statements:
                if statement.concurrently:
                    concurrent.append(statement.sql)
                else:
                    await db.execute(text(statement.sql))
            if row is not None:
                await db.execute(update(SchemaBlueprint).where(SchemaBlueprint.id == row.id)
                                 .values(status="superseded"))
                await db.flush()
            version = result.blueprint["version"]
            db.add(SchemaBlueprint(id=uuid.uuid4(), company_id=company_id, version=version, status="active",
                                   document=result.blueprint, change_id=change_id))
            change.status, change.result_version, change.applied_at = "applied", version, datetime.utcnow()
            change.plan, change.error = result.as_dict(), None
            event, created = await store.record(db, company_id, Envelope(
                type="schema.version.activated", source="schema_engine", trust="internal",
                dedupe_key=f"schema:{company_id}:{version}", subject=f"schema:{version}",
                data={"version": version, "change_id": str(change_id), "summary": result.summary}))
            await db.commit()
            event_id = event.id if created else None
    except Exception as error:
        message = str(error) if isinstance(error, (ApplyError, planner.PlanError)) else f"{type(error).__name__}: {error}"
        async with session(engine) as db:
            await db.execute(update(SchemaChange).where(SchemaChange.id == change_id)
                             .values(status="failed", error=message[:2000]))
            await db.commit()
        if isinstance(error, (ApplyError, planner.PlanError)):
            raise ApplyError(message) from None
        logger.exception("schema change %s failed", change_id)
        raise ApplyError(message) from error

    _cache.pop(str(company_id), None)
    for sql in concurrent:  # outside a transaction; the blueprint is already active
        try:
            async with engine.connect() as conn:
                autocommit = await conn.execution_options(isolation_level="AUTOCOMMIT")
                if role:
                    await autocommit.execute(text(f'SET ROLE "{role}"'))
                await autocommit.execute(text(sql))
                if role:
                    await autocommit.execute(text("RESET ROLE"))
        except Exception as error:  # noqa: BLE001 - recorded; the index can be added again
            logger.warning("concurrent index for change %s not built: %s", change_id, error)
            async with session(engine) as db:
                await db.execute(update(SchemaChange).where(SchemaChange.id == change_id)
                                 .values(error=f"index not built: {error}"[:2000]))
                await db.commit()
    if event_id is not None:
        await store.nudge(company_id, event_id)
    await _announce(company_id, version)


async def _announce(company_id: Any, version: int) -> None:
    """Tell running Data API instances to reload (channel ``tenant:<key>:schema``)."""
    try:
        from src.common.redis_client import shared_redis
        from src.common.tenancy.directory import directory

        location = await directory.find(company_id)
        if location is not None:
            await shared_redis().publish(f"tenant:{location.key}:schema", str(version))
    except Exception:  # noqa: BLE001 - instances also re-read on their own
        logger.debug("schema version %s not announced", version, exc_info=True)


async def change_view(engine: AsyncEngine, company_id: Any, change_id: Any) -> Dict[str, Any]:
    async with session(engine) as db:
        change = await db.get(SchemaChange, UUID(str(change_id)))
        if change is None or change.company_id != company_id:
            raise LookupError("no such change")
        return {"id": str(change.id), "status": change.status, "operations": change.operations,
                "reason": change.reason, "actor_kind": change.actor_kind, "actor_id": change.actor_id,
                "run_id": str(change.run_id) if change.run_id else None,
                "base_version": change.base_version, "result_version": change.result_version,
                "plan": change.plan, "impact": change.impact, "error": change.error,
                "decided_by": change.decided_by, "decided_at": _iso(change.decided_at),
                "created_at": _iso(change.created_at), "applied_at": _iso(change.applied_at)}


async def list_changes(engine: AsyncEngine, company_id: Any, *, status: Optional[str] = None,
                       limit: int = 100) -> List[Dict[str, Any]]:
    """The business's schema changes, newest first (the change review screen, WS8 8.2)."""
    query = select(SchemaChange.id).where(SchemaChange.company_id == company_id)
    if status:
        query = query.where(SchemaChange.status == status)
    async with session(engine) as db:
        ids = (await db.execute(query.order_by(SchemaChange.created_at.desc()).limit(min(limit, 500)))).scalars().all()
    return [await change_view(engine, company_id, change_id) for change_id in ids]


def _iso(moment: Optional[datetime]) -> Optional[str]:
    if moment is None:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment.isoformat() + "Z"
