# CRM Integration Feasibility Report — Real Estate Tenant

**Date:** May 5, 2026 | **Platform:** HireBuddha (hb-proto-3)

---

## Executive Summary

> **Verdict: FEASIBLE — with targeted enhancements (~20 hours of work).**
>
> The system already has ~80% of the infrastructure. The core pipeline exists:
> webhook ingestion → event bus → dispatcher → voice agent → Tata Tele outbound calling.
> What's missing: (1) persistent lead queue table, (2) custom tools for tenant's
> WhatsApp API and Google Calendar, (3) post-call CRM update tool, (4) datetime tool.

---

## 1. Existing Capabilities (What Already Works)

| Capability | File | Status |
|---|---|---|
| Unified Webhook Receiver | `gateway/webhook_inbound.py` — `CRMWebhookStrategy` handles HubSpot/Salesforce/Zoho + `GenericWebhookStrategy` fallback | Ready |
| Event Bus (async fan-out) | `gateway/event_bus.py` — In-memory asyncio.Queue, 1000-event buffer | Ready |
| Central Dispatcher | `gateway/dispatcher.py` — Routes events to arq Redis queue then ExecutionEngine | Ready |
| Tata Tele Outbound Calling | `ai/campaign_executor.py` — `_place_tata_call()` via Click-to-Call Support API | Ready |
| Tata Tele Inbound Webhook | `voice/webhook_router.py` — Resumes session via `custom_identifier`, returns WSS URL | Ready |
| Bidirectional Voice Streaming | `voice/websocket_handler.py` — Gemini Live + Azure Realtime, tool calling mid-call | Ready |
| Agent Context + Persona | `voice/agent_loader.py` — System prompt, goals, context sources (PDFs), conversation history | Ready |
| Tool Execution During Voice | `voice/websocket_handler.py` L527-605 — `_handle_tool_call()` via ToolExecutor | Ready |
| Campaign Engine (bulk calls) | `ai/campaign_executor.py` — Queue-based with `max_concurrent_calls` throttling | Ready |
| WhatsApp Messaging (Tata Tele) | `voice/whatsapp_messaging.py` — Text, media, template messages | Ready |
| Call Intelligence | `voice/conversation_logger.py` — Transcript, recording, per-turn logging | Ready |

---

## 2. Gaps — What Needs to Be Built

| Gap | Impact | Effort |
|---|---|---|
| No persistent Lead Queue table | Simultaneous webhooks may lose data (in-memory bus drops at capacity) | Medium |
| No `crm_update_lead` tool | Agent can't push call results back to tenant CRM | Medium |
| No `whatsapp_send_via_tenant_api` tool | Agent can't call tenant's custom WhatsApp system | Medium |
| No `google_calendar_create_event` tool | Agent can't schedule property visits | Medium |
| No `get_current_datetime` tool | Agent doesn't know today's date/day | Low |
| Dispatcher finds "first active agent" | Need to route CRM leads to a specific agent (by entity_id) | Low |
| No post-call webhook to CRM | CRM won't get call outcome automatically | Medium |

---

## 3. End-to-End Data Flow

```
Google/FB/Insta Ads --> [Tenant CRM] --webhook--> HireBuddha
                           ^                        |
                           |                        v
                     POST result         POST /webhook/inbound
                     (call outcome)      (CRMWebhookStrategy)
                           ^                        |
                           |                        v
                           |                 lead_queue (DB)
                           |                 persistent storage
                           |                        |
                           |                        v
                           |                 Queue Worker
                           |                 picks leads
                           |                 sequentially
                           |                        |
                           |                        v
                           |                 Tata Tele
                           |                 Click-to-Call
                           |                        |
                           |                        v
                           |                 Voice Agent (Gemini)
                           |                 Tools:
[Tenant WhatsApp] <--------|                   get_datetime
[Google Calendar] <--------|                   whatsapp_tenant
                           +-------------------crm_update_lead
                                               google_calendar
```

---

## 4. APIs Required from Tenant

### 4.1 CRM Webhook — Tenant to HireBuddha (Lead Created)

**Endpoint:** `POST https://gateway.hirebuddha.com/webhook/inbound?client_id={TENANT_UUID}&source=crm&event_type=lead.created`

