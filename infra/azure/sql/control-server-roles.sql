-- Azure dev: the control server's workload logins and roles (setup guide §10.5,
-- status doc §3 step 4). Run once, connected to the "postgres" database as the
-- Entra admin (a member of grp-hb-dev-pg-admins). Safe to run again.
\set ON_ERROR_STOP on

-- Entra principals for the workloads that sign in with their managed identity.
DO $$
DECLARE who text;
BEGIN
  FOREACH who IN ARRAY ARRAY['id-hb-dev-api', 'id-hb-dev-worker', 'id-hb-dev-connsvc', 'id-hb-dev-migrator',
                             'id-hb-dev-provisioner'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = who) THEN
      PERFORM pgaadauth_create_principal(who, false, false);
    END IF;
  END LOOP;
END $$;

-- Group roles of the tech spec (§5.2).
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hb_runtime') THEN CREATE ROLE hb_runtime NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hb_dataapi') THEN CREATE ROLE hb_dataapi NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hb_migrator') THEN CREATE ROLE hb_migrator NOLOGIN; END IF;
END $$;
GRANT hb_runtime TO "id-hb-dev-worker", "id-hb-dev-api", "id-hb-dev-connsvc";
GRANT hb_migrator TO "id-hb-dev-migrator";
-- The provisioner creates tenant databases (WS2 2.8) and roles for them.
ALTER ROLE "id-hb-dev-provisioner" CREATEDB CREATEROLE;
-- The admin group may act for the migrator (needed for ALTER DEFAULT PRIVILEGES below).
GRANT "id-hb-dev-migrator" TO "grp-hb-dev-pg-admins";

-- hb_control: who may connect and what the migrator may create.
REVOKE CONNECT ON DATABASE hb_control FROM PUBLIC;
GRANT CONNECT ON DATABASE hb_control TO hb_runtime, hb_migrator, "id-hb-dev-provisioner";
GRANT CREATE ON DATABASE hb_control TO hb_migrator;
