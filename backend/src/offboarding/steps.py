"""The control-side steps of erasing a business (docs/phase15/13 §6 steps 1–4, 12; §10 for a test business).

Each step takes the open control session, the offboarding and the business's
workspace, does its work idempotently and returns what it did; the runner
(``src.offboarding.runner``) logs and commits.
"""
from __future__ import annotations

import io
import json
import logging
import uuid
import zipfile
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy import select, text, update

from src.offboarding.models import CompanyOffboarding
from src.offboarding.workspace import Workspace

logger = logging.getLogger(__name__)

# The books a business leaves behind (§8): kept for tax and accounts, its personal details stripped.
RETAINED_TABLES = frozenset({
    "companies", "invoices", "credit_notes", "payment_transactions", "refunds", "wallet_lots", "wallet_entries",
    "credit_wallets", "subscriptions", "one_time_charges", "partner_ledger", "partner_statements",
    "tenant_directory", "company_offboardings", "offboarding_step_log",
})
# Contact details a payment's metadata may carry; the gateway's ids stay for reconciliation.
PERSONAL_METADATA_KEYS = ("email", "contact", "phone", "name", "customer", "notes", "address", "user_email")
RETAINED_NAMESPACE = "retained"
# Columns that name a company with no foreign key, so the purge walk cannot follow them (the
# inventory census, tests/unit/test_offboarding_inventory.py, lists them).
KEYLESS_REFERENCES = (("partner_ledger", ("tenant_id", "origin_partner_id")),
                      ("partner_access_events", ("partner_id", "tenant_id")))


def company_ref(company_id: UUID) -> str:
    """The reference a business is known by once its name is gone (certificates, the books)."""
    return f"B-{uuid.UUID(str(company_id)).hex[:8]}"


# ── 1 quiesced ──────────────────────────────────────────────────────────────

async def quiesced(db: Any, off: CompanyOffboarding, ws: Workspace) -> Dict[str, Any]:
    """Nothing new starts and nothing runs: the company read-only, automation paused, apps stopped,
    keys and webhooks off, partner grants revoked, everyone signed out."""
    from src.auth.models import Company, User
    from src.billing.enforcement_hooks import pause_automation, stop_apps_for_balance
    from src.partners.models import PartnerAccessGrant

    company = await db.get(Company, off.company_id)
    company.status = "erasing"
    await db.execute(update(User).where(User.company_id == off.company_id)
                     .values(token_version=User.token_version + 1, is_active=False))
    revoked = (await db.execute(update(PartnerAccessGrant).where(
        PartnerAccessGrant.tenant_id == off.company_id, PartnerAccessGrant.status != "revoked")
        .values(status="revoked", revoked_at=datetime.utcnow()))).rowcount
    keys = await _disable(db, "api_keys", off.company_id)
    hooks = await _disable(db, "webhook_endpoints", off.company_id)
    await db.commit()
    paused = await _safely(pause_automation, off.company_id)
    stopped = await _safely(stop_apps_for_balance, off.company_id)
    from src.billing.suspension import forget
    forget(off.company_id)
    return {"grants_revoked": revoked or 0, "api_keys_disabled": keys, "webhooks_disabled": hooks,
            "automation_paused": paused, "apps_stopped": stopped}


async def _disable(db: Any, table: str, company_id: UUID) -> int:
    columns = set((await db.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
        "AND table_name = :t"), {"t": table})).scalars().all())
    for flag, value in (("is_active", "false"), ("active", "false"), ("enabled", "false")):
        if flag in columns:
            return (await db.execute(text(f"UPDATE {table} SET {flag} = {value} WHERE company_id = :c"),
                                     {"c": company_id})).rowcount or 0
    return 0


async def _safely(fn: Any, *args: Any) -> Any:
    try:
        return await fn(*args)
    except Exception as exc:  # noqa: BLE001 - the workspace steps remove what these would stop
        logger.warning("offboarding: %s skipped: %s", getattr(fn, "__name__", fn), exc)
        return f"skipped: {exc}"[:200]


# ── 2 billing_closed ────────────────────────────────────────────────────────