**Expected Payload:**
```json
{
  "crm_event": "lead.created",
  "object_type": "lead",
  "id": "CRM-LEAD-12345",
  "properties": {
    "first_name": "Rahul",
    "last_name": "Sharma",
    "phone": "+919876543210",
    "email": "rahul@example.com",
    "ad_source": "google_ads",
    "ad_campaign": "Prestige Lakeside Habitat",
    "project_interested": "Prestige Lakeside Habitat",
    "project_id": "PLH-001",
    "budget_range": "80L-1.2Cr",
    "city": "Bangalore",
    "utm_source": "google",
    "utm_medium": "cpc",
    "utm_campaign": "prestige-lakeside-2bhk",
    "created_at": "2026-05-05T06:50:00Z"
  }
}
```

**Minimum Required Fields:** `phone`, `first_name`, `project_interested`

**Response:** `202 Accepted` with `{"status": "accepted", "correlation_id": "..."}`

---

### 4.2 CRM Update API — HireBuddha to Tenant CRM (Post-Call)

**What we need from tenant:** REST endpoint URL + auth credentials.

**Payload we will send:**
```json
{
  "lead_id": "CRM-LEAD-12345",
  "call_status": "completed",
  "call_outcome": "interested",
  "call_duration_seconds": 187,
  "call_summary": "Lead interested in 2BHK at Prestige Lakeside. Budget 90L-1Cr. Visit scheduled Sat May 10 at 11 AM.",
  "next_action": "site_visit_scheduled",
  "next_action_date": "2026-05-10T11:00:00+05:30",
  "lead_temperature": "hot",
  "agent_notes": "Asked about EMI options and parking. Wants east-facing unit.",
  "call_recording_url": "https://app.hirebuddha.com/artifacts/recording_xxx.wav",
  "updated_at": "2026-05-05T07:05:00Z"
}
```

**Tenant must provide:** API endpoint URL, authentication method (API Key / Bearer Token), field name mapping if different.

---

### 4.3 Tenant WhatsApp API — HireBuddha to Tenant WhatsApp System

**Payload we will send:**
```json
{
  "to": "+919876543210",
  "message_type": "text",
  "body": "Hi Rahul! Your site visit to Prestige Lakeside Habitat is confirmed for Saturday, May 10th at 11:00 AM.",
  "metadata": {
    "lead_id": "CRM-LEAD-12345",
    "source": "hirebuddha_agent"
  }
}
```

**Expected Response from tenant's WA system:**
```json
{
  "success": true,
  "message_id": "wa-msg-xyz-789",
  "status": "sent"
}
```

**Tenant must provide:** API endpoint URL, auth credentials, supported message types.

---

### 4.4 Google Calendar API

Standard Google Calendar API via OAuth2. Tenant provides OAuth credentials stored in IntegrationRegistry.

**Required from tenant:** Google Cloud project with Calendar API enabled, OAuth2 Client ID/Secret, Calendar ID.

---

## 5. Webhooks Summary — Tenant Checklist

| Direction | Webhook | URL | Trigger | Auth |
|---|---|---|---|---|
| Tenant to HireBuddha | Lead Created | `POST /webhook/inbound?client_id={UUID}&source=crm&event_type=lead.created` | New lead in CRM | HMAC-SHA256 (optional) |
| HireBuddha to Tenant | Call Result | `POST <tenant-provided-url>` | After each call | API Key / Bearer |
| HireBuddha to Tenant | WhatsApp Send | `POST <tenant-wa-api-url>` | During call (agent tool) | API Key / Bearer |
| Tenant to HireBuddha | WA Status (optional) | `POST /webhook/inbound?client_id={UUID}&source=whatsapp_tenant` | Delivery receipts | HMAC-SHA256 |

---

## 6. Lead Queue Architecture (Simultaneous Leads)

### Problem
Current InMemoryEventBus (maxsize=1000) drops events when full. No persistence guarantee.

### Solution: New lead_queue DB Table

```sql
CREATE TABLE lead_queue (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id),
    agent_id        UUID NOT NULL REFERENCES hierarchical_entities(id),
    lead_id         VARCHAR(255) NOT NULL,
    phone           VARCHAR(20) NOT NULL,
    lead_data       JSONB NOT NULL,
    ad_source       VARCHAR(100),
    project_id      VARCHAR(100),
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    priority        INTEGER NOT NULL DEFAULT 5,
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 3,
    last_error      TEXT,
    correlation_id  VARCHAR(100),
    voice_session_id UUID REFERENCES voice_sessions(id),
    call_outcome    JSONB,
    created_at      TIMESTAMP NOT NULL DEFAULT now(),
    updated_at      TIMESTAMP NOT NULL DEFAULT now(),
    processed_at    TIMESTAMP,
    UNIQUE(company_id, lead_id)
);

CREATE INDEX idx_lead_queue_pending
    ON lead_queue(company_id, status, priority, created_at)
    WHERE status = 'pending';
```

