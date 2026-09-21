-- ============================================================================
-- Mobile dialer: app diagnostic logs (docs/mobile-dialer-app/10 §6)
--
-- Idempotent and additive. Apply BEFORE deploying the code that writes to it:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/db-scripts/mobile_dialer_002_logs.sql
-- Also applied by Alembic revision m0b1e0d1a200.
-- ============================================================================
BEGIN;

-- New table only: no locks on the busy campaign tables.
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS mobile_client_logs (
	id UUID NOT NULL, 
	company_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	device_id UUID, 
	run_id UUID, 
	attempt_id UUID, 
	seq INTEGER NOT NULL, 
	level VARCHAR(10) NOT NULL, 
	tag VARCHAR(64) NOT NULL, 
	message TEXT NOT NULL, 
	fields JSONB NOT NULL, 
	app_version VARCHAR(50), 
	device_ts TIMESTAMP WITHOUT TIME ZONE, 
	received_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(company_id) REFERENCES companies (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS ix_mobile_client_logs_attempt_id ON mobile_client_logs (attempt_id);

CREATE INDEX IF NOT EXISTS ix_mobile_client_logs_company_id ON mobile_client_logs (company_id);

CREATE INDEX IF NOT EXISTS ix_mobile_logs_company_time ON mobile_client_logs (company_id, received_at);

CREATE INDEX IF NOT EXISTS ix_mobile_logs_device_time ON mobile_client_logs (device_id, received_at);

COMMIT;
