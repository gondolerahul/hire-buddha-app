-- ============================================================================
-- Mobile dialer app schema (docs/mobile-dialer-app/06-backend-changes-and-api.md §1)
--
-- Idempotent: safe to run more than once. Additive only (new tables, nullable
-- or defaulted columns), so the currently deployed code keeps working if this
-- is applied before the mobile-dialer code is deployed.
--
-- Apply BEFORE deploying the code that references these columns:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/db-scripts/mobile_dialer_001.sql
-- Alembic revision m0b1e0d1a100 executes this same file.
-- ============================================================================
BEGIN;

-- Fail fast instead of queueing: a waiting ALTER TABLE blocks every later query
-- on that table. If this times out, find idle-in-transaction sessions holding
-- campaigns/campaign_calls (pg_stat_activity), release them, and re-run.
SET LOCAL lock_timeout = '5s';

-- ── Existing tables ──────────────────────────────────────────────────────────
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS execution_mode VARCHAR(30) NOT NULL DEFAULT 'server_dialer';
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS contact_upload_id UUID;

ALTER TABLE campaign_calls ADD COLUMN IF NOT EXISTS leased_by_user_id UUID;
ALTER TABLE campaign_calls ADD COLUMN IF NOT EXISTS leased_by_device_id UUID;
ALTER TABLE campaign_calls ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMP WITHOUT TIME ZONE;
CREATE INDEX IF NOT EXISTS ix_campaign_calls_lease ON campaign_calls (campaign_id, status, lease_expires_at);

-- ── New tables (compiled from src/mobile/models.py) ─────────────────────────

