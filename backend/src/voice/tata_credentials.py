"""The one place Tata Tele (Smartflo) credentials are read and written.

Every Smartflo caller — click-to-call, the number syncs, the hang-up — resolves its
credentials here, from the ``tata_tele`` row of ``integration_registry`` and nothing
else. Before this, each caller picked its own field: click-to-call and the syncs read
a plain-text ``service_metadata["api_key"]``, the hang-up read a plain-text
``service_metadata["auth_token"]``, and two ConfigService lookups matched the row
differently (``ILIKE '%tata_tele%'`` vs an exact name, both unordered ``.first()``).

Storage
  * ``encrypted_api_key``                  the click-to-call api_key
  * ``service_metadata["secrets_encrypted"]`` every other secret, each AES-GCM
    encrypted with the same key as encrypted_api_key: ``auth_token`` (Smartflo
    account-API token, used for hang-up), ``login_password``, ``api_secret``
  * ``service_metadata`` plain fields       non-secret settings: ``api_url``,
    ``business_id``, ``login_email``, ``from_number``

No secret is ever stored or returned in plain text. Writes go through
:func:`normalize_tata_metadata`, which lifts plain-text secrets an admin typed into the
metadata JSON into their encrypted homes; responses go through
:func:`redact_secrets`, which shows only which secrets are set.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.security import decrypt_api_key, encrypt_api_key

logger = logging.getLogger(__name__)

TATA_PROVIDER = "tata_tele"
DEFAULT_API_URL = "https://api-smartflo.tatateleservices.com"

#: Secrets kept encrypted inside service_metadata (the api_key has its own column).
METADATA_SECRETS = ("auth_token", "login_password", "api_secret")
#: Every secret name an admin might type into the metadata JSON.
ALL_SECRETS = ("api_key",) + METADATA_SECRETS
ENCRYPTED_KEY = "secrets_encrypted"
#: Response-only: the names of the secrets that are set, never their values.
SECRETS_SET_KEY = "secrets_set"


@dataclass(frozen=True)
class TataCredentials:
    integration_id: UUID
    owner_company_id: UUID
    api_key: Optional[str]
    auth_token: Optional[str]
    login_email: Optional[str]
    login_password: Optional[str]
    api_secret: Optional[str]
    business_id: Optional[str]
    from_number: Optional[str]
    api_url: str = DEFAULT_API_URL


def credentials_from_entry(entry) -> TataCredentials:
    """Decrypt one integration_registry row. Plain-text secrets are ignored on purpose."""
    meta: Dict[str, Any] = dict(entry.service_metadata or {})
    encrypted: Dict[str, str] = dict(meta.get(ENCRYPTED_KEY) or {})
    leftover = [k for k in ALL_SECRETS if meta.get(k)]
    if leftover:
        logger.warning(
            f"tata_tele integration {entry.id} still holds plain-text {leftover} in "
            "service_metadata; they are ignored. Re-save the integration to encrypt them."
        )

    def secret(name: str) -> Optional[str]:
        value = encrypted.get(name)
        return decrypt_api_key(value) if value else None

    return TataCredentials(
        integration_id=entry.id,
        owner_company_id=entry.company_id,
        api_key=decrypt_api_key(entry.encrypted_api_key) if entry.encrypted_api_key else None,
        auth_token=secret("auth_token"),
        login_email=meta.get("login_email"),
        login_password=secret("login_password"),
        api_secret=secret("api_secret"),
        business_id=meta.get("business_id"),
        from_number=meta.get("from_number"),
        api_url=(meta.get("api_url") or DEFAULT_API_URL).rstrip("/"),
    )


async def resolve_tata_credentials(db: AsyncSession, company_id: UUID) -> Optional[TataCredentials]:
    """The Tata credentials that apply to ``company_id``: its own active ``tata_tele``
    row, else the platform (APP) company's. Deterministic: exact provider name, and the
    most recently updated row wins if there were ever more than one."""
    from src.auth.models import Company
    from src.config.models import IntegrationRegistry

    async def row_for(cid: UUID):
        return (await db.execute(
            select(IntegrationRegistry)
            .where(
                IntegrationRegistry.company_id == cid,
                IntegrationRegistry.provider_name == TATA_PROVIDER,
                IntegrationRegistry.status == "active",
            )
            .order_by(IntegrationRegistry.updated_at.desc(), IntegrationRegistry.id)
            .limit(1)
        )).scalar_one_or_none()

    entry = await row_for(company_id)
    if entry is None:
        app_id = (await db.execute(select(Company.id).where(Company.type == "APP").limit(1))).scalar_one_or_none()
        if app_id and app_id != company_id:
            entry = await row_for(app_id)
    if entry is None:
        logger.warning(f"No active tata_tele integration for company {company_id} or the platform")
        return None
    return credentials_from_entry(entry)


def normalize_tata_metadata(
    new_meta: Optional[Dict[str, Any]],
    existing_meta: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Prepare metadata an admin submitted for storage.

    Returns ``(metadata, api_key)``: plain-text secrets are removed from the metadata
    and encrypted into ``secrets_encrypted``; a plain-text ``api_key`` is returned for
    the caller to store in ``encrypted_api_key``. Secrets already stored are kept — the
    console never sees them, so its edit round-trip cannot erase them — and anything a
    client sends under ``secrets_encrypted`` / ``secrets_set`` is ignored.
    """
    meta = dict(new_meta or {})
    meta.pop(SECRETS_SET_KEY, None)
    meta.pop(ENCRYPTED_KEY, None)
    encrypted = dict((existing_meta or {}).get(ENCRYPTED_KEY) or {})

    api_key = meta.pop("api_key", None) or None
    for name in METADATA_SECRETS:
        value = meta.pop(name, None)
        if value:
            encrypted[name] = encrypt_api_key(str(value))
    if encrypted:
        meta[ENCRYPTED_KEY] = encrypted
    return meta, api_key


def redact_secrets(meta: Optional[Dict[str, Any]], has_api_key: bool = False) -> Optional[Dict[str, Any]]:
    """What the console may see: no ciphertext, just which secrets are set."""
    if not meta or ENCRYPTED_KEY not in meta:
        return meta
    shown = {k: v for k, v in meta.items() if k != ENCRYPTED_KEY}
    names = sorted((meta.get(ENCRYPTED_KEY) or {}).keys())
    shown[SECRETS_SET_KEY] = (["api_key"] if has_api_key else []) + names
    return shown
