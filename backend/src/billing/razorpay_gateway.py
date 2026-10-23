"""
Razorpay credentials and client.

The keys are the ``integration_registry`` row with ``service_sku='razorpay_keys'``
(Phase 15 T0-2 — no secret in the database in plain text, B-8):

* ``service_metadata["key_id"]`` — the public key id (sent to Razorpay Checkout);
* the key secret — the row's own secret: ``secret_ref`` (a name in the platform
  vault) or ``encrypted_api_key`` (the console's API key field);
* ``service_metadata["webhook_secret_ref"]`` — the vault name of the secret set
  on the webhook in the Razorpay dashboard; without it the webhook answers 503.

Rows from before kept ``key_secret`` and ``webhook_secret`` in the metadata in
plain text. They are still read, with an error in the log, until
``python -m src.config.move_secrets --apply`` moves them into the vault; the
registry API no longer accepts them (``refuse_plain_secrets``).
"""
import logging
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

RAZORPAY_SKU = "razorpay_keys"
# The metadata fields that held secrets in plain text before T0-2.
PLAIN_SECRETS = ("key_secret", "webhook_secret")
WEBHOOK_SECRET_REF = "webhook_secret_ref"


def refuse_plain_secrets(service_sku: Optional[str], metadata: Optional[dict]) -> None:
    """422 when a ``razorpay_keys`` write puts a secret in the metadata in plain text."""
    if service_sku != RAZORPAY_SKU or not metadata:
        return
    found = [name for name in PLAIN_SECRETS if metadata.get(name)]
    if found:
        raise HTTPException(status_code=422, detail=(
            f"razorpay_keys: {', '.join(found)} may not be stored in service_metadata. Put the key secret "
            "in the API key field (or secret_ref, a vault name) and the webhook secret in the vault, "
            "named by service_metadata.webhook_secret_ref."))


async def _secret(entry: Any, metadata: dict) -> Optional[str]:
    from src.config.registry_secrets import registry_secret

    value = await registry_secret(entry)
    if value is None and metadata.get("key_secret"):
        logger.error("razorpay_keys: the key secret is in service_metadata in plain text; "
                     "run python -m src.config.move_secrets --apply")
        value = metadata["key_secret"]
    return value


async def _webhook_secret(metadata: dict) -> Optional[str]:
    from src.config.registry_secrets import secret_by_name

    value = await secret_by_name(metadata.get(WEBHOOK_SECRET_REF))
    if value is None and metadata.get("webhook_secret"):
        logger.error("razorpay_keys: the webhook secret is in service_metadata in plain text; "
                     "run python -m src.config.move_secrets --apply")
        value = metadata["webhook_secret"]
    return value


async def get_razorpay_creds(db: AsyncSession) -> Optional[dict]:
    """``{key_id, key_secret, webhook_secret}`` of the active ``razorpay_keys`` row, or None
    when there is none or it lacks the key id or secret (``webhook_secret`` may be None)."""
    try:
        from src.config.models import IntegrationRegistry
        stmt = select(IntegrationRegistry).where(
            IntegrationRegistry.service_sku == RAZORPAY_SKU,
            IntegrationRegistry.status == "active",
        )
        entry = (await db.execute(stmt)).scalars().first()
        if entry is None:
            return None
        metadata = dict(entry.service_metadata or {})
        key_secret = await _secret(entry, metadata)
        if not metadata.get("key_id") or not key_secret:
            logger.error("razorpay_keys: the row has no key_id or no key secret")
            return None
        return {
            "key_id": metadata["key_id"],
            "key_secret": key_secret,
            "webhook_secret": await _webhook_secret(metadata),
        }
    except Exception as e:
        logger.error(f"Failed to fetch Razorpay credentials: {e}")
        return None


def razorpay_client(creds: Optional[dict]) -> Optional[Any]:
    """A ``razorpay.Client`` for ``creds``, or None when keys are missing."""
    if not creds or not creds.get("key_id") or not creds.get("key_secret"):
        return None
    try:
        import razorpay
    except ImportError:
        logger.warning("razorpay package not installed. Payment processing unavailable.")
        return None
    return razorpay.Client(auth=(creds["key_id"], creds["key_secret"]))
