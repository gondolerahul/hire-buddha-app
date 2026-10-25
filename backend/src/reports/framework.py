"""The report framework (Phase 15 T9-4; 07 §7.4).

A report is a ``ReportDef`` — id, title, audience (workspaces, roles, staff
functions, partner types), an optional plan entitlement, its filters — and a
builder ``async (ctx) -> Report``. The ``Context`` gives the builder the
viewer's scope (``companies``: None for all), the period, the filters, and
money helpers that put USD amounts in the viewer's currency (a business's own
currency; a partner's; staff's display currency). Columns and tiles marked
``cost`` are removed for anyone but staff (the money view, 06 §5.2).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Mapping, Optional, Sequence
from uuid import UUID

from fastapi import HTTPException

logger = logging.getLogger(__name__)

STAFF = ("app_admin", "app_user")
WORKSPACE = {"app_admin": "console", "app_user": "console", "partner_admin": "partner", "partner_user": "partner",
             "tenant_admin": "business", "tenant_user": "business"}


@dataclass
class Column:
    key: str
    label: str
    kind: str = "text"          # text | money | number | percent | date | link
    cost: bool = False          # staff only


@dataclass
class Tile:
    label: str
    value: Any
    kind: str = "number"        # number | money | percent | text
    hint: Optional[str] = None
    cost: bool = False
    tone: str = "neutral"


@dataclass
class Chart:
    type: str                   # bar | stacked | line | pie
    x: str
    series: List[Dict[str, str]]  # [{key, label}]
    data: List[Dict[str, Any]]
    cost_keys: Sequence[str] = ()


@dataclass
class Report:
    tiles: List[Tile] = field(default_factory=list)
    chart: Optional[Chart] = None
    columns: List[Column] = field(default_factory=list)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    drill: Optional[Dict[str, str]] = None      # {column: route template with {key}}
    notes: List[str] = field(default_factory=list)


@dataclass
class Filter:
    key: str
    label: str
    kind: str = "text"          # text | choice | company
    choices: Sequence[str] = ()
    labels: Mapping[str, str] = field(default_factory=dict)   # a choice's name on screen (the key if none)


@dataclass
class ReportDef:
    id: str
    title: str
    description: str
    workspaces: Sequence[str]
    builder: Callable[["Context"], Awaitable[Report]]
    roles: Optional[Sequence[str]] = None
    staff_functions: Optional[Sequence[str]] = None
    partner_types: Optional[Sequence[str]] = None
    entitlement: Optional[str] = None
    filters: Sequence[Filter] = ()
    group: str = "General"
    period: bool = True


@dataclass
class Context:
    db: Any                                    # the control session
    user: Any
    workspace: str
    companies: Optional[List[UUID]]            # None: every company (staff)
    start: date
    end: date                                  # exclusive
    filters: Dict[str, str]
    currency: str
    rate: Any                                  # USD → currency
    partner_id: Optional[UUID] = None
    staff: bool = False

    @property
    def company_id(self) -> Optional[UUID]:
        """The one company of a business viewer (or a staff filter)."""
        return self.companies[0] if self.companies and len(self.companies) == 1 else None

    @property
    def start_dt(self) -> datetime:
        return datetime.combine(self.start, datetime.min.time())

    @property
    def end_dt(self) -> datetime:
        return datetime.combine(self.end, datetime.min.time())

    def money(self, usd: Any) -> Decimal:
        """USD in the viewer's currency (for display; exact)."""
        from src.billing.currency import to_ccy
        return to_ccy(Decimal(str(usd or 0)), self.rate)

    def scoped(self, column: Any) -> Any:
        """A WHERE clause limiting ``column`` (a company id) to the scope, or True for everyone."""
        from sqlalchemy import true
        return true() if self.companies is None else column.in_(self.companies)

    async def tenant_rows(self, query: Any) -> List[Any]:
        """``query``'s rows from the tenant databases in scope (one shared database in single mode)."""
        from src.common.tenancy.session import is_split, tenant_scopes, tenant_session

        if not is_split():
            from src.common.tenancy.session import control_session
            async with control_session() as session:
                return list((await session.execute(query)).all())
        scopes = self.companies if self.companies is not None else await tenant_scopes()
        rows: List[Any] = []
        for company_id in scopes:
            try:
                async with tenant_session(company_id) as session:
                    rows.extend((await session.execute(query)).all())
            except Exception as exc:  # noqa: BLE001 - one tenant must not fail the report
                logger.warning("report: tenant %s left out: %s", company_id, exc)
        return rows


