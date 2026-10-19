"""Custom domains for published apps (Phase 14 WS6 6.9, tech spec §11.5).

The owner adds ``crm.acme.com`` to an app; HireBuddha answers with two DNS
records to create — ``CNAME crm.acme.com → <app>-<slug>.<APPS_DOMAIN>`` (an
apex domain, which cannot have a CNAME, uses an ``A`` record to the edge's
static IP, ``APP_EDGE_IP``) and ``TXT _hb-verify.crm.acme.com = <token>``.
:func:`verify` looks both up; once they are right the domain is
``verified``, the published app is re-applied with it among its routes, and
the tenant app edge obtains a certificate at the first request — after
asking :func:`may_serve` (the edge's ``ask`` endpoint) whether the name is
one of ours.

The platform's own names (published and preview hostnames) live in the same
table, ``kind`` ``platform`` / ``preview``, so the edge asks one place.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional

from sqlalchemy import select

from src.apps.models import CustomDomain

Resolver = Callable[[str, str], Awaitable[List[str]]]
_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
RESERVED = ("localhost", "local", "internal", "test", "invalid", "example")


def domain_view(row: CustomDomain) -> Dict[str, Any]:
    from src.common.config import settings

    records = []
    if row.kind == "custom":
        records = [{"type": "CNAME", "name": row.hostname, "value": row.target}]
        if settings.APP_EDGE_IP:
            records.append({"type": "A", "name": row.hostname, "value": settings.APP_EDGE_IP,
                            "note": "instead of the CNAME, for a domain's apex"})
        records.append({"type": "TXT", "name": f"_hb-verify.{row.hostname}", "value": row.verification_token})
    return {"hostname": row.hostname, "kind": row.kind, "status": row.status, "cert_status": row.cert_status,
            "app_id": str(row.app_id), "dns_records": records, "last_error": row.last_error,
            "last_checked_at": row.last_checked_at.isoformat() + "Z" if row.last_checked_at else None,
            "verified_at": row.verified_at.isoformat() + "Z" if row.verified_at else None}


def normalize(hostname: str) -> str:
    """A custom hostname as stored: lower case, no trailing dot; refused when it is not one."""
    from src.common.config import settings

    name = (hostname or "").strip().lower().rstrip(".")
    try:
        name = name.encode("idna").decode("ascii")
    except UnicodeError:
        raise ValueError(f"{hostname!r} is not a host name") from None
    labels = name.split(".")
    if len(name) > 253 or len(labels) < 2 or not all(_LABEL.match(label) for label in labels):
        raise ValueError(f"{hostname!r} is not a host name")
    if labels[-1].isdigit():
        raise ValueError("an IP address is not a domain")
    if labels[-1] in RESERVED:
        raise ValueError(f"{name} cannot be served publicly")
    apps_domain = settings.APPS_DOMAIN.lower()
    if name == apps_domain or name.endswith("." + apps_domain):
        raise ValueError(f"names under {apps_domain} are HireBuddha's own")
    return name


async def dns_lookup(name: str, record_type: str) -> List[str]:
    """Records of a name (``TXT``, ``CNAME``, ``A``) from public DNS; none when it has none."""
    import dns.asyncresolver
    import dns.exception
    import dns.resolver

    try:
        answer = await dns.asyncresolver.resolve(name, record_type, lifetime=10)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers, dns.exception.Timeout):
        return []
    out = []
    for item in answer:
        if record_type == "TXT":
            out.append(b"".join(item.strings).decode(errors="replace"))
        else:
            out.append(item.to_text().rstrip(".").lower())
    return out


async def add(company_id: Any, app_id: Any, hostname: str) -> Dict[str, Any]:
    from src.apps import service as apps
    from src.apps.db import app_session
    from src.apps.models import App
    from src.common.tenancy.directory import directory
    from src.common.tenancy.session import control_session

    try:
        name = normalize(hostname)
    except ValueError as error:
        raise apps.AppProblem(str(error), 422) from None
    async with app_session(company_id) as db:
        app = await db.get(App, apps._uuid(app_id))  # noqa: SLF001
        if app is None or app.company_id != apps._uuid(company_id) or app.status == "archived":  # noqa: SLF001
            raise apps.AppProblem("no such app", 404)
        target = apps.hostname(app.name, (app.settings or {}).get("hostname_slug") or "app")
    location = await directory.get(company_id)
    async with control_session() as cdb:
        existing = await cdb.get(CustomDomain, name)
        if existing is not None and existing.status != "removed":
            if existing.company_id == app.company_id and existing.app_id == app.id:
                return domain_view(existing)
            raise apps.AppProblem(f"{name} is already used by another app")
        row = existing or CustomDomain(hostname=name, company_id=app.company_id, app_id=app.id)
        row.company_id, row.app_id, row.tenant_key, row.kind = app.company_id, app.id, location.key, "custom"
        row.status, row.cert_status, row.target = "pending", "none", target
        row.verification_token = "hb-verify-" + secrets.token_urlsafe(18)
        row.last_error, row.verified_at, row.created_at = None, None, datetime.utcnow()
        if existing is None:
            cdb.add(row)
        await cdb.commit()
        return domain_view(row)


async def verify(company_id: Any, app_id: Any, hostname: str, *, resolver: Optional[Resolver] = None) -> Dict[str, Any]:
    """Check the domain's DNS records; once right, it is served (the published app is re-applied)."""
    from src.apps import service as apps
    from src.common.config import settings
    from src.common.tenancy.session import control_session

    lookup = resolver or dns_lookup
    try:
        name = normalize(hostname)
    except ValueError as error:
        raise apps.AppProblem(str(error), 422) from None
    async with control_session() as cdb:
        row = await cdb.get(CustomDomain, name)
        if row is None or row.kind != "custom" or row.status == "removed" or \
                row.company_id != apps._uuid(company_id) or row.app_id != apps._uuid(app_id):  # noqa: SLF001
            raise apps.AppProblem("no such domain on this app", 404)
        token, target = row.verification_token, row.target
    problems = []
    txt = await lookup(f"_hb-verify.{name}", "TXT")
    if not any(token in value for value in txt):
        problems.append(f"TXT _hb-verify.{name} does not hold {token}")
    cname = await lookup(name, "CNAME")
    pointed = target in cname
    if not pointed and settings.APP_EDGE_IP:
        pointed = settings.APP_EDGE_IP in await lookup(name, "A")
    if not pointed:
        problems.append(f"{name} does not point at {target}" + (f" (or A {settings.APP_EDGE_IP})"
                                                                if settings.APP_EDGE_IP else ""))
    async with control_session() as cdb:
        row = await cdb.get(CustomDomain, name)
        row.last_checked_at = datetime.utcnow()
        if problems:
            row.status = "pending" if row.status != "verified" else "failed"
            row.last_error = "; ".join(problems)
        else:
            row.status, row.last_error, row.verified_at, row.cert_status = "verified", None, datetime.utcnow(), "pending"
        await cdb.commit()
        view = domain_view(row)
    if not problems:
        try:
            await apps._reapply(company_id, app_id)  # noqa: SLF001 - the route is added now
        except apps.AppProblem:
            pass  # not published yet: the domain is served from the first publish
    return view


