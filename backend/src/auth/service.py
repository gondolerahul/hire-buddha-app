from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status
from src.auth.models import User, Company, RefreshToken
from src.auth.schemas import UserCreate, UserLogin
from src.common.security import get_password_hash, verify_password, create_access_token
from src.common.email import email_service
from datetime import datetime, timedelta
import uuid
import secrets
from sqlalchemy import or_

from src.auth.schemas import UserCreate, UserLogin, UserCreateAdmin
import logging

logger = logging.getLogger(__name__)


async def _provision_new_tenant(db: AsyncSession, company: Company):
    """Create CreditWallet for a newly-created tenant company.

    IMPORTANT: This runs inside an active transaction (post-flush, pre-commit).
    We must NOT execute queries to other tables (like BillingConfig) here because
    asyncpg doesn't support concurrent operations on the same connection.

    The caller is expected to set company.default_daily_credits before calling this.
    """
    try:
        from src.billing.billing_models import CreditWallet
        from decimal import Decimal

        # Read default from company (set by caller from BillingConfig)
        default_daily = Decimal("0")  # no fallback — must come from BillingConfig
        if company.default_daily_credits:
            try:
                default_daily = Decimal(str(company.default_daily_credits))
            except Exception:
                pass

        wallet = CreditWallet(
            company_id=company.id,
            daily_credits=default_daily,
        )
        db.add(wallet)
        # Don't flush here — let the caller's commit handle it
        logger.info(f"Queued CreditWallet for company {company.id} with {default_daily} daily credits")
    except ImportError:
        logger.warning("Billing module not available — skipping CreditWallet creation")
    except Exception as e:
        logger.warning(f"Failed to provision CreditWallet for company {company.id}: {e}")

