"""Which tenant a telephony request is for (Phase 14 WS2 2.12, tech spec §5.3).

Twilio and Tata Tele call our webhooks, and open media streams, without
signing in. With ``TENANCY_MODE=split`` each tenant's sessions, calls and
agents live in its own database, so a request names its tenant before
anything reads them:

* a URL we handed the provider says so — a media-stream path
  ``/stream/<provider>/<company>/<session>`` (``media_stream_path``) or
  ``company=`` on a callback URL (``tenant_query``);
* else our own phone number on the call — the dialled number inbound, the
  calling number outbound — found in ``phone_numbers``, a control table
  (``company_for_numbers``).

With ``single`` every tenant's rows are in the one database and nothing here
changes what a request does: the helpers give back the session or manager
they were handed.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional
from uuid import UUID

from src.common.tenancy.session import is_split, tenant_session

COMPANY_PARAM = "company"


def company_param(value: Any) -> Optional[UUID]:
    """A ``company=`` value from a provider's request, if it is a company id."""
    try:
        return UUID(str(value).strip()) if value else None
    except ValueError:
        return None


def tenant_query(company_id: Any) -> str:
    """``company=<id>`` for a callback URL we hand a provider (split mode); else empty."""
    return f"{COMPANY_PARAM}={company_id}" if is_split() and company_id else ""


def media_stream_path(provider: str, session: Any) -> str:
    """The media-stream path for a voice session: the company is in it in split mode."""
    if is_split() and getattr(session, "company_id", None):
        return f"/stream/{provider}/{session.company_id}/{session.id}"
    return f"/stream/{provider}/{session.id}"


def _clean(number: Any) -> str:
    return str(number or "").replace("whatsapp:", "").strip()


async def company_for_numbers(number_router: Any, *numbers: Any) -> Optional[UUID]:
    """The company the first of ``numbers`` is assigned to (``phone_numbers``), if any."""
    for number in numbers:
        number = _clean(number)
        if not number:
            continue
        assignment = await number_router.find_customer_by_number(number)
        if assignment is not None and getattr(assignment, "company_id", None):
            return assignment.company_id
    return None


async def call_company(number_router: Any, explicit: Any, *numbers: Any) -> Optional[UUID]:
    """Split mode: the request's tenant (``company=`` first, then our numbers);
    single mode: ``None`` — there is nothing to choose."""
    if not is_split():
        return None
    return company_param(explicit) or await company_for_numbers(number_router, *numbers)


@asynccontextmanager
async def tenant_session_manager(manager: Any, company_id: Optional[Any]) -> AsyncIterator[Any]:
    """A ``SessionManager`` on ``company_id``'s tenant database (split mode); ``manager`` itself in single mode."""
    if not is_split():
        yield manager
        return
    from src.voice.session_manager import SessionManager

    async with tenant_session(company_id) as db:
        yield SessionManager(db, getattr(manager, "_redis", None))
