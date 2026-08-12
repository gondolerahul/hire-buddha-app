"""
Unified Phone Number model — single source of truth for phone number inventory,
tenant claiming, and agent assignment.

Lifecycle:  available → claimed → assigned → retired

  - available:  synced from provider or added manually; no owner
  - claimed:    tenant owns it, no agent assigned yet
  - assigned:   tenant owns it + agent configured — calls will route
  - retired:    decommissioned
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, ForeignKey, DateTime, Numeric, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from src.common.database import Base


class PhoneNumber(Base):
    """
    Unified phone number table replacing both `phone_number_pool`
    and `customer_phone_numbers`.
    """
    __tablename__ = "phone_numbers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone_number = Column(String(20), unique=True, nullable=False)
    provider = Column(String(20), nullable=False)  # 'twilio' | 'tata_tele'
    country_code = Column(String(5), nullable=False, default="+91")

    # Lifecycle status: available | claimed | assigned | retired
    status = Column(String(20), nullable=False, default="available")

    # Ownership (set when claimed)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True)
    claimed_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    claimed_at = Column(DateTime, nullable=True)

    # Agent assignment (set when assigned)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("hierarchical_entities.id"), nullable=True)
    customer_id = Column(UUID(as_uuid=True), nullable=True)
    customer_name = Column(String(255), nullable=True)
    customer_metadata = Column(JSONB, nullable=True)
    assigned_at = Column(DateTime, nullable=True)

    # Inventory metadata (from provider sync)
    provider_sid = Column(String(100), nullable=True)
    capabilities = Column(JSONB, nullable=True)  # {"voice": true, "sms": false}
    monthly_cost_usd = Column(Numeric(10, 4), nullable=True)
    label = Column(String(100), nullable=True)
    notes = Column(String(500), nullable=True)

    # Admin tracking
    added_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    company = relationship("Company", foreign_keys=[company_id])
    agent = relationship("HierarchicalEntity", foreign_keys=[agent_id])
    added_by_user = relationship("User", foreign_keys=[added_by_user_id])

    __table_args__ = (
        Index('idx_phone_numbers_phone', 'phone_number'),
        Index('idx_phone_numbers_status', 'status'),
        Index('idx_phone_numbers_company', 'company_id'),
        Index('idx_phone_numbers_agent', 'agent_id'),
        Index('idx_phone_numbers_customer', 'customer_id'),
        Index('idx_phone_numbers_provider', 'provider'),
    )

