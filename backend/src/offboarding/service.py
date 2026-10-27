"""Who may close or delete a business, and when (docs/phase15/13 §4, §5, §10).

* Flow A — ``request_closure``: a business's admin asks (confirmed at once), or
  staff or its reselling partner ask on its behalf (its admin confirms). The
  grace period (``offboarding.grace_days``) starts at confirmation: the company
  is read-only, may cancel, may ask for an export. ``tick`` starts erasure when
  it ends; staff may bring it forward.
* Flow B — ``delete_immediately``: an app admin deletes a test business now,
  with its whole workspace, while ``offboarding.immediate_delete_enabled`` is on.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select

from src.offboarding.models import OPEN_STATES, CompanyOffboarding
from src.offboarding.steps import company_ref

logger = logging.getLogger(__name__)


async def open_offboarding(db: Any, company_id: UUID) -> Optional[CompanyOffboarding]:
    return (await db.execute(select(CompanyOffboarding).where(
        CompanyOffboarding.company_id == company_id, CompanyOffboarding.state.in_(OPEN_STATES)))
        ).scalar_one_or_none()


async def _company(db: Any, company_id: UUID) -> Any:
    from src.auth.models import Company

    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="No such business")
    from src.auth.platform import platform_company_id

    if company.id == await platform_company_id(db):
        raise HTTPException(status_code=409, detail="The platform's own company cannot be closed or deleted")
    return company


async def _setting(db: Any, key: str) -> Any:
    from src.billing.settings_catalogue import value
    return await value(db, key)


async def _notify(company_id: UUID, kind: str, title: str, body: str, key: str) -> None:
    try:
        from src.notifications.service import notify
        await notify(company_id, kind=f"offboarding.{kind}", title=title, body=body, link="/settings",
                     severity="warning", dedupe_key=key)
    except Exception:  # noqa: BLE001
        logger.warning("offboarding notice %s for %s not sent", kind, company_id, exc_info=True)


async def remaining_credit(db: Any, company_id: UUID) -> Dict[str, Any]:
    """What closing forfeits (shown before the business confirms; no refund, D-2)."""
    from src.billing.wallet import WalletService

    balance = await WalletService(db).balance(company_id)
    return {"available": str(balance.get("available")), "currency": balance.get("currency")}


# ── Flow A ──────────────────────────────────────────────────────────────────

async def request_closure(db: Any, company_id: UUID, *, actor: Any, reason: str,
                          export: bool = False) -> CompanyOffboarding:
    """A closure request. The business's own admin confirms by asking; anyone else asks on its behalf."""
    from src.common.admin_audit import record_admin_change

    company = await _company(db, company_id)
    if await open_offboarding(db, company_id) is not None:
        raise HTTPException(status_code=409, detail="This business is already being closed")
    own_admin = str(actor.role) == "tenant_admin" and actor.company_id == company_id
    off = CompanyOffboarding(company_id=company_id, company_ref=company_ref(company_id), company_name=company.name,
                             mode="erasure", state="requested", reason=reason, requested_by=actor.id,
                             requested_by_role=str(actor.role), export_requested=export,
                             previous_status=company.status or "active")
    db.add(off)
    if own_admin:
        await _confirm(db, off, company, actor)
    record_admin_change(db, actor=actor, action="request", object_type="offboarding", object_key=str(company_id),
                        target_company_id=company_id, new_value={"confirmed": own_admin, "export": export},
                        reason=reason)
    await db.commit()
    if not own_admin:
        await _notify(company_id, "requested", "Closing your business was requested",
                      f"{actor.email} asked to close this business ({reason}). Your admin must confirm it in "
                      "Settings before anything happens.", f"offboarding:{off.id}:requested")
    return off


async def _confirm(db: Any, off: CompanyOffboarding, company: Any, actor: Any) -> None:
    days = int(await _setting(db, "offboarding.grace_days"))
    now = datetime.utcnow()
    off.confirmed_by, off.confirmed_at = actor.id, now
    off.grace_until = now + timedelta(days=days)
    company.status = "offboarding_requested"
    from src.billing.suspension import forget
    forget(company.id)
    credit = await remaining_credit(db, company.id)
    await _notify(company.id, "confirmed", "Your business will be closed",
                  f"Its data will be erased on {off.grace_until:%d %b %Y}. Until then it is read-only and you can "
                  f"cancel or download an export. Remaining credit ({credit['currency']} {credit['available']}) "
                  "is not refunded.", f"offboarding:{off.id}:confirmed")


async def confirm_closure(db: Any, company_id: UUID, *, actor: Any) -> CompanyOffboarding:
    if not (str(actor.role) == "tenant_admin" and actor.company_id == company_id):
        raise HTTPException(status_code=403, detail="Only the business's own admin confirms its closure")
    off = await open_offboarding(db, company_id)
    if off is None or off.state != "requested":
        raise HTTPException(status_code=404, detail="Nothing to confirm")
    if off.confirmed_at is None:
        await _confirm(db, off, await _company(db, company_id), actor)
        await db.commit()
    return off


