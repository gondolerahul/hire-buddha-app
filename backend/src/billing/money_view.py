"""Who sees which money (Phase 15 T9-3, REQ-BL-3, Q7; tech design §5.2).

Staff (``app_admin``, ``app_user``) see cost and billed. Everyone else — the
tenant's and the partner's people — sees **billed only**, in the currency of
their company: never a provider cost, a margin or a formula.

One layer does it for every JSON response of the platform API:
:class:`MoneyViewMiddleware`. ``get_current_user`` records who is asking
(``request.state.money_viewer``); for a non-staff viewer the middleware

* drops every cost field — a key containing ``cost`` that is not a
  ``billed…`` key (``total_cost_usd``, ``calculated_cost``, ``cost_usd``,
  ``base_cost``, ``estimated_cost`` …) and ``margin``;
* shows each USD billed amount (``billed_amount``, ``billed_usd``, …) in the
  viewer's billing currency at today's rate, with ``billed_currency`` beside it.

Business data is not platform money and is never touched: the Data API
(``/data``) and the records API (``/api/v1/records``) pass through. Server-sent
events are not JSON responses: their cost frames go through :func:`sse_frame`.
``tests/integration/test_money_views.py`` is the contract: a non-staff caller
of the money endpoints of §5.2 gets no cost field.
"""
from __future__ import annotations

import json
import logging
import time
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

STAFF_ROLES = frozenset({"app_admin", "app_user"})
COST_WORDS = ("cost",)
COST_KEYS = frozenset({"margin", "internal_cost", "spf", "sales_partner_fee_pct"})
USD_BILLED_KEYS = frozenset({"billed_amount", "billed_usd", "total_billed_usd", "billed_amount_usd", "total_billed"})
PASS_THROUGH = ("/data/", "/api/v1/records", "/api/v1/admin/", "/api/v1/data-keys")
CACHE_SECONDS = 60.0

_currency: Dict[str, Tuple[str, float]] = {}
_rates: Dict[str, Tuple[Any, float]] = {}


def is_staff(role: Any) -> bool:
    return str(getattr(role, "value", role) or "") in STAFF_ROLES


def is_cost_key(key: str) -> bool:
    k = key.lower()
    if k.startswith("billed") or k == "total_billing":
        return False
    return k in COST_KEYS or any(word in k for word in COST_WORDS)


def remember_viewer(request: Any, user: Any) -> None:
    """Called by ``get_current_user``: who this response is for."""
    try:
        request.state.money_viewer = (str(getattr(user.role, "value", user.role)), user.company_id)
    except Exception:  # noqa: BLE001 - a request without state (tests) is shown as is
        pass


def needs_rate(payload: Any) -> bool:
    if isinstance(payload, dict):
        return any(k in USD_BILLED_KEYS or needs_rate(v) for k, v in payload.items())
    if isinstance(payload, list):
        return any(needs_rate(v) for v in payload)
    return False


def billed_only(payload: Any, rate: Optional[Any] = None) -> Any:
    """``payload`` with no cost field, its USD billed amounts at ``rate`` (a ``currency.Rate``)."""
    if isinstance(payload, list):
        return [billed_only(v, rate) for v in payload]
    if not isinstance(payload, dict):
        return payload
    out: Dict[str, Any] = {}
    converted = False
    for key, value in payload.items():
        if is_cost_key(key):
            continue
        if key in USD_BILLED_KEYS and rate is not None and isinstance(value, (int, float, str)) \
                and not isinstance(value, bool):
            try:
                amount = Decimal(str(value)) * rate.units_per_usd
            except Exception:  # noqa: BLE001 - not a number: shown as is
                out[key] = value
                continue
            out[key] = float(amount) if isinstance(value, (int, float)) else str(amount)
            converted = True
            continue
        out[key] = billed_only(value, rate)
    if converted and "billed_currency" not in out:
        out["billed_currency"] = rate.currency
    return out