async def billing_closed(db: Any, off: CompanyOffboarding, ws: Workspace) -> Dict[str, Any]:
    """Subscriptions cancelled now, usage settled, holds released, numbers released, open charges
    cancelled, and every remaining credit lot forfeited — no refund (D-2)."""
    from src.billing.billing_models import CreditHold, Subscription, WalletLot
    from src.billing.rentals import end_rental
    from src.billing.settlement import settle_unsettled
    from src.billing.wallet import WalletService
    from src.voice.phone_pool_models import PhoneNumber

    out: Dict[str, Any] = {}
    subs = (await db.execute(select(Subscription).where(
        Subscription.company_id == off.company_id, Subscription.status.in_(("active", "past_due", "created",
                                                                           "authenticated", "pending")))
    )).scalars().all()
    if subs:
        from src.billing.gateways import get_gateway
        from src.billing.subscriptions import cancel

        gateway = await get_gateway(db)
        for sub in subs:
            await cancel(db, gateway, sub, at_cycle_end=False)
    out["subscriptions_cancelled"] = len(subs)
    settled = await settle_unsettled(db, off.company_id)
    out["usage_settled_rows"] = len(settled.rows)
    holds = (await db.execute(update(CreditHold).where(CreditHold.company_id == off.company_id,
                                                       CreditHold.released_at.is_(None))
                              .values(released_at=datetime.utcnow()))).rowcount
    out["holds_released"] = holds or 0
    numbers = (await db.execute(select(PhoneNumber).where(PhoneNumber.company_id == off.company_id))
               ).scalars().all()
    for number in numbers:
        await end_rental(db, number)
        number.company_id, number.agent_id, number.status = None, None, "available"
    out["numbers_released"] = len(numbers)
    charges = (await db.execute(text(
        "UPDATE one_time_charges SET status = 'cancelled' WHERE tenant_id = :c AND status IN ('draft', 'sent')"),
        {"c": off.company_id})).rowcount
    out["charges_cancelled"] = charges or 0
    wallets = WalletService(db)
    lots = (await db.execute(select(WalletLot).where(WalletLot.company_id == off.company_id,
                                                     WalletLot.remaining > 0))).scalars().all()
    forfeited = Decimal(0)
    if lots:
        change = await wallets.expire_lots(off.company_id, lots, reason="offboarding")
        forfeited = change.amount
    out["credit_forfeited"] = str(forfeited)
    await db.commit()
    return out


# ── 3 records_retained (Flow A) ─────────────────────────────────────────────

async def records_retained(db: Any, off: CompanyOffboarding, ws: Workspace) -> Dict[str, Any]:
    """Invoice and credit-note PDFs and a monthly billing summary copied to ``retained/<ref>/``
    before anything is deleted; each copy read back and checked."""
    import hashlib

    from src.billing.billing_models import BillingLine
    from src.common.platform.storage import get_storage
    from sqlalchemy import func

    storage = get_storage()
    ref = off.company_ref
    copied = []
    for namespace in ws.storage_namespaces:
        for key in await storage.list(f"{namespace}/"):
            path = key.split("/", 1)[1]
            if not (path.startswith("invoices/") or path.startswith("credit-notes/") or path.startswith("credit_notes/")):
                continue
            body = await storage.get(key)
            target = f"{RETAINED_NAMESPACE}/{ref}/{path}"
            await storage.put(target, body, content_type="application/pdf")
            if hashlib.sha256(await storage.get(target)).hexdigest() != hashlib.sha256(body).hexdigest():
                raise RuntimeError(f"retained copy of {key} does not match")
            copied.append(path)
    month = func.date_trunc("month", BillingLine.period_day)
    rows = (await db.execute(select(month, BillingLine.category, BillingLine.currency,
                                    func.sum(BillingLine.cost_usd), func.sum(BillingLine.billed_usd),
                                    func.sum(BillingLine.billed_ccy))
                             .where(BillingLine.company_id == off.company_id)
                             .group_by(month, BillingLine.category, BillingLine.currency).order_by(month))).all()
    summary = [{"month": f"{m:%Y-%m}", "category": c, "currency": ccy, "cost_usd": str(cost),
                "billed_usd": str(billed), "billed_ccy": str(billed_ccy)}
               for m, c, ccy, cost, billed, billed_ccy in rows]
    await storage.put(f"{RETAINED_NAMESPACE}/{ref}/billing-summary.json",
                      json.dumps({"company_ref": ref, "months": summary}, indent=1).encode(),
                      content_type="application/json")
    return {"documents": len(copied), "billing_summary_rows": len(summary), "at": f"{RETAINED_NAMESPACE}/{ref}/"}


# ── 4 exported (Flow A, on request) ─────────────────────────────────────────

async def exported(db: Any, off: CompanyOffboarding, ws: Workspace) -> Dict[str, Any]:
    """The business's files and its records as JSON in one ZIP, kept apart from its workspace for
    ``offboarding.export_retention_days`` (§7)."""
    if not off.export_requested:
        return {"skipped": "no export asked"}
    if off.export_key:
        return {"export": off.export_key, "made": False}
    from src.billing.settings_catalogue import value
    from src.common.platform.storage import get_storage

    storage = get_storage()
    buffer = io.BytesIO()
    manifest: Dict[str, Any] = {"company_ref": off.company_ref, "made_at": datetime.utcnow().isoformat() + "Z",
                                "files": 0, "tables": {}}
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for namespace in ws.storage_namespaces:
            for key in await storage.list(f"{namespace}/"):
                archive.writestr(f"files/{key}", await storage.get(key))
                manifest["files"] += 1
        for table, rows in (await _records(ws)).items():
            archive.writestr(f"records/{table}.json", json.dumps(rows, default=str, indent=1))
            manifest["tables"][table] = len(rows)
        archive.writestr("manifest.json", json.dumps(manifest, indent=1))
    key = f"{RETAINED_NAMESPACE}/exports/{off.id}.zip"
    await storage.put(key, buffer.getvalue(), content_type="application/zip")
    off.export_key = key
    off.export_expires_at = datetime.utcnow() + timedelta(days=int(await value(db, "offboarding.export_retention_days")))
    await db.commit()
    return {"export": key, "files": manifest["files"], "tables": manifest["tables"]}


