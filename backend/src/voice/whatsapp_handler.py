"""
WhatsApp Message Handler for Twilio and Tata Tele Business API.

Handles:
- Incoming WhatsApp messages
- Media messages (images, documents, audio)
- Message status callbacks
- Session management
- Integration with Gemini for AI responses (Text-only)
- Multi-provider support (Twilio & Tata Tele)
"""
import logging
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.voice.models import WhatsAppSession, ConversationHistory
from src.voice.session_manager import SessionManager
from src.voice.agent_loader import AgentContextLoader
from src.voice.conversation_logger import ConversationLogger
from src.voice.gemini_text import GeminiTextServiceFactory
from src.voice.whatsapp_messaging import (
    WhatsAppMessagingFactory, 
    WhatsAppProvider
)

logger = logging.getLogger(__name__)


class WhatsAppHandler:
    """
    Handles WhatsApp message processing using Gemini and multi-provider messaging.
    """
    
    def __init__(self, db: AsyncSession):
        """
        Initialize WhatsApp handler.
        
        Args:
            db: Database session
        """
        self.db = db
        self.session_manager = SessionManager(db)
        self.agent_loader = AgentContextLoader(db)
        self.conversation_logger = ConversationLogger(db)
    
    async def handle_incoming_message(
        self,
        from_number: str,
        to_number: str,
        message_body: str,
        media_url: Optional[str] = None,
        media_type: Optional[str] = None,
        message_sid: Optional[str] = None,
        provider: str = "twilio"
    ) -> str:
        """
        Handle incoming WhatsApp message.
        
        Args:
            from_number: Customer's WhatsApp number
            to_number: Business WhatsApp number
            message_body: Message text content
            media_url: URL to media file if present
            media_type: MIME type of media
            message_sid: Message unique identifier
            provider: 'twilio' or 'tata_tele'
            
        Returns:
            Response message text (for TwiML/logging)
        """
        # Clean phone numbers
        # Twilio sends "whatsapp:+123...", Tata sends "123..."
        customer_phone = from_number.replace("whatsapp:", "").lstrip("+")
        business_phone = to_number.replace("whatsapp:", "").lstrip("+")
        
        logger.info(f"WhatsApp message from {customer_phone} via {provider}: {message_body[:50]}...")
        
        try:
            # 1. Find or create session
            session = await self._get_or_create_session(
                customer_phone=customer_phone,
                business_phone=business_phone,
                provider=provider
            )
            
            if not session:
                logger.error(f"Could not create WhatsApp session for {customer_phone}")
                return "Sorry, we're experiencing technical difficulties. Please try again later."
            
            # 2. Log customer message
            await self.conversation_logger.log_turn(
                company_id=session.company_id,
                customer_id=session.customer_id,
                agent_id=session.agent_id,
                session_id=session.id,
                channel="whatsapp",
                turn_number=await self._get_next_turn_number(session.id),
                speaker="customer",
                content=message_body or "[Media Message]",
                message_type="text" if not media_url else media_type or "media",
                metadata={
                    "message_sid": message_sid,
                    "media_url": media_url,
                    "provider": provider
                }
            )
            
            # 3. Generate AI response using Gemini
            response_text = await self._generate_response(
                session=session,
                customer_message=message_body,
                media_url=media_url
            )
            
            # 4. Log agent response
            await self.conversation_logger.log_turn(
                company_id=session.company_id,
                customer_id=session.customer_id,
                agent_id=session.agent_id,
                session_id=session.id,
                channel="whatsapp",
                turn_number=await self._get_next_turn_number(session.id),
                speaker="agent",
                content=response_text,
                message_type="text"
            )
            
            # 5. Update session timestamp
            await self.session_manager.update_whatsapp_session(
                session.id,
                {"last_message_at": datetime.utcnow()}
            )
            
            # 6. Send response via Messaging Service (if not Twilio TwiML)
            # For Twilio webhook, we can return TwiML for the immediate response.
            # But for Tata or async responses, we use the messaging service.
            if provider == "tata_tele":
                messaging_service = WhatsAppMessagingFactory.get_service(provider)
                await messaging_service.send_message(
                    to=customer_phone,
                    message=response_text,
                    from_number=business_phone
                )
            
            return response_text
            
        except Exception as e:
            logger.error(f"Error handling WhatsApp message: {e}", exc_info=True)
            return "Sorry, I encountered an error processing your message. Please try again."
    
    async def _get_or_create_session(
        self,
        customer_phone: str,
        business_phone: str,
        provider: str
    ) -> Optional[WhatsAppSession]:
        """Get existing or create new WhatsApp session."""
        try:
            # First, find customer assignment using the business number they messaged
            # We need to match the incoming business number to our config
            from src.voice.number_router import NumberRouter
            router = NumberRouter(self.db)
            
            # Try exact match, then with + prefix
            assignment = await router.find_customer_by_number(business_phone)
            if not assignment:
                 assignment = await router.find_customer_by_number(f"+{business_phone}")
            
            if not assignment:
                logger.error(f"No customer assignment found for business number {business_phone}")
                return None
            
            # Get or create WhatsApp session
            session = await self.session_manager.get_or_create_whatsapp_session(
                company_id=assignment.company_id,
                customer_id=assignment.customer_id,
                agent_id=assignment.agent_id,
                customer_phone=customer_phone,
                provider=provider
            )
            
            logger.info(f"Using WhatsApp session: {session.id}")
            return session
            
        except Exception as e:
            logger.error(f"Error getting/creating WhatsApp session: {e}", exc_info=True)
            return None
    
    async def _generate_response(
        self,
        session: WhatsAppSession,
        customer_message: str,
        media_url: Optional[str] = None
    ) -> str:
        """Generate AI response using Gemini Text Service."""
        try:
            # 1. Load agent context
            agent_context = await self.agent_loader.load_agent_for_session(
                agent_id=session.agent_id,
                customer_id=session.customer_id,
                channel="whatsapp"
            )
            
            # 2. Initialize Gemini Service
            gemini_service = GeminiTextServiceFactory.get_service(
                api_key=agent_context.api_key,
                system_instruction=agent_context.system_instruction,
                model="gemini-2.0-flash" # Use fast model for chat
            )
            
            # 3. Prepare context and history
            history = agent_context.conversation_history
            
            current_input = customer_message
            if media_url:
                current_input += f"\n[User sent a media file: {media_url}]"
            
            # 4. Generate response
            result = await gemini_service.generate_response(
                message=current_input,
                conversation_history=history
            )
            
            return result["response"]
            
        except Exception as e:
            logger.error(f"Error generating response: {e}", exc_info=True)
            return "I'm currently unable to process your request. Please try again later."
    
    async def _get_next_turn_number(self, session_id: UUID) -> int:
        """Get next turn number for session."""
        history = await self.conversation_logger.get_session_transcript(session_id)
        return len(history) + 1


async def send_whatsapp_message(
    to: str,
    message: str,
    from_: str,
    media_url: Optional[str] = None
) -> str:
    """
    Send WhatsApp message via Twilio.
    
    Args:
        to: Recipient phone number (with whatsapp: prefix)
        message: Message text
        from_: Sender phone number (with whatsapp: prefix)
        media_url: Optional media URL
        
    Returns:
        Message SID
    """
    # TODO: Integrate with Twilio SDK
    # from twilio.rest import Client
    # client = Client(account_sid, auth_token)
    # 
    # message_params = {
    #     "to": f"whatsapp:{to}",
    #     "from_": f"whatsapp:{from_}",
    #     "body": message
    # }
    # 
    # if media_url:
    #     message_params["media_url"] = [media_url]
    # 
    # msg = client.messages.create(**message_params)
    # return msg.sid
    
    logger.info(f"[MOCK] WhatsApp message to {to}: {message[:50]}...")
    return f"SM_mock_{datetime.utcnow().timestamp()}"
