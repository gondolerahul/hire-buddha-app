"""
Razorpay credentials and client.

The keys live in ``integration_registry`` (``service_sku='razorpay_keys'``),
``service_metadata`` = ``{"key_id", "key_secret", "webhook_secret"}``.
``webhook_secret`` is the secret set on the webhook in the Razorpay dashboard;
without it the webhook answers 503.
"""
import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

RAZORPAY_SKU = "razorpay_keys"


async def get_razorpay_creds(db: AsyncSession) -> Optional[dict]:
    """The active ``razorpay_keys`` metadata, or None."""
    try:
        from src.config.models import IntegrationRegistry
        stmt = select(IntegrationRegistry).where(
            IntegrationRegistry.service_sku == RAZORPAY_SKU,
            IntegrationRegistry.status == "active",
        )
        entry = (await db.execute(stmt)).scalars().first()
        if entry and entry.service_metadata:
            return entry.service_metadata
        return None
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
