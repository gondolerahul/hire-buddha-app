"""Data API tokens signed by the platform's signer (Phase 14 W4-1, tech spec §9.3).

Locally HS256 with a shared secret; on Azure RS256 by Key Vault, checked with
public keys only (the JWKS). Key Vault is played here by a local RSA key behind
the same client calls the adapter makes.
"""
from __future__ import annotations

import base64
import json
import uuid
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed

from src.common.platform import signing
from src.data_api import tokens

USER = SimpleNamespace(id=uuid.uuid4(), role="tenant_admin")
COMPANY = uuid.uuid4()


@pytest.fixture(autouse=True)
def _fresh_signer():
    signing.set_signer(None)
    yield
    signing.set_signer(None)


def _parts(token):
    head, body, _ = token.split(".")
    pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
    return json.loads(base64.urlsafe_b64decode(pad(head))), json.loads(base64.urlsafe_b64decode(pad(body)))


async def test_a_local_token_is_hs256_and_round_trips():
    token = await tokens.mint_user_token(USER, COMPANY, "acme01")
    header, claims = _parts(token)
    assert (header["alg"], header["kid"]) == ("HS256", "hs256")
    caller = await tokens.decode(token, tenant_key="acme01")
    assert (caller.company_id, caller.actor, caller.schema) == (COMPANY, f"user:{USER.id}", "apply")
    with pytest.raises(tokens.Unauthorized, match="another business"):
        await tokens.decode(token, tenant_key="beta01")


# ── Key Vault, played ────────────────────────────────────────────────────────

class _Vault:
    """Versions of one RSA key; what the adapter's KeyClient / CryptographyClient calls see."""

    def __init__(self):
        self.versions = []
        self.rotate()
        self.sign_calls = 0

    def rotate(self):
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        version = uuid.uuid4().hex
        self.versions.append((f"https://kv.example/keys/data-api-signing/{version}", version, private))

    def key(self, version=None):
        kid, v, private = next(x for x in reversed(self.versions) if version in (None, x[1]))
        numbers = private.public_key().public_numbers()
        to_bytes = lambda i: i.to_bytes((i.bit_length() + 7) // 8, "big")  # noqa: E731
        return SimpleNamespace(id=kid, key=SimpleNamespace(n=to_bytes(numbers.n), e=to_bytes(numbers.e)))

    def private(self, kid):
        return next(p for k, _, p in self.versions if k == kid)


def _play(monkeypatch, vault):
    from src.common.platform.signing import azure_keyvault as kv

    class KeyClient:
        def __init__(self, url, credential):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get_key(self, name, version=None):
            return vault.key(version)

        async def list_properties_of_key_versions(self, name):
            for kid, version, _ in vault.versions:
                yield SimpleNamespace(id=kid, version=version, enabled=True, created_on=None)

    class CryptographyClient:
        def __init__(self, kid, credential):
            self.kid = kid

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def sign(self, algorithm, digest):
            vault.sign_calls += 1
            signature = vault.private(self.kid).sign(digest, padding.PKCS1v15(), Prehashed(hashes.SHA256()))
            return SimpleNamespace(signature=signature)

    monkeypatch.setattr(kv, "KeyClient", KeyClient)
    monkeypatch.setattr(kv, "CryptographyClient", CryptographyClient)
    monkeypatch.setattr(kv.KeyVaultSigner, "_credential", lambda self: object())
    signer = kv.KeyVaultSigner("https://kv.example/", "data-api-signing")
    signing.set_signer(signer)
    return signer


async def test_on_azure_key_vault_signs_rs256_and_the_public_key_checks_it(monkeypatch):
    vault = _Vault()
    signer = _play(monkeypatch, vault)
    token = await tokens.mint_run_token(uuid.uuid4(), SimpleNamespace(id=uuid.uuid4(), capabilities={}), COMPANY, "acme01")
    header, _ = _parts(token)
    assert header["alg"] == "RS256" and header["kid"] == vault.versions[-1][0] and vault.sign_calls == 1
    caller = await tokens.decode(token, tenant_key="acme01")
    assert caller.kind == "run" and vault.sign_calls == 1  # checking signs nothing
    [jwk] = (await signer.jwks())["keys"]
    assert (jwk["kty"], jwk["alg"], jwk["kid"]) == ("RSA", "RS256", header["kid"]) and "d" not in jwk


async def test_a_token_from_the_key_before_a_rotation_still_checks(monkeypatch):
    vault = _Vault()
    signer = _play(monkeypatch, vault)
    old = await tokens.mint_user_token(USER, COMPANY, "acme01")
    vault.rotate()
    signer._read_at = 0.0  # the cache has aged out
    new = await tokens.mint_user_token(USER, COMPANY, "acme01")
    assert _parts(old)[0]["kid"] != _parts(new)[0]["kid"]
    for token in (old, new):
        assert (await tokens.decode(token)).actor == f"user:{USER.id}"


async def test_a_token_signed_any_other_way_is_refused(monkeypatch):
    local = await tokens.mint_user_token(USER, COMPANY, "acme01")     # HS256, the shared secret
    vault = _Vault()
    _play(monkeypatch, vault)
    with pytest.raises(tokens.Unauthorized, match="HS256"):
        await tokens.decode(local)
    good = await tokens.mint_user_token(USER, COMPANY, "acme01")
    head, body, sig = good.split(".")
    stranger = base64.urlsafe_b64encode(json.dumps({**_parts(good)[0], "kid": "https://elsewhere/k/1"})
                                        .encode()).rstrip(b"=").decode()
    with pytest.raises(tokens.Unauthorized, match="unknown key"):
        await tokens.decode(f"{stranger}.{body}.{sig}")
    claims = {**_parts(good)[1], "sch": "apply", "obj": {"*": ["read", "create", "update", "delete"]}}
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    with pytest.raises(tokens.Unauthorized, match="invalid token"):
        await tokens.decode(f"{head}.{forged}.{sig}")
