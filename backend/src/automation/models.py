"""Automation tables (Phase 14 WS3 3.2, tech spec §7.3–§7.4; decision D47).

Tenant plane (each business's own database, schema ``platform``):

* ``events``          — every accepted event once (``dedupe_key`` unique); the outbox
* ``triggers``        — rules: when → run which agent with what input → under which rules
* ``trigger_firings`` — one decision per trigger per event, with its reason
* ``waits``           — runs paused until an event or a deadline

Control plane:

* ``time_index``           — the next due moment of each tenant object, so the
  scheduler does not scan every tenant database (a cache of the tenant rows)
* ``automation_settings``  — per business (and one platform row): the limits
  of D47, none by default, and whether automation is running or paused
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.common.tenancy.bases import ControlBase, TenantBase

EVENT_STATUSES = ("received", "routed", "parked", "dead")
TRUST_LEVELS = ("verified", "unverified", "internal")
TRIGGER_KINDS = ("schedule", "timer", "event", "data", "condition", "manual")
CATCH_UP_POLICIES = ("skip", "once", "all")
OVERLAP_POLICIES = ("skip", "queue", "allow")
CREATED_BY_KINDS = ("user", "agent", "system")
FIRING_OUTCOMES = ("started", "queued", "skipped_overlap", "skipped_rate", "skipped_chain_depth",
                   "skipped_condition_false", "skipped_missed", "blocked_budget", "blocked_paused", "blocked_policy",
                   "failed")
WAIT_STATUSES = ("waiting", "satisfied", "expired", "cancelled")
TIME_INDEX_KINDS = ("trigger", "wait", "connection_refresh", "scratch_cleanup")
AUTOMATION_STATES = ("running", "paused")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _now() -> Any:
    return text("now()")


class Event(TenantBase):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(_in("status", EVENT_STATUSES), name="ck_events_status"),
        CheckConstraint(_in("trust", TRUST_LEVELS), name="ck_events_trust"),
        # One event per business per dedupe key: a provider's retry, a double tick.
        UniqueConstraint("company_id", "dedupe_key", name="uq_events_company_dedupe"),
        # What the router and the relay sweep look for; the event log's type filter.
        Index("ix_events_pending", "status", "received_at", postgresql_where=text("status IN ('received', 'parked')")),
        Index("ix_events_type_time", "type", "time"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)  # UUIDv7
    # The business, as on every tenant row (§5.3 rule 5): in single mode one
    # table holds every business's events, and a sweep must know whose each is.
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now(),
                                                  default=datetime.utcnow)
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False)
    trust: Mapped[str] = mapped_column(Text, nullable=False)
    causation_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    correlation_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    chain_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Operational envelope payload, not a business record (D09, D11).
    data: Mapped[Any] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    data_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="received", server_default="received")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    routed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Trigger(TenantBase):
    __tablename__ = "triggers"
    __table_args__ = (
        CheckConstraint(_in("kind", TRIGGER_KINDS), name="ck_triggers_kind"),
        CheckConstraint(f"catch_up IS NULL OR {_in('catch_up', CATCH_UP_POLICIES)}", name="ck_triggers_catch_up"),
        CheckConstraint(f"overlap IS NULL OR {_in('overlap', OVERLAP_POLICIES)}", name="ck_triggers_overlap"),
        CheckConstraint(_in("created_by_kind", CREATED_BY_KINDS), name="ck_triggers_created_by_kind"),
        Index("ix_triggers_event_type", "event_type", postgresql_where=text("enabled")),
        Index("ix_triggers_entity_id", "entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # The business, as a plain UUID (no key crosses the planes; tech spec §5.3
    # rule 5: company filters stay in tenant queries as defence in depth).
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                                 ForeignKey("hierarchical_entities.id", ondelete="CASCADE"),
                                                 nullable=False)
    entity_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    input_template: Mapped[Any] = mapped_column(JSONB, nullable=False, default=dict,
                                                server_default=text("'{}'::jsonb"))
    event_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    filter: Mapped[Any] = mapped_column(JSONB, nullable=True)
    cron: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timezone: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    until_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    max_firings: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # The trigger's own rules; NULL = the business's automation settings (D47).
    catch_up: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    overlap: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    max_concurrency: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rate_per_hour: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # A condition trigger's check (a report query, no LLM; WS4 4.10).
    condition: Mapped[Any] = mapped_column(JSONB, nullable=True)
    scope: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # department / process label
    created_by_kind: Mapped[str] = mapped_column(Text, nullable=False, default="user")
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    next_fire_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_fired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    firings: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    paused_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now(),
                                                 default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now(),
                                                 default=datetime.utcnow, onupdate=datetime.utcnow)


class TriggerFiring(TenantBase):
    __tablename__ = "trigger_firings"
    __table_args__ = (
        CheckConstraint(_in("outcome", FIRING_OUTCOMES), name="ck_trigger_firings_outcome"),
        # One decision per trigger per event (§7.3): a replayed event cannot fire twice.
        UniqueConstraint("trigger_id", "event_id", name="uq_trigger_firings_trigger_event"),
        Index("ix_trigger_firings_trigger_decided", "trigger_id", "decided_at"),
        Index("ix_trigger_firings_event", "event_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trigger_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("triggers.id", ondelete="CASCADE"),
                                                  nullable=False)
    event_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("events.id"), nullable=True)
    run_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now(),
                                                 default=datetime.utcnow)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Wait(TenantBase):
    __tablename__ = "waits"
    __table_args__ = (
        CheckConstraint(_in("status", WAIT_STATUSES), name="ck_waits_status"),
        Index("ix_waits_waiting_type", "event_type", postgresql_where=text("status = 'waiting'")),
        Index("ix_waits_run", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    step_ref: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    match: Mapped[Any] = mapped_column(JSONB, nullable=True)
    deadline_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="waiting", server_default="waiting")
    satisfied_by_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now(),
                                                 default=datetime.utcnow)


class TimeIndexEntry(ControlBase):
    __tablename__ = "time_index"
    __table_args__ = (
        CheckConstraint(_in("ref_kind", TIME_INDEX_KINDS), name="ck_time_index_ref_kind"),
        Index("ix_time_index_due_at", "due_at"),
    )

    # The tenant's company in single mode too, so one index serves both (WS2 directory keys by company).
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    ref_kind: Mapped[str] = mapped_column(Text, primary_key=True)
    ref_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lease_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AutomationLimitsRow(ControlBase):
    """One business's automation settings (``company_id`` NULL: the platform defaults)."""

    __tablename__ = "automation_settings"
    __table_args__ = (
        CheckConstraint(_in("automation_state", AUTOMATION_STATES), name="ck_automation_settings_state"),
        Index("uq_automation_settings_company", "company_id", unique=True,
              postgresql_where=text("company_id IS NOT NULL")),
        Index("uq_automation_settings_platform", text("(company_id IS NULL)"), unique=True,
              postgresql_where=text("company_id IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"),
                                                            nullable=True)
    # src/automation/limits.py: absent = inherit, null = no limit (D47).
    limits: Mapped[Any] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    automation_state: Mapped[str] = mapped_column(Text, nullable=False, default="running", server_default="running")
    paused_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now(),
                                                 default=datetime.utcnow)
