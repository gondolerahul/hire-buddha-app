# Phase 5 - Campaign Execution Engine & Monitoring

## Overview

Phase 5 implements the **auto-dialer** that actually places outbound calls and provides real-time monitoring.

## Implementation Status

### ✅ Backend Components (Complete):

1. **`campaign_executor.py`** - Core auto-dialer engine
   - Campaign execution orchestration
   - Call queue management
   - Worker tasks (concurrent calling)
   - Throttling enforcement (max concurrent, rate limits)
   - Outbound call placement (Twilio/Tata Tele)
   - Status tracking and metrics

2. **`campaign_worker.py`** - ARQ background tasks
   - `execute_campaign_task` - Starts campaign execution
   - `pause_campaign_task` - Pauses running campaign
   - `stop_campaign_task` - Stops campaign completely

3. **Updated `number_router.py`**
   - Added `get_company_number()` for outbound caller ID

4. **Updated `campaign_router.py`**
   - Status update endpoint now enqueues ARQ task when starting campaign

## Architecture

### Call Flow:

```
1. User clicks "Start Campaign" in UI
   ↓
2. PATCH /api/v1/campaigns/{id}/status (status="running")
   ↓
3. Enqueue ARQ task: execute_campaign_task
   ↓
4. CampaignExecutor.start_campaign()
   ↓
5. Load pending calls from campaign_calls table
   ↓
6. Create asyncio.Queue with all pending calls
   ↓
7. Spawn N worker tasks (N = max_concurrent_calls)
   ↓
8. Each worker:
   - Gets next call from queue
   - Creates VoiceSession
   - Calls _place_twilio_call() or _place_tata_call()
   - Updates campaign stats
   - Repeats until queue empty
   ↓
9. All workers complete → Mark campaign as "completed"
```

### Throttling:

- **Concurrent Limit**: Max N calls at once (configurable per campaign)
- **Rate Limit**: Max calls per hour (optional, not yet implemented)
- **Queue-based**: Uses asyncio.Queue for clean concurrency control

### Status Tracking:

**Campaign statuses**:
- `draft` → Created but not started
- `scheduled` → Scheduled for future execution
- `running` → Currently placing calls
- `paused` → Temporarily stopped
- `completed` → All calls attempted
- `failed` → Error during execution

**Call statuses**:
- `pending` → Not yet called
- `calling` → Currently on call
- `completed` → Call finished
- `failed` → Could not connect
- `skipped` → Skipped for some reason

## Integration Points

### Twilio API (Outbound Calls):

```python
from twilio.rest import Client

client = Client(account_sid, auth_token)
call = client.calls.create(
    to="+14155551234",
    from_="+14155556789",  # Company's Twilio number
    url=f"http://{STREAMING_HOST}/webhooks/voice/twilio/incoming?session_id={session_id}"
)
```

The `url` parameter tells Twilio to connect to our streaming service once the call is answered.

### Tata Tele API (Outbound Calls):

```python
# To be implemented based on Tata Tele API documentation
# Expected format:
POST https://api.tatatelebusiness.com/v1/calls
{
  "to": "+919876543210",
  "from": "+911234567890",
  "callback_url": "http://{STREAMING_HOST}/webhooks/voice/tata/incoming?session_id={session_id}"
}
```

## Real-Time Monitoring

### Metrics Endpoints:

**Campaign Status**:
```
GET /api/v1/campaigns/{id}/status

Response:
{
  "campaign_id": "uuid",
  "name": "EMI Collection Drive",
  "status": "running",
  "total_contacts": 1000,
  "calls_initiated": 450,
  "calls_completed": 420,
  "calls_failed": 30,
  "pending": 550,
  "calling": 5,  // Currently active
  "completed": 420,
  "failed": 30
}
```

**Active Calls**:
```
GET /api/v1/campaigns/{id}/active-calls

Response:
{
  "campaign_id": "uuid",
  "active_calls": [
    {
      "id": "call-uuid",
      "contact_name": "John Doe",
      "contact_phone": "+14155551234",
      "called_at": "2026-02-06T12:00:00Z",
      "duration": 45  // seconds
    }
  ]
}
```

## Testing

### Prerequisites:

1. **Run migrations**:
   ```bash
   alembic upgrade head
   ```

2. **Start ARQ worker**:
   ```bash
   arq src.worker.WorkerSettings
   ```

3. **Assign phone number to company**:
   ```sql
   INSERT INTO customer_phone_numbers (
     company_id, customer_id, customer_name, phone_number,
     provider, agent_id, is_active
   ) VALUES (
     'company-uuid', 'temp-uuid', 'Company Outbound',
     '+14155551234', 'twilio', 'agent-uuid', true
   );
   ```

### Test Flow:

