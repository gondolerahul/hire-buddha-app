"""Shared Twilio REST helpers: credential lookup and call hangup.

Closing the media-stream WebSocket does not terminate the PSTN leg; ending a
Twilio call programmatically requires POSTing Status=completed to the Calls
resource. Used by the stream handler (in-call voicemail/silence detection)
and the status webhook (async AMD results).
"""

import logging
from typing import Optional, Tuple
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.models import IntegrationRegistry
from src.common.security import decrypt_api_key

logger = logging.getLogger(__name__)


async def get_twilio_credentials(
    db: AsyncSession, company_id: Optional[UUID]
) -> Tuple[Optional[str], Optional[str]]:
    """Return (account_sid, auth_token) from the Integration Registry."""
    result = await db.execute(
        select(IntegrationRegistry).where(
            IntegrationRegistry.company_id == company_id,
            IntegrationRegistry.provider_name == "twilio",
            IntegrationRegistry.status == "active",
        )
    )
    entry = result.scalars().first()

    account_sid = None
    auth_token = None
    if entry:
        auth_token = (
            decrypt_api_key(entry.encrypted_api_key) if entry.encrypted_api_key else None
        )
        if entry.service_metadata:
            account_sid = entry.service_metadata.get("account_sid")
    return account_sid, auth_token


async def hangup_twilio_call(
    db: AsyncSession, company_id: Optional[UUID], call_sid: str
) -> bool:
    """Force-complete a live Twilio call. Returns True on success."""
    account_sid, auth_token = await get_twilio_credentials(db, company_id)
    if not account_sid or not auth_token:
        logger.warning(
            f"Cannot hang up Twilio call {call_sid}: no credentials for "
            f"company {company_id}"
        )
        return False

    api_url = (
        f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}"
        f"/Calls/{call_sid}.json"
    )
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                api_url,
                data={"Status": "completed"},
                auth=(account_sid, auth_token),
                timeout=10.0,
            )
        logger.info(
            f"Twilio hangup for {call_sid}: status={resp.status_code}"
        )
        return resp.status_code in (200, 201)
    except Exception as e:
        logger.error(f"Twilio hangup request failed for {call_sid}: {e}")
        return False
