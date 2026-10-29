"""Register HireBuddha's own app with a provider (WS5 5.9; docs/how-to/PROVIDER_APP_REGISTRATION_GUIDE.md §9).

    python -m src.connections.register_app meta \\
        --set client_id=123 --set config_id=456 --set solution_id=789 --set graph_version=v26.0 \\
        --secret oauth-meta-app-secret --ref verify_token=oauth-meta-verify-token [--apply]

Writes (or updates) the platform company's ``OAUTH_APP`` row that
``connections.apps.provider_app`` reads: SKU ``oauth-app-<provider>``,
non-secret settings in ``service_metadata``, the client secret and any further
secrets **by their vault name** only (``secret_ref``, ``<name>_ref``). Without
``--apply`` it prints what it would write. No secret value ever passes through
it: the owner puts them in Key Vault (the guide's names).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

# ``google-marketing``: the separate Google Cloud project for YouTube and
# Google Ads (docs/phase15/14_connector_approvals/09 §4), SKU oauth-app-google-marketing.
PROVIDERS = ("meta", "google", "google-marketing", "microsoft", "linkedin", "x", "github")
# Settings each provider's adapter needs (connections/apps.py, providers/*).
REQUIRED: Dict[str, Sequence[str]] = {
    "meta": ("client_id",),
    "google": ("client_id",),
    "google-marketing": ("client_id",),
    "microsoft": ("client_id",),
    "linkedin": ("client_id",),
    "x": ("client_id",),
    "github": ("client_id", "app_id", "app_slug"),
}
REQUIRED_REFS: Dict[str, Sequence[str]] = {"github": ("private_key", "webhook_secret")}


def row_values(provider: str, settings: Dict[str, str], refs: Dict[str, str],
               secret: Optional[str]) -> Dict[str, Any]:
    """The registry row for ``provider``'s app, checked; raises ``ValueError``."""
    from src.common.platform.secrets import validate_secret_name

    if provider not in PROVIDERS:
        raise ValueError(f"provider must be one of {', '.join(PROVIDERS)}")
    missing = [k for k in REQUIRED[provider] if not settings.get(k)]
    missing += [f"--ref {k}=…" for k in REQUIRED_REFS.get(provider, ()) if not refs.get(k)]
    if missing:
        raise ValueError(f"{provider} needs: {', '.join(missing)}")
    for key in settings:
        if key.endswith("_ref"):
            raise ValueError(f"{key}: give secrets with --ref NAME=VAULT_NAME, not --set")
    for name in [*refs.values(), *([secret] if secret else [])]:
        validate_secret_name(name)
    metadata: Dict[str, Any] = dict(settings)
    metadata.update({f"{key}_ref": name for key, name in refs.items()})
    return {
        "provider_name": provider,
        "service_sku": f"oauth-app-{provider}",
        "service_category": "OAUTH_APP",
        "component_type": "flat_fee",
        "internal_cost": Decimal("0"),
        "cost_unit_code": "PER_REQUEST",
        "service_metadata": metadata,
        "secret_ref": secret,
        "status": "active",
    }


async def register(values: Dict[str, Any], *, apply: bool) -> str:
    """Create or update the row on the platform company; returns what was done."""
    from sqlalchemy import select

    from src.auth.platform import platform_company_id
    from src.common.tenancy.session import control_session
    from src.config.models import IntegrationRegistry

    async with control_session() as db:
        platform = await platform_company_id(db)
        if platform is None:
            raise RuntimeError("no platform (APP) company on this environment")
        row = (await db.execute(select(IntegrationRegistry).where(
            IntegrationRegistry.company_id == platform,
            IntegrationRegistry.service_sku == values["service_sku"],
        ))).scalar_one_or_none()
        action = "update" if row is not None else "create"
        if not apply:
            return f"would {action} {values['service_sku']}"
        if row is None:
            row = IntegrationRegistry(company_id=platform, **values)
            db.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        await db.commit()
        return f"{action}d {values['service_sku']}"


def _pairs(items: Optional[List[str]], flag: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep or not key or not value:
            raise ValueError(f"{flag} takes NAME=VALUE, not {item!r}")
        out[key.strip()] = value.strip()
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.connections.register_app", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("provider", choices=PROVIDERS)
    parser.add_argument("--set", action="append", metavar="NAME=VALUE",
                        help="a non-secret setting (client_id, config_id, solution_id, graph_version, app_id, "
                             "app_slug, tenant)")
    parser.add_argument("--ref", action="append", metavar="NAME=VAULT_NAME",
                        help="a further secret by its vault name (verify_token, private_key, webhook_secret)")
    parser.add_argument("--secret", metavar="VAULT_NAME", help="the client secret's vault name")
    parser.add_argument("--apply", action="store_true", help="write the row (default: show it)")
    args = parser.parse_args(argv)
    try:
        values = row_values(args.provider, _pairs(args.set, "--set"), _pairs(args.ref, "--ref"), args.secret)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps({k: (str(v) if isinstance(v, Decimal) else v) for k, v in values.items()}, indent=2))
    print(asyncio.run(register(values, apply=args.apply)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
