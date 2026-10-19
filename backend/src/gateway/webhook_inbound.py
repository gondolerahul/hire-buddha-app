"""
Interface 2: Unified Webhook Endpoint.

A tenant's providers post to ``POST /webhook/inbound/{endpoint_id}``. The
endpoint (``gateway.models.WebhookEndpoint``) names the company, the source and
the secret, so:
  1. the request is checked with that source's signature scheme
     (``gateway.webhook_signatures``) — a missing or wrong signature is a 401 and
     nothing is queued (GW-01);
  1a. a signed delivery over the endpoint's allowance (``WEBHOOK_RATE_LIMIT``
     a minute) is a 429 with ``Retry-After``, before it is claimed (GW-02); the
     endpoints are exempt from the per-IP REST limit, which a provider's
     shared IPs would exhaust;
  2. a delivery the endpoint has already taken in the last 24 hours (the
     provider's delivery id, else the body's hash) is acknowledged with 200
     ``duplicate`` and not run again (GW-03);
  3. the source's normaliser turns the body into a standard EventEnvelope for the
     endpoint's company — never one named in the request;
  4. it is stored as an event in the company's database and routed by its
     triggers (``automation.gateway``, Phase 14 WS3; the delivery is the event's
     dedupe key) — or, with ``AUTOMATION_GATEWAY_EVENTS`` off, queued as a
     process_gateway_event arq job (src/gateway/envelope.py). The answer is 202
     only once the event is stored or queued — 503 otherwise, so the provider
     retries (SA-09).

The bare ``POST /webhook/inbound`` (tenant from ``?client_id=``, scheme sniffed
from the request's own headers, every check returning True) answers 401.

Adding a source = a name in ``WEBHOOK_SOURCES``, a normaliser here and a check
in ``webhook_signatures.SIGNERS``.
"""
# No ``from __future__ import annotations``: the endpoints are wrapped by
# ``limiter.exempt``, and FastAPI would resolve string annotations against the
# wrapper's module (slowapi), turning ``request: Request`` into a query param.
import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.tenancy.session import get_control_db
from src.common.rate_limit import limiter
from src.common.redis_client import shared_redis
from src.gateway.envelope import EventEnvelope, queue_event
from src.gateway.socket_limits import webhook_allowed
from src.gateway.webhook_signatures import SignedRequest, verify_signature

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Webhooks"])


# ===========================================================================
# Normalisers — one per source
# ===========================================================================

class WebhookStrategy:
    """Turns one source's payload into ``event_type`` and ``normalized_data``."""

    source = "generic"

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> Dict[str, Any]:
        raise NotImplementedError


class EmailWebhookStrategy(WebhookStrategy):
    """Email providers (Mailgun, SendGrid, Postmark, …)."""

    source = "email"

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        return {
            "event_type": "new_email",
            "normalized_data": {
                "from": payload.get("from") or payload.get("sender"),
                "to": payload.get("to") or payload.get("recipient"),
                "subject": payload.get("subject", ""),
                "body": payload.get("body-plain") or payload.get("body", ""),
                "attachments": payload.get("attachment-count", 0),
                "headers": dict(headers),
            },
        }


class CRMWebhookStrategy(WebhookStrategy):
    """CRM webhooks (HubSpot, Salesforce, Zoho, …)."""

    source = "crm"

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        event_type = payload.get("subscriptionType") or payload.get("crm_event", "crm_update")
        # A CRM payload may name the agent a lead should go to.
        entity_id = payload.get("entity_id") or query_params.get("entity_id", "")
        properties = payload.get("properties", {})
        return {
            "event_type": event_type,
            "normalized_data": {
                "object_type": payload.get("objectTypeId") or payload.get("object_type", "contact"),
                "object_id": payload.get("objectId") or payload.get("id"),
                "change_source": payload.get("changeSource", "unknown"),
                "properties": properties,
                "entity_id": entity_id,
                "phone": properties.get("phone", ""),
                "lead_id": payload.get("id", ""),
                "ad_source": properties.get("ad_source", ""),
                "project_id": properties.get("project_id", ""),
                "raw": payload,
            },
        }


class LinkedInWebhookStrategy(WebhookStrategy):
    source = "linkedin"

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        return {
            "event_type": payload.get("type", "linkedin.event"),
            "normalized_data": {
                "actor": payload.get("actor"),
                "object": payload.get("object"),
                "change_type": payload.get("changeType"),
                "raw": payload,
            },
        }


