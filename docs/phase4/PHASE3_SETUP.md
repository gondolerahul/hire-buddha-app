# Phase 3 Setup Instructions - Gemini Live API Integration

## New Dependencies

Install the required packages:

```bash
cd backend
pip install -r requirements-streaming.txt
```

Or install individually:
```bash
pip install google-genai>=0.2.0
pip install audioop-lts>=0.2.1
pip install pydub>=0.25.1
pip install numpy>=1.24.0
pip install websockets>=12.0
```

## Environment Configuration

Add to your `.env` file:

```env
# Gemini Live API
GEMINI_API_KEY=your_gemini_api_key_here

# Streaming Service
STREAMING_HOST=localhost:8002
STREAMING_PORT=8002

# Optional: Force mock mode for testing
USE_MOCK_GEMINI=false
```

## Getting Gemini API Key

1. Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Create a new API key
3. Copy the key to your `.env` file

## Testing Phase 3

### 1. Test  Auto-Fallback

Without setting `GEMINI_API_KEY`, the system will automatically use the mock client:

```bash
# Start streaming service
cd backend
python3 -m uvicorn src.streaming.main:app --port 8002 --reload
```

Check logs - should see:
```
WARNING - Falling back to mock client: Gemini API key required...
INFO - MockGeminiClient created (using mock responses)
```

### 2. Test Real Gemini Connection

Set `GEMINI_API_KEY` in `.env`:

```bash
export GEMINI_API_KEY=your_key_here
# OR add to .env file

# Start streaming service
python3 -m uvicorn src.streaming.main:app --port 8002 --reload
```

Check logs - should see:
```
INFO - google.genai SDK available
INFO - Gemini Live client initialized
```

### 3. Test Transcript APIs

The streaming service now includes transcript endpoints:

```bash
# Get call transcript (JSON format)
curl http://localhost:8002/api/calls/{call_id}/transcript

# Get transcript as text
curl http://localhost:8002/api/calls/{call_id}/transcript/text

# Get call summary
curl http://localhost:8002/api/calls/{call_id}/summary

# Export transcript
curl http://localhost:8002/api/calls/{call_id}/export
```

### 4. End-to-End Test with Twilio

#### Prerequisites:
- Twilio account with phone number
- Ngrok or similar tunnel
- Customer phone number assigned in database

#### Steps:

1. **Start streaming service**:
   ```bash
   cd backend
   python3 -m uvicorn src.streaming.main:app --port 8002 --reload
   ```

2. **Expose via ngrok**:
   ```bash
   ngrok http 8002
   ```

3. **Configure Twilio webhook**:
   - Go to Twilio Console → Phone Numbers
   - Set webhook URL: `https://your-ngrok-url.ngrok.io/webhooks/voice/twilio/incoming`

4. **Make test call**:
   - Call your Twilio number
   - Should hear: "Please wait while we connect you"
   - If Gemini API key is set: Real AI conversation
   - If no API key: Mock responses

5. **Check database**:
   ```sql
   -- View active sessions
   SELECT * FROM voice_sessions WHERE status = 'active';
   
   -- View conversation history
   SELECT * FROM conversation_history 
   WHERE session_id = 'your-session-id'
   ORDER BY turn_number;
   ```

6. **Get transcript via API**:
   ```bash
   curl http://localhost:8002/api/calls/{session_id}/transcript
   ```

## Conversation Logging

Phase 3 introduces comprehensive conversation logging:

### Features:
- ✅ Every turn logged to `conversation_history` table
- ✅ Speaker identification (customer vs agent)
- ✅ Timestamps for each turn
- ✅ Metadata support for additional context
- ✅ Multiple export formats (JSON, text)
- ✅ Session summaries with statistics

### API Examples:

**Get Transcript** (JSON):
```bash
GET /api/calls/{call_id}/transcript

Response:
{
  "call_id": "uuid",
  "total_turns": 12,
  "transcript": [
    {
      "turn_number": 1,
      "speaker": "customer",
      "content": "Hello, I need help",
      "timestamp": "2026-02-06T11:30:00",
      "message_type": "text"
    },
    ...
  ]
}
```