**Processing Flow:**
1. Webhook arrives -> INSERT into lead_queue with status=pending -> return 202 immediately
2. Background worker polls for status=pending (ordered by priority, created_at)
3. Worker sets status=queued, calls _place_tata_call()
4. Call connects -> status=calling
5. Call completes -> status=completed, stores call_outcome JSONB
6. Failure -> increment attempt_count, if < max_attempts reset to pending

**This guarantees zero data loss** even under burst traffic of simultaneous leads.

---

## 7. New Tools Specification

### 7.1 get_current_datetime
```json
{
  "name": "get_current_datetime",
  "description": "Get the current date, time, and day of the week in IST timezone",
  "parameters": {"type": "object", "properties": {}, "required": []}
}
```
Returns: "Monday, May 5, 2026 12:20 PM IST"

### 7.2 whatsapp_send_tenant
```json
{
  "name": "whatsapp_send_tenant",
  "description": "Send WhatsApp message via tenant's WhatsApp system",
  "parameters": {
    "type": "object",
    "properties": {
      "to": {"type": "string", "description": "Recipient phone (+919876543210)"},
      "message": {"type": "string", "description": "Message text"},
      "template_name": {"type": "string", "description": "Optional template name"},
      "media_url": {"type": "string", "description": "Optional media/brochure URL"}
    },
    "required": ["to", "message"]
  }
}
```
Reads tenant WA API URL + auth from IntegrationRegistry (provider_name=whatsapp_tenant).

### 7.3 google_calendar_create_event
```json
{
  "name": "google_calendar_create_event",
  "description": "Schedule a property visit on Google Calendar",
  "parameters": {
    "type": "object",
    "properties": {
      "title": {"type": "string"},
      "description": {"type": "string"},
      "start_datetime": {"type": "string", "description": "ISO-8601 datetime"},
      "end_datetime": {"type": "string", "description": "ISO-8601 datetime"},
      "attendee_email": {"type": "string"},
      "location": {"type": "string"}
    },
    "required": ["title", "start_datetime"]
  }
}
```

### 7.4 crm_update_lead
```json
{
  "name": "crm_update_lead",
  "description": "Update lead status in tenant's CRM after call",
  "parameters": {
    "type": "object",
    "properties": {
      "lead_id": {"type": "string"},
      "call_outcome": {"type": "string", "enum": ["interested","not_interested","callback_requested","no_answer","busy","invalid_number"]},
      "summary": {"type": "string"},
      "next_action": {"type": "string"},
      "next_action_date": {"type": "string"},
      "lead_temperature": {"type": "string", "enum": ["hot","warm","cold"]}
    },
    "required": ["lead_id", "call_outcome", "summary"]
  }
}
```

All tools follow the existing Tool base class pattern in ai/tools/base.py.

---

## 8. Integration Registry Entries (Tenant Setup)

| provider_name | Purpose | encrypted_api_key | service_metadata |
|---|---|---|---|
| tata_tele | Voice calling | Tata Tele API key | {"account_sid": "..."} |
| google_gemini | AI (voice agent) | Gemini API key | {"project_id": "...", "region": "..."} |
| whatsapp_tenant | Tenant WA system | WA API auth token | {"api_url": "https://...", "from_number": "..."} |
| google_calendar | Visit scheduling | OAuth2 refresh token | {"calendar_id": "...", "client_id": "...", "client_secret": "..."} |
| crm_tenant | CRM updates | CRM API key | {"api_url": "https://...", "auth_type": "bearer"} |

---

## 9. Implementation Work Items

| # | Item | Effort |
|---|---|---|
| 1 | Create lead_queue DB table + Alembic migration | 2h |
| 2 | Build lead queue processor (poll, dispatch, retry) | 4h |
| 3 | Enhance CRM webhook to persist to lead_queue | 2h |
| 4 | Build get_current_datetime tool | 30m |
| 5 | Build whatsapp_send_tenant tool | 2h |
| 6 | Build google_calendar_create_event tool | 3h |
| 7 | Build crm_update_lead tool | 2h |
| 8 | Post-call hook: auto-fire CRM update after voice session ends | 3h |
| 9 | Create Real Estate agent template with system prompt + tool assignments | 1h |
| 10 | Upload project documents as context sources | 30m |
| **Total** | | **~20h** |
