-- =============================================================================
-- clean_db.sql
-- Database Cleanup Script — HireBuddha Proto-3
-- =============================================================================
-- PURPOSE:
--   Drops all transactional data from every table, preserving ONLY master /
--   seed data that is required for the system to operate correctly.
--
-- MASTER DATA PRESERVED (not touched):
--   • subscription_tiers   — App-Admin configured billing tiers (system config)
--   • tool_registry_entries WHERE tool_type = 'BUILT_IN'  — system-seeded tools
--
-- ALL OTHER TABLES are fully truncated (user accounts, companies, entities,
-- runs, logs, billing records, sessions, CORTEX trees, etc.)
--
-- USAGE:
--   PGPASSWORD=postgres psql -U postgres -h localhost -p 5433 -d hirebuddha -f clean_db.sql
--
-- CAUTION:
--   ⚠️  This is IRREVERSIBLE. Take a database backup before running.
--   ⚠️  Designed for development / staging environments only.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- Step 1: Truncate all transactional tables.
-- Tables are listed in dependency order. CASCADE covers any remaining FK refs.
-- Tables that don't exist yet (pending migrations) are silently skipped.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    -- List of tables to TRUNCATE, in safe order (leaves → roots)
    -- MASTER DATA tables are excluded: subscription_tiers, tool_registry_entries
    tables_to_truncate TEXT[] := ARRAY[
        'cortex_nodes',
        'cortex_trees',
        'llm_interaction_logs',
        'tool_interaction_logs',
        'human_approvals',
        'usage_logs',
        'call_content',
        'call_logs',
        'artifacts',
        'assets',
        'conversation_history',
        'campaign_calls',
        'voice_sessions',
        'whatsapp_sessions',
        'customer_phone_numbers',
        'campaigns',
        'document_chunks',
        'documents',
        'episodic_memories',
        'execution_runs',
        'hierarchical_entities',
        'email_connections',
        'social_connections',
        'billing_events',
        'payment_transactions',
        'subscriptions',
        'credit_wallets',
        'billing_config',
        'model_task_defaults',
        'integration_registry',
        'refresh_tokens',
        'users',
        'companies'
    ];
    tbl TEXT;
    tbl_exists BOOLEAN;
BEGIN
    FOREACH tbl IN ARRAY tables_to_truncate
    LOOP
        SELECT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = 'public' AND tablename = tbl
        ) INTO tbl_exists;

        IF tbl_exists THEN
            EXECUTE format('TRUNCATE TABLE %I RESTART IDENTITY CASCADE', tbl);
            RAISE NOTICE 'TRUNCATED: %', tbl;
        ELSE
            RAISE NOTICE 'SKIPPED (not found): %', tbl;
        END IF;
    END LOOP;
END;
$$;

-- ---------------------------------------------------------------------------
-- Step 2: Tool Registry — delete CUSTOM tools only; preserve BUILT_IN entries.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables
        WHERE schemaname = 'public' AND tablename = 'tool_registry_entries'
    ) THEN
        DELETE FROM tool_registry_entries WHERE tool_type = 'CUSTOM';
        RAISE NOTICE 'Deleted CUSTOM tool_registry_entries (BUILT_IN preserved)';
    ELSE
        RAISE NOTICE 'SKIPPED tool_registry_entries (not found)';
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------
-- Step 3: Verification — report final row counts for all public tables
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    tbl TEXT;
    cnt BIGINT;
BEGIN
    RAISE NOTICE '=== Final Row Counts ===';
    FOR tbl IN
        SELECT tablename
        FROM   pg_tables
        WHERE  schemaname = 'public'
        ORDER  BY tablename
    LOOP
        EXECUTE format('SELECT COUNT(*) FROM %I', tbl) INTO cnt;
        RAISE NOTICE '  %-40s → % rows', tbl, cnt;
    END LOOP;
    RAISE NOTICE '========================';
END;
$$;

COMMIT;

-- =============================================================================
-- End of clean_db.sql
-- =============================================================================
