"""Who is calling: the app user behind the request's bearer token."""
from __future__ import annotations

from typing import Optional


def bearer(header: Optional[str]) -> Optional[str]:
    """The token in ``Authorization: Bearer <token>``, or ``None``."""
    if not header:
        return None
    scheme, _, token = header.strip().partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()
