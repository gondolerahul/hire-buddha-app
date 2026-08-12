# Quick Start Guide: Phone Numbers & Streaming Services

## 🎯 Objective
Configure customer phone numbers and start handling voice calls and WhatsApp messages with AI-powered agents.

## 📋 Prerequisites

1. ✅ All services running (`./start_services.sh`)
2. ✅ Database migrations applied
3. ✅ At least one agent created in Entity Library
4. ✅ Twilio or Tata Tele account configured

## 🚀 Step-by-Step Setup

### Step 1: Access the Application

Open your browser and navigate to:
```
http://localhost:3000
```

Log in with your credentials.

### Step 2: Configure a Phone Number

1. Navigate to **Streaming > Phone Numbers** (or go to `/streaming/phone-numbers`)
2. Click **"+ Add Phone Number"**
3. Fill in the form:
   - **Customer Name**: Name of the customer (e.g., "John Doe")
   - **Phone Number**: Full phone number with country code (e.g., "+14155551234")
   - **Provider**: Select "Twilio" or "Tata Tele"
   - **Agent**: Select the AI agent to handle this customer
4. Click **"Add Phone Number"**

The phone number is now configured and ready to receive calls/messages!

### Step 3: Configure Webhooks in Twilio/Tata Tele

#### For Voice Calls (Twilio):
1. Go to Twilio Console → Phone Numbers
2. Select your phone number
3. Under "Voice & Fax", set:
   - **A Call Comes In**: Webhook
   - **URL**: `https://your-domain.com/webhooks/voice/twilio/incoming`
   - **HTTP Method**: POST

#### For WhatsApp (Twilio):
1. Go to Twilio Console → Messaging → Try it out → WhatsApp
2. Set webhook URL to:
   - `https://your-domain.com/webhooks/voice/whatsapp/incoming`

#### For Tata Tele:
1. Configure webhook in Tata Tele dashboard
2. Set URL to: `https://your-domain.com/webhooks/voice/tata-tele/incoming`

### Step 4: Test the Integration

#### Test Voice Call:
1. Call the configured phone number
2. The AI agent should answer and start conversation
3. Navigate to **Streaming > Sessions** → **Voice Calls** tab
4. You should see your call session appear
5. Click **"View"** to see the transcript

#### Test WhatsApp:
1. Send a WhatsApp message to the configured number
2. The AI agent should respond
3. Navigate to **Streaming > Sessions** → **WhatsApp** tab
4. You should see your conversation session
5. Click **"View"** to see the message history

### Step 5: Monitor Sessions

Go to **Streaming > Sessions** to:
- View all voice calls and WhatsApp conversations
- See real-time status updates
- Access full transcripts
- Monitor costs and duration
- View statistics for the last 7 days

## 📊 Using the Dashboard

### Phone Numbers Page (`/streaming/phone-numbers`)

**Features**:
- View all configured phone numbers
- See which agent handles each number
- Toggle active/inactive status
- Delete old assignments
- Filter by provider

**Actions**:
- **Add**: Create new phone number assignment
- **Toggle**: Activate/deactivate a number
- **Delete**: Remove a phone number assignment

### Sessions Page (`/streaming/sessions`)

**Tabs**:
1. **📞 Voice Calls**: View all voice call sessions
2. **💬 WhatsApp**: View all WhatsApp conversations
3. **📊 Statistics**: See aggregated metrics

**Voice Session Details**:
- Phone number
- Provider (Twilio/Tata Tele)
- Direction (inbound/outbound)
- Status (active/completed)
- Duration
- Cost
- Full transcript

**WhatsApp Session Details**:
- Phone number
- Provider
- Status (active/expired)
- Message count
- Last message time
- Full conversation history

### Campaigns Page (`/streaming/campaigns`)

**Features**:
- View all bulk calling campaigns
- See progress indicators
- Monitor success/failure rates
- View detailed campaign metrics

## 🔧 Advanced Configuration

### Environment Variables

Add to your `.env` file:

```bash
# Gemini API for AI conversations
GEMINI_API_KEY=your_gemini_api_key_here

# Twilio credentials (if using Twilio)
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token

# Tata Tele credentials (if using Tata Tele)
TATA_TELE_API_KEY=your_api_key
```

### Custom Metadata

When creating phone numbers, you can add custom metadata:

```json
{
  "customer_name": "John Doe",
  "phone_number": "+14155551234",
  "provider": "twilio",
  "agent_id": "agent-uuid-here",
  "customer_metadata": {
    "company": "Acme Corp",
    "department": "Sales",
    "priority": "high",
    "custom_field": "value"
  }
}
```

## 🎨 UI Features

All pages include:
- **Real-time updates**: Sessions update automatically
- **Search & Filter**: Find specific sessions quickly
- **Responsive design**: Works on desktop and mobile
- **Dark mode**: Optimized for low-light viewing
- **Glassmorphism**: Modern, premium design

## 📈 Monitoring & Analytics

### Statistics Dashboard

Access via **Streaming > Sessions > Statistics** tab:

**Voice Metrics** (Last 7 Days):
- Total calls
- Completed calls
- Total duration (minutes)
- Total cost (USD)
- Breakdown by provider

**WhatsApp Metrics** (Last 7 Days):
- Total sessions
- Active sessions
- Total messages
- Total cost (USD)
- Breakdown by provider

## 🔍 Troubleshooting

### Phone number not receiving calls

1. Check phone number is active in UI
2. Verify webhook URL is correct in provider dashboard
3. Check backend logs: `tail -f logs/backend_api.log`
4. Verify agent exists and is active

### WhatsApp messages not responding

1. Check WhatsApp session window (24 hours)
2. Verify webhook configuration
3. Check streaming service logs: `tail -f logs/streaming_service.log`
4. Ensure Gemini API key is configured

### Sessions not appearing in UI

1. Refresh the page
2. Check network tab for API errors
3. Verify authentication token is valid
4. Check backend API is running on port 8001

## 📚 API Reference

### Phone Numbers API

```bash
# List phone numbers
GET /api/v1/phone-numbers

# Create phone number
POST /api/v1/phone-numbers
{
  "customer_name": "John Doe",
  "phone_number": "+14155551234",
  "provider": "twilio",
  "agent_id": "uuid"
}

# Update phone number
PATCH /api/v1/phone-numbers/{id}
{
  "is_active": false
}

# Delete phone number
DELETE /api/v1/phone-numbers/{id}
```

### Sessions API

```bash
# List voice sessions
GET /api/v1/streaming/voice-sessions

# Get voice session details
GET /api/v1/streaming/voice-sessions/{id}

# List WhatsApp sessions
GET /api/v1/streaming/whatsapp-sessions

# Get statistics
GET /api/v1/streaming/stats?days=7
```

## 🎯 Next Steps

1. **Configure multiple phone numbers** for different customers
2. **Create specialized agents** for different use cases
3. **Set up campaigns** for bulk calling
4. **Monitor costs** and optimize usage
5. **Analyze transcripts** for insights

## 💡 Tips

- Use descriptive customer names for easy identification
- Assign different agents for different customer segments
- Monitor the statistics dashboard regularly
- Review transcripts to improve agent responses
- Keep phone numbers active only when needed to save costs

## 🆘 Support

- **API Documentation**: http://localhost:8001/docs
- **Streaming Docs**: http://localhost:8002/docs
- **Logs Directory**: `/logs/`

---

**You're all set!** Start configuring phone numbers and handling real-time conversations with AI agents. 🚀
