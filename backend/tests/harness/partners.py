"""Partner-programme fixtures for integration tests (Phase 15 WS15-8): partners, tenants, staff users.

``partner(db, "GOLD", recruiter=…)`` makes a PARTNER company with an active,
KYC-verified profile (bank on file) in the given currency; ``tenant(db,
partner, relationship)`` a TENANT attributed to it. The caller's transaction
rolls them back.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, Optional


async def partner(db: Any, partner_type: str = "GOLD", *, recruiter: Optional[Any] = None, currency: str = "INR",
                  status: str = "active", kyc: str = "verified", activated_days_ago: int = 400) -> Any:
    from src.auth.models import Company
    from src.common.security import encrypt_api_key
    from src.partners.lifecycle import create_profile

    company = Company(name=f"partner-{uuid.uuid4().hex[:6]}", type="PARTNER", status="active",
                      parent_id=recruiter, billing_currency=currency, country_code="IN" if currency == "INR" else "US")
    db.add(company)
    await db.flush()
    profile = await create_profile(db, company, partner_type=partner_type, status="approved", recruiter_id=recruiter)
    profile.status, profile.kyc_status = status, kyc
    profile.activated_at = datetime.utcnow() - timedelta(days=activated_days_ago)
    profile.probation_until = None
    profile.bank_encrypted = encrypt_api_key(json.dumps({"account_name": "P", "account_number": "1234567890",
                                                         "ifsc": "HDFC0001234"}))
    profile.bank_last4, profile.bank_verified = "7890", True
    await db.flush()
    return company.id


async def tenant(db: Any, partner_id: Optional[Any] = None, relationship: str = "resold", *, currency: str = "INR",
                 since_days_ago: int = 1) -> Any:
    from src.auth.models import Company
    from src.partners.scope import assign

    company = Company(name=f"tenant-{uuid.uuid4().hex[:6]}", type="TENANT", status="active",
                      parent_id=partner_id if relationship == "resold" else None, billing_currency=currency,
                      country_code="IN" if currency == "INR" else "US", billing_state="KA")
    db.add(company)
    await db.flush()
    if partner_id is not None:
        await assign(db, tenant_id=company.id, partner_id=partner_id, relationship=relationship, source="created",
                     since=datetime.utcnow() - timedelta(days=since_days_ago))
    return company.id


async def own_revenue(db: Any, partner_id: Any, usd: str = "1000") -> None:
    """Give a partner paid revenue of its own this month (uplines need it to earn overrides)."""
    from decimal import Decimal

    from src.partners.models import PartnerLedgerEntry

    db.add(PartnerLedgerEntry(partner_id=partner_id, kind="commission", amount=Decimal(0), currency="INR",
                              base_usd=Decimal(usd), level=0, status="accrued", source_type="test",
                              source_id=uuid.uuid4().hex, revenue_kind="usage_topup", amount_usd=Decimal(0)))
    await db.flush()


def user(role: str, company_id: Any) -> Any:
    from src.auth.roles import Role

    return SimpleNamespace(id=uuid.uuid4(), role=Role(role), company_id=company_id, email=f"{role}@example.com")
