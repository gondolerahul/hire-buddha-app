"""call_admission.py — whether a call may start: one rule, every checkpoint (VT-01, VT-08, HD9).

There were three credit checks on calls and they disagreed. The inbound
webhooks compared ``total_available`` (ignoring the credit other runs hold)
with $0.10 and, on any error, let the call through; until ``2092be4c`` they
could not even run (a ``NameError``, swallowed). The media socket blocked an
outbound call short of credit but let an inbound one through "so nobody
misses an important call", and let any call through when the check failed.
So no inbound call was ever refused for credit.

Per HD9 a call — inbound or outbound, at the provider's webhook, on the media
socket or from a campaign — is admitted by this one rule:

* the company's **free** credit (the wallet minus running runs' holds) must
  reach the ``AGENT`` floor, and the company must be under its monthly spend
  cap (GH-18) — ``CreditService.check_sufficient_for_execution``;
* a balance that cannot be read **refuses** the call (gate
  ``voice_call_credit``, GH-21);
* the company must hold fewer live sessions than its plan's
  ``limit.live_sessions`` (GW-02, :mod:`src.voice.live_sessions`);
* the plan must include the kind of call (Phase 15 T6-2), and the number, when
  given, must not be held for an unpaid balance (NR-4).

Every decision is an event — ``voice.call.admitted`` / ``voice.call.refused``
with the direction and the checkpoint — so refusals can be counted.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["call_refusal", "UNCHECKED"]

UNCHECKED = "The call could not be checked for credit, so it was not connected. Try again shortly."

# What a call needs in the plan, by where it is admitted (Phase 15 T6-2).
_FEATURE_BY_CHECKPOINT = {
    "video": "feature.video.calls",
    "web_audio": "feature.voice.browser_calls",
    "campaign_start": "feature.voice.outbound_campaigns",
    "campaign_call": "feature.voice.outbound_campaigns",
}


HELD = "This number is on hold until the account's balance is paid."


async def call_refusal(db: Any, company_id: Any, *, direction: str, checkpoint: str,
                       number: Optional[str] = None) -> Optional[str]:
    """Why the company may not take or make this call (to or from ``number``) now, or ``None``."""
    from src.ai.core.events import event
    from src.billing.credit_service import CreditService, InsufficientCreditsError
    from src.common.gates import gate_failed

    from src.voice import live_sessions

    context = {"company_id": str(company_id), "direction": direction, "checkpoint": checkpoint}
    await live_sessions.load_limit(db, company_id)          # the plan's limit (Phase 15 T6-2)
    if number:
        from src.billing.rentals import number_held
        if await number_held(db, number):
            event("voice.call.refused", reason="number held", **context)
            return HELD
    feature = _FEATURE_BY_CHECKPOINT.get(checkpoint) or ("feature.voice.inbound" if direction == "inbound" else None)
    if feature:
        from src.billing.features import check_feature
        try:
            locked = await check_feature(db, company_id, feature)
        except Exception:  # noqa: BLE001 - the credit gate below still decides
            locked = None
        if locked:
            event("voice.call.refused", reason=f"plan: {feature}", **context)
            return locked
    if live_sessions.at_cap(company_id):
        # As many live calls as the company may hold (GW-02).
        event("voice.call.refused", reason="live session cap", **context)
        return live_sessions.cap_message(company_id)
    try:
        # The wallet is ok and admission.min_balance.call is free (Phase 15 T4-5, T4-6).
        await CreditService(db).check_sufficient_for_execution(company_id=company_id, entity_type="call",
                                                               floor_key="admission.min_balance.call")
    except InsufficientCreditsError as exc:
        logger.warning("Call refused (%s, %s) for company %s: %s", direction, checkpoint, company_id, exc)
        event("voice.call.refused", reason=str(exc)[:300], **context)
        return str(exc)
    except Exception as exc:                                                # noqa: BLE001
        gate_failed("voice_call_credit", exc, **context)
        event("voice.call.refused", reason="credit check failed", **context)
        return UNCHECKED
    event("voice.call.admitted", **context)
    return None
