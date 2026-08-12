from fastapi import APIRouter, Depends, HTTPException, status, Response, Body
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.security import OAuth2PasswordRequestForm
from src.common.database import get_db
from src.auth.schemas import UserCreate, UserResponse, Token, UserLogin, RefreshTokenRequest, OAuthRequest
from src.auth import service
import httpx
import os
from src.auth import service
from src.common.security import create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=Token)
async def register(user: UserCreate, response: Response, db: AsyncSession = Depends(get_db)):
    new_user = await service.create_user(db, user)
    # Generate tokens so the frontend can immediately authenticate
    access_token = create_access_token(data={"sub": new_user.email, "company_id": str(new_user.company_id)})
    refresh_token = await service.create_refresh_token(db, new_user.id)

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=7 * 24 * 60 * 60
    )

    return {"access_token": access_token, "token_type": "bearer", "refresh_token": refresh_token}

@router.post("/login", response_model=Token)
async def login(response: Response, login_data: UserLogin, db: AsyncSession = Depends(get_db)):
    user = await service.authenticate_user(db, login_data)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.email, "company_id": str(user.company_id)})
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
    access_token = create_access_token(data={"sub": user.email, "company_id": str(user.company_id)})
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
    new_refresh_token = await service.rotate_refresh_token(db, request.refresh_token)
    user = await service.verify_refresh_token(db, new_refresh_token)
    
    access_token = create_access_token(data={"sub": user.email, "company_id": str(user.company_id)})
    
    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=7 * 24 * 60 * 60
    )
    
    return {"access_token": access_token, "token_type": "bearer", "refresh_token": new_refresh_token}

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
            email = user_info.get("email")
            name = user_info.get("name")
            
    elif provider == "microsoft":
        token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        data = {
            "client_id": os.getenv("MICROSOFT_CLIENT_ID"),
            "client_secret": os.getenv("MICROSOFT_CLIENT_SECRET"),
            "code": request.code,
            "grant_type": "authorization_code",
            "redirect_uri": request.redirect_uri,
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
            email = user_info.get("mail") or user_info.get("userPrincipalName")
            name = user_info.get("displayName")
    else:
        raise HTTPException(status_code=400, detail="Unsupported provider")

    if not email:
        raise HTTPException(status_code=400, detail="Could not retrieve email from provider")

    user = await service.get_or_create_oauth_user(db, email, name)
    
    access_token = create_access_token(data={"sub": user.email, "company_id": str(user.company_id)})
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


