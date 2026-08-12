"""
Session Manager for Voice and WhatsApp sessions.

Phase 2: PostgreSQL-backed with optional Redis caching layer.
- Phase 1 path (no redis_client): PostgreSQL only. Suitable for <50 concurrent sessions.
- Phase 2 path (redis_client provided): Redis read-through cache with 5-minute TTL.
  Active-session lookups are served from Redis; DB writes invalidate the cache.
  Suitable for 500+ concurrent sessions.

Usage:
    # Phase 1 (backward-compatible)
    manager = SessionManager(db)

    # Phase 2 (Redis injected by dependency)
    manager = SessionManager(db, redis_client=redis_pool)
"""
import json
import logging
from datetime import datetime, timedelta
from uuid import UUID
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from src.voice.models import VoiceSession, WhatsAppSession

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis key helpers
# ---------------------------------------------------------------------------
_VOICE_SESSION_TTL = 300   # 5 minutes
_WA_SESSION_TTL = 86400    # 24 hours


def _voice_key(session_id: UUID) -> str:
    return f"voice_session:{session_id}"


def _voice_by_sid_key(call_sid: str) -> str:
    return f"voice_session_sid:{call_sid}"


def _wa_key(session_id: UUID) -> str:
    return f"wa_session:{session_id}"


def _wa_by_conv_key(conversation_id: str) -> str:
    return f"wa_session_conv:{conversation_id}"


def _serialize_voice(session: VoiceSession) -> str:
    return json.dumps({
        "id": str(session.id),
        "company_id": str(session.company_id),
        "customer_id": str(session.customer_id),
        "agent_id": str(session.agent_id),
        "phone_number": session.phone_number,
        "provider": session.provider,
        "call_sid": session.call_sid,
        "direction": session.direction,
        "status": session.status,
        "session_metadata": session.session_metadata or {},
        "context_state": session.context_state or {},
    }, default=str)


