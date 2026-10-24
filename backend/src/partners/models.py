"""The partner programme's tables (Phase 15 T8-2…T8-10, tech design §11.2). All control plane.

``companies.parent_id`` keeps the tree (TENANT → owning partner or APP,
PARTNER → recruiting partner or APP); ``partner_assignments`` is the source of
truth for which partner a tenant is attributed to, over time.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CHAR, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text,
    UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.common.tenancy.bases import ControlBase

SILVER, GOLD = "SILVER", "GOLD"
PROFILE_STATUSES = ("approved", "active", "renewal_due", "lapsed", "suspended", "terminated")
EARNING_STATUSES = ("active", "renewal_due")          # earn and are paid (§11.3)
REVENUE_KINDS = ("usage_topup", "subscription", "setup_fee", "customisation_fee")
FEE_KINDS = ("setup", "customisation")
LEDGER_KINDS = ("commission", "override", "fee_share", "clawback", "adjustment", "payout", "tds")
LEDGER_STATUSES = ("accrued", "held", "payable", "paid", "reversed")
GRANT_SCOPES = ("read", "support", "admin", "billing")


def _id() -> Column:
    return Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))


def _now() -> Column:
    return Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, server_default=text("now()"))


def _in(column: str, values: tuple) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class PartnerType(ControlBase):
    """Silver (referral) and Gold (resell and deliver), §11.1."""
    __tablename__ = "partner_types"

    code = Column(String(10), primary_key=True)
    name = Column(Text, nullable=False)
    can_create_tenants = Column(Boolean, nullable=False)
    tenant_data_access = Column(String(10), nullable=False)          # none | grants
    annual_fee_item = Column(Text, ForeignKey("price_items.code"), nullable=True)
    active = Column(Boolean, nullable=False, default=True, server_default=text("true"))


class PartnerProfile(ControlBase):
    """A partner company in the programme (one per PARTNER company)."""
    __tablename__ = "partner_profiles"
    __table_args__ = (CheckConstraint(_in("status", PROFILE_STATUSES), name="ck_partner_profiles_status"),
                      CheckConstraint("depth BETWEEN 1 AND 10", name="ck_partner_profiles_depth"))

    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), primary_key=True)
    partner_type = Column(String(10), ForeignKey("partner_types.code"), nullable=False)
    status = Column(String(20), nullable=False, default="approved", server_default="approved")
    legal_name = Column(Text, nullable=True)
    country_code = Column(CHAR(2), nullable=True)
    billing_currency = Column(CHAR(3), nullable=True)
    pan = Column(String(10), nullable=True)
    gstin = Column(String(15), nullable=True)
    kyc_status = Column(String(10), nullable=False, default="pending", server_default="pending")  # pending|verified|rejected
    # Bank details: AES-GCM encrypted (``encrypt_api_key``); only the last four digits are shown.
    bank_encrypted = Column(Text, nullable=True)
    bank_last4 = Column(String(4), nullable=True)
    bank_verified = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    agreement_id = Column(UUID(as_uuid=True), nullable=True)
    recruiter_partner_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True, index=True)
    depth = Column(Integer, nullable=False, default=1, server_default="1")     # 1 = recruited by BCL
    activated_at = Column(DateTime(timezone=True), nullable=True)
    fee_paid_until = Column(DateTime(timezone=True), nullable=True)
    probation_until = Column(DateTime(timezone=True), nullable=True)
    status_reason = Column(Text, nullable=True)
    created_at = _now()
    updated_at = _now()


class PartnerAgreement(ControlBase):
    """An agreement version: the rates in force when it was made, snapshotted (§11.3)."""
    __tablename__ = "partner_agreements"
    __table_args__ = (UniqueConstraint("partner_id", "version", name="uq_partner_agreements_version"),)

    id = _id()
    partner_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    version = Column(Integer, nullable=False)
    terms = Column(JSONB, nullable=False)
    effective_from = Column(DateTime(timezone=True), nullable=False)
    effective_to = Column(DateTime(timezone=True), nullable=True)
    signed_at = Column(DateTime(timezone=True), nullable=True)
    signed_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = _now()


class PartnerAssignment(ControlBase):
    """Which partner a tenant is attributed to, from ``since`` until ``until`` (open: current)."""
    __tablename__ = "partner_assignments"
    __table_args__ = (
        CheckConstraint("relationship IN ('referred', 'resold')", name="ck_partner_assignments_relationship"),
        CheckConstraint("source IN ('lead', 'created', 'link', 'staff')", name="ck_partner_assignments_source"),
        Index("uq_partner_assignments_current", "tenant_id", unique=True, postgresql_where=text("until IS NULL")),
        Index("ix_partner_assignments_partner", "partner_id"),
    )

    id = _id()
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    partner_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    relationship = Column(String(10), nullable=False)
    since = Column(DateTime(timezone=True), nullable=False)
    until = Column(DateTime(timezone=True), nullable=True)
    commission_until = Column(DateTime(timezone=True), nullable=True)    # NULL: no end (O-8)
    source = Column(String(10), nullable=False)
    reason = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = _now()


class PartnerLead(ControlBase):
    """A customer a partner registered (T8-9): exclusive to it until ``exclusive_until``."""
    __tablename__ = "partner_leads"
    __table_args__ = (
        CheckConstraint(_in("status", ("registered", "accepted", "in_progress", "converted", "lost", "expired")),
                        name="ck_partner_leads_status"),
        Index("ix_partner_leads_domain", "email_domain"),
    )

    id = _id()
    partner_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    company_name = Column(Text, nullable=False)
    contact_name = Column(Text, nullable=True)
    email = Column(Text, nullable=True)
    email_domain = Column(Text, nullable=True)
    phone = Column(Text, nullable=True)
    country_code = Column(CHAR(2), nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(String(12), nullable=False, default="registered", server_default="registered")
    bcl_owner_id = Column(UUID(as_uuid=True), nullable=True)
    exclusive_until = Column(DateTime(timezone=True), nullable=True)
    converted_company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True)
    lost_reason = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = _now()
    updated_at = _now()


class PartnerApplication(ControlBase):
    """Someone applying to be a partner, through BCL or a recruiter's invite (T8-5)."""
    __tablename__ = "partner_applications"
    __table_args__ = (
        CheckConstraint(_in("status", ("invited", "applied", "under_review", "approved", "rejected")),
                        name="ck_partner_applications_status"),
    )

    id = _id()
    recruiter_partner_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True)
    invite_token = Column(String(64), nullable=True, unique=True)
    status = Column(String(14), nullable=False, default="applied", server_default="applied")
    requested_type = Column(String(10), nullable=True)
    approved_type = Column(String(10), nullable=True)
    company_name = Column(Text, nullable=True)
    contact_name = Column(Text, nullable=True)
    email = Column(Text, nullable=True)
    phone = Column(Text, nullable=True)
    country_code = Column(CHAR(2), nullable=True)
    details = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    checklist = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    reviewed_by = Column(UUID(as_uuid=True), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    review_notes = Column(Text, nullable=True)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True)
    created_at = _now()
    updated_at = _now()


