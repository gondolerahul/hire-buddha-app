"""GW-01: each source's signature scheme accepts its own signature and nothing else.

Every check before was ``return True``. Here each source is signed the way its
provider signs, then tampered with, unsigned, signed with the wrong secret, and
signed with another source's scheme.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time

import pytest

from src.gateway.models import WEBHOOK_SOURCES
from src.gateway.webhook_signatures import SIGNERS, SignedRequest, verify_signature

SECRET = "provider-secret-0123456789abcdef"
BODY = b'{"event": "x", "n": 1}'
URL = "https://api.example.com/webhook/inbound/00000000-0000-0000-0000-000000000001"


def _hex(data: bytes, algo=hashlib.sha256, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), data, algo).hexdigest()


def _b64(data: bytes, algo=hashlib.sha256, secret: str = SECRET) -> str:
    return base64.b64encode(hmac.new(secret.encode(), data, algo).digest()).decode()


def _signed(source: str, body: bytes = BODY, secret: str = SECRET) -> SignedRequest:
    """A request signed the way ``source``'s provider signs it."""
    now = str(int(time.time()))
    if source in ("github", "facebook", "instagram"):
        return SignedRequest({"x-hub-signature-256": "sha256=" + _hex(body, secret=secret)}, body)
    if source == "linkedin":
        return SignedRequest({"x-li-signature": "hmacsha256=" + _hex(body, secret=secret)}, body)
    if source == "twitter":
        return SignedRequest({"x-twitter-webhooks-signature": "sha256=" + _b64(body, secret=secret)}, body)
    if source == "tiktok":
        s = _hex(now.encode() + b"." + body, secret=secret)
        return SignedRequest({"tiktok-signature": f"t={now},s={s}"}, body)
    if source == "youtube":
        return SignedRequest({"x-hub-signature": "sha1=" + _hex(body, hashlib.sha1, secret)}, body)
    if source == "twilio":
        form = {"CallSid": "CA1", "CallStatus": "completed"}
        data = (URL + "".join(k + form[k] for k in sorted(form))).encode()
        return SignedRequest({"x-twilio-signature": _b64(data, hashlib.sha1, secret)}, body, URL, form)
    if source == "email":
        token = "tok-123"
        payload = {"signature": {"timestamp": now, "token": token,
                                 "signature": _hex((now + token).encode(), secret=secret)}}
        return SignedRequest({}, body, payload=payload)
    if source == "crm":
        data = b"POST" + URL.encode() + body + now.encode()
        return SignedRequest({"x-hubspot-request-timestamp": now,
                              "x-hubspot-signature-v3": _b64(data, secret=secret)}, body, URL)
    # pinterest, generic: the relay signature
    return SignedRequest({"x-hb-signature": "sha256=" + _hex(body, secret=secret)}, body)


def test_every_source_has_a_check() -> None:
    assert set(SIGNERS) == set(WEBHOOK_SOURCES)


@pytest.mark.parametrize("source", WEBHOOK_SOURCES)
def test_the_providers_own_signature_passes(source) -> None:
    assert verify_signature(source, SECRET, _signed(source))


@pytest.mark.parametrize("source", WEBHOOK_SOURCES)
def test_a_wrong_secret_fails(source) -> None:
    assert not verify_signature(source, SECRET, _signed(source, secret="another-secret-xxxxxxxxxx"))


@pytest.mark.parametrize("source", WEBHOOK_SOURCES)
def test_no_signature_fails(source) -> None:
    assert not verify_signature(source, SECRET, SignedRequest({}, BODY, URL))


@pytest.mark.parametrize("source", sorted(set(WEBHOOK_SOURCES) - {"twilio", "email"}))
def test_a_changed_body_fails(source) -> None:
    signed = _signed(source)
    tampered = SignedRequest(signed.headers, BODY.replace(b"1", b"9"), signed.url, signed.form,
                             signed.payload)
    assert not verify_signature(source, SECRET, tampered)


def test_a_changed_twilio_field_fails() -> None:
    signed = _signed("twilio")
    tampered = SignedRequest(signed.headers, signed.body, signed.url,
                             {**signed.form, "CallStatus": "failed"})
    assert not verify_signature("twilio", SECRET, tampered)


@pytest.mark.parametrize("source", WEBHOOK_SOURCES)
def test_the_relay_signature_passes_for_every_source(source) -> None:
    relay = SignedRequest({"x-hb-signature": "sha256=" + _hex(BODY)}, BODY)
    assert verify_signature(source, SECRET, relay)


@pytest.mark.parametrize("source,other", [("github", "twitter"), ("twitter", "github"),
                                          ("crm", "github"), ("youtube", "github")])
def test_another_sources_scheme_does_not_pass(source, other) -> None:
    assert not verify_signature(source, SECRET, _signed(other))


def test_a_stale_timestamp_fails() -> None:
    old = str(int(time.time()) - 3600)
    s = _hex(old.encode() + b"." + BODY)
    assert not verify_signature("tiktok", SECRET, SignedRequest({"tiktok-signature": f"t={old},s={s}"}, BODY))


def test_no_secret_and_unknown_sources_fail() -> None:
    assert not verify_signature("github", "", _signed("github"))
    assert not verify_signature("smoke-signals", SECRET, _signed("generic"))
