"""The people and companies the journeys use (Phase 15 T10-2, 08 §5 "E2E per role").

``build(tag)`` commits, to the database the running stack uses, one of each:

* a business billed in INR (onboarded) with an admin and a user, its wallet
  funded with ₹2,000 of top-up credit;
* a Gold partner (active, KYC verified, agreement signed) with an admin, a
  customer it resells under an ``admin`` grant, an accrued commission on that
  customer, and a second business it does **not** resell;
* a Silver partner with an admin, and a customer it referred.

Every name and address carries ``tag``, and every company is a **test
business** (``is_test``). ``teardown`` deletes them with the product's own
immediate delete (docs/phase15/13 §10, decision D-7) — tenants first, then the
partners — which removes their rows, people, files and, with split tenancy
(Azure), their workspaces: database, namespace, identity, key. Locally the
delete runs here; on Azure it runs on the provisioning queue (only the
provisioner may remove what it made) and ``teardown`` waits until each is
``erased``. Immediate delete must be switched on
(``offboarding.immediate_delete_enabled``) where the journeys run.

With split tenancy ``build`` has the provisioner set up each new company's
workspace and waits until it is ``active``. Run again with a tag that exists,
``build`` reuses its companies and puts back the state the journeys start
from (wallet, partner types, assignments, grants, agreement, commission).

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
    split: bool = False                                        # each company has its own workspace
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
    company.status, company.parent_id, company.is_test = "active", parent, True
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
                     emails=emails, names=names, split=split())

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


TEARDOWN_TIMEOUT_SECONDS = 1200


def teardown(world: World, extra_companies: List[uuid.UUID] = ()) -> Dict[str, Any]:
    """Delete the run's companies with the immediate delete — the businesses, then the partners once
    nothing sits under them — and its staff user. Returns each offboarding's final state."""
    waves = [[world.gold_customer, world.silver_customer, world.not_resold, world.business, *extra_companies],
             [world.gold, world.silver]]
    states: Dict[str, str] = {}

    async def start(db: Any, wave: List[uuid.UUID]) -> List[str]:
        from types import SimpleNamespace

        from src.auth.models import Company, User
        from src.billing.settings_catalogue import value
        from src.offboarding import service
        from sqlalchemy import select

        if not await value(db, "offboarding.immediate_delete_enabled"):
            raise RuntimeError("turn on offboarding.immediate_delete_enabled where the journeys run")
        if world.split and extra_companies:
            await _provision([c for c in extra_companies if c in wave])   # a sign-up's workspace finishes first
        staff = (await db.execute(select(User).where(User.email == world.emails.get("staff", "")))).scalar_one()
        actor = SimpleNamespace(id=staff.id, role="app_admin", company_id=staff.company_id, email=staff.email)
        ids = []
        for company_id in wave:
            company = await db.get(Company, company_id)
            if company is None:
                continue
            if not company.is_test:          # a sign-up's company: no money moved, so it may be one
                await service.set_test(db, company_id, True, actor=actor, reason="journey teardown")
            made = await service.delete_immediately(db, company_id, actor=actor, reason=f"journeys {world.tag}",
                                                    confirm_name=company.name, queue=world.split)
            ids += [str(o.id) for o in made]
        return ids

    async def inline(db: Any, ids: List[str]) -> Dict[str, str]:
        from src.offboarding.runner import run as run_offboarding
        return {i: (await run_offboarding(uuid.UUID(i)))["state"] for i in ids}

    async def current(db: Any, ids: List[str]) -> Dict[str, str]:
        from src.offboarding.models import CompanyOffboarding
        return {i: (await db.get(CompanyOffboarding, uuid.UUID(i))).state for i in ids}

    for wave in waves:
        ids = run(lambda db, wave=wave: start(db, wave))
        if not world.split:
            states.update(run(lambda db, ids=ids: inline(db, ids)))
        else:
            deadline = time.monotonic() + TEARDOWN_TIMEOUT_SECONDS
            while True:
                now = run(lambda db, ids=ids: current(db, ids))
                if all(s in ("erased", "failed") for s in now.values()) or time.monotonic() > deadline:
                    break
                time.sleep(10)
            states.update(now)
        if any(s != "erased" for s in states.values()):
            return states                      # a partner is not deleted while its businesses remain

    async def staff_gone(db: Any) -> None:
        from sqlalchemy import delete

        from src.auth.models import User

        await db.execute(delete(User).where(User.email == world.emails.get("staff", "")))
        await db.commit()

    run(staff_gone)
    return states


def find(tag: str) -> World:
    """The world made earlier under ``tag`` (to delete what an old run left)."""
    async def work(db: Any) -> World:
        from sqlalchemy import select

        from src.auth.models import Company

        names = {key: f"Journey {label} {tag}" for key, label in (
            ("business", "Business"), ("gold", "Gold Partner"), ("gold_customer", "Gold Customer"),
            ("not_resold", "Other Business"), ("silver", "Silver Partner"), ("silver_customer", "Silver Referral"))}
        ids = dict((await db.execute(select(Company.name, Company.id).where(Company.name.in_(names.values())))).all())
        missing = uuid.UUID(int=0)
        return World(tag=tag, **{k: ids.get(v, missing) for k, v in names.items()},
                     emails={"staff": email("staff", tag)}, names=names, split=split())

    return run(work)


def set_immediate_delete(on: bool) -> None:
    """Switch immediate delete on or off (a local run's own switch; on Azure the owner sets it)."""
    async def work(db: Any) -> None:
        from types import SimpleNamespace

        from src.common.settings_store import set_platform_setting

        actor = SimpleNamespace(id=None, role="app_admin", company_id=None, email="journeys@example.com")
        await set_platform_setting(db, "offboarding.immediate_delete_enabled", on, actor=actor,
                                   reason="browser journeys")
        await db.commit()

    run(work)


def throwaway(tag: str) -> Dict[str, str]:
    """One more test business, made to be deleted by a journey from Company 360 (Delete now)."""
    async def work(db: Any) -> Dict[str, str]:
        from src.auth.platform import platform_company_id

        company = await _company(db, f"Journey Throwaway {tag}", "TENANT", parent=await platform_company_id(db))
        from src.billing.wallet import WalletService
        await WalletService(db).ensure(company.id)
        await db.commit()
        if split():
            await _provision([company.id])
        return {"id": str(company.id), "name": company.name}

    return run(work)


def company_exists(company_id: uuid.UUID) -> bool:
    async def work(db: Any) -> bool:
        from src.auth.models import Company
        return await db.get(Company, uuid.UUID(str(company_id))) is not None

    return run(work)