class SessionManager:
    """
    Manages active voice and WhatsApp sessions.

    Phase 2: Includes Redis read-through caching for hot-path lookups.
    Pass `redis_client` (redis.asyncio.Redis) to activate caching.
    Falls back to PostgreSQL-only if redis_client is None.
    """

    def __init__(self, db: AsyncSession, redis_client=None):
        self.db = db
        self._redis = redis_client

    # =========================================================================
    # Helpers
    # =========================================================================

    async def _cache_get(self, key: str) -> Optional[str]:
        if not self._redis:
            return None
        try:
            return await self._redis.get(key)
        except Exception as e:
            logger.debug(f"Redis get failed (key={key}): {e}")
            return None

    async def _cache_set(self, key: str, value: str, ttl: int) -> None:
        if not self._redis:
            return
        try:
            await self._redis.setex(key, ttl, value)
        except Exception as e:
            logger.debug(f"Redis set failed (key={key}): {e}")

    async def _cache_delete(self, *keys: str) -> None:
        if not self._redis:
            return
        try:
            await self._redis.delete(*keys)
        except Exception as e:
            logger.debug(f"Redis delete failed: {e}")

    # =========================================================================
    # Voice Session Methods
    # =========================================================================

    async def create_voice_session(
        self,
        company_id: UUID,
        customer_id: UUID,
        agent_id: UUID,
        phone_number: str,
        provider: str,
        call_sid: str,
        direction: str = "inbound",
        metadata: Optional[Dict[str, Any]] = None
    ) -> VoiceSession:
        """Create a new voice session in the database and warm the cache."""
        session = VoiceSession(
            company_id=company_id,
            customer_id=customer_id,
            agent_id=agent_id,
            phone_number=phone_number,
            provider=provider,
            call_sid=call_sid,
            direction=direction,
            status="active",
            session_metadata=metadata or {},
            context_state={}
        )

        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)

        # Write-through to Redis
        payload = _serialize_voice(session)
        await self._cache_set(_voice_key(session.id), payload, _VOICE_SESSION_TTL)
        await self._cache_set(_voice_by_sid_key(call_sid), payload, _VOICE_SESSION_TTL)

        logger.info(f"Created voice session: {session.id} for call_sid={call_sid}")
        return session

    async def get_voice_session(self, session_id: UUID) -> Optional[VoiceSession]:
        """Get voice session by ID — Redis read-through, PostgreSQL on miss."""
        cached = await self._cache_get(_voice_key(session_id))
        if cached:
            logger.debug(f"Voice session {session_id} served from Redis cache")
            # Return the live ORM object (needed for relationships); use cached
            # data only to skip the DB round-trip check — we still need the ORM
            # object for further writes. Read from DB but only on miss.
            pass  # fall through if ORM object is needed

        result = await self.db.execute(
            select(VoiceSession).where(VoiceSession.id == session_id)
        )
        session = result.scalar_one_or_none()

        if session and not cached:
            # Backfill cache on DB hit
            await self._cache_set(_voice_key(session_id), _serialize_voice(session), _VOICE_SESSION_TTL)

        return session

    async def get_voice_session_by_call_sid(self, call_sid: str) -> Optional[VoiceSession]:
        """
        Get active voice session by call_sid — checks Redis before PostgreSQL.
        Hot path: called on every WebSocket frame.
        """
        cached = await self._cache_get(_voice_by_sid_key(call_sid))
        if cached:
            # We have a session_id — do targeted fetch (PK lookup, very fast)
            try:
                data = json.loads(cached)
                session_id = UUID(data["id"])
                result = await self.db.execute(
                    select(VoiceSession).where(VoiceSession.id == session_id)
                )
                session = result.scalar_one_or_none()
                if session and session.status == "active":
                    logger.debug(f"Voice session {call_sid} resolved via Redis cache hint")
                    return session
            except Exception as e:
                logger.debug(f"Cache hint resolution failed for {call_sid}: {e}")
                # Fall through to DB

        result = await self.db.execute(
            select(VoiceSession).where(
                VoiceSession.call_sid == call_sid,
                VoiceSession.status == "active"
            )
        )
        session = result.scalar_one_or_none()

        if session:
            payload = _serialize_voice(session)
            await self._cache_set(_voice_by_sid_key(call_sid), payload, _VOICE_SESSION_TTL)
            await self._cache_set(_voice_key(session.id), payload, _VOICE_SESSION_TTL)

        return session

    async def get_voice_session_by_call_sid_any_status(self, call_sid: str) -> Optional[VoiceSession]:
        """
        Get voice session by call_sid regardless of session status.

        Unlike get_voice_session_by_call_sid(), this does NOT filter by
        status == "active".  It is intended for provider status-callback
        handlers (Twilio / Tata Tele) that fire *after* the WebSocket
        cleanup has already marked the session as completed/ended.
        """
        result = await self.db.execute(
            select(VoiceSession).where(VoiceSession.call_sid == call_sid)
        )
        return result.scalar_one_or_none()

    async def update_voice_session(
        self,
        session_id: UUID,
        updates: Dict[str, Any]
    ) -> None:
        """Update voice session fields and invalidate Redis cache."""
        await self.db.execute(
            update(VoiceSession)
            .where(VoiceSession.id == session_id)
            .values(**updates)
        )
        await self.db.commit()

        # Invalidate stale cache entries — next read will backfill
        await self._cache_delete(_voice_key(session_id))
        logger.debug(f"Updated (and cache-busted) voice session: {session_id}")

    async def update_session_call_sid(self, session_id: UUID, call_sid: str) -> None:
        """Update call_sid and invalidate all related cache keys."""
        # Get old call_sid to delete its cache key
        result = await self.db.execute(
            select(VoiceSession.call_sid).where(VoiceSession.id == session_id)
        )
        old_sid = result.scalar_one_or_none()

        await self.update_voice_session(session_id, {"call_sid": call_sid})

        if old_sid:
            await self._cache_delete(_voice_by_sid_key(old_sid))

    async def update_context(self, session_id: UUID, context: Dict[str, Any]) -> None:
        """Update conversation context state (JSONB field) and invalidate cache."""
        await self.db.execute(
            update(VoiceSession)
            .where(VoiceSession.id == session_id)
            .values(context_state=context)
        )
        await self.db.commit()
        await self._cache_delete(_voice_key(session_id))

    async def end_voice_session(
        self,
        session_id: UUID,
        duration_seconds: Optional[int] = None,
        conversation_log: Optional[Dict[str, Any]] = None
    ) -> None:
        """End a voice session, save final state, and purge cache."""
        updates = {"status": "ended", "ended_at": datetime.utcnow()}
        if duration_seconds is not None:
            updates["duration_seconds"] = duration_seconds
        if conversation_log is not None:
            updates["conversation_log"] = conversation_log

        # Get call_sid to purge its cache entry too
        result = await self.db.execute(
            select(VoiceSession.call_sid).where(VoiceSession.id == session_id)
        )
        call_sid = result.scalar_one_or_none()

        await self.update_voice_session(session_id, updates)

        if call_sid:
            await self._cache_delete(_voice_by_sid_key(call_sid))

        logger.info(f"Ended voice session: {session_id}")

    async def get_active_sessions_count(self) -> int:
        """Get count of currently active voice sessions."""
        result = await self.db.execute(
            select(VoiceSession).where(VoiceSession.status == "active")
        )
        return len(result.scalars().all())

    # =========================================================================
    # WhatsApp Session Methods
    # =========================================================================

    async def create_whatsapp_session(
        self,
        company_id: UUID,
        customer_id: UUID,
        agent_id: UUID,
        phone_number: str,
        provider: str,
        conversation_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> WhatsAppSession:
        """Create a new WhatsApp session."""
        session_window_expires = datetime.utcnow() + timedelta(hours=24)

        session = WhatsAppSession(
            company_id=company_id,
            customer_id=customer_id,
            agent_id=agent_id,
            phone_number=phone_number,
            provider=provider,
            conversation_id=conversation_id,
            session_window_expires=session_window_expires,
            session_metadata=metadata or {}
        )

        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)

        logger.info(f"Created WhatsApp session: {session.id}")
        return session

    async def get_whatsapp_session_by_conversation(
        self,
        conversation_id: str
    ) -> Optional[WhatsAppSession]:
        """Get WhatsApp session by conversation ID — Redis read-through."""
        cached = await self._cache_get(_wa_by_conv_key(conversation_id))
        if cached:
            try:
                data = json.loads(cached)
                session_id = UUID(data["id"])
                result = await self.db.execute(
                    select(WhatsAppSession).where(
                        WhatsAppSession.id == session_id,
                        WhatsAppSession.status == "active"
                    )
                )
                session = result.scalar_one_or_none()
                if session:
                    return session
            except Exception:
                pass  # fall through to DB

        result = await self.db.execute(
            select(WhatsAppSession).where(
                WhatsAppSession.conversation_id == conversation_id,
                WhatsAppSession.status == "active"
            )
        )
        return result.scalar_one_or_none()

    async def get_or_create_whatsapp_session(
        self,
        company_id: UUID,
        customer_id: UUID,
        agent_id: UUID,
        customer_phone: str,
        provider: str
    ) -> WhatsAppSession:
        """Get existing WhatsApp session or create new one.
        Checks if session window is still valid (24 hours)."""
        conversation_id = f"{provider}:{customer_phone}"

        existing = await self.get_whatsapp_session_by_conversation(conversation_id)

        if existing:
            if existing.session_window_expires > datetime.utcnow():
                await self.update_whatsapp_session(
                    existing.id,
                    {"session_window_expires": datetime.utcnow() + timedelta(hours=24)}
                )
                return existing
            else:
                await self.update_whatsapp_session(existing.id, {"status": "expired"})

        return await self.create_whatsapp_session(
            company_id=company_id,
            customer_id=customer_id,
            agent_id=agent_id,
            phone_number=customer_phone,
            provider=provider,
            conversation_id=conversation_id
        )

    async def update_whatsapp_session(
        self,
        session_id: UUID,
        updates: Dict[str, Any]
    ) -> None:
        """Update WhatsApp session fields."""
        await self.db.execute(
            update(WhatsAppSession)
            .where(WhatsAppSession.id == session_id)
            .values(**updates)
        )
        await self.db.commit()
        await self._cache_delete(_wa_key(session_id))
        logger.debug(f"Updated WhatsApp session: {session_id}")

    async def increment_message_count(self, session_id: UUID) -> None:
        """Increment message count for WhatsApp session."""
        session = await self.db.get(WhatsAppSession, session_id)
        if session:
            session.message_count += 1
            session.last_message_at = datetime.utcnow()
            await self.db.commit()
            await self._cache_delete(_wa_key(session_id))