class CommissionRule(ControlBase):
    """A rate per partner type × revenue kind × level; edits are new versions (§11.6)."""
    __tablename__ = "commission_rules"
    __table_args__ = (
        UniqueConstraint("partner_type", "revenue_kind", "level", "version", name="uq_commission_rules_version"),
        CheckConstraint("level BETWEEN 0 AND 2", name="ck_commission_rules_level"),
        CheckConstraint("rate_pct >= 0 AND rate_pct <= 100 AND (cap_pct IS NULL OR cap_pct <= 100)",
                        name="ck_commission_rules_pct"),
    )

    id = _id()
    partner_type = Column(String(10), ForeignKey("partner_types.code"), nullable=False)
    revenue_kind = Column(String(20), nullable=False)
    level = Column(Integer, nullable=False)
    rate_pct = Column(Numeric(10, 4), nullable=False)
    cap_pct = Column(Numeric(10, 4), nullable=True)        # the pool cap; level 0's applies to the event
    months = Column(Integer, nullable=True)                 # NULL: no end
    active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    version = Column(Integer, nullable=False, default=1, server_default="1")
    reason = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = _now()


class FeeRule(ControlBase):
    """The range and split of a setup or customisation fee per partner type (§11.5)."""
    __tablename__ = "fee_rules"
    __table_args__ = (UniqueConstraint("partner_type", "fee_kind", "version", name="uq_fee_rules_version"),)

    id = _id()
    partner_type = Column(String(10), ForeignKey("partner_types.code"), nullable=False)
    fee_kind = Column(String(14), nullable=False)
    min_usd = Column(Numeric(24, 10), nullable=False)
    max_usd = Column(Numeric(24, 10), nullable=False)
    split = Column(JSONB, nullable=False)          # {"originator": 75, "level1": 3, "level2": 2, "platform": 20}
    active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    version = Column(Integer, nullable=False, default=1, server_default="1")
    reason = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = _now()


class OneTimeCharge(ControlBase):
    """A setup or customisation fee raised for a tenant, paid directly (not from the wallet) (T8-8)."""
    __tablename__ = "one_time_charges"
    __table_args__ = (
        CheckConstraint(_in("status", ("draft", "sent", "paid", "cancelled", "refunded")),
                        name="ck_one_time_charges_status"),
    )

    id = _id()
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    partner_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True)
    fee_kind = Column(String(14), nullable=False)
    description = Column(Text, nullable=True)
    amount = Column(Numeric(24, 10), nullable=False)               # net, in the tenant's currency
    currency = Column(CHAR(3), nullable=False)
    amount_usd = Column(Numeric(24, 10), nullable=False)
    status = Column(String(10), nullable=False, default="sent", server_default="sent")
    payment_id = Column(UUID(as_uuid=True), ForeignKey("payment_transactions.id"), nullable=True)
    invoice_id = Column(UUID(as_uuid=True), nullable=True)
    rule_version = Column(Integer, nullable=True)
    raised_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = _now()
    paid_at = Column(DateTime(timezone=True), nullable=True)


