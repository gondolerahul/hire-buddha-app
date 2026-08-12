# Database Migration Setup Guide

## Migration Files Created

Two new Alembic migrations have been created for the streaming system:

### 1. Voice & WhatsApp Streaming Tables
**File**: `a1b2c3d4e5f6_add_voice_and_whatsapp_streaming_tables.py`

Creates 4 tables:
- `voice_sessions` - Voice call sessions
- `whatsapp_sessions` - WhatsApp message sessions
- `conversation_history` - Unified conversation logging
- `customer_phone_numbers` - Phone number assignments

### 2. Campaign Tables
**File**: `b2c3d4e5f6a7_add_campaign_tables.py`

Creates 2 tables:
- `campaigns` - Campaign configuration and metrics
- `campaign_calls` - Individual calls within campaigns

## How to Run Migrations

### Option 1: Create Fresh Virtual Environment (Recommended)

```bash
cd /home/rahul/workspace/dev-hb-codebase/hb-proto-3/backend

# Create new virtual environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate

# Install required packages
pip install alembic sqlalchemy asyncpg psycopg2-binary

# Run migrations
alembic upgrade head
```

### Option 2: Use Existing Virtual Environment

If you have a working virtual environment:

```bash
cd /home/rahul/workspace/dev-hb-codebase/hb-proto-3/backend

# Activate venv
source venv/bin/activate  # or source .venv/bin/activate

# Ensure alembic is installed
pip install alembic

# Run migrations
alembic upgrade head
```

### Option 3: System-wide Installation (Not Recommended)

```bash
# Install alembic system-wide
sudo apt install alembic

# Run migrations
cd /home/rahul/workspace/dev-hb-codebase/hb-proto-3/backend
alembic upgrade head
```

## Expected Output

When successful, you should see:

```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 9bc12d4c6cc6 -> a1b2c3d4e5f6, add voice and whatsapp streaming tables
INFO  [alembic.runtime.migration] Running upgrade a1b2c3d4e5f6 -> b2c3d4e5f6a7, add campaign tables
```

## Verify Migrations

After running, check the database:

```sql
-- List all tables
\dt

-- Check new tables
SELECT * FROM voice_sessions LIMIT 1;
SELECT * FROM whatsapp_sessions LIMIT 1;
SELECT * FROM conversation_history LIMIT 1;
SELECT * FROM customer_phone_numbers LIMIT 1;
SELECT * FROM campaigns LIMIT 1;
SELECT * FROM campaign_calls LIMIT 1;
```

## Troubleshooting

### Error: "No module named alembic"
- Ensure virtual environment is activated
- Install alembic: `pip install alembic`

### Error: "Can't locate revision 9bc12d4c6cc6"
- Previous migrations not run
- Run: `alembic upgrade head` to apply all pending

### Error: Database connection failed
- Check `.env` file has correct `DATABASE_URL`
- Ensure PostgreSQL is running
- Verify database exists

## Environment Variables Required

Ensure your `.env` file contains:

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost/dbname
```

## Next Steps After Migration

1. Start streaming service: `uvicorn src.streaming.main:app --port 8002 --reload`
2. Start ARQ worker: `arq src.worker.WorkerSettings`
3. Test webhooks with ngrok: `ngrok http 8002`
4. Configure Twilio/Tata webhooks
