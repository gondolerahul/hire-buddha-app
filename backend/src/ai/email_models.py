"""
SQLAlchemy model for email connections (IMAP/SMTP).

Stores encrypted credentials for AI agent email integration.
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Text, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from src.common.tenancy.bases import TenantBase, refers_to


class EmailConnection(TenantBase):
    """
    Email connection configuration for AI agent IMAP/SMTP integration.
    
    Each company can have multiple email accounts connected for
    AI-driven email monitoring, classification, drafting, and sending.
    """
    __tablename__ = "email_connections"
    __table_args__ = (
        UniqueConstraint("company_id", "email_address", name="uq_email_connection_company_email"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, info=refers_to("companies.id"))
    email_address = Column(String, nullable=False)
    encrypted_app_password = Column(Text, nullable=False)
    imap_host = Column(String, nullable=False, default="imap.gmail.com")
    imap_port = Column(Integer, nullable=False, default=993)
    smtp_host = Column(String, nullable=False, default="smtp.gmail.com")
    smtp_port = Column(Integer, nullable=False, default=587)
    provider_type = Column(String, nullable=False, default="gmail")  # gmail, outlook, custom
    folder_prefix = Column(String, nullable=True)  # e.g., "[Gmail]/" for Gmail
    is_active = Column(Boolean, nullable=False, default=True)
    last_connected_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, nullable=False, default="active")  # active, auth_failed, disconnected
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
