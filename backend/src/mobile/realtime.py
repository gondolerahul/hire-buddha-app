"""
Cross-process messaging for the mobile dialer (docs 04 §7).

The live call handler runs in the gateway (:8001) while app events arrive at
the backend API (:8000); both share Redis. Pub/sub is fire-and-forget — the
durable state is always the Postgres attempt row, so every subscriber
re-reads it after (re)subscribing.

Channels:
  voice:session:{session_id}:control   API -> stream handler ("merged", "abort", "rep_takeover")
  mobile:user:{user_id}:push           handler/API -> the user's /mobile/ws socket(s)
"""
import json
import logging
from datetime import datetime
from typing import Any, AsyncIterator, Dict, Optional
from uuid import UUID

from src.common.config import settings

logger = logging.getLogger(__name__)

_redis = None


def session_control_channel(session_id) -> str:
    return f"voice:session:{session_id}:control"


def user_push_channel(user_id) -> str:
    return f"mobile:user:{user_id}:push"


async def get_redis():
    """Shared redis.asyncio client (lazy, one per process)."""
    global _redis
    if _redis is None:
        import redis.asyncio as aioredis
        _redis = aioredis.from_url(settings.REDIS_URL or "redis://localhost:6379", decode_responses=True)
    return _redis


def _default(o):
    if isinstance(o, UUID):
        return str(o)
    if isinstance(o, datetime):
        return o.isoformat() + "Z"
    raise TypeError(f"not serializable: {type(o)}")


def build_message(msg_type: str, **fields: Any) -> Dict[str, Any]:
    msg = {"type": msg_type, "at": datetime.utcnow()}
    msg.update(fields)
    return json.loads(json.dumps(msg, default=_default))


async def publish(channel: str, message: Dict[str, Any]) -> int:
    """Publish JSON; returns subscriber count (0 is normal, never raises)."""
    try:
        r = await get_redis()
        return await r.publish(channel, json.dumps(message, default=_default))
    except Exception as e:
        logger.warning(f"[Mobile] publish to {channel} failed: {e}")
        return 0


async def publish_session_control(session_id, msg_type: str, **fields) -> int:
    return await publish(session_control_channel(session_id), build_message(msg_type, session_id=session_id, **fields))


async def publish_user_push(user_id, msg_type: str, *, fcm_token: Optional[str] = None, **fields) -> int:
    """Push to the user's live sockets; falls back to FCM when nobody listens."""
    message = build_message(msg_type, **fields)
    receivers = await publish(user_push_channel(user_id), message)
    if receivers == 0 and fcm_token and msg_type in FCM_FALLBACK_TYPES:
        await send_fcm_data_message(fcm_token, message)
    return receivers


async def subscribe(channel: str) -> AsyncIterator[Dict[str, Any]]:
    """Yield decoded JSON messages from a channel until cancelled."""
    r = await get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(channel)
    try:
        async for raw in pubsub.listen():
            if raw.get("type") != "message":
                continue
            try:
                yield json.loads(raw["data"])
            except (TypeError, ValueError):
                logger.warning(f"[Mobile] dropped malformed message on {channel}")
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
        except Exception:
            pass


# ── FCM fallback ────────────────────────────────────────────────────────

# Only messages the app must act on even when backgrounded without a socket.
FCM_FALLBACK_TYPES = {"attempt.ai_ended", "attempt.ai_ready", "attempt.unidentified", "run.paused"}

_fcm_credentials = None


async def send_fcm_data_message(token: str, message: Dict[str, Any]) -> bool:
    """High-priority FCM HTTP v1 data message. No-op when FCM isn't configured."""
    path = settings.MOBILE_FCM_SERVICE_ACCOUNT_FILE
    if not path or not token:
        return False
    try:
        import asyncio
        import httpx
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2 import service_account

        global _fcm_credentials
        if _fcm_credentials is None:
            _fcm_credentials = service_account.Credentials.from_service_account_file(
                path, scopes=["https://www.googleapis.com/auth/firebase.messaging"]
            )
        if not _fcm_credentials.valid:
            await asyncio.to_thread(_fcm_credentials.refresh, GoogleRequest())
        project_id = _fcm_credentials.project_id
        body = {
            "message": {
                "token": token,
                "android": {"priority": "HIGH", "ttl": "30s"},
                # FCM data values must be strings.
                "data": {k: (v if isinstance(v, str) else json.dumps(v)) for k, v in message.items()},
            }
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send",
                json=body,
                headers={"Authorization": f"Bearer {_fcm_credentials.token}"},
            )
        if resp.status_code >= 300:
            logger.warning(f"[Mobile] FCM send failed {resp.status_code}: {resp.text[:200]}")
            return False
        return True
    except Exception as e:
        logger.warning(f"[Mobile] FCM send error: {e}")
        return False