CREATE TABLE IF NOT EXISTS user_devices (
	id UUID NOT NULL, 
	company_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	install_id VARCHAR(64) NOT NULL, 
	platform VARCHAR(20) NOT NULL, 
	model VARCHAR(100), 
	os_version VARCHAR(30), 
	app_version VARCHAR(50), 
	fcm_token VARCHAR(512), 
	phone_account_label VARCHAR(100), 
	presented_cli VARCHAR(40), 
	verified_cli VARCHAR(20), 
	cli_available BOOLEAN NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	verification_code_hash VARCHAR(128), 
	verification_did VARCHAR(20), 
	verification_expires_at TIMESTAMP WITHOUT TIME ZONE, 
	verified_at TIMESTAMP WITHOUT TIME ZONE, 
	last_seen_at TIMESTAMP WITHOUT TIME ZONE, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(company_id) REFERENCES companies (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	UNIQUE (install_id)
);

CREATE INDEX IF NOT EXISTS ix_user_devices_company_id ON user_devices (company_id);

CREATE INDEX IF NOT EXISTS ix_user_devices_user_id ON user_devices (user_id);

CREATE INDEX IF NOT EXISTS ix_user_devices_verification_did ON user_devices (verification_did, verification_expires_at);

CREATE INDEX IF NOT EXISTS ix_user_devices_verified_cli ON user_devices (verified_cli);

CREATE TABLE IF NOT EXISTS contact_uploads (
	id UUID NOT NULL, 
	company_id UUID NOT NULL, 
	uploaded_by UUID NOT NULL, 
	filename VARCHAR(255) NOT NULL, 
	file_type VARCHAR(10) NOT NULL, 
	total_rows INTEGER NOT NULL, 
	valid_rows INTEGER NOT NULL, 
	invalid_rows INTEGER NOT NULL, 
	duplicate_rows INTEGER NOT NULL, 
	columns JSONB NOT NULL, 
	phone_column VARCHAR(255), 
	valid_contacts JSONB NOT NULL, 
	errors JSONB NOT NULL, 
	consumed_at TIMESTAMP WITHOUT TIME ZONE, 
	expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(company_id) REFERENCES companies (id), 
	FOREIGN KEY(uploaded_by) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS ix_contact_uploads_company_id ON contact_uploads (company_id);

CREATE TABLE IF NOT EXISTS campaign_assignees (
	campaign_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	assigned_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (campaign_id, user_id), 
	FOREIGN KEY(campaign_id) REFERENCES campaigns (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_campaign_assignees_user_id ON campaign_assignees (user_id);

CREATE TABLE IF NOT EXISTS mobile_campaign_runs (
	id UUID NOT NULL, 
	company_id UUID NOT NULL, 
	campaign_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	device_id UUID NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	dial_order VARCHAR(20) NOT NULL, 
	started_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	ended_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(company_id) REFERENCES companies (id), 
	FOREIGN KEY(campaign_id) REFERENCES campaigns (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(device_id) REFERENCES user_devices (id)
);

CREATE INDEX IF NOT EXISTS ix_mobile_campaign_runs_campaign_id ON mobile_campaign_runs (campaign_id);

CREATE INDEX IF NOT EXISTS ix_mobile_campaign_runs_company_id ON mobile_campaign_runs (company_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_mobile_run_running_per_device ON mobile_campaign_runs (device_id) WHERE status IN ('running', 'paused');

CREATE TABLE IF NOT EXISTS mobile_call_attempts (
	id UUID NOT NULL, 
	company_id UUID NOT NULL, 
	campaign_id UUID NOT NULL, 
	campaign_call_id UUID NOT NULL, 
	run_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	device_id UUID NOT NULL, 
	agent_id UUID NOT NULL, 
	device_cli VARCHAR(20), 
	did VARCHAR(20) NOT NULL, 
	dtmf_token VARCHAR(8) NOT NULL, 
	dial_order VARCHAR(20) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	identification_method VARCHAR(20), 
	identification_conflict BOOLEAN NOT NULL, 
	assisted BOOLEAN NOT NULL, 
	voice_session_id UUID, 
	expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	ai_answered_at TIMESTAMP WITHOUT TIME ZONE, 
	ai_ready_at TIMESTAMP WITHOUT TIME ZONE, 
	lead_dialed_at TIMESTAMP WITHOUT TIME ZONE, 
	lead_answered_at TIMESTAMP WITHOUT TIME ZONE, 
	merged_at TIMESTAMP WITHOUT TIME ZONE, 
	ended_at TIMESTAMP WITHOUT TIME ZONE, 
	lead_failure_cause VARCHAR(30), 
	end_reason VARCHAR(50), 
	lead_ring_seconds INTEGER, 
	conversation_seconds INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(company_id) REFERENCES companies (id), 
	FOREIGN KEY(campaign_id) REFERENCES campaigns (id), 
	FOREIGN KEY(campaign_call_id) REFERENCES campaign_calls (id), 
	FOREIGN KEY(run_id) REFERENCES mobile_campaign_runs (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(device_id) REFERENCES user_devices (id), 
	FOREIGN KEY(agent_id) REFERENCES hierarchical_entities (id), 
	FOREIGN KEY(voice_session_id) REFERENCES voice_sessions (id)
);

CREATE INDEX IF NOT EXISTS ix_attempt_cli_lookup ON mobile_call_attempts (device_cli, did) WHERE status IN ('pending', 'ai_connected');

CREATE INDEX IF NOT EXISTS ix_mobile_call_attempts_campaign_call_id ON mobile_call_attempts (campaign_call_id);

CREATE INDEX IF NOT EXISTS ix_mobile_call_attempts_campaign_id ON mobile_call_attempts (campaign_id);

CREATE INDEX IF NOT EXISTS ix_mobile_call_attempts_company_id ON mobile_call_attempts (company_id);

CREATE INDEX IF NOT EXISTS ix_mobile_call_attempts_run_id ON mobile_call_attempts (run_id);

CREATE INDEX IF NOT EXISTS ix_mobile_call_attempts_user_id ON mobile_call_attempts (user_id);

CREATE INDEX IF NOT EXISTS ix_mobile_call_attempts_voice_session_id ON mobile_call_attempts (voice_session_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_attempt_open_per_device ON mobile_call_attempts (device_id) WHERE status IN ('pending', 'ai_connected', 'ai_ready', 'unidentified_ready', 'merged');

CREATE UNIQUE INDEX IF NOT EXISTS uq_attempt_token_open ON mobile_call_attempts (did, dtmf_token) WHERE status IN ('pending', 'ai_connected', 'ai_ready', 'unidentified_ready', 'merged');

CREATE TABLE IF NOT EXISTS mobile_call_events (
	id UUID NOT NULL, 
	attempt_id UUID NOT NULL, 
	seq INTEGER NOT NULL, 
	type VARCHAR(40) NOT NULL, 
	device_ts TIMESTAMP WITHOUT TIME ZONE, 
	elapsed_ms INTEGER, 
	received_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	payload JSONB NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(attempt_id) REFERENCES mobile_call_attempts (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_event_seq ON mobile_call_events (attempt_id, seq);

COMMIT;
