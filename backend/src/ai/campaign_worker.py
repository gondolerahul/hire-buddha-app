"""
Campaign execution worker - ARQ background task for campaign execution.

Runs campaigns in the background using ARQ task queue.

NOTE: Background workers MUST NOT use FastAPI's yielding ``get_db()``
dependency.  The ``break`` inside ``async for db in get_db()`` triggers
``GeneratorExit``, which races with SQLAlchemy's async session close and
causes ``IllegalStateChangeError``.  Open a session directly.

Additionally, the campaign executor uses fully isolated sessions per
operation — the worker does NOT create any session itself.

Each task takes ``company_id`` (keyword, ``job_queue.tenant_arg``): the
tenant whose database holds the campaign (Phase 14 WS2 2.5). A task queued
before tasks carried it runs only with ``TENANCY_MODE=single``.
"""
import logging
from typing import Optional
from uuid import UUID

from src.ai.campaign_executor import CampaignExecutor
from src.common.tenancy.session import tenant_session

logger = logging.getLogger(__name__)


def _company(company_id: Optional[str]) -> Optional[UUID]:
    return UUID(company_id) if company_id else None


async def execute_campaign_task(ctx: dict, campaign_id: str, continuation: bool = False,
                                company_id: Optional[str] = None):
    """
    ARQ background task to execute a campaign.

    Delegates entirely to CampaignExecutor.start_campaign_standalone()
    which manages its own database sessions. No session is created here
    to avoid cross-session ORM conflicts.

    Args:
        ctx: ARQ context
        campaign_id: Campaign UUID as string
        company_id: the campaign's company (its tenant database)
    """
    logger.info(f"Starting campaign execution task for {campaign_id}")

    try:
        await CampaignExecutor.start_campaign_standalone(UUID(campaign_id), continuation=continuation,
                                                         company_id=_company(company_id))
    except Exception as e:
        logger.error(f"Error in campaign execution task: {e}", exc_info=True)
        raise


async def pause_campaign_task(ctx: dict, campaign_id: str, company_id: Optional[str] = None):
    """
    ARQ background task to pause a campaign.

    Args:
        ctx: ARQ context
        campaign_id: Campaign UUID as string
        company_id: the campaign's company (its tenant database)
    """
    logger.info(f"Pausing campaign {campaign_id}")

    try:
        async with tenant_session(_company(company_id)) as db:
            executor = CampaignExecutor(db)
            await executor.pause_campaign(UUID(campaign_id))

    except Exception as e:
        logger.error(f"Error pausing campaign: {e}", exc_info=True)
        raise


async def stop_campaign_task(ctx: dict, campaign_id: str, company_id: Optional[str] = None):
    """
    ARQ background task to stop a campaign.

    Args:
        ctx: ARQ context
        campaign_id: Campaign UUID as string
        company_id: the campaign's company (its tenant database)
    """
    logger.info(f"Stopping campaign {campaign_id}")

    try:
        async with tenant_session(_company(company_id)) as db:
            executor = CampaignExecutor(db)
            await executor.stop_campaign(UUID(campaign_id))

    except Exception as e:
        logger.error(f"Error stopping campaign: {e}", exc_info=True)
        raise
