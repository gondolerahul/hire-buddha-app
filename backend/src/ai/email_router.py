"""
Email Connection CRUD API Router.

Endpoints for managing AI agent email connections (IMAP/SMTP).
"""
import logging
import imaplib
from datetime import datetime
from uuid import UUID
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.common.database import get_db
from src.auth.models import User
from src.ai.email_models import EmailConnection
from src.common.security import encrypt_api_key, decrypt_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/email", tags=["Email Connections"])


# --- Pydantic Schemas ---

class EmailConnectionCreate(BaseModel):
    email_address: str
    app_password: str
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    provider_type: str = "gmail"  # gmail, outlook, custom
    folder_prefix: Optional[str] = None


class EmailConnectionResponse(BaseModel):
    id: str
    company_id: str
    email_address: str
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    provider_type: str
    folder_prefix: Optional[str]
    is_active: bool
    last_connected_at: Optional[str]
    status: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class EmailValidateResponse(BaseModel):
    valid: bool
    message: str


# --- Provider Defaults ---

PROVIDER_DEFAULTS = {
    "gmail": {
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "folder_prefix": "[Gmail]/",
        "help_url": "https://myaccount.google.com/apppasswords"
    },
    "outlook": {
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "smtp_host": "smtp.office365.com",
        "smtp_port": 587,
        "folder_prefix": "",
        "help_url": "https://support.microsoft.com/en-us/account-billing/manage-app-passwords-for-two-step-verification"
    }
}


# --- Endpoints ---

@router.get("/provider-defaults")
async def get_provider_defaults():
    """Get default IMAP/SMTP settings for known email providers."""
    return PROVIDER_DEFAULTS


@router.post("/connections", response_model=EmailConnectionResponse)
async def create_email_connection(
    data: EmailConnectionCreate,
    db: AsyncSession = Depends(get_db),
    # current_user will be injected by auth middleware in production
    company_id: Optional[str] = None
):
    """Create a new email connection with encrypted credentials."""
    # For now, use a placeholder company_id (auth middleware will provide real one)
    if not company_id:
        # In production, this comes from the authenticated user
        raise HTTPException(status_code=400, detail="company_id is required")
    
    try:
        company_uuid = UUID(company_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid company_id format")
    
    # Check if connection already exists for this email
    existing = await db.execute(
        select(EmailConnection).where(
            EmailConnection.company_id == company_uuid,
            EmailConnection.email_address == data.email_address
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"Email connection for {data.email_address} already exists"
        )
    
    # Auto-detect provider defaults
    if data.provider_type in PROVIDER_DEFAULTS:
        defaults = PROVIDER_DEFAULTS[data.provider_type]
        if data.imap_host == "imap.gmail.com" and data.provider_type != "gmail":
            data.imap_host = defaults["imap_host"]
            data.imap_port = defaults["imap_port"]
            data.smtp_host = defaults["smtp_host"]
            data.smtp_port = defaults["smtp_port"]
        if not data.folder_prefix:
            data.folder_prefix = defaults.get("folder_prefix")
    
    # Encrypt the app password
    encrypted_password = encrypt_api_key(data.app_password)
    
    connection = EmailConnection(
        company_id=company_uuid,
        email_address=data.email_address,
        encrypted_app_password=encrypted_password,
        imap_host=data.imap_host,
        imap_port=data.imap_port,
        smtp_host=data.smtp_host,
        smtp_port=data.smtp_port,
        provider_type=data.provider_type,
        folder_prefix=data.folder_prefix,
        status="pending_validation"
    )
    
    db.add(connection)
    await db.commit()
    await db.refresh(connection)
    
    return _to_response(connection)


@router.get("/connections")
async def list_email_connections(
    company_id: str,
    db: AsyncSession = Depends(get_db)
):
    """List all email connections for a company."""
    try:
        company_uuid = UUID(company_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid company_id format")
    
    result = await db.execute(
        select(EmailConnection).where(
            EmailConnection.company_id == company_uuid
        )
    )
    connections = result.scalars().all()
    return [_to_response(c) for c in connections]


@router.delete("/connections/{connection_id}")
async def delete_email_connection(
    connection_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Delete an email connection."""
    try:
        conn_uuid = UUID(connection_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid connection_id format")
    
    result = await db.execute(
        select(EmailConnection).where(EmailConnection.id == conn_uuid)
    )
    connection = result.scalar_one_or_none()
    
    if not connection:
        raise HTTPException(status_code=404, detail="Email connection not found")
    
    await db.delete(connection)
    await db.commit()
    
    return {"status": "deleted", "id": connection_id}


@router.post("/connections/{connection_id}/validate", response_model=EmailValidateResponse)
async def validate_email_connection(
    connection_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Validate email connection by running an IMAP NOOP command.
    This tests the credentials without performing any mail operations.
    """
    try:
        conn_uuid = UUID(connection_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid connection_id format")
    
    result = await db.execute(
        select(EmailConnection).where(EmailConnection.id == conn_uuid)
    )
    connection = result.scalar_one_or_none()
    
    if not connection:
        raise HTTPException(status_code=404, detail="Email connection not found")
    
    try:
        # Decrypt password
        password = decrypt_api_key(connection.encrypted_app_password)
        
        # Test IMAP connection with NOOP
        imap = imaplib.IMAP4_SSL(connection.imap_host, connection.imap_port)
        imap.login(connection.email_address, password)
        status, _ = imap.noop()
        imap.logout()
        
        if status == "OK":
            # Update connection status
            connection.status = "active"
            connection.is_active = True
            connection.last_connected_at = datetime.utcnow()
            await db.commit()
            
            return EmailValidateResponse(
                valid=True,
                message="Connection validated successfully. IMAP NOOP returned OK."
            )
        else:
            connection.status = "auth_failed"
            connection.is_active = False
            await db.commit()
            
            return EmailValidateResponse(
                valid=False,
                message=f"IMAP NOOP returned unexpected status: {status}"
            )
    
    except imaplib.IMAP4.error as e:
        connection.status = "auth_failed"
        connection.is_active = False
        await db.commit()
        
        return EmailValidateResponse(
            valid=False,
            message=f"IMAP authentication failed: {str(e)}. Check your App Password."
        )
    except Exception as e:
        logger.error(f"Email validation error: {e}", exc_info=True)
        return EmailValidateResponse(
            valid=False,
            message=f"Connection failed: {str(e)}"
        )


def _to_response(connection: EmailConnection) -> dict:
    """Convert EmailConnection model to response dict."""
    return {
        "id": str(connection.id),
        "company_id": str(connection.company_id),
        "email_address": connection.email_address,
        "imap_host": connection.imap_host,
        "imap_port": connection.imap_port,
        "smtp_host": connection.smtp_host,
        "smtp_port": connection.smtp_port,
        "provider_type": connection.provider_type,
        "folder_prefix": connection.folder_prefix,
        "is_active": connection.is_active,
        "last_connected_at": connection.last_connected_at.isoformat() if connection.last_connected_at else None,
        "status": connection.status,
        "created_at": connection.created_at.isoformat() if connection.created_at else None,
        "updated_at": connection.updated_at.isoformat() if connection.updated_at else None,
    }
