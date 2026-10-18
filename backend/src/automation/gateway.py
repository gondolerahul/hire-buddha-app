"""Today's inbound paths onto events and triggers (tech spec §7.6, §7.13;
plan WS3 3.5 and 3.9).

**Ingestion.** A signed webhook or an internal event is stored as an event in
the business's database (``automation.store`` — the outbox; a provider's retry
of the same delivery is the same ``dedupe_key``), then the router is nudged.
The answer to the provider is given only once the event is stored; if the
business's database cannot take it the endpoint answers 503 and the provider
retries. ``settings.AUTOMATION_GATEWAY_EVENTS`` off puts the old direct path
(``process_gateway_event``) back.

**Which agent runs.** Declared triggers, nothing implicit:

* an endpoint bound to an agent has a trigger for it (made with the endpoint,
  and by migration ``p14_webhook_triggers`` for existing endpoints — also for
  an unbound endpoint of a business with one agent, which the old "company's
  only agent" fallback ran);
* an event that names an agent itself (``entity_id`` in the request, as CRM
  integrations do) gets a visible system trigger the first time, so the
  binding the integrator chose shows in the Control Room and can be turned off;
* anything else is routed with no decision and stays visible in the event log.

**Sheet rows.** ``sheet.row_inserted`` still becomes a one-contact voice
campaign for the trigger's agent (``arq_jobs._handle_sheet_row_campaign``),
now through a trigger, with its decision recorded.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
from uuid import UUID

from sqlalchemy import select

from src.automation import events as events_mod
from src.automation import store
from src.automation.models import Event, Trigger

logger = logging.getLogger(__name__)

SHEET_ROW = "sheet.row_inserted"
_UNSAFE = re.compile(r"[^a-z0-9_.]+")


class TenantUnavailable(RuntimeError):
    """The business's database could not take the event (the provider should retry)."""


def enabled() -> bool:
    from src.common.config import settings

    return bool(settings.AUTOMATION_GATEWAY_EVENTS)


def event_type_for(source: str, event_type: str) -> str:
    """An inbound event's v2 type: ``<source>.<type>`` — kept as given when it is
    already in a known namespace (``sheet.row_inserted``, ``custom.order.paid``,
    ``crm.lead.created`` from the CRM source)."""
    def clean(text: str) -> str:
        text = _UNSAFE.sub("_", str(text or "").strip().lower()).strip("._")
        return re.sub(r"\.{2,}", ".", text)

    kind = clean(event_type) or "event"
    base = clean(source).split(".")[0] or "webhook"
    known = {base, "custom"} | {prefix.rstrip(".") for prefix in events_mod.PLATFORM_PREFIXES}
    candidate = kind if kind.split(".")[0] in known and "." in kind else f"{base}.{kind}"
    if not candidate[0].isalpha():
        candidate = f"{base}.{candidate}"
    try:
        return events_mod.validate_type(candidate)
    except events_mod.EventError:
        return f"{base}.event"


def endpoint_subject(endpoint_id: Any) -> str:
    return f"webhook:{endpoint_id}"


async def _data(company_id: Any, envelope: Any, *, endpoint_id: Optional[Any],
                bound: bool) -> Tuple[Dict[str, Any], Optional[str]]:
    """The event's data: the normalised payload's fields, plus where it came from
    under ``_gateway``. A payload too large to keep inline goes to storage.

    ``entity_id`` is an agent the request itself names — not the endpoint's
    binding, which has its own trigger, and ignored when the endpoint is bound
    (as before: the binding came first)."""
    raw = envelope.raw_data if isinstance(envelope.raw_data, dict) else {"items": envelope.raw_data}
    nested = raw.get("raw") if isinstance(raw.get("raw"), dict) else {}
    named = None if bound else (raw.get("entity_id") or nested.get("entity_id"))
    meta = {"channel": envelope.channel, "source": envelope.source, "event_type": envelope.event_type,
            "correlation_id": envelope.id, "endpoint_id": str(endpoint_id) if endpoint_id else None}
    if named:  # absent, not null, when the request names no agent (filters test "exists")
        meta["entity_id"] = str(named)
    body = json.dumps(raw, default=str)
    if len(body) <= events_mod.MAX_INLINE_DATA_BYTES:
        return {**raw, "_gateway": meta}, None
    from src.common.platform.storage import company_namespace, get_storage

    key = f"{company_namespace(company_id)}/events/{datetime.utcnow():%Y-%m-%d}/{uuid.uuid4().hex}.json"
    await get_storage().put(key, body.encode("utf-8"), content_type="application/json")
    return {"_gateway": {**meta, "too_large_bytes": len(body)}}, key


async def ingest(envelope: Any, *, dedupe_key: str, trust: str, endpoint_id: Optional[Any] = None,
                 bound: bool = False) -> Tuple[UUID, bool]:
    """Store the inbound event in the business's database and nudge the router.

    Returns ``(event id, created)``; ``created`` False is a delivery already stored.
    Raises :class:`TenantUnavailable` when the database cannot take it.
    """
    from src.common.tenancy.session import tenant_session

    company_id = UUID(str(envelope.client_id))
    data, data_ref = await _data(company_id, envelope, endpoint_id=endpoint_id, bound=bound)
    v2 = events_mod.Envelope(
        type=event_type_for(envelope.source, envelope.event_type), source=f"{envelope.channel}:{envelope.source}",
        trust=trust, dedupe_key=dedupe_key[:512], data=data, data_ref=data_ref,
        subject=endpoint_subject(endpoint_id) if endpoint_id else None)
    try:
        async with tenant_session(company_id) as db:
            row, created = await store.record(db, company_id, v2)
            await db.commit()
            event_id = row.id
    except Exception as error:
        logger.exception("event %s could not be stored for company %s", dedupe_key, company_id)
        raise TenantUnavailable(str(error)) from error
    if created:
        await store.nudge(company_id, event_id)
    return event_id, created


