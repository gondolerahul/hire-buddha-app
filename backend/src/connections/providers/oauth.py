"""OAuth 2.0 providers: Google, Microsoft, X and LinkedIn (Phase 14 WS5 5.4).

Authorisation code with PKCE where the provider supports it, refresh tokens
where it issues them. Each provider's ``accounts`` turns the token into the
accounts a business chooses from: the signed-in mailbox or Drive (Google,
Microsoft), the X user, the LinkedIn organisations the member administers.
"""
from __future__ import annotations

import base64
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from src.connections.providers.base import (
    Account, AccessToken, Provider, ProviderError, expires_in, http, raise_for,
)


class OAuth2Provider(Provider):
    authorize_endpoint = ""
    token_endpoint = ""
    revoke_endpoint: Optional[str] = None
    scope_separator = " "
    uses_pkce = True
    client_auth_basic = False                  # client credentials in an Authorization header
    extra_authorize: Dict[str, str] = {}

    def scopes(self, connector: Any) -> List[str]:
        return list(connector.scopes or [])

    async def authorize_url(self, app: Any, connector: Any, *, state: str, redirect_uri: str,
                            code_challenge: Optional[str]) -> str:
        params = {"response_type": "code", "client_id": app.client_id, "redirect_uri": redirect_uri,
                  "state": state, "scope": self.scope_separator.join(self.scopes(connector)),
                  **self.extra_authorize}
        if self.uses_pkce and code_challenge:
            params.update(code_challenge=code_challenge, code_challenge_method="S256")
        return f"{self.endpoint(app, self.authorize_endpoint)}?{urlencode(params)}"

    def endpoint(self, app: Any, url: str) -> str:
        return url

    def _client_auth(self, app: Any, body: Dict[str, Any]) -> Dict[str, str]:
        if self.client_auth_basic:
            raw = f"{app.client_id}:{app.client_secret or ''}".encode()
            return {"Authorization": "Basic " + base64.b64encode(raw).decode()}
        body["client_id"] = app.client_id
        if app.client_secret:
            body["client_secret"] = app.client_secret
        return {}

    async def _token(self, app: Any, body: Dict[str, Any], what: str) -> Dict[str, Any]:
        headers = {"Accept": "application/json", **self._client_auth(app, body)}
        async with http() as client:
            response = await client.post(self.endpoint(app, self.token_endpoint), data=body, headers=headers)
        token = raise_for(response, what)
        if not token.get("access_token"):
            raise ProviderError(f"{what}: the provider sent no access token")
        return token

    @staticmethod
    def secret_from(token: Dict[str, Any], previous: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        secret = dict(previous or {})
        secret["access_token"] = token["access_token"]
        if token.get("refresh_token"):  # some providers rotate it, some send it once
            secret["refresh_token"] = token["refresh_token"]
        return secret

    async def exchange(self, app: Any, connector: Any, params: Dict[str, Any], *, redirect_uri: str,
                       code_verifier: Optional[str]) -> List[Account]:
        if params.get("error"):
            raise ProviderError(f"sign-in was not completed: {params.get('error_description') or params['error']}")
        code = params.get("code")
        if not code:
            raise ProviderError("the provider sent no authorisation code")
        body = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
        if self.uses_pkce and code_verifier:
            body["code_verifier"] = code_verifier
        token = await self._token(app, body, "code exchange")
        self.check_granted(connector, token)
        secret = self.secret_from(token)
        granted = str(token.get("scope") or "").replace(",", " ").split() or self.scopes(connector)
        accounts = await self.accounts(app, connector, secret)
        for account in accounts:
            account.secret = {**secret, **account.secret}
            account.scopes = account.scopes or granted
            account.expires_at = account.expires_at or expires_in(token.get("expires_in"))
        return accounts

    async def accounts(self, app: Any, connector: Any, secret: Dict[str, Any]) -> List[Account]:
        raise NotImplementedError

    def check_granted(self, connector: Any, token: Dict[str, Any]) -> None:
        """Refuse a sign-in that granted less than the connector needs (a provider
        with granular consent overrides it)."""
        return None

    async def refresh(self, app: Any, connector: Any, settings: Dict[str, Any],
                      secret: Dict[str, Any]) -> Optional[tuple[Dict[str, Any], Optional[datetime]]]:
        if not secret.get("refresh_token"):
            return None
        token = await self._token(app, {"grant_type": "refresh_token", "refresh_token": secret["refresh_token"]},
                                  "token refresh")
        return self.secret_from(token, secret), expires_in(token.get("expires_in"))

    async def revoke(self, app: Any, connector: Any, settings: Dict[str, Any], secret: Dict[str, Any]) -> None:
        if not self.revoke_endpoint:
            return None
        token = secret.get("refresh_token") or secret.get("access_token")
        if not token:
            return None
        body: Dict[str, Any] = {"token": token}
        headers = self._client_auth(app, body)
        async with http() as client:
            await client.post(self.endpoint(app, self.revoke_endpoint), data=body, headers=headers)

    async def _get(self, url: str, secret: Dict[str, Any], what: str, **kwargs: Any) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {secret['access_token']}", **kwargs.pop("headers", {})}
        async with http() as client:
            return raise_for(await client.get(url, headers=headers, **kwargs), what)


# What a Google scope is for, said when a person unticks it on Google's consent
# screen (GOOG-E3: people may grant some scopes and not others).
GOOGLE_SCOPE_FEATURES = {
    "https://www.googleapis.com/auth/gmail.modify": "read, label, draft and send your Gmail",
    "https://www.googleapis.com/auth/gmail.send": "send mail from your Gmail",
    "https://www.googleapis.com/auth/drive.file": "open the Drive files you choose and save the files it makes",
    "https://www.googleapis.com/auth/youtube.upload": "upload videos to your channel",
    "https://www.googleapis.com/auth/youtube.readonly": "see your channel's videos and playlists",
    "https://www.googleapis.com/auth/youtube.force-ssl": "manage your channel's playlists and comments",
    "https://www.googleapis.com/auth/yt-analytics.readonly": "see your channel's analytics",
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly": "see your channel's revenue",
    "https://www.googleapis.com/auth/adwords": "manage your Google Ads campaigns",
}
# Google returns these short scopes under their full names.
_GOOGLE_ALIASES = {"email": "https://www.googleapis.com/auth/userinfo.email",
                   "profile": "https://www.googleapis.com/auth/userinfo.profile"}


def missing_google_scopes(requested: List[str], granted: List[str]) -> List[str]:
    """Of ``requested``, the scopes Google's answer did not grant (``openid`` aside)."""
    have = {_GOOGLE_ALIASES.get(scope, scope) for scope in granted}
    return [scope for scope in requested if scope != "openid" and _GOOGLE_ALIASES.get(scope, scope) not in have]


class GoogleProvider(OAuth2Provider):
    name = "google"
    authorize_endpoint = "https://accounts.google.com/o/oauth2/v2/auth"
    token_endpoint = "https://oauth2.googleapis.com/token"
    revoke_endpoint = "https://oauth2.googleapis.com/revoke"
    extra_authorize = {"access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"}

    def check_granted(self, connector: Any, token: Dict[str, Any]) -> None:
        if not token.get("scope"):
            return
        missing = missing_google_scopes(self.scopes(connector), str(token["scope"]).split())
        if missing:
            features = "; ".join(GOOGLE_SCOPE_FEATURES.get(scope, scope.rsplit("/", 1)[-1]) for scope in missing)
            raise ProviderError(f"Google did not grant everything {connector.display_name} needs ({features}). "
                                "Connect again and leave every permission ticked.")

    async def accounts(self, app: Any, connector: Any, secret: Dict[str, Any]) -> List[Account]:
        if connector.id == "youtube_channel":
            return await self._channels(secret)
        if connector.id == "google_ads":
            return await self._ads_customers(secret)
        me = await self._get("https://openidconnect.googleapis.com/v1/userinfo", secret, "reading the account")
        email = me.get("email") or me.get("sub")
        return [Account(external_id=str(me.get("sub") or email), name=str(email), settings={"email": email})]

    async def _channels(self, secret: Dict[str, Any]) -> List[Account]:
        """YouTube: the channels of the signed-in account (YT-E1)."""
        found = await self._get("https://www.googleapis.com/youtube/v3/channels", secret, "listing channels",
                                params={"part": "snippet", "mine": "true"})
        accounts = [Account(external_id=str(item["id"]), name=str((item.get("snippet") or {}).get("title") or item["id"]),
                            settings={"channel_id": item["id"],
                                      "custom_url": (item.get("snippet") or {}).get("customUrl")})
                    for item in found.get("items", []) if item.get("id")]
        if not accounts:
            raise ProviderError("this Google account has no YouTube channel")
        return accounts

    async def _ads_customers(self, secret: Dict[str, Any]) -> List[Account]:
        """Google Ads: the customers the signed-in person can reach directly (GADS-E1).
        No developer token: the access level is the OAuth client's Cloud project's."""
        from src.connections.api_versions import google_ads_version

        found = await self._get(f"https://googleads.googleapis.com/{google_ads_version()}/customers:listAccessibleCustomers",
                                secret, "listing Google Ads accounts")
        accounts = []
        for resource in found.get("resourceNames", []):
            customer = str(resource).rsplit("/", 1)[-1]
            if customer.isdigit():
                shown = f"{customer[:3]}-{customer[3:6]}-{customer[6:]}" if len(customer) == 10 else customer
                accounts.append(Account(external_id=customer, name=f"Google Ads {shown}",
                                        settings={"customer_id": customer}))
        if not accounts:
            raise ProviderError("this Google account can reach no Google Ads account")
        return accounts

    async def test(self, app: Any, connector: Any, settings: Dict[str, Any], secret: Dict[str, Any]) -> Dict[str, Any]:
        me = await self._get("https://openidconnect.googleapis.com/v1/userinfo", secret, "test")
        return {"ok": True, "detail": f"signed in as {me.get('email')}"}


# Microsoft's answers when the tenant lets only an administrator consent to the
# mail permissions (the Microsoft-managed default policy, 04 §2).
_ADMIN_CONSENT_CODES = ("AADSTS65001", "AADSTS90094", "AADSTS90008", "consent_required", "admin_consent_required")
ADMIN_CONSENT_NEEDED = ("Your Microsoft 365 organisation lets only an administrator approve mail access for apps. "
                        "Use 'Admin consent link' and send it to an administrator; once they approve HireBuddha "
                        "for the organisation, connect Outlook again.")


def needs_admin_consent(params: Dict[str, Any]) -> bool:
    text = f"{params.get('error') or ''} {params.get('error_description') or ''}"
    return any(code.lower() in text.lower() for code in _ADMIN_CONSENT_CODES)


class MicrosoftProvider(OAuth2Provider):
    name = "microsoft"
    authorize_endpoint = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
    token_endpoint = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    extra_authorize = {"prompt": "select_account"}

    def endpoint(self, app: Any, url: str) -> str:
        return url.format(tenant=app.settings.get("tenant") or "common")

    async def exchange(self, app: Any, connector: Any, params: Dict[str, Any], *, redirect_uri: str,
                       code_verifier: Optional[str]) -> List[Account]:
        if params.get("error") and needs_admin_consent(params):
            raise ProviderError(ADMIN_CONSENT_NEEDED)
        return await super().exchange(app, connector, params, redirect_uri=redirect_uri, code_verifier=code_verifier)

    @staticmethod
    def admin_consent_url(app: Any, *, state: str, redirect_uri: str) -> str:
        """Where a business's Microsoft 365 administrator grants HireBuddha's
        mail permissions for the whole organisation (MS-E3)."""
        params = {"client_id": app.client_id, "scope": "https://graph.microsoft.com/.default",
                  "redirect_uri": redirect_uri, "state": state}
        return f"https://login.microsoftonline.com/organizations/v2.0/adminconsent?{urlencode(params)}"

    async def accounts(self, app: Any, connector: Any, secret: Dict[str, Any]) -> List[Account]:
        me = await self._get("https://graph.microsoft.com/v1.0/me", secret, "reading the account")
        email = me.get("mail") or me.get("userPrincipalName")
        return [Account(external_id=str(me.get("id")), name=str(email), settings={"email": email})]

    async def test(self, app: Any, connector: Any, settings: Dict[str, Any], secret: Dict[str, Any]) -> Dict[str, Any]:
        me = await self._get("https://graph.microsoft.com/v1.0/me", secret, "test")
        return {"ok": True, "detail": f"signed in as {me.get('mail') or me.get('userPrincipalName')}"}


class XProvider(OAuth2Provider):
    name = "x"
    authorize_endpoint = "https://x.com/i/oauth2/authorize"
    token_endpoint = "https://api.x.com/2/oauth2/token"
    revoke_endpoint = "https://api.x.com/2/oauth2/revoke"
    client_auth_basic = True

    async def accounts(self, app: Any, connector: Any, secret: Dict[str, Any]) -> List[Account]:
        me = (await self._get("https://api.x.com/2/users/me", secret, "reading the account")).get("data") or {}
        return [Account(external_id=str(me.get("id")), name=f"@{me.get('username')}",
                        settings={"username": me.get("username"), "user_id": me.get("id")})]

    async def test(self, app: Any, connector: Any, settings: Dict[str, Any], secret: Dict[str, Any]) -> Dict[str, Any]:
        me = (await self._get("https://api.x.com/2/users/me", secret, "test")).get("data") or {}
        return {"ok": True, "detail": f"@{me.get('username')}"}


class LinkedInProvider(OAuth2Provider):
    name = "linkedin"
    authorize_endpoint = "https://www.linkedin.com/oauth/v2/authorization"
    token_endpoint = "https://www.linkedin.com/oauth/v2/accessToken"
    uses_pkce = False                      # confidential web apps; LinkedIn offers PKCE to native apps only

    @property
    def api_version(self) -> str:
        """The one ``LINKEDIN_API_VERSION`` the tools send too (LI-E1)."""
        from src.connections.api_versions import linkedin_version

        return linkedin_version()

    def _headers(self) -> Dict[str, str]:
        return {"LinkedIn-Version": self.api_version, "X-Restli-Protocol-Version": "2.0.0"}

    async def accounts(self, app: Any, connector: Any, secret: Dict[str, Any]) -> List[Account]:
        acls = await self._get("https://api.linkedin.com/rest/organizationAcls", secret, "listing organisations",
                               params={"q": "roleAssignee", "role": "ADMINISTRATOR", "state": "APPROVED"},
                               headers=self._headers())
        accounts = []
        for element in acls.get("elements", []):
            urn = str(element.get("organization") or "")
            org_id = urn.rsplit(":", 1)[-1]
            if not org_id:
                continue
            org = await self._get(f"https://api.linkedin.com/rest/organizations/{org_id}", secret,
                                  "reading an organisation", headers=self._headers())
            name = org.get("localizedName") or (org.get("name") or {}).get("localized", {}).get("en_US") or urn
            accounts.append(Account(external_id=org_id, name=str(name), settings={"organization_urn": urn}))
        if not accounts:
            raise ProviderError("this LinkedIn member administers no organisation pages")
        return accounts

    async def test(self, app: Any, connector: Any, settings: Dict[str, Any], secret: Dict[str, Any]) -> Dict[str, Any]:
        org_id = str(settings.get("organization_urn", "")).rsplit(":", 1)[-1]
        org = await self._get(f"https://api.linkedin.com/rest/organizations/{org_id}", secret, "test",
                              headers=self._headers())
        return {"ok": True, "detail": org.get("localizedName") or org_id}

    async def access(self, app: Any, connector: Any, settings: Dict[str, Any], secret: Dict[str, Any]) -> AccessToken:
        return AccessToken(access_token=secret.get("access_token"),
                           extra={"organization_urn": settings.get("organization_urn"),
                                  "linkedin_version": self.api_version})
