"""
Webhook router for Twilio and Tata Tele voice/WhatsApp integrations.

Handles incoming call webhooks and generates appropriate TwiML/JSON responses.
"""
import logging
from datetime import datetime
from fastapi import APIRouter, Request, Response, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update as sa_update
from uuid import UUID
import os

from src.common.database import get_db
from src.voice.session_manager import SessionManager
from src.voice.number_router import NumberRouter
from src.common.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/voice", tags=["Voice Webhooks"])


async def get_session_manager(db: AsyncSession = Depends(get_db)) -> SessionManager:
    """Dependency to get SessionManager instance."""
    return SessionManager(db)


async def get_number_router(db: AsyncSession = Depends(get_db)) -> NumberRouter:
    """Dependency to get NumberRouter instance."""
    return NumberRouter(db)


@router.post("/twilio/incoming")
async def twilio_incoming_call(
    request: Request,
    session_manager: SessionManager = Depends(get_session_manager),
    number_router: NumberRouter = Depends(get_number_router)
):
    """
    Webhook called by Twilio when an inbound call arrives.
    Must return TwiML to establish Media Stream.
    
    Twilio sends form data with:
    - CallSid: Unique call identifier
    - From: Caller's phone number
    - To: Called number (our Twilio number)
    - CallStatus: Call status (ringing, in-progress, etc.)
    """
    form_data = await request.form()
    
    call_sid = form_data.get("CallSid")
    from_number = form_data.get("From")
    to_number = form_data.get("To")
    call_status = form_data.get("CallStatus")
    
    logger.info(f"Twilio incoming call: {call_sid} from {from_number} to {to_number}")
    
    # 1. Find customer by phone number
    customer_assignment = await number_router.find_customer_by_number(to_number)
    
    if not customer_assignment:
        logger.warning(f"No customer found for number {to_number}")
        # Return TwiML to reject call or play error message
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">Sorry, this number is not configured. Please contact support.</Say>
    <Hangup/>
</Response>"""
        return Response(content=twiml, media_type="application/xml")
    # 2. Pre-call credit check — reject if balance below minimum threshold
    try:
        from src.billing.credit_service import CreditService
        credit_svc = CreditService(db)
        balance = await credit_svc.get_balance(customer_assignment.company_id)
        if balance["total_available"] < 0.10:
            logger.warning(
                f"Insufficient credits for inbound call on {to_number} "
                f"(company {customer_assignment.company_id}, available: ${balance['total_available']:.4f})"
            )
            twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">Sorry, this service is temporarily unavailable due to insufficient credits. Please contact your administrator.</Say>
    <Hangup/>
</Response>"""
            return Response(content=twiml, media_type="application/xml")
    except Exception as credit_err:
        logger.warning(f"Pre-call credit check failed (allowing call): {credit_err}")
    
    # 3. Create session in database
    session = await session_manager.create_voice_session(
        company_id=customer_assignment.company_id,
        customer_id=customer_assignment.customer_id,
        agent_id=customer_assignment.agent_id,
        phone_number=to_number,
        provider="twilio",
        call_sid=call_sid,
        direction="inbound",
        metadata={
            "from": from_number,
            "to": to_number,
            "call_status": call_status
        }
    )
    
    # 3. Fetch agent to determine greeting strategy (Issue 6: Option A for incoming)
    from src.ai.models import HierarchicalEntity
    agent = await session_manager.db.get(HierarchicalEntity, customer_assignment.agent_id)
    
    greeting_xml = '<Say voice="alice">Please wait while we connect you.</Say>'
    if agent:
        metadata = agent.metadata_extensions or {}
        identity = agent.identity or {}
        
        # Option A: Pre-recorded audio for Incoming Calls
        greeting_audio_url = metadata.get("greeting_audio_url")
        if greeting_audio_url:
            greeting_xml = f'<Play>{greeting_audio_url}</Play>'
        else:
            greeting_text = identity.get("greeting") or metadata.get("greeting_text")
            if greeting_text:
                greeting_xml = f'<Say voice="alice">{greeting_text}</Say>'

    # 4. Generate WebSocket URL for streaming
    streaming_host = settings.STREAMING_HOST or "localhost:8002"
    # Use configured protocol or auto-detect
    ws_protocol = settings.STREAMING_PROTOCOL or ("wss" if "https" in streaming_host or not streaming_host.startswith("localhost") else "ws")
    ws_url = f"{ws_protocol}://{streaming_host}/stream/twilio/{session.id}"
    
    logger.info(f"Created session {session.id}, streaming to {ws_url}")
    
    # 5. Return TwiML with <Connect><Stream>
    # This establishes the WebSocket connection for bidirectional audio
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    {greeting_xml}
    <Connect>
        <Stream url="{ws_url}" />
    </Connect>
