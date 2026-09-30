"""Email-verification and password-reset tokens and emails (AU-06, AU-08).

Both tokens are JWTs signed with ``SECRET_KEY`` and told apart from login
tokens by ``type`` (``_authenticate_user`` accepts only ``"access"``, AU-14).

- Verification: ``type = "email_verification"``, 24 hours.
- Password reset: ``type = "password_reset"``, 30 minutes, and ``pwh`` — a
  fingerprint of the password hash it was issued against. Setting a new
  password changes the hash, so a reset link works once.

The emails are sent after the response (FastAPI background tasks) through the
system SMTP integration. A user who never receives one asks again: the
forgot-password and resend-verification endpoints are the retry. With
``EMAIL_LINKS_IN_LOG`` (local development only) a link that could not be
emailed is written to the log instead of being lost.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import timedelta

from src.common.config import settings
from src.common.email import email_service
from src.common.security import EMAIL_VERIFICATION_TOKEN_TYPE, create_access_token

logger = logging.getLogger(__name__)

PASSWORD_RESET_TOKEN_TYPE = "password_reset"
VERIFICATION_TTL = timedelta(hours=24)
RESET_TTL = timedelta(minutes=30)


def password_fingerprint(hashed_password: str) -> str:
    """A short digest of the stored hash: changes whenever the password does."""
    return hashlib.sha256(hashed_password.encode()).hexdigest()[:16]


def verification_token(email: str) -> str:
    return create_access_token({"sub": email, "type": EMAIL_VERIFICATION_TOKEN_TYPE}, VERIFICATION_TTL)


def reset_token(email: str, hashed_password: str) -> str:
    return create_access_token(
        {"sub": email, "type": PASSWORD_RESET_TOKEN_TYPE, "pwh": password_fingerprint(hashed_password)},
        RESET_TTL,
    )


def frontend_link(path: str, token: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}{path}?token={token}"


async def _send(to_email: str, subject: str, body: str, link: str) -> None:
    sent = await email_service.async_send_email(to_email, subject, body)
    if not sent:
        logger.error("Could not send '%s' to a user: SMTP not configured or unreachable", subject)
        if settings.EMAIL_LINKS_IN_LOG:
            logger.warning("EMAIL_LINKS_IN_LOG: '%s' link for %s: %s", subject, to_email, link)


async def send_verification_email(to_email: str) -> None:
    link = frontend_link("/verify-email", verification_token(to_email))
    body = f"""
    <html><body>
        <h1>Welcome to HireBuddha!</h1>
        <p>Please confirm your email address to finish creating your account:</p>
        <p><a href="{link}">Verify my email</a></p>
        <p>The link works for 24 hours. If you did not sign up, ignore this email.</p>
    </body></html>
    """
    await _send(to_email, "Verify your HireBuddha account", body, link)


async def send_password_reset_email(to_email: str, hashed_password: str) -> None:
    link = frontend_link("/reset-password", reset_token(to_email, hashed_password))
    body = f"""
    <html><body>
        <h1>Reset your HireBuddha password</h1>
        <p>Someone asked to reset the password for this account. If it was you:</p>
        <p><a href="{link}">Choose a new password</a></p>
        <p>The link works once, for 30 minutes. Resetting signs you out everywhere.
        If you did not ask for this, ignore this email; your password is unchanged.</p>
    </body></html>
    """
    await _send(to_email, "Reset your HireBuddha password", body, link)
