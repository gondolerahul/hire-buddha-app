"""
Campaign Executor - Auto-dialer for bulk voice campaigns.

Handles:
- Campaign execution scheduling
- Call queue management
- Throttling and rate limiting
- Twilio/Tata Tele API integration for outbound calls
- Call status monitoring

NOTE: All database operations use isolated AsyncSessionLocal sessions
to avoid cross-session ORM state conflicts in the ARQ worker.
"""
import logging
import asyncio
import httpx
from datetime import datetime
from uuid import UUID, uuid4
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update

from src.ai.campaign_models import Campaign, CampaignCall
from src.voice.models import VoiceSession
from src.voice.number_router import NumberRouter
from src.config.service import ConfigService
from src.config.models import IntegrationRegistry
from src.common.security import decrypt_api_key
from src.common.config import settings
from src.common.database import AsyncSessionLocal
from src.billing.credit_service import CreditService, InsufficientCreditsError

logger = logging.getLogger(__name__)


class CampaignExecutor:
    """
    Executes voice calling campaigns.

    Manages call queues, throttling, and status tracking.

    All public entry points create their own database sessions to avoid
    cross-session ORM conflicts that cause IllegalStateChangeError.
    """

    def __init__(self, db: AsyncSession):
        """
        Initialize campaign executor.

        Args:
            db: Database session (used only for non-worker operations)
        """
        self.db = db
        self.number_router = NumberRouter(db)
        self.active_campaigns: Dict[UUID, asyncio.Task] = {}

    # ── Standalone entry point for ARQ worker ──────────────────────────
    @classmethod
    async def start_campaign_standalone(cls, campaign_id: UUID):
        """
        Entry point for the ARQ background worker.

        Manages its own DB sessions — never accepts an external session.
        This prevents the IllegalStateChangeError caused by cross-session
        ORM object usage between the worker's session and inner call sessions.
        """
        logger.info(f"Starting standalone campaign execution for {campaign_id}")

        try:
            # Load campaign + pending calls and extract primitives
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Campaign).where(Campaign.id == campaign_id)
                )
                campaign = result.scalar_one_or_none()

                if not campaign:
                    raise ValueError(f"Campaign {campaign_id} not found")

                if campaign.status not in ["draft", "scheduled", "paused", "running"]:
                    raise ValueError(f"Campaign cannot be started from status: {campaign.status}")

                # Update to running
                await db.execute(
                    update(Campaign)
                    .where(Campaign.id == campaign_id)
                    .values(status="running", started_at=datetime.utcnow(), updated_at=datetime.utcnow())
                )
                await db.commit()

                # Load pending calls
                calls_result = await db.execute(
                    select(CampaignCall)
                    .where(
                        and_(
                            CampaignCall.campaign_id == campaign_id,
                            CampaignCall.status == "pending"
                        )
                    )
                    .order_by(CampaignCall.created_at.asc())
                )
                pending_calls = calls_result.scalars().all()

                # Extract ALL data as primitives before closing this session.
                # This is critical — ORM objects must NOT be used outside their session.
                campaign_data = {
                    "id": campaign.id,
                    "company_id": campaign.company_id,
                    "agent_id": campaign.agent_id,
                    "provider": campaign.provider,
                    "name": campaign.name,
                    "max_concurrent_calls": campaign.max_concurrent_calls or 5,
                }

                calls_data = [
                    {
                        "id": call.id,
                        "contact_data": dict(call.contact_data) if call.contact_data else {},
                    }
                    for call in pending_calls
                ]

            # Session is now closed — we work only with primitives from here

            logger.info(
                f"Executing campaign {campaign_id} ({campaign_data['name']}) "
                f"with {len(calls_data)} pending calls"
            )

            # ── Pre-campaign credit gate ───────────────────────────────
            # Block the entire campaign if the company has zero credits.
            try:
                async with AsyncSessionLocal() as db:
                    credit_svc = CreditService(db)
                    await credit_svc.check_sufficient_for_execution(
                        company_id=campaign_data["company_id"],
                        entity_type="AGENT",
                    )
            except InsufficientCreditsError as e:
                logger.warning(
                    f"Campaign {campaign_id} blocked — insufficient credits: {e}"
                )
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        update(Campaign)
                        .where(Campaign.id == campaign_id)
                        .values(
                            status="failed",
                            updated_at=datetime.utcnow(),
                        )
                    )
                    # Mark all pending calls as skipped
                    for call_info in calls_data:
                        await db.execute(
                            update(CampaignCall)
                            .where(CampaignCall.id == call_info["id"])
                            .values(
                                status="failed",
                                outcome="insufficient_credits",
                                outcome_notes=str(e),
                            )
                        )
                    await db.commit()
                return

            # Warm the agent-context cache so the first dialed lead doesn't
            # pay the ~5s cold load during call setup.
            try:
                from src.voice.agent_loader import AgentContextLoader
                async with AsyncSessionLocal() as db:
                    await AgentContextLoader(db).load_agent_for_session(
                        agent_id=campaign_data["agent_id"],
                        customer_id=uuid4(),
                        channel="voice",
                    )
                logger.info(
                    f"Warmed agent context cache for agent {campaign_data['agent_id']}"
                )
            except Exception as e:
                logger.warning(f"Agent cache warm failed (non-fatal): {e}")

            # Process calls sequentially, each with its own session
            halted_status = None
            for call_info in calls_data:
                # Honor pause/stop issued while the campaign runs: the status
                # PATCH only writes the DB row, so the dial loop must re-read
                # it (previously it dialed the whole list regardless).
                current_status = await cls._get_campaign_status(campaign_id)
                if current_status != "running":
                    halted_status = current_status
                    logger.info(
                        f"Campaign {campaign_id} is '{current_status}' — "
                        f"halting dialing with calls remaining"
                    )
                    break

                # Enforce max_concurrent_calls: the Kanakia run showed 6-8
                # simultaneous call setups starving the audio pipeline (5-27s
                # of dead air per call). Wait until a slot frees up.
                await cls._wait_for_concurrency_slot(
                    campaign_data["id"], campaign_data["max_concurrent_calls"]
                )
                try:
                    await cls._place_call_safe(campaign_data, call_info)
                except Exception as e:
                    logger.error(
                        f"Error placing call {call_info['id']}: {e}",
                        exc_info=True
                    )
                # Delay between calls to respect rate limits
                await asyncio.sleep(2)

            if halted_status is not None:
                # Leave the user-set status (paused keeps pending calls for
                # resume); on stop, mark undialed leads as skipped.
                if halted_status in ("stopped", "completed", "failed"):
                    async with AsyncSessionLocal() as db:
                        await db.execute(
                            update(CampaignCall)
                            .where(
                                CampaignCall.campaign_id == campaign_id,
                                CampaignCall.status == "pending",
                            )
                            .values(
                                status="skipped",
                                outcome_notes=f"campaign_{halted_status}",
                            )
                        )
                        await db.commit()
                logger.info(f"Campaign {campaign_id} halted as '{halted_status}'")
                return

            # Mark campaign as completed
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(Campaign)
                    .where(Campaign.id == campaign_id)
                    .values(
                        status="completed",
                        completed_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                )
                await db.commit()

            logger.info(f"Campaign {campaign_id} completed")

        except Exception as e:
            logger.error(f"Error executing campaign {campaign_id}: {e}", exc_info=True)
            # Try to mark as failed
            try:
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        update(Campaign)
                        .where(Campaign.id == campaign_id)
                        .values(status="failed", updated_at=datetime.utcnow())
                    )
                    await db.commit()
            except Exception:
                logger.error(f"Failed to mark campaign {campaign_id} as failed")

    @staticmethod
    def normalize_phone(raw: Optional[str], default_cc: Optional[str] = None) -> str:
        """Coerce a contact number into E.164-ish form for the dialer.

        The Kanakia follow-up campaign failed every placement with Tata HTTP
        422 because contacts like '+8149603309' carried a '+' but no country
        code. 10-digit numbers get DEFAULT_PHONE_COUNTRY_CODE prepended; a
        leading trunk '0' on an 11-digit number is dropped first.
        """
        import re

        cc = default_cc or settings.DEFAULT_PHONE_COUNTRY_CODE
        digits = re.sub(r"[^\d]", "", str(raw or ""))
        if len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        if len(digits) == 10:
            digits = cc + digits
        return f"+{digits}" if digits else ""

    @classmethod
    async def _get_campaign_status(cls, campaign_id: UUID) -> str:
        """Fresh read of the campaign status in an isolated session."""
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Campaign.status).where(Campaign.id == campaign_id)
                )
                return result.scalar() or "unknown"
        except Exception as e:
            logger.warning(f"Could not read campaign {campaign_id} status: {e}")
            return "running"  # fail open — don't halt dialing on a read blip

    @classmethod
    async def _wait_for_concurrency_slot(
        cls, campaign_id: UUID, max_concurrent: int, max_wait_seconds: int = 180
    ) -> None:
        """Block until fewer than max_concurrent calls are in 'calling' state.

        Waits at most max_wait_seconds so calls stuck in 'calling' (missed
        webhooks) can't deadlock the dialer; when the cap trips we log and
        proceed. Returns early if the campaign leaves 'running' so a stop
        issued during the wait takes effect promptly.
        """
        if max_concurrent <= 0:
            return
        from sqlalchemy import func

        waited = 0
        while waited < max_wait_seconds:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(func.count(CampaignCall.id)).where(
                        and_(
                            CampaignCall.campaign_id == campaign_id,
                            CampaignCall.status == "calling",
                        )
                    )
                )
                active = result.scalar() or 0
            if active < max_concurrent:
                return
            if await cls._get_campaign_status(campaign_id) != "running":
                return  # stop/pause during the wait — dial loop re-checks
            if waited == 0:
                logger.info(
                    f"Campaign {campaign_id}: {active} calls active, "
                    f"waiting for a slot (max_concurrent={max_concurrent})"
                )
            await asyncio.sleep(3)
            waited += 3

        logger.warning(
            f"Campaign {campaign_id}: concurrency wait capped at "
            f"{max_wait_seconds}s — proceeding despite {max_concurrent}+ "
            f"calls still marked 'calling'"
        )

    @classmethod
    async def _place_call_safe(
        cls,
        campaign_data: Dict[str, Any],
        call_info: Dict[str, Any]
    ):
        """
        Place an outbound call using a fully isolated DB session.

        Receives only primitive data — no ORM objects cross session boundaries.

        Args:
            campaign_data: Dict with campaign primitives (id, company_id, agent_id, provider)
            call_info: Dict with call primitives (id, contact_data)
        """
        call_id = call_info["id"]
        contact = call_info["contact_data"]
        raw_phone = contact.get("phone")
        phone = cls.normalize_phone(raw_phone)
        if phone != (raw_phone or "").strip():
            logger.info(f"Normalized contact number {raw_phone!r} → {phone!r}")
        campaign_id = campaign_data["id"]
        company_id = campaign_data["company_id"]
        agent_id = campaign_data["agent_id"]
        provider = campaign_data["provider"]

        logger.info(f"Placing call to {phone} for campaign {campaign_id}")

        async with AsyncSessionLocal() as db:
            try:
                # ── Per-call credit gate ───────────────────────────────
                # Re-check balance before each call — credits may have been
                # exhausted by earlier calls in this campaign.
                try:
                    credit_svc = CreditService(db)
                    await credit_svc.check_sufficient_for_execution(
                        company_id=company_id,
                        entity_type="AGENT",
                    )
                except InsufficientCreditsError as e:
                    logger.warning(
                        f"Skipping call {call_id} — insufficient credits: {e}"
                    )
                    await db.execute(
                        update(CampaignCall)
                        .where(CampaignCall.id == call_id)
                        .values(
                            status="failed",
                            outcome="insufficient_credits",
                            outcome_notes=str(e),
                        )
                    )
                    await db.commit()
                    return

                # Update call status to "calling"
                await db.execute(
                    update(CampaignCall)
                    .where(CampaignCall.id == call_id)
                    .values(status="calling")
                )
                await db.commit()

                # Resolve the number assigned to the campaign's agent
                number_router = NumberRouter(db)
                assignment = await number_router.get_company_number(
                    company_id=company_id,
                    provider=provider,
                    agent_id=agent_id,
                )

                if not assignment:
                    logger.error(f"No phone number assigned for company {company_id}")
                    await db.execute(
                        update(CampaignCall)
                        .where(CampaignCall.id == call_id)
                        .values(status="failed")
                    )
                    await db.commit()
                    return

                from_number = assignment.phone_number

                # Create voice session
                voice_session = VoiceSession(
                    company_id=company_id,
                    customer_id=uuid4(),
                    agent_id=agent_id,
                    phone_number=from_number,
                    provider=provider,
                    direction="outbound",
                    status="initiated",
                    call_sid=f"pending_{uuid4()}",
                    session_metadata={
                        "campaign_id": str(campaign_id),
                        "campaign_call_id": str(call_id),
                        "contact_data": contact,
                    },
                )

                db.add(voice_session)
                await db.commit()
                await db.refresh(voice_session)

                # Link voice session to campaign call
                await db.execute(
                    update(CampaignCall)
                    .where(CampaignCall.id == call_id)
                    .values(
                        voice_session_id=voice_session.id,
                        called_at=datetime.utcnow(),
                    )
                )
                await db.commit()

                # Place actual call via provider
                if provider == "twilio":
                    call_sid = await cls._place_twilio_call_static(
                        db=db,
                        to=phone,
                        from_=from_number,
                        voice_session_id=voice_session.id,
                        agent_id=agent_id,
                        company_id=company_id,
                    )
                elif provider == "tata_tele":
                    call_sid = await cls._place_tata_call_static(
                        db=db,
                        to=phone,
                        from_=from_number,
                        voice_session_id=voice_session.id,
                        agent_id=agent_id,
                        company_id=company_id,
                    )
                else:
                    raise ValueError(f"Unknown provider: {provider}")

                # Update call_sid
                await db.execute(
                    update(CampaignCall)
                    .where(CampaignCall.id == call_id)
                    .values(call_sid=call_sid)
                )
                await db.commit()

                # Update campaign stats
                await cls._increment_stat(db, campaign_id, "calls_initiated")

                logger.info(f"Call placed successfully: {call_sid}")

            except Exception as e:
                logger.error(f"Error placing call to {phone}: {e}", exc_info=True)
                try:
                    await db.rollback()
                    await db.execute(
                        update(CampaignCall)
                        .where(CampaignCall.id == call_id)
                        .values(
                            status="failed",
                            outcome="placement_error",
                            outcome_notes=str(e)[:500],
                            disposition="failed",
                        )
                    )
                    await db.commit()
                    await cls._increment_stat(db, campaign_id, "calls_failed")
                except Exception:
                    logger.error(f"Failed to mark call {call_id} as failed")

    # ── Provider call methods (static — no self.db dependency) ─────────

    @staticmethod
    async def _place_twilio_call_static(
        db: AsyncSession,
        to: str,
        from_: str,
        voice_session_id: UUID,
        agent_id: UUID,
        company_id: Optional[UUID] = None
    ) -> str:
        """
        Place outbound call via Twilio REST API.

        Uses Twilio's Calls resource to initiate an outbound call.
        The call connects to a TwiML webhook that returns <Connect><Stream>
        to establish a WebSocket for bidirectional audio streaming.

        API: POST https://api.twilio.com/2010-04-01/Accounts/{AccountSid}/Calls.json

        Args:
            db: Database session for credential lookup
            to: Destination phone number (E.164 format, e.g. +14155551234)
            from_: Caller ID (Twilio number, E.164 format)
            voice_session_id: VoiceSession UUID
            agent_id: Agent UUID
            company_id: Company UUID for credential lookup

        Returns:
            Call SID from Twilio
        """
        # 1. Retrieve Twilio credentials from Integration Registry
        from src.voice.twilio_api import get_twilio_credentials
        account_sid, auth_token = await get_twilio_credentials(db, company_id)

        if not account_sid or not auth_token:
            raise ValueError(
                "Twilio credentials not found. Please register a 'twilio' "
                "integration in the Integration Registry with account_sid "
                "in service_metadata and auth_token as the api_key."
            )

        # 2. Build the TwiML webhook URL
        # When Twilio connects the call, it will request this URL.
        # The webhook returns TwiML with <Connect><Stream> to establish
        # a WebSocket for bidirectional audio with our streaming service.
        streaming_host = settings.STREAMING_HOST or "localhost:8002"
        # Use HTTPS for production domains, HTTP only for localhost
        protocol = "http" if streaming_host.startswith("localhost") else "https"
        ws_protocol = "ws" if streaming_host.startswith("localhost") else "wss"

        # The TwiML URL that Twilio will fetch when the call connects
        twiml_url = (
            f"{protocol}://{streaming_host}/webhooks/voice/twilio/outbound-twiml"
            f"?session_id={voice_session_id}"
        )

        # Status callback URL for call completion events
        status_callback_url = f"{protocol}://{streaming_host}/webhooks/voice/twilio/status"

        # 3. Build request payload for Twilio REST API
        payload = {
            "To": to,
            "From": from_,
            "Url": twiml_url,
            "StatusCallback": status_callback_url,
            "StatusCallbackEvent": ["initiated", "ringing", "answered", "completed"],
            "StatusCallbackMethod": "POST",
            "Record": "false",
            "MachineDetection": "Enable",  # Detect answering machines
            "AsyncAmd": "true",  # Async answering machine detection
            "AsyncAmdStatusCallback": status_callback_url,
            "AsyncAmdStatusCallbackMethod": "POST",
        }

        # 4. Make API call to Twilio
        api_url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls.json"

        logger.info(
            f"Twilio outbound call: {from_} → {to}, "
            f"session={voice_session_id}, twiml_url={twiml_url}"
        )

        async with httpx.AsyncClient() as client:
            response = await client.post(
                api_url,
                data=payload,  # Twilio expects form-encoded data
                auth=(account_sid, auth_token),
                timeout=30.0
            )

        # 5. Parse response
        response_data = response.json()
        logger.info(f"Twilio API response: {response.status_code} - {response_data}")

        if response.status_code in [200, 201]:
            call_sid = response_data.get("sid")
            logger.info(f"Twilio call initiated successfully: {call_sid}")
            return call_sid
        else:
            error_msg = (
                response_data.get("message")
                or response_data.get("detail")
                or str(response_data)
            )
            raise Exception(
                f"Twilio API error (HTTP {response.status_code}): {error_msg}"
            )

    @staticmethod
    async def _place_tata_call_static(
        db: AsyncSession,
        to: str,
        from_: str,
        voice_session_id: UUID,
        agent_id: UUID,
        company_id: Optional[UUID] = None
    ) -> str:
        """
        Place outbound call via Tata Tele Click-to-Call Support API.

        The Click-to-Call Support API works in reverse:
        1. Customer receives the call first
        2. Once customer answers, a second call connects to the destination/agent

        API: POST https://api-smartflo.tatateleservices.com/v1/click_to_call_support

        Args:
            db: Database session for API key lookup
            to: Destination phone number (customer)
            from_: Caller ID (DID number)
            voice_session_id: VoiceSession UUID
            agent_id: Agent UUID
            company_id: Company UUID for API key lookup

        Returns:
            Call SID/reference from Tata Tele
        """
        # 1. Retrieve Tata Tele API key from integration registry.
        # Prefer service_metadata["api_key"] — it is the click-to-call
        # credential specifically. encrypted_api_key is only a fallback: users
        # editing the integration (e.g. to add the hangup auth_token) have
        # overwritten it, which broke every placement with HTTP 422.
        config_service = ConfigService(db)
        entry = await config_service.get_integration_by_provider(
            company_id=company_id,
            provider_name="tata_tele",
        )
        api_key = (entry.service_metadata or {}).get("api_key") if entry else None
        if not api_key:
            api_key = await config_service.get_api_key_by_provider(
                company_id=company_id,
                provider_name="tata_tele"
            )

        if not api_key:
            raise ValueError(
                "Tata Tele API key not found. Please ensure you have a 'tata_tele' "
                "integration configured in the Integration Registry with the "
                "click-to-call api_key in service_metadata."
            )

        # 2. Clean phone numbers
        # Remove '+' prefix and country code formatting if present
        customer_number = to.lstrip("+")
        caller_id = from_.lstrip("+")

        # 3. Build request payload
        payload = {
            "customer_number": customer_number,
            "api_key": api_key,
            "async": 1,  # Non-blocking, allows concurrent calls
            "customer_ring_timeout": 30,  # Max ring time in seconds
            "caller_id": caller_id,
            "custom_identifier": str(voice_session_id),  # For correlating callbacks
        }

        # 4. Make API call
        api_url = "https://api-smartflo.tatateleservices.com/v1/click_to_call_support"

        headers = {
            "Authorization": api_key,
            "Content-Type": "application/json"
        }

        logger.info(
            f"Tata Tele Click-to-Call Support: {from_} → {to}, "
            f"session={voice_session_id}"
        )

        async with httpx.AsyncClient() as client:
            response = await client.post(
                api_url,
                json=payload,
                headers=headers,
                timeout=30.0
            )

        # 5. Parse response
        response_data = response.json()
        logger.info(f"Tata Tele API response: {response.status_code} - {response_data}")

        if response.status_code in [200, 201]:
            # Extract call reference/SID from response
            # When async=1, the API returns ref_id (call_id comes later via webhook)
            call_sid = (
                response_data.get("call_id")
                or response_data.get("callId")
                or response_data.get("ref_id")
                or response_data.get("id")
                or f"TT_{voice_session_id}"
            )
            logger.info(f"Tata Tele call initiated successfully: {call_sid}")
            return str(call_sid)
        else:
            error_msg = response_data.get("message") or response_data.get("error") or str(response_data)
            raise Exception(
                f"Tata Tele Click-to-Call Support API error "
                f"(HTTP {response.status_code}): {error_msg}"
            )

    @staticmethod
    async def _increment_stat(db: AsyncSession, campaign_id: UUID, stat: str):
        """Increment a campaign statistic counter using the given DB session."""
        result = await db.execute(
            select(Campaign).where(Campaign.id == campaign_id)
        )
        campaign = result.scalar_one_or_none()

        if campaign:
            current_value = getattr(campaign, stat, 0) or 0
            await db.execute(
                update(Campaign)
                .where(Campaign.id == campaign_id)
                .values({stat: current_value + 1})
            )
            await db.commit()

    # ── Instance methods (for non-worker use, e.g. pause/stop from API) ──

    async def start_campaign(self, campaign_id: UUID):
        """
        Start executing a campaign (instance method for backward compat).

        Delegates to the standalone classmethod for actual execution.
        """
        await self.start_campaign_standalone(campaign_id)

    async def pause_campaign(self, campaign_id: UUID):
        """
        Pause a running campaign.

        Args:
            campaign_id: Campaign UUID
        """
        await self._update_campaign_status(campaign_id, "paused")
        logger.info(f"Paused campaign {campaign_id}")

    async def stop_campaign(self, campaign_id: UUID):
        """
        Stop a campaign completely.

        Args:
            campaign_id: Campaign UUID
        """
        await self._update_campaign_status(campaign_id, "completed")
        logger.info(f"Stopped campaign {campaign_id}")

    async def _update_campaign_status(self, campaign_id: UUID, status: str):
        """Update campaign status."""
        updates = {"status": status, "updated_at": datetime.utcnow()}

        if status == "running":
            updates["started_at"] = datetime.utcnow()
        elif status == "completed":
            updates["completed_at"] = datetime.utcnow()

        await self.db.execute(
            update(Campaign)
            .where(Campaign.id == campaign_id)
            .values(**updates)
        )
        await self.db.commit()

    # ── Legacy wrappers (kept for backward compat) ─────────────────────

    async def _place_twilio_call(self, **kwargs) -> str:
        """Legacy wrapper — delegates to static method."""
        return await self._place_twilio_call_static(db=self.db, **kwargs)

    async def _place_tata_call(self, **kwargs) -> str:
        """Legacy wrapper — delegates to static method."""
        return await self._place_tata_call_static(db=self.db, **kwargs)
