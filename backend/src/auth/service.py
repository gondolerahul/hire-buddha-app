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
from sqlalchemy import or_, update

from src.auth.schemas import UserCreate, UserLogin, UserCreateAdmin, UserUpdate
from src.auth.roles import Role, USER_ADMIN_ROLES, assignable_roles
from src.auth.dependencies import EMAIL_NOT_VERIFIED
from src.auth.throttle import ACCOUNT_EMAILS, LOGIN_FAILURES
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
    check_password_policy(user_in.password, user_in.email)
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
    """Self-registration: a new TENANT workspace and its unverified tenant_admin.

    The account cannot sign in until the email address is verified (AU-08); the
    router sends the verification email.
    """
    check_password_policy(user.password, user.email)
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
    """A login access token for ``user`` — the only kind that authenticates requests.

    ``tv`` is the user's ``token_version``; a token whose ``tv`` no longer matches
    is refused, which is how every session is ended at once (AU-05).
    """
    return create_access_token(
        data={
            "sub": user.email,
            "company_id": str(user.company_id),
            "type": ACCESS_TOKEN_TYPE,
            "tv": user.token_version or 0,
        }
    )


async def revoke_all_sessions(db: AsyncSession, user_id: uuid.UUID) -> None:
    """End every session of a user: all refresh tokens, and all access tokens.

    Bumps ``users.token_version`` (access tokens carry it and are refused once
    it moves) and revokes every refresh token. The caller commits.
    """
    await db.execute(
        update(User).where(User.id == user_id).values(token_version=User.token_version + 1)
        .execution_options(synchronize_session="fetch")
    )
    await db.execute(
        update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked.is_not(True))
        .values(revoked=True).execution_options(synchronize_session="fetch")
    )


MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128


