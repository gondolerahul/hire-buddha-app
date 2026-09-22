-- ============================================================================
-- Mobile dialer v2: rep-captured outcomes, callbacks and do-not-call.
-- docs/mobile-dialer-app/11-ux-and-visual-design.md §3.1
--
-- Idempotent and additive: every column is nullable with no default, so on
-- PostgreSQL 11+ each ALTER is a catalogue-only change (no table rewrite) and
-- the currently deployed code keeps working if this lands before the code.
--
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/db-scripts/mobile_dialer_002.sql
--
-- Rollback (nothing depends on these until the matching code ships):
--   ALTER TABLE campaign_calls
--     DROP COLUMN IF EXISTS rep_disposition,
--     DROP COLUMN IF EXISTS rep_note,
--     DROP COLUMN IF EXISTS rep_dispositioned_at,
--     DROP COLUMN IF EXISTS rep_dispositioned_by,
--     DROP COLUMN IF EXISTS disposition_source,
--     DROP COLUMN IF EXISTS callback_at;
-- ============================================================================
BEGIN;

-- Fail fast instead of queueing. An ALTER waiting for ACCESS EXCLUSIVE blocks
-- every later query on the table behind it — that is how campaign_calls has
-- stalled before. If this times out, look for idle-in-transaction sessions
-- holding campaign_calls in pg_stat_activity and clear them first.
SET LOCAL lock_timeout = '5s';

-- ── The rep's own read of the call ──────────────────────────────────────────
-- `disposition` stays the effective value that analytics and reports read, so
-- nothing downstream changes. These columns record where that value came from
-- and preserve the rep's answer even if a later LLM pass disagrees.
ALTER TABLE campaign_calls ADD COLUMN IF NOT EXISTS rep_disposition VARCHAR(30);
ALTER TABLE campaign_calls ADD COLUMN IF NOT EXISTS rep_note TEXT;
ALTER TABLE campaign_calls ADD COLUMN IF NOT EXISTS rep_dispositioned_at TIMESTAMP WITHOUT TIME ZONE;
ALTER TABLE campaign_calls ADD COLUMN IF NOT EXISTS rep_dispositioned_by UUID;
-- 'ai' | 'rep'. NULL means the row predates this change.
ALTER TABLE campaign_calls ADD COLUMN IF NOT EXISTS disposition_source VARCHAR(10);

-- ── Callbacks ───────────────────────────────────────────────────────────────
-- "Call me after six" currently has nowhere to go. A lead with callback_at in
-- the future is held back by the leasing query until its time comes.
ALTER TABLE campaign_calls ADD COLUMN IF NOT EXISTS callback_at TIMESTAMP WITHOUT TIME ZONE;

-- Partial: only a handful of rows per company ever carry a callback.
CREATE INDEX IF NOT EXISTS ix_campaign_calls_callback
    ON campaign_calls (leased_by_user_id, callback_at)
    WHERE callback_at IS NOT NULL;

-- The leasing query's do-not-call subquery scans disposition + phone across the
-- company on every lease. It has been a sequential scan until now.
CREATE INDEX IF NOT EXISTS ix_campaign_calls_dnc_phone
    ON campaign_calls ((contact_data->>'phone'))
    WHERE disposition = 'do_not_call';

COMMIT;
