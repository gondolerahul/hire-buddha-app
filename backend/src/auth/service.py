from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status
from src.auth.models import User, Company, RefreshToken
from src.auth.schemas import UserCreate, UserLogin
from src.common.security import get_password_hash, verify_password, create_access_token, ACCESS_TOKEN_TYPE, EMAIL_VERIFICATION_TOKEN_TYPE
from src.common.email import email_service
from datetime import datetime, timedelta
import hashlib
import uuid
import secrets
from sqlalchemy import or_

from src.auth.schemas import UserCreate, UserLogin, UserCreateAdmin, UserUpdate
from src.auth.roles import Role, USER_ADMIN_ROLES, assignable_roles
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

async def _require_user_admin_over(db: AsyncSession, actor: User, company_id) -> None:
    """403 unless ``actor`` administers users of ``company_id``.

    app_admin: every company. partner_admin: its own company and its tenants.
    tenant_admin: its own company. Anyone else: no company.
    """
    if actor.role == Role.APP_ADMIN:
        return
    if actor.role == Role.TENANT_ADMIN and company_id == actor.company_id:
        return
    if actor.role == Role.PARTNER_ADMIN:
        if company_id == actor.company_id:
            return
        result = await db.execute(select(Company.parent_id).where(Company.id == company_id))
        if result.scalar_one_or_none() == actor.company_id:
            return
    raise HTTPException(status_code=403, detail="Not authorized to manage users of this company")


async def create_user_as_admin(db: AsyncSession, user_in: UserCreateAdmin, creator: User):
    # Permission Checks
    if creator.role not in USER_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized to create users")
    result = await db.execute(select(Company.id).where(Company.id == user_in.company_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Target company not found")
    await _require_user_admin_over(db, creator, user_in.company_id)
    if user_in.role not in assignable_roles(creator.role):
        raise HTTPException(status_code=403, detail=f"A {creator.role} cannot assign the role {user_in.role}")

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
        role=str(user_in.role),
        is_verified=True # Admin created users are pre-verified
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user


async def update_user_as_admin(db: AsyncSession, user_id: uuid.UUID, update: UserUpdate, actor: User) -> User:
    """Apply ``update`` to a user, if ``actor`` may make that change (AU-01).

    Anyone may change their own ``full_name``. Everything else is a user-admin
    action: the actor must administer the target's company, the target's current
    role must be one the actor could assign, and a new role must be one too. No
    one changes their own role or deactivates themselves — the escalation this
    closes was a tenant admin PATCHing ``{"role": "app_admin"}`` onto their own row.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    changes = update.model_dump(exclude_unset=True)
    if "role" in changes and changes["role"] == user.role:
        del changes["role"]  # unchanged — edit forms send the current role back
    if "is_active" in changes and changes["is_active"] == user.is_active:
        del changes["is_active"]
    is_self = user.id == actor.id

    if is_self and ("role" in changes or "is_active" in changes):
        raise HTTPException(status_code=403, detail="You cannot change your own role or active status")
    if not is_self or set(changes) - {"full_name"}:
        if actor.role not in USER_ADMIN_ROLES:
            raise HTTPException(status_code=403, detail="Not authorized to update this user")
        await _require_user_admin_over(db, actor, user.company_id)
        allowed = assignable_roles(actor.role)
        if not is_self and user.role not in allowed:
            raise HTTPException(status_code=403, detail=f"A {actor.role} cannot manage a {user.role}")
        if "role" in changes and changes["role"] not in allowed:
            raise HTTPException(status_code=403, detail=f"A {actor.role} cannot assign the role {changes['role']}")

    for field, value in changes.items():
        setattr(user, field, str(value) if field == "role" else value)
    await db.commit()
    await db.refresh(user)
    return user

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

def issue_access_token(user: User) -> str:
    """A login access token for ``user`` — the only kind that authenticates requests."""
    return create_access_token(
        data={"sub": user.email, "company_id": str(user.company_id), "type": ACCESS_TOKEN_TYPE}
    )


def require_active(user: User) -> User:
    """403 for a deactivated user, so a correct password does not sign them in (AU-04)."""
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account has been deactivated")
    return user


async def authenticate_user(db: AsyncSession, login_data: UserLogin):
    result = await db.execute(select(User).filter(User.email == login_data.email))
    user = result.scalars().first()
    if not user:
        return None
    if not verify_password(login_data.password, user.hashed_password):
        return None
    return require_active(user)

def hash_refresh_token(token: str) -> str:
    """The stored form of a refresh token (AU-10).

    Only this SHA-256 is kept, so a leaked ``refresh_tokens`` table holds no
    usable session. The token is 32 random bytes, so an unsalted fast hash is
    enough — there is nothing to guess.
    """
    return hashlib.sha256(token.encode()).hexdigest()


async def _find_refresh_token(db: AsyncSession, token: str) -> RefreshToken | None:
    result = await db.execute(select(RefreshToken).filter(RefreshToken.token_hash == hash_refresh_token(token)))
    return result.scalars().first()


async def create_refresh_token(db: AsyncSession, user_id: uuid.UUID) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(days=7)
    
    refresh_token = RefreshToken(
        user_id=user_id,
        token_hash=hash_refresh_token(token),
        expires_at=expires_at
    )
    db.add(refresh_token)
    await db.commit()
    return token

async def verify_refresh_token(db: AsyncSession, token: str) -> User:
    refresh_token = await _find_refresh_token(db, token)
    
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
    if not user.is_active:
        raise HTTPException(status_code=401, detail="This account has been deactivated")
        
    return user

async def rotate_refresh_token(db: AsyncSession, old_token: str) -> str:
    # Verify old token (and get user)
    # We do this manually to get the token object too
    refresh_token = await _find_refresh_token(db, old_token)
    
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
    if payload.get("type") != EMAIL_VERIFICATION_TOKEN_TYPE:
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

