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
       ▼  POST /webhook/inbound?client_id=<COMPANY_UUID>
Unified Gateway (:8001)
       │  GenericWebhookStrategy normalizes payload
       ▼
Event Bus (asyncio.Queue fan-out)
       │
       ▼
Dispatcher → creates ExecutionRun with entity_id from payload
       │
       ▼
ExecutionEngine.execute_run()
       │
       ▼
Agent executes plan → initiates voice call to customer
```

### Key Files

| File | Role |
|------|------|
| `backend/src/gateway/webhook_inbound.py` | Receives POST, normalizes via GenericWebhookStrategy |
| `backend/src/gateway/event_bus.py` | In-memory fan-out queue |
| `backend/src/gateway/dispatcher.py` | Routes events → creates ExecutionRun → invokes engine |
| `backend/src/ai/worker.py` | ExecutionEngine runs the agent's plan |
| `backend/src/gateway/auth_middleware.py` | Extracts `client_id` from query params |

---

## Configuration Steps (Zero Code Changes)

### Step 1: Find Your Company UUID

```sql
SELECT id, name FROM companies;
```

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
  var COMPANY_UUID = '<YOUR_COMPANY_UUID>';
  var ENTITY_ID    = '<YOUR_AGENT_ENTITY_UUID>';
  var GATEWAY_URL  = 'https://gateway.hirebuddha.com';
  // ════════════════════════════════════════════

  var webhookUrl = GATEWAY_URL 
    + '/webhook/inbound'
    + '?client_id=' + COMPANY_UUID
    + '&source=google_sheets'
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

  var options = {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
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
- `<YOUR_COMPANY_UUID>` — your company's UUID from Step 1
- `<YOUR_AGENT_ENTITY_UUID>` — the agent entity's UUID from Step 2
- `GATEWAY_URL` — your production gateway URL (default: `https://gateway.hirebuddha.com`)

### Step 4: Install the Trigger

1. In the Apps Script editor, click the **clock icon** (Triggers) in the left sidebar
2. Click **+ Add Trigger** (bottom right)
3. Configure:
   - **Function**: `sendWebhookOnChange`
   - **Event source**: `From spreadsheet`
   - **Event type**: `On change`
4. Click **Save**
5. Authorize the script when prompted

### Step 5: Verify Gateway Health

```bash
curl https://gateway.hirebuddha.com/health
```

Confirm `consumer_count ≥ 1` in the response. If it's 0, the Dispatcher didn't start and events will be silently dropped.

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

## Required Code Change: Entity-Specific Routing

> **Important**: The current dispatcher (`_execute_in_process`) picks the **first active entity** for the company. Since you want to pass a specific `entity_id`, a small code change is needed in `backend/src/gateway/dispatcher.py` line ~205.

The change: extract `entity_id` from `envelope.raw_data` if present, instead of always querying for the first active entity. This is a ~5-line change in `_execute_in_process()`.

---

## Testing

### Quick Test with curl

```bash
curl -X POST "https://gateway.hirebuddha.com/webhook/inbound?client_id=<COMPANY_UUID>&source=google_sheets&event_type=sheet.row_inserted" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "sheet.row_inserted",
    "entity_id": "<AGENT_ENTITY_UUID>",
    "sheet_name": "Leads",
    "row_index": 2,
    "data": {"Name": "Test Customer", "Phone": "+919876543210", "Interest": "Product Demo"}
  }'
```

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