async def remove(company_id: Any, app_id: Any, hostname: str) -> None:
    from src.apps import service as apps
    from src.common.tenancy.session import control_session

    async with control_session() as cdb:
        row = await cdb.get(CustomDomain, (hostname or "").strip().lower())
        if row is None or row.kind != "custom" or row.company_id != apps._uuid(company_id) or \
                row.app_id != apps._uuid(app_id):  # noqa: SLF001
            raise apps.AppProblem("no such domain on this app", 404)
        await cdb.delete(row)
        await cdb.commit()
    try:
        await apps._reapply(company_id, app_id)  # noqa: SLF001
    except apps.AppProblem:
        pass


async def may_serve(hostname: str) -> bool:
    """The edge's ``ask``: may it obtain a certificate for, and serve, this name? Records the first ask."""
    from src.common.tenancy.session import control_session

    name = (hostname or "").strip().lower().rstrip(".")
    async with control_session() as cdb:
        row = await cdb.get(CustomDomain, name)
        if row is None or row.status != "verified":
            return False
        if row.cert_status in ("none", "pending"):
            row.cert_status = "issued"
            await cdb.commit()
    return True


async def list_domains(company_id: Any, app_id: Any) -> List[Dict[str, Any]]:
    from src.apps import service as apps
    from src.common.tenancy.session import control_session

    async with control_session() as cdb:
        rows = (await cdb.execute(select(CustomDomain).where(
            CustomDomain.company_id == apps._uuid(company_id), CustomDomain.app_id == apps._uuid(app_id),  # noqa: SLF001
            CustomDomain.status != "removed").order_by(CustomDomain.kind, CustomDomain.hostname))).scalars().all()
    return [domain_view(r) for r in rows]
