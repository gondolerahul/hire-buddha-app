"""Meta: Facebook Pages, Instagram and WhatsApp Business (Phase 14 WS5 5.4, tech spec §10.5).

One HireBuddha Meta app. Pages and Instagram: Facebook Login → a long-lived
user token → the Pages the person manages, each with its own Page token
(which does not expire); Instagram business accounts are reached through
their Page. Each chosen Page is subscribed to the app's webhooks
(``subscribed_apps``). WhatsApp: Embedded Signup in the browser returns a code
→ a business token → the WhatsApp Business Accounts it was shared, and their
phone numbers; the WABA is subscribed to the app.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from src.connections.providers.base import Account, AccessToken, Provider, ProviderError, expires_in, http, raise_for

DEFAULT_GRAPH_VERSION = "v26.0"


class MetaProvider(Provider):
    name = "meta"
    uses_pkce = False

    @staticmethod
    def graph(app: Any, path: str) -> str:
        return f"https://graph.facebook.com/{app.settings.get('graph_version') or DEFAULT_GRAPH_VERSION}/{path.lstrip('/')}"

    async def _call(self, method: str, url: str, what: str, **kwargs: Any) -> Dict[str, Any]:
        async with http() as client:
            return raise_for(await client.request(method, url, **kwargs), what)

    async def authorize_url(self, app: Any, connector: Any, *, state: str, redirect_uri: str,
                            code_challenge: Optional[str]) -> str:
        version = app.settings.get("graph_version") or DEFAULT_GRAPH_VERSION
        params = {"client_id": app.client_id, "redirect_uri": redirect_uri, "state": state,
                  "response_type": "code", "scope": ",".join(connector.scopes or [])}
        return f"https://www.facebook.com/{version}/dialog/oauth?{urlencode(params)}"

    async def _long_lived_user_token(self, app: Any, params: Dict[str, Any], redirect_uri: Optional[str]) -> str:
        if params.get("error"):
            raise ProviderError(f"sign-in was not completed: {params.get('error_description') or params['error']}")
        query = {"client_id": app.client_id, "client_secret": app.client_secret or "", "code": params.get("code", "")}
        if redirect_uri:
            query["redirect_uri"] = redirect_uri
        short = await self._call("GET", self.graph(app, "oauth/access_token"), "code exchange", params=query)
        long = await self._call("GET", self.graph(app, "oauth/access_token"), "long-lived token", params={
            "grant_type": "fb_exchange_token", "client_id": app.client_id, "client_secret": app.client_secret or "",
            "fb_exchange_token": short.get("access_token", "")})
        token = long.get("access_token") or short.get("access_token")
        if not token:
            raise ProviderError("Meta sent no access token")
        return token

    async def exchange(self, app: Any, connector: Any, params: Dict[str, Any], *, redirect_uri: str,
                       code_verifier: Optional[str]) -> List[Account]:
        if connector.auth_type == "meta_embedded_signup":
            return await self._whatsapp_accounts(app, params)
        user_token = await self._long_lived_user_token(app, params, redirect_uri)
        pages = await self._call("GET", self.graph(app, "me/accounts"), "listing Pages", params={
            "access_token": user_token, "limit": 100,
            "fields": "id,name,access_token,tasks,instagram_business_account{id,username,name}"})
        accounts: List[Account] = []
        for page in pages.get("data", []):
            secret = {"access_token": page.get("access_token")}
            if connector.id == "instagram_business":
                ig = page.get("instagram_business_account")
                if not ig:
                    continue
                accounts.append(Account(external_id=str(ig["id"]), name=f"@{ig.get('username') or ig.get('name')}",
                                        secret=secret, scopes=list(connector.scopes or []),
                                        settings={"instagram_account_id": ig["id"], "page_id": page["id"],
                                                  "page_name": page.get("name")}))
            else:
                accounts.append(Account(external_id=str(page["id"]), name=str(page.get("name")), secret=secret,
                                        scopes=list(connector.scopes or []),
                                        settings={"page_id": page["id"], "tasks": page.get("tasks", [])}))
        if not accounts:
            raise ProviderError("no Page (or Instagram business account linked to a Page) was shared")
        return accounts

    async def _whatsapp_accounts(self, app: Any, params: Dict[str, Any]) -> List[Account]:
        token = (await self._call("GET", self.graph(app, "oauth/access_token"), "code exchange", params={
            "client_id": app.client_id, "client_secret": app.client_secret or "",
            "code": params.get("code", "")})).get("access_token")
        if not token:
            raise ProviderError("Meta sent no access token")
        debug = await self._call("GET", self.graph(app, "debug_token"), "reading the shared accounts", params={
            "input_token": token, "access_token": f"{app.client_id}|{app.client_secret or ''}"})
        waba_ids: List[str] = []
        for scope in (debug.get("data") or {}).get("granular_scopes", []):
            if scope.get("scope") == "whatsapp_business_management":
                waba_ids.extend(str(t) for t in scope.get("target_ids", []))
        if params.get("waba_id") and str(params["waba_id"]) not in waba_ids:
            waba_ids.append(str(params["waba_id"]))
        accounts: List[Account] = []
        for waba_id in dict.fromkeys(waba_ids):
            numbers = await self._call("GET", self.graph(app, f"{waba_id}/phone_numbers"), "listing numbers",
                                       params={"access_token": token,
                                               "fields": "id,display_phone_number,verified_name"})
            for number in numbers.get("data", []):
                accounts.append(Account(
                    external_id=str(number["id"]),
                    name=f"{number.get('display_phone_number')} ({number.get('verified_name') or 'WhatsApp'})",
                    secret={"access_token": token}, scopes=["whatsapp_business_management",
                                                             "whatsapp_business_messaging"],
                    settings={"waba_id": waba_id, "phone_number_id": number["id"],
                              "display_phone_number": number.get("display_phone_number")}))
        if not accounts:
            raise ProviderError("no WhatsApp Business number was shared")
        return accounts

    async def after_connect(self, app: Any, connector: Any, settings: Dict[str, Any],
                            secret: Dict[str, Any]) -> Dict[str, Any]:
        token = secret.get("access_token")
        if connector.auth_type == "meta_embedded_signup":
            await self._call("POST", self.graph(app, f"{settings['waba_id']}/subscribed_apps"),
                             "subscribing the WhatsApp account", params={"access_token": token})
            return {"subscribed": ["messages"]}
        fields = (connector.capabilities or {}).get("webhook_fields") or ["feed"]
        await self._call("POST", self.graph(app, f"{settings['page_id']}/subscribed_apps"), "subscribing the Page",
                         params={"access_token": token, "subscribed_fields": ",".join(fields)})
        return {"subscribed": fields}

    async def test(self, app: Any, connector: Any, settings: Dict[str, Any], secret: Dict[str, Any]) -> Dict[str, Any]:
        token = secret.get("access_token")
        if connector.auth_type == "meta_embedded_signup":
            number = await self._call("GET", self.graph(app, settings["phone_number_id"]), "test",
                                      params={"access_token": token, "fields": "display_phone_number,quality_rating"})
            return {"ok": True, "detail": f"{number.get('display_phone_number')} quality {number.get('quality_rating')}"}
        target = settings.get("instagram_account_id") or settings["page_id"]
        found = await self._call("GET", self.graph(app, str(target)), "test",
                                 params={"access_token": token, "fields": "id,name,username"})
        return {"ok": True, "detail": found.get("name") or found.get("username") or found.get("id")}

    async def revoke(self, app: Any, connector: Any, settings: Dict[str, Any], secret: Dict[str, Any]) -> None:
        token = secret.get("access_token")
        target = settings.get("waba_id") if connector.auth_type == "meta_embedded_signup" else settings.get("page_id")
        if token and target:
            await self._call("DELETE", self.graph(app, f"{target}/subscribed_apps"), "unsubscribing",
                             params={"access_token": token})

    async def access(self, app: Any, connector: Any, settings: Dict[str, Any], secret: Dict[str, Any]) -> AccessToken:
        return AccessToken(access_token=secret.get("access_token"),
                           extra={k: settings.get(k) for k in ("page_id", "instagram_account_id", "waba_id",
                                                              "phone_number_id") if settings.get(k)})


def embedded_signup_params(app: Any, state: str) -> Dict[str, Any]:
    """What the browser's Facebook SDK needs to open Embedded Signup."""
    config_id = app.settings.get("config_id")
    if not config_id:
        raise ProviderError("HireBuddha's Meta app has no Embedded Signup configuration (config_id)")
    # A Multi-Partner Solution (HireBuddha as Tech Provider with a Solution
    # Partner, e.g. Tata): its id makes the flow grant the business's WhatsApp
    # assets to both partners and bill messages on the partner's credit line.
    setup: Dict[str, Any] = {}
    if app.settings.get("solution_id"):
        setup["solutionID"] = str(app.settings["solution_id"])
    return {"app_id": app.client_id, "config_id": config_id, "state": state,
            "graph_version": app.settings.get("graph_version") or DEFAULT_GRAPH_VERSION,
            "extras": {"setup": setup, "featureType": "", "sessionInfoVersion": "3"}}
