"""
Lead Queue Service — atomic queue operations for CRM-driven outbound calling.

Provides transactional enqueue (with dedup), atomic pick (FOR UPDATE SKIP LOCKED),
and status transition methods for the lead lifecycle.
"""
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.ai.lead_queue_model import LeadQueueEntry

logger = logging.getLogger(__name__)


class LeadQueueService:
    """Manages the lead_queue table for CRM-driven outbound calls."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def enqueue_lead(
        self,
        company_id: UUID,
        agent_id: UUID,
        lead_id: str,
        phone: str,
        lead_data: Dict[str, Any],
        ad_source: Optional[str] = None,
        project_id: Optional[str] = None,
        priority: int = 5,
        correlation_id: Optional[str] = None,
    ) -> Optional[LeadQueueEntry]:
        """
        Insert a lead into the queue with deduplication.

        Uses INSERT ... ON CONFLICT DO NOTHING so duplicate leads
        (same company_id + lead_id) are silently ignored.

        Returns the entry if inserted, None if duplicate.
        """
        stmt = pg_insert(LeadQueueEntry).values(
            company_id=company_id,
            agent_id=agent_id,
            lead_id=lead_id,
            phone=phone,
            lead_data=lead_data,
            ad_source=ad_source,
            project_id=project_id,
            priority=priority,
            correlation_id=correlation_id,
            status="pending",
            attempt_count=0,
        ).on_conflict_do_nothing(
            constraint="uq_lead_queue_company_lead"
        ).returning(LeadQueueEntry.__table__.c.id)

        result = await self.db.execute(stmt)
        row = result.first()
        await self.db.commit()

        if row:
            # Fetch the full object
            entry = await self.db.get(LeadQueueEntry, row.id)
            logger.info(
                f"[LeadQueue] Enqueued lead {lead_id} for company {company_id} "
                f"(priority={priority}, phone={phone})"
            )
            return entry
        else:
            logger.info(f"[LeadQueue] Duplicate lead {lead_id} for company {company_id} — skipped")
            return None

    async def pick_next_lead(self, company_id: Optional[UUID] = None) -> Optional[LeadQueueEntry]:
        """
        Atomically pick the next pending lead using FOR UPDATE SKIP LOCKED.

        This prevents multiple workers from picking the same lead.
        Transitions status from 'pending' to 'queued'.

        Args:
            company_id: Optional filter by company. If None, picks across all companies.

        Returns:
            LeadQueueEntry or None if no pending leads.
        """
        # Build raw SQL for FOR UPDATE SKIP LOCKED (SQLAlchemy Core doesn't
        # support SKIP LOCKED directly in all versions)
        where_clause = "status = 'pending'"
        params: Dict[str, Any] = {}
        if company_id:
            where_clause += " AND company_id = :company_id"
            params["company_id"] = str(company_id)

        pick_sql = text(f"""
            UPDATE lead_queue
            SET status = 'queued', updated_at = NOW(), attempt_count = attempt_count + 1
            WHERE id = (
                SELECT id FROM lead_queue
                WHERE {where_clause}
                ORDER BY priority ASC, created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id
        """)

        result = await self.db.execute(pick_sql, params)
        row = result.first()
        await self.db.commit()

        if not row:
            return None

        entry = await self.db.get(LeadQueueEntry, row.id)
        logger.info(
            f"[LeadQueue] Picked lead {entry.lead_id} (attempt {entry.attempt_count}/{entry.max_attempts})"
        )
        return entry

    async def mark_calling(
        self, entry_id: UUID, voice_session_id: UUID
    ) -> None:
        """Transition a queued lead to 'calling' and link the voice session."""
        await self.db.execute(
            update(LeadQueueEntry)
            .where(LeadQueueEntry.id == entry_id)
            .values(
                status="calling",
                voice_session_id=voice_session_id,
                updated_at=datetime.utcnow(),
            )
        )
        await self.db.commit()
        logger.info(f"[LeadQueue] Lead {entry_id} → calling (session={voice_session_id})")

    async def mark_completed(
        self, entry_id: UUID, call_outcome: Dict[str, Any]
    ) -> None:
        """Transition to 'completed' with the call result."""
        await self.db.execute(
            update(LeadQueueEntry)
            .where(LeadQueueEntry.id == entry_id)
            .values(
                status="completed",
                call_outcome=call_outcome,
                processed_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )
        await self.db.commit()
        logger.info(f"[LeadQueue] Lead {entry_id} → completed")

    async def mark_failed(self, entry_id: UUID, error: str) -> None:
        """
        Handle a failed call attempt.

        If retries remain (attempt_count < max_attempts), resets to 'pending'
        for retry. Otherwise, transitions to 'failed'.
        """
        entry = await self.db.get(LeadQueueEntry, entry_id)
        if not entry:
            logger.warning(f"[LeadQueue] Entry {entry_id} not found for mark_failed")
            return

        if entry.attempt_count < entry.max_attempts:
            new_status = "pending"
            logger.info(
                f"[LeadQueue] Lead {entry_id} failed (attempt {entry.attempt_count}/{entry.max_attempts}), "
                f"retrying..."
            )
        else:
            new_status = "failed"
            logger.warning(
                f"[LeadQueue] Lead {entry_id} exhausted all {entry.max_attempts} attempts — marking failed"
            )

        await self.db.execute(
            update(LeadQueueEntry)
            .where(LeadQueueEntry.id == entry_id)
            .values(
                status=new_status,
                last_error=error,
                processed_at=datetime.utcnow() if new_status == "failed" else None,
                updated_at=datetime.utcnow(),
            )
        )
        await self.db.commit()

    async def get_by_voice_session(self, voice_session_id: UUID) -> Optional[LeadQueueEntry]:
        """Find a lead queue entry by its linked voice session ID."""
        result = await self.db.execute(
            select(LeadQueueEntry).where(
                LeadQueueEntry.voice_session_id == voice_session_id
            )
        )
        return result.scalar_one_or_none()

    async def get_pending_count(self, company_id: Optional[UUID] = None) -> int:
        """Count pending leads (for monitoring/throttling)."""
        query = select(LeadQueueEntry).where(LeadQueueEntry.status == "pending")
        if company_id:
            query = query.where(LeadQueueEntry.company_id == company_id)
        result = await self.db.execute(query)
        return len(result.scalars().all())