async def viewer_rate(company_id: Any) -> Optional[Any]:
    """The viewer's billing currency's rate now (cached a minute)."""
    from sqlalchemy import select

    from src.auth.models import Company
    from src.billing.currency import current_rate
    from src.common.tenancy.session import control_session

    now = time.monotonic()
    key = str(company_id)
    async with control_session() as db:
        hit = _currency.get(key)
        if hit and hit[1] > now:
            currency = hit[0]
        else:
            currency = (await db.execute(select(Company.billing_currency).where(Company.id == company_id))
                        ).scalar_one_or_none() or "INR"
            _currency[key] = (currency, now + CACHE_SECONDS)
        rate_hit = _rates.get(currency)
        if rate_hit and rate_hit[1] > now:
            return rate_hit[0]
        rate = await current_rate(db, currency)
        _rates[currency] = (rate, now + CACHE_SECONDS)
        return rate


def forget() -> None:
    _currency.clear()
    _rates.clear()


# SSE frames whose ``amount_usd`` is a provider cost (``agent.cost.charged``).
COST_FRAMES = frozenset({"cost_charged", "agent.cost.charged"})


async def sse_frame(viewer: Optional[Tuple[str, Any]], frame: Dict[str, Any]) -> Dict[str, Any]:
    """A run's live event as ``viewer`` may see it (the stream's own money view)."""
    if viewer is None or is_staff(viewer[0]) or not isinstance(frame, dict):
        return frame
    if frame.get("type") in COST_FRAMES or frame.get("event") in COST_FRAMES:
        frame = {k: v for k, v in frame.items() if k != "amount_usd"}
    rate = await viewer_rate(viewer[1]) if needs_rate(frame) else None
    return billed_only(frame, rate)


async def sse_data(viewer: Optional[Tuple[str, Any]], data: str) -> str:
    """One SSE ``data:`` payload (JSON text) as ``viewer`` may see it."""
    if viewer is None or is_staff(viewer[0]):
        return data
    try:
        frame = json.loads(data)
    except ValueError:
        return data
    return json.dumps(await sse_frame(viewer, frame), separators=(",", ":"))


class MoneyViewMiddleware:
    """Billed-only JSON for non-staff viewers (pure ASGI, so streams pass untouched)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or any(scope["path"].startswith(p) for p in PASS_THROUGH):
            await self.app(scope, receive, send)
            return
        start: Dict[str, Any] = {}
        chunks: list = []
        holding = False

        async def send_wrapper(message: Dict[str, Any]) -> None:
            nonlocal holding
            if message["type"] == "http.response.start":
                viewer = (scope.get("state") or {}).get("money_viewer")
                headers = dict((k.lower(), v) for k, v in message.get("headers") or [])
                is_json = headers.get(b"content-type", b"").startswith(b"application/json")
                if viewer is not None and not is_staff(viewer[0]) and is_json:
                    holding = True
                    start.update(message)
                    return
                await send(message)
                return
            if message["type"] == "http.response.body" and holding:
                chunks.append(message.get("body", b""))
                if message.get("more_body"):
                    return
                await self._send_viewed(scope, send, start, b"".join(chunks))
                return
            await send(message)

        await self.app(scope, receive, send_wrapper)

    async def _send_viewed(self, scope: Any, send: Any, start: Dict[str, Any], body: bytes) -> None:
        viewer = scope["state"]["money_viewer"]
        try:
            payload = json.loads(body) if body else None
            rate = await viewer_rate(viewer[1]) if needs_rate(payload) else None
            body = json.dumps(billed_only(payload, rate), separators=(",", ":")).encode()
        except Exception:  # noqa: BLE001 - a body that cannot be read is not passed through either
            logger.warning("money view of %s failed; the body is withheld", scope.get("path"), exc_info=True)
            body = json.dumps({"detail": "This response could not be prepared."}).encode()
            start = {**start, "status": 500}
        headers = [(k, v) for k, v in start.get("headers") or [] if k.lower() != b"content-length"]
        headers.append((b"content-length", str(len(body)).encode()))
        await send({**start, "headers": headers})
        await send({"type": "http.response.body", "body": body})
