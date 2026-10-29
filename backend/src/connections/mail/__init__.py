"""Mail for the mail connectors (Phase 14 WS5; MAIL-E1, MAIL-E2).

The Mailbox connector (``imap_mailbox``) signs in over IMAP and SMTP with the
business's own (app) password. These helpers tell a refused password from a
network fault, and recognise the Microsoft mailboxes that no longer accept
passwords at all.
"""
from __future__ import annotations

import imaplib
import smtplib
from typing import Any, Dict, Optional

# What mail servers answer when the password itself is refused (Gmail, Exchange,
# Zoho, Yahoo, Dovecot …), and Google's lock-out after repeated refusals.
_REFUSED = ("authenticationfailed", "invalid credentials", "login failed", "authentication failed",
            "authenticate failed", "username and password not accepted", "application-specific password",
            "log in via your web browser", "web login required")

# Microsoft refuses Basic authentication, app passwords included: Exchange Online
# for IMAP and POP since October 2022, Outlook.com since 16 September 2024.
MICROSOFT_HOSTS = frozenset({"outlook.office365.com", "smtp.office365.com", "outlook.office.com",
                             "imap-mail.outlook.com", "smtp-mail.outlook.com", "pop-mail.outlook.com"})
MICROSOFT_DOMAINS = frozenset({"outlook.com", "hotmail.com", "live.com", "msn.com", "outlook.in", "hotmail.co.uk",
                               "live.in", "live.co.uk", "windowslive.com", "passport.com"})
USE_OUTLOOK = ("Microsoft 365 and Outlook.com mailboxes don't accept passwords or app passwords any more. "
               "Connect this mailbox with the Outlook connector instead.")


def password_refused(error: BaseException) -> bool:
    """Whether a mail server's answer means the stored password is no good, as
    opposed to a server that could not be reached."""
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return True
    if isinstance(error, imaplib.IMAP4.abort) or not isinstance(error, imaplib.IMAP4.error):
        return False
    text = str(error).lower()
    return any(marker in text for marker in _REFUSED)


def microsoft_mailbox(settings: Dict[str, Any]) -> Optional[str]:
    """Why this mailbox can't use a password, when it is Microsoft's (by its servers or address)."""
    hosts = {str(settings.get(key) or "").strip().lower() for key in ("imap_host", "smtp_host")}
    domain = str(settings.get("email_address") or "").rsplit("@", 1)[-1].strip().lower()
    if hosts & MICROSOFT_HOSTS or domain in MICROSOFT_DOMAINS:
        return USE_OUTLOOK
    return None
