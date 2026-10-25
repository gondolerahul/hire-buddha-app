"""The people and companies the journeys use (Phase 15 T10-2, 08 §5 "E2E per role").

``build(tag)`` commits, to the database the running stack uses, one of each:

* a business billed in INR (onboarded) with an admin and a user, its wallet
  funded with ₹2,000 of top-up credit;
* a Gold partner (active, KYC verified, agreement signed) with an admin, a
  customer it resells under an ``admin`` grant, an accrued commission on that
  customer, and a second business it does **not** resell;
* a Silver partner with an admin, and a customer it referred.

Every name and address carries ``tag``, and ``teardown`` deletes exactly
those companies and users (``tests.harness.purge``). Each call runs on an
engine of its own with no pool, so it can be driven by ``asyncio.run`` from a
synchronous Playwright test.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Awaitable, Callable, Dict, List

PASSWORD = "Journey-Passw0rd-2026"


@dataclass
class World:
    tag: str
    business: uuid.UUID
    gold: uuid.UUID
    gold_customer: uuid.UUID
    not_resold: uuid.UUID
    silver: uuid.UUID
    silver_customer: uuid.UUID
    emails: Dict[str, str] = field(default_factory=dict)       # role key -> e-mail
    names: Dict[str, str] = field(default_factory=dict)        # company key -> name

    @property
    def company_ids(self) -> List[uuid.UUID]:
        return [self.business, self.gold, self.gold_customer, self.not_resold, self.silver, self.silver_customer]

    @property
    def email_pattern(self) -> str:
        return f"journey\\_%\\_{self.tag}@example.com"


def email(role: str, tag: str) -> str:
    return f"journey_{role}_{tag}@example.com"


async def _with_db(work: Callable[[Any], Awaitable[Any]]) -> Any:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from src.common import database
    from src.common.config import settings
    from src.common.orm_models import import_all_models

    import_all_models()
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    # Code that opens control sessions of its own (notices, audits) uses this engine too.
    saved = database.AsyncSessionLocal, database.engine
    database.AsyncSessionLocal, database.engine = maker, engine
    try:
        async with maker() as db:
            return await work(db)
    finally:
        database.AsyncSessionLocal, database.engine = saved
        await engine.dispose()


def run(work: Callable[[Any], Awaitable[Any]]) -> Any:
    """``work(db)`` on a fresh engine, from synchronous code."""
    return asyncio.run(_with_db(work))


async def _company(db: Any, name: str, kind: str, *, parent: Any = None, currency: str = "INR") -> Any:
    from src.auth.models import Company

    company = Company(name=name, type=kind, status="active", parent_id=parent, billing_currency=currency,
                      country_code="IN" if currency == "INR" else "US", billing_state="KA" if currency == "INR" else None,
                      onboarding_status="completed")
    db.add(company)
    await db.flush()
    return company


async def _person(db: Any, address: str, role: str, company_id: Any) -> None:
    from src.auth.models import User
    from src.common.security import get_password_hash

    db.add(User(email=address, full_name=f"Journey {role}", hashed_password=get_password_hash(PASSWORD),
                role=role, company_id=company_id, is_active=True, is_verified=True))


async def _partner(db: Any, name: str, partner_type: str) -> Any:
    from src.partners.lifecycle import create_profile, new_agreement

    company = await _company(db, name, "PARTNER")
    profile = await create_profile(db, company, partner_type=partner_type, status="active")
    profile.kyc_status, profile.bank_verified = "verified", True
    agreement = await new_agreement(db, profile)
    agreement.signed_at = datetime.utcnow()
    return company


def build(tag: str) -> World:
    async def work(db: Any) -> World:
        from src.auth.platform import platform_company_id
        from src.partners.access import grant_for_created_tenant
        from src.partners.models import PartnerLedgerEntry
        from src.partners.scope import assign
        from tests.harness.wallet import fund

        platform = await platform_company_id(db)
        names = {key: f"Journey {label} {tag}" for key, label in (
            ("business", "Business"), ("gold", "Gold Partner"), ("gold_customer", "Gold Customer"),
            ("not_resold", "Other Business"), ("silver", "Silver Partner"), ("silver_customer", "Silver Referral"))}
        business = await _company(db, names["business"], "TENANT", parent=platform)
        gold = await _partner(db, names["gold"], "GOLD")
        gold_customer = await _company(db, names["gold_customer"], "TENANT", parent=gold.id)
        await assign(db, tenant_id=gold_customer.id, partner_id=gold.id, relationship="resold", source="created",
                     since=datetime.utcnow() - timedelta(days=60))
        await grant_for_created_tenant(db, partner_id=gold.id, tenant_id=gold_customer.id)
        not_resold = await _company(db, names["not_resold"], "TENANT", parent=platform)
        silver = await _partner(db, names["silver"], "SILVER")
        silver_customer = await _company(db, names["silver_customer"], "TENANT", parent=platform)
        await assign(db, tenant_id=silver_customer.id, partner_id=silver.id, relationship="referred", source="lead",
                     since=datetime.utcnow() - timedelta(days=30))
        db.add(PartnerLedgerEntry(
            partner_id=gold.id, kind="commission", amount=Decimal("20000"), currency="INR", amount_usd=Decimal("200"),
            revenue_kind="usage_topup", base_amount=Decimal("100000"), base_currency="INR", base_usd=Decimal("1000"),
            rate_pct=Decimal(20), source_type="journey", source_id=uuid.uuid4().hex, tenant_id=gold_customer.id,
            level=0, origin_partner_id=gold.id, status="accrued", payable_after=datetime.utcnow() + timedelta(days=30),
            reason=f"20 % of a INR 1,00,000.00 top-up by {names['gold_customer']}"))
        emails = {"tenant_admin": email("tenantadmin", tag), "tenant_user": email("tenantuser", tag),
                  "gold_admin": email("goldadmin", tag), "silver_admin": email("silveradmin", tag),
                  "staff": email("staff", tag)}
        await _person(db, emails["tenant_admin"], "tenant_admin", business.id)
        await _person(db, emails["tenant_user"], "tenant_user", business.id)
        await _person(db, emails["gold_admin"], "partner_admin", gold.id)
        await _person(db, emails["silver_admin"], "partner_admin", silver.id)
        await _person(db, emails["staff"], "app_admin", platform)
        await db.flush()
        await fund(db, business.id, "20", expires_in=timedelta(days=30))          # ₹2,000 at the seeded rate
        await db.commit()
        return World(tag=tag, business=business.id, gold=gold.id, gold_customer=gold_customer.id,
                     not_resold=not_resold.id, silver=silver.id, silver_customer=silver_customer.id,
                     emails=emails, names=names)

    return run(work)


def token(address: str, minutes: int = 30) -> str:
    """A short-lived access token for ``address`` (as a sign-in would issue)."""
    async def work(db: Any) -> str:
        from sqlalchemy import select

        from src.auth.models import User
        from src.common.security import create_access_token

        user = (await db.execute(select(User).where(User.email == address))).scalar_one()
        return create_access_token({"sub": user.email, "type": "access", "tv": user.token_version or 0},
                                   timedelta(minutes=minutes))

    return run(work)


def company_of(address: str) -> Any:
    """The company of the person with ``address`` (``None`` if there is none): id, type, currency."""
    async def work(db: Any) -> Any:
        from sqlalchemy import select

        from src.auth.models import Company, User

        row = (await db.execute(select(Company.id, Company.type, Company.billing_currency, Company.country_code)
                                .join(User, User.company_id == Company.id).where(User.email == address))).first()
        return None if row is None else {"id": row[0], "type": row[1], "currency": row[2], "country": row[3]}

    return run(work)


def partner_state(partner_id: uuid.UUID) -> Dict[str, Any]:
    """The partner's type and its customers' relationships now."""
    async def work(db: Any) -> Dict[str, Any]:
        from sqlalchemy import select

        from src.partners.models import PartnerAssignment, PartnerProfile

        profile = await db.get(PartnerProfile, partner_id)
        rows = (await db.execute(select(PartnerAssignment.tenant_id, PartnerAssignment.relationship).where(
            PartnerAssignment.partner_id == partner_id, PartnerAssignment.until.is_(None)))).all()
        return {"type": profile.partner_type, "customers": {t: r for t, r in rows}}

    return run(work)


def spend(company_id: uuid.UUID, billed_usd: str) -> None:
    """Usage worth ``billed_usd`` with no run, settled as the hourly job settles it (T3-6):
    lots first, the rest into debt — the wallet's state follows."""
    async def work(db: Any) -> None:
        from src.ai.orm.usage import UsageLog
        from src.billing.enforcement import wallet_changed
        from src.billing.settlement import settle_unsettled

        db.add(UsageLog(company_id=company_id, raw_quantity=Decimal(1000), calculated_cost=Decimal(billed_usd) / 2,
                        billed_usd=Decimal(billed_usd), category="ai_models", attribution="actor_step"))
        await db.flush()
        settled = await settle_unsettled(db, company_id)
        await db.commit()
        await wallet_changed(db, company_id, settled.change)

    run(work)


def pay(company_id: uuid.UUID, amount: str) -> None:
    """A verified top-up of ``amount`` in the wallet's currency — what the gateway's
    confirmation credits (the Razorpay checkout itself is not driven locally)."""
    async def work(db: Any) -> None:
        from src.billing.credit_service import CreditService

        await CreditService(db).add_wallet_credits(company_id, Decimal(amount), source_type="journey",
                                                   source_id=uuid.uuid4().hex)

    run(work)


def teardown(world: World, extra_companies: List[uuid.UUID] = ()) -> None:
    async def work(db: Any) -> None:
        from tests.harness.purge import purge_companies

        conn = await db.connection()
        await purge_companies(conn, [*world.company_ids, *extra_companies], user_email_pattern=world.email_pattern)
        await db.commit()

    run(work)