</Response>"""
    
    return Response(content=twiml, media_type="application/xml")


@router.post("/twilio/status")
async def twilio_status_callback(
    request: Request,
    session_manager: SessionManager = Depends(get_session_manager)
):
    """
    Webhook called by Twilio for call status updates.

    Twilio sends:
    - CallSid: Call identifier
    - CallStatus: completed, busy, failed, no-answer, canceled
    - CallDuration: Duration in seconds

    This handler:
    1. Finds the VoiceSession (using status-agnostic lookup, since the
       WebSocket cleanup may have already marked the session completed)
    2. Stores any recording URL as an artifact
    3. Updates the VoiceSession with final status/duration
    4. Updates the linked CampaignCall status, outcome, duration
    5. Increments the campaign counter (completed/failed)
    """
    form_data = await request.form()

    call_sid = form_data.get("CallSid")
    call_status = form_data.get("CallStatus")
    call_duration = form_data.get("CallDuration")
    recording_url = form_data.get("RecordingUrl")
    answered_by = form_data.get("AnsweredBy")  # Async AMD result

    logger.info(
        f"Twilio status callback: {call_sid} status={call_status} "
        f"duration={call_duration} recording={bool(recording_url)} "
        f"answered_by={answered_by}"
    )

    # ── Step 1: Find session (status-agnostic to handle race with cleanup) ──
    session = await session_manager.get_voice_session_by_call_sid_any_status(call_sid)

    if not session:
        logger.warning(f"No VoiceSession found for Twilio status callback: call_sid={call_sid}")
        return {"status": "ok", "message": "No matching session found"}

    db = session_manager.db
    duration = int(call_duration) if call_duration else None

    # ── Step 1b: Async AMD result — machine answered → hang up now ──────
    # AMD callbacks arrive separately from terminal status callbacks (the
    # stream handler runs in another process, so the REST hangup is the only
    # cross-process-safe disconnect).
    from src.voice.call_guards import is_twilio_machine
    if answered_by:
        if is_twilio_machine(answered_by):
            logger.info(
                f"Twilio AMD detected machine ({answered_by}) for {call_sid} — hanging up"
            )
            try:
                from src.ai.campaign_models import CampaignCall
                await db.execute(
                    sa_update(CampaignCall)
                    .where(CampaignCall.voice_session_id == session.id)
                    .values(
                        status="completed-voicemail",
                        outcome="voicemail",
                        disposition="voicemail",
                        outcome_notes=f"twilio_amd={answered_by}",
                        completed_at=datetime.utcnow(),
                    )
                )
                await db.commit()
            except Exception as e:
                logger.warning(f"Failed to mark CampaignCall voicemail: {e}")
                await db.rollback()
            try:
                from src.voice.twilio_api import hangup_twilio_call
                await hangup_twilio_call(db, session.company_id, call_sid)
            except Exception as e:
                logger.error(f"Twilio AMD hangup failed for {call_sid}: {e}")
            return {"status": "ok", "answered_by": answered_by, "action": "hangup"}
        else:
            logger.info(f"Twilio AMD: {answered_by} for {call_sid} — continuing")

    # ── Step 2: Save recording reference if available ───────────────────
    if recording_url:
        try:
            from src.ai.artifact_models import Artifact
            recording_artifact = Artifact(
                company_id=session.company_id,
                origin="system-generated",
                file_category="recordings",
                file_name=f"recording_{call_sid}.wav",
                file_path=recording_url,  # Twilio-hosted URL
                mime_type="audio/wav",
                purpose=f"Call recording for session {session.id}",
                generated_by="twilio:recording",
                artifact_metadata={"session_id": str(session.id), "call_sid": call_sid, "source": "twilio"}
            )
            db.add(recording_artifact)
        except Exception as e:
            logger.warning(f"Failed to save recording artifact: {e}")

    # ── Step 3: Update VoiceSession with final status ───────────────────
    if call_status in ["completed", "busy", "failed", "no-answer", "canceled"]:
        # Only update if the session hasn't already been ended by cleanup
        if session.status not in ["ended", "completed"]:
            from src.voice.models import VoiceSession
            session_updates = {
                "status": "ended",
                "ended_at": datetime.utcnow(),
            }
            if duration and duration > 0:
                session_updates["duration_seconds"] = duration
            try:
                await db.execute(
                    sa_update(VoiceSession)
                    .where(VoiceSession.id == session.id)
                    .values(**session_updates)
                )
            except Exception as e:
                logger.warning(f"Failed to update VoiceSession status: {e}")

    # ── Step 4: Determine call outcome ──────────────────────────────────
    status_lower = (call_status or "").lower()
    if status_lower == "completed":
        if duration and duration > 0:
            call_outcome = "completed"
            outcome_detail = "answered"
        else:
            # completed with 0 duration = call ended before being answered
            call_outcome = "failed"
            outcome_detail = "no_answer"
    elif status_lower == "busy":
        call_outcome = "failed"
        outcome_detail = "busy"
    elif status_lower == "no-answer":
        call_outcome = "failed"
        outcome_detail = "no_answer"
    elif status_lower == "canceled":
        # canceled = caller or callee rejected/hung up before answering
        call_outcome = "failed"
        outcome_detail = "rejected"
    elif status_lower == "failed":
        call_outcome = "failed"
        outcome_detail = "failed"
    else:
        # Non-terminal statuses (initiated, ringing, in-progress) — skip CampaignCall update
        try:
            await db.commit()
        except Exception:
            await db.rollback()
        return {"status": "ok"}

    # ── Step 5: Update linked CampaignCall ──────────────────────────────
    try:
        from src.ai.campaign_models import Campaign, CampaignCall

        cc_result = await db.execute(
            select(CampaignCall).where(
                CampaignCall.voice_session_id == session.id
            )
        )
        campaign_call = cc_result.scalar_one_or_none()

        if campaign_call:
            old_status = campaign_call.status

            # In-call detection already finalized this record (e.g. voicemail);
            # only backfill timing fields, never the status/outcome/disposition.
            if old_status == "completed-voicemail":
                await db.execute(
                    sa_update(CampaignCall)
                    .where(CampaignCall.id == campaign_call.id)
                    .values(
                        completed_at=datetime.utcnow(),
                        duration_seconds=duration if duration and duration > 0 else None,
                    )
                )
                await db.commit()
                return {"status": "ok", "session_id": str(session.id), "outcome": "voicemail"}

            # Structured disposition from the telephony outcome; answered calls
            # stay NULL until the post-call LLM classification fills them.
            disposition = (
                outcome_detail
                if outcome_detail in ("busy", "no_answer", "rejected", "failed")
                else None
            )

            values = dict(
                status=call_outcome,
                outcome=outcome_detail,
                outcome_notes=f"twilio_status={call_status}",
                completed_at=datetime.utcnow(),
                duration_seconds=duration if duration and duration > 0 else None,
            )
            if disposition:
                values["disposition"] = disposition

            await db.execute(
                sa_update(CampaignCall)
                .where(CampaignCall.id == campaign_call.id)
                .values(**values)
            )

            # Increment campaign counter only if transitioning from "calling"
            if old_status == "calling" and campaign_call.campaign_id:
                stat_field = "calls_completed" if call_outcome == "completed" else "calls_failed"
                camp_result = await db.execute(
                    select(Campaign).where(Campaign.id == campaign_call.campaign_id)
                )
                campaign = camp_result.scalar_one_or_none()
                if campaign:
                    current_val = getattr(campaign, stat_field, 0) or 0
                    await db.execute(
                        sa_update(Campaign)
                        .where(Campaign.id == campaign.id)
                        .values({stat_field: current_val + 1})
                    )

            logger.info(
                f"Updated CampaignCall {campaign_call.id}: "
                f"{old_status} → {call_outcome} ({outcome_detail})"
            )
    except Exception as e:
        logger.warning(f"Failed to update CampaignCall: {e}")

    # Commit all changes
    try:
        await db.commit()
    except Exception as e:
        logger.error(f"Failed to commit Twilio status updates: {e}")
        await db.rollback()

    return {"status": "ok", "session_id": str(session.id), "outcome": call_outcome}


@router.post("/twilio/outbound-twiml")
async def twilio_outbound_twiml(
    request: Request,
    session_manager: SessionManager = Depends(get_session_manager)
):
    """
    TwiML webhook for outbound Twilio calls.
    
    When the campaign executor places an outbound call via Twilio,
    it specifies this URL. Twilio fetches this URL when the call connects.
    
    We return TwiML with <Connect><Stream> to establish a WebSocket
    for bidirectional audio streaming, similar to inbound call handling.
    
    Query params:
    - session_id: VoiceSession UUID (created by campaign executor)
    """
    # Get session_id from query params
    session_id = request.query_params.get("session_id")
    
    if not session_id:
        logger.error("No session_id in outbound TwiML request")
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">An error occurred. Please try again later.</Say>
    <Hangup/>
</Response>"""
        return Response(content=twiml, media_type="application/xml")
    
    # Parse form data from Twilio
    form_data = await request.form()
    call_sid = form_data.get("CallSid")
    from_number = form_data.get("From")
    to_number = form_data.get("To")
    
    logger.info(f"Twilio outbound TwiML: session_id={session_id}, call_sid={call_sid}, from={from_number}, to={to_number}")
    
    try:
        session_uuid = UUID(session_id)
        session = await session_manager.get_voice_session(session_uuid)
        
        if not session:
            logger.error(f"Session not found: {session_id}")
            twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">Sorry, this session is no longer available.</Say>
    <Hangup/>
