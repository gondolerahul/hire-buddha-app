from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Response, Body
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.security import OAuth2PasswordRequestForm
from src.common.database import get_db
from src.auth.schemas import (
    UserCreate, UserResponse, Token, UserLogin, RefreshTokenRequest, LogoutRequest, OAuthRequest,
    EmailRequest, PasswordResetRequest, RegistrationResponse,
)
from src.auth import account_emails, service
import httpx
import os
from src.auth import service

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=RegistrationResponse, status_code=status.HTTP_201_CREATED)
async def register(user: UserCreate, background: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Create a workspace and its admin, and email a verification link (AU-08).

    No tokens: the account cannot sign in until the address is verified.
    """
    new_user = await service.create_user(db, user)
    background.add_task(account_emails.send_verification_email, new_user.email)
    return {"email": new_user.email, "message": "Check your email for a link to verify your address."}


@router.post("/resend-verification", status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(request: EmailRequest, background: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Send the verification link again. The same answer whether or not the address has an account."""
    if await service.needs_verification_email(db, request.email):
        background.add_task(account_emails.send_verification_email, request.email)
    return {"message": "If that address has an unverified account, a new link is on its way."}


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(request: EmailRequest, background: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Email a single-use, 30-minute reset link (AU-06). The same answer for any address."""
    user = await service.password_reset_target(db, request.email)
    if user is not None:
        background.add_task(account_emails.send_password_reset_email, user.email, user.hashed_password)
    return {"message": "If that address has an account, a reset link is on its way."}


@router.post("/reset-password")
async def reset_password(request: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    """Set a new password from a reset link. Every existing session ends."""
    await service.reset_password(db, request.token, request.new_password)
    return {"message": "Password updated. Sign in with your new password."}


@router.post("/login", response_model=Token)
async def login(response: Response, login_data: UserLogin, db: AsyncSession = Depends(get_db)):
    user = await service.authenticate_user(db, login_data)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = service.issue_access_token(user)
    refresh_token = await service.create_refresh_token(db, user.id)
    
    # Set HttpOnly cookie
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True, # Should be True in production
        samesite="lax",
        max_age=7 * 24 * 60 * 60 # 7 days
    )
    
    return {"access_token": access_token, "token_type": "bearer", "refresh_token": refresh_token}

# Support for OAuth2PasswordRequestForm for Swagger UI
@router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    user = await service.authenticate_user(db, UserLogin(email=form_data.username, password=form_data.password))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = service.issue_access_token(user)
    return {"access_token": access_token, "token_type": "bearer"}

from src.auth.dependencies import get_current_user, RoleChecker
from src.auth.schemas import UserResponse

@router.get("/me", response_model=UserResponse)
async def read_users_me(current_user: UserResponse = Depends(get_current_user)):
    return current_user

@router.get("/admin-only", dependencies=[Depends(RoleChecker(["app_admin"]))])
async def admin_only():
    return {"message": "Admin access granted"}

@router.post("/refresh", response_model=Token)
async def refresh_token(
    response: Response,
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    user, new_refresh_token = await service.rotate_refresh_token(db, request.refresh_token)
    
    access_token = service.issue_access_token(user)
    
    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=7 * 24 * 60 * 60
    )
    
    return {"access_token": access_token, "token_type": "bearer", "refresh_token": new_refresh_token}

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: LogoutRequest, response: Response, db: AsyncSession = Depends(get_db)):
    """End this session — or, with ``all_sessions``, every session of its user (AU-12).

    The refresh token is the credential: it is revoked, so it can no longer mint
    access tokens. ``all_sessions`` also bumps the user's ``token_version``, which
    ends their access tokens on every device at once.
    """
    await service.logout(db, request.refresh_token, all_sessions=request.all_sessions)
    response.delete_cookie("refresh_token")
    response.status_code = status.HTTP_204_NO_CONTENT
    return None

def _verified_email(provider: str, user_info: dict) -> str | None:
    """The address the provider vouches for, or None; never one a tenant admin typed (AU-23).

    An OAuth login signs into the account with this email if one exists, so the
    email must be one the provider has verified. Google says so in
    ``email_verified``. Microsoft's ``mail`` is an attribute any Entra tenant's
    admin can set to anyone's address — logging in through ``common`` with it
    took over that address's account. ``userPrincipalName`` must be in a
    domain the user's tenant has verified (or the user's own Microsoft
    account), so that is the identity.
    """
    if provider == "google":
        if user_info.get("email_verified") is not True:
            raise HTTPException(status_code=400, detail="Google has not verified this email address")
        email = user_info.get("email")
    else:
        email = user_info.get("userPrincipalName")
    return email.strip().lower() if email else None


def _pkce(request: OAuthRequest) -> dict[str, str]:
    """The PKCE verifier for the token request, when the SPA sent one."""
    return {"code_verifier": request.code_verifier} if request.code_verifier else {}


@router.post("/oauth/{provider}", response_model=Token)
async def oauth_login(
    provider: str,
    request: OAuthRequest,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    if provider == "google":
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "code": request.code,
            "grant_type": "authorization_code",
            "redirect_uri": request.redirect_uri,
            **_pkce(request),
        }
        async with httpx.AsyncClient() as client:
            token_res = await client.post(token_url, data=data)
            if token_res.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to get token from Google")
            token_data = token_res.json()
            
            user_info_res = await client.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {token_data['access_token']}"}
            )
            user_info = user_info_res.json()
            email = _verified_email(provider, user_info)
            name = user_info.get("name")

    elif provider == "microsoft":
        token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        data = {
            "client_id": os.getenv("MICROSOFT_CLIENT_ID"),
            "client_secret": os.getenv("MICROSOFT_CLIENT_SECRET"),
            "code": request.code,
            "grant_type": "authorization_code",
            "redirect_uri": request.redirect_uri,
            **_pkce(request),
        }
        async with httpx.AsyncClient() as client:
            token_res = await client.post(token_url, data=data)
            if token_res.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to get token from Microsoft")
            token_data = token_res.json()
            
            user_info_res = await client.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {token_data['access_token']}"}
            )
            user_info = user_info_res.json()
            email = _verified_email(provider, user_info)
            name = user_info.get("displayName")
    else:
        raise HTTPException(status_code=400, detail="Unsupported provider")

    if not email:
        raise HTTPException(status_code=400, detail="Could not retrieve email from provider")

    user = service.require_active(await service.get_or_create_oauth_user(db, email, name))
    
    access_token = service.issue_access_token(user)
    refresh_token = await service.create_refresh_token(db, user.id)
    
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=7 * 24 * 60 * 60
    )
    
    return {"access_token": access_token, "token_type": "bearer", "refresh_token": refresh_token}

@router.get("/verify-email")
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    """Verify email using the token sent to the user's email"""
    result = await service.verify_email_token(db, token)
    return result


