#!/usr/bin/env python3
"""
seed_admin_user.py
------------------
Seeds the database with the HireBuddha application admin user.

WHAT IT CREATES:
  • A company of type "APP" named "HireBuddha" (idempotent — skipped if exists)
  • A user with role "app_admin" linked to that company (idempotent — skipped if exists)

CREDENTIALS:
  Email    : admin@hirebuddha.com
  Password : adminpass locally; with --password-stdin, the first line of stdin
             (Azure: the value of Key Vault's app-admin-password), which also
             replaces the password of an admin that already exists

USAGE (from the backend/ directory):
  PGPASSWORD=postgres psql -U postgres -h localhost -p 5433 -d hirebuddha \
      -c "SELECT 1" >/dev/null  # sanity check DB is up
  python db-scripts/seed_admin_user.py

Or with explicit DB URL:
  DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/hirebuddha \
      python db-scripts/seed_admin_user.py

On Azure, in an API pod (the platform's own engine signs in with the pod's
Entra token, DB_AUTH=entra_token):
  az keyvault secret show --vault-name <kv> -n app-admin-password --query value -o tsv |
      kubectl -n hb-platform exec -i deploy/hb-api -- python db-scripts/seed_admin_user.py --password-stdin
"""

import asyncio
import os
import sys
import uuid
from datetime import datetime

# ---------------------------------------------------------------------------
# Make sure the backend src package is importable when run from backend/
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from sqlalchemy.engine import make_url
from sqlalchemy.future import select

from src.auth.models import Company, User
from src.common import database
from src.common.config import settings
from src.common.security import get_password_hash
from src.common.orm_models import import_all_models

import_all_models()  # every mapper, so foreign keys to other modules resolve (companies → currencies)

ADMIN_EMAIL    = "admin@hirebuddha.com"
ADMIN_PASSWORD = "adminpass"
ADMIN_NAME     = "HireBuddha Admin"
COMPANY_NAME   = "HireBuddha"
COMPANY_TYPE   = "APP"


# ---------------------------------------------------------------------------
# Seed Logic
# ---------------------------------------------------------------------------
async def seed(password: str | None = None):
    # The platform's own engine: the URL from settings (DATABASE_URL), and on
    # Azure an Entra token as each connection's password (DB_AUTH).
    async with database.AsyncSessionLocal() as session:
        # ── 1. Ensure the APP company exists ─────────────────────────────────
        result = await session.execute(
            select(Company).where(
                Company.name == COMPANY_NAME,
                Company.type == COMPANY_TYPE,
            )
        )
        company = result.scalar_one_or_none()

        if company:
            print(f"  [SKIP] Company '{COMPANY_NAME}' ({COMPANY_TYPE}) already exists  → id={company.id}")
        else:
            company = Company(
                id=uuid.uuid4(),
                name=COMPANY_NAME,
                type=COMPANY_TYPE,
                status="active",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(company)
            await session.flush()          # obtain company.id before using it below
            print(f"  [OK]   Created company '{COMPANY_NAME}' ({COMPANY_TYPE})  → id={company.id}")

        # ── 2. Ensure the admin user exists  ─────────────────────────────────
        result = await session.execute(
            select(User).where(User.email == ADMIN_EMAIL)
        )
        user = result.scalar_one_or_none()

        if user and password:
            user.hashed_password = get_password_hash(password)
            user.token_version = (user.token_version or 0) + 1   # sessions signed in before end
            print(f"  [OK]   Password of '{ADMIN_EMAIL}' replaced  → id={user.id}")
        elif user:
            print(f"  [SKIP] User '{ADMIN_EMAIL}' already exists  → id={user.id}")
        else:
            hashed_pw = get_password_hash(password or ADMIN_PASSWORD)
            user = User(
                id=uuid.uuid4(),
                email=ADMIN_EMAIL,
                full_name=ADMIN_NAME,
                hashed_password=hashed_pw,
                company_id=company.id,
                role="app_admin",
                is_active=True,
                is_verified=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(user)
            print(f"  [OK]   Created user '{ADMIN_EMAIL}' (role=app_admin)  → id={user.id}")

        await session.commit()

    await database.engine.dispose()


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("  HireBuddha — Admin User Seed Script")
    print("=" * 60)
    print(f"  DB  : {make_url(settings.CONTROL_DATABASE_URL or settings.DATABASE_URL).render_as_string(hide_password=True)}")
    print(f"  User: {ADMIN_EMAIL}")
    print()

    password = None
    if "--password-stdin" in sys.argv[1:]:
        password = sys.stdin.readline().rstrip("\n")
        if not password:
            sys.exit("--password-stdin: no password on stdin")
    asyncio.run(seed(password))

    print()
    print("  Done ✓")
    print("=" * 60)