async def cancel_closure(db: Any, company_id: UUID, *, actor: Any) -> CompanyOffboarding:
    from src.common.admin_audit import record_admin_change

    allowed = str(actor.role) == "app_admin" or (str(actor.role) == "tenant_admin" and actor.company_id == company_id)
    if not allowed:
        raise HTTPException(status_code=403, detail="Only the business's admin or HireBuddha may cancel")
    off = await open_offboarding(db, company_id)
    if off is None or off.state != "requested":
        raise HTTPException(status_code=409, detail="Erasure has started: it cannot be cancelled")
    company = await _company(db, company_id)
    company.status = off.previous_status or "active"
    off.state, off.updated_at = "cancelled", datetime.utcnow()
    record_admin_change(db, actor=actor, action="cancel", object_type="offboarding", object_key=str(company_id),
                        target_company_id=company_id, reason="closure cancelled")
    await db.commit()
    from src.billing.suspension import forget
    forget(company_id)
    return off


async def bring_forward(db: Any, offboarding_id: UUID, *, actor: Any) -> CompanyOffboarding:
    from src.common.admin_audit import record_admin_change

    if not await _setting(db, "offboarding.allow_staff_bring_forward"):
        raise HTTPException(status_code=409, detail="Bringing erasure forward is switched off")
    off = await db.get(CompanyOffboarding, offboarding_id)
    if off is None or off.state != "requested":
        raise HTTPException(status_code=409, detail="Only a closure in its grace period can be brought forward")
    if off.confirmed_at is None:
        raise HTTPException(status_code=409, detail="The business's admin has not confirmed the closure")
    off.grace_until = datetime.utcnow()
    record_admin_change(db, actor=actor, action="bring_forward", object_type="offboarding",
                        object_key=str(off.company_id), target_company_id=off.company_id, reason="erase now")
    await db.commit()
    await start(db, off)
    return off


async def start(db: Any, off: CompanyOffboarding) -> None:
    """Grace over: erasure begins (irreversible) — on the provisioning queue."""
    from src.offboarding.runner import enqueue

    off.state = "exporting" if off.export_requested else "erasing"
    off.updated_at = datetime.utcnow()
    await db.commit()
    await enqueue(off.id)


async def tick(db: Any, *, now: Optional[datetime] = None) -> Dict[str, int]:
    """Every 15 minutes: start erasures whose grace has ended; remind 7 days and 1 day before."""
    now = now or datetime.utcnow()
    out = {"started": 0, "reminded": 0}
    due = (await db.execute(select(CompanyOffboarding).where(
        CompanyOffboarding.state == "requested", CompanyOffboarding.confirmed_at.is_not(None),
        CompanyOffboarding.grace_until <= now))).scalars().all()
    for off in due:
        await start(db, off)
        out["started"] += 1
    soon = (await db.execute(select(CompanyOffboarding).where(
        CompanyOffboarding.state == "requested", CompanyOffboarding.confirmed_at.is_not(None),
        CompanyOffboarding.grace_until > now, CompanyOffboarding.grace_until <= now + timedelta(days=7))
    )).scalars().all()
    for off in soon:
        days = 1 if off.grace_until <= now + timedelta(days=1) else 7
        await _notify(off.company_id, f"reminder_{days}", f"Your business is erased in {days} day{'s' * (days > 1)}",
                      "Cancel in Settings to keep it; download your export before then.",
                      f"offboarding:{off.id}:reminder:{days}")
        out["reminded"] += 1
    return out


# ── test businesses and Flow B ──────────────────────────────────────────────

async def real_money(db: Any, company_id: UUID) -> List[str]:
    """Why a business is not a throwaway one: real money moved, or a real partner owns it."""
    from src.auth.models import Company
    from src.billing.billing_models import PaymentTransaction, Subscription
    from src.partners.models import PartnerAssignment

    reasons = []
    paid = (await db.execute(select(func.count()).select_from(PaymentTransaction).where(
        PaymentTransaction.company_id == company_id, PaymentTransaction.status.in_(("paid", "captured", "success",
                                                                                     "completed"))))).scalar()
    if paid:
        reasons.append(f"{paid} paid payments")
    live = (await db.execute(select(func.count()).select_from(Subscription).where(
        Subscription.company_id == company_id, Subscription.status.in_(("active", "past_due"))))).scalar()
    if live:
        reasons.append("a live subscription")
    partners = (await db.execute(select(PartnerAssignment.partner_id).where(
        PartnerAssignment.tenant_id == company_id))).scalars().all()
    for partner_id in set(partners):
        partner = await db.get(Company, partner_id)
        if partner is not None and not partner.is_test:
            reasons.append(f"attributed to the partner {partner.name}, which is not a test partner")
    return reasons