</Response>"""
            return Response(content=twiml, media_type="application/xml")
        
        # Update session with the real call_sid from Twilio
        if session.call_sid and session.call_sid.startswith("pending_"):
            await session_manager.update_session_call_sid(session.id, call_sid)
        
        # Generate WebSocket URL for streaming
        streaming_host = settings.STREAMING_HOST or "localhost:8002"
        # Use configured protocol or auto-detect
        ws_protocol = settings.STREAMING_PROTOCOL or ("wss" if "https" in streaming_host or not streaming_host.startswith("localhost") else "ws")
        ws_url = f"{ws_protocol}://{streaming_host}/stream/twilio/{session.id}"
        
        logger.info(f"Outbound call connected, streaming to {ws_url}")
        
        # Determine Greeting XML
        from src.ai.models import HierarchicalEntity
        agent = await session_manager.db.get(HierarchicalEntity, session.agent_id)
        
        greeting_xml = ''
        if agent:
            metadata = agent.metadata_extensions or {}
            identity = agent.identity or {}
            
            # Option B: Use TTS for Outgoing Calls
            greeting_text = identity.get("greeting") or metadata.get("greeting_text")
            if greeting_text:
                greeting_xml = f'<Say voice="alice">{greeting_text}</Say>'
        
        # Return TwiML with <Connect><Stream> for bidirectional audio
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    {greeting_xml}
    <Connect>
        <Stream url="{ws_url}" />
    </Connect>
</Response>"""
        
        return Response(content=twiml, media_type="application/xml")
        
    except ValueError as e:
        logger.error(f"Invalid session_id format: {session_id}")
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">An error occurred. Please try again later.</Say>
    <Hangup/>