class GitHubWebhookStrategy(WebhookStrategy):
    """GitHub push, PR and issue events."""

    source = "github"

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        event_name = headers.get("x-github-event", "push")
        return {
            "event_type": f"github.{event_name}",
            "normalized_data": {
                "repository": payload.get("repository", {}).get("full_name"),
                "sender": payload.get("sender", {}).get("login"),
                "action": payload.get("action"),
                "raw": payload,
            },
        }


class TwilioWebhookStrategy(WebhookStrategy):
    """Twilio status and message callbacks."""

    source = "twilio"

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        return {
            "event_type": "twilio." + payload.get("EventType", "status_update"),
            "normalized_data": payload,
        }


def _meta_events(payload: dict) -> list:
    events = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            events.append({"field": change.get("field"), "value": change.get("value")})
        for msg in entry.get("messaging", []):
            events.append({"messaging": msg})
    return events


class FacebookWebhookStrategy(WebhookStrategy):
    """Facebook Page and Messenger events."""

    source = "facebook"

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        obj = payload.get("object", "page")
        return {
            "event_type": f"facebook.{obj}",
            "normalized_data": {"object": obj, "events": _meta_events(payload), "raw": payload},
        }


class InstagramWebhookStrategy(WebhookStrategy):
    """Instagram events (Meta Graph API)."""

    source = "instagram"

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        return {
            "event_type": "instagram.webhook",
            "normalized_data": {"events": _meta_events(payload), "raw": payload},
        }


class TwitterWebhookStrategy(WebhookStrategy):
    """X/Twitter Account Activity events."""

    source = "twitter"

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        # Events arrive under keys like tweet_create_events, follow_events, …
        event_types = [k for k in payload.keys() if k.endswith("_events")]
        primary_event = event_types[0] if event_types else "unknown_event"
        return {
            "event_type": f"twitter.{primary_event}",
            "normalized_data": {
                "for_user_id": payload.get("for_user_id", ""),
                "event_type": primary_event,
                "events": payload.get(primary_event, []),
                "raw": payload,
            },
        }


class TikTokWebhookStrategy(WebhookStrategy):
    source = "tiktok"

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        return {
            "event_type": f"tiktok.{payload.get('event', 'tiktok.event')}",
            "normalized_data": payload,
        }


class YouTubeWebhookStrategy(WebhookStrategy):
    """YouTube WebSub (PubSubHubbub) notifications."""

    source = "youtube"

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        entry = payload.get("feed", {}).get("entry", payload.get("entry", {}))
        video_id = channel_id = ""
        if isinstance(entry, dict):
            video_id = entry.get("yt:videoId", entry.get("videoId", ""))
            channel_id = entry.get("yt:channelId", entry.get("channelId", ""))
        return {
            "event_type": "youtube.video.published",
            "normalized_data": {
                "video_id": video_id,
                "channel_id": channel_id,
                "title": entry.get("title", "") if isinstance(entry, dict) else "",
                "raw": payload,
            },
        }


class PinterestWebhookStrategy(WebhookStrategy):
    source = "pinterest"

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        event_type = payload.get("event", payload.get("type", "unknown"))
        return {
            "event_type": f"pinterest.{event_type}",
            "normalized_data": {"event": event_type, "data": payload.get("data", payload), "raw": payload},
        }


class GenericWebhookStrategy(WebhookStrategy):
    """Any other system; ``?source=`` and ``?event_type=`` describe the event."""

    source = "generic"

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        return {
            "event_type": query_params.get("event_type") or payload.get("type", "generic_event"),
            "normalized_data": {"source": query_params.get("source", "unknown"), "raw": payload},
        }


STRATEGIES: Dict[str, WebhookStrategy] = {
    s.source: s for s in (
        EmailWebhookStrategy(), CRMWebhookStrategy(), LinkedInWebhookStrategy(),
        GitHubWebhookStrategy(), TwilioWebhookStrategy(), FacebookWebhookStrategy(),
        InstagramWebhookStrategy(), TwitterWebhookStrategy(), TikTokWebhookStrategy(),
        YouTubeWebhookStrategy(), PinterestWebhookStrategy(), GenericWebhookStrategy(),
    )
}


# ===========================================================================
# Endpoint lookup
# ===========================================================================

@dataclass(frozen=True)
class BoundEndpoint:
    """An active endpoint of an active company, with its secret decrypted."""

    id: UUID
    company_id: UUID
    source: str
    secret: str
    entity_id: Optional[UUID]


