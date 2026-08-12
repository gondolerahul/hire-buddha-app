"""
Migration: Merge phone_number_pool + customer_phone_numbers → phone_numbers

This script:
  1. Creates the new unified `phone_numbers` table
  2. Migrates data from `phone_number_pool` (pool inventory)
  3. Migrates data from `customer_phone_numbers` (agent assignments)
  4. Handles overlapping numbers (same number in both tables)
  5. Drops the old tables

Run with:  cd backend && .venv/bin/python -m migrations.merge_phone_tables
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5433/hirebuddha"


async def migrate():
    engine = create_async_engine(DATABASE_URL)

    async with engine.begin() as conn:
        # 1. Check if old tables exist
        pool_exists = await conn.scalar(
            text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'phone_number_pool')")
        )
        cpn_exists = await conn.scalar(
            text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'customer_phone_numbers')")
        )
        new_exists = await conn.scalar(
            text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'phone_numbers')")
        )

        print(f"phone_number_pool exists:      {pool_exists}")
        print(f"customer_phone_numbers exists:  {cpn_exists}")
        print(f"phone_numbers (new) exists:     {new_exists}")

        # 2. Create the new table if it doesn't exist
        if not new_exists:
            print("\n→ Creating phone_numbers table...")
            await conn.execute(text("""
                CREATE TABLE phone_numbers (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    phone_number VARCHAR(20) UNIQUE NOT NULL,
                    provider VARCHAR(20) NOT NULL,
                    country_code VARCHAR(5) NOT NULL DEFAULT '+91',
                    status VARCHAR(20) NOT NULL DEFAULT 'available',

                    company_id UUID REFERENCES companies(id),
                    claimed_by_user_id UUID REFERENCES users(id),
                    claimed_at TIMESTAMP,

                    agent_id UUID REFERENCES hierarchical_entities(id),
                    customer_id UUID,
                    customer_name VARCHAR(255),
                    customer_metadata JSONB,
                    assigned_at TIMESTAMP,

                    provider_sid VARCHAR(100),
                    capabilities JSONB,
                    monthly_cost_usd NUMERIC(10,4),
                    label VARCHAR(100),
                    notes VARCHAR(500),

                    added_by_user_id UUID REFERENCES users(id),
                    is_active BOOLEAN NOT NULL DEFAULT true,

                    created_at TIMESTAMP DEFAULT now(),
                    updated_at TIMESTAMP DEFAULT now()
                )
            """))
            print("  ✓ Table created")

            # Create indexes
            for idx_sql in [
                "CREATE INDEX idx_phone_numbers_phone ON phone_numbers(phone_number)",
                "CREATE INDEX idx_phone_numbers_status ON phone_numbers(status)",
                "CREATE INDEX idx_phone_numbers_company ON phone_numbers(company_id)",
                "CREATE INDEX idx_phone_numbers_agent ON phone_numbers(agent_id)",
                "CREATE INDEX idx_phone_numbers_customer ON phone_numbers(customer_id)",
                "CREATE INDEX idx_phone_numbers_provider ON phone_numbers(provider)",
            ]:
                await conn.execute(text(idx_sql))
            print("  ✓ Indexes created")
        else:
            print("\n→ phone_numbers table already exists — checking for data migration")

        # 3. Migrate data from phone_number_pool
        if pool_exists:
            count = await conn.scalar(text("SELECT COUNT(*) FROM phone_number_pool"))
            print(f"\n→ Migrating {count} rows from phone_number_pool...")
            if count > 0:
                await conn.execute(text("""
                    INSERT INTO phone_numbers (
                        id, phone_number, provider, country_code, status,
                        company_id, claimed_by_user_id, claimed_at,
                        provider_sid, capabilities, monthly_cost_usd, label, notes,
                        added_by_user_id, is_active, created_at, updated_at
                    )
                    SELECT
                        id, phone_number, provider, country_code, status,
                        claimed_by_company_id, claimed_by_user_id, claimed_at,
                        provider_sid, capabilities, monthly_cost_usd, label, notes,
                        added_by_user_id, true, created_at, updated_at
                    FROM phone_number_pool
                    ON CONFLICT (phone_number) DO NOTHING
                """))
                migrated = await conn.scalar(
                    text("SELECT COUNT(*) FROM phone_numbers WHERE added_by_user_id IS NOT NULL")
                )
                print(f"  ✓ Migrated {migrated} numbers from pool")

        # 4. Migrate data from customer_phone_numbers
        if cpn_exists:
            count = await conn.scalar(text("SELECT COUNT(*) FROM customer_phone_numbers"))
            print(f"\n→ Migrating {count} rows from customer_phone_numbers...")
            if count > 0:
                # For numbers that already exist (from pool migration),
                # UPDATE them with the assignment data
                await conn.execute(text("""
                    UPDATE phone_numbers pn
                    SET
                        status = 'assigned',
                        company_id = COALESCE(pn.company_id, cpn.company_id),
                        agent_id = cpn.agent_id,
                        customer_id = cpn.customer_id,
                        customer_name = cpn.customer_name,
                        customer_metadata = cpn.customer_metadata,
                        assigned_at = cpn.assigned_at,
                        is_active = cpn.is_active
                    FROM customer_phone_numbers cpn
                    WHERE pn.phone_number = LTRIM(cpn.phone_number, '+')
                       OR pn.phone_number = cpn.phone_number
                """))

                # For numbers that don't exist yet, INSERT them
                await conn.execute(text("""
                    INSERT INTO phone_numbers (
                        id, phone_number, provider, country_code, status,
                        company_id, agent_id, customer_id, customer_name,
                        customer_metadata, assigned_at, is_active,
                        created_at, updated_at
                    )
                    SELECT
                        cpn.id,
                        LTRIM(cpn.phone_number, '+'),
                        cpn.provider,
                        CASE
                            WHEN cpn.phone_number LIKE '+91%%' THEN '+91'
                            WHEN cpn.phone_number LIKE '+1%%' THEN '+1'
                            WHEN cpn.phone_number LIKE '+44%%' THEN '+44'
                            ELSE '+91'
                        END,
                        'assigned',
                        cpn.company_id,
                        cpn.agent_id,
                        cpn.customer_id,
                        cpn.customer_name,
                        cpn.customer_metadata,
                        cpn.assigned_at,
                        cpn.is_active,
                        cpn.assigned_at,
                        cpn.assigned_at
                    FROM customer_phone_numbers cpn
                    WHERE NOT EXISTS (
                        SELECT 1 FROM phone_numbers pn
                        WHERE pn.phone_number = LTRIM(cpn.phone_number, '+')
                           OR pn.phone_number = cpn.phone_number
                    )
                    ON CONFLICT (phone_number) DO NOTHING
                """))
                total = await conn.scalar(text("SELECT COUNT(*) FROM phone_numbers"))
                print(f"  ✓ Total numbers in unified table: {total}")

        # 5. Summary
        total_final = await conn.scalar(text("SELECT COUNT(*) FROM phone_numbers"))
        by_status = await conn.execute(
            text("SELECT status, COUNT(*) FROM phone_numbers GROUP BY status ORDER BY status")
        )
        print(f"\n✅ Migration complete! {total_final} numbers in unified table:")
        for row in by_status:
            print(f"   {row[0]}: {row[1]}")

        # 6. Rename old tables (keep as backup, don't drop yet)
        if pool_exists:
            await conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'phone_number_pool_old') THEN
                        ALTER TABLE phone_number_pool RENAME TO phone_number_pool_old;
                    END IF;
                END $$;
            """))
            print("\n→ Renamed phone_number_pool → phone_number_pool_old (backup)")

        if cpn_exists:
            await conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'customer_phone_numbers_old') THEN
                        ALTER TABLE customer_phone_numbers RENAME TO customer_phone_numbers_old;
                    END IF;
                END $$;
            """))
            print("→ Renamed customer_phone_numbers → customer_phone_numbers_old (backup)")

    await engine.dispose()
    print("\n🎉 Done! Old tables preserved as *_old. Drop them when confident.")


if __name__ == "__main__":
    asyncio.run(migrate())
