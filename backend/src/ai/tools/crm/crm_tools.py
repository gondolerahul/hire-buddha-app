"""
CRM Integration Tools for Real Estate Tenant Voice Agents.

Four tools that enable a voice agent to:
  1. Check the current date/time (the business's time zone)
  2. Send WhatsApp messages via tenant's own WhatsApp system
  3. Schedule Google Calendar events for property visits
  4. Update lead status in tenant's CRM after a call

All tools resolve tenant-specific credentials from IntegrationRegistry
using the company_id passed via the extra_context dict. Whom they message,
invite or update is a subject of the run (``ai.governance.subjects``), never
a number, address or lead id the model chose (TL-09).
"""
import logging
import httpx
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from urllib.parse import quote
from uuid import UUID as _UUID

from pydantic import Field

from src.ai.governance.subjects import LEAD, recipient, scope_for
from src.ai.tools.base import Tool, ToolOutput, ToolParams

logger = logging.getLogger(__name__)


async def _business_now(company_id: Optional[str]) -> datetime:
    """Now in the company's time zone (Phase 14 WS1 1.10; was fixed IST)."""
    from src.common.timezones import company_timezone

    return datetime.now(await company_timezone(company_id))


# ---------------------------------------------------------------------------
# Helper: resolve IntegrationRegistry credentials for a tenant
# ---------------------------------------------------------------------------

async def _resolve_integration(
    company_id: str,
    provider_name: str,
) -> Dict[str, Any]:
    """
    Look up tenant-specific integration from IntegrationRegistry.

    Returns dict with 'api_key', 'service_metadata' and full integration
    fields, or empty dict if not found.
    """
    if not company_id:
        return {}

    try:
        from src.common.tenancy.session import control_session
        from sqlalchemy import select
        from src.config.models import IntegrationRegistry
        from src.common.security import decrypt_api_key

        async with control_session() as db:
            result = await db.execute(
                select(IntegrationRegistry).where(
                    IntegrationRegistry.company_id == _UUID(str(company_id)),
                    IntegrationRegistry.provider_name == provider_name,
                    IntegrationRegistry.status == "active",
                )
            )
            entry = result.scalars().first()

            if entry:
                from src.config.registry_secrets import registry_secret
                api_key = await registry_secret(entry)

                return {
                    "api_key": api_key,
                    "service_metadata": entry.service_metadata or {},
                    "provider_name": entry.provider_name,
                }
    except Exception as e:
        logger.error(f"Failed to resolve integration for {provider_name}: {e}")

    return {}


# ===========================================================================
# Tool 1: Get Current Date/Time
# ===========================================================================

class GetCurrentDateTimeParams(ToolParams):
    pass


class GetCurrentDateTimeTool(Tool):
    """
    Returns the current date, time, and day of the week in the business's
    time zone (the company's setting; Asia/Kolkata unless changed).

    Enables the voice agent to suggest visit dates, know business hours,
    and avoid scheduling on past dates.
    """
    name = "get_current_datetime"
    description = (
        "Get the current date, time, and day of the week in the business's time zone. "
        "Use this before suggesting dates for site visits or appointments."
    )
    Params = GetCurrentDateTimeParams

    async def execute(self, params: GetCurrentDateTimeParams, ctx: Dict[str, Any]) -> ToolOutput:
        now = await _business_now(ctx.get("company_id"))
        return ToolOutput(output={
            "datetime": f"{now.strftime('%A, %B %d, %Y %I:%M %p')} {now.tzname()}",
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%I:%M %p"),
            "day": now.strftime("%A"),
            "timezone": now.tzinfo.key,
            "iso": now.isoformat(),
        })


# ===========================================================================
# Tool 2: WhatsApp Send (Tenant's System)
# ===========================================================================

_CONTACT_REF = ("Ref of the contact from the run's Subjects list. May be omitted when the run has one "
                "contact with a {needs} (a voice call's caller).")
_RAW = "A raw {needs}: only for an agent that allows free recipients."


def _auth_headers(auth_type: str, api_key: str) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if auth_type == "bearer":
        headers["Authorization"] = f"Bearer {api_key}"
    elif auth_type == "api_key":
        headers["X-API-Key"] = api_key
    elif auth_type == "basic":
        import base64
        headers["Authorization"] = f"Basic {base64.b64encode(api_key.encode()).decode()}"
    return headers


class WhatsAppSendParams(ToolParams):
    message: str = Field(..., description="Message text to send")
    to_ref: Optional[str] = Field(None, description=_CONTACT_REF.format(needs="phone number"))
    to: Optional[str] = Field(None, description=_RAW.format(needs="phone number in E.164 format"))
    template_name: Optional[str] = Field(None, description="Optional template name for pre-approved template messages")
    media_url: Optional[str] = Field(None, description="Optional URL to a media file (brochure PDF, image, etc.)")


class WhatsAppSendTenantTool(Tool):
    """
    Send WhatsApp messages via the tenant's own WhatsApp system.

    Resolves the tenant's WhatsApp API URL and auth token from
    IntegrationRegistry (provider_name='whatsapp_tenant'). The number is a
    contact of the run's subject scope (TL-09).
    """
    name = "whatsapp_send_tenant"
    description = (
        "Send a WhatsApp message to a contact of this run (to_ref; on a call, the caller) via the "
        "company's own WhatsApp system. Use for visit confirmations, brochures or follow-ups."
    )
    Params = WhatsAppSendParams

    async def execute(self, params: WhatsAppSendParams, ctx: Dict[str, Any]) -> ToolOutput:
        company_id = ctx.get("company_id")
        if not company_id:
            return ToolOutput.failed("Missing company_id in execution context", code="no_context")
        to, error = recipient(await scope_for(ctx), ctx, ref=params.to_ref, raw=params.to,
                              needs="phone", field_name="to")
        if error:
            return ToolOutput.failed(error, code="recipient_not_in_scope")
        # WhatsApp's rules for messages the business starts (META-E5): free text in
        # the 24-hour window; outside it an approved template, to an opted-in contact.
        from src.messaging.rules import business_initiated_refusal

        refusal = await business_initiated_refusal(company_id, str(to), template=params.template_name)
        if refusal:
            return ToolOutput.failed(refusal, code="whatsapp_rules")

        integration = await _resolve_integration(company_id, "whatsapp_tenant")
        if not integration:
            return ToolOutput.failed(
                "No WhatsApp integration configured. "
                "Please register a 'whatsapp_tenant' integration in the Integration Registry.",
                code="no_connection")
        api_key = integration.get("api_key", "")
        metadata = integration.get("service_metadata", {})
        api_url = metadata.get("api_url", "")
        from_number = metadata.get("from_number", "")
        if not api_url:
            return ToolOutput.failed("WhatsApp integration missing 'api_url' in service_metadata", code="no_connection")

        payload: Dict[str, Any] = {
            "to": to,
            "message_type": "template" if params.template_name else "text",
            "body": params.message,
        }
        if params.template_name:
            payload["template_name"] = params.template_name
        if params.media_url:
            payload["media_url"] = params.media_url
        if from_number:
            payload["from"] = from_number
        payload["metadata"] = {"source": "hirebuddha_agent", "company_id": company_id}
        headers = _auth_headers(metadata.get("auth_type", "bearer"), api_key)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(api_url, json=payload, headers=headers)
        except httpx.TimeoutException:
            return ToolOutput.failed("WhatsApp API request timed out")
        except Exception as e:  # noqa: BLE001
            logger.error(f"[WhatsAppTenant] Error: {e}", exc_info=True)
            return ToolOutput.failed(str(e))
        if response.status_code not in (200, 201, 202):
            error_body = response.text[:500]
            logger.error(f"[WhatsAppTenant] API error {response.status_code}: {error_body}")
            return ToolOutput.failed(f"WhatsApp API returned {response.status_code}: {error_body}")
        result = response.json() if response.text else {}
        logger.info(f"[WhatsAppTenant] Message sent to {to}: {result}")
        return ToolOutput(output={
            "success": True,
            "message_id": result.get("message_id", result.get("id", "")),
            "status": result.get("status", "sent"),
            "to": to,
        })


# ===========================================================================
# Tool 3: Google Calendar Create Event
# ===========================================================================

class CalendarEventParams(ToolParams):
    title: str = Field(..., description="Event title (e.g. 'Site Visit - Prestige Lakeside Habitat')")
    start_datetime: str = Field(..., description="Start datetime in ISO-8601 format (e.g. '2026-05-10T11:00:00+05:30')")
    end_datetime: Optional[str] = Field(None, description="End datetime in ISO-8601 format. Defaults to 1 hour after start.")
    description: Optional[str] = Field(None, description="Event description with details")
    location: Optional[str] = Field(None, description="Event location / address")
    attendee_ref: Optional[str] = Field(
        None, description="Ref of the contact to invite, from the run's Subjects list. Omit for no invitee.")
    attendee_email: Optional[str] = Field(None, description=_RAW.format(needs="e-mail"))


class GoogleCalendarCreateEventTool(Tool):
    """
    Schedule events on Google Calendar for property visits.

    Resolves Google Calendar credentials from IntegrationRegistry
    (provider_name='google_calendar'). The invitee is a contact of the run's
    subject scope (TL-09).
    """
    name = "google_calendar_create_event"
    description = (
        "Schedule a property visit or appointment on the company's Google Calendar, optionally "
        "inviting a contact of this run (attendee_ref). Use after the customer agrees to a visit."
    )
    Params = CalendarEventParams

    async def execute(self, params: CalendarEventParams, ctx: Dict[str, Any]) -> ToolOutput:
        company_id = ctx.get("company_id")
        if not company_id:
            return ToolOutput.failed("Missing company_id in execution context", code="no_context")
        attendee = None
        if params.attendee_ref or params.attendee_email:
            attendee, error = recipient(await scope_for(ctx), ctx, ref=params.attendee_ref,
                                        raw=params.attendee_email, needs="email", field_name="attendee_email")
            if error:
                return ToolOutput.failed(error, code="recipient_not_in_scope")

        integration = await _resolve_integration(company_id, "google_calendar")
        if not integration:
            return ToolOutput.failed(
                "No Google Calendar integration configured. "
                "Please register a 'google_calendar' integration in the Integration Registry.",
                code="no_connection")
        metadata = integration.get("service_metadata", {})
        calendar_id = metadata.get("calendar_id", "primary")
        refresh_token = integration.get("api_key", "")  # Stored as the encrypted_api_key

        start_dt = params.start_datetime
        end_dt = params.end_datetime
        if not end_dt:
            try:
                end_dt = (datetime.fromisoformat(start_dt) + timedelta(hours=1)).isoformat()
            except ValueError:
                end_dt = start_dt

        access_token = await self._get_access_token(
            metadata.get("client_id", ""), metadata.get("client_secret", ""), refresh_token)
        if not access_token:
            return ToolOutput.failed("Failed to obtain Google Calendar access token")

        event_body: Dict[str, Any] = {
            "summary": params.title,
            "description": params.description or "",
            "start": {"dateTime": start_dt},
            "end": {"dateTime": end_dt},
        }
        if params.location:
            event_body["location"] = params.location
        if attendee:
            event_body["attendees"] = [{"email": attendee}]

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"https://www.googleapis.com/calendar/v3/calendars/{quote(calendar_id, safe='@')}/events",
                    json=event_body,
                    headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                    params={"sendUpdates": "all"} if attendee else {},
                )
        except Exception as e:  # noqa: BLE001
            logger.error(f"[GoogleCalendar] Error: {e}", exc_info=True)
            return ToolOutput.failed(str(e))
        if response.status_code not in (200, 201):
            error = response.text[:500]
            logger.error(f"[GoogleCalendar] API error {response.status_code}: {error}")
            return ToolOutput.failed(f"Google Calendar API returned {response.status_code}: {error}")
        result = response.json()
        logger.info(f"[GoogleCalendar] Event created: {result.get('id')}")
        return ToolOutput(output={
            "success": True,
            "event_id": result.get("id"),
            "html_link": result.get("htmlLink"),
            "start": result.get("start", {}).get("dateTime"),
            "end": result.get("end", {}).get("dateTime"),
            "summary": result.get("summary"),
            "attendee": attendee,
        })

    @staticmethod
    async def _get_access_token(
        client_id: str, client_secret: str, refresh_token: str
    ) -> Optional[str]:
        """Exchange a refresh token for a short-lived access token."""
        if not all([client_id, client_secret, refresh_token]):
            logger.error("[GoogleCalendar] Missing OAuth2 credentials")
            return None

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "grant_type": "refresh_token",
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "refresh_token": refresh_token,
                    },
                )
            if response.status_code == 200:
                return response.json().get("access_token")
            else:
                logger.error(f"[GoogleCalendar] Token refresh failed: {response.text}")
                return None
        except Exception as e:
            logger.error(f"[GoogleCalendar] Token refresh error: {e}")
            return None


# ===========================================================================
# Tool 4: CRM Update Lead
# ===========================================================================

class CRMUpdateLeadParams(ToolParams):
    call_outcome: str = Field(
        ..., description="Call outcome: interested, not_interested, callback_requested, no_answer, busy, invalid_number")
    summary: str = Field(..., description="Brief summary of the call conversation and key points discussed")
    lead_ref: Optional[str] = Field(
        None, description="Ref of the lead from the run's Subjects list. May be omitted when the run has one "
                          "lead (a campaign call's).")
    next_action: Optional[str] = Field(
        None, description="Next action to be taken (e.g. 'site_visit_scheduled', 'send_brochure', 'callback_tuesday')")
    next_action_date: Optional[str] = Field(None, description="Date/time for the next action in ISO-8601 format")
    lead_temperature: Optional[str] = Field(None, description="Lead temperature: hot, warm, or cold")


class CRMUpdateLeadTool(Tool):
    """
    Update lead status in tenant's CRM after a call completes.

    Resolves CRM API credentials from IntegrationRegistry
    (provider_name='crm_tenant'). The lead is one of the run's subjects — the
    campaign call's or the CRM event's — never an id the model chose (TL-09).
    """
    name = "crm_update_lead"
    description = (
        "Record a call's outcome, summary and next action on this run's lead in the company CRM. "
        "ALWAYS call this tool at the end of every call."
    )
    Params = CRMUpdateLeadParams

    async def execute(self, params: CRMUpdateLeadParams, ctx: Dict[str, Any]) -> ToolOutput:
        company_id = ctx.get("company_id")
        if not company_id:
            return ToolOutput.failed("Missing company_id in execution context", code="no_context")
        scope = await scope_for(ctx)
        lead = scope.resolve(LEAD, params.lead_ref)
        if lead is None or not lead.value:
            what = f"'{params.lead_ref}' is not a lead of this run" if params.lead_ref else "say which lead"
            return ToolOutput.failed(f"{what}: {scope.listing(LEAD)}", code="lead_not_in_scope")
        lead_id = lead.value

        integration = await _resolve_integration(company_id, "crm_tenant")
        if not integration:
            return ToolOutput.failed(
                "No CRM integration configured. "
                "Please register a 'crm_tenant' integration in the Integration Registry.",
                code="no_connection")
        api_key = integration.get("api_key", "")
        metadata = integration.get("service_metadata", {})
        api_url = metadata.get("api_url", "")
        # Some CRMs use a specific endpoint pattern
        update_endpoint = metadata.get("update_endpoint", "/leads/{lead_id}/update")
        if not api_url:
            return ToolOutput.failed("CRM integration missing 'api_url' in service_metadata", code="no_connection")

        payload = {
            "lead_id": lead_id,
            "call_status": "completed",
            "call_outcome": params.call_outcome,
            "call_summary": params.summary,
            "next_action": params.next_action or "",
            "next_action_date": params.next_action_date or "",
            "lead_temperature": params.lead_temperature or "",
            "updated_at": (await _business_now(company_id)).isoformat(),
            "updated_by": "hirebuddha_agent",
        }
        # The id is one path segment: a '/' or '..' in it no longer reaches
        # another endpoint of the tenant's CRM.
        endpoint = update_endpoint.replace("{lead_id}", quote(lead_id, safe=""))
        full_url = f"{api_url.rstrip('/')}{endpoint}"
        headers = _auth_headers(metadata.get("auth_type", "bearer"), api_key)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Try POST first (most CRMs), fall back to PUT
                response = await client.post(full_url, json=payload, headers=headers)
                if response.status_code == 405:  # Method Not Allowed → try PUT
                    response = await client.put(full_url, json=payload, headers=headers)
        except httpx.TimeoutException:
            return ToolOutput.failed("CRM API request timed out")
        except Exception as e:  # noqa: BLE001
            logger.error(f"[CRMUpdate] Error: {e}", exc_info=True)
            return ToolOutput.failed(str(e))
        if response.status_code not in (200, 201, 202, 204):
            error = response.text[:500]
            logger.error(f"[CRMUpdate] API error {response.status_code}: {error}")
            return ToolOutput.failed(f"CRM API returned {response.status_code}: {error}")
        result = response.json() if response.text and response.text.strip() else {}
        logger.info(f"[CRMUpdate] Lead {lead_id} updated: {params.call_outcome}")
        return ToolOutput(output={
            "success": True,
            "lead_id": lead_id,
            "call_outcome": params.call_outcome,
            "crm_response": result,
        })
