# Google Sheets → Agent Trigger Configuration Guide

> **Goal**: When a row is inserted in a Google Sheet, automatically trigger a specific HireBuddha agent that **calls the customer and gathers their specific requirement**.

---

## Architecture

```
Google Sheets (Row Inserted)
       │
       ▼
Apps Script (onChange trigger)
       │
       ▼  POST /webhook/inbound/<ENDPOINT_ID>, signed with X-HB-Signature
API (:8000) — checks the signature against the endpoint's secret (401 if wrong)
       │  GenericWebhookStrategy normalizes payload; the company is the endpoint's
       ▼
Redis (arq job process_gateway_event; 202 once it is queued)
       │
       ▼
Worker → creates an ExecutionRun for the agent (entity_id from the payload)
       │
       ▼
AgentLoop → the agent calls the customer
```

### Key Files

| File | Role |
|------|------|
| `backend/src/gateway/webhook_inbound.py` | Receives the POST, checks the signature, normalizes via `GenericWebhookStrategy` |
| `backend/src/gateway/webhook_endpoints_router.py` | `/api/v1/webhook-endpoints` — register the endpoint and get its secret |
| `backend/src/gateway/envelope.py` | Queues the event for the worker |
| `backend/src/ai/core/arq_jobs.py` | `process_gateway_event` — creates the run and starts the agent |

---

## Configuration Steps (Zero Code Changes)

### Step 1: Register a webhook endpoint

Webhooks are accepted only at a registered endpoint, signed with its secret (GW-01,
2026-10-07). As a company admin:

```bash
curl -s -X POST https://app.hirebuddha.com/api/v1/webhook-endpoints \
  -H "Authorization: Bearer <ADMIN_ACCESS_TOKEN>" -H "Content-Type: application/json" \
  -d '{"source": "generic", "name": "Leads sheet", "entity_id": "<YOUR_AGENT_ENTITY_UUID>"}'
```

The response carries the endpoint's `url` and its `secret`. **The secret is shown
only once** — keep it for Step 3. The company is the admin's own; there is no
company id to send.

### Step 2: Find the Agent Entity ID

```sql
SELECT id, name, type, is_active 
FROM hierarchical_entities 
WHERE company_id = '<YOUR_COMPANY_UUID>' 
  AND is_active = true
ORDER BY created_at;
```

Pick the agent that handles customer calls. Note its `id` — you'll pass it as `entity_id` in the webhook.

### Step 3: Set Up Google Apps Script

1. Open your Google Sheet
2. Go to **Extensions → Apps Script**
3. Paste this script:

```javascript
function sendWebhookOnChange(e) {
  // Only fire on row insertion — ignore edits, column inserts, etc.
  if (e.changeType !== 'INSERT_ROW') return;

  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var lastRow = sheet.getLastRow();
  var lastCol = sheet.getLastColumn();
  
  // Get headers (row 1) and the newly inserted row data
  var headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
  var rowData = sheet.getRange(lastRow, 1, 1, lastCol).getValues()[0];
  
  // Build a key:value object from headers + row data
  var rowObject = {};
  for (var i = 0; i < headers.length; i++) {
    if (headers[i]) {
      rowObject[headers[i]] = rowData[i];
    }
  }

  // ════════════════════════════════════════════
  // CONFIGURE THESE VALUES
  // ════════════════════════════════════════════
  var ENDPOINT_URL = '<THE url FROM STEP 1>';     // .../webhook/inbound/<endpoint id>
  var SECRET       = '<THE secret FROM STEP 1>';
  var ENTITY_ID    = '<YOUR_AGENT_ENTITY_UUID>';
  // ════════════════════════════════════════════

  var webhookUrl = ENDPOINT_URL
    + '?source=google_sheets'
    + '&event_type=sheet.row_inserted';

  var payload = {
    type: 'sheet.row_inserted',
    entity_id: ENTITY_ID,
    sheet_name: sheet.getName(),
    row_index: lastRow,
    data: rowObject,
    spreadsheet_id: SpreadsheetApp.getActiveSpreadsheet().getId(),
    timestamp: new Date().toISOString()
  };

  // Sign the exact body that is sent: sha256=<hex HMAC-SHA256(body, SECRET)>
  var body = JSON.stringify(payload);
  var mac = Utilities.computeHmacSha256Signature(body, SECRET, Utilities.Charset.UTF_8);
  var hex = mac.map(function (b) { return ('0' + (b & 0xFF).toString(16)).slice(-2); }).join('');

  var options = {
    method: 'post',
    contentType: 'application/json',
    payload: body,
    headers: { 'X-HB-Signature': 'sha256=' + hex },
    muteHttpExceptions: true
  };

  try {
    var response = UrlFetchApp.fetch(webhookUrl, options);
    Logger.log('Webhook sent: ' + response.getResponseCode() + ' ' + response.getContentText());
  } catch (err) {
    Logger.log('Webhook failed: ' + err);
  }
}
```