**Get Summary**:
```bash
GET /api/calls/{call_id}/summary

Response:
{
  "call_id": "uuid",
  "total_turns": 12,
  "customer_turns": 6,
  "agent_turns": 6,
  "duration_ms": 45000,
  "start_time": "2026-02-06T11:30:00",
  "end_time": "2026-02-06T11:30:45"
}
```

**Get Text Format**:
```bash
GET /api/calls/{call_id}/transcript/text?include_timestamps=true

Response:
{
  "call_id": "uuid",
  "transcript": "[11:30:00] Customer: Hello, I need help\n[11:30:05] Agent: I'm here to help you. What can I assist with?\n..."
}
```

## Gemini Live API Configuration

### Voice Selection:

The default voice is "Aoede" (natural female voice). To change:

Edit `src/streaming/gemini_live.py`:
```python
"speech_config": {
    "voice_config": {
        "prebuilt_voice_config": {
            "voice_name": "Puck"  # Male voice
        }
    }
}
```

Available voices:
- `Aoede` - Female, natural
- `Puck` - Male, conversational
- `Charon` - Male, deep
- `Kore` - Female, warm
- `Fenrir` - Male, authoritative

### Generation Config:

Customize in agent's `llm_config.parameters`:
```json
{
  "temperature": 0.7,
  "max_output_tokens": 1024,
  "top_p": 0.95,
  "top_k": 40
}
```

## Monitoring & Debugging

### Check Gemini Connection:

View streaming service logs:
```bash
tail -f logs/streaming.log
```

Look for:
```
INFO - Gemini Live client initialized
INFO - Gemini session established for {session_id}
INFO - Logged voice turn #1 by customer
INFO - Logged voice turn #2 by agent
```

### Common Issues:

**1. "google.genai SDK not available"**
```bash
pip install google-genai
```

**2. "Gemini API key required"**
- Set `GEMINI_API_KEY` in `.env`
- Or export as environment variable

**3. "Falling back to mock client"**
- This is normal if no API key is set
- System gracefully falls back to mock for development

**4. WebSocket connection issues**
- Check firewall rules
- Verify ngrok tunnel is active
- Check Twilio webhook configuration

**5. No conversation history**
- Verify database migration ran: `alembic upgrade head`
- Check `conversation_history` table exists
- Look for errors in logs

## Architecture Notes

### Automatic Fallback:

The `get_client_with_fallback()` function automatically:
1. Tries to create real Gemini client
2. If API key missing → Falls back to mock
3. If SDK not installed → Falls back to mock
4. Logs warnings but continues working

This allows:
- **Development**: No API key needed
- **Testing**: Can test streaming pipeline without Gemini
- **Production**: Seamlessly uses real Gemini when configured

### Conversation Context:

Agent loader now:
1. Loads previous conversation history (last 10 turns)
2. Formats for Gemini Live API
3. Provides context continuity across sessions

### Audio Pipeline:

```
Twilio (mulaw 8kHz) 
  ↓ WebSocket
  ↓ base64 decode
  ↓ mulaw → PCM16 (16kHz) [AudioProcessor]
  ↓
Gemini Live API
  ↓
  ↓ PCM24 (24kHz) response
  ↓ PCM24 → mulaw (8kHz) [AudioProcessor]
  ↓ base64 encode
  ↓ WebSocket
Twilio
```

## Next Steps

Once Phase 3 is tested:
- ✅ **Phase 4**: Frontend Campaign Builder
- ✅ **Phase 5**: Monitoring Dashboard
- ✅ **Phase 6**: Tata Tele + WhatsApp Integration

## Production Checklist

Before deploying to production:

- [ ] Set `GEMINI_API_KEY` in production environment
- [ ] Configure appropriate voice (Aoede/Puck/etc.)
- [ ] Set generation config (temperature, etc.)
- [ ] Test latency (<500ms target)
- [ ] Load test (50+ concurrent calls)
- [ ] Set up monitoring/alerts
- [ ] Configure proper CORS origins
- [ ] Enable TLS/SSL for WebSocket
- [ ] Set up log aggregation
- [ ] Configure backup/failover

## Cost Considerations

Gemini Live API pricing:
- ~$0.05 per minute of audio
- Monitor usage via Google Cloud Console
- Set up billing alerts
- Consider caching responses for common queries
