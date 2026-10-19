"""{{display_name}} — the backend of a mobile app, on the HireBuddha Data API.

The app signs its users in with the Data API (``/v1/auth/*``) and sends their
token here; each endpoint asks the Data API with that token, so a user sees
and changes only what their role (and its row policy) allows.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, Header, HTTPException

from app.auth import bearer
from app.hb_data import DataApi, DataApiError

app = FastAPI(title="{{display_name}} API")
data = DataApi()


async def user_token(authorization: Optional[str] = Header(default=None)) -> str:
    token = bearer(authorization)
    if token is None:
        raise HTTPException(status_code=401, detail="Sign in first")
    try:
        await data.app_user(token)
    except DataApiError as error:
        raise HTTPException(status_code=401, detail=error.detail) from None
    return token


@app.get("/healthz")
async def healthz() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/me")
async def me(token: str = Depends(user_token)) -> Dict[str, Any]:
    return await data.app_user(token)


@app.get("/api/{object_name}")
async def list_records(object_name: str, token: str = Depends(user_token)) -> Dict[str, Any]:
    try:
        return await data.list(object_name, token=token)
    except DataApiError as error:
        raise HTTPException(status_code=error.status, detail=error.detail) from None


@app.post("/api/{object_name}", status_code=201)
async def create_record(object_name: str, values: Dict[str, Any], token: str = Depends(user_token)) -> Dict[str, Any]:
    try:
        return await data.create(object_name, values, token=token)
    except DataApiError as error:
        raise HTTPException(status_code=error.status, detail=error.detail) from None
