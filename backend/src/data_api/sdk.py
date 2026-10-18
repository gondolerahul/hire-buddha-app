"""The Python client of the Data API (plan WS4 4.11): agents' record tools,
app templates and tests use it.

    async with DataApi(token) as api:
        page = await api.list("contact", filters=[("lifecycle_stage", "eq", "lead")], sort="-created_at")
        contact = await api.create("contact", {"first_name": "Priya"}, idempotency_key="form-42")
        contact = await api.update("contact", contact["id"], {"lifecycle_stage": "customer"},
                                   row_version=contact["row_version"])

``base_url`` is the business's Data API (``…/data/v1``); without one, the
client calls the Data API in this process (``DATA_API_URL`` unset — the
local stack and workers), through the same checks as over the network.
Every error is a :class:`DataApiError` with the problem's status and code.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import httpx

Filter = Tuple[str, str, Any]  # (field, operator, value)
_IN_PROCESS: Dict[str, Any] = {}


class DataApiError(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(f"{status} {code}: {detail}")
        self.status, self.code, self.detail = status, code, detail


def _in_process_transport() -> httpx.AsyncBaseTransport:
    if "app" not in _IN_PROCESS:
        from src.data_api.app import create_app

        _IN_PROCESS["app"] = create_app()
    return httpx.ASGITransport(app=_IN_PROCESS["app"])


def default_base_url() -> Optional[str]:
    from src.common.config import settings

    return (getattr(settings, "DATA_API_URL", "") or "").rstrip("/") or None


def query_params(filters: Iterable[Filter] = (), sort: Optional[str] = None, fields: Optional[Sequence[str]] = None,
                 size: Optional[int] = None, after: Optional[str] = None, archived: bool = False,
                 include: Optional[Sequence[str]] = None) -> List[Tuple[str, str]]:
    """``filter[f][op]=v`` and the paging parameters, as the API reads them."""
    params: List[Tuple[str, str]] = []
    for field, op, value in filters:
        if isinstance(value, (list, tuple, set)):
            value = ",".join(str(v) for v in value)
        elif isinstance(value, bool):
            value = "true" if value else "false"
        params.append((f"filter[{field}][{op}]", "" if value is None else str(value)))
    for key, value in (("sort", sort), ("fields", ",".join(fields) if fields else None),
                       ("page[size]", size), ("page[after]", after), ("archived", "true" if archived else None),
                       ("include", ",".join(include) if include else None)):
        if value is not None:
            params.append((key, str(value)))
    return params


class DataApi:
    """One caller's client: a user or run token, or an app key."""

    def __init__(self, credential: str, base_url: Optional[str] = None, *,
                 transport: Optional[httpx.AsyncBaseTransport] = None, timeout: float = 30.0) -> None:
        base = base_url or default_base_url()
        if base is None:
            transport, base = transport or _in_process_transport(), "http://data-api.internal/v1"
        self._client = httpx.AsyncClient(base_url=base, transport=transport, timeout=timeout,
                                         headers={"Authorization": f"Bearer {credential}"})

    async def __aenter__(self) -> "DataApi":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = await self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            try:
                problem = response.json()
            except ValueError:
                problem = {}
            raise DataApiError(response.status_code, str(problem.get("code") or "error"),
                               str(problem.get("detail") or response.text[:300]))
        return response

    # ── Schema ─────────────────────────────────────────────────────────────
    async def schema(self) -> Dict[str, Any]:
        return (await self._call("GET", "/schema")).json()

    async def propose_change(self, operations: List[Dict[str, Any]], *, reason: Optional[str] = None,
                             dry_run: bool = False) -> Dict[str, Any]:
        return (await self._call("POST", "/schema/changes", json={
            "operations": operations, "reason": reason, "dry_run": dry_run})).json()

    async def change(self, change_id: str) -> Dict[str, Any]:
        return (await self._call("GET", f"/schema/changes/{change_id}")).json()

    async def decide(self, change_id: str, *, approve: bool) -> Dict[str, Any]:
        verb = "approve" if approve else "reject"
        return (await self._call("POST", f"/schema/changes/{change_id}/{verb}")).json()

    # ── Records ────────────────────────────────────────────────────────────
    async def list(self, obj: str, *, filters: Iterable[Filter] = (), sort: Optional[str] = None,
                   fields: Optional[Sequence[str]] = None, size: Optional[int] = None, after: Optional[str] = None,
                   archived: bool = False, include: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        """``{"items": [...], "next": cursor or None}``; ``include`` adds linked records (``_included``)."""
        params = query_params(filters, sort, fields, size, after, archived, include)
        return (await self._call("GET", f"/{obj}", params=params)).json()

    async def get(self, obj: str, record_id: str, *, include: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        params = query_params(include=include)
        return (await self._call("GET", f"/{obj}/{record_id}", params=params)).json()

    async def linked(self, obj: str, record_id: str, relation: str, *, sort: Optional[str] = None,
                     size: Optional[int] = None, after: Optional[str] = None) -> Dict[str, Any]:
        """The record a link field points to, or the records of ``relation`` linking to this one."""
        params = query_params(sort=sort, size=size, after=after)
        return (await self._call("GET", f"/{obj}/{record_id}/links/{relation}", params=params)).json()

    async def link(self, obj: str, record_id: str, relation: str, *, to: Any = None,
                   ids: Sequence[str] = (), unlink: Sequence[str] = ()) -> Dict[str, Any]:
        """Set a link field (``to``: an id or None), or link / unlink records of another object."""
        body: Dict[str, Any] = {"ids": list(ids), "unlink": list(unlink)} if ids or unlink else {"id": to}
        return (await self._call("POST", f"/{obj}/{record_id}/links/{relation}", json=body)).json()

    async def batch(self, operations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Up to 100 ``{"op": "create"|"update"|"archive", "object", "id", "row_version", "values"}``,
        all or none."""
        return (await self._call("POST", "/batch", json={"operations": operations})).json()

    async def create(self, obj: str, values: Dict[str, Any], *,
                     idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        return (await self._call("POST", f"/{obj}", json=values, headers=headers)).json()

    async def update(self, obj: str, record_id: str, values: Dict[str, Any], *,
                     row_version: Union[int, str]) -> Dict[str, Any]:
        """Refused with 412 ``stale`` when the record changed since ``row_version``."""
        return (await self._call("PATCH", f"/{obj}/{record_id}", json=values,
                                 headers={"If-Match": f'"{row_version}"'})).json()

    async def archive(self, obj: str, record_id: str) -> Dict[str, Any]:
        return (await self._call("DELETE", f"/{obj}/{record_id}")).json()

    async def report(self, obj: str, *, group_by: Sequence[str] = (), measures: Sequence[Dict[str, Any]] = (),
                     filters: Iterable[Filter] = (), bucket: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"object": obj, "group_by": list(group_by),
                                "measures": list(measures) or [{"fn": "count"}],
                                "filter": [list(f) for f in filters]}
        if bucket:
            body["bucket"] = bucket
        return (await self._call("POST", "/reports", json=body)).json()
