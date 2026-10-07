"""gateway/webhook_signatures.py — one signature check per webhook source (GW-01).

The endpoint a webhook arrives at names its source, and the request is checked
with that source's scheme and the endpoint's secret — never with a scheme chosen
from the request's own headers, which the sender controls. Every source also
accepts ``X-HB-Signature: sha256=<hex HMAC-SHA256 of the raw body>``, for a
provider that posts through a relay which signs (n8n, Zapier, a small proxy).

A check that cannot be made — no signature, a malformed one, a stale timestamp —
is a failed check. All comparisons are constant-time.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

__all__ = ["SignedRequest", "verify_signature", "SIGNERS"]

# How old a timestamped signature may be (TikTok, HubSpot v3).
MAX_SIGNATURE_AGE_SECONDS = 300


@dataclass(frozen=True)
class SignedRequest:
    """What a check may look at. ``headers`` keys are lower-case."""

    headers: Mapping[str, str]
    body: bytes
    url: str = ""
    form: Mapping[str, str] = field(default_factory=dict)
    payload: Mapping[str, Any] = field(default_factory=dict)
    method: str = "POST"


def _digest(secret: str, data: bytes, algo: Any = hashlib.sha256) -> bytes:
    return hmac.new(secret.encode("utf-8"), data, algo).digest()


def _same(given: str, expected: str) -> bool:
    return bool(given) and hmac.compare_digest(given.strip().encode(), expected.encode())


def _relay(req: SignedRequest, secret: str) -> bool:
    return _same(req.headers.get("x-hb-signature", ""), "sha256=" + _digest(secret, req.body).hex())


def _hub_sha256(req: SignedRequest, secret: str) -> bool:
    """GitHub, and Meta (Facebook, Instagram): ``X-Hub-Signature-256: sha256=<hex>``."""
    return _same(req.headers.get("x-hub-signature-256", ""), "sha256=" + _digest(secret, req.body).hex())


def _websub_sha1(req: SignedRequest, secret: str) -> bool:
    """YouTube's WebSub hub: ``X-Hub-Signature: sha1=<hex>``."""
    expected = "sha1=" + _digest(secret, req.body, hashlib.sha1).hex()
    return _same(req.headers.get("x-hub-signature", ""), expected)


def _linkedin(req: SignedRequest, secret: str) -> bool:
    """``X-LI-Signature``: hex HMAC-SHA256 of the body, with or without ``hmacsha256=``."""
    given = req.headers.get("x-li-signature", "")
    if given.lower().startswith("hmacsha256="):
        given = given[len("hmacsha256="):]
    return _same(given, _digest(secret, req.body).hex())


def _twitter(req: SignedRequest, secret: str) -> bool:
    """X Account Activity: ``sha256=<base64 HMAC-SHA256>`` with the consumer secret."""
    expected = "sha256=" + base64.b64encode(_digest(secret, req.body)).decode()
    return _same(req.headers.get("x-twitter-webhooks-signature", ""), expected)


def _fresh(timestamp: str) -> bool:
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if ts > 10**11:            # milliseconds (HubSpot)
        ts //= 1000
    return abs(time.time() - ts) <= MAX_SIGNATURE_AGE_SECONDS


def _tiktok(req: SignedRequest, secret: str) -> bool:
    """``TikTok-Signature: t=<unix>,s=<hex HMAC-SHA256 of "<t>.<body>">``."""
    raw = req.headers.get("tiktok-signature") or req.headers.get("x-tiktok-signature", "")
    parts = dict(p.split("=", 1) for p in raw.split(",") if "=" in p)
    t, s = parts.get("t", ""), parts.get("s", "")
    if not _fresh(t):
        return False
    return _same(s, _digest(secret, t.encode() + b"." + req.body).hex())


def _twilio(req: SignedRequest, secret: str) -> bool:
    """``X-Twilio-Signature``: base64 HMAC-SHA1 of the URL plus the sorted form fields."""
    data = req.url + "".join(k + str(req.form[k]) for k in sorted(req.form))
    expected = base64.b64encode(_digest(secret, data.encode(), hashlib.sha1)).decode()
    return _same(req.headers.get("x-twilio-signature", ""), expected)


def _mailgun(req: SignedRequest, secret: str) -> bool:
    """Mailgun signs in the body: hex HMAC-SHA256 of ``timestamp + token``."""
    sig = req.payload.get("signature")
    fields = sig if isinstance(sig, Mapping) else req.payload
    timestamp, token = str(fields.get("timestamp", "")), str(fields.get("token", ""))
    given = fields.get("signature") if isinstance(sig, Mapping) else sig
    if not (timestamp and token and isinstance(given, str)) or not _fresh(timestamp):
        return False
    return _same(given, _digest(secret, (timestamp + token).encode()).hex())


def _hubspot_v3(req: SignedRequest, secret: str) -> bool:
    """HubSpot v3: base64 HMAC-SHA256 of method + URL + body + timestamp."""
    timestamp = req.headers.get("x-hubspot-request-timestamp", "")
    if not _fresh(timestamp):
        return False
    data = req.method.encode() + req.url.encode() + req.body + timestamp.encode()
    expected = base64.b64encode(_digest(secret, data)).decode()
    return _same(req.headers.get("x-hubspot-signature-v3", ""), expected)


Check = Callable[[SignedRequest, str], bool]

# Each source's native schemes; the relay signature is accepted for every source.
SIGNERS: dict[str, tuple[Check, ...]] = {
    "github": (_hub_sha256,),
    "facebook": (_hub_sha256,),
    "instagram": (_hub_sha256,),
    "linkedin": (_linkedin,),
    "twitter": (_twitter,),
    "tiktok": (_tiktok,),
    "youtube": (_websub_sha1,),
    "twilio": (_twilio,),
    "email": (_mailgun,),
    "crm": (_hubspot_v3,),
    "pinterest": (),
    "generic": (),
}


def verify_signature(source: str, secret: str, req: SignedRequest) -> bool:
    """True only if ``req`` carries a valid signature for ``source`` under ``secret``."""
    if not secret or source not in SIGNERS:
        return False
    return any(check(req, secret) for check in (*SIGNERS[source], _relay))