def check_password_policy(password: str, email: str | None = None) -> None:
    """422 unless ``password`` may be set (AU-07).

    12 to 128 characters, and not the account's email address. Checked wherever
    a password is chosen — registration, admin creation, reset — not at login,
    so existing passwords keep working. The message is a plain string because
    the UI shows ``detail`` as text.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=422, detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters long")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise HTTPException(status_code=422, detail=f"Password must be at most {MAX_PASSWORD_LENGTH} characters long")
    if email and password.strip().lower() == email.strip().lower():
        raise HTTPException(status_code=422, detail="Password must not be your email address")


def require_active(user: User) -> User:
    """403 for a deactivated user, so a correct password does not sign them in (AU-04)."""
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account has been deactivated")
    return user


def require_verified(user: User) -> User:
    """403 until the user has confirmed their email address (AU-08)."""
    if not user.is_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=EMAIL_NOT_VERIFIED)
    return user


async def authenticate_user(db: AsyncSession, login_data: UserLogin):
    """The user for a correct email and password, or ``None``.

    Ten wrong passwords for one account in 15 minutes stop sign-in for that
    account until the window ends (429), wherever the attempts come from (AU-07).
    Unknown emails count too, so the limit does not reveal which accounts exist.
    A right password for a deactivated or unverified account is a 403.
    """
    wait = await LOGIN_FAILURES.retry_after(login_data.email)
    if wait:
        minutes = -(-wait // 60)
        unit = "minute" if minutes == 1 else "minutes"
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed sign-in attempts. Try again in {minutes} {unit}.",
            headers={"Retry-After": str(wait)},
        )
    result = await db.execute(select(User).filter(User.email == login_data.email))
    user = result.scalars().first()
    if not user or not verify_password(login_data.password, user.hashed_password):
        await LOGIN_FAILURES.hit(login_data.email)
        return None
    await LOGIN_FAILURES.clear(login_data.email)
    return require_verified(require_active(user))

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

async def _refresh_token_user(db: AsyncSession, token: str) -> tuple[RefreshToken, User]:
    """The live refresh token row and its active user, or 401.

    A **revoked** token presented again means it was copied: whoever rotated it
    first holds the live one. Every session of the user is ended (AU-09).
    """
    refresh_token = await _find_refresh_token(db, token)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if refresh_token.revoked:
        logger.warning("Revoked refresh token reused for user %s: ending all of their sessions", refresh_token.user_id)
        await revoke_all_sessions(db, refresh_token.user_id)
        await db.commit()
        raise HTTPException(status_code=401, detail="Token revoked")
    if refresh_token.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Token expired")

    result = await db.execute(select(User).filter(User.id == refresh_token.user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="This account has been deactivated")
    if not user.is_verified:
        raise HTTPException(status_code=401, detail=EMAIL_NOT_VERIFIED)
    return refresh_token, user


async def verify_refresh_token(db: AsyncSession, token: str) -> User:
    return (await _refresh_token_user(db, token))[1]


async def rotate_refresh_token(db: AsyncSession, old_token: str) -> tuple[User, str]:
    """Swap a refresh token for a new one; return its user and the new token."""
    refresh_token, user = await _refresh_token_user(db, old_token)
    refresh_token.revoked = True
    new_token = await create_refresh_token(db, user.id)  # commits both
    return user, new_token


async def logout(db: AsyncSession, token: str, all_sessions: bool = False) -> None:
    """End the presented refresh token's session; with ``all_sessions``, every one (AU-12).

    The row is deleted, not flagged ``revoked``: a flagged token presented again
    is treated as stolen and ends every session (reuse detection), and a token
    the user logged out with is not evidence of theft. Unknown or already-revoked
    tokens are a no-op.
    """
    refresh_token = await _find_refresh_token(db, token)
    if refresh_token is None or refresh_token.revoked:
        return
    user_id = refresh_token.user_id
    await db.delete(refresh_token)
    if all_sessions:
        await revoke_all_sessions(db, user_id)
    await db.commit()


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


# ── Verification and password reset (AU-06, AU-08) ────────────────────────────

async def _user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).filter(User.email == email))
    return result.scalars().first()


async def needs_verification_email(db: AsyncSession, email: str) -> bool:
    """Whether to (re)send a verification email to ``email``.

    Only for an existing, active, unverified account, at most five account
    emails an hour per address. The endpoint answers the same either way, so it
    does not reveal which addresses have accounts.
    """
    user = await _user_by_email(db, email)
    if user is None or user.is_verified or not user.is_active:
        return False
    if await ACCOUNT_EMAILS.retry_after(email):
        return False
    await ACCOUNT_EMAILS.hit(email)
    return True


async def password_reset_target(db: AsyncSession, email: str) -> User | None:
    """The account a forgot-password request should email, or ``None`` (same rules)."""
    user = await _user_by_email(db, email)
    if user is None or not user.is_active:
        return None
    if await ACCOUNT_EMAILS.retry_after(email):
        return None
    await ACCOUNT_EMAILS.hit(email)
    return user


async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
    """Set a new password from a reset link, and end every session (AU-06).

    The token must be a ``password_reset`` token issued against the password the
    account still has, so each link works once. Proving control of the mailbox
    also verifies the address.
    """
    from src.auth.account_emails import PASSWORD_RESET_TOKEN_TYPE, password_fingerprint
    from src.common.security import decode_access_token

    invalid = HTTPException(status_code=400, detail="This reset link is invalid, used or expired. Ask for a new one.")
    payload = decode_access_token(token)
    if not payload or payload.get("type") != PASSWORD_RESET_TOKEN_TYPE or not payload.get("sub"):
        raise invalid
    user = await _user_by_email(db, payload["sub"])
    if user is None or not user.is_active or payload.get("pwh") != password_fingerprint(user.hashed_password):
        raise invalid
    check_password_policy(new_password, user.email)
    user.hashed_password = get_password_hash(new_password)
    user.is_verified = True
    await revoke_all_sessions(db, user.id)
    await db.commit()
    await LOGIN_FAILURES.clear(user.email)
