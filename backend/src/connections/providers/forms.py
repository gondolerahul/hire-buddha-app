"""Connections made with a form: a mailbox, an API-key service, an MCP server (Phase 14 WS5 5.4).

The form's ``secret`` fields are sealed; the rest are the connection's settings.
"""
from __future__ import annotations

import asyncio
import imaplib
from typing import Any, Dict

from src.connections.providers.base import Account, AccessToken, Provider, ProviderError, http


def _split(connector: Any, fields: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    from src.connections.catalog import spec

    secret: Dict[str, Any] = {}
    settings: Dict[str, Any] = {}
    for item in spec(connector.id).form:
        value = fields.get(item.name, item.default)
        if item.required and value in (None, ""):
            raise ProviderError(f"{item.label} is required")
        if value in (None, ""):
            continue
        if item.kind == "number":
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ProviderError(f"{item.label} must be a number") from None
        (secret if item.kind == "secret" else settings)[item.name] = value
    return secret, settings


class MailboxProvider(Provider):
    name = "mailbox"

    async def from_form(self, connector: Any, fields: Dict[str, Any]) -> Account:
        secret, settings = _split(connector, fields)
        address = str(settings["email_address"]).strip().lower()
        settings["email_address"] = address
        return Account(external_id=address, name=address, secret=secret, settings=settings)

    async def test(self, app: Any, connector: Any, settings: Dict[str, Any], secret: Dict[str, Any]) -> Dict[str, Any]:
        def login() -> None:
            mailbox = imaplib.IMAP4_SSL(settings.get("imap_host", "imap.gmail.com"), int(settings.get("imap_port", 993)),
                                        timeout=20)
            try:
                mailbox.login(settings["email_address"], secret["password"])
            finally:
                try:
                    mailbox.logout()
                except Exception:  # noqa: BLE001
                    pass

        try:
            await asyncio.to_thread(login)
        except imaplib.IMAP4.error as error:
            raise ProviderError(f"the mailbox refused the sign-in: {error}") from None
        except OSError as error:
            raise ProviderError(f"the mail server could not be reached: {error}") from None
        return {"ok": True, "detail": f"signed in to {settings.get('imap_host')}"}

    async def access(self, app: Any, connector: Any, settings: Dict[str, Any], secret: Dict[str, Any]) -> AccessToken:
        return AccessToken(access_token=None, extra={**settings, "password": secret.get("password")})


class ApiKeyProvider(Provider):
    name = "api_key"

    async def from_form(self, connector: Any, fields: Dict[str, Any]) -> Account:
        secret, settings = _split(connector, fields)
        label = settings.get("service_name") or connector.display_name
        # No outside account to route webhooks by: an empty id has no route.
        return Account(external_id="", name=str(label), secret=secret, settings=settings)

    async def test(self, app: Any, connector: Any, settings: Dict[str, Any], secret: Dict[str, Any]) -> Dict[str, Any]:
        url = (connector.capabilities or {}).get("test_url") or settings.get("base_url")
        if not url:
            return {"ok": True, "detail": "no test address; the key is stored"}
        header = settings.get("header_name") or "Authorization"
        value = secret["api_key"] if header.lower() != "authorization" else f"Bearer {secret['api_key']}"
        async with http(timeout=15) as client:
            response = await client.get(url, headers={header: value})
        if response.status_code in (401, 403):
            raise ProviderError(f"the service refused the key ({response.status_code})")
        return {"ok": response.status_code < 500, "detail": f"HTTP {response.status_code}"}

    async def access(self, app: Any, connector: Any, settings: Dict[str, Any], secret: Dict[str, Any]) -> AccessToken:
        return AccessToken(access_token=secret.get("api_key"), extra=settings)


class McpProvider(Provider):
    """An MCP server over Streamable HTTP: its tools are listed when connected and
    stay unusable until granted (E09-S02)."""
    name = "mcp"

    async def from_form(self, connector: Any, fields: Dict[str, Any]) -> Account:
        secret, settings = _split(connector, fields)
        url = str(settings["url"])
        if not url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise ProviderError("an MCP server's address must be https")
        return Account(external_id=url, name=url, secret=secret, settings=settings)

    async def _rpc(self, settings: Dict[str, Any], secret: Dict[str, Any], method: str,
                   params: Dict[str, Any]) -> Dict[str, Any]:
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        if secret.get("auth_header"):
            headers["Authorization"] = secret["auth_header"]
        async with http(timeout=20) as client:
            response = await client.post(settings["url"], headers=headers,
                                         json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        if response.status_code >= 400:
            raise ProviderError(f"the MCP server answered {response.status_code}")
        text = response.text
        if "text/event-stream" in response.headers.get("content-type", ""):
            data = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
            text = data[-1] if data else "{}"
        import json

        body = json.loads(text or "{}")
        if body.get("error"):
            raise ProviderError(f"the MCP server refused {method}: {body['error'].get('message')}")
        return body.get("result") or {}

    async def test(self, app: Any, connector: Any, settings: Dict[str, Any], secret: Dict[str, Any]) -> Dict[str, Any]:
        info = await self._rpc(settings, secret, "initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "HireBuddha", "version": "1"}})
        tools = await self._rpc(settings, secret, "tools/list", {})
        names = [tool.get("name") for tool in tools.get("tools", [])]
        server = (info.get("serverInfo") or {}).get("name") or settings["url"]
        return {"ok": True, "detail": f"{server}: {len(names)} tools", "tools": names}

    async def access(self, app: Any, connector: Any, settings: Dict[str, Any], secret: Dict[str, Any]) -> AccessToken:
        return AccessToken(access_token=secret.get("auth_header"), extra={"url": settings.get("url")})
