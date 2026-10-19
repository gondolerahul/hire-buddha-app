"""GitHub through the HireBuddha GitHub App (Phase 14 WS5 5.4, tech spec §10.5, §11.3).

The owner installs the App on the repositories they choose
(``https://github.com/apps/<slug>/installations/new?state=…``); GitHub sends
the browser back with ``installation_id``. The connection keeps that id and
no secret of its own: tokens are minted per use — an App JWT (RS256, the App's
private key from the vault) exchanged for a one-hour installation token —
and cached in memory until five minutes before they expire. Disconnecting
uninstalls the App from that account.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

from src.connections.providers.base import Account, AccessToken, Provider, ProviderError, http, raise_for

API = "https://api.github.com"
_tokens: Dict[Tuple[str, str], Tuple[str, datetime]] = {}


def app_jwt(app: Any, now: Optional[float] = None) -> str:
    from jose import jwt

    key = app.secret("private_key")
    app_id = app.settings.get("app_id") or app.client_id
    if not key:
        raise ProviderError("HireBuddha's GitHub App has no private key (private_key_ref)")
    issued = int(now or time.time()) - 60   # clock skew allowance, as GitHub documents
    return jwt.encode({"iat": issued, "exp": issued + 540, "iss": str(app_id)}, key, algorithm="RS256")


def _headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


class GitHubAppProvider(Provider):
    name = "github"

    async def authorize_url(self, app: Any, connector: Any, *, state: str, redirect_uri: str,
                            code_challenge: Optional[str]) -> str:
        slug = app.settings.get("app_slug")
        if not slug:
            raise ProviderError("HireBuddha's GitHub App has no app_slug")
        return f"https://github.com/apps/{slug}/installations/new?{urlencode({'state': state})}"

    async def exchange(self, app: Any, connector: Any, params: Dict[str, Any], *, redirect_uri: str,
                       code_verifier: Optional[str]) -> List[Account]:
        installation_id = str(params.get("installation_id") or "")
        if not installation_id.isdigit():
            raise ProviderError("GitHub sent no installation (was the App installed?)")
        async with http() as client:
            found = raise_for(await client.get(f"{API}/app/installations/{installation_id}",
                                               headers=_headers(app_jwt(app))), "reading the installation")
        account = found.get("account") or {}
        return [Account(external_id=installation_id, name=str(account.get("login") or installation_id),
                        scopes=[f"{k}:{v}" for k, v in (found.get("permissions") or {}).items()],
                        settings={"installation_id": installation_id, "account_login": account.get("login"),
                                  "account_type": account.get("type"),
                                  "repository_selection": found.get("repository_selection")})]

    async def access(self, app: Any, connector: Any, settings: Dict[str, Any], secret: Dict[str, Any]) -> AccessToken:
        installation_id = str(settings["installation_id"])
        cached = _tokens.get((app.ref, installation_id))
        if cached and cached[1] - timedelta(minutes=5) > datetime.utcnow():
            return AccessToken(access_token=cached[0], expires_at=cached[1],
                               extra={"installation_id": installation_id})
        async with http() as client:
            body = raise_for(await client.post(f"{API}/app/installations/{installation_id}/access_tokens",
                                               headers=_headers(app_jwt(app))), "minting a token")
        expires = datetime.strptime(body["expires_at"], "%Y-%m-%dT%H:%M:%SZ") if body.get("expires_at") \
            else datetime.utcnow() + timedelta(hours=1)
        _tokens[(app.ref, installation_id)] = (body["token"], expires)
        return AccessToken(access_token=body["token"], expires_at=expires, extra={"installation_id": installation_id})

    async def test(self, app: Any, connector: Any, settings: Dict[str, Any], secret: Dict[str, Any]) -> Dict[str, Any]:
        token = await self.access(app, connector, settings, secret)
        async with http() as client:
            repos = raise_for(await client.get(f"{API}/installation/repositories", params={"per_page": 1},
                                               headers=_headers(token.access_token or "")), "test")
        return {"ok": True, "detail": f"{repos.get('total_count', 0)} repositories"}

    async def revoke(self, app: Any, connector: Any, settings: Dict[str, Any], secret: Dict[str, Any]) -> None:
        installation_id = str(settings.get("installation_id") or "")
        if not installation_id:
            return
        _tokens.pop((app.ref, installation_id), None)
        async with http() as client:
            response = await client.delete(f"{API}/app/installations/{installation_id}", headers=_headers(app_jwt(app)))
        if response.status_code not in (204, 404):
            raise_for(response, "uninstalling the App")