async def load_endpoint(db: AsyncSession, endpoint_id: str) -> Optional[BoundEndpoint]:
    """The endpoint behind ``endpoint_id``, or None if it cannot take events.

    None for an unknown or revoked endpoint, a suspended company, or a secret
    that does not decrypt — the request is then refused, never let through.
    """
    from src.auth.models import Company
    from src.common.security import decrypt_api_key
    from src.gateway.models import WebhookEndpoint

    try:
        eid = UUID(endpoint_id)
    except ValueError:
        return None
    row = (await db.execute(
        select(WebhookEndpoint, Company.status)
        .join(Company, Company.id == WebhookEndpoint.company_id)
        .where(WebhookEndpoint.id == eid, WebhookEndpoint.is_active.is_(True))
    )).first()
    if row is None or row[1] != "active":
        return None
    endpoint = row[0]
    try:
        secret = decrypt_api_key(endpoint.secret_encrypted) or ""
    except Exception as exc:
        from src.common.gates import gate_failed
        gate_failed("webhook_signature", exc, endpoint_id=str(eid))
        return None
    if not secret:
        return None
    return BoundEndpoint(id=endpoint.id, company_id=endpoint.company_id, source=endpoint.source,
                         secret=secret, entity_id=endpoint.entity_id)


async def _mark_received(db: AsyncSession, endpoint_id: UUID) -> None:
    from sqlalchemy import update

    from src.gateway.models import WebhookEndpoint
    try:
        await db.execute(update(WebhookEndpoint).where(WebhookEndpoint.id == endpoint_id)
                         .values(last_received_at=datetime.utcnow()))
        await db.commit()
    except Exception:
        logger.warning("[WebhookRouter] Could not record delivery time for %s", endpoint_id,
                       exc_info=True)


# ===========================================================================
# Deliveries — each is processed once (GW-03)
# ===========================================================================

# How long a delivery is remembered. Providers retry within minutes to hours.
DELIVERY_TTL_SECONDS = 24 * 60 * 60

# The header a source puts its own delivery id in; any source may also send
# ``X-HB-Delivery`` (a relay's id). Without one, the body's hash is the id.
_DELIVERY_HEADERS = {
    "github": "x-github-delivery",
    "twilio": "i-twilio-idempotency-token",
}


def delivery_id(source: str, headers: dict, body: bytes) -> str:
    """What identifies one delivery of one event, retries included."""
    for header in (_DELIVERY_HEADERS.get(source), "x-hb-delivery"):
        if header and headers.get(header):
            return "id:" + headers[header]
    return "body:" + hashlib.sha256(body).hexdigest()


def _delivery_key(endpoint_id: UUID, delivery: str) -> str:
    return f"webhook:delivery:{endpoint_id}:{delivery}"


async def claim_delivery(endpoint_id: UUID, delivery: str) -> bool:
    """True the first time a delivery is seen in ``DELIVERY_TTL_SECONDS``."""
    claimed = await shared_redis().set(_delivery_key(endpoint_id, delivery), "1",
                                       nx=True, ex=DELIVERY_TTL_SECONDS)
    return bool(claimed)


async def release_delivery(endpoint_id: UUID, delivery: str) -> None:
    """Forget a claimed delivery whose event was not queued, so its retry runs."""
    try:
        await shared_redis().delete(_delivery_key(endpoint_id, delivery))
    except Exception:
        logger.warning("[WebhookRouter] Could not release delivery %s for %s", delivery,
                       endpoint_id, exc_info=True)


def _rejected(status_code: int, correlation_id: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={
        "status": "rejected", "correlation_id": correlation_id, "detail": detail,
    })


# ===========================================================================
# Endpoints
# ===========================================================================

@router.post("/webhook/inbound", status_code=401)
@limiter.exempt
async def unified_webhook_inbound(request: Request):
    """Retired: a webhook must arrive at its endpoint and be signed (GW-01)."""
    return _rejected(401, str(uuid.uuid4()),
                     "Webhooks are accepted only at /webhook/inbound/{endpoint_id}, signed with "
                     "the endpoint's secret. Create one with POST /api/v1/webhook-endpoints.")