class PartnerLedgerEntry(ControlBase):
    """What a partner earned, lost or was paid, in its currency (§11.6, §11.7). Append-only but for status."""
    __tablename__ = "partner_ledger"
    __table_args__ = (
        CheckConstraint(_in("kind", LEDGER_KINDS), name="ck_partner_ledger_kind"),
        CheckConstraint(_in("status", LEDGER_STATUSES), name="ck_partner_ledger_status"),
        Index("uq_partner_ledger_event", "source_type", "source_id", "partner_id", "level", "kind", unique=True,
              postgresql_where=text("kind IN ('commission', 'override', 'fee_share', 'clawback')")),
        Index("ix_partner_ledger_partner_status", "partner_id", "status"),
    )

    id = _id()
    partner_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    kind = Column(String(12), nullable=False)
    amount = Column(Numeric(24, 10), nullable=False)               # partner currency; negative takes away
    currency = Column(CHAR(3), nullable=False)
    fx_rate_id = Column(UUID(as_uuid=True), nullable=True)
    amount_usd = Column(Numeric(24, 10), nullable=True)            # for the margin guard and reports
    revenue_kind = Column(String(20), nullable=True)
    base_amount = Column(Numeric(24, 10), nullable=True)           # the revenue, in the tenant's currency
    base_currency = Column(CHAR(3), nullable=True)
    base_usd = Column(Numeric(24, 10), nullable=True)
    rate_pct = Column(Numeric(10, 4), nullable=True)
    source_type = Column(String(20), nullable=True)                # payment | charge | refund | statement | staff
    source_id = Column(String(80), nullable=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=True)
    origin_partner_id = Column(UUID(as_uuid=True), nullable=True)   # the level-0 partner (overrides by sub-partner)
    level = Column(Integer, nullable=False, default=0, server_default="0")
    status = Column(String(10), nullable=False, default="accrued", server_default="accrued")
    hold_reason = Column(String(20), nullable=True)                # lapsed | kyc | margin_guard
    payable_after = Column(DateTime(timezone=True), nullable=True)
    statement_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    reason = Column(Text, nullable=True)
    created_at = _now()
    updated_at = _now()


class PartnerStatement(ControlBase):
    """A month's payable entries for one partner in one currency (T8-10)."""
    __tablename__ = "partner_statements"
    __table_args__ = (
        UniqueConstraint("partner_id", "period", "currency", name="uq_partner_statements_period"),
        CheckConstraint(_in("status", ("draft", "approved", "paid", "disputed")), name="ck_partner_statements_status"),
    )

    id = _id()
    partner_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    period = Column(Date, nullable=False)                           # the month's first day
    currency = Column(CHAR(3), nullable=False)
    gross = Column(Numeric(24, 10), nullable=False)
    tds = Column(Numeric(24, 10), nullable=False)
    net = Column(Numeric(24, 10), nullable=False)
    tds_pct = Column(Numeric(10, 4), nullable=False)
    status = Column(String(10), nullable=False, default="draft", server_default="draft")
    document_ref = Column(Text, nullable=True)
    gst_invoice_ref = Column(Text, nullable=True)
    dispute_reason = Column(Text, nullable=True)
    approved_by = Column(UUID(as_uuid=True), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    payout_ref = Column(Text, nullable=True)
    created_at = _now()


class PartnerAccessGrant(ControlBase):
    """A Gold partner's access to a tenant's data: scopes, until it expires or is revoked (T8-4, §11.9)."""
    __tablename__ = "partner_access_grants"
    __table_args__ = (
        CheckConstraint(_in("status", ("requested", "active", "revoked")), name="ck_partner_access_grants_status"),
        Index("ix_partner_access_grants_pair", "partner_id", "tenant_id"),
    )

    id = _id()
    partner_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    scopes = Column(JSONB, nullable=False)
    status = Column(String(10), nullable=False, default="active", server_default="active")
    reason = Column(Text, nullable=True)
    requested_by = Column(UUID(as_uuid=True), nullable=True)
    granted_by = Column(UUID(as_uuid=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = _now()


class PartnerAccessEvent(ControlBase):
    """One request a partner made inside a tenant, under a grant (audit, §11.9)."""
    __tablename__ = "partner_access_events"
    __table_args__ = (Index("ix_partner_access_events_tenant", "tenant_id", "at"),)

    id = _id()
    grant_id = Column(UUID(as_uuid=True), nullable=True)
    partner_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    method = Column(String(8), nullable=False)
    path = Column(Text, nullable=False)
    at = _now()
