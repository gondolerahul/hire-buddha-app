import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from datetime import datetime, timedelta
from typing import Optional
from jose import jwt, JWTError
from passlib.context import CryptContext
from src.common.config import settings

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

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

def encrypt_api_key(api_key: str) -> str:
    """Encrypt API key using AES-256-GCM."""
    if not api_key:
        return None
    key = settings.ENCRYPTION_MASTER_KEY.encode()
    if len(key) > 32:
        key = key[:32]
    elif len(key) < 32:
        key = key.ljust(32, b'\0')
    
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, api_key.encode(), None)
    return base64.b64encode(nonce + ciphertext).decode('utf-8')

def decrypt_api_key(encrypted_key: str) -> str:
    """Decrypt API key using AES-256-GCM."""
    if not encrypted_key:
        return None
    key = settings.ENCRYPTION_MASTER_KEY.encode()
    if len(key) > 32:
        key = key[:32]
    elif len(key) < 32:
        key = key.ljust(32, b'\0')
    
    aesgcm = AESGCM(key)
    data = base64.b64decode(encrypted_key)
    nonce = data[:12]
    ciphertext = data[12:]
    return aesgcm.decrypt(nonce, ciphertext, None).decode('utf-8')

