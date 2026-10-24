from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from src.common.config import settings
from src.common.database import get_db
from src.auth.models import User
from src.auth.roles import Role
from src.auth.schemas import TokenData

from typing import Iterable, Optional
import logging

from src.common.security import ACCESS_TOKEN_TYPE, URL_TOKEN_SCOPES, URL_TOKEN_TYPE

EMAIL_NOT_VERIFIED = "Please verify your email address before signing in"

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

async def _authenticate_user(token: Optional[str], db: AsyncSession, *,
                             token_type: str = ACCESS_TOKEN_TYPE, path: Optional[str] = None):
    """The user a login access token belongs to, or 401/403.

    The token must be a login token (``type == "access"``, AU-14) — not, say, an
    email-verification token signed with the same key. With ``token_type`` set to
    ``URL_TOKEN_TYPE`` it must instead be a URL token whose scope is one of
    ``URL_TOKEN_SCOPES`` and a prefix of ``path``, the request's path (FE-28). Its
    user must exist and
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
    if email is None or payload.get("type") != token_type:
        logger.debug("auth: token has no subject or is not a %s token (type=%r)", token_type,
                     payload.get("type"))
        raise credentials_exception
    if token_type == URL_TOKEN_TYPE:
        scope = payload.get("scope")
        if scope not in URL_TOKEN_SCOPES or not path or not path.startswith(scope):
            logger.debug("auth: URL token scope %r does not cover %r", scope, path)
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

async def get_current_user(request: Request, token: Optional[str] = Depends(oauth2_scheme),
                           db: AsyncSession = Depends(get_db)):
    user = await _authenticate_user(token, db)
    # A company suspended for an unpaid balance is read-only (Phase 15 T4-8).
    from src.billing.suspension import refuse_writes
    await refuse_writes(request, db, user)
    # Who the response is for: tenants and partners see billed amounts only (Phase 15 T9-3).
    from src.billing.money_view import remember_viewer
    remember_viewer(request, user)
    return user

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

async def authenticate_stream_token(token: Optional[str], path: str):
    """The user behind a WebSocket handshake's URL token for ``path`` (GW-04).

    A WebSocket handler has no dependency-injected session, so it opens its own.
    """
    from src.common.tenancy.session import control_session  # users are control rows

    async with control_session() as db:
        return await _authenticate_user(token, db, token_type=URL_TOKEN_TYPE, path=path)


async def get_current_user_from_query(request: Request, token: str, db: AsyncSession = Depends(get_db)):
    """The user behind ``?token=``, which must be a URL token for this path (FE-28).

    A login access token is refused here: it would sit in logs, the history and
    Referer headers for as long as it lives. Mint one with ``POST /auth/url-token``.
    """
    return await _authenticate_user(token, db, token_type=URL_TOKEN_TYPE, path=request.url.path)

class RoleChecker:
    """Dependency: the signed-in user, if their role is allowed; 403 otherwise.

    The one role guard (AU-17). ``app_admin`` is always allowed — the platform
    administrator is never locked out by a list that forgot it (AU-18). Each
    role must be a ``Role``; a misspelt role name raises when the route module
    is imported, instead of making a guard that silently allows nobody (AU-21).
    """

    def __init__(self, allowed_roles: Iterable[str]):
        self.allowed_roles: frozenset[Role] = frozenset(Role(r) for r in allowed_roles) | {Role.APP_ADMIN}

    def __call__(self, user: User = Depends(get_current_user)):
        if user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operation not permitted"
            )
        return user
