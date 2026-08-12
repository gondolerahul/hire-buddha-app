# Phase 2 Setup Instructions

## Prerequisites

1. **Database Migration**
   ```bash
   cd backend
   # If using virtual environment
   source .venv/bin/activate  # or venv/bin/activate
   
   # Run migration
   alembic upgrade head
   ```

2. **Install Dependencies** (if not already installed)
   ```bash
   pip install fastapi uvicorn websockets audioop sqlalchemy asyncpg
   ```

## Starting the Streaming Service

### Method 1: Direct Python
```bash
cd backend
python3 -m uvicorn src.streaming.main:app --port 8002 --reload
```

### Method 2: Using the script
```bash
cd backend/src/streaming
python3 main.py
```

The service will start on Port 8002.

## Testing Phase 2 Components

Run the test script:
```bash
cd backend
python3 test_phase2.py
```

Expected output:
```
============================================================
Phase 2 Component Tests
============================================================
Testing imports...
✓ Models imported successfully
✓ SessionManager imported successfully
✓ NumberRouter imported successfully
✓ AudioProcessor imported successfully
✓ AgentContextLoader imported successfully
✓ MockGeminiClient imported successfully
✓ TwilioStreamHandler imported successfully
✓ Webhook router imported successfully

Testing AudioProcessor...
✓ Generated silence: 3200 bytes
✓ Duration calculation correct: 100ms
✓ Split into 20 chunks

Testing NumberRouter...
✓ India number → Tata Tele
✓ US number → Twilio

Testing MockGeminiClient...
✓ MockGeminiClient created
✓ Mock session connected
✓ Audio sent to mock Gemini
✓ Mock session disconnected

============================================================
Test Summary
============================================================
Passed: 4/4

✅ All tests passed! Phase 2 components are working.
```

## Verifying Endpoints

1. **Health Check**
   ```bash
   curl http://localhost:8002/health
   ```
   
   Expected: `{"status": "healthy", "service": "streaming", ...}`

2. **Webhook Endpoints**
   ```bash
   # List all routes
   curl http://localhost:8002/docs
   ```
   
   You should see:
   - `POST /webhooks/voice/twilio/incoming`
   - `POST /webhooks/voice/twilio/status`
   - `POST /webhooks/voice/tata/incoming`
   - `POST /webhooks/whatsapp/incoming`
   - `WS /stream/twilio/{session_id}`
   - `WS /stream/tata/{session_id}`

## Testing with Twilio (Requires Twilio Account)

### 1. Expose Local Service
```bash
ngrok http 8002
```

Copy the ngrok URL (e.g., `https://abc123.ngrok.io`)

### 2. Configure Twilio Number
1. Go to Twilio Console → Phone Numbers
2. Select your number
3. Configure Voice & Fax:
   - **A CALL COMES IN**: Webhook
   - **URL**: `https://abc123.ngrok.io/webhooks/voice/twilio/incoming`
   - **HTTP Method**: POST

### 3. Create Number Assignment
Before making a test call, assign the Twilio number to a customer:

```bash
# Via API or directly in database
INSERT INTO customer_phone_numbers (
    company_id, customer_id, customer_name, phone_number,
    provider, agent_id, is_active
) VALUES (
    'your-company-uuid',
    'customer-uuid',
    'Test Customer',
    '+15551234567',  -- Your Twilio number
    'twilio',
    'agent-entity-uuid',
    true
);
```

### 4. Make Test Call
Call your Twilio number from your phone.

Expected flow:
1. Call connects
2. You hear: "Please wait while we connect you"
3. WebSocket stream establishes
4. Mock Gemini generates responses
5. Call is logged to database

### 5. Check Logs
```bash
# Streaming service logs
tail -f logs/streaming.log

# Database
SELECT * FROM voice_sessions ORDER BY created_at DESC LIMIT 1;
SELECT * FROM conversation_history ORDER BY timestamp DESC LIMIT 10;
```

## Troubleshooting

### Error: "No module named 'src'"
```bash
export PYTHONPATH=/path/to/hb-proto-3/backend:$PYTHONPATH
```

### Error: "connection to server failed"
Check PostgreSQL is running:
```bash
sudo systemctl status postgresql
```

### Error: "table does not exist"
Run migrations:
```bash
alembic upgrade head
```

### WebSocket connection refused
- Verify streaming service is running on port 8002
- Check firewall rules
- Verify ngrok tunnel is active

## Next Steps

Once Phase 2 is tested and working:
1. ✅ Replace MockGeminiClient with real Gemini Live API (Phase 3)
2. ✅ Implement frontend Campaign Builder (Phase 4)
3. ✅ Add monitoring dashboard (Phase 5)
4. ✅ Integrate Tata Tele + WhatsApp (Phase 6)

## Environment Variables

Add to `.env`:
```env
# Streaming Service
STREAMING_HOST=localhost:8002  # or your production URL
STREAMING_PORT=8002

# Twilio (add in Phase 3 when integrating credentials)
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=
```
