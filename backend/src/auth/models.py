import uuid
from datetime import datetime
from sqlalchemy import CHAR, CheckConstraint, Column, Index, text, String, Boolean, ForeignKey, DateTime, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from src.common.tenancy.bases import ControlBase

class Company(ControlBase):
    __tablename__ = "companies"
    # At most one APP (platform) company; see src/auth/platform.py (LP-21).
    __table_args__ = (
        Index("uq_companies_one_app", "type", unique=True, postgresql_where=text("type = 'APP'")),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)  # APP, PARTNER, TENANT
    parent_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True)
    logo_url = Column(String, nullable=True)
    status = Column(String, default="active")  # active, suspended
    onboarding_status = Column(String, default="pending")  # pending, in_progress, completed
    onboarding_metadata = Column(JSONB, nullable=True)  # tracks completed steps & config
    default_daily_credits = Column(Numeric(10, 4), nullable=True)  # override daily credit amount for this tenant (was text, DM-11)
    # What the company may be billed in a calendar month; NULL = no cap (GH-18).
    monthly_spend_cap_usd = Column(Numeric(24, 10), nullable=True)
    # The business's IANA time zone: schedules, reports, an agent's "today"
    # (Phase 14 WS1 1.10; src/common/timezones.py). With TENANCY_MODE=split the tenant
    # directory's copy is read (WS2); a change is written to both.
    timezone = Column(String(64), nullable=False, default="Asia/Kolkata", server_default="Asia/Kolkata")
    # Geography and billing profile (Phase 15 T2-2, tech design §3.1). The
    # billing currency follows the country when the company is made (FX-1,
    # src/auth/geography.py) and does not change by itself afterwards.
    country_code = Column(CHAR(2), ForeignKey("country_profiles.country_code"), nullable=False,
                          default="IN", server_default="IN")
    billing_currency = Column(CHAR(3), ForeignKey("currencies.code"), nullable=False,
                              default="INR", server_default="INR")
    billing_state = Column(String(2), nullable=True)      # Indian state (GST place of supply)
    gstin = Column(Text, nullable=True)
    legal_name = Column(Text, nullable=True)
    billing_address = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    parent = relationship("Company", remote_side=[id], backref="children")
    users = relationship("User", back_populates="company")

class User(ControlBase):
    __tablename__ = "users"
    # One account per address whatever its case (AU-26); inputs are lower-cased.
    __table_args__ = (CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    role = Column(String, default="tenant_user")  # app_admin, partner_admin, tenant_admin, app_user, partner_user, tenant_user
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    profile_picture_url = Column(String, nullable=True)
    # Carried in every access token as ``tv``; bumping it ends every session the
    # user has — access tokens at their next request, refresh tokens at once (AU-I3).
    token_version = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship("Company", back_populates="users")
    refresh_tokens = relationship("RefreshToken", back_populates="user")

class RefreshToken(ControlBase):
    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    # SHA-256 (hex) of the token; the token itself is never stored (AU-10).
    token_hash = Column(String(64), unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    user = relationship("User", back_populates="refresh_tokens")
