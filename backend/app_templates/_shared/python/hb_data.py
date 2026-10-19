"""The HireBuddha Data API from a backend: records with the app's key, app users' tokens checked.

Settings come from the environment the App Controller sets: ``HB_DATA_API_URL``,
``HB_APP_KEY`` (the app's key, mounted from its secret), ``HB_TENANT_KEY``, ``HB_APP``.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx


class DataApiError(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


class DataApi:
    def __init__(self, base_url: Optional[str] = None, key: Optional[str] = None) -> None:
        self.base_url = (base_url or os.environ.get("HB_DATA_API_URL", "")).rstrip("/")
        self.key = key or os.environ.get("HB_APP_KEY", "")

    async def _call(self, method: str, path: str, *, token: Optional[str] = None, json: Any = None,
                    params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Any:
        sent = {"Authorization": f"Bearer {token or self.key}", **(headers or {})}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=15) as client:
            response = await client.request(method, path, json=json, params=params, headers=sent)
        body = response.json() if response.content else None
        if response.status_code >= 400:
            body = body or {}
            raise DataApiError(response.status_code, body.get("code", "error"), body.get("detail", response.text))
        return body

    async def list(self, object_name: str, *, token: Optional[str] = None, **params: str) -> Dict[str, Any]:
        return await self._call("GET", f"/v1/{object_name}", token=token, params=params)

    async def get(self, object_name: str, record_id: str, *, token: Optional[str] = None) -> Dict[str, Any]:
        return await self._call("GET", f"/v1/{object_name}/{record_id}", token=token)

    async def create(self, object_name: str, values: Dict[str, Any], *, token: Optional[str] = None) -> Dict[str, Any]:
        return await self._call("POST", f"/v1/{object_name}", token=token, json=values)

    async def update(self, object_name: str, record_id: str, row_version: int, values: Dict[str, Any], *,
                     token: Optional[str] = None) -> Dict[str, Any]:
        return await self._call("PATCH", f"/v1/{object_name}/{record_id}", token=token, json=values,
                                headers={"If-Match": f'"{row_version}"'})

    async def app_user(self, token: str) -> Dict[str, Any]:
        """Who an app user's bearer token belongs to (raises DataApiError 401 when it is not valid)."""
        return await self._call("GET", "/v1/auth/me", token=token)
