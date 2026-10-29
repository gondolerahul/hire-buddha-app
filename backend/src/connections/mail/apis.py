"""Mail through the providers' APIs: Gmail (GOOG-E1) and Microsoft Graph (MS-E1).

Gmail and Outlook connections no longer use IMAP and SMTP. IMAP with an OAuth
token needs Google's broadest scope (``https://mail.google.com/``) or a
separate Exchange Online token; the APIs work with the scopes the connectors
ask for — ``gmail.modify`` (read, label, draft, send) and Graph's
``Mail.ReadWrite`` and ``Mail.Send``. The Mailbox connector keeps IMAP.

Both speak MIME: a message is fetched as its raw RFC 822 bytes (parsed by the
e-mail tools as before) and sent or drafted from the ``email.message`` the
tools build. The tools' ``uid`` is the provider's message id.

* **Gmail**: new mail by ``users.history.list`` from the mailbox's
  ``historyId`` (a history too old to read restarts from the current one).
* **Graph**: new mail by ``receivedDateTime`` in the inbox, with the ids seen
  at the newest time so none is counted twice.
"""
from __future__ import annotations

import base64
import email
from dataclasses import dataclass
from email.message import Message
from typing import Any, Dict, List, Optional, Tuple

from src.connections.providers.base import ProviderError, http, raise_for

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
GRAPH = "https://graph.microsoft.com/v1.0/me"
CLASSIFIED = "AI-Classified"


