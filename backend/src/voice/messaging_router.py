"""
Messaging Router for outbound WhatsApp messages.

Provides API endpoints for sending messages via configured providers.
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from src.common.database import get_db
from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.voice.whatsapp_messaging import (
    WhatsAppMessagingFactory, 
    WhatsAppProvider, 
    MessageType
)
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/messaging", tags=["Messaging"])


class SendMessageRequest(BaseModel):
    to: str
    message: str
    provider: str = "twilio"  # twilio or tata_tele
    from_number: Optional[str] = None
    media_url: Optional[str] = None
    media_type: Optional[str] = "image"


class SendTemplateRequest(BaseModel):
    to: str
    template_id: str
    parameters: List[str]
    provider: str = "twilio"
    from_number: Optional[str] = None
    language: str = "en"


@router.post("/send")
async def send_whatsapp_message(
    request: SendMessageRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Send an outbound WhatsApp message.
    
    This can be used for proactive notifications or manual agent responses.
    """
    try:
        # Validate provider
        if request.provider not in ["twilio", "tata_tele"]:
            raise HTTPException(status_code=400, detail="Invalid provider")
        
        # Determine sender number if not provided
        # Use company's default number for provider (TODO: lookup from DB)
        # For now, rely on env vars in service or explicit input
        
        # Send message
        service = WhatsAppMessagingFactory.get_service(request.provider)
        
        # Execute options
        media_type_enum = None
        if request.media_url and request.media_type:
            try:
                media_type_enum = MessageType(request.media_type)
            except ValueError:
                pass
        
        result = await service.send_message(
            to=request.to,
            message=request.message,
            from_number=request.from_number,
            media_url=request.media_url,
            media_type=media_type_enum
        )
        
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error"))
            
        return {
            "success": True,
            "message_id": result.get("message_id"),
            "provider": request.provider
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send-template")
async def send_whatsapp_template(
    request: SendTemplateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Send a WhatsApp template message (HSM).
    
    Required for initiating conversations outside the 24-hour window.
    """
    try:
        service = WhatsAppMessagingFactory.get_service(request.provider)
        
        result = await service.send_template_message(
            to=request.to,
            template_id=request.template_id,
            template_params=request.parameters,
            from_number=request.from_number,
            language=request.language
        )
        
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error"))
            
        return {
            "success": True,
            "message_id": result.get("message_id"),
            "provider": request.provider
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
