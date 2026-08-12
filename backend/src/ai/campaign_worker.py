"""
Campaign execution worker - ARQ background task for campaign execution.

Runs campaigns in the background using ARQ task queue.

NOTE: Background workers MUST NOT use FastAPI's yielding ``get_db()``
dependency.  The ``break`` inside ``async for db in get_db()`` triggers
``GeneratorExit``, which races with SQLAlchemy's async session close and
causes ``IllegalStateChangeError``.  Use ``AsyncSessionLocal`` directly.

Additionally, the campaign executor uses fully isolated sessions per
operation — the worker does NOT create any session itself.
"""
import logging
from uuid import UUID

from src.ai.campaign_executor import CampaignExecutor
from src.common.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def execute_campaign_task(ctx: dict, campaign_id: str):
    """
    ARQ background task to execute a campaign.

    Delegates entirely to CampaignExecutor.start_campaign_standalone()
    which manages its own database sessions. No session is created here
    to avoid cross-session ORM conflicts.

    Args:
        ctx: ARQ context
        campaign_id: Campaign UUID as string
    """
    logger.info(f"Starting campaign execution task for {campaign_id}")

    try:
        await CampaignExecutor.start_campaign_standalone(UUID(campaign_id))
    except Exception as e:
        logger.error(f"Error in campaign execution task: {e}", exc_info=True)
        raise


async def pause_campaign_task(ctx: dict, campaign_id: str):
    """
    ARQ background task to pause a campaign.

    Args:
        ctx: ARQ context
        campaign_id: Campaign UUID as string
    """
    logger.info(f"Pausing campaign {campaign_id}")

    try:
        async with AsyncSessionLocal() as db:
            executor = CampaignExecutor(db)
            await executor.pause_campaign(UUID(campaign_id))

    except Exception as e:
        logger.error(f"Error pausing campaign: {e}", exc_info=True)
        raise


async def stop_campaign_task(ctx: dict, campaign_id: str):
    """
    ARQ background task to stop a campaign.

    Args:
        ctx: ARQ context
        campaign_id: Campaign UUID as string
    """
    logger.info(f"Stopping campaign {campaign_id}")

    try:
        async with AsyncSessionLocal() as db:
            executor = CampaignExecutor(db)
            await executor.stop_campaign(UUID(campaign_id))

    except Exception as e:
        logger.error(f"Error stopping campaign: {e}", exc_info=True)
        raise
