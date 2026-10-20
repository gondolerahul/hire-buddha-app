-- Azure dev: inside hb_control (status doc §3 step 4). Run once, connected to
-- "hb_control" as the Entra admin, after control-server-roles.sql. Safe to run again.
\set ON_ERROR_STOP on

-- The migrator is not a server admin, so the extensions are made here.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Until WS2 splits the schemas, today's tables stay in public.
GRANT CREATE, USAGE ON SCHEMA public TO hb_migrator;
GRANT USAGE ON SCHEMA public TO hb_runtime;

-- Tables and sequences the migrator creates are usable by the API and workers.
ALTER DEFAULT PRIVILEGES FOR ROLE "id-hb-dev-migrator" IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLES TO hb_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE "id-hb-dev-migrator" IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO hb_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE "id-hb-dev-migrator"
  GRANT USAGE ON SCHEMAS TO hb_runtime;
