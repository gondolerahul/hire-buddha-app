# HireBuddha — CRM Voice Automation Integration Guide

**For:** Tenant Engineering Team
**Platform:** HireBuddha AI Agent Platform
**Date:** May 5, 2026
**Version:** 1.0

---

## What This Integration Does

When a new lead enters your CRM (from Google Ads, Facebook, Instagram, or any other source), HireBuddha will **automatically**:

1. **Call the lead** within seconds using an AI voice agent
2. **Pitch the correct project** based on which ad the lead clicked
3. **Schedule a site visit** on Google Calendar if the lead is interested
4. **Send a WhatsApp confirmation** to the lead with visit details
5. **Update your CRM** with the call outcome, summary, and next action

The entire flow is hands-free — no manual intervention required.

---

## What You Need To Provide

| # | Item | Required? | Details |
|---|---|---|---|
| 1 | CRM webhook configuration | **Yes** | Fire a webhook to HireBuddha when a new lead is created |
| 2 | CRM Update API | **Yes** | REST endpoint for HireBuddha to push call results back |
| 3 | WhatsApp API access | **Yes** | REST endpoint for HireBuddha to send messages via your WA system |
| 4 | Google Calendar credentials | Optional | OAuth2 credentials for scheduling site visits |
| 5 | Project documents | **Yes** | PDFs/brochures for each project (agent uses these to pitch) |

---

## 1. CRM Webhook Setup (Your CRM → HireBuddha)

Configure your CRM to fire a webhook whenever a **new lead is created**.

### Endpoint

```
POST https://app.hirebuddha.com/webhook/inbound
```

### Query Parameters

| Parameter | Required | Description |
|---|---|---|
| `client_id` | **Yes** | Your HireBuddha Company ID (we will provide this) |
| `source` | **Yes** | Set to `crm` |
| `event_type` | **Yes** | Set to `lead.created` |
| `entity_id` | Optional | Specific AI agent ID to handle this lead (we will provide if needed) |

**Full URL example:**
```
https://app.hirebuddha.com/webhook/inbound?client_id=YOUR_COMPANY_UUID&source=crm&event_type=lead.created
```

### Headers

```
Content-Type: application/json
```

### Request Body

```json
{
  "crm_event": "lead.created",
  "id": "your-crm-lead-id-12345",
  "properties": {
    "first_name": "Rahul",
    "last_name": "Sharma",
    "phone": "+919876543210",
    "email": "rahul@example.com",
    "ad_source": "google_ads",
    "ad_campaign": "Prestige Lakeside Habitat - 2BHK",
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

### Field Reference

| Field | Required | Type | Description |
|---|---|---|---|
| `crm_event` | **Yes** | string | Must be `"lead.created"` |
| `id` | **Yes** | string | Your CRM's unique lead ID (used for deduplication) |
| `properties.first_name` | **Yes** | string | Lead's first name |
| `properties.last_name` | Recommended | string | Lead's last name |
| `properties.phone` | **Yes** | string | Lead's phone number in E.164 format (e.g. `+919876543210`) |
| `properties.email` | Recommended | string | Lead's email address |
| `properties.project_interested` | **Yes** | string | Name of the project the lead clicked on |
| `properties.project_id` | Recommended | string | Your internal project identifier |
| `properties.ad_source` | Recommended | string | Ad platform: `google_ads`, `facebook`, `instagram`, etc. |
| `properties.ad_campaign` | Optional | string | Ad campaign name |
| `properties.budget_range` | Optional | string | Lead's budget range |
| `properties.city` | Optional | string | Lead's city |
| `properties.utm_source` | Optional | string | UTM source parameter |
| `properties.utm_medium` | Optional | string | UTM medium parameter |
| `properties.utm_campaign` | Optional | string | UTM campaign parameter |

### Response

You will receive an immediate acknowledgment:

```json
{
  "status": "accepted",
  "correlation_id": "uuid-for-tracking",
  "source": "crm",
  "event_type": "lead.created"
}
```

**HTTP Status:** `202 Accepted`

> **Important:** The call is placed asynchronously after the webhook is received. A `202` response means the lead has been queued successfully. Duplicate leads (same `id`) are automatically ignored.

---

## 2. CRM Update API (HireBuddha → Your CRM)

After every call, HireBuddha will send the call result back to your CRM.

### What You Need To Provide

| Item | Description |
|---|---|
| **API URL** | Your CRM's REST endpoint for updating leads (e.g. `https://crm.yourcompany.com/api/v1`) |
| **Update Endpoint Pattern** | Path to update a specific lead (e.g. `/leads/{lead_id}/update`) |
| **Authentication** | Choose one: `Bearer Token`, `API Key`, or `Basic Auth` |
| **Auth Credential** | The token/key value |

### Payload HireBuddha Will Send

```json
{
  "lead_id": "your-crm-lead-id-12345",
  "call_status": "completed",
  "call_outcome": "interested",
  "call_summary": "Lead expressed strong interest in 2BHK at Prestige Lakeside Habitat. Budget confirmed at 90L-1Cr. Preferred east-facing unit. Asked about EMI options and parking availability. Site visit scheduled for Saturday, May 10th at 11:00 AM.",
  "next_action": "site_visit_scheduled",
  "next_action_date": "2026-05-10T11:00:00+05:30",
  "lead_temperature": "hot",
  "updated_at": "2026-05-05T07:05:00+05:30",
  "updated_by": "hirebuddha_agent"
}
```

### Field Reference