@router.post("/webhook/inbound/{endpoint_id}", status_code=202)
@limiter.exempt
async def webhook_inbound(endpoint_id: str, request: Request, db: AsyncSession = Depends(get_control_db)):
    """
    Receive one webhook for one endpoint.

    404 for an endpoint that cannot take events; 401 when the signature is
    missing or wrong (nothing is queued); 200 ``duplicate`` for a delivery
    already taken; 202 once the event is queued for the worker; 503 if it
    cannot be checked or queued (the provider should retry).
    """
    correlation_id = str(uuid.uuid4())
    raw_body = await request.body()

    endpoint = await load_endpoint(db, endpoint_id)
    if endpoint is None:
        return _rejected(404, correlation_id, "Unknown webhook endpoint")

    # Parse payload (JSON preferred; fall back to form data)
    form: dict = {}
    try:
        payload = await request.json()
    except Exception:
        form = {k: str(v) for k, v in (await request.form()).items()}
        payload = dict(form)
    if not isinstance(payload, dict):
        payload = {"items": payload}

    headers = {k.lower(): v for k, v in request.headers.items()}
    query_params = dict(request.query_params)

    signed = SignedRequest(headers=headers, body=raw_body, url=str(request.url),
                           form=form, payload=payload, method=request.method)
    if not verify_signature(endpoint.source, endpoint.secret, signed):
        logger.warning("[WebhookRouter] Signature check failed: endpoint=%s source=%s "
                       "correlation=%s", endpoint.id, endpoint.source, correlation_id)
        from src.ai.core.events import event
        event("gateway.webhook.signature_failed", endpoint_id=str(endpoint.id),
              company_id=str(endpoint.company_id), source=endpoint.source)
        return _rejected(401, correlation_id, "Webhook signature missing or invalid")

    # So many signed deliveries a minute per endpoint — one company, one
    # source (GW-02). Before the delivery is claimed, so the provider's retry
    # is taken, not dropped as a duplicate.
    if not webhook_allowed(endpoint.id):
        from src.ai.core.events import event
        event("gateway.webhook.rate_limited", endpoint_id=str(endpoint.id),
              company_id=str(endpoint.company_id), source=endpoint.source)
        return JSONResponse(status_code=429, headers={"Retry-After": "60"}, content={
            "status": "rate_limited", "correlation_id": correlation_id,
            "detail": "Too many deliveries to this endpoint; retry later.",
        })

    # A provider's retry of an event already queued is acknowledged, not run
    # again (GW-03). Unable to tell — Redis down — is a 503, never a second run.
    delivery = delivery_id(endpoint.source, headers, raw_body)
    try:
        fresh = await claim_delivery(endpoint.id, delivery)
    except Exception as exc:
        from src.common.gates import gate_failed
        gate_failed("webhook_duplicate", exc, endpoint_id=str(endpoint.id), correlation_id=correlation_id)
        return JSONResponse(status_code=503, content={
            "status": "unavailable",
            "correlation_id": correlation_id,
            "detail": "The event could not be checked for duplicates. Retry later.",
        })
    if not fresh:
        logger.info("[WebhookRouter] Duplicate delivery %s on endpoint %s", delivery, endpoint.id)
        return JSONResponse(status_code=200, content={
            "status": "duplicate", "correlation_id": correlation_id, "source": endpoint.source,
        })

    normalized = STRATEGIES[endpoint.source].normalize(headers, payload, query_params)
    event_type = normalized.get("event_type", "generic_event")
    client_id = str(endpoint.company_id)

    logger.info(
        f"[WebhookRouter] Received {event_type} from source={endpoint.source} "
        f"endpoint={endpoint.id} client={client_id} correlation={correlation_id}"
    )

    envelope = EventEnvelope(
        channel="webhook",
        source=endpoint.source,
        client_id=client_id,
        event_type=event_type,
        raw_data=normalized.get("normalized_data", {}),
        metadata={
            "correlation_id": correlation_id,
            "delivery_id": delivery,
            "endpoint_id": str(endpoint.id),
            "entity_id": str(endpoint.entity_id) if endpoint.entity_id else None,
            "x_forwarded_for": headers.get("x-forwarded-for", ""),
            "user_agent": headers.get("user-agent", ""),
            "strategy": STRATEGIES[endpoint.source].__class__.__name__,
        },
        id=correlation_id,
    )

    try:
        from src.automation import gateway
        if gateway.enabled():
            await gateway.ingest(envelope, dedupe_key=f"webhook:{endpoint.id}:{delivery}", trust="verified",
                                 endpoint_id=endpoint.id, bound=endpoint.entity_id is not None)
        else:
            await queue_event(envelope)
    except Exception:
        logger.exception(f"[WebhookRouter] Could not queue event {correlation_id}")
        await release_delivery(endpoint.id, delivery)
        return JSONResponse(status_code=503, content={
            "status": "unavailable",
            "correlation_id": correlation_id,
            "detail": "The event could not be queued. Retry later.",
        })

    await _mark_received(db, endpoint.id)
    return {
        "status": "accepted",
        "correlation_id": correlation_id,
        "source": endpoint.source,
        "event_type": event_type,
    }