**Replace**:
- `ENDPOINT_URL` and `SECRET` — the `url` and `secret` from Step 1
- `<YOUR_AGENT_ENTITY_UUID>` — the agent entity's UUID from Step 2

### Step 4: Install the Trigger

1. In the Apps Script editor, click the **clock icon** (Triggers) in the left sidebar
2. Click **+ Add Trigger** (bottom right)
3. Configure:
   - **Function**: `sendWebhookOnChange`
   - **Event source**: `From spreadsheet`
   - **Event type**: `On change`
4. Click **Save**
5. Authorize the script when prompted

### Step 5: Verify the API and worker

```bash
curl https://app.hirebuddha.com/api/v1/health
```

Confirm `"status": "ok"`. `degraded` names what is wrong — for example no live worker
on the queue, in which case events wait in Redis until one starts.

---

## What the Agent Receives

When the webhook fires, the dispatcher creates an `ExecutionRun` with this `input_data`:

```json
{
  "input": "{\"source\": \"google_sheets\", \"raw\": {\"type\": \"sheet.row_inserted\", \"entity_id\": \"<agent-uuid>\", \"sheet_name\": \"Leads\", \"row_index\": 42, \"data\": {\"Name\": \"Rahul\", \"Phone\": \"+91...\", \"Email\": \"...\", \"Interest\": \"...\"}, \"timestamp\": \"...\"}}",
  "channel": "webhook",
  "source": "generic",
  "event_type": "sheet.row_inserted",
  "correlation_id": "<uuid>"
}
```

The agent's prompt can reference `{{input}}` to access the customer's name, phone number, and any other fields from the sheet row.

---

## Entity-Specific Routing

No code change is needed. The event runs the agent the endpoint is bound to
(Step 1); an endpoint without one runs the payload's `entity_id`, and that must be
an active agent of your company. With neither, it runs your company's only agent —
if you have several, the event is not run, so bind the endpoint.

---

## Testing

### Quick Test with curl

```bash
BODY='{"type": "sheet.row_inserted", "entity_id": "<AGENT_ENTITY_UUID>", "sheet_name": "Leads", "row_index": 2, "data": {"Name": "Test Customer", "Phone": "+919876543210", "Interest": "Product Demo"}}'
SIG="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | sed 's/^.* //')"
curl -X POST "$ENDPOINT_URL?source=google_sheets&event_type=sheet.row_inserted" \
  -H "Content-Type: application/json" -H "X-HB-Signature: $SIG" -d "$BODY"
```

A missing or wrong signature answers **401** and nothing runs.

**Expected response** (HTTP 202):
```json
{
  "status": "accepted",
  "correlation_id": "...",
  "source": "generic",
  "event_type": "sheet.row_inserted"
}
```

### Verify Execution

```sql
SELECT id, entity_id, status, input_data, created_at 
FROM execution_runs 
WHERE company_id = '<COMPANY_UUID>' 
ORDER BY created_at DESC 
LIMIT 5;
```

### End-to-End Test

1. Insert a new row in the Google Sheet with customer name + phone number
2. Check gateway logs for `[WebhookRouter] Received sheet.row_inserted`
3. Verify an execution run was created for your agent
4. Confirm the agent initiated a voice call to the customer

---

## Notes

- **Apps Script quotas**: Google limits `UrlFetchApp` calls to ~20,000/day for consumer accounts, 100,000/day for Workspace accounts.
- **Arq job gap**: The `process_gateway_event` arq job is referenced by the dispatcher but not registered in `WorkerSettings.functions`. The system falls back to in-process execution, which works but runs on the gateway's event loop.
- **Agent design**: Ensure the target agent has voice calling capabilities configured (Tata Tele / Twilio integration) and its planning prompt knows to extract the phone number from the input data and initiate a call.
