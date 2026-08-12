import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from src.gateway.config import settings

limiter = Limiter(key_func=get_remote_address, default_limits=[settings.RATE_LIMIT], storage_uri=settings.REDIS_URL)

app = FastAPI(title="HireBuddha API Gateway")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://34.100.230.121:3000",
        "https://dev.hirebuddha.com",
        "https://app.hirebuddha.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

client = httpx.AsyncClient(base_url=settings.BACKEND_URL)

@app.on_event("shutdown")
async def shutdown_event():
    await client.aclose()

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
@limiter.limit(settings.RATE_LIMIT)
async def proxy(request: Request, path: str):
    url = f"/{path}"
    if request.query_params:
        url += f"?{request.query_params}"
    
    if "upload-csv" in path:
        print(f"Gateway Debug: Headers for {path}: {request.headers}")
    
    # Forward headers but exclude host to avoid confusion
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None) # Let httpx handle this
    
    content = await request.body()
    
    try:
        response = await client.request(
            method=request.method,
            url=url,
            headers=headers,
            content=content,
            timeout=60.0
        )
        
        # Stream response back
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=dict(response.headers)
        )
    except httpx.RequestError as exc:
        return Response(
            content=f"Backend service unavailable: {str(exc)}",
            status_code=503
        )