EXPORT_TABLES = ("hierarchical_entities", "campaigns", "contact_uploads", "documents", "voice_sessions",
                 "call_logs", "triggers")


async def _records(ws: Workspace) -> Dict[str, List[dict]]:
    """The business's own data, table by table, from its database (the shared one in single mode)."""
    from src.common.tenancy.session import tenant_session

    out: Dict[str, List[dict]] = {}
    async with tenant_session(ws.company_id) as tdb:
        tables = set((await tdb.execute(text(
            "SELECT table_name FROM information_schema.columns WHERE column_name = 'company_id' "
            "AND table_schema = ANY(current_schemas(false))"))).scalars().all())
        for table in EXPORT_TABLES:
            if table in tables:
                rows = (await tdb.execute(text(f"SELECT * FROM {table} WHERE company_id = :c"),
                                          {"c": ws.company_id})).mappings().all()
                out[table] = [dict(r) for r in rows]
        if "business" in set((await tdb.execute(text("SELECT nspname FROM pg_namespace"))).scalars().all()):
            for (table,) in (await tdb.execute(text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'business'"))).all():
                rows = (await tdb.execute(text(f'SELECT * FROM business."{table}"'))).mappings().all()
                out[f"business.{table}"] = [dict(r) for r in rows]
    return out


# ── 12 control_erased (Flow A) / control_purged (Flow B) ────────────────────

async def control_erased(db: Any, off: CompanyOffboarding, ws: Workspace) -> Dict[str, Any]:
    """Everything that refers to the business is deleted except its books; the books lose its
    personal details; the company row keeps only a reference (§8)."""
    from src.auth.models import Company
    from src.offboarding.purge import erase_company_rows

    ref = off.company_ref
    company = await db.get(Company, off.company_id)
    old_name = company.name if company else None
    conn = await db.connection()
    removed = await erase_company_rows(conn, off.company_id, keep=RETAINED_TABLES)
    events = (await db.execute(text("DELETE FROM partner_access_events WHERE tenant_id = :c OR partner_id = :c"),
                               {"c": off.company_id})).rowcount
    if events:
        removed["partner_access_events"] = events
    await db.execute(text(
        "UPDATE payment_transactions SET transaction_metadata = transaction_metadata - CAST(:keys AS text[]) "
        "WHERE company_id = :c AND transaction_metadata IS NOT NULL"),
        {"keys": list(PERSONAL_METADATA_KEYS), "c": off.company_id})
    if old_name:
        await db.execute(text("UPDATE partner_ledger SET reason = replace(reason, :name, :ref) "
                              "WHERE tenant_id = :c AND reason IS NOT NULL"),
                         {"name": old_name, "ref": f"former customer {ref}", "c": off.company_id})
    await db.execute(text(
        "UPDATE admin_audit_log SET old_value = NULL, new_value = NULL "
        "WHERE target_company_id = :c OR acting_company_id = :c"), {"c": off.company_id})
    await db.execute(text("UPDATE tenant_directory SET status = 'retired', slug = :slug WHERE company_id = :c"),
                     {"slug": ref.lower(), "c": off.company_id})
    if company is not None:
        company.name = f"Erased business {ref}"
        company.logo_url = company.legal_name = company.gstin = None
        company.billing_address = company.onboarding_metadata = None
        company.status = "erased"
    off.company_name = None
    await db.commit()
    await _forget_redis(off.company_id)
    return {"rows_removed": removed, "company": f"Erased business {ref}"}


async def control_purged(db: Any, off: CompanyOffboarding, ws: Workspace) -> Dict[str, Any]:
    """A test business: the company and every row that refers to it, its books and audit rows
    included (§10). The offboarding record, which names it by id only, stays as the proof."""
    from src.offboarding.purge import purge_companies, row_counts

    conn = await db.connection()
    before = await row_counts(conn, off.company_id)
    await db.execute(text("DELETE FROM admin_audit_log WHERE (target_company_id = :c OR acting_company_id = :c) "
                          "AND NOT (object_type = 'company' AND action = 'delete_immediately')"),
                     {"c": off.company_id})
    for table, columns in KEYLESS_REFERENCES:
        where = " OR ".join(f"{c} = :c" for c in columns)
        await db.execute(text(f"DELETE FROM {table} WHERE {where}"), {"c": off.company_id})
    await purge_companies(conn, [off.company_id])
    await db.commit()
    await _forget_redis(off.company_id)
    return {"rows_removed": before}


async def _forget_redis(company_id: UUID) -> int:
    try:
        from src.common.redis_client import shared_redis

        redis = shared_redis()
        removed = 0
        async for key in redis.scan_iter(match=f"*{company_id}*", count=500):
            await redis.delete(key)
            removed += 1
        return removed
    except Exception as exc:  # noqa: BLE001 - throttles and caches expire by themselves
        logger.warning("offboarding: redis keys of %s not removed: %s", company_id, exc)
        return 0
