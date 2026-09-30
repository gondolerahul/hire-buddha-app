-- =============================================================================
-- clean_db.sql
-- Database Cleanup Script — HireBuddha
-- =============================================================================
-- PURPOSE:
--   Removes all transactional data from every table, preserving ONLY master /
--   seed data that is required for the system to operate correctly.
--
-- MASTER DATA PRESERVED:
--   • alembic_version       — the schema revision
--   • subscription_tiers    — App-Admin configured billing tiers (system config)
--   • tool_registry_entries WHERE tool_type = 'BUILT_IN' — system-seeded tools
--     (their company_id / created_by are cleared: those rows are gone)
--
-- EVERY OTHER TABLE in the public schema is truncated. The list is read from
-- the database (DM-15): a new table is covered the day its migration runs,
-- instead of when someone remembers to add it here.
--
-- USAGE:
--   PGPASSWORD=postgres psql -U postgres -h localhost -p 5433 -d hirebuddha -v ON_ERROR_STOP=1 -f clean_db.sql
--
-- CAUTION:
--   ⚠️  This is IRREVERSIBLE. Take a database backup before running.
--   ⚠️  Designed for development / staging environments only.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- Step 1: Keep the BUILT_IN tools aside. tool_registry_entries references
-- companies and users, so truncating those (CASCADE) empties it too — the old
-- hand-listed version of this script lost every BUILT_IN tool that way.
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE keep_builtin_tools ON COMMIT DROP AS
    SELECT * FROM tool_registry_entries WHERE tool_type = 'BUILT_IN';
UPDATE keep_builtin_tools SET company_id = NULL, created_by = NULL;

-- ---------------------------------------------------------------------------
-- Step 2: Truncate every other table in one statement.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    keep CONSTANT TEXT[] := ARRAY['alembic_version', 'subscription_tiers'];
    tables TEXT;
BEGIN
    SELECT string_agg(format('%I', tablename), ', ' ORDER BY tablename)
      INTO tables
      FROM pg_tables
     WHERE schemaname = 'public' AND tablename <> ALL (keep);
    IF tables IS NOT NULL THEN
        EXECUTE 'TRUNCATE TABLE ' || tables || ' RESTART IDENTITY CASCADE';
        RAISE NOTICE 'TRUNCATED: %', tables;
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------
-- Step 3: Put the BUILT_IN tools back.
-- ---------------------------------------------------------------------------
INSERT INTO tool_registry_entries SELECT * FROM keep_builtin_tools;

-- ---------------------------------------------------------------------------
-- Step 4: Verification — report the tables that still hold rows
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    tbl TEXT;
    cnt BIGINT;
BEGIN
    RAISE NOTICE '=== Tables with rows left ===';
    FOR tbl IN
        SELECT tablename
        FROM   pg_tables
        WHERE  schemaname = 'public'
        ORDER  BY tablename
    LOOP
        EXECUTE format('SELECT COUNT(*) FROM %I', tbl) INTO cnt;
        IF cnt > 0 THEN
            RAISE NOTICE '  %-40s → % rows', tbl, cnt;
        END IF;
    END LOOP;
    RAISE NOTICE '=============================';
END;
$$;

COMMIT;

-- =============================================================================
-- End of clean_db.sql
-- =============================================================================
