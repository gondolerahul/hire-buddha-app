import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from datetime import datetime, timedelta
from typing import Optional
from jose import jwt, JWTError
from passlib.context import CryptContext
from src.common.config import settings

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

# The ``type`` claim separates a login token from other tokens signed with the
# same key. Only ACCESS_TOKEN_TYPE authenticates API requests (AU-14).
ACCESS_TOKEN_TYPE = "access"
EMAIL_VERIFICATION_TOKEN_TYPE = "email_verification"

# A URL token is what goes in a URL the browser loads by itself (an <audio>,
# <img> or download link, an EventSource), which cannot send a header. It is
# short-lived and good only under one path prefix, so a URL that ends up in a
# log, the history or a Referer does not carry a login (FE-28). Ten minutes,
# because a media element keeps fetching ranges while it plays.
URL_TOKEN_TYPE = "url"
URL_TOKEN_TTL_SECONDS = 600
# The prefixes a URL token may be minted for — the routes that read ``?token=``.
# "/stream/" is the live audio and video sockets' handshake (GW-04).
URL_TOKEN_SCOPES = ("/api/v1/artifacts/", "/api/v1/ai/executions/", "/stream/")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> Optional[dict]:
    """Decode and verify a JWT token. Returns the payload if valid, None otherwise."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None

# ── Stored-credential encryption (AU-24) ─────────────────────────────────
# AES-256-GCM. The key is derived from ENCRYPTION_MASTER_KEY with HKDF-SHA256;
# a ciphertext made that way starts with "v2:". An unprefixed ciphertext was
# made before AU-24 with the master key's bytes truncated or NUL-padded to 32
# and still decrypts, so stored credentials keep working; running
# scripts/rotate_encryption_key.py rewrites them as v2 (and moves them to a new
# master key when one is given).
CIPHERTEXT_V2 = "v2:"
_HKDF_SALT = b"hirebuddha/stored-credentials"
_HKDF_INFO = b"aes-256-gcm v2"


def _v2_key(master: str) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(algorithm=hashes.SHA256(), length=32, salt=_HKDF_SALT,
                info=_HKDF_INFO).derive(master.encode())


def _legacy_key(master: str) -> bytes:
    key = master.encode()
    return key[:32] if len(key) > 32 else key.ljust(32, b"\0")


def encrypt_api_key(api_key: str, *, master: Optional[str] = None) -> str:
    """Encrypt a stored credential: ``v2:`` + base64(nonce + AES-256-GCM ciphertext).

    ``master`` overrides ENCRYPTION_MASTER_KEY (the rotation script's new key).
    """
    if not api_key:
        return None
    aesgcm = AESGCM(_v2_key(master if master is not None else settings.ENCRYPTION_MASTER_KEY))
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, api_key.encode(), None)
    return CIPHERTEXT_V2 + base64.b64encode(nonce + ciphertext).decode("utf-8")


def decrypt_api_key(encrypted_key: str, *, master: Optional[str] = None) -> str:
    """Decrypt a stored credential, v2 or pre-AU-24; ``master`` as in ``encrypt_api_key``."""
    if not encrypted_key:
        return None
    master = master if master is not None else settings.ENCRYPTION_MASTER_KEY
    if encrypted_key.startswith(CIPHERTEXT_V2):
        key, body = _v2_key(master), encrypted_key[len(CIPHERTEXT_V2):]
    else:
        key, body = _legacy_key(master), encrypted_key
    data = base64.b64decode(body)
    return AESGCM(key).decrypt(data[:12], data[12:], None).decode("utf-8")

