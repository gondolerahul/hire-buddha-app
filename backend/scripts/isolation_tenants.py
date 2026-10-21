"""Two businesses for the isolation suite (Phase 14 M2-3, tech spec §13.3).

Run where the platform's own settings are (an API pod on Azure, or this laptop
against the local stack)::

    python -m scripts.isolation_tenants [--api http://localhost:8000] [--ttl-minutes 60] --out fixtures.json

Through the platform's own API, as the platform admin: makes the companies
"Isolation A" and "Isolation B" (TENANT) if they are not there — in split mode
each gets its own database by that one call (WS2 2.9) —, waits until both
workspaces are ``active``, and gives each a ``tenant_admin``. Then prints, as
JSON, each business's company id, tenant key and a short-lived access token for
its admin, which is what ``tests/isolation`` reads (``ISOLATION_FIXTURES``).

Nobody signs in: the tokens are minted here with the platform's signing key,
and the admins' passwords are random and never shown. Running it again reuses
the companies and users and mints new tokens.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
import time
from datetime import timedelta

import httpx

ADMIN_EMAIL = "admin@hirebuddha.com"
BUSINESSES = {"a": "Isolation A", "b": "Isolation B"}


def _email(side: str) -> str:
    return f"isolation-{side}@example.com"


async def _user(email: str):
    from sqlalchemy import select

    from src.auth.models import User
    from src.common.tenancy.session import control_session

    async with control_session() as db:
        return (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()


def _token(user, ttl: timedelta) -> str:
    from src.common.security import create_access_token

    return create_access_token({"sub": user.email, "type": "access", "tv": user.token_version or 0}, ttl)


async def _company(client: httpx.AsyncClient, name: str) -> dict:
    listed = await client.get("/api/v1/companies")
    listed.raise_for_status()
    for company in listed.json():
        if company["name"] == name and company["type"] == "TENANT":
            return company
    made = await client.post("/api/v1/companies", json={"name": name, "type": "TENANT"})
    made.raise_for_status()
    return made.json()


async def _active(client: httpx.AsyncClient, company_id: str, wait: float) -> dict:
    """The business's directory row once it is ``active``; asks for it if it was never requested."""
    deadline = time.monotonic() + wait
    asked = False
    while True:
        got = await client.get(f"/api/v1/admin/tenants/{company_id}")
        if got.status_code == 404 and not asked:
            (await client.post("/api/v1/admin/tenants", json={"company_id": company_id})).raise_for_status()
            asked = True
        elif got.status_code == 200:
            row = got.json()
            status = row["status"]
            if status == "active":
                return row
            if status == "failed" and not asked:
                (await client.post(f"/api/v1/admin/tenants/{company_id}/provision")).raise_for_status()
                asked = True
        if time.monotonic() > deadline:
            raise SystemExit(f"workspace of {company_id} not active after {wait:.0f}s: {got.text[:500]}")
        await asyncio.sleep(3)


async def main(api: str, ttl: timedelta, wait: float) -> dict:
    import src.main  # noqa: F401 — every mapper, as the API has them

    admin = await _user(ADMIN_EMAIL)
    if admin is None:
        raise SystemExit(f"{ADMIN_EMAIL} does not exist here")
    headers = {"Authorization": f"Bearer {_token(admin, timedelta(minutes=10))}"}
    out: dict = {}
    async with httpx.AsyncClient(base_url=api, headers=headers, timeout=60) as client:
        for side, name in BUSINESSES.items():
            company = await _company(client, name)
            row = await _active(client, company["id"], wait)
            email = _email(side)
            if await _user(email) is None:
                made = await client.post("/api/v1/users", json={
                    "email": email, "full_name": f"{name} admin", "company_id": company["id"],
                    "role": "tenant_admin", "password": secrets.token_urlsafe(24) + "aA1!"})
                made.raise_for_status()
            user = await _user(email)
            out[side] = {"company_id": company["id"], "tenant_key": row["tenant_key"], "email": email,
                         "token": _token(user, ttl)}
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--ttl-minutes", type=int, default=60)
    parser.add_argument("--wait", type=float, default=300, help="seconds to wait for each workspace")
    parser.add_argument("--out", help="write the JSON here instead of to stdout (imports may print there)")
    args = parser.parse_args()
    fixtures = asyncio.run(main(args.api, timedelta(minutes=args.ttl_minutes), args.wait))
    text = json.dumps(fixtures, indent=2) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
