"""The people and companies the journeys use (Phase 15 T10-2, 08 §5 "E2E per role").

``build(tag)`` commits, to the database the running stack uses, one of each:

* a business billed in INR (onboarded) with an admin and a user, its wallet
  funded with ₹2,000 of top-up credit;
* a Gold partner (active, KYC verified, agreement signed) with an admin, a
  customer it resells under an ``admin`` grant, an accrued commission on that
  customer, and a second business it does **not** resell;
* a Silver partner with an admin, and a customer it referred.

Every name and address carries ``tag``. Locally (one shared database) each
run uses a fresh tag and ``teardown`` deletes exactly those companies and
users (``tests.harness.purge``).

With split tenancy (Azure dev) a company's workspace — its database,
namespace and identity — cannot be removed, so the journeys keep one set of
companies under a fixed tag (``persistent``): ``build`` makes what is missing
and has the provisioner set up each new workspace (waiting until it is
``active``), and on every run puts back the state the journeys start from —
the wallet, the partners' types, assignments, grants, agreement and
commission. ``teardown`` then deletes nothing but a sign-up's company.

Each call runs on an engine of its own with no pool, so it can be driven by
``asyncio.run`` from a synchronous Playwright test, or in an API pod
(``tests.journeys.remote``).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Awaitable, Callable, Dict, List

PASSWORD = "Journey-Passw0rd-2026"
PROVISIONING_TIMEOUT_SECONDS = 900
# The rows a journey leaves on its business and partners, cleared before each run (children first).
_STATE_TABLES = ("wallet_entries", "wallet_lots", "credit_holds", "credit_wallets", "usage_logs", "billing_lines")


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
    persistent: bool = False                                   # split tenancy: kept between runs
    extra_companies: List[uuid.UUID] = field(default_factory=list)

    @property
    def company_ids(self) -> List[uuid.UUID]:
        return [self.business, self.gold, self.gold_customer, self.not_resold, self.silver, self.silver_customer]

    @property
    def email_pattern(self) -> str:
        return f"journey\\_%\\_{self.tag}@example.com"

    def to_json(self) -> Dict[str, Any]:
        return {k: (str(v) if isinstance(v, uuid.UUID) else [str(x) for x in v] if k == "extra_companies" else v)
                for k, v in asdict(self).items()}

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "World":
        ids = ("business", "gold", "gold_customer", "not_resold", "silver", "silver_customer")
        return cls(**{**data, **{k: uuid.UUID(data[k]) for k in ids},
                      "extra_companies": [uuid.UUID(x) for x in data.get("extra_companies", [])]})


def email(role: str, tag: str) -> str:
    return f"journey_{role}_{tag}@example.com"


async def _with_db(work: Callable[[Any], Awaitable[Any]]) -> Any:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from src.common import database
    from src.common.config import settings
    from src.common.orm_models import import_all_models

    import_all_models()
    # As the platform makes its own (src.common.database): on Azure an Entra token per connection.
    from src.common.platform.dbauth import install

    engine = create_async_engine(settings.CONTROL_DATABASE_URL, poolclass=NullPool,
                                 json_serializer=database.json_serializer)
    install(engine)
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


def split() -> bool:
    from src.common.tenancy.session import is_split
    return is_split()


async def _company(db: Any, name: str, kind: str, *, parent: Any = None, currency: str = "INR") -> Any:
    """The company called ``name`` (made if there is none), active under ``parent``."""
    from sqlalchemy import select

    from src.auth.models import Company

    company = (await db.execute(select(Company).where(Company.name == name))).scalar_one_or_none()
    if company is None:
        company = Company(name=name, type=kind, status="active", billing_currency=currency,
                          country_code="IN" if currency == "INR" else "US",
                          billing_state="KA" if currency == "INR" else None, onboarding_status="completed")
        db.add(company)
    company.status, company.parent_id = "active", parent
    await db.flush()
    return company


async def _person(db: Any, address: str, role: str, company_id: Any) -> None:
    from sqlalchemy import select

    from src.auth.models import User
    from src.common.security import get_password_hash

    user = (await db.execute(select(User).where(User.email == address))).scalar_one_or_none()
    if user is None:
        user = User(email=address, full_name=f"Journey {role}")
        db.add(user)
    user.hashed_password, user.role, user.company_id = get_password_hash(PASSWORD), role, company_id
    user.is_active, user.is_verified = True, True


async def _partner(db: Any, name: str, partner_type: str) -> Any:
    """An active, KYC-verified partner of ``partner_type`` with one signed agreement, whatever a run left."""
    from sqlalchemy import delete

    from src.partners.lifecycle import create_profile, new_agreement
    from src.partners.models import PartnerAgreement, PartnerProfile

    company = await _company(db, name, "PARTNER")
    profile = await db.get(PartnerProfile, company.id)
    if profile is None:
        profile = await create_profile(db, company, partner_type=partner_type, status="active")
    profile.partner_type, profile.status, profile.status_reason = partner_type, "active", None
    profile.kyc_status, profile.bank_verified = "verified", True
    profile.agreement_id = None
    await db.flush()
    await db.execute(delete(PartnerAgreement).where(PartnerAgreement.partner_id == company.id))
    agreement = await new_agreement(db, profile)
    agreement.signed_at = datetime.utcnow()
    return company


async def _clear(db: Any, company_ids: List[Any], partner_ids: List[Any]) -> None:
    """What earlier runs left: the companies' wallets and usage, the partners' grants, customers and earnings."""
    from sqlalchemy import delete, text

    from src.partners.models import PartnerAccessEvent, PartnerAccessGrant, PartnerAssignment, PartnerLedgerEntry

    for table in _STATE_TABLES:
        await db.execute(text(f"DELETE FROM {table} WHERE company_id = ANY(CAST(:ids AS uuid[]))"),
                         {"ids": [str(i) for i in company_ids]})
    for model in (PartnerAccessEvent, PartnerAccessGrant, PartnerLedgerEntry):
        await db.execute(delete(model).where(model.partner_id.in_(partner_ids)))
    await db.execute(delete(PartnerAssignment).where(PartnerAssignment.tenant_id.in_(company_ids)))


async def _provision(company_ids: List[Any]) -> None:
    """Split tenancy: each company's workspace requested from the provisioner, and waited for."""
    from src.common.tenancy.provisioner import provisioning_status, request_and_enqueue
    from src.common.tenancy.session import control_session

    for company_id in company_ids:
        async with control_session() as db:
            status = await provisioning_status(db, company_id)
        if status["status"] == "not_requested" or (not status["ready"] and status["status"] != "provisioning"):
            await request_and_enqueue(company_id)
    deadline = time.monotonic() + PROVISIONING_TIMEOUT_SECONDS
    waiting = list(company_ids)
    while waiting:
        async with control_session() as db:
            waiting = [c for c in waiting if not (await provisioning_status(db, c))["ready"]]
        if not waiting:
            return
        if time.monotonic() > deadline:
            raise TimeoutError(f"workspaces not active after {PROVISIONING_TIMEOUT_SECONDS} s: {waiting}")
        await asyncio.sleep(10)


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
        not_resold = await _company(db, names["not_resold"], "TENANT", parent=platform)
        silver = await _partner(db, names["silver"], "SILVER")
        silver_customer = await _company(db, names["silver_customer"], "TENANT", parent=platform)
        companies = [business, gold, gold_customer, not_resold, silver, silver_customer]
        await _clear(db, [c.id for c in companies], [gold.id, silver.id])

        await assign(db, tenant_id=gold_customer.id, partner_id=gold.id, relationship="resold", source="created",
                     since=datetime.utcnow() - timedelta(days=60))
        await grant_for_created_tenant(db, partner_id=gold.id, tenant_id=gold_customer.id)
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
        from src.billing.wallet import WalletService
        for company in companies:                       # every company has a wallet, as when it is created
            await WalletService(db).ensure(company.id)
        await fund(db, business.id, "20", expires_in=timedelta(days=30))          # ₹2,000 at the seeded rate
        await db.commit()
        if split():
            await _provision([c.id for c in companies])
        return World(tag=tag, business=business.id, gold=gold.id, gold_customer=gold_customer.id,
                     not_resold=not_resold.id, silver=silver.id, silver_customer=silver_customer.id,
                     emails=emails, names=names, persistent=split())

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
    """Delete the run's companies and people — locally. A persistent world stays for the next run."""
    async def work(db: Any) -> None:
        from tests.harness.purge import purge_companies

        conn = await db.connection()
        if world.persistent:
            await purge_companies(conn, list(extra_companies))
        else:
            await purge_companies(conn, [*world.company_ids, *extra_companies], user_email_pattern=world.email_pattern)
        await db.commit()

    run(work)