async def create_user_as_admin(db: AsyncSession, user_in: UserCreateAdmin, creator: User):
    # Permission Checks
    if creator.role == "tenant_admin":
        if user_in.company_id != creator.company_id:
            raise HTTPException(status_code=403, detail="Can only create users in your own company")
        if user_in.role not in ["tenant_admin", "tenant_user"]:
            raise HTTPException(status_code=403, detail="Invalid role for tenant admin to assign")
    
    elif creator.role == "partner_admin":
        # Get target company to check parent_id
        result = await db.execute(select(Company).where(Company.id == user_in.company_id))
        target_company = result.scalar_one_or_none()
        if not target_company:
            raise HTTPException(status_code=404, detail="Target company not found")
        
        # Partner admin can create for their own company or their tenants
        if target_company.id != creator.company_id and target_company.parent_id != creator.company_id:
            raise HTTPException(status_code=403, detail="Not authorized to create users for this company")
        
        if user_in.role not in ["partner_admin", "partner_user", "tenant_admin", "tenant_user"]:
            raise HTTPException(status_code=403, detail="Invalid role for partner admin to assign")
            
    elif creator.role != "app_admin":
        raise HTTPException(status_code=403, detail="Not authorized to create users")

    # Check if email exists
    result = await db.execute(select(User).filter(User.email == user_in.email))
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create User
    hashed_password = get_password_hash(user_in.password)
    new_user = User(
        email=user_in.email,
        full_name=user_in.full_name,
        hashed_password=hashed_password,
        company_id=user_in.company_id,
        role=user_in.role,
        is_verified=True # Admin created users are pre-verified
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user

async def create_user(db: AsyncSession, user: UserCreate, creator: User = None):
    # Check if user exists
    result = await db.execute(select(User).filter(User.email == user.email))
    existing_user = result.scalars().first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    # For self-registration or direct creation without company context, create a TENANT company
    new_company = Company(
        name=f"{user.full_name}'s Workspace",
        type="TENANT",
        status="active",
        onboarding_status="pending",
        onboarding_metadata={"completed_steps": [], "created_via": "self_registration"}
    )

    # Read default_daily_credits from global BillingConfig BEFORE flush
    try:
        from src.billing.billing_models import BillingConfig
        config_result = await db.execute(
            select(BillingConfig).where(
                BillingConfig.company_id.is_(None),
                BillingConfig.is_active == True
            ).limit(1)
        )
        global_config = config_result.scalar_one_or_none()
        if global_config and global_config.default_daily_credits:
            new_company.default_daily_credits = str(global_config.default_daily_credits)
            logger.info(f"Using BillingConfig default_daily_credits: {global_config.default_daily_credits}")
    except Exception as e:
        logger.warning(f"Could not read BillingConfig for default credits: {e}")

    db.add(new_company)
    await db.flush()

    # Create User
    hashed_password = get_password_hash(user.password)
    new_user = User(
        email=user.email,
        full_name=user.full_name,
        hashed_password=hashed_password,
        company_id=new_company.id,
        role="tenant_admin"
    )
    db.add(new_user)
    await db.flush()

    # Auto-provision CreditWallet with default daily credits
    await _provision_new_tenant(db, new_company)

    await db.commit()
    await db.refresh(new_user)
    
    # NOTE: Verification emails are handled by the background worker (arq).
    # Do NOT call email_service here — it opens a new DB session from 
    # _load_credentials(), which deadlocks the asyncpg connection pool.
    logger.info(f"New tenant registered: {new_user.email} (company: {new_company.id})")
    
    return new_user

async def authenticate_user(db: AsyncSession, login_data: UserLogin):
    result = await db.execute(select(User).filter(User.email == login_data.email))
    user = result.scalars().first()
    if not user:
        return None
    if not verify_password(login_data.password, user.hashed_password):
        return None
    return user

async def create_refresh_token(db: AsyncSession, user_id: uuid.UUID) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(days=7)
    
    refresh_token = RefreshToken(
        user_id=user_id,
        token=token,
        expires_at=expires_at
    )
    db.add(refresh_token)
    await db.commit()
    return token

async def verify_refresh_token(db: AsyncSession, token: str) -> User:
    result = await db.execute(select(RefreshToken).filter(RefreshToken.token == token))
    refresh_token = result.scalars().first()
    
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
        
    if refresh_token.revoked:
        # Security alert: Attempt to use revoked token
        # In a real system, we might revoke all tokens for this user
        raise HTTPException(status_code=401, detail="Token revoked")
        
    if refresh_token.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Token expired")
        
    # Get user
    result = await db.execute(select(User).filter(User.id == refresh_token.user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
        
    return user

async def rotate_refresh_token(db: AsyncSession, old_token: str) -> str:
    # Verify old token (and get user)
    # We do this manually to get the token object too
    result = await db.execute(select(RefreshToken).filter(RefreshToken.token == old_token))
    refresh_token = result.scalars().first()
    
    if not refresh_token or refresh_token.revoked or refresh_token.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    
    # Revoke old token
    refresh_token.revoked = True
    
    # Create new token
    new_token = await create_refresh_token(db, refresh_token.user_id)
    
    await db.commit()
    return new_token

async def get_or_create_oauth_user(db: AsyncSession, email: str, full_name: str) -> User:
    result = await db.execute(select(User).filter(User.email == email))
    user = result.scalars().first()
    
    if user:
        return user
        
    # Create new user
    # Create Company
    new_company = Company(
        name=f"{full_name}'s Workspace",
        type="TENANT",
        status="active",
        onboarding_status="pending",
        onboarding_metadata={"completed_steps": [], "created_via": "oauth"}
    )

    # Read default_daily_credits from global BillingConfig BEFORE flush
    try:
        from src.billing.billing_models import BillingConfig
        config_result = await db.execute(
            select(BillingConfig).where(
                BillingConfig.company_id.is_(None),
                BillingConfig.is_active == True
            ).limit(1)
        )
        global_config = config_result.scalar_one_or_none()
        if global_config and global_config.default_daily_credits:
            new_company.default_daily_credits = str(global_config.default_daily_credits)
    except Exception:
        pass  # Fall back to model default

    db.add(new_company)
    await db.flush()
    
    # Create User with random password (since they use OAuth)
    random_password = secrets.token_urlsafe(16)
    hashed_password = get_password_hash(random_password)
    
    new_user = User(
        email=email,
        full_name=full_name,
        hashed_password=hashed_password,
        company_id=new_company.id,
        role="tenant_admin",
        is_verified=True # OAuth users are verified by provider
    )
    db.add(new_user)
    await db.flush()

    # Auto-provision CreditWallet
    await _provision_new_tenant(db, new_company)

    await db.commit()
    await db.refresh(new_user)
    return new_user

async def verify_email_token(db: AsyncSession, token: str):
    """Verify email using a JWT token"""
    from src.common.security import decode_access_token
    
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    
    # Check token type
    if payload.get("type") != "email_verification":
        raise HTTPException(status_code=400, detail="Invalid token type")
    
    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=400, detail="Invalid token")
    
    # Find and verify user
    result = await db.execute(select(User).filter(User.email == email))
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if user.is_verified:
        return {"message": "Email already verified"}
    
    user.is_verified = True
    await db.commit()
    
    return {"message": "Email verified successfully"}

