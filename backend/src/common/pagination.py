"""One page of a list, the same on every list endpoint (API-16, API-I3).

Every list decided for itself: ``GET /ai/entities``, ``/ai/executions`` and
``/config/integrations`` answered every row at once (``app_admin``: every
company's), ``/artifacts`` took ``limit`` / ``offset`` and answered
``{"artifacts", "count"}``. No client could write one paging helper, and no
list degraded gracefully as data grew.

Each paged list now takes ``?limit=`` (1–200, default 50) and ``?cursor=`` (the
previous page's ``next_cursor``) and answers::

    {"items": [...], "next_cursor": "<opaque>" | null, "limit": 50}

Pages are keyset pages, newest first, on ``(created_at, id)``: a row added
while a client pages does not shift the next page, and ``next_cursor`` is null
on the last page. The cursor is opaque to clients; one this API did not give
is a 400.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any, Generic, Optional, Sequence, TypeVar
from uuid import UUID

from fastapi import HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, tuple_

__all__ = ["Page", "MAX_LIMIT", "DEFAULT_LIMIT", "LimitParam", "CursorParam",
           "encode_cursor", "decode_cursor", "keyset", "page_of"]

T = TypeVar("T")

MAX_LIMIT = 200
DEFAULT_LIMIT = 50
_EPOCH = datetime(1970, 1, 1)


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: Optional[str] = None
    limit: int


def LimitParam() -> Any:  # noqa: N802 - a FastAPI parameter factory
    return Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description=f"Items per page, at most {MAX_LIMIT}")


def CursorParam() -> Any:  # noqa: N802
    return Query(None, description="The previous page's next_cursor; omit for the first page")


def encode_cursor(created_at: Optional[datetime], row_id: Any) -> str:
    raw = json.dumps([(created_at or _EPOCH).isoformat(), str(row_id)])
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        created, row_id = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        return datetime.fromisoformat(created), UUID(row_id)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="cursor is not one this API gave") from exc


def keyset(query: Any, created_col: Any, id_col: Any, cursor: Optional[str], limit: int) -> Any:
    """``query`` narrowed to the page after ``cursor``, newest first, one row
    more than ``limit`` (so :func:`page_of` can tell whether another page follows)."""
    created = func.coalesce(created_col, _EPOCH)
    if cursor:
        after_created, after_id = decode_cursor(cursor)
        query = query.where(tuple_(created, id_col) < tuple_(after_created, after_id))
    return query.order_by(created.desc(), id_col.desc()).limit(limit + 1)


def page_of(rows: Sequence[Any], limit: int, items: Optional[list[Any]] = None) -> dict[str, Any]:
    """The page for rows read by :func:`keyset`; ``items`` replaces the rows
    as shown (a mapped response) when given."""
    shown = list(rows[:limit])
    more = len(rows) > limit and shown
    next_cursor = encode_cursor(getattr(shown[-1], "created_at", None), shown[-1].id) if more else None
    return {"items": items[:limit] if items is not None else shown, "next_cursor": next_cursor, "limit": limit}
