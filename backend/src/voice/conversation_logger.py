"""
Conversation Logger for voice and WhatsApp sessions.

Logs conversation turns to database for:
- Transcripts
- Analytics
- Audit trail
- Context retrieval
"""
import logging
from datetime import datetime
from uuid import UUID
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from src.voice.models import ConversationHistory

logger = logging.getLogger(__name__)


class ConversationLogger:
    """
    Manages conversation logging to database.
    
    Creates structured logs of all interactions for:
    - Voice calls
    - WhatsApp messages
    """
    
    def __init__(self, db: AsyncSession):
        """
        Initialize conversation logger.
        
        Args:
            db: Database session
        """
        self.db = db
    
    async def log_turn(
        self,
        company_id: UUID,
        customer_id: UUID,
        agent_id: UUID,
        session_id: UUID,
        channel: str,
        turn_number: int,
        speaker: str,
        content: str,
        message_type: str = "text",
        audio_duration_ms: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ConversationHistory:
        """
        Log a single conversation turn.
        
        Args:
            company_id: Company UUID
            customer_id: Customer UUID
            agent_id: Agent UUID
            session_id: Session UUID (voice_sessions.id or whatsapp_sessions.id)
            channel: 'voice' or 'whatsapp'
            turn_number: Sequential turn number
            speaker: 'customer' or 'agent'
            content: Text content of the turn
            message_type: 'text', 'audio', 'image', etc.
            audio_duration_ms: Audio duration if applicable
            metadata: Additional metadata
            
        Returns:
            Created ConversationHistory object
        """
        turn = ConversationHistory(
            company_id=company_id,
            customer_id=customer_id,
            agent_id=agent_id,
            session_id=session_id,
            channel=channel,
            turn_number=turn_number,
            speaker=speaker,
            message_type=message_type,
            content=content,
            audio_duration_ms=audio_duration_ms,
            timestamp=datetime.utcnow(),
            message_metadata=metadata or {}
        )
        
        self.db.add(turn)
        await self.db.commit()
        await self.db.refresh(turn)
        
        logger.debug(f"Logged {channel} turn #{turn_number} by {speaker}")
        return turn
    
    async def get_session_transcript(
        self,
        session_id: UUID,
        limit: Optional[int] = None
    ) -> List[ConversationHistory]:
        """
        Get full transcript for a session.
        
        Args:
            session_id: Session UUID
            limit: Maximum turns to retrieve (default: all)
            
        Returns:
            List of ConversationHistory turns, ordered by turn_number
        """
        query = select(ConversationHistory).where(
            ConversationHistory.session_id == session_id
        ).order_by(ConversationHistory.turn_number.asc())
        
        if limit:
            query = query.limit(limit)
        
        result = await self.db.execute(query)
        turns = result.scalars().all()
        
        logger.info(f"Retrieved {len(turns)} turns for session {session_id}")
        return turns
    
    async def get_customer_history(
        self,
        customer_id: UUID,
        agent_id: UUID,
        channel: str,
        limit: int = 20
    ) -> List[ConversationHistory]:
        """
        Get recent conversation history for a customer with an agent.
        
        Used to load context for new sessions.
        
        Args:
            customer_id: Customer UUID
            agent_id: Agent UUID
            channel: 'voice' or 'whatsapp'
            limit: Maximum turns to retrieve
            
        Returns:
            List of recent conversation turns
        """
        result = await self.db.execute(
            select(ConversationHistory)
            .where(
                and_(
                    ConversationHistory.customer_id == customer_id,
                    ConversationHistory.agent_id == agent_id,
                    ConversationHistory.channel == channel
                )
            )
            .order_by(ConversationHistory.timestamp.desc())
            .limit(limit)
        )
        
        turns = result.scalars().all()
        
        # Return in chronological order (oldest first)
        return list(reversed(turns))
    
    async def get_session_summary(
        self,
        session_id: UUID
    ) -> Dict[str, Any]:
        """
        Get summary statistics for a session.
        
        Args:
            session_id: Session UUID
            
        Returns:
            Dict with summary stats
        """
        turns = await self.get_session_transcript(session_id)
        
        if not turns:
            return {
                "total_turns": 0,
                "customer_turns": 0,
                "agent_turns": 0,
                "duration_ms": 0,
                "start_time": None,
                "end_time": None
            }
        
        customer_turns = [t for t in turns if t.speaker == "customer"]
        agent_turns = [t for t in turns if t.speaker == "agent"]
        
        # Calculate total audio duration
        total_duration = sum(
            t.audio_duration_ms for t in turns
            if t.audio_duration_ms
        )
        
        return {
            "total_turns": len(turns),
            "customer_turns": len(customer_turns),
            "agent_turns": len(agent_turns),
            "duration_ms": total_duration,
            "start_time": turns[0].timestamp,
            "end_time": turns[-1].timestamp
        }
    
    async def format_transcript(
        self,
        session_id: UUID,
        include_timestamps: bool = True
    ) -> str:
        """
        Format session transcript as readable text.
        
        Args:
            session_id: Session UUID
            include_timestamps: Include timestamps in output
            
        Returns:
            Formatted transcript string
        """
        turns = await self.get_session_transcript(session_id)
        
        if not turns:
            return "No conversation history."
        
        lines = []
        
        for turn in turns:
            speaker_label = "Customer" if turn.speaker == "customer" else "Agent"
            
            if include_timestamps:
                timestamp = turn.timestamp.strftime("%H:%M:%S")
                line = f"[{timestamp}] {speaker_label}: {turn.content}"
            else:
                line = f"{speaker_label}: {turn.content}"
            
            lines.append(line)
        
        return "\n".join(lines)
    
    async def export_transcript_json(
        self,
        session_id: UUID
    ) -> List[Dict[str, Any]]:
        """
        Export transcript as JSON-serializable list.
        
        Args:
            session_id: Session UUID
            
        Returns:
            List of turn dicts
        """
        turns = await self.get_session_transcript(session_id)
        
        return [
            {
                "turn_number": t.turn_number,
                "speaker": t.speaker,
                "content": t.content,
                "message_type": t.message_type,
                "audio_duration_ms": t.audio_duration_ms,
                "timestamp": t.timestamp.isoformat(),
                "metadata": t.message_metadata
            }
            for t in turns
        ]