REGISTRY: Dict[str, ReportDef] = {}


def report(**kwargs: Any) -> Callable[[Callable[[Context], Awaitable[Report]]], Callable[[Context], Awaitable[Report]]]:
    """Register a builder: ``@report(id="R-A02", title=…, workspaces=("console",), …)``."""
    def wrap(builder: Callable[[Context], Awaitable[Report]]) -> Callable[[Context], Awaitable[Report]]:
        definition = ReportDef(builder=builder, **kwargs)
        REGISTRY[definition.id] = definition
        return builder
    return wrap


def load() -> Dict[str, ReportDef]:
    from src.reports import business, console, partner  # noqa: F401 - registers the builders
    return REGISTRY


def may_see(definition: ReportDef, user: Any, partner_type: Optional[str]) -> bool:
    role = str(user.role)
    if WORKSPACE.get(role) not in definition.workspaces:
        return False
    if definition.roles and role not in definition.roles:
        return False
    if role == "app_user" and definition.staff_functions:
        mine = set(getattr(user, "staff_functions", None) or [])
        if not mine & set(definition.staff_functions):
            return False
    if definition.partner_types and WORKSPACE.get(role) == "partner":
        if (partner_type or "GOLD") not in definition.partner_types:
            return False
    return True


def period_of(period: Optional[str], start: Optional[date], end: Optional[date]) -> tuple[date, date]:
    """``period``: ``YYYY-MM`` (a month), ``30d`` / ``90d`` / ``12m`` (rolling), or explicit from/to."""
    today = datetime.utcnow().date()
    if start and end:
        return start, end
    if period and len(period) == 7 and period[4] == "-":
        first = date(int(period[:4]), int(period[5:]), 1)
        return first, (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    if period and period.endswith("d") and period[:-1].isdigit():
        return today - timedelta(days=int(period[:-1])), today + timedelta(days=1)
    if period and period.endswith("m") and period[:-1].isdigit():
        months = int(period[:-1])
        index = today.year * 12 + today.month - 1 - (months - 1)
        return date(index // 12, index % 12 + 1, 1), today + timedelta(days=1)
    first = today.replace(day=1)
    return first, today + timedelta(days=1)


async def scope_for(db: Any, user: Any, company_filter: Optional[UUID]) -> tuple[Optional[List[UUID]], Optional[UUID]]:
    """(companies, partner_id): staff everything (or one company), a partner its customers, a business itself."""
    role = str(user.role)
    if role in STAFF:
        return ([company_filter] if company_filter else None), None
    if WORKSPACE.get(role) == "partner":
        from src.partners.scope import tenant_ids
        customers = await tenant_ids(db, user.company_id)
        if company_filter is not None:
            if company_filter not in customers:
                raise HTTPException(status_code=403, detail="Not one of your customers")
            return [company_filter], user.company_id
        return customers, user.company_id
    return [user.company_id], None


async def viewer_currency(db: Any, user: Any) -> str:
    from src.auth.models import Company
    from src.billing.settings_catalogue import value

    if str(user.role) in STAFF:
        return str(await value(db, "billing.display_currency") or "INR")
    company = await db.get(Company, user.company_id)
    return (company.billing_currency if company else None) or "INR"


def strip_cost(payload: Dict[str, Any], staff: bool) -> Dict[str, Any]:
    """Remove cost columns, tiles and series for everyone but staff (06 §5.2)."""
    if staff:
        return payload
    cost_cols = {c["key"] for c in payload["columns"] if c.get("cost")}
    payload["columns"] = [c for c in payload["columns"] if not c.get("cost")]
    payload["rows"] = [{k: v for k, v in r.items() if k not in cost_cols} for r in payload["rows"]]
    payload["tiles"] = [t for t in payload["tiles"] if not t.get("cost")]
    chart = payload.get("chart")
    if chart and chart.get("cost_keys"):
        keys = set(chart["cost_keys"])
        chart["series"] = [s for s in chart["series"] if s["key"] not in keys]
        chart["data"] = [{k: v for k, v in d.items() if k not in keys} for d in chart["data"]]
    if chart is not None:
        chart.pop("cost_keys", None)
    return payload


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value.quantize(Decimal("0.01"))) if abs(value) >= 1 or value == 0 else str(value.normalize())
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def to_payload(definition: ReportDef, ctx: Context, built: Report) -> Dict[str, Any]:
    payload = {
        "id": definition.id, "title": definition.title, "description": definition.description,
        "currency": ctx.currency, "as_of": datetime.utcnow().isoformat(),
        "period": {"from": ctx.start.isoformat(), "to": (ctx.end - timedelta(days=1)).isoformat()} if definition.period else None,
        "filters": [{"key": f.key, "label": f.label, "kind": f.kind, "choices": list(f.choices),
                     "choice_labels": {c: f.labels.get(c, c) for c in f.choices}} for f in definition.filters],
        "tiles": [{"label": t.label, "value": jsonable(t.value), "kind": t.kind, "hint": t.hint, "cost": t.cost,
                   "tone": t.tone} for t in built.tiles],
        "chart": None if built.chart is None else {
            "type": built.chart.type, "x": built.chart.x, "series": built.chart.series,
            "data": [{k: jsonable(v) for k, v in d.items()} for d in built.chart.data],
            "cost_keys": list(built.chart.cost_keys)},
        "columns": [{"key": c.key, "label": c.label, "kind": c.kind, "cost": c.cost} for c in built.columns],
        "rows": [{k: jsonable(v) for k, v in r.items()} for r in built.rows],
        "drill": built.drill, "notes": built.notes,
    }
    return strip_cost(payload, ctx.staff)


# ── export ───────────────────────────────────────────────────────────────────

def to_csv(payload: Dict[str, Any]) -> bytes:
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    cols = payload["columns"]
    writer.writerow([c["label"] + (f" ({payload['currency']})" if c["kind"] == "money" else "") for c in cols])
    for row in payload["rows"]:
        writer.writerow([row.get(c["key"], "") for c in cols])
    return buffer.getvalue().encode("utf-8-sig")


def to_xlsx(payload: Dict[str, Any]) -> bytes:
    import io

    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = payload["id"][:31]
    sheet.append([payload["title"], f"{payload['currency']}", payload["as_of"][:19]])
    for tile in payload["tiles"]:
        sheet.append([tile["label"], tile["value"]])
    sheet.append([])
    cols = payload["columns"]
    sheet.append([c["label"] for c in cols])
    for row in payload["rows"]:
        values = []
        for c in cols:
            v = row.get(c["key"])
            if c["kind"] in ("money", "number", "percent") and v not in (None, ""):
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    pass
            values.append(v)
        sheet.append(values)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def to_pdf(payload: Dict[str, Any]) -> bytes:
    from src.billing.pdf import Document

    doc = Document(payload["title"])
    page = doc.page()
    page.text(50, 800, payload["title"], size=15, bold=True)
    period = payload.get("period") or {}
    page.text(50, 782, f"{period.get('from', '')} – {period.get('to', '')} · {payload['currency']} · as of "
                       f"{payload['as_of'][:16]}", size=9)
    y = 760
    for tile in payload["tiles"][:8]:
        page.text(50, y, f"{tile['label']}: {tile['value']}", size=9)
        y -= 13
    cols = payload["columns"][:6]
    width = 495 / max(len(cols), 1)
    y -= 8
    for i, c in enumerate(cols):
        page.text(50 + i * width, y, str(c["label"])[:22], size=8, bold=True)
    y -= 12
    for row in payload["rows"]:
        if y < 50:
            page = doc.page()
            y = 800
        for i, c in enumerate(cols):
            page.text(50 + i * width, y, str(row.get(c["key"], ""))[:26], size=8)
        y -= 11
    return doc.to_bytes()


def chunks(items: Iterable[Any], size: int) -> Iterable[List[Any]]:
    batch: List[Any] = []
    for item in items:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch
