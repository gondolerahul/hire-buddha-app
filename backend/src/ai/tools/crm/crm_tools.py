"""
CRM Integration Tools for Real Estate Tenant Voice Agents.

Four tools that enable a voice agent to:
  1. Check the current date/time (IST)
  2. Send WhatsApp messages via tenant's own WhatsApp system
  3. Schedule Google Calendar events for property visits
  4. Update lead status in tenant's CRM after a call

All tools resolve tenant-specific credentials from IntegrationRegistry
using the company_id passed via the extra_context dict.
"""
import logging
import json
import httpx
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from uuid import UUID as _UUID

from src.ai.tools.base import Tool

logger = logging.getLogger(__name__)

# IST timezone offset
IST = timezone(timedelta(hours=5, minutes=30))


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
        from src.common.database import AsyncSessionLocal
        from sqlalchemy import select
        from src.config.models import IntegrationRegistry
        from src.common.security import decrypt_api_key

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(IntegrationRegistry).where(
                    IntegrationRegistry.company_id == _UUID(str(company_id)),
                    IntegrationRegistry.provider_name == provider_name,
                    IntegrationRegistry.status == "active",
                )
            )
            entry = result.scalars().first()

            if entry:
                api_key = None
                if entry.encrypted_api_key:
                    api_key = decrypt_api_key(entry.encrypted_api_key)

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

class GetCurrentDateTimeTool(Tool):
    """
    Returns the current date, time, and day of the week in IST.

    Enables the voice agent to suggest visit dates, know business hours,
    and avoid scheduling on past dates.
    """
    name = "get_current_datetime"
    description = (
        "Get the current date, time, and day of the week in Indian Standard Time (IST). "
        "Use this before suggesting dates for site visits or appointments."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        }

    async def run(self, input_data: str) -> str:
        now_ist = datetime.now(IST)
        return json.dumps({
            "datetime": now_ist.strftime("%A, %B %d, %Y %I:%M %p IST"),
            "date": now_ist.strftime("%Y-%m-%d"),
            "time": now_ist.strftime("%I:%M %p"),
            "day": now_ist.strftime("%A"),
            "iso": now_ist.isoformat(),
        })


# ===========================================================================
# Tool 2: WhatsApp Send (Tenant's System)
# ===========================================================================

class WhatsAppSendTenantTool(Tool):
    """
    Send WhatsApp messages via the tenant's own WhatsApp system.

    Resolves the tenant's WhatsApp API URL and auth token from
    IntegrationRegistry (provider_name='whatsapp_tenant').
    """
    name = "whatsapp_send_tenant"
    description = (
        "Send a WhatsApp message to a customer via the company's own WhatsApp system. "
        "Use for sending visit confirmations, brochures, or follow-up messages. "
        "Credentials are automatically resolved from the company's integration settings."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient phone number in E.164 format (e.g. +919876543210)",
                    },
                    "message": {
                        "type": "string",
                        "description": "Message text to send",
                    },
                    "template_name": {
                        "type": "string",
                        "description": "Optional template name for pre-approved template messages",
                    },
                    "media_url": {
                        "type": "string",
                        "description": "Optional URL to a media file (brochure PDF, image, etc.)",
                    },
                },
                "required": ["to", "message"],
            },
        }

    async def run(self, input_data: str) -> str:
        return await self.run_with_context(input_data, None)

    async def run_with_context(
        self, input_data: str, context: Optional[Dict[str, Any]] = None
    ) -> str:
        try:
            params = json.loads(input_data)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON input"})

        company_id = context.get("company_id") if context else None
        if not company_id:
            return json.dumps({"error": "Missing company_id in execution context"})

        # Resolve tenant's WhatsApp integration
        integration = await _resolve_integration(company_id, "whatsapp_tenant")
        if not integration:
            return json.dumps({
                "error": "No WhatsApp integration configured. "
                "Please register a 'whatsapp_tenant' integration in the Integration Registry."
            })

        api_key = integration.get("api_key", "")
        metadata = integration.get("service_metadata", {})
        api_url = metadata.get("api_url", "")
        from_number = metadata.get("from_number", "")
        auth_type = metadata.get("auth_type", "bearer")  # bearer | api_key | basic

        if not api_url:
            return json.dumps({"error": "WhatsApp integration missing 'api_url' in service_metadata"})

        to = params.get("to", "")
        message = params.get("message", "")
        template_name = params.get("template_name")
        media_url = params.get("media_url")

        if not to or not message:
            return json.dumps({"error": "Missing required parameters: 'to' and 'message'"})

        # Build request payload
        payload: Dict[str, Any] = {
            "to": to,
            "message_type": "template" if template_name else "text",
            "body": message,
        }
        if template_name:
            payload["template_name"] = template_name
        if media_url:
            payload["media_url"] = media_url
        if from_number:
            payload["from"] = from_number
        payload["metadata"] = {"source": "hirebuddha_agent", "company_id": company_id}

        # Build auth headers
        headers = {"Content-Type": "application/json"}
        if auth_type == "bearer":
            headers["Authorization"] = f"Bearer {api_key}"
        elif auth_type == "api_key":
            headers["X-API-Key"] = api_key
        elif auth_type == "basic":
            import base64
            headers["Authorization"] = f"Basic {base64.b64encode(api_key.encode()).decode()}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(api_url, json=payload, headers=headers)

            if response.status_code in (200, 201, 202):
                result = response.json() if response.text else {}
                logger.info(f"[WhatsAppTenant] Message sent to {to}: {result}")
                return json.dumps({
                    "success": True,
                    "message_id": result.get("message_id", result.get("id", "")),
                    "status": result.get("status", "sent"),
                    "to": to,
                })
            else:
                error_body = response.text[:500]
                logger.error(f"[WhatsAppTenant] API error {response.status_code}: {error_body}")
                return json.dumps({
                    "success": False,
                    "error": f"WhatsApp API returned {response.status_code}: {error_body}",
                })

        except httpx.TimeoutException:
            return json.dumps({"success": False, "error": "WhatsApp API request timed out"})
        except Exception as e:
            logger.error(f"[WhatsAppTenant] Error: {e}", exc_info=True)
            return json.dumps({"success": False, "error": str(e)})


# ===========================================================================
# Tool 3: Google Calendar Create Event
# ===========================================================================

class GoogleCalendarCreateEventTool(Tool):
    """
    Schedule events on Google Calendar for property visits.

    Resolves Google Calendar credentials from IntegrationRegistry
    (provider_name='google_calendar'). Supports both Service Account
    and OAuth2 refresh token flows.
    """
    name = "google_calendar_create_event"
    description = (
        "Schedule a property visit or appointment on Google Calendar. "
        "Use this after the customer agrees to a site visit. "
        "Credentials are automatically resolved from the company's integration settings."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Event title (e.g. 'Site Visit - Prestige Lakeside Habitat')",
                    },
                    "description": {
                        "type": "string",
                        "description": "Event description with details",
                    },
                    "start_datetime": {
                        "type": "string",
                        "description": "Start datetime in ISO-8601 format (e.g. '2026-05-10T11:00:00+05:30')",
                    },
                    "end_datetime": {
                        "type": "string",
                        "description": "End datetime in ISO-8601 format. Defaults to 1 hour after start.",
                    },
                    "attendee_email": {
                        "type": "string",
                        "description": "Email of the attendee to invite",
                    },
                    "location": {
                        "type": "string",
                        "description": "Event location / address",
                    },
                },
                "required": ["title", "start_datetime"],
            },
        }

    async def run(self, input_data: str) -> str:
        return await self.run_with_context(input_data, None)

    async def run_with_context(
        self, input_data: str, context: Optional[Dict[str, Any]] = None
    ) -> str:
        try:
            params = json.loads(input_data)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON input"})

        company_id = context.get("company_id") if context else None
        if not company_id:
            return json.dumps({"error": "Missing company_id in execution context"})

        # Resolve Google Calendar integration
        integration = await _resolve_integration(company_id, "google_calendar")
        if not integration:
            return json.dumps({
                "error": "No Google Calendar integration configured. "
                "Please register a 'google_calendar' integration in the Integration Registry."
            })

        metadata = integration.get("service_metadata", {})
        calendar_id = metadata.get("calendar_id", "primary")
        client_id = metadata.get("client_id", "")
        client_secret = metadata.get("client_secret", "")
        refresh_token = integration.get("api_key", "")  # Stored as the encrypted_api_key

        title = params.get("title", "Site Visit")
        description = params.get("description", "")
        start_dt = params.get("start_datetime", "")
        end_dt = params.get("end_datetime", "")
        attendee_email = params.get("attendee_email", "")
        location = params.get("location", "")

        if not start_dt:
            return json.dumps({"error": "Missing required parameter: 'start_datetime'"})

        # If no end_datetime, default to 1 hour after start
        if not end_dt:
            try:
                from datetime import datetime as dt
                start = dt.fromisoformat(start_dt)
                end = start + timedelta(hours=1)
                end_dt = end.isoformat()
            except Exception:
                end_dt = start_dt

        # Get access token via OAuth2 refresh
        access_token = await self._get_access_token(client_id, client_secret, refresh_token)
        if not access_token:
            return json.dumps({"error": "Failed to obtain Google Calendar access token"})

        # Build Calendar API event
        event_body: Dict[str, Any] = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_dt},
            "end": {"dateTime": end_dt},
        }
        if location:
            event_body["location"] = location
        if attendee_email:
            event_body["attendees"] = [{"email": attendee_email}]

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
                response = await client.post(
                    url,
                    json=event_body,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    params={"sendUpdates": "all"} if attendee_email else {},
                )

            if response.status_code in (200, 201):
                result = response.json()
                logger.info(f"[GoogleCalendar] Event created: {result.get('id')}")
                return json.dumps({
                    "success": True,
                    "event_id": result.get("id"),
                    "html_link": result.get("htmlLink"),
                    "start": result.get("start", {}).get("dateTime"),
                    "end": result.get("end", {}).get("dateTime"),
                    "summary": result.get("summary"),
                })
            else:
                error = response.text[:500]
                logger.error(f"[GoogleCalendar] API error {response.status_code}: {error}")
                return json.dumps({
                    "success": False,
                    "error": f"Google Calendar API returned {response.status_code}: {error}",
                })

        except Exception as e:
            logger.error(f"[GoogleCalendar] Error: {e}", exc_info=True)
            return json.dumps({"success": False, "error": str(e)})

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

class CRMUpdateLeadTool(Tool):
    """
    Update lead status in tenant's CRM after a call completes.

    Resolves CRM API credentials from IntegrationRegistry
    (provider_name='crm_tenant').
    """
    name = "crm_update_lead"
    description = (
        "Update the lead's status in the company CRM after a call. "
        "ALWAYS call this tool at the end of every call to record the outcome, "
        "call summary, and next action to take. "
        "Credentials are automatically resolved from the company's integration settings."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_id": {
                        "type": "string",
                        "description": "The CRM lead ID to update",
                    },
                    "call_outcome": {
                        "type": "string",
                        "description": "Call outcome: interested, not_interested, callback_requested, no_answer, busy, invalid_number",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Brief summary of the call conversation and key points discussed",
                    },
                    "next_action": {
                        "type": "string",
                        "description": "Next action to be taken (e.g. 'site_visit_scheduled', 'send_brochure', 'callback_tuesday')",
                    },
                    "next_action_date": {
                        "type": "string",
                        "description": "Date/time for the next action in ISO-8601 format",
                    },
                    "lead_temperature": {
                        "type": "string",
                        "description": "Lead temperature: hot, warm, or cold",
                    },
                },
                "required": ["lead_id", "call_outcome", "summary"],
            },
        }

    async def run(self, input_data: str) -> str:
        return await self.run_with_context(input_data, None)

    async def run_with_context(
        self, input_data: str, context: Optional[Dict[str, Any]] = None
    ) -> str:
        try:
            params = json.loads(input_data)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON input"})

        company_id = context.get("company_id") if context else None
        if not company_id:
            return json.dumps({"error": "Missing company_id in execution context"})

        # Resolve tenant's CRM integration
        integration = await _resolve_integration(company_id, "crm_tenant")
        if not integration:
            return json.dumps({
                "error": "No CRM integration configured. "
                "Please register a 'crm_tenant' integration in the Integration Registry."
            })

        api_key = integration.get("api_key", "")
        metadata = integration.get("service_metadata", {})
        api_url = metadata.get("api_url", "")
        auth_type = metadata.get("auth_type", "bearer")
        # Some CRMs use a specific endpoint pattern
        update_endpoint = metadata.get("update_endpoint", "/leads/{lead_id}/update")

        if not api_url:
            return json.dumps({"error": "CRM integration missing 'api_url' in service_metadata"})

        lead_id = params.get("lead_id", "")
        call_outcome = params.get("call_outcome", "")
        summary = params.get("summary", "")
        next_action = params.get("next_action", "")
        next_action_date = params.get("next_action_date", "")
        lead_temperature = params.get("lead_temperature", "")

        if not lead_id or not call_outcome or not summary:
            return json.dumps({"error": "Missing required parameters: lead_id, call_outcome, summary"})

        # Build update payload
        payload = {
            "lead_id": lead_id,
            "call_status": "completed",
            "call_outcome": call_outcome,
            "call_summary": summary,
            "next_action": next_action,
            "next_action_date": next_action_date,
            "lead_temperature": lead_temperature,
            "updated_at": datetime.now(IST).isoformat(),
            "updated_by": "hirebuddha_agent",
        }

        # Build URL
        endpoint = update_endpoint.replace("{lead_id}", lead_id)
        full_url = f"{api_url.rstrip('/')}{endpoint}"

        # Build auth headers
        headers = {"Content-Type": "application/json"}
        if auth_type == "bearer":
            headers["Authorization"] = f"Bearer {api_key}"
        elif auth_type == "api_key":
            headers["X-API-Key"] = api_key

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Try POST first (most CRMs), fall back to PUT
                response = await client.post(full_url, json=payload, headers=headers)

                if response.status_code == 405:  # Method Not Allowed → try PUT
                    response = await client.put(full_url, json=payload, headers=headers)

            if response.status_code in (200, 201, 202, 204):
                result = response.json() if response.text and response.text.strip() else {}
                logger.info(f"[CRMUpdate] Lead {lead_id} updated: {call_outcome}")
                return json.dumps({
                    "success": True,
                    "lead_id": lead_id,
                    "call_outcome": call_outcome,
                    "crm_response": result,
                })
            else:
                error = response.text[:500]
                logger.error(f"[CRMUpdate] API error {response.status_code}: {error}")
                return json.dumps({
                    "success": False,
                    "error": f"CRM API returned {response.status_code}: {error}",
                })

        except httpx.TimeoutException:
            return json.dumps({"success": False, "error": "CRM API request timed out"})
        except Exception as e:
            logger.error(f"[CRMUpdate] Error: {e}", exc_info=True)
            return json.dumps({"success": False, "error": str(e)})
