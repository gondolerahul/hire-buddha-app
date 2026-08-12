/**
 * Fires on every cell edit. Detects a "new row" when data is entered
 * in row 2+ (below the header) and at least one key column has a value.
 *
 * SETUP:
 *   1. Paste this into Extensions → Apps Script
 *   2. Click the clock icon (Triggers) → + Add Trigger
 *   3. Function: onEditWebhook
 *      Event source: From spreadsheet
 *      Event type: On edit          ← NOT "On change"
 *   4. Save & authorize
 */
function onEditWebhook(e) {
  // Safety: ignore edits to header row
  var editedRow = e.range.getRow();
  if (editedRow <= 1) return;

  var sheet = e.range.getSheet();
  var lastCol = sheet.getLastColumn();
  if (lastCol < 1) return;

  // Read the full row that was just edited
  var headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
  var rowData = sheet.getRange(editedRow, 1, 1, lastCol).getValues()[0];

  // Build key:value object — only send if at least one field has data
  var rowObject = {};
  var hasData = false;
  for (var i = 0; i < headers.length; i++) {
    if (headers[i]) {
      rowObject[headers[i]] = rowData[i];
      if (rowData[i] !== '' && rowData[i] !== null && rowData[i] !== undefined) {
        hasData = true;
      }
    }
  }
  if (!hasData) return;

  // ════════════════════════════════════════════
  // CONFIGURE THESE VALUES
  // ════════════════════════════════════════════
  var COMPANY_UUID = '699098ce-a31c-42ef-b13b-2780c7decb9d';
  var ENTITY_ID    = '87a07ac0-2b5c-4171-829e-e9b7df7eaa67';
  var GATEWAY_URL  = 'https://gateway.hirebuddha.com';
  // ════════════════════════════════════════════

  // De-duplicate: use ScriptProperties to track already-sent rows
  var props = PropertiesService.getScriptProperties();
  var sentKey = 'sent_row_' + sheet.getName() + '_' + editedRow;
  if (props.getProperty(sentKey)) {
    // Already sent this row — skip (prevents duplicate webhooks on edits)
    return;
  }

  var webhookUrl = GATEWAY_URL
    + '/webhook/inbound'
    + '?client_id=' + COMPANY_UUID
    + '&source=google_sheets'
    + '&event_type=sheet.row_inserted';

  var payload = {
    type: 'sheet.row_inserted',
    entity_id: ENTITY_ID,
    sheet_name: sheet.getName(),
    row_index: editedRow,
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
    var code = response.getResponseCode();
    Logger.log('Webhook sent: ' + code + ' ' + response.getContentText());

    if (code >= 200 && code < 300) {
      // Mark row as sent so edits to the same row don't re-trigger
      props.setProperty(sentKey, new Date().toISOString());
    }
  } catch (err) {
    Logger.log('Webhook failed: ' + err);
  }
}
