from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request, HTTPException, status
from src.common.database import AsyncSessionLocal
from src.auth.models import Company
from sqlalchemy import select
import logging

logger = logging.getLogger(__name__)

class CompanySuspensionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip for public endpoints or if no auth header
        if request.url.path.startswith("/api/v1/auth") or request.url.path == "/" or request.url.path.startswith("/docs") or request.url.path.startswith("/openapi.json"):
            return await call_next(request)
        
        # We need to extract company_id from the token or request state
        # Since the auth dependency runs *after* middleware in FastAPI, we have to manually check the token here
        # OR we can rely on the fact that if the user is authenticated, we can check their tenant status.
        # However, middleware runs before dependencies.
        
        # A better approach for FastAPI is to use a dependency that checks this, 
        # but the requirement specifically asked for Middleware.
        # Let's try to extract the token and check.
        
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            try:
                # We need a DB session
                async with AsyncSessionLocal() as db:
                    # Verify token and get user (simplified version of get_current_user)
                    # We'll reuse the service logic if possible, or just decode the token
                    from src.common.security import decode_access_token
                    
                    payload = decode_access_token(token)
                    if payload:
                        company_id = payload.get("company_id")
                        if company_id:
                            # Check company status
                            result = await db.execute(select(Company).where(Company.id == company_id))
                            company = result.scalar_one_or_none()
                            
                            if company and company.status == "suspended":
                                return Response(
                                    content='{"detail": "Company is suspended. Please contact support."}',
                                    status_code=status.HTTP_403_FORBIDDEN,
                                    media_type="application/json"
                                )
            except Exception as e:
                logger.error(f"Middleware error checking tenant status: {e}")
                # Don't block request on error, let the actual auth dependency handle invalid tokens
                pass
                
        return await call_next(request)

from fastapi.responses import Response
