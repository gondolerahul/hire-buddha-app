"""
WhatsApp Messaging Service for sending outbound messages.

Supports:
- Twilio WhatsApp Business API
- Tata Tele Business WhatsApp API (for Indian customers)

Provides unified interface for:
- Sending text messages
- Sending media messages
- Template messages (HSM)
- Message status tracking
"""
import logging
import os
import httpx
import base64
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import UUID
from enum import Enum

logger = logging.getLogger(__name__)


class WhatsAppProvider(str, Enum):
    """Supported WhatsApp providers."""
    TWILIO = "twilio"
    TATA_TELE = "tata_tele"


class MessageType(str, Enum):
    """WhatsApp message types."""
    TEXT = "text"
    TEMPLATE = "template"
    IMAGE = "image"
    DOCUMENT = "document"
    AUDIO = "audio"
    VIDEO = "video"


class WhatsAppMessagingService:
    """
    Unified WhatsApp messaging service supporting multiple providers.
    
    Provides a consistent interface for sending messages via
    Twilio or Tata Tele WhatsApp Business API.
    """
    
    def __init__(
        self,
        provider: WhatsAppProvider,
        credentials: Optional[Dict[str, str]] = None
    ):
        """
        Initialize messaging service for a specific provider.
        
        Args:
            provider: WhatsApp provider (twilio or tata_tele)
            credentials: Provider-specific credentials dict
        """
        self.provider = provider
        self.credentials = credentials or {}
        
        # Load credentials from environment if not provided
        if provider == WhatsAppProvider.TWILIO:
            self._init_twilio()
        elif provider == WhatsAppProvider.TATA_TELE:
            self._init_tata_tele()
        
        logger.info(f"Initialized WhatsAppMessagingService for {provider}")
    
    def _init_twilio(self):
        """Initialize Twilio credentials from Integration Registry."""
        self.account_sid = self.credentials.get("account_sid")
        self.auth_token = self.credentials.get("auth_token")
        self.from_number = self.credentials.get("from_number")
        
        if not all([self.account_sid, self.auth_token]):
            logger.warning(
                "Twilio credentials not fully configured. "
                "Register a 'twilio' integration in the Integration Registry "
                "with account_sid in service_metadata and auth_token as api_key."
            )
        
        self.base_url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}"
    
    def _init_tata_tele(self):
        """Initialize Tata Tele credentials from Integration Registry."""
        self.api_key = self.credentials.get("api_key")
        self.api_secret = self.credentials.get("api_secret")
        self.business_id = self.credentials.get("business_id")
        self.from_number = self.credentials.get("from_number")
        
        if not all([self.api_key, self.api_secret]):
            logger.warning(
                "Tata Tele credentials not fully configured. "
                "Register a 'tata_tele' integration in the Integration Registry "
                "with api_key, api_secret, business_id in service_metadata."
            )
        
        # Tata Tele WhatsApp API base URL (from service_metadata or default)
        self.base_url = self.credentials.get(
            "api_url",
            "https://api-smartflo.tatateleservices.com"
        )
    
    async def send_message(
        self,
        to: str,
        message: str,
        from_number: Optional[str] = None,
        media_url: Optional[str] = None,
        media_type: Optional[MessageType] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Send a WhatsApp message.
        
        Args:
            to: Recipient phone number (E.164 format, e.g., +919876543210)
            message: Message text
            from_number: Sender number (optional, uses default)
            media_url: URL to media file for media messages
            media_type: Type of media being sent
            metadata: Additional metadata for tracking
            
        Returns:
            Dict with 'success', 'message_id', 'provider', 'error' (if any)
        """
        from_number = from_number or self.from_number
        
        if self.provider == WhatsAppProvider.TWILIO:
            return await self._send_twilio_message(
                to=to,
                message=message,
                from_number=from_number,
                media_url=media_url
            )
        elif self.provider == WhatsAppProvider.TATA_TELE:
            return await self._send_tata_message(
                to=to,
                message=message,
                from_number=from_number,
                media_url=media_url,
                media_type=media_type
            )
        
        return {
            "success": False,
            "error": f"Unsupported provider: {self.provider}"
        }
    
    async def send_template_message(
        self,
        to: str,
        template_id: str,
        template_params: List[str],
        from_number: Optional[str] = None,
        language: str = "en"
    ) -> Dict[str, Any]:
        """
        Send a template message (HSM) for initiating conversations.
        
        Template messages are pre-approved messages that can be sent
        outside the 24-hour session window.
        
        Args:
            to: Recipient phone number
            template_id: Approved template SID/ID
            template_params: List of parameter values for template variables
            from_number: Sender number
            language: Template language code
            
        Returns:
            Dict with 'success', 'message_id', 'error'
        """
        from_number = from_number or self.from_number
        
        if self.provider == WhatsAppProvider.TWILIO:
            return await self._send_twilio_template(
                to=to,
                template_id=template_id,
                template_params=template_params,
                from_number=from_number
            )
        elif self.provider == WhatsAppProvider.TATA_TELE:
            return await self._send_tata_template(
                to=to,
                template_id=template_id,
                template_params=template_params,
                from_number=from_number,
                language=language
            )
        
        return {"success": False, "error": f"Unsupported provider: {self.provider}"}
    
    # ========== Twilio Implementation ==========
    
    async def _send_twilio_message(
        self,
        to: str,
        message: str,
        from_number: str,
        media_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send message via Twilio WhatsApp API."""
        try:
            # Format numbers for Twilio
            to_formatted = f"whatsapp:{to}" if not to.startswith("whatsapp:") else to
            from_formatted = f"whatsapp:{from_number}" if not from_number.startswith("whatsapp:") else from_number
            
            # Build request
            url = f"{self.base_url}/Messages.json"
            
            data = {
                "To": to_formatted,
                "From": from_formatted,
                "Body": message
            }
            
            if media_url:
                data["MediaUrl"] = media_url
            
            # Make request
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    data=data,
                    auth=(self.account_sid, self.auth_token),
                    timeout=30.0
                )
            
            if response.status_code in [200, 201]:
                result = response.json()
                logger.info(f"Twilio message sent: {result.get('sid')}")
                return {
                    "success": True,
                    "message_id": result.get("sid"),
                    "provider": "twilio",
                    "status": result.get("status")
                }
            else:
                error = response.json() if response.text else {"message": response.text}
                logger.error(f"Twilio error: {error}")
                return {
                    "success": False,
                    "error": error.get("message", str(error)),
                    "provider": "twilio"
                }
                
        except Exception as e:
            logger.error(f"Error sending Twilio message: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "provider": "twilio"
            }
    
    async def _send_twilio_template(
        self,
        to: str,
        template_id: str,
        template_params: List[str],
        from_number: str
    ) -> Dict[str, Any]:
        """Send template message via Twilio."""
        try:
            to_formatted = f"whatsapp:{to}" if not to.startswith("whatsapp:") else to
            from_formatted = f"whatsapp:{from_number}" if not from_number.startswith("whatsapp:") else from_number
            
            url = f"{self.base_url}/Messages.json"
            
            # Twilio uses ContentSid for templates
            data = {
                "To": to_formatted,
                "From": from_formatted,
                "ContentSid": template_id
            }
            
            # Add template variables (Twilio uses ContentVariables as JSON)
            if template_params:
                import json
                variables = {str(i+1): v for i, v in enumerate(template_params)}
                data["ContentVariables"] = json.dumps(variables)
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    data=data,
                    auth=(self.account_sid, self.auth_token),
                    timeout=30.0
                )
            
            if response.status_code in [200, 201]:
                result = response.json()
                return {
                    "success": True,
                    "message_id": result.get("sid"),
                    "provider": "twilio"
                }
            else:
                error = response.json() if response.text else {}
                return {
                    "success": False,
                    "error": error.get("message", response.text),
                    "provider": "twilio"
                }
                
        except Exception as e:
            logger.error(f"Error sending Twilio template: {e}")
            return {"success": False, "error": str(e), "provider": "twilio"}
    
    # ========== Tata Tele Implementation ==========
    
    async def _send_tata_message(
        self,
        to: str,
        message: str,
        from_number: str,
        media_url: Optional[str] = None,
        media_type: Optional[MessageType] = None
    ) -> Dict[str, Any]:
        """
        Send message via Tata Tele WhatsApp Business API.
        
        Tata Tele uses Meta's Cloud API format.
        """
        try:
            # Clean phone number (remove + prefix)
            to_clean = to.lstrip("+")
            
            # Build authorization header
            auth_header = base64.b64encode(
                f"{self.api_key}:{self.api_secret}".encode()
            ).decode()
            
            headers = {
                "Authorization": f"Basic {auth_header}",
                "Content-Type": "application/json"
            }
            
            # Build message payload based on type
            if media_url and media_type:
                payload = self._build_tata_media_payload(
                    to_clean, media_url, media_type, message
                )
            else:
                payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": to_clean,
                    "type": "text",
                    "text": {
                        "preview_url": True,
                        "body": message
                    }
                }
            
            # API endpoint
            url = f"{self.base_url}/v1/messages"
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=30.0
                )
            
            if response.status_code in [200, 201]:
                result = response.json()
                message_id = None
                if "messages" in result and result["messages"]:
                    message_id = result["messages"][0].get("id")
                
                logger.info(f"Tata Tele message sent: {message_id}")
                return {
                    "success": True,
                    "message_id": message_id,
                    "provider": "tata_tele",
                    "response": result
                }
            else:
                error = response.json() if response.text else {}
                logger.error(f"Tata Tele error: {error}")
                return {
                    "success": False,
                    "error": error.get("error", {}).get("message", str(error)),
                    "provider": "tata_tele"
                }
                
        except Exception as e:
            logger.error(f"Error sending Tata Tele message: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "provider": "tata_tele"
            }
    
    def _build_tata_media_payload(
        self,
        to: str,
        media_url: str,
        media_type: MessageType,
        caption: Optional[str] = None
    ) -> Dict[str, Any]:
        """Build Tata Tele media message payload."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": media_type.value
        }
        
        media_obj = {"link": media_url}
        if caption:
            media_obj["caption"] = caption
        
        payload[media_type.value] = media_obj
        return payload
    
    async def _send_tata_template(
        self,
        to: str,
        template_id: str,
        template_params: List[str],
        from_number: str,
        language: str = "en"
    ) -> Dict[str, Any]:
        """
        Send template message via Tata Tele.
        
        Uses Meta's Cloud API template format.
        """
        try:
            to_clean = to.lstrip("+")
            
            auth_header = base64.b64encode(
                f"{self.api_key}:{self.api_secret}".encode()
            ).decode()
            
            headers = {
                "Authorization": f"Basic {auth_header}",
                "Content-Type": "application/json"
            }
            
            # Build template components
            components = []
            if template_params:
                body_params = [{"type": "text", "text": p} for p in template_params]
                components.append({
                    "type": "body",
                    "parameters": body_params
                })
            
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to_clean,
                "type": "template",
                "template": {
                    "name": template_id,
                    "language": {
                        "code": language
                    }
                }
            }
            
            if components:
                payload["template"]["components"] = components
            
            url = f"{self.base_url}/v1/messages"
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=30.0
                )
            
            if response.status_code in [200, 201]:
                result = response.json()
                message_id = None
                if "messages" in result and result["messages"]:
                    message_id = result["messages"][0].get("id")
                
                return {
                    "success": True,
                    "message_id": message_id,
                    "provider": "tata_tele"
                }
            else:
                error = response.json() if response.text else {}
                return {
                    "success": False,
                    "error": error.get("error", {}).get("message", str(error)),
                    "provider": "tata_tele"
                }
                
        except Exception as e:
            logger.error(f"Error sending Tata Tele template: {e}")
            return {"success": False, "error": str(e), "provider": "tata_tele"}


class WhatsAppMessagingFactory:
    """Factory for getting provider-specific messaging service."""
    
    _instances: Dict[str, WhatsAppMessagingService] = {}
    
    @classmethod
    def get_service(
        cls,
        provider: str,
        credentials: Optional[Dict[str, str]] = None
    ) -> WhatsAppMessagingService:
        """
        Get messaging service for a provider.
        
        Args:
            provider: Provider name (twilio, tata_tele)
            credentials: Optional provider credentials
            
        Returns:
            WhatsAppMessagingService instance
        """
        provider_enum = WhatsAppProvider(provider)
        cache_key = provider
        
        if cache_key not in cls._instances:
            cls._instances[cache_key] = WhatsAppMessagingService(
                provider=provider_enum,
                credentials=credentials
            )
        
        return cls._instances[cache_key]
    
    @classmethod
    def clear_cache(cls):
        """Clear service cache."""
        cls._instances.clear()


# Convenience function for quick message sending
async def send_whatsapp_message(
    to: str,
    message: str,
    provider: str = "twilio",
    from_number: Optional[str] = None,
    media_url: Optional[str] = None,
    credentials: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Quick function to send a WhatsApp message.
    
    Args:
        to: Recipient phone number
        message: Message text
        provider: Provider name (twilio or tata_tele)
        from_number: Optional sender number
        media_url: Optional media URL
        credentials: Optional provider credentials
        
    Returns:
        Dict with 'success', 'message_id', 'error'
    """
    service = WhatsAppMessagingFactory.get_service(provider, credentials)
    return await service.send_message(
        to=to,
        message=message,
        from_number=from_number,
        media_url=media_url
    )


async def send_whatsapp_template(
    to: str,
    template_id: str,
    template_params: List[str],
    provider: str = "twilio",
    from_number: Optional[str] = None,
    language: str = "en",
    credentials: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Quick function to send a WhatsApp template message.
    
    Args:
        to: Recipient phone number
        template_id: Approved template ID
        template_params: Template variable values
        provider: Provider name
        from_number: Optional sender number
        language: Template language code
        credentials: Optional provider credentials
        
    Returns:
        Dict with 'success', 'message_id', 'error'
    """
    service = WhatsAppMessagingFactory.get_service(provider, credentials)
    return await service.send_template_message(
        to=to,
        template_id=template_id,
        template_params=template_params,
        from_number=from_number,
        language=language
    )
