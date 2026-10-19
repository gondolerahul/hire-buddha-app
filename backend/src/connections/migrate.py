"""Credential conversion (Phase 14 WS7 7.2, tech spec §10.7, E09-S09).

    python -m src.connections.migrate [--company ID] [--apply] [--remove-registry-rows]

Moves each business's credentials out of the old tables into its connections:

| From | To |
|------|----|
| ``social_connections`` (facebook, instagram, linkedin, twitter) | ``facebook_pages`` / ``instagram_business`` / ``linkedin_org`` / ``x_account`` connections |
| ``email_connections`` | ``imap_mailbox`` connections |
| the business's own ``integration_registry`` rows (not the platform's) | ``provider_api_key`` connections, read by ``ConfigService`` before the platform's key |
| each Page / account in them | ``external_account_routes`` |

Tokens and passwords are re-sealed under the business's DEK. A social row
whose token can only be refreshed with the business's **own** developer app
(a refresh token and the business's client credentials) becomes
``needs_reconnect`` — HireBuddha's app cannot refresh it (functional spec
§6.5: "ask for a one-time Reconnect"); its owners are notified. Grants: all
agents, as the old rows were usable by every agent. Platforms without a
connector yet (Google Ads, YouTube, TikTok, Reddit) stay in the old table and
are reported.

Idempotent: a row already converted (its id is recorded on the connection as
``settings.converted_from``) is skipped. Nothing is deleted from the old
tables; with ``--remove-registry-rows`` the converted registry rows are
deleted (after which ``REGISTRY_PLATFORM_ONLY`` can be switched on). The
old social / e-mail tables are dropped one release after cutover.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select

logger = logging.getLogger(__name__)

SOCIAL_CONNECTORS = {"facebook": "facebook_pages", "instagram": "instagram_business",
                     "linkedin": "linkedin_org", "twitter": "x_account"}
ROUTE_PROVIDERS = {"facebook_pages": "meta", "instagram_business": "meta", "linkedin_org": "linkedin",
                   "x_account": "x"}


def _report() -> Dict[str, Any]:
    return {"converted": [], "skipped": [], "kept": [], "failed": [], "needs_reconnect": [], "registry_removed": 0}


async def _already(db: Any, company_id: Any, source: str) -> bool:
    from src.connections.models import Connection

    rows = (await db.execute(select(Connection.settings).where(Connection.company_id == company_id))).scalars().all()
    return any((s or {}).get("converted_from") == source for s in rows)


async def _make(db: Any, company_id: Any, *, connector_id: str, name: str, external_id: Optional[str],
                secret: Dict[str, Any], settings: Dict[str, Any], status: str, scopes: List[str],
                expires_at: Any = None, source: str) -> Any:
    from src.connections import service
    from src.connections.models import Connection, ConnectionGrant

    connection = Connection(id=uuid.uuid4(), company_id=company_id, connector_id=connector_id, display_name=name,
                            external_account_id=external_id or None, external_account_name=name,
                            scopes_granted=scopes, status=status, token_expires_at=expires_at,
                            settings={**settings, "converted_from": source},
                            health={"note": "moved from the old credential tables (WS7)"})
    db.add(connection)
    await db.flush()
    db.add(ConnectionGrant(connection_id=connection.id, principal_kind="all_agents", principal_id=None,
                           actions=["*"]))
    await service._store_secret(db, connection, secret)
    await service._audit(db, company_id, connection.id, "connected", actor_kind="system",
                         detail={"converted_from": source})
    return connection


async def convert_company(company_id: Any, *, apply: bool, remove_registry_rows: bool = False) -> Dict[str, Any]:
    from src.ai.email_models import EmailConnection
    from src.ai.social_connection_service import open_oauth_metadata
    from src.ai.social_models import SocialConnection
    from src.common.security import decrypt_api_key
    from src.common.tenancy.session import control_session, tenant_session
    from src.config.models import IntegrationRegistry
    from src.config.registry_secrets import registry_secret
    from src.connections import service

    company_id = uuid.UUID(str(company_id))
    report = _report()
    routes: List[tuple] = []
    async with tenant_session(company_id) as db:
        for row in (await db.execute(select(SocialConnection).where(SocialConnection.company_id == company_id,
                                                                    SocialConnection.is_active.is_(True)))).scalars():
            source = f"social_connections:{row.id}"
            connector = SOCIAL_CONNECTORS.get(row.platform)
            item = {"from": source, "platform": row.platform, "account": row.account_name}
            if connector is None:
                report["kept"].append({**item, "reason": "no connector for this platform yet"})
                continue
            if await _already(db, company_id, source):
                report["skipped"].append(item)
                continue
            try:
                metadata = open_oauth_metadata(row.oauth_metadata)
                own_app = bool(metadata.get("client_id") and metadata.get("client_secret"))
                refresh = decrypt_api_key(row.encrypted_refresh_token) if row.encrypted_refresh_token else None
                status = "needs_reconnect" if (refresh and own_app) else "active"
                external = row.platform_page_id or row.platform_user_id
                settings = {k: v for k, v in metadata.items() if k not in ("client_id", "client_secret")
                            and not str(k).lower().endswith(("secret", "token", "password"))}
                settings.update({"page_id": row.platform_page_id, "user_id": row.platform_user_id})
                if connector == "instagram_business":
                    settings["instagram_account_id"] = row.platform_user_id
                secret = {"access_token": decrypt_api_key(row.encrypted_access_token)}
                if refresh:
                    secret["refresh_token"] = refresh
                if apply:
                    made = await _make(db, company_id, connector_id=connector, name=row.account_name or row.platform,
                                       external_id=external, secret=secret, settings=settings, status=status,
                                       scopes=list(row.scopes or []), expires_at=row.token_expires_at, source=source)
                    if external:
                        routes.append((ROUTE_PROVIDERS[connector], str(external), made.id))
                    item["connection_id"] = str(made.id)
                report["converted"].append({**item, "connector": connector, "status": status})
                if status == "needs_reconnect":
                    report["needs_reconnect"].append(item)
            except Exception as error:  # noqa: BLE001 - this row stays where it was
                report["failed"].append({**item, "error": f"{type(error).__name__}: {error}"[:300]})

        for row in (await db.execute(select(EmailConnection).where(EmailConnection.company_id == company_id,
                                                                   EmailConnection.is_active.is_(True)))).scalars():
            source = f"email_connections:{row.id}"
            item = {"from": source, "platform": "email", "account": row.email_address}
            if await _already(db, company_id, source):
                report["skipped"].append(item)
                continue
            try:
                settings = {"email_address": row.email_address, "imap_host": row.imap_host,
                            "imap_port": row.imap_port, "smtp_host": row.smtp_host, "smtp_port": row.smtp_port,
                            "provider_type": row.provider_type}
                if apply:
                    made = await _make(db, company_id, connector_id="imap_mailbox", name=row.email_address,
                                       external_id=row.email_address,
                                       secret={"password": decrypt_api_key(row.encrypted_app_password)},
                                       settings=settings, status="active", scopes=[], source=source)
                    item["connection_id"] = str(made.id)
                report["converted"].append({**item, "connector": "imap_mailbox", "status": "active"})
            except Exception as error:  # noqa: BLE001
                report["failed"].append({**item, "error": f"{type(error).__name__}: {error}"[:300]})

        converted_registry: List[Any] = []
        async with control_session() as control:
            from src.auth.platform import platform_company_id

            platform = await platform_company_id(control)
            registry_rows = [] if company_id == platform else (await control.execute(select(IntegrationRegistry).where(
                IntegrationRegistry.company_id == company_id))).scalars().all()
            for row in registry_rows:
                source = f"integration_registry:{row.id}"
                item = {"from": source, "platform": row.provider_name, "account": row.service_sku}
                if await _already(db, company_id, source):
                    report["skipped"].append(item)
                    converted_registry.append(row.id)
                    continue
                try:
                    key = await registry_secret(row)
                    if not key:
                        report["kept"].append({**item, "reason": "no key stored"})
                        continue
                    settings = {"provider": row.provider_name, "service_sku": row.service_sku,
                                "model_name": row.model_name, "service_category": row.service_category,
                                "metadata": {k: v for k, v in (row.service_metadata or {}).items()
                                             if not str(k).lower().endswith(("secret", "token", "password", "_encrypted"))}}
                    if apply:
                        made = await _make(db, company_id, connector_id="provider_api_key",
                                           name=f"{row.provider_name} ({row.service_sku})", external_id=None,
                                           secret={"api_key": key}, settings=settings, status="active", scopes=[],
                                           source=source)
                        item["connection_id"] = str(made.id)
                        converted_registry.append(row.id)
                    report["converted"].append({**item, "connector": "provider_api_key", "status": "active"})
                except Exception as error:  # noqa: BLE001
                    report["failed"].append({**item, "error": f"{type(error).__name__}: {error}"[:300]})
            if apply:
                await db.commit()
                for provider, external, connection_id in routes:
                    try:
                        await service._claim_route(company_id, provider, external, connection_id)
                    except service.ConnectionProblem:
                        report["failed"].append({"from": f"route:{provider}:{external}",
                                                 "error": "another business already has this account"})
                if remove_registry_rows and converted_registry:
                    for row in registry_rows:
                        if row.id in converted_registry:
                            await control.delete(row)
                    await control.commit()
                    report["registry_removed"] = len(converted_registry)
    if apply and report["needs_reconnect"]:
        from src.notifications.service import notify

        await notify(company_id, kind="connection_needs_reconnect",
                     title=f"{len(report['needs_reconnect'])} connection(s) need a one-time reconnect",
                     body="They used your own developer app. Reconnect them on the Connections screen so "
                          "HireBuddha can keep them working.",
                     dedupe_key=f"connections:converted:{company_id}", link="/connections")
    return report


async def companies_with_credentials() -> List[uuid.UUID]:
    from sqlalchemy import union

    from src.ai.email_models import EmailConnection
    from src.ai.social_models import SocialConnection
    from src.common.tenancy.session import control_session, tenant_scopes, tenant_session
    from src.config.models import IntegrationRegistry

    found: set = set()
    for scope in await tenant_scopes():
        async with tenant_session(scope) as db:
            found.update((await db.execute(union(select(SocialConnection.company_id),
                                                 select(EmailConnection.company_id)))).scalars().all())
    async with control_session() as db:
        from src.auth.platform import platform_company_id

        platform = await platform_company_id(db)
        found.update((await db.execute(select(IntegrationRegistry.company_id).where(
            IntegrationRegistry.company_id != platform).distinct())).scalars().all())
    return sorted(found, key=str)


async def _cli(args: argparse.Namespace) -> int:
    from src.common import database

    try:
        companies = [uuid.UUID(args.company)] if args.company else await companies_with_credentials()
        failed = 0
        for company_id in companies:
            report = await convert_company(company_id, apply=args.apply,
                                           remove_registry_rows=args.remove_registry_rows)
            failed += len(report["failed"])
            print(json.dumps({"company_id": str(company_id), **{k: (len(v) if isinstance(v, list) else v)
                                                                for k, v in report.items()}}))
            for item in report["failed"]:
                print("  failed:", item)
        if not args.apply:
            print("(dry run: nothing written; add --apply)")
        return 1 if failed else 0
    finally:
        await database.engine.dispose()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.connections.migrate")
    parser.add_argument("--company", help="only this company (default: every company with old credentials)")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--remove-registry-rows", action="store_true",
                        help="delete the business registry rows once converted")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(_cli(args))


if __name__ == "__main__":
    sys.exit(main())
