"""
Lead Queue Worker — background poller that dispatches outbound calls for queued leads.

Runs as an arq background task or standalone asyncio loop.
Polls the lead_queue table for pending entries and initiates
outbound calls via CampaignExecutor's Tata Tele integration.
"""
import logging
import asyncio
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from src.common.database import AsyncSessionLocal
from src.ai.lead_queue_service import LeadQueueService
from src.ai.lead_queue_model import LeadQueueEntry

logger = logging.getLogger(__name__)

# Maximum concurrent outbound calls from the lead queue
MAX_CONCURRENT_LEAD_CALLS = 5
POLL_INTERVAL_SECONDS = 5

# Track active calls for concurrency control
_active_calls: set = set()


async def process_lead(entry: LeadQueueEntry) -> None:
    """
    Place an outbound call for a single lead queue entry.

    Creates a VoiceSession, calls the lead via Tata Tele Click-to-Call,
    and updates the queue entry status throughout the lifecycle.
    """
    entry_id = entry.id
    _active_calls.add(entry_id)

    try:
        async with AsyncSessionLocal() as db:
            from src.ai.campaign_executor import CampaignExecutor
            from src.voice.session_manager import SessionManager

            queue_svc = LeadQueueService(db)
            session_mgr = SessionManager(db)
            campaign_exec = CampaignExecutor(db)

            lead_data = entry.lead_data or {}
            properties = lead_data.get("properties", lead_data)
            phone = entry.phone
            lead_name = (
                f"{properties.get('first_name', '')} {properties.get('last_name', '')}".strip()
                or "Unknown"
            )

            logger.info(
                f"[LeadQueueWorker] Placing call for lead {entry.lead_id} "
                f"({lead_name}) at {phone}"
            )

            # Create a VoiceSession for tracking
            customer_id = uuid4()  # Ephemeral customer ID for new leads
            session = await session_mgr.create_voice_session(
                company_id=entry.company_id,
                customer_id=customer_id,
                agent_id=entry.agent_id,
                phone_number=phone,
                provider="tata_tele",
                call_sid=f"lead-{entry.lead_id}-{entry.attempt_count}",
                direction="outbound",
                session_metadata={
                    "lead_queue_entry_id": str(entry.id),
                    "lead_id": entry.lead_id,
                    "lead_name": lead_name,
                    "ad_source": entry.ad_source,
                    "project_id": entry.project_id,
                    "lead_data": lead_data,
                },
            )

            # Link voice session to queue entry
            await queue_svc.mark_calling(entry.id, session.id)

            # Place the outbound call via Tata Tele
            try:
                await campaign_exec._place_tata_call(
                    company_id=entry.company_id,
                    phone_number=phone,
                    agent_id=entry.agent_id,
                    session_id=session.id,
                    contact_name=lead_name,
                )
                logger.info(
                    f"[LeadQueueWorker] Call placed for lead {entry.lead_id} "
                    f"(session={session.id})"
                )
            except Exception as call_err:
                logger.error(f"[LeadQueueWorker] Call failed for lead {entry.lead_id}: {call_err}")
                await queue_svc.mark_failed(entry.id, str(call_err))

    except Exception as e:
        logger.error(f"[LeadQueueWorker] Error processing lead {entry_id}: {e}", exc_info=True)
        try:
            async with AsyncSessionLocal() as db:
                await LeadQueueService(db).mark_failed(entry_id, str(e))
        except Exception:
            pass
    finally:
        _active_calls.discard(entry_id)


async def poll_lead_queue() -> None:
    """
    Single poll cycle: pick a pending lead and dispatch a call.

    Respects MAX_CONCURRENT_LEAD_CALLS to avoid overwhelming telephony.
    """
    if len(_active_calls) >= MAX_CONCURRENT_LEAD_CALLS:
        return

    try:
        async with AsyncSessionLocal() as db:
            queue_svc = LeadQueueService(db)
            entry = await queue_svc.pick_next_lead()

            if entry:
                # Fire-and-forget the call in a background task
                asyncio.create_task(process_lead(entry))
    except Exception as e:
        logger.error(f"[LeadQueueWorker] Poll error: {e}")


async def run_lead_queue_loop() -> None:
    """
    Continuous polling loop — entry point for background execution.

    Can be started as:
      - An arq periodic task
      - A standalone asyncio.create_task() from app startup
    """
    logger.info(
        f"[LeadQueueWorker] Starting lead queue poller "
        f"(interval={POLL_INTERVAL_SECONDS}s, max_concurrent={MAX_CONCURRENT_LEAD_CALLS})"
    )
    while True:
        await poll_lead_queue()
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


# --- arq task interface ---

async def poll_lead_queue_task(ctx: dict) -> None:
    """ARQ background task wrapper for a single poll cycle."""
    await poll_lead_queue()
