"""Running an offboarding, step by step (docs/phase15/13 §6, §10).

``run(offboarding_id)`` takes the steps of its mode in order, from the first
that has not succeeded: each attempt is an ``OffboardingStepLog`` row
(started, then succeeded, skipped or failed). A failed step leaves the
offboarding ``failed`` with the error; running it again resumes there. Two
runners never work on one business at once (an advisory lock). The
workspace the steps act on is written to the offboarding when it starts, so a
run that resumes after the control rows are gone still knows it.

The arq job ``offboard_company`` runs it on the provisioning queue — as the
provisioner identity on Azure, which holds the rights to remove what it made.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func, select, text

from src.offboarding import steps as control
from src.offboarding import workspace as ws_steps
from src.offboarding.models import CompanyOffboarding, OffboardingStepLog
from src.offboarding.workspace import Workspace

logger = logging.getLogger(__name__)

Step = Callable[..., Awaitable[Dict[str, Any]]]


def _ws(fn: Callable[[Workspace], Awaitable[Dict[str, Any]]]) -> Step:
    async def run(db: Any, off: CompanyOffboarding, ws: Workspace) -> Dict[str, Any]:
        return await fn(ws)
    run.__name__ = fn.__name__
    return run


ERASURE_STEPS: List[tuple] = [
    ("quiesced", control.quiesced),
    ("billing_closed", control.billing_closed),
    ("records_retained", control.records_retained),
    ("exported", control.exported),
    ("apps_removed", _ws(ws_steps.apps_removed)),
    ("namespace_deleted", _ws(ws_steps.namespace_deleted)),
    ("storage_deleted", _ws(ws_steps.storage_deleted)),
    ("database_dropped", _ws(ws_steps.database_dropped)),
    ("identity_deleted", _ws(ws_steps.identity_deleted)),
    ("key_deleted", _ws(ws_steps.key_deleted)),
    ("control_erased", control.control_erased),
]
IMMEDIATE_STEPS: List[tuple] = [
    ("quiesced", control.quiesced),
    ("billing_closed", control.billing_closed),
    ("apps_removed", _ws(ws_steps.apps_removed)),
    ("namespace_deleted", _ws(ws_steps.namespace_deleted)),
    ("storage_deleted", _ws(ws_steps.storage_deleted)),
    ("database_dropped", _ws(ws_steps.database_dropped)),
    ("identity_deleted", _ws(ws_steps.identity_deleted)),
    ("key_deleted", _ws(ws_steps.key_deleted)),
    ("control_purged", control.control_purged),
]
FINAL_STEPS = ("verified", "certified")


def steps_of(mode: str) -> List[str]:
    return [name for name, _ in (IMMEDIATE_STEPS if mode == "immediate" else ERASURE_STEPS)] + list(FINAL_STEPS)


def _lock_id(company_id: UUID) -> int:
    return int.from_bytes(hashlib.sha256(f"offboard:{company_id}".encode()).digest()[:8], "big", signed=True)


async def _done(db: Any, offboarding_id: UUID) -> set:
    rows = (await db.execute(select(OffboardingStepLog.step).where(
        OffboardingStepLog.offboarding_id == offboarding_id,
        OffboardingStepLog.outcome.in_(("succeeded", "skipped"))))).scalars().all()
    return set(rows)


async def _attempt(db: Any, offboarding_id: UUID, step: str) -> int:
    n = (await db.execute(select(func.count()).where(OffboardingStepLog.offboarding_id == offboarding_id,
                                                     OffboardingStepLog.step == step,
                                                     OffboardingStepLog.outcome == "started"))).scalar()
    return int(n or 0) + 1


def _workspace(off: CompanyOffboarding) -> Workspace:
    saved = (off.inventory or {}).get("workspace") or {}
    return Workspace(company_id=off.company_id, tenant_key=saved.get("tenant_key"), db_name=saved.get("db_name"),
                     server_host=saved.get("server_host"))


async def run(offboarding_id: UUID) -> Dict[str, Any]:
    """Run (or resume) the offboarding; what each step did, or where it stopped."""
    from src.common.tenancy.session import control_session

    async with control_session() as lock_db:
        conn = await lock_db.connection()
        off = await lock_db.get(CompanyOffboarding, offboarding_id)
        if off is None:
            raise LookupError(f"no offboarding {offboarding_id}")
        got = (await conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _lock_id(off.company_id)})).scalar()
        if not got:
            return {"offboarding_id": str(offboarding_id), "state": off.state, "busy": True}
        try:
            return await _run_locked(offboarding_id)
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _lock_id(off.company_id)})


async def _run_locked(offboarding_id: UUID) -> Dict[str, Any]:
    from src.common.tenancy.session import control_session

    async with control_session() as db:
        off = await db.get(CompanyOffboarding, offboarding_id)
        if off.state in ("erased", "cancelled"):
            return {"offboarding_id": str(off.id), "state": off.state, "steps": []}
        if off.state == "requested":
            raise RuntimeError("the offboarding is still in its grace period")
        if not (off.inventory or {}).get("workspace"):
            await _start(db, off)
        off.state, off.error = "erasing", None
        off.started_at = off.started_at or datetime.utcnow()
        await db.commit()
        mode = off.mode
    table = dict(IMMEDIATE_STEPS if mode == "immediate" else ERASURE_STEPS)
    ran: List[Dict[str, Any]] = []
    for step in steps_of(mode):
        async with control_session() as db:
            off = await db.get(CompanyOffboarding, offboarding_id)
            if step in await _done(db, off.id):
                continue
            attempt = await _attempt(db, off.id, step)
            db.add(OffboardingStepLog(offboarding_id=off.id, step=step, outcome="started", attempt=attempt))
            await db.commit()
            ws = _workspace(off)
            try:
                if step == "verified":
                    detail = await verify(db, off, ws)
                elif step == "certified":
                    detail = await certify(db, off)
                else:
                    detail = await table[step](db, off, ws)
            except Exception as exc:  # noqa: BLE001 - recorded; the run resumes here next time
                await db.rollback()
                error = f"{type(exc).__name__}: {exc}"[:2000]
                logger.error("offboarding %s: step %s failed: %s", offboarding_id, step, error)
                off = await db.get(CompanyOffboarding, offboarding_id)
                db.add(OffboardingStepLog(offboarding_id=off.id, step=step, outcome="failed", attempt=attempt,
                                          error=error))
                off.state, off.error, off.updated_at = "failed", f"{step}: {error}", datetime.utcnow()
                await db.commit()
                ran.append({"step": step, "outcome": "failed", "error": error})
                return {"offboarding_id": str(offboarding_id), "state": "failed", "failed": step, "steps": ran}
            off = await db.get(CompanyOffboarding, offboarding_id)
            outcome = "skipped" if isinstance(detail, dict) and set(detail) == {"skipped"} else "succeeded"
            db.add(OffboardingStepLog(offboarding_id=off.id, step=step, outcome=outcome, attempt=attempt,
                                      detail=_json(detail)))
            off.last_step, off.updated_at = step, datetime.utcnow()
            await db.commit()
            ran.append({"step": step, "outcome": outcome, "detail": _json(detail)})
            if step in ("database_dropped", "control_purged", "control_erased"):
                await _publish(off.company_id)
    return {"offboarding_id": str(offboarding_id), "state": "erased", "steps": ran}


def _json(value: Any) -> Any:
    import json
    return json.loads(json.dumps(value, default=str))


async def _publish(company_id: UUID) -> None:
    try:
        from src.common.tenancy.provisioner import _publish as publish
        await publish(company_id)
    except Exception:  # noqa: BLE001 - other processes see it within the cache time
        logger.warning("offboarding: directory change of %s not published", company_id)


async def _start(db: Any, off: CompanyOffboarding) -> None:
    """Note the workspace and count what is about to go (the certificate's 'before')."""
    from src.offboarding.purge import row_counts
    from src.offboarding.workspace import workspace_of

    ws = await workspace_of(db, off.company_id)
    counts = await row_counts(await db.connection(), off.company_id)
    off.inventory = {**(off.inventory or {}),
                     "workspace": {"tenant_key": ws.tenant_key, "db_name": ws.db_name, "server_host": ws.server_host},
                     "control_rows": counts}


# ── 13 verified ─────────────────────────────────────────────────────────────

async def verify(db: Any, off: CompanyOffboarding, ws: Workspace) -> Dict[str, Any]:
    """Looks for anything left; a finding fails the step (and the run stops there)."""
    from src.offboarding.purge import row_counts

    findings = await leftovers(db, off, ws)
    if findings:
        raise RuntimeError("left behind: " + "; ".join(findings))
    kept = await row_counts(await db.connection(), off.company_id)
    return {"left": [], "retained_rows": kept}


async def leftovers(db: Any, off: CompanyOffboarding, ws: Workspace) -> List[str]:
    """What should be gone and is not — also a staff check (``python -m src.offboarding.verify``)."""
    from src.auth.models import Company, User
    from src.offboarding.purge import row_counts

    found: List[str] = []
    if await ws_steps.database_exists(ws):
        found.append(f"database {ws.db_name}")
    if await ws_steps.namespace_exists(ws):
        found.append(f"cluster namespace t-{ws.tenant_key}")
    for namespace, n in (await ws_steps.storage_left(ws)).items():
        found.append(f"{n} objects in storage {namespace}")
    if await ws_steps.identity_exists(ws):
        found.append(f"identity of t-{ws.tenant_key}")
    users = (await db.execute(select(func.count()).select_from(User).where(User.company_id == off.company_id))).scalar()
    if users:
        found.append(f"{users} users")
    counts = await row_counts(await db.connection(), off.company_id)
    allowed = set() if off.mode == "immediate" else set(control.RETAINED_TABLES)
    for table, n in counts.items():
        if table not in allowed:
            found.append(f"{n} rows of {table}")
    company = await db.get(Company, off.company_id)
    if off.mode == "immediate" and company is not None:
        found.append("the company row")
    if off.mode == "erasure" and company is not None and company.status != "erased":
        found.append("the company row is not anonymised")
    others = (await db.execute(text(
        "SELECT count(*) FROM partner_access_grants WHERE tenant_id = :c"), {"c": off.company_id})).scalar()
    if others:
        found.append(f"{others} partner access grants")
    for table, columns in control.KEYLESS_REFERENCES:
        if table in allowed:
            continue
        where = " OR ".join(f"{c} = :c" for c in columns)
        n = (await db.execute(text(f"SELECT count(*) FROM {table} WHERE {where}"), {"c": off.company_id})).scalar()
        if n:
            found.append(f"{n} rows of {table} naming it")
    return found


# ── 14 certified ────────────────────────────────────────────────────────────

async def certify(db: Any, off: CompanyOffboarding) -> Dict[str, Any]:
    from src.offboarding.certificate import build

    log = (await db.execute(select(OffboardingStepLog).where(
        OffboardingStepLog.offboarding_id == off.id, OffboardingStepLog.outcome != "started")
        .order_by(OffboardingStepLog.created_at))).scalars().all()
    certificate, pdf = build(off, log)
    off.certificate = certificate
    if off.mode == "erasure":
        from src.common.platform.storage import get_storage

        key = f"{control.RETAINED_NAMESPACE}/{off.company_ref}/certificate.pdf"
        await get_storage().put(key, pdf, content_type="application/pdf")
        off.certificate_key = key
    off.state, off.finished_at, off.updated_at = "erased", datetime.utcnow(), datetime.utcnow()
    await db.commit()
    return {"certificate": off.certificate_key or "kept on the offboarding record"}


async def offboard_company(ctx: Dict[str, Any], offboarding_id: str) -> Dict[str, Any]:
    """arq job: run (or resume) one offboarding."""
    return await run(UUID(str(offboarding_id)))


async def enqueue(offboarding_id: UUID) -> Optional[Any]:
    from src.common.config import settings
    from src.common.job_queue import enqueue_job

    options: Dict[str, Any] = {"_queue_name": settings.PROVISIONING_QUEUE} if settings.PROVISIONING_QUEUE else {}
    options["_job_id"] = f"offboard:{offboarding_id}:{datetime.utcnow():%Y%m%d%H%M%S}"
    return await enqueue_job("offboard_company", str(offboarding_id), **options)


async def offboarding_tick(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Every 15 minutes: erasures whose grace has ended start; reminders 7 days and 1 day before."""
    from src.common.tenancy.session import control_session
    from src.offboarding.service import tick

    async with control_session() as db:
        return await tick(db)