# ── Triggers for endpoints and named agents ────────────────────────────────

def endpoint_trigger_fields(endpoint: Any, entity_id: Any) -> Dict[str, Any]:
    """The trigger that runs an endpoint's bound agent for each of its events."""
    return {
        "name": f"Webhook: {endpoint.name}"[:200], "kind": "event", "entity_id": entity_id,
        # Every type the endpoint delivers (a generic endpoint carries its own,
        # like sheet.row_inserted); the subject names the endpoint.
        "event_type": "*",
        "filter": {"path": "subject", "op": "eq", "value": endpoint_subject(endpoint.id)},
        "scope": "webhooks",
    }


async def add_endpoint_trigger(db: Any, control_db: Any, endpoint: Any, user_id: Any = None) -> Optional[Trigger]:
    """Make the trigger of a newly bound endpoint (no commit)."""
    from src.automation import triggers

    if not endpoint.entity_id:
        return None
    trigger = await triggers.create(db, control_db, endpoint.company_id,
                                    endpoint_trigger_fields(endpoint, endpoint.entity_id),
                                    triggers.Actor("system", user_id))
    return trigger


async def remove_endpoint_triggers(db: Any, control_db: Any, company_id: Any, endpoint_id: Any) -> int:
    """Turn off the triggers of a deleted endpoint (their history stays)."""
    from src.automation import triggers

    subject = endpoint_subject(endpoint_id)
    rows = (await db.execute(select(Trigger).where(
        Trigger.company_id == company_id, Trigger.created_by_kind == "system",
        Trigger.enabled.is_(True)))).scalars().all()
    changed = 0
    for trigger in rows:
        if (trigger.filter or {}).get("value") == subject:
            await triggers.update(db, control_db, company_id, trigger, {"enabled": False})
            trigger.paused_reason = "its webhook endpoint was deleted"
            changed += 1
    return changed


async def ensure_named_trigger(db: Any, company_id: Any, event: Event) -> Optional[Trigger]:
    """An inbound event that names an agent (``entity_id``) gets a system trigger for
    that agent and source the first time — the old "named agent" rule, made visible."""
    from src.automation import triggers
    from src.gateway.agent_choice import choose_agent

    meta = (event.data or {}).get("_gateway") or {}
    named = meta.get("entity_id")
    if not named or not event.source.split(":", 1)[0] in ("webhook", "internal"):
        return None
    choice = await choose_agent(db, company_id, [named])
    if choice.entity is None:
        return None
    entity_id = str(choice.entity.id)
    prefix = event.type.split(".")[0]
    rule = {"path": "data._gateway.entity_id", "op": "eq", "value": entity_id}
    for trigger in (await db.execute(select(Trigger).where(
            Trigger.company_id == company_id, Trigger.created_by_kind == "system",
            Trigger.entity_id == choice.entity.id, Trigger.event_type == f"{prefix}.*"))).scalars().all():
        if trigger.filter == rule:
            return None  # already made (on or off: the owner decides)
    from src.common.tenancy.session import control_session, is_split

    control = control_session() if is_split() else None
    try:
        trigger = await triggers.create(db, control or db, company_id, {
            "name": f"{prefix} events naming {choice.entity.name}"[:200], "kind": "event",
            "entity_id": choice.entity.id, "event_type": f"{prefix}.*", "filter": rule, "scope": "webhooks",
        }, triggers.Actor("system"))
        # It answers this event too: the request that named the agent made it.
        trigger.created_at = min(event.time, datetime.utcnow()) if event.time else trigger.created_at
        await db.commit()
        if control is not None:
            await control.commit()
    finally:
        if control is not None:
            await control.close()
    return trigger


def subjects_for(event: Event) -> Optional[Dict[str, Any]]:
    """The run's subjects for an inbound event (its lead, its sender) — set by the
    platform, never by a template (TL-09)."""
    meta = (event.data or {}).get("_gateway")
    if not meta:
        return None
    from src.ai.governance.subjects import gateway_subjects

    payload = {k: v for k, v in (event.data or {}).items() if k != "_gateway"}
    return gateway_subjects(str(meta.get("source") or ""), payload)


def default_input(event: Event) -> Dict[str, Any]:
    """A trigger with no input template gets the event itself, as the old path gave runs."""
    meta = (event.data or {}).get("_gateway") or {}
    payload = {k: v for k, v in (event.data or {}).items() if k != "_gateway"}
    out: Dict[str, Any] = {"input": json.dumps(payload, default=str), "event_type": event.type}
    if meta:
        out.update({"channel": meta.get("channel"), "source": meta.get("source"),
                    "correlation_id": meta.get("correlation_id")})
    return out


async def sheet_campaign(db: Any, company_id: Any, entity_id: Any, event: Event) -> Optional[str]:
    """A sheet row → a one-contact voice campaign for the trigger's agent; returns its id."""
    from src.ai.core.arq_jobs import _handle_sheet_row_campaign
    from src.ai.orm import HierarchicalEntity
    from src.common.tenancy.session import tenant_session

    payload = {k: v for k, v in (event.data or {}).items() if k != "_gateway"}
    meta = (event.data or {}).get("_gateway") or {}
    async with tenant_session(company_id) as campaign_db:  # it commits as it goes
        entity = await campaign_db.get(HierarchicalEntity, entity_id)
        campaign_id = await _handle_sheet_row_campaign(
            db=campaign_db, entity=entity, client_id=str(company_id), raw_data=payload,
            correlation_id=str(meta.get("correlation_id") or event.id), redis_pool=None)
    return str(campaign_id) if campaign_id else None
