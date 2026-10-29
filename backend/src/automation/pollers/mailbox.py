"""The mailbox poller: ``email.received`` for each new message (Phase 14 WS3 3.13).

IMAP UIDs in INBOX: the cursor is ``{uid_validity, last_uid}``. A server that
renumbered its mailbox (a new UIDVALIDITY) starts again from where it stands.
At most ``BATCH`` messages a poll, oldest first; the rest come next time.
IMAP is the Mailbox connection's (password); Gmail and Outlook connections are
read through the Gmail API and Microsoft Graph (``connections/mail/apis.py``).
"""
from __future__ import annotations

import asyncio
import email
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.automation.pollers import Polled

BATCH = 20
BODY_LIMIT = 5000


class MailboxPoller:
    name = "mailbox"
    connectors = ("imap_mailbox", "gmail", "outlook_mail")
    event_prefix = "email."

    def _login(self, credential: Any):
        from src.ai.tools.email.email_tool import OAuthBearer, _get_imap_connection

        extra = credential.extra or {}
        password = extra.get("password")
        if credential.access_token and not password:
            password = OAuthBearer(credential.access_token)
        host = extra.get("imap_host") or {"gmail": "imap.gmail.com",
                                          "outlook_mail": "outlook.office365.com"}.get(extra.get("connector"), "")
        address = extra.get("email_address") or extra.get("email")
        return _get_imap_connection(host, int(extra.get("imap_port") or 993), address, password)

    def _poll_sync(self, credential: Any, cursor: Optional[Dict[str, Any]]) -> Tuple[List[Polled], Dict[str, Any]]:
        from src.ai.tools.email.email_tool import _parse_email_body

        conn = self._login(credential)
        try:
            status, data = conn.select("INBOX", readonly=True)
            if status != "OK":
                raise RuntimeError("the mailbox's INBOX could not be opened")
            uid_validity = int(conn.untagged_responses.get("UIDVALIDITY", [b"0"])[0])
            status, data = conn.uid("SEARCH", None, "ALL")
            uids = [int(u) for u in (data[0] or b"").split()] if status == "OK" else []
            latest = max(uids) if uids else 0
            if not cursor or int(cursor.get("uid_validity") or 0) != uid_validity:
                return [], {"uid_validity": uid_validity, "last_uid": latest,
                            "last_poll_at": datetime.utcnow().isoformat()}
            last = int(cursor.get("last_uid") or 0)
            new = sorted(u for u in uids if u > last)[:BATCH]
            items: List[Polled] = []
            for uid in new:
                status, msg_data = conn.uid("FETCH", str(uid).encode(), "(BODY.PEEK[])")
                if status != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                    continue
                message = email.message_from_bytes(msg_data[0][1])
                body = _parse_email_body(message)
                items.append(Polled(
                    event_type="email.received", dedupe_key=f"email:{uid_validity}:{uid}:{message.get('Message-ID', '')}",
                    data={"uid": uid, "message_id": message.get("Message-ID", ""), "from": message.get("From", ""),
                          "to": message.get("To", ""), "subject": message.get("Subject", ""),
                          "date": message.get("Date", ""), "body": body[:BODY_LIMIT],
                          "truncated": len(body) > BODY_LIMIT}))
            return items, {"uid_validity": uid_validity, "last_uid": max(new) if new else last,
                           "last_poll_at": datetime.utcnow().isoformat()}
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def refused(connection: Any, error: BaseException) -> bool:
        """The server refused a Mailbox connection's password (MAIL-E1): stop polling
        it until reconnected. OAuth mailboxes refresh through the token broker."""
        from src.connections.mail import password_refused

        return connection.connector_id == "imap_mailbox" and password_refused(error)

    async def _poll_api(self, api: Any, connection: Any, cursor: Optional[Dict[str, Any]]
                        ) -> Tuple[List[Polled], Dict[str, Any]]:
        """Gmail (history since the mailbox's ``historyId``) and Outlook (received
        since the last poll) through their APIs (GOOG-E1, MS-E1). A first poll, or
        a cursor from the old IMAP path, records where the mailbox stands."""
        from src.ai.tools.email.email_tool import _parse_email_body
        from src.connections.mail.apis import GmailApi

        now = datetime.utcnow().isoformat()
        if isinstance(api, GmailApi):
            if not cursor or not cursor.get("history_id"):
                return [], {"history_id": await api.position(), "last_poll_at": now}
            fetched, newest = await api.since(str(cursor["history_id"]), BATCH)
            new_cursor: Dict[str, Any] = {"history_id": newest, "last_poll_at": now}
        else:
            first = not cursor or not cursor.get("graph")
            fetched, position = await api.since(None if first else cursor["graph"], BATCH)
            new_cursor = {"graph": position, "last_poll_at": now}
            if first:
                return [], new_cursor
        items: List[Polled] = []
        for found in fetched:
            message = found.message
            body = _parse_email_body(message)
            items.append(Polled(
                event_type="email.received",
                dedupe_key=f"email:{connection.connector_id}:{found.id}:{message.get('Message-ID', '')}",
                data={"uid": found.id, "message_id": message.get("Message-ID", ""), "from": message.get("From", ""),
                      "to": message.get("To", ""), "subject": message.get("Subject", ""),
                      "date": message.get("Date", ""), "body": body[:BODY_LIMIT],
                      "truncated": len(body) > BODY_LIMIT}))
        return items, new_cursor

    async def poll(self, connection: Any, credential: Any, cursor: Optional[Dict[str, Any]]
                   ) -> Tuple[List[Polled], Dict[str, Any]]:
        from src.connections.mail.apis import API_OF, mail_api

        credential.extra = {**(credential.extra or {}), "connector": connection.connector_id,
                            **{k: v for k, v in (connection.settings or {}).items() if k != "poll"}}
        api = mail_api(API_OF.get(connection.connector_id), credential.access_token)
        if api is not None:
            items, new_cursor = await self._poll_api(api, connection, cursor)
        else:
            items, new_cursor = await asyncio.to_thread(self._poll_sync, credential, cursor)
        for item in items:
            item.dedupe_key = f"{connection.id}:{item.dedupe_key}"
            item.data["mailbox"] = credential.extra.get("email_address") or credential.extra.get("email")
        return items, new_cursor