async def set_test(db: Any, company_id: UUID, is_test: bool, *, actor: Any, reason: str) -> Any:
    from src.common.admin_audit import record_admin_change

    company = await _company(db, company_id)
    if is_test and not company.is_test:
        refused = await real_money(db, company_id)
        if refused:
            raise HTTPException(status_code=409, detail="Not a test business: " + "; ".join(refused))
    before = company.is_test
    company.is_test = is_test
    record_admin_change(db, actor=actor, action="set", object_type="company_is_test", object_key=str(company_id),
                        target_company_id=company_id, old_value={"is_test": before}, new_value={"is_test": is_test},
                        reason=reason)
    await db.commit()
    return company


async def immediate_check(db: Any, company_id: UUID, *, include_test_tenants: bool = False) -> Dict[str, Any]:
    """Whether Flow B may delete the business now, and what it would delete (§10's guardrails)."""
    from src.auth.models import Company
    from src.offboarding.purge import row_counts
    from src.offboarding.workspace import workspace_of

    company = await _company(db, company_id)
    refused: List[str] = []
    if not await _setting(db, "offboarding.immediate_delete_enabled"):
        refused.append("immediate delete is switched off (offboarding.immediate_delete_enabled)")
    if not company.is_test:
        refused.append("not marked as a test business")
    refused += await real_money(db, company_id)
    children = (await db.execute(select(Company).where(Company.parent_id == company_id))).scalars().all()
    tenants = [c for c in children if c.type == "TENANT"]
    if tenants and not include_test_tenants:
        refused.append(f"{len(tenants)} businesses sit under it: delete them first, or include its test tenants")
    if include_test_tenants:
        for tenant in tenants:
            if not tenant.is_test:
                refused.append(f"{tenant.name} under it is not a test business")
    ws = await workspace_of(db, company_id)
    return {"company_id": str(company_id), "name": company.name, "allowed": not refused, "refused": refused,
            "workspace": {"tenant_key": ws.tenant_key, "database": ws.db_name,
                          "storage": ws.storage_namespaces, "git_owners": ws.git_owners},
            "rows": await row_counts(await db.connection(), company_id),
            "test_tenants": [{"id": str(t.id), "name": t.name} for t in tenants] if include_test_tenants else []}


async def delete_immediately(db: Any, company_id: UUID, *, actor: Any, reason: str, confirm_name: str,
                             include_test_tenants: bool = False, queue: bool = True) -> List[CompanyOffboarding]:
    """Flow B: every check of §10, then one offboarding per business (its test tenants first), started now
    on the provisioning queue — or not queued (``queue=False``) for a caller that runs them itself."""
    from src.common.admin_audit import record_admin_change
    from src.offboarding.runner import enqueue

    if str(actor.role) != "app_admin":
        raise HTTPException(status_code=403, detail="Only an app admin deletes a business at once")
    check = await immediate_check(db, company_id, include_test_tenants=include_test_tenants)
    if confirm_name.strip() != (check["name"] or ""):
        raise HTTPException(status_code=422, detail="Type the business's exact name to confirm")
    if not check["allowed"]:
        raise HTTPException(status_code=409, detail={"code": "not_deletable", "refused": check["refused"]})
    targets = [UUID(t["id"]) for t in check["test_tenants"]] + [company_id]
    made = []
    for target in targets:
        company = await _company(db, target)
        existing = await open_offboarding(db, target)
        if existing is not None:
            existing.mode, existing.state = "immediate", "erasing"
            off = existing
        else:
            off = CompanyOffboarding(company_id=target, company_ref=company_ref(target), company_name=company.name,
                                     mode="immediate", state="erasing", reason=reason, requested_by=actor.id,
                                     requested_by_role=str(actor.role), confirmed_by=actor.id,
                                     confirmed_at=datetime.utcnow(), previous_status=company.status)
            db.add(off)
        record_admin_change(db, actor=actor, action="delete_immediately", object_type="company",
                            object_key=str(target), target_company_id=target,
                            new_value={"name": company.name, "rows": check["rows"] if target == company_id else None},
                            reason=reason)
        made.append(off)
    await db.commit()
    if queue:
        for off in made:
            await enqueue(off.id)
    return made


def view(off: CompanyOffboarding, log: Optional[List[Any]] = None) -> Dict[str, Any]:
    def iso(v: Any) -> Optional[str]:
        return v.isoformat() if v else None

    out = {"id": str(off.id), "company_id": str(off.company_id), "company_ref": off.company_ref,
           "company_name": off.company_name, "mode": off.mode, "state": off.state, "reason": off.reason,
           "requested_by_role": off.requested_by_role, "confirmed": off.confirmed_at is not None,
           "confirmed_at": iso(off.confirmed_at), "grace_until": iso(off.grace_until),
           "export_requested": off.export_requested, "export_ready": bool(off.export_key),
           "export_expires_at": iso(off.export_expires_at), "started_at": iso(off.started_at),
           "finished_at": iso(off.finished_at), "last_step": off.last_step, "error": off.error,
           "certificate": off.certificate, "created_at": iso(off.created_at)}
    if log is not None:
        out["steps"] = [{"step": r.step, "outcome": r.outcome, "attempt": r.attempt, "error": r.error,
                         "detail": r.detail, "at": iso(r.created_at)} for r in log]
    return out