</Response>"""
        return Response(content=twiml, media_type="application/xml")
    except Exception as e:
        logger.error(f"Error in outbound TwiML webhook: {e}", exc_info=True)
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">An error occurred. Please try again later.</Say>
    <Hangup/>
</Response>"""
        return Response(content=twiml, media_type="application/xml")


@router.get("/tata/incoming")
async def tata_incoming_verification(request: Request):
    """
    GET handler for Tata Tele webhook verification.

    Tata Tele sends a GET request to verify the webhook URL is reachable
    before sending actual call events via POST. Returns 200 OK.
    """
    logger.info(f"Tata Tele webhook verification GET from {request.client.host if request.client else 'unknown'}")
    return {"status": "ok", "message": "Tata Tele webhook endpoint active"}


@router.post("/tata/incoming")
async def tata_incoming_call(
    request: Request,
    session_manager: SessionManager = Depends(get_session_manager),
    number_router: NumberRouter = Depends(get_number_router)
):
    """
    Webhook called by Tata Tele when inbound call arrives.
    Must return JSON with WebSocket URL (Dynamic Endpoint).
    
    Tata Tele sends JSON with:
    - callId: Unique call identifier
    - fromNumber: Caller's phone number
    - toNumber: Called number
    - status: Call status
    """
    # Parse body — handle both JSON and form-encoded data
    content_type = request.headers.get("content-type", "")
    raw_body = await request.body()
    logger.info(f"Tata Tele incoming POST: content-type={content_type}, body_len={len(raw_body)}, raw={raw_body[:500]}")
    
    try:
        if "json" in content_type:
            data = await request.json()
        elif "form" in content_type:
            form = await request.form()
            data = dict(form)
        elif raw_body:
            # Try JSON first, then form
            import json as _json
            try:
                data = _json.loads(raw_body)
            except Exception:
                from urllib.parse import parse_qs
                parsed = parse_qs(raw_body.decode("utf-8", errors="replace"))
                data = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
        else:
            data = {}
    except Exception as e:
        logger.error(f"Failed to parse Tata POST body: {e}")
        data = {}
    
    # Log the parsed data
    logger.info(f"Tata Tele incoming call PARSED data: {data}")
    
    # Extract fields — try multiple possible field names since Tata Tele's
    # API may use different names than documented
    call_id = (
        data.get("callId")
        or data.get("call_id")
        or data.get("callSid")
        or data.get("call_sid")
        or data.get("id")
    )
    from_number = (
        data.get("fromNumber")
        or data.get("from_number")
        or data.get("from")
        or data.get("caller_id_number")
        or data.get("caller_number")
        or data.get("source")
    )
    to_number = (
        data.get("toNumber")
        or data.get("to_number")
        or data.get("to")
        or data.get("destination")
        or data.get("did_number")
        or data.get("called_number")
    )
    status = data.get("status") or data.get("call_status")
    custom_identifier = data.get("custom_identifier") or data.get("customIdentifier")
    
    logger.info(f"Tata Tele incoming call: {call_id} from {from_number} to {to_number}, custom_id={custom_identifier}")
    
    # 1. Try to resume existing session (Outbound Campaign)
    if custom_identifier and custom_identifier != "null":
        try:
            session_id = UUID(custom_identifier)
            session = await session_manager.get_voice_session(session_id)
            if session:
                logger.info(f"Resuming existing session {session.id} for outbound campaign")
                
                # Update session with call_sid if it was temporary
                if session.call_sid and session.call_sid.startswith("pending_"):
                    await session_manager.update_session_call_sid(session.id, call_id)
                
                # Generate WebSocket URL
                streaming_host = settings.STREAMING_HOST or "localhost:8002"
                ws_protocol = settings.STREAMING_PROTOCOL or ("wss" if "https" in streaming_host or not streaming_host.startswith("localhost") else "ws")
                ws_url = f"{ws_protocol}://{streaming_host}/stream/tata/{session.id}"
                
                return {
                    "sucess": True,
                    "wss_url": ws_url
                }
        except ValueError:
            logger.warning(f"Invalid custom_identifier format: {custom_identifier}")
        except Exception as e:
            logger.error(f"Error resuming session: {e}")

    # 2. Find context by phone number (Inbound)
    # Check both numbers to see which one is our DID
    customer_assignment = await number_router.find_customer_by_number(to_number)
    
    # If not found by to_number, try from_number (in case of directionality confusion or click-to-call logic)
    if not customer_assignment:
         customer_assignment = await number_router.find_customer_by_number(from_number)

    if not customer_assignment:
        logger.warning(f"No configured number found for call {from_number} -> {to_number}")
        return {
            "sucess": False,
            "error": "Number not configured"
        }
    # 3. Pre-call credit check — reject if balance below minimum threshold
    try:
        from src.billing.credit_service import CreditService
        credit_svc = CreditService(db)
        balance = await credit_svc.get_balance(customer_assignment.company_id)
        if balance["total_available"] < 0.10:
            logger.warning(
                f"Insufficient credits for inbound Tata call on {to_number} "
                f"(company {customer_assignment.company_id}, available: ${balance['total_available']:.4f})"
            )
            return {
                "sucess": False,
                "error": "Insufficient credits for this service"
            }
    except Exception as credit_err:
        logger.warning(f"Pre-call credit check failed (allowing call): {credit_err}")
    
    # 4. Create NEW session (Inbound Flow)
    session = await session_manager.create_voice_session(
        company_id=customer_assignment.company_id,
        customer_id=customer_assignment.customer_id,
        agent_id=customer_assignment.agent_id,
        phone_number=from_number if customer_assignment.phone_number == to_number else to_number,
        provider="tata_tele",
        call_sid=call_id,
        direction="inbound",
        metadata=data
    )
    
    # 4. Generate WebSocket URL
    streaming_host = settings.STREAMING_HOST or "localhost:8002"
    ws_protocol = settings.STREAMING_PROTOCOL or ("wss" if "https" in streaming_host or not streaming_host.startswith("localhost") else "ws")
    ws_url = f"{ws_protocol}://{streaming_host}/stream/tata/{session.id}"
    
    logger.info(f"Created new Tata session {session.id}, streaming to {ws_url}")
    
    return {
        "sucess": True,
        "wss_url": ws_url
    }