1. **Create campaign** (via API or UI):
   ```bash
   POST /api/v1/campaigns
   {
     "name": "Test Campaign",
     "agent_id": "uuid",
     "contact_list": [
       {"phone": "+14155559999", "name": "Test Contact"}
     ],
     "provider": "twilio",
     "max_concurrent_calls": 2
   }
   ```

2. **Start campaign**:
   ```bash
   PATCH /api/v1/campaigns/{id}/status?status=running
   ```

3. **Monitor execution**:
   ```bash
   # Watch logs
   tail -f logs/worker.log
   
   # Check status
   GET /api/v1/campaigns/{id}/status
   
   # View active calls
   GET /api/v1/campaigns/{id}/active-calls
   ```

4. **Check database**:
   ```sql
   -- Campaign stats
   SELECT * FROM campaigns WHERE id = 'campaign-uuid';
   
   -- Call statuses
   SELECT status, COUNT(*) FROM campaign_calls
   WHERE campaign_id = 'campaign-uuid'
   GROUP BY status;
   
   -- Voice sessions created
   SELECT * FROM voice_sessions
   WHERE call_metadata->>'campaign_id' = 'campaign-uuid';
   ```

## Configuration

### Environment Variables:

```env
# Twilio
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token

# Tata Tele (Phase 6)
TATA_TELE_API_KEY=your_api_key
TATA_TELE_API_SECRET=your_secret

# Streaming service
STREAMING_HOST=your-domain.com:8002
```

### Campaign Settings:

- **max_concurrent_calls**: Number of simultaneous outbound calls (default: 5)
- **max_calls_per_hour**: Rate limit (optional, not yet enforced)
- **scheduled_start**: When to start automatically (optional)
- **scheduled_end**: When to stop automatically (optional)

## Known Limitations & TODOs:

### Phase 5:
- [ ] Real Twilio/Tata Tele API integration (currently mocked)
- [ ] Rate limiting (calls per hour) enforcement
- [ ] Retry logic for failed calls
- [ ] Call recording integration
- [ ] Real-time WebSocket updates for dashboard
- [ ] Campaign scheduling (cron-based auto-start)
- [ ] Pause/resume functionality
- [ ] Better error handling and recovery

### Future Enhancements:
- [ ] Predictive dialing (call before agent available)
- [ ] Voicemail detection
- [ ] DNC (Do Not Call) list integration
- [ ] Time zone awareness (don't call at night)
- [ ] Call disposition categorization
- [ ] Automated retry scheduling
- [ ] A/B testing for different scripts

## Monitoring Dashboard (UI)

### Real-Time Metrics Panel:

**Components to build**:

1. **Campaign Overview Card**
   - Campaign name, status badge
   - Start time, duration
   - Agent being used

2. **Progress Visualization**
   - Circular progress (% completed)
   - Progress bar
   - ETA to completion

3. **Call Status Breakdown**
   - Pie chart or donut chart
   - Segments: Pending, Calling, Completed, Failed
   - Click to filter call list

4. **Live Call Monitor**
   - Table of currently active calls
   - Contact name, phone, duration (live counter)
   - Auto-refresh every 5 seconds

5. **Metrics Cards**
   - Total Contacts
   - Calls Initiated
   - Success Rate
   - Average Call Duration
   - Calls/Hour (current rate)

6. **Historical Chart**
   - Line chart showing calls over time
   - X-axis: Time (hourly buckets)
   - Y-axis: Number of calls
   - Multiple lines: Initiated, Completed, Failed

### API Integration:

```typescript
// polls/campaigns.ts
export const useCampaignStatus = (campaignId: string) => {
  const [status, setStatus] = useState(null);
  
  useEffect(() => {
    const interval = setInterval(async () => {
      const data = await campaignsAPI.getStatus(campaignId);
      setStatus(data);
    }, 5000); // Poll every 5 seconds
    
    return () => clearInterval(interval);
  }, [campaignId]);
  
  return status;
};
```

## Production Checklist

Before running campaigns in production:

- [ ] Configure Twilio/Tata Tele credentials
- [ ] Test with small campaign (5-10 contacts)
- [ ] Verify call quality and audio streaming
- [ ] Set appropriate throttling limits
- [ ] Configure monitoring/alerts for failures
- [ ] Implement error recovery mechanisms
- [ ] Test pause/resume functionality
- [ ] Validate billing/usage tracking
- [ ] Set up call recording storage
- [ ] Configure DNC list
- [ ] Test retry logic
- [ ] Verify transcript logging

## Next Steps

**Phase 6** will add:
- Tata Tele voice integration (complete implementation)
- WhatsApp integration (text-based campaigns)
- WhatsApp media support (images, documents)
- Unified messaging dashboard
- Cross-channel analytics
