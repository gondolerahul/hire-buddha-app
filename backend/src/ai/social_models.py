"""
SQLAlchemy model for social media connections (OAuth 2.0).

Stores encrypted OAuth tokens for AI agent social media integrations.
Each company can connect multiple social media accounts across platforms.
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Text, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from src.common.database import Base


class SocialConnection(Base):
    """
    Social media connection configuration for AI agent integrations.

    Each company can have multiple social accounts connected for
    AI-driven content publishing, analytics, comment management, etc.

    Supported platforms: linkedin, twitter, facebook, instagram, google_ads,
    youtube, tiktok, reddit, quora (future phases).
    """
    __tablename__ = "social_connections"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "platform", "platform_user_id",
            name="uq_social_connection_company_platform_user",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    platform = Column(String(50), nullable=False)  # linkedin, twitter, facebook, instagram, google_ads
    account_name = Column(String(255), nullable=True)  # human-readable label

    # OAuth tokens (encrypted via common/security.py AES-256-GCM)
    encrypted_access_token = Column(Text, nullable=False)
    encrypted_refresh_token = Column(Text, nullable=True)  # some platforms don't issue refresh tokens
    token_expires_at = Column(DateTime, nullable=True)  # NULL = never expires

    # Platform identifiers
    platform_user_id = Column(String(255), nullable=True)  # e.g. LinkedIn URN, Twitter user ID
    platform_page_id = Column(String(255), nullable=True)  # page/org ID for Page-level tokens

    # OAuth metadata
    scopes = Column(JSON, nullable=True, default=list)  # granted OAuth scopes
    oauth_metadata = Column(JSON, nullable=True)  # extra platform-specific data (e.g. ad_account_id)

    # Status
    is_active = Column(Boolean, nullable=False, default=True)
    status = Column(String(50), nullable=False, default="active")  # active, token_expired, revoked, error
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship("Company")
