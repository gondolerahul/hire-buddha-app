"""
Interface 2: Unified Webhook Endpoint.

Single endpoint: POST /webhook/inbound

Uses the Strategy Pattern to:
  1. Identify the source (email, CRM, LinkedIn, GitHub, generic)
  2. Validate the signature (per-provider)
  3. Normalize to a standard EventEnvelope
  4. Return 202 Accepted immediately
  5. Publish to the event bus (async processing by the dispatcher)

Adding a new webhook source = add a new WebhookStrategy subclass.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from src.gateway.event_bus import EventEnvelope, get_event_bus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Webhooks"])


# ===========================================================================
# Webhook Strategy Base
# ===========================================================================

class WebhookStrategy(ABC):
    """Base strategy for detecting and normalizing a specific webhook source."""

    @abstractmethod
    def can_handle(self, request_headers: dict, payload: dict) -> bool:
        """Return True if this strategy can handle the given request."""

    @abstractmethod
    def get_source(self) -> str:
        """Return the normalized source name."""

    @abstractmethod
    def normalize(
        self, request_headers: dict, payload: dict, query_params: dict
    ) -> Dict[str, Any]:
        """
        Return a dict with:
          client_id, event_type, normalized_data
        """

    def validate_signature(self, request_headers: dict, raw_body: bytes) -> bool:
        """Override for signature validation. Default: always True (no validation)."""
        return True


# ===========================================================================
# Concrete Strategies
# ===========================================================================

class EmailWebhookStrategy(WebhookStrategy):
    """
    Handles webhooks from email providers (Mailgun, SendGrid, Postmark, etc.).
    Detects via X-Mailgun-* or X-Sg-Signature or X-Postmark-* headers.
    """

    def can_handle(self, headers: dict, payload: dict) -> bool:
        return any(
            k.lower().startswith(("x-mailgun", "x-sg-", "x-postmark"))
            for k in headers
        )

    def get_source(self) -> str:
        return "email"

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        return {
            "client_id": query_params.get("client_id", ""),
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
    """
    Handles CRM webhooks (HubSpot, Salesforce, Zoho, etc.).
    Detects via X-HubSpot-Signature, X-Salesforce-* or payload structure.
    """

    def can_handle(self, headers: dict, payload: dict) -> bool:
        return any(
            k.lower().startswith(("x-hubspot", "x-salesforce", "x-zoho"))
            for k in headers
        ) or "crm_event" in payload

    def get_source(self) -> str:
        return "crm"

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        # Detect sub-type from payload
        event_type = payload.get("subscriptionType") or payload.get("crm_event", "crm_update")

        # Extract entity_id (target agent) from payload or query params.
        # This allows CRM webhooks to route leads to a specific voice agent
        # instead of the generic "first active agent" fallback.
        entity_id = (
            payload.get("entity_id")
            or query_params.get("entity_id", "")
        )

        properties = payload.get("properties", {})

        return {
            "client_id": query_params.get("client_id", ""),
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
    """
    Handles LinkedIn webhook events (connection requests, messages, etc.).
    Detects via X-Li-Signature or payload structure.
    """

    def can_handle(self, headers: dict, payload: dict) -> bool:
        return (
            "x-li-signature" in {k.lower() for k in headers}
            or payload.get("type", "").startswith("linkedin.")
            or "linkedin" in payload.get("source", "").lower()
        )

    def get_source(self) -> str:
        return "linkedin"

    def validate_signature(self, headers: dict, raw_body: bytes) -> bool:
        # LinkedIn sends HMAC-SHA256 signature in X-Li-Signature
        signature = headers.get("X-Li-Signature") or headers.get("x-li-signature", "")
        if not signature:
            return True  # No signature = unauthenticated (log warning)
        # TODO: validate against configured LinkedIn client secret
        logger.warning("[WebhookRouter] LinkedIn signature validation not yet configured")
        return True

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        event_type = payload.get("type", "linkedin.event")
        return {
            "client_id": query_params.get("client_id", ""),
            "event_type": event_type,
            "normalized_data": {
                "actor": payload.get("actor"),
                "object": payload.get("object"),
                "change_type": payload.get("changeType"),
                "raw": payload,
            },
        }


class GitHubWebhookStrategy(WebhookStrategy):
    """Handles GitHub webhooks (push, PR, issue events)."""

    def can_handle(self, headers: dict, payload: dict) -> bool:
        return "x-github-event" in {k.lower() for k in headers}

    def get_source(self) -> str:
        return "github"

    def validate_signature(self, headers: dict, raw_body: bytes) -> bool:
        sig256 = headers.get("X-Hub-Signature-256") or headers.get("x-hub-signature-256", "")
        if not sig256:
            return True
        # TODO: validate HMAC-SHA256 against configured GitHub webhook secret
        logger.warning("[WebhookRouter] GitHub signature validation not yet configured")
        return True

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        event_name = headers.get("X-GitHub-Event") or headers.get("x-github-event", "push")
        return {
            "client_id": query_params.get("client_id", ""),
            "event_type": f"github.{event_name}",
            "normalized_data": {
                "repository": payload.get("repository", {}).get("full_name"),
                "sender": payload.get("sender", {}).get("login"),
                "action": payload.get("action"),
                "raw": payload,
            },
        }


class TwilioWebhookStrategy(WebhookStrategy):
    """
    Handles Twilio webhooks (call status, SMS, etc) routed via the unified endpoint.
    Detects via X-Twilio-Signature header.
    """

    def can_handle(self, headers: dict, payload: dict) -> bool:
        return "x-twilio-signature" in {k.lower() for k in headers}

    def get_source(self) -> str:
        return "twilio"

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        return {
            "client_id": query_params.get("client_id", ""),
            "event_type": "twilio." + payload.get("EventType", "status_update"),
            "normalized_data": payload,
        }


class FacebookWebhookStrategy(WebhookStrategy):
    """
    Handles Facebook webhooks (Page events, Messenger).
    Detects via X-Hub-Signature-256 header with 'sha256=' prefix.
    Also handles the hub.challenge verification for webhook subscription.
    """

    def can_handle(self, headers: dict, payload: dict) -> bool:
        has_hub_sig = "x-hub-signature-256" in {k.lower() for k in headers}
        is_fb_payload = payload.get("object") in ("page", "instagram", "permissions")
        return has_hub_sig or is_fb_payload

    def get_source(self) -> str:
        return "facebook"

    def validate_signature(self, headers: dict, raw_body: bytes) -> bool:
        sig = headers.get("X-Hub-Signature-256") or headers.get("x-hub-signature-256", "")
        if not sig:
            return True
        # TODO: validate HMAC-SHA256 against configured Facebook app secret
        logger.warning("[WebhookRouter] Facebook signature validation not yet configured")
        return True

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        obj = payload.get("object", "page")
        entries = payload.get("entry", [])
        events = []
        for entry in entries:
            for change in entry.get("changes", []):
                events.append({
                    "field": change.get("field"),
                    "value": change.get("value"),
                })
            for msg in entry.get("messaging", []):
                events.append({"messaging": msg})

        return {
            "client_id": query_params.get("client_id", ""),
            "event_type": f"facebook.{obj}",
            "normalized_data": {
                "object": obj,
                "events": events,
                "raw": payload,
            },
        }


class TwitterWebhookStrategy(WebhookStrategy):
    """
    Handles X/Twitter webhook events (Account Activity API).
    Detects via X-Twitter-Webhooks-Signature header.
    """

    def can_handle(self, headers: dict, payload: dict) -> bool:
        return (
            "x-twitter-webhooks-signature" in {k.lower() for k in headers}
            or "for_user_id" in payload
        )

    def get_source(self) -> str:
        return "twitter"

    def validate_signature(self, headers: dict, raw_body: bytes) -> bool:
        sig = headers.get("X-Twitter-Webhooks-Signature") or headers.get("x-twitter-webhooks-signature", "")
        if not sig:
            return True
        logger.warning("[WebhookRouter] Twitter signature validation not yet configured")
        return True

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        user_id = payload.get("for_user_id", "")
        # Twitter sends events under keys like tweet_create_events, follow_events, etc.
        event_types = [k for k in payload.keys() if k.endswith("_events")]
        primary_event = event_types[0] if event_types else "unknown_event"

        return {
            "client_id": query_params.get("client_id", ""),
            "event_type": f"twitter.{primary_event}",
            "normalized_data": {
                "for_user_id": user_id,
                "event_type": primary_event,
                "events": payload.get(primary_event, []),
                "raw": payload,
            },
        }


class InstagramWebhookStrategy(WebhookStrategy):
    """
    Handles Instagram webhook events (via Meta Graph API).
    Instagram webhooks share the X-Hub-Signature-256 with Facebook but have
    object='instagram' in the payload.
    """

    def can_handle(self, headers: dict, payload: dict) -> bool:
        return payload.get("object") == "instagram"

    def get_source(self) -> str:
        return "instagram"

    def validate_signature(self, headers: dict, raw_body: bytes) -> bool:
        sig = headers.get("X-Hub-Signature-256") or headers.get("x-hub-signature-256", "")
        if not sig:
            return True
        logger.warning("[WebhookRouter] Instagram signature validation not yet configured")
        return True

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        entries = payload.get("entry", [])
        events = []
        for entry in entries:
            for change in entry.get("changes", []):
                events.append({
                    "field": change.get("field"),
                    "value": change.get("value"),
                })
            for msg in entry.get("messaging", []):
                events.append({"messaging": msg})

        return {
            "client_id": query_params.get("client_id", ""),
            "event_type": "instagram.webhook",
            "normalized_data": {
                "events": events,
                "raw": payload,
            },
        }


class TikTokWebhookStrategy(WebhookStrategy):
    """
    Handles TikTok webhook events.
    Detects via X-TikTok-Signature header.
    """

    def can_handle(self, headers: dict, payload: dict) -> bool:
        return "x-tiktok-signature" in {k.lower() for k in headers}

    def get_source(self) -> str:
        return "tiktok"

    def validate_signature(self, headers: dict, raw_body: bytes) -> bool:
        sig = headers.get("X-TikTok-Signature") or headers.get("x-tiktok-signature", "")
        if not sig:
            return True
        logger.warning("[WebhookRouter] TikTok signature validation not yet configured")
        return True

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        event_type = payload.get("event", "tiktok.event")
        return {
            "client_id": query_params.get("client_id", ""),
            "event_type": f"tiktok.{event_type}",
            "normalized_data": payload,
        }


class GenericWebhookStrategy(WebhookStrategy):
    """
    Fallback strategy for unrecognized webhook sources.
    Reads source from ?source= query parameter.
    """

    def can_handle(self, headers: dict, payload: dict) -> bool:
        return True  # Always matches (must be last in the list)

    def get_source(self) -> str:
        return "generic"

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        source = query_params.get("source", "unknown")
        event_type = query_params.get("event_type") or payload.get("type", "generic_event")
        return {
            "client_id": query_params.get("client_id", ""),
            "event_type": event_type,
            "normalized_data": {
                "source": source,
                "raw": payload,
            },
        }


class YouTubeWebhookStrategy(WebhookStrategy):
    """YouTube PubSubHubbub / Data API webhook notifications.

    YouTube sends notifications via PubSubHubbub (Atom feed) or the YouTube
    Data API v3 for subscription-based push notifications. The Content-Type
    is typically application/atom+xml.
    """

    def can_handle(self, headers: dict, payload: dict) -> bool:
        ct = headers.get("content-type", "")
        link_header = headers.get("link", "")
        return (
            "atom+xml" in ct
            or "youtube.com" in link_header
            or "pubsubhubbub" in headers.get("x-hub-signature", "").lower()
            or payload.get("hub.topic", "").startswith("https://www.youtube.com/")
        )

    def get_source(self) -> str:
        return "youtube"

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        # YouTube PubSubHubbub delivers Atom XML; payload is pre-parsed or raw
        entry = payload.get("feed", {}).get("entry", payload.get("entry", {}))
        video_id = ""
        channel_id = ""
        if isinstance(entry, dict):
            video_id = entry.get("yt:videoId", entry.get("videoId", ""))
            channel_id = entry.get("yt:channelId", entry.get("channelId", ""))

        return {
            "client_id": query_params.get("client_id", ""),
            "event_type": "youtube.video.published",
            "normalized_data": {
                "video_id": video_id,
                "channel_id": channel_id,
                "title": entry.get("title", "") if isinstance(entry, dict) else "",
                "raw": payload,
            },
        }


class PinterestWebhookStrategy(WebhookStrategy):
    """Pinterest webhook notifications.

    Pinterest signs webhook payloads using X-Pinterest-Signature header
    and sends events for pin creation, board updates, etc.
    """

    def can_handle(self, headers: dict, payload: dict) -> bool:
        return (
            "x-pinterest-signature" in headers
            or payload.get("source") == "pinterest"
            or "pinterest" in headers.get("user-agent", "").lower()
        )

    def get_source(self) -> str:
        return "pinterest"

    def normalize(self, headers: dict, payload: dict, query_params: dict) -> dict:
        event_type = payload.get("event", payload.get("type", "unknown"))
        data = payload.get("data", payload)

        return {
            "client_id": query_params.get("client_id", ""),
            "event_type": f"pinterest.{event_type}",
            "normalized_data": {
                "event": event_type,
                "data": data,
                "raw": payload,
            },
        }

# ---------------------------------------------------------------------------
# Strategy registry — order matters (GenericWebhookStrategy MUST be last)
# ---------------------------------------------------------------------------

WEBHOOK_STRATEGIES: list[WebhookStrategy] = [
    EmailWebhookStrategy(),
    CRMWebhookStrategy(),
    LinkedInWebhookStrategy(),
    GitHubWebhookStrategy(),
    TwilioWebhookStrategy(),
    # Social media platform webhooks
    InstagramWebhookStrategy(),  # Must come before Facebook (both use X-Hub-Signature-256)
    FacebookWebhookStrategy(),
    TwitterWebhookStrategy(),
    TikTokWebhookStrategy(),
    YouTubeWebhookStrategy(),
    PinterestWebhookStrategy(),
    GenericWebhookStrategy(),   # ← fallback, always last
]


def detect_strategy(headers: dict, payload: dict) -> WebhookStrategy:
    for strategy in WEBHOOK_STRATEGIES:
        if strategy.can_handle(headers, payload):
            return strategy
    return WEBHOOK_STRATEGIES[-1]  # GenericWebhookStrategy


# ===========================================================================
# Endpoint
# ===========================================================================

@router.post("/webhook/inbound", status_code=202)
async def unified_webhook_inbound(request: Request, background_tasks: BackgroundTasks):
    """
    Unified Webhook Receiver — Interface 2.

    Accepts HTTP POST from any external system (email providers, CRMs,
    LinkedIn, GitHub, Twilio, etc.).

    Returns 202 Accepted immediately. Processing is async via the event bus.
    """
    raw_body = await request.body()

    # Parse payload (JSON preferred; fall back to form data)
    try:
        payload = await request.json()
    except Exception:
        form = await request.form()
        payload = dict(form)

    headers = dict(request.headers)
    query_params = dict(request.query_params)

    # Detect source and normalize
    strategy = detect_strategy(headers, payload)
    source = strategy.get_source()

    # Signature validation (best-effort; log warning on failure, don't block)
    if not strategy.validate_signature(headers, raw_body):
        logger.warning(f"[WebhookRouter] Signature validation failed for source={source}")
        # We still process — providers may retry; we log for audit

    normalized = strategy.normalize(headers, payload, query_params)
    client_id = normalized.get("client_id", "") or query_params.get("client_id", "")
    event_type = normalized.get("event_type", "generic_event")

    correlation_id = str(uuid.uuid4())

    logger.info(
        f"[WebhookRouter] Received {event_type} from source={source} "
        f"client={client_id} correlation={correlation_id}"
    )

    # Build normalized envelope
    envelope = EventEnvelope(
        channel="webhook",
        source=source,
        client_id=client_id,
        event_type=event_type,
        raw_data=normalized.get("normalized_data", {}),
        metadata={
            "correlation_id": correlation_id,
            "x_forwarded_for": headers.get("x-forwarded-for", ""),
            "user_agent": headers.get("user-agent", ""),
            "strategy": strategy.__class__.__name__,
        },
        id=correlation_id,
    )

    # Publish to event bus (non-blocking)
    background_tasks.add_task(_publish_to_bus, envelope)

    return {
        "status": "accepted",
        "correlation_id": correlation_id,
        "source": source,
        "event_type": event_type,
    }


async def _publish_to_bus(envelope: EventEnvelope) -> None:
    """Background task: publish event envelope to the event bus."""
    try:
        bus = get_event_bus()
        await bus.publish(envelope)
        logger.info(f"[WebhookRouter] Published event {envelope.id} to bus")
    except Exception as exc:
        logger.error(f"[WebhookRouter] Failed to publish event: {exc}")
