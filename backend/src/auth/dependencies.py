from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from src.common.config import settings
from src.common.database import get_db
from src.auth.models import User
from src.auth.schemas import TokenData

from typing import Optional
import logging

from src.common.security import ACCESS_TOKEN_TYPE

EMAIL_NOT_VERIFIED = "Please verify your email address before signing in"

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

async def _authenticate_user(token: Optional[str], db: AsyncSession):
    """The user a login access token belongs to, or 401/403.

    The token must be a login token (``type == "access"``, AU-14) — not, say, an
    email-verification token signed with the same key — its user must exist and
    be active (AU-04) and verified (AU-08), and its ``tv`` must equal the user's ``token_version``, so
    ending a user's sessions ends their access tokens too (AU-05). A suspended
    company is a 403.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise credentials_exception
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as e:
        logger.debug("auth: JWT rejected: %s", e)
        raise credentials_exception
    email = payload.get("sub")
    if email is None or payload.get("type") != ACCESS_TOKEN_TYPE:
        logger.debug("auth: token has no subject or is not a login token (type=%r)", payload.get("type"))
        raise credentials_exception
    token_data = TokenData(email=email)

    result = await db.execute(select(User).options(selectinload(User.company)).filter(User.email == token_data.email))
    user = result.scalars().first()
    if user is None:
        raise credentials_exception
    if payload.get("tv") != (user.token_version or 0):
        # The user's sessions were ended (logout everywhere, password reset,
        # refresh-token reuse) after this token was issued (AU-05).
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account has been deactivated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_verified:
        # Unverified accounts cannot sign in (AU-08); a token issued before that
        # rule does not outlive it.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=EMAIL_NOT_VERIFIED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.company and user.company.status == "suspended":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Company account is suspended. Please contact support."
        )

    return user

async def get_current_user(token: Optional[str] = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    return await _authenticate_user(token, db)

async def get_current_user_and_company(
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """Return (user, company) tuple. Raises 403 if user has no company."""
    user = await _authenticate_user(token, db)
    if not user.company:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not associated with any company.",
        )
    return user, user.company

async def get_current_user_from_query(token: str, db: AsyncSession = Depends(get_db)):
    return await _authenticate_user(token, db)

class RoleChecker:
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, user: User = Depends(get_current_user)):
        if user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operation not permitted"
            )
        return user