@router.get("/tata/status")
async def tata_status_callback_get(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    GET handler for Tata Tele status webhook.

    Tata Tele sends call status updates as GET requests with query parameters
    (not POST). This handler parses the query params and delegates to the
    shared processing logic.
    """
    data = dict(request.query_params)
    logger.info(f"Tata Tele status GET callback: {len(data)} params")
    return await _process_tata_status(data, db)


@router.post("/tata/status")
async def tata_status_callback(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    POST handler for Tata Tele call status webhooks.
    Parses body (JSON or form-encoded) and delegates to shared processor.
    """
    content_type = request.headers.get("content-type", "")
    raw_body = await request.body()
    logger.info(f"Tata Tele status POST: content-type={content_type}, body_len={len(raw_body)}")

    try:
        if "json" in content_type:
            data = await request.json()
        elif "form" in content_type:
            form = await request.form()
            data = dict(form)
        elif raw_body:
            import json as _json
            try:
                data = _json.loads(raw_body)
            except Exception:
                from urllib.parse import parse_qs
                parsed = parse_qs(raw_body.decode("utf-8", errors="replace"))
                data = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
        else:
            data = {}
    except Exception as e:
        logger.error(f"Failed to parse Tata status POST body: {e}")
        data = {}

    return await _process_tata_status(data, db)


async def _process_tata_status(data: dict, db: AsyncSession):
    """
    Shared Tata Tele status processing logic used by both GET and POST handlers.

    Tata Tele sends call status data with fields including:
    - call_status / $call_status: "answered" or "missed"
    - hangup_cause_key / hangup_cause / $hangup_cause: Reason for hangup
    - custom_identifier / ref_id / $ref_id: VoiceSession UUID
    - call_id / $call_id: Tata's internal call ID
    - uuid / $uuid: Connection-level identifier
    - duration / $duration: Call duration in seconds
    - call_connected / $call_connected: Boolean (1 or 0)
    - recording_url: URL to call recording

    This handler:
    1. Correlates the event to a VoiceSession via custom_identifier / ref_id / call_id
    2. Updates the linked CampaignCall status and outcome
    3. Stores the recording URL as an artifact
    4. Increments the correct campaign counter (completed/failed)
    """
    logger.info(f"Tata Tele status callback data keys: {list(data.keys())}")

    # Extract relevant fields — Tata uses varying field names between
    # GET query params and POST body. We check all known variants.
    ref_id = (
        data.get("custom_identifier") or data.get("ref_id")
        or data.get("$ref_id") or data.get("refId")
    )
    call_id = data.get("call_id") or data.get("$call_id") or data.get("callId")
    uuid_field = data.get("uuid") or data.get("$uuid")
    call_status = data.get("call_status") or data.get("$call_status") or ""
    hangup_cause = (
        data.get("hangup_cause_key") or data.get("hangup_cause")
        or data.get("$hangup_cause") or ""
    )
    recording_url = data.get("recording_url") or data.get("$recording_url") or ""
    duration_str = data.get("duration") or data.get("$duration") or "0"
    billsec_str = data.get("billsec") or data.get("$billsec") or "0"
    call_connected = data.get("call_connected") or data.get("$call_connected")
    customer_number = data.get("customer_number") or data.get("$customer_number") or ""
    direction = data.get("direction") or data.get("$direction") or ""

    logger.info(
        f"Tata Tele status: ref_id={ref_id}, call_id={call_id}, "
        f"status={call_status}, hangup={hangup_cause}, "
        f"connected={call_connected}, duration={duration_str}"
    )

    # Try to parse duration as integer
    try:
        duration = int(duration_str)
    except (ValueError, TypeError):
        duration = 0

    # ── Step 1: Find the VoiceSession ────────────────────────────────────
    # custom_identifier / ref_id from Tata corresponds to our VoiceSession UUID.
    from src.voice.models import VoiceSession
    from sqlalchemy import or_

    voice_session = None

    # Strategy 1: custom_identifier/ref_id matches VoiceSession UUID
    if ref_id:
        try:
            session_uuid = UUID(ref_id)
            result = await db.execute(
                select(VoiceSession).where(VoiceSession.id == session_uuid)
            )
            voice_session = result.scalar_one_or_none()
        except (ValueError, Exception):
            pass

    # Strategy 2: Match by call_sid (call_id or uuid from Tata)
    if not voice_session and (call_id or uuid_field):
        search_sids = [s for s in [call_id, uuid_field] if s]
        for sid in search_sids:
            result = await db.execute(
                select(VoiceSession).where(
                    VoiceSession.call_sid == sid,
                    VoiceSession.provider == "tata_tele"
                ).order_by(VoiceSession.started_at.desc()).limit(1)
            )
            voice_session = result.scalar_one_or_none()
            if voice_session:
                break

    if not voice_session:
        logger.warning(
            f"No VoiceSession found for Tata status callback: "
            f"ref_id={ref_id}, call_id={call_id}, uuid={uuid_field}"
        )
        return {"status": "ok", "message": "No matching session found"}

    logger.info(f"Matched Tata status to VoiceSession {voice_session.id}")

    # ── Step 2: Determine call outcome ──────────────────────────────────
    status_lower = call_status.lower() if call_status else ""
    is_connected = call_connected in (True, "true", "True", "1", 1)

    if status_lower == "answered" or (is_connected and duration > 0):
        call_outcome = "completed"
        outcome_detail = "answered"
    elif status_lower == "missed":
        call_outcome = "failed"
        outcome_detail = hangup_cause or "missed"
    elif hangup_cause:
        # Map common hangup causes — covers Tata Tele, Twilio, and SIP causes
        cause_lower = hangup_cause.lower()
        if any(x in cause_lower for x in ["busy", "user_busy"]):
            call_outcome = "failed"
            outcome_detail = "busy"
        elif any(x in cause_lower for x in [
            "no_answer", "no answer", "originator_cancel",
            "no_user_response", "recovery_on_timer_expire",
        ]):
            call_outcome = "failed"
            outcome_detail = "no_answer"
        elif any(x in cause_lower for x in [
            "call_rejected", "call_declined", "rejected",
        ]):
            call_outcome = "failed"
            outcome_detail = "rejected"
        elif any(x in cause_lower for x in [
            "subscriber_absent", "destination_out_of_order",
            "network_out_of_order", "temporary_failure",
        ]):
            call_outcome = "failed"
            outcome_detail = "unreachable"
        elif any(x in cause_lower for x in ["unallocated", "invalid", "unassigned"]):
            call_outcome = "failed"
            outcome_detail = "invalid_number"
        elif any(x in cause_lower for x in ["normal_clearing", "normal"]):
            # normal_clearing with duration > 0 means call was answered and ended normally
            if duration > 0:
                call_outcome = "completed"
                outcome_detail = "normal_clearing"
            else:
                # normal_clearing with 0 duration = call ended before being answered
                call_outcome = "failed"
                outcome_detail = "no_answer"
        elif any(x in cause_lower for x in ["normal_unspecified"]):
            call_outcome = "failed" if duration == 0 else "completed"
            outcome_detail = "unspecified" if duration == 0 else "answered"
        else:
            call_outcome = "failed"
            outcome_detail = hangup_cause
    else:
        # No hangup cause — fallback based on whether call connected and had duration
        if is_connected and duration > 0:
            call_outcome = "completed"
            outcome_detail = "answered"
        else:
            call_outcome = "failed"
            outcome_detail = "no_answer"

    # ── Step 3: Update VoiceSession ─────────────────────────────────────
    try:
        session_updates = {
            "status": "ended",
            "ended_at": datetime.utcnow(),
        }
        if duration > 0:
            session_updates["duration_seconds"] = duration

        await db.execute(
            sa_update(VoiceSession)
            .where(VoiceSession.id == voice_session.id)
            .values(**session_updates)
        )
    except Exception as e:
        logger.warning(f"Failed to update VoiceSession status: {e}")

    # ── Step 4: Update linked CampaignCall ──────────────────────────────
    try:
        from src.ai.campaign_models import Campaign, CampaignCall

        # Find CampaignCall linked to this voice session
        cc_result = await db.execute(
            select(CampaignCall).where(
                CampaignCall.voice_session_id == voice_session.id
            )
        )
        campaign_call = cc_result.scalar_one_or_none()

        if campaign_call:
            old_status = campaign_call.status

            # In-call detection already finalized this record (e.g. voicemail);
            # only backfill timing fields, never the status/outcome/disposition.
            if old_status == "completed-voicemail":
                await db.execute(
                    sa_update(CampaignCall)
                    .where(CampaignCall.id == campaign_call.id)
                    .values(
                        completed_at=datetime.utcnow(),
                        duration_seconds=duration if duration > 0 else None,
                    )
                )
                await db.commit()
                return {
                    "status": "ok",
                    "session_id": str(voice_session.id),
                    "outcome": "voicemail",
                }

            # Structured disposition from the telephony outcome; answered calls
            # stay NULL until the post-call LLM classification fills them.
            _DISPOSITION_BY_DETAIL = {
                "busy": "busy",
                "no_answer": "no_answer",
                "missed": "no_answer",
                "rejected": "rejected",
                "unreachable": "failed",
                "invalid_number": "failed",
                "failed": "failed",
                "unspecified": "failed",
            }
            disposition = (
                _DISPOSITION_BY_DETAIL.get(outcome_detail)
                if call_outcome == "failed"
                else None
            )

            values = dict(
                status=call_outcome,
                outcome=outcome_detail,
                outcome_notes=f"hangup_cause={hangup_cause}, call_status={call_status}",
                completed_at=datetime.utcnow(),
                duration_seconds=duration if duration > 0 else None,
            )
            if call_outcome == "failed" and not disposition:
                disposition = "failed"
            if disposition:
                values["disposition"] = disposition

            await db.execute(
                sa_update(CampaignCall)
                .where(CampaignCall.id == campaign_call.id)
                .values(**values)
            )

            # Increment campaign counter only if transitioning from "calling"
            if old_status == "calling" and campaign_call.campaign_id:
                stat_field = "calls_completed" if call_outcome == "completed" else "calls_failed"
                camp_result = await db.execute(
                    select(Campaign).where(Campaign.id == campaign_call.campaign_id)
                )
                campaign = camp_result.scalar_one_or_none()
                if campaign:
                    current_val = getattr(campaign, stat_field, 0) or 0
                    await db.execute(
                        sa_update(Campaign)
                        .where(Campaign.id == campaign.id)
                        .values({stat_field: current_val + 1})
                    )

            logger.info(
                f"Updated CampaignCall {campaign_call.id}: "
                f"{old_status} → {call_outcome} ({outcome_detail})"
            )
    except Exception as e:
        logger.warning(f"Failed to update CampaignCall: {e}")

    # ── Step 5: Store recording URL as artifact ─────────────────────────
    if recording_url and recording_url.strip():
        try:
            from src.ai.artifact_models import Artifact
            recording_artifact = Artifact(
                company_id=voice_session.company_id,
                origin="system-generated",
                file_category="recordings",
                file_name=f"recording_{voice_session.id}.wav",
                file_path=recording_url,  # Tata-hosted URL
                mime_type="audio/wav",
                purpose=f"Call recording for session {voice_session.id}",
                generated_by="tata_tele:recording",
                artifact_metadata={
                    "session_id": str(voice_session.id),
                    "call_id": call_id or "",
                    "ref_id": ref_id or "",
                    "source": "tata_tele_webhook",
                }
            )
            db.add(recording_artifact)
            logger.info(f"Stored recording artifact for session {voice_session.id}")
        except Exception as e:
            logger.warning(f"Failed to save recording artifact: {e}")

    # Commit all changes
    try:
        await db.commit()
    except Exception as e:
        logger.error(f"Failed to commit Tata status updates: {e}")
        await db.rollback()

    return {"status": "ok", "session_id": str(voice_session.id), "outcome": call_outcome}


@router.post("/whatsapp/incoming")
async def whatsapp_incoming_message(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Webhook called by Twilio when WhatsApp message arrives.
    Process message and respond via Gemini.
    """
    from src.voice.whatsapp_handler import WhatsAppHandler
    from twilio.twiml.messaging_response import MessagingResponse
    
    logger.info("Processing Twilio webhook request")
    try:
        form_data = await request.form()
    except Exception as e:
        logger.error(f"Error parsing form data: {e}")
        return Response(content="Error parsing form data", status_code=400)
    
    from_number = form_data.get("From", "")
    to_number = form_data.get("To", "")
    message_body = form_data.get("Body", "")
    media_url = form_data.get("MediaUrl0")
    media_type = form_data.get("MediaContentType0")
    message_sid = form_data.get("MessageSid")
    
    logger.info(f"WhatsApp message (Twilio): {message_sid} from {from_number}")
    
    # Create handler
    handler = WhatsAppHandler(db)
    
    # Process message and get response
    response_text = await handler.handle_incoming_message(
        from_number=from_number,
        to_number=to_number,
        message_body=message_body,
        media_url=media_url,
        media_type=media_type,
        message_sid=message_sid,
        provider="twilio"
    )
    
    # Create TwiML response
    resp = MessagingResponse()
    resp.message(response_text)
    
    return Response(content=str(resp), media_type="application/xml")


@router.post("/tata/whatsapp/incoming")
async def tata_whatsapp_incoming(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Webhook called by Tata Tele for WhatsApp messages.
    """
    from src.voice.whatsapp_handler import WhatsAppHandler
    
    data = await request.json()
    logger.debug(f"Tata Tele WhatsApp payload: {data}")
    
    try:
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        
        if not messages:
            return {"status": "ok"} # Just a status notification
            
        message = messages[0]
        from_number = message.get("from") # E.g., "919876543210"
        
        # Tata sends metadata with display_phone_number which is our business number
        # Need to make sure we parse it correctly
        metadata = value.get("metadata", {})
        to_number = metadata.get("display_phone_number") or metadata.get("phone_number_id")
        
        message_id = message.get("id")
        msg_type = message.get("type")
        
        # Extract body based on type
        message_body = ""
        media_url = None
        media_type = None
        
        if msg_type == "text":
            message_body = message.get("text", {}).get("body", "")
        elif msg_type in ["image", "document", "audio", "video"]:
            media_obj = message.get(msg_type, {})
            # Note: For full implementation, we'd fetch media URL using media ID.
            # Assuming caption or placeholder for now.
            message_body = media_obj.get("caption", "[Media Message]")
            media_type = media_obj.get("mime_type")
            # media_url = ... (requires extra API call to get URL)
        
        logger.info(f"WhatsApp message (Tata): {message_id} from {from_number}")
        
        handler = WhatsAppHandler(db)
        
        # Tata handler sends response asynchronously via Messaging Service
        await handler.handle_incoming_message(
            from_number=from_number,
            to_number=to_number,
            message_body=message_body,
            media_url=media_url,
            media_type=media_type,
            message_sid=message_id,
            provider="tata_tele"
        )
        
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Error processing Tata webhook: {e}", exc_info=True)
        # Always return 200 to Tata/Meta so they don't retry indefinitely on logic errors
        return {"status": "error", "message": str(e)}
