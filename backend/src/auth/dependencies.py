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

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

async def _authenticate_user(token: Optional[str], db: AsyncSession):
    if token is None:
        print("Auth Debug: Token is None - Authorization header missing or invalid")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            print("Auth Debug: Token payload missing 'sub'")
            raise credentials_exception
        token_data = TokenData(email=email)
    except JWTError as e:
        print(f"Auth Debug: JWT Error: {e}")
        raise credentials_exception
    
    result = await db.execute(select(User).options(selectinload(User.company)).filter(User.email == token_data.email))
    user = result.scalars().first()
    if user is None:
        print(f"Auth Debug: User not found for email {token_data.email}")
        raise credentials_exception
        
    if user.company and user.company.status == "suspended":
        print(f"Auth Debug: Company suspended for user {user.email}")
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
