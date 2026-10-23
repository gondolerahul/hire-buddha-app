"""Move the platform's integration secrets into the vault (Phase 14 WS5 5.7, tech spec §10.7).

    python -m src.config.move_secrets            # what would move (nothing written)
    python -m src.config.move_secrets --apply    # write each to the vault, then point the row at it

For every system-integration row of the platform company that still holds its
secret encrypted in the database (``encrypted_api_key``, no ``secret_ref``):
the value is written to the platform vault as ``registry-<service sku>``, read
back to check it, and only then does the row get ``secret_ref`` and lose its
``encrypted_api_key``. A row that fails is left as it was.

The ``razorpay_keys`` row from before Phase 15 T0-2 kept its secrets in its
metadata in plain text (``key_secret``, ``webhook_secret``): they move the
same way, to ``registry-razorpay-keys`` (the row's ``secret_ref``) and
``registry-razorpay-keys-webhook`` (``service_metadata.webhook_secret_ref``),
and leave the metadata. Rows of other
companies are a business's own keys: they become connections (WS7,
``python -m src.connections.migrate``), not vault secrets.

The vault must be writable: the ``azure_keyvault`` adapter on Azure (Key Vault
Secrets Officer on the platform vault). Locally there is no vault to write to;
the dry run still lists what would move.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from typing import Any, Dict, List, Optional

from sqlalchemy import select


def vault_name(service_sku: str) -> str:
    return ("registry-" + re.sub(r"[^0-9A-Za-z-]+", "-", service_sku).strip("-"))[:127]


async def move_secrets(db: Any, writer: Optional[Any], *, apply: bool) -> Dict[str, List[Dict[str, str]]]:
    from src.auth.platform import platform_company_id
    from src.common.platform.secrets import get_secrets
    from src.common.security import decrypt_api_key
    from src.config.models import IntegrationRegistry

    platform = await platform_company_id(db)
    rows = (await db.execute(select(IntegrationRegistry).where(
        IntegrationRegistry.company_id == platform, IntegrationRegistry.encrypted_api_key.is_not(None),
        IntegrationRegistry.secret_ref.is_(None)).order_by(IntegrationRegistry.service_sku))).scalars().all()
    report: Dict[str, List[Dict[str, str]]] = {"moved": [], "would_move": [], "failed": []}
    for row in rows:
        name = vault_name(row.service_sku)
        item = {"service_sku": row.service_sku, "secret_ref": name}
        if not apply:
            report["would_move"].append(item)
            continue
        try:
            value = decrypt_api_key(row.encrypted_api_key)
            await writer.set(name, value)
            reader = get_secrets()
            reader.forget(name)
            if await reader.get(name) != value:
                raise RuntimeError("the vault does not return what was written")
            row.secret_ref, row.encrypted_api_key = name, None
            await db.commit()
            report["moved"].append(item)
        except Exception as error:  # noqa: BLE001 - this row stays as it was
            await db.rollback()
            report["failed"].append({**item, "error": f"{type(error).__name__}: {error}"[:300]})
    await _move_razorpay_metadata(db, writer, apply=apply, report=report)
    return report


async def _write_checked(writer: Any, name: str, value: str) -> None:
    from src.common.platform.secrets import get_secrets

    await writer.set(name, value)
    reader = get_secrets()
    reader.forget(name)
    if await reader.get(name) != value:
        raise RuntimeError("the vault does not return what was written")


async def _move_razorpay_metadata(db: Any, writer: Optional[Any], *, apply: bool,
                                  report: Dict[str, List[Dict[str, str]]]) -> None:
    """The plain-text secrets of ``razorpay_keys`` (T0-2) into the vault."""
    from src.billing.razorpay_gateway import RAZORPAY_SKU, WEBHOOK_SECRET_REF
    from src.config.models import IntegrationRegistry

    rows = (await db.execute(select(IntegrationRegistry).where(
        IntegrationRegistry.service_sku == RAZORPAY_SKU))).scalars().all()
    for row in rows:
        metadata = dict(row.service_metadata or {})
        moves = []  # (metadata field, vault name)
        if metadata.get("key_secret"):
            moves.append(("key_secret", vault_name(row.service_sku)))
        if metadata.get("webhook_secret"):
            moves.append(("webhook_secret", vault_name(row.service_sku) + "-webhook"))
        for field, name in moves:
            item = {"service_sku": f"{row.service_sku}.{field}", "secret_ref": name}
            if not apply:
                report["would_move"].append(item)
                continue
            try:
                await _write_checked(writer, name, metadata[field])
                metadata.pop(field)
                if field == "key_secret":
                    row.secret_ref, row.encrypted_api_key = name, None
                else:
                    metadata[WEBHOOK_SECRET_REF] = name
                row.service_metadata = dict(metadata)
                await db.commit()
                report["moved"].append(item)
            except Exception as error:  # noqa: BLE001 - this secret stays where it was
                await db.rollback()
                report["failed"].append({**item, "error": f"{type(error).__name__}: {error}"[:300]})
                break  # the local copy of the metadata no longer matches the row


async def _cli(apply: bool) -> int:
    from src.common import database
    from src.common.platform.secrets import get_secrets
    from src.common.tenancy.session import control_session

    writer = get_secrets().inner
    if apply and not hasattr(writer, "set"):
        print(f"The {writer.name} secrets adapter cannot write; run this where SECRETS_BACKEND=azure_keyvault.")
        return 2
    try:
        async with control_session() as db:
            report = await move_secrets(db, writer, apply=apply)
    finally:
        await database.engine.dispose()
    for key, items in report.items():
        for item in items:
            print(f"{key:11} {item['service_sku']:40} -> {item['secret_ref']} {item.get('error', '')}")
    return 1 if report["failed"] else 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.config.move_secrets")
    parser.add_argument("--apply", action="store_true", help="write to the vault and update the rows")
    return asyncio.run(_cli(parser.parse_args(argv).apply))


if __name__ == "__main__":
    sys.exit(main())