@dataclass
class Fetched:
    """One message: the provider's id and the parsed MIME message."""
    id: str
    message: Message


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64url(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


class _Api:
    def __init__(self, token: str) -> None:
        self.token = token

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json", **(extra or {})}

    async def _json(self, method: str, url: str, what: str, **kwargs: Any) -> Dict[str, Any]:
        headers = self._headers(kwargs.pop("headers", None))
        async with http() as client:
            return raise_for(await client.request(method, url, headers=headers, **kwargs), what)


class GmailApi(_Api):
    """The Gmail API with ``gmail.modify``."""

    async def _raw(self, message_id: str) -> Fetched:
        body = await self._json("GET", f"{GMAIL}/messages/{message_id}", "reading a message",
                                params={"format": "raw"})
        return Fetched(id=str(message_id), message=email.message_from_bytes(_unb64url(body.get("raw", ""))))

    async def latest(self, count: int, unread_only: bool, folder: str = "INBOX") -> List[Fetched]:
        params: Dict[str, Any] = {"maxResults": max(1, min(int(count), 50)),
                                  "labelIds": "INBOX" if folder.upper() == "INBOX" else folder}
        if unread_only:
            params["q"] = "is:unread"
        listed = await self._json("GET", f"{GMAIL}/messages", "listing messages", params=params)
        return [await self._raw(m["id"]) for m in listed.get("messages", []) if m.get("id")]

    async def position(self) -> str:
        return str((await self._json("GET", f"{GMAIL}/profile", "reading the mailbox")).get("historyId") or "")

    async def since(self, history_id: str, limit: int) -> Tuple[List[Fetched], str]:
        """Messages added to the inbox since ``history_id``, oldest first; the new position."""
        ids: List[str] = []
        page: Optional[str] = None
        newest = history_id
        while True:
            params: Dict[str, Any] = {"startHistoryId": history_id, "historyTypes": "messageAdded",
                                      "labelId": "INBOX"}
            if page:
                params["pageToken"] = page
            try:
                body = await self._json("GET", f"{GMAIL}/history", "reading new mail", params=params)
            except ProviderError as error:
                if "(404)" in str(error):  # a position too old to read: start again from now
                    return [], await self.position()
                raise
            for record in body.get("history", []) or []:
                for added in record.get("messagesAdded", []) or []:
                    message = added.get("message") or {}
                    if message.get("id") and "INBOX" in (message.get("labelIds") or ["INBOX"]) \
                            and message["id"] not in ids:
                        ids.append(message["id"])
            newest = str(body.get("historyId") or newest)
            page = body.get("nextPageToken")
            if not page or len(ids) >= limit:
                break
        return [await self._raw(i) for i in ids[:limit]], newest

    async def send(self, message: Message) -> str:
        sent = await self._json("POST", f"{GMAIL}/messages/send", "sending",
                                json={"raw": _b64url(message.as_bytes())})
        return str(sent.get("id") or "")

    async def draft(self, message: Message) -> str:
        made = await self._json("POST", f"{GMAIL}/drafts", "saving the draft",
                                json={"message": {"raw": _b64url(message.as_bytes())}})
        return str(made.get("id") or "")

    async def classify(self, message_id: str, category: str) -> str:
        """Label the message ``AI-Classified/<category>`` and take it out of the inbox."""
        name = f"{CLASSIFIED}/{category}"
        labels = (await self._json("GET", f"{GMAIL}/labels", "listing labels")).get("labels", [])
        label = next((item["id"] for item in labels if item.get("name") == name), None)
        if label is None:
            label = (await self._json("POST", f"{GMAIL}/labels", "creating the label", json={
                "name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}))["id"]
        await self._json("POST", f"{GMAIL}/messages/{message_id}/modify", "labelling", json={
            "addLabelIds": [label], "removeLabelIds": ["INBOX"]})
        return name


class GraphMail(_Api):
    """Microsoft Graph mail with ``Mail.ReadWrite`` and ``Mail.Send``."""

    async def _mime(self, message_id: str) -> Fetched:
        async with http() as client:
            response = await client.get(f"{GRAPH}/messages/{message_id}/$value", headers=self._headers())
        if response.status_code >= 400:
            raise_for(response, "reading a message")
        return Fetched(id=str(message_id), message=email.message_from_bytes(response.content))

    async def latest(self, count: int, unread_only: bool, folder: str = "INBOX") -> List[Fetched]:
        params: Dict[str, Any] = {"$top": max(1, min(int(count), 50)), "$orderby": "receivedDateTime desc",
                                  "$select": "id"}
        if unread_only:
            params["$filter"] = "isRead eq false"
        box = "inbox" if folder.upper() == "INBOX" else folder
        listed = await self._json("GET", f"{GRAPH}/mailFolders/{box}/messages", "listing messages", params=params)
        return [await self._mime(m["id"]) for m in listed.get("value", []) if m.get("id")]

    async def since(self, cursor: Optional[Dict[str, Any]], limit: int) -> Tuple[List[Fetched], Dict[str, Any]]:
        """Inbox messages received since the cursor (``{"since", "seen"}``), oldest
        first; with no cursor, none, and where the inbox stands now."""
        params: Dict[str, Any] = {"$select": "id,receivedDateTime", "$orderby": "receivedDateTime asc",
                                  "$top": limit}
        if cursor and cursor.get("since"):
            params["$filter"] = f"receivedDateTime ge {cursor['since']}"
        else:
            params.update({"$orderby": "receivedDateTime desc", "$top": 1})
        listed = (await self._json("GET", f"{GRAPH}/mailFolders/inbox/messages", "reading new mail",
                                   params=params)).get("value", [])
        if not cursor or not cursor.get("since"):
            newest = listed[0]["receivedDateTime"] if listed else "1970-01-01T00:00:00Z"
            return [], {"since": newest, "seen": [m["id"] for m in listed]}
        seen = set(cursor.get("seen") or [])
        fresh = [m for m in listed if m.get("id") and m["id"] not in seen]
        if not fresh:
            return [], cursor
        newest = fresh[-1]["receivedDateTime"]
        at_newest = [m["id"] for m in listed if m.get("receivedDateTime") == newest]
        return [await self._mime(m["id"]) for m in fresh], {"since": newest, "seen": at_newest}

    async def _post_mime(self, url: str, message: Message, what: str) -> Dict[str, Any]:
        async with http() as client:
            response = await client.post(url, content=base64.b64encode(message.as_bytes()),
                                         headers=self._headers({"Content-Type": "text/plain"}))
        return raise_for(response, what) if response.content else {}

    async def send(self, message: Message) -> str:
        await self._post_mime(f"{GRAPH}/sendMail", message, "sending")
        return ""

    async def draft(self, message: Message) -> str:
        return str((await self._post_mime(f"{GRAPH}/messages", message, "saving the draft")).get("id") or "")

    async def classify(self, message_id: str, category: str) -> str:
        """Move the message to the ``AI-Classified - <category>`` folder (made when missing)."""
        name = f"{CLASSIFIED} - {category}"
        quoted = name.replace("'", "''")
        found = (await self._json("GET", f"{GRAPH}/mailFolders", "listing folders",
                                  params={"$filter": f"displayName eq '{quoted}'"})).get("value", [])
        folder = found[0]["id"] if found else (await self._json(
            "POST", f"{GRAPH}/mailFolders", "creating the folder", json={"displayName": name}))["id"]
        await self._json("POST", f"{GRAPH}/messages/{message_id}/move", "moving", json={"destinationId": folder})
        return name


def mail_api(kind: Optional[str], token: Optional[str]) -> Optional[_Api]:
    """The API client of a Gmail (``gmail``) or Outlook (``graph``) connection."""
    if not token:
        return None
    if kind == "gmail":
        return GmailApi(token)
    if kind == "graph":
        return GraphMail(token)
    return None


API_OF = {"gmail": "gmail", "outlook_mail": "graph"}
