"""The erasure certificate (docs/phase15/13 §12): a JSON record and a one-page PDF.

It names the business by its reference only, lists every step with its time
and outcome, what was kept and until when, and the copies that expire by
themselves and the date each is gone.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

# The copies erasure cannot remove at once, and how long each lives (§9); days.
EXPIRING_COPIES = (
    ("Database point-in-time restore (server-wide)", 7),
    ("Blob soft-deleted copies and versions", 14),
    ("Log Analytics and Application Insights", 30),
    ("Platform-wide weekly database dumps (hb-backup)", 35),
    ("Tenant key, soft-deleted and unusable, in the tenant-keys vault", 90),
)
RETAINED = (
    ("Invoices and credit notes", "GST (CGST Act s.36) and books of account (Companies Act s.128)", 8),
    ("Payments, refunds, wallet lots and ledger entries", "Books of account", 8),
    ("Monthly billing summary", "Revenue reporting and disputes", 8),
    ("Partner ledger entries naming the business as a reference", "The partner's books, TDS", 8),
    ("The anonymised company row and this certificate", "Proof of erasure", 8),
)


def _fy_end(at: datetime) -> datetime:
    """31 March of the financial year ``at`` falls in."""
    return datetime(at.year + (1 if at.month > 3 else 0), 3, 31)


def build(off: Any, log: List[Any]) -> Tuple[Dict[str, Any], bytes]:
    from src.billing.pdf import Document

    now = datetime.utcnow()
    immediate = off.mode == "immediate"
    steps = [{"step": r.step, "outcome": r.outcome, "at": r.created_at.isoformat() if r.created_at else None,
              "error": r.error} for r in log]
    kept = [] if immediate else [
        {"what": what, "basis": basis,
         "until": (_fy_end(now).replace(year=_fy_end(now).year + years)).date().isoformat()}
        for what, basis, years in RETAINED]
    expiring = [{"copy": what, "gone_by": (now + timedelta(days=days)).date().isoformat()}
                for what, days in EXPIRING_COPIES]
    certificate = {
        "business": off.company_ref,
        "kind": "test business — immediate delete" if immediate else "erasure",
        "reason": off.reason,
        "requested_at": off.created_at.isoformat() if off.created_at else None,
        "confirmed_at": off.confirmed_at.isoformat() if off.confirmed_at else None,
        "started_at": off.started_at.isoformat() if off.started_at else None,
        "finished_at": now.isoformat(),
        "steps": steps,
        "kept": kept,
        "expiring_copies": expiring,
        "rows_before": (off.inventory or {}).get("control_rows"),
    }
    doc = Document(title=f"Erasure certificate {off.company_ref}")
    page = doc.page()
    y = 800
    page.text(50, y, "HireBuddha — certificate of erasure", size=16, bold=True)
    y -= 26
    for label, value in (("Business", off.company_ref), ("Kind", certificate["kind"]),
                         ("Requested", certificate["requested_at"] or "—"),
                         ("Erasure finished", now.strftime("%Y-%m-%d %H:%M UTC"))):
        page.text(50, y, f"{label}:", bold=True)
        page.text(170, y, str(value)[:80])
        y -= 16
    y -= 8
    page.text(50, y, "Steps", size=12, bold=True)
    y -= 16
    for s in steps:
        page.text(60, y, f"{s['step']}", size=9)
        page.text(220, y, f"{s['outcome']}", size=9)
        page.text(300, y, (s["at"] or "")[:19].replace("T", " "), size=9)
        y -= 12
    y -= 8
    page.text(50, y, "Kept, and why" if kept else "Kept: nothing (a test business)", size=12, bold=True)
    y -= 16
    for k in kept:
        page.text(60, y, f"{k['what']} — until {k['until']}", size=9)
        y -= 12
        page.text(70, y, k["basis"], size=8)
        y -= 12
    y -= 8
    page.text(50, y, "Copies that expire by themselves", size=12, bold=True)
    y -= 16
    for e in expiring:
        page.text(60, y, f"{e['copy']} — gone by {e['gone_by']}", size=9)
        y -= 12
    return certificate, doc.to_bytes()
