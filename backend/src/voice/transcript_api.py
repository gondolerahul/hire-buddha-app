"""
API Router for Call and Transcript endpoints.

Provides APIs to:
- Get call transcripts
- Retrieve call history
- Export conversation data
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import List, Dict, Any

from src.common.database import get_db
from src.voice.conversation_logger import ConversationLogger
from src.voice.session_manager import SessionManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/calls", tags=["Calls & Transcripts"])


@router.get("/{call_id}/transcript")
async def get_call_transcript(
    call_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Get full transcript for a voice call.
    
    Args:
        call_id: Voice session UUID
        
    Returns:
        Formatted transcript with turns
    """
    logger = ConversationLogger(db)
    
    try:
        # Get transcript
        turns = await logger.get_session_transcript(call_id)
        
        if not turns:
            raise HTTPException(status_code=404, detail="Call not found or no transcript available")
        
        # Format response
        return {
            "call_id": str(call_id),
            "total_turns": len(turns),
            "transcript": [
                {
                    "turn_number": t.turn_number,
                    "speaker": t.speaker,
                    "content": t.content,
                    "timestamp": t.timestamp.isoformat(),
                    "message_type": t.message_type
                }
                for t in turns
            ]
        }
        
    except Exception as e:
        logger.error(f"Error retrieving transcript: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{call_id}/transcript/text")
async def get_call_transcript_text(
    call_id: UUID,
    include_timestamps: bool = True,
    db: AsyncSession = Depends(get_db)
):
    """
    Get transcript as formatted text.
    
    Args:
        call_id: Voice session UUID
        include_timestamps: Include timestamps in output
        
    Returns:
        Plain text transcript
    """
    conv_logger = ConversationLogger(db)
    
    try:
        transcript_text = await conv_logger.format_transcript(
            call_id,
            include_timestamps=include_timestamps
        )
        
        return {
            "call_id": str(call_id),
            "transcript": transcript_text
        }
        
    except Exception as e:
        logger.error(f"Error formatting transcript: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{call_id}/summary")
async def get_call_summary(
    call_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Get summary statistics for a call.
    
    Args:
        call_id: Voice session UUID
        
    Returns:
        Call summary with stats
    """
    conv_logger = ConversationLogger(db)
    
    try:
        summary = await conv_logger.get_session_summary(call_id)
        
        return {
            "call_id": str(call_id),
            **summary
        }
        
    except Exception as e:
        logger.error(f"Error retrieving summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{call_id}/export")
async def export_call_transcript(
    call_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Export transcript as JSON.
    
    Args:
        call_id: Voice session UUID
        
    Returns:
        JSON-serialized transcript
    """
    conv_logger = ConversationLogger(db)
    
    try:
        transcript_json = await conv_logger.export_transcript_json(call_id)
        
        return {
            "call_id": str(call_id),
            "format": "json",
            "data": transcript_json
        }
        
    except Exception as e:
        logger.error(f"Error exporting transcript: {e}")
        raise HTTPException(status_code=500, detail=str(e))
