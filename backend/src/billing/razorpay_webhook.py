"""
Razorpay webhook — ``POST /api/v1/credits/razorpay/webhook`` (BC-I5).

Razorpay calls this server to server. The browser callbacks
(``/credits/topup/verify``) depend on the payer's browser staying open; this
does not. Both credit through :class:`PaymentService`, so a payment is credited
by whichever arrives first and ignored by the other.

Configure it in the Razorpay dashboard with the events ``payment.captured`` and
``payment.failed``, and put the webhook's secret in ``razorpay_keys`` as
``webhook_secret``. The signature (``X-Razorpay-Signature``) is an HMAC-SHA256
of the raw body under that secret. A handled or ignored event is a 200; an
error is a 500, which Razorpay retries.
"""
import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.billing.payment_service import PaymentService, razorpay_signature_valid
from src.billing.razorpay_gateway import get_razorpay_creds
from src.common.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/credits", tags=["Credits & Payments"])


@router.post("/razorpay/webhook", summary="Razorpay server-to-server payment events")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(default=""),
    x_razorpay_event_id: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
):
    body = await request.body()
    secret = (await get_razorpay_creds(db) or {}).get("webhook_secret")
    if not secret:
        raise HTTPException(status_code=503, detail="Razorpay webhook secret not configured")
    if not razorpay_signature_valid(secret, body.decode("utf-8"), x_razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        event = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="Body is not JSON")

    outcome = await PaymentService(db).handle_webhook_event(event)
    logger.info("Razorpay webhook %s (%s): %s", event.get("event"), x_razorpay_event_id, outcome)
    return {"status": outcome}