| Field | Type | Description |
|---|---|---|
| `lead_id` | string | Your CRM's lead ID (same as what you sent in the webhook) |
| `call_status` | string | Always `"completed"` |
| `call_outcome` | string | One of: `interested`, `not_interested`, `callback_requested`, `no_answer`, `busy`, `invalid_number` |
| `call_summary` | string | AI-generated summary of the conversation |
| `next_action` | string | Recommended next step (e.g. `site_visit_scheduled`, `send_brochure`, `callback_tuesday`) |
| `next_action_date` | string | ISO-8601 datetime for the next action (if applicable) |
| `lead_temperature` | string | Lead scoring: `hot`, `warm`, or `cold` |
| `updated_at` | string | ISO-8601 timestamp of the update |

### Expected Response

HireBuddha expects any `2xx` status code (`200`, `201`, `202`, `204`).

---

## 3. WhatsApp API Access (HireBuddha → Your WhatsApp System)

The AI agent will send WhatsApp messages to leads during or after a call (e.g. site visit confirmations, brochure links).

### What You Need To Provide

| Item | Description |
|---|---|
| **API URL** | Your WhatsApp system's send message endpoint (e.g. `https://wa.yourcompany.com/api/v1/messages/send`) |
| **Authentication** | Choose one: `Bearer Token`, `API Key`, or `Basic Auth` |
| **Auth Credential** | The token/key value |
| **From Number** | The WhatsApp business number messages are sent from |

### Payload HireBuddha Will Send

**Text Message:**
```json
{
  "to": "+919876543210",
  "message_type": "text",
  "body": "Hi Rahul! This is from [Your Company]. Your site visit to Prestige Lakeside Habitat has been scheduled for Saturday, May 10th at 11:00 AM. Our representative will meet you at the site office. Looking forward to seeing you!",
  "from": "+91XXXXXXXXXX",
  "metadata": {
    "source": "hirebuddha_agent",
    "company_id": "your-company-uuid"
  }
}
```

**Template Message (for brochures):**
```json
{
  "to": "+919876543210",
  "message_type": "template",
  "body": "Please find the brochure for Prestige Lakeside Habitat attached.",
  "template_name": "project_brochure",
  "media_url": "https://yourcompany.com/brochures/prestige-lakeside.pdf",
  "from": "+91XXXXXXXXXX"
}
```

### Expected Response

```json
{
  "success": true,
  "message_id": "msg-abc-123",
  "status": "sent"
}
```

HireBuddha expects a `2xx` status code with a JSON response containing at least a `message_id` or `id` field.

> **Note:** If your WhatsApp system uses a different payload format, please share your API documentation and we will adapt.

---

## 4. Google Calendar Setup (Optional)

If you want the AI agent to schedule site visits on Google Calendar:

### What You Need To Provide

| Item | Description |
|---|---|
| **Google Cloud Project** | With Calendar API enabled |
| **OAuth2 Client ID** | From Google Cloud Console → Credentials |
| **OAuth2 Client Secret** | From Google Cloud Console → Credentials |
| **Calendar ID** | The calendar to create events on (usually your email or a shared calendar ID) |

### Setup Steps

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or use existing)
3. Enable **Google Calendar API** under APIs & Services
4. Create **OAuth 2.0 Client ID** (Application type: Web Application)
5. Share the Client ID, Client Secret, and Calendar ID with us securely
6. We will guide you through a one-time authorization to obtain a refresh token

---

## 5. Project Documents

Upload the following for each real estate project:

| Document | Purpose |
|---|---|
| Project brochure (PDF) | Agent uses this to pitch features, amenities, pricing |
| Floor plans | Agent can reference unit types and sizes |
| Price list | Agent uses this for budget discussions |
| Location map / address | Agent provides directions for site visits |
| FAQ document | Common questions and answers about the project |

We will upload these into the AI agent's knowledge base so it can reference them during calls.

---

## Integration Checklist

Use this checklist to track your setup progress:

- [ ] **CRM Webhook** — Configure your CRM to fire `POST` to our webhook URL on new lead creation
- [ ] **CRM Update API** — Share your API endpoint URL, auth type, and credentials
- [ ] **WhatsApp API** — Share your send message API endpoint URL, auth type, and credentials
- [ ] **Google Calendar** — Share OAuth2 Client ID, Client Secret, and Calendar ID
- [ ] **Project Documents** — Upload brochures, price lists, and floor plans for each project
- [ ] **Test Lead** — Send a test webhook with a sample lead to verify the pipeline

---

## Security & Data Handling

- All credentials are **encrypted at rest** using AES-256 encryption
- API calls to your systems use **HTTPS only**
- Lead data is processed in compliance with data protection regulations
- Call recordings and transcripts are stored securely and accessible only to your team
- You can revoke access at any time by disabling the integration

---

## Testing

Once you have completed the setup, send a test webhook to verify everything works:

```bash
curl -X POST "https://app.hirebuddha.com/webhook/inbound?client_id=YOUR_COMPANY_UUID&source=crm&event_type=lead.created" \
  -H "Content-Type: application/json" \
  -d '{
    "crm_event": "lead.created",
    "id": "TEST-LEAD-001",
    "properties": {
      "first_name": "Test",
      "last_name": "Lead",
      "phone": "+91XXXXXXXXXX",
      "project_interested": "Your Project Name",
      "project_id": "PROJ-001",
      "ad_source": "manual_test"
    }
  }'
```

**Expected:** You should receive a call on the test phone number within 30 seconds.

---

## Support

For integration support, contact us at:
- **Email:** support@hirebuddha.com
- **WhatsApp:** +91-XXXXXXXXXX

We are happy to assist with API mapping, testing, and troubleshooting.
