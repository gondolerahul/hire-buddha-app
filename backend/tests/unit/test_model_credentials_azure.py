"""Phase 14 WS1 1.5–1.7: model credentials that work from AKS with no key files.

* Claude runs on Vertex, Microsoft Foundry or the Anthropic API, chosen by the
  integration's ``service_metadata.provider`` (else ``ANTHROPIC_PROVIDER``).
  On Foundry with no stored key it sends an Entra token from the workload's
  identity, on every request.
* Azure OpenAI with no stored key does the same.
* Vertex clients take credentials from ``GOOGLE_WIF_CREDENTIAL_FILE`` (an
  ``external_account`` file for workload identity federation) when it is set.
"""
import json

import httpx
import pytest

from src.ai.llm.anthropic_adapter import AnthropicAdapter
from src.ai.llm.azure_adapter import AzureOpenAIAdapter
from src.common import genai_factory
from src.common.config import settings
from src.common.platform import identity
from src.config.models import needs_api_key


class _FakeTokens:
    name = "fake"

    def __init__(self):
        self.scopes = []

    async def token(self, scope):
        self.scopes.append(scope)
        return f"entra-token-{len(self.scopes)}"


@pytest.fixture
def tokens():
    fake = _FakeTokens()
    identity.set_token_source(fake)
    yield fake
    identity.set_token_source(None)


def _claude(meta, api_key=""):
    return AnthropicAdapter(api_key=api_key, model_name="claude-opus-5-5", service_metadata=meta)


# ── Claude ─────────────────────────────────────────────────────────────────


def test_vertex_stays_the_default(monkeypatch):
    import anthropic

    monkeypatch.setattr(settings, "ANTHROPIC_PROVIDER", "vertex")
    monkeypatch.setattr(settings, "GOOGLE_WIF_CREDENTIAL_FILE", "")
    client = _claude({"project_id": "p", "region": "us-east5"})._build_client()
    assert isinstance(client, anthropic.AsyncAnthropicVertex)


def test_the_setting_chooses_where_claude_runs_when_the_integration_does_not(monkeypatch):
    import anthropic

    monkeypatch.setattr(settings, "ANTHROPIC_PROVIDER", "anthropic")
    assert isinstance(_claude({}, api_key="sk-test")._build_client(), anthropic.AsyncAnthropic)
    with pytest.raises(ValueError, match="API key"):
        _claude({})._build_client()


def test_an_unknown_provider_is_refused():
    with pytest.raises(ValueError, match="vertex, foundry, anthropic"):
        _claude({"provider": "bedrock"})._build_client()


def test_foundry_needs_a_resource_or_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "FOUNDRY_ENDPOINT", "")
    with pytest.raises(ValueError, match="resource"):
        _claude({"provider": "foundry"}, api_key="k")._build_client()


async def test_foundry_with_a_key_sends_the_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_FOUNDRY_RESOURCE", raising=False)
    seen = await _one_request(_claude({"provider": "foundry", "resource": "ai-hb-dev-0000"}, api_key="fk"))
    assert seen.url.host == "ai-hb-dev-0000.services.ai.azure.com"
    assert seen.url.path == "/anthropic/v1/messages"
    assert seen.headers.get("x-api-key") == "fk" and "authorization" not in seen.headers


async def test_foundry_without_a_key_sends_a_fresh_entra_token(monkeypatch, tokens):
    monkeypatch.delenv("ANTHROPIC_FOUNDRY_RESOURCE", raising=False)
    monkeypatch.delenv("ANTHROPIC_FOUNDRY_API_KEY", raising=False)
    adapter = _claude({"provider": "foundry", "foundry_endpoint": "https://res.services.ai.azure.com/anthropic/"})
    first = await _one_request(adapter)
    second = await _one_request(adapter)
    assert first.headers["authorization"] == "Bearer entra-token-1"
    assert second.headers["authorization"] == "Bearer entra-token-2"
    assert tokens.scopes == [identity.COGNITIVE_SERVICES_SCOPE] * 2
    assert "x-api-key" not in first.headers


async def _one_request(adapter):
    """Build the adapter's client on a transport that records the request."""
    seen = {}

    def handler(request):
        seen["request"] = request
        return httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn",
            "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}})

    client = adapter._build_client()
    client = client.with_options(http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await client.messages.create(model="claude-opus-5-5", max_tokens=16,
                                 messages=[{"role": "user", "content": "hi"}])
    return seen["request"]


def test_vertex_uses_the_federation_file_when_set(monkeypatch, tmp_path):
    path = _external_account_file(tmp_path)
    monkeypatch.setattr(settings, "GOOGLE_WIF_CREDENTIAL_FILE", str(path))
    genai_factory._credentials_cache.clear()
    try:
        client = _claude({"provider": "vertex", "project_id": "p", "region": "us-east5"})._build_client()
        from google.auth import identity_pool

        assert isinstance(client.credentials, identity_pool.Credentials)
        assert genai_factory.google_credentials() is client.credentials  # one object, refreshed by itself
    finally:
        genai_factory._credentials_cache.clear()


def test_gemini_clients_get_the_federation_credentials(monkeypatch, tmp_path):
    from google import genai

    captured = {}
    monkeypatch.setattr(genai, "Client", lambda **kwargs: captured.update(kwargs) or "client")
    monkeypatch.setattr(settings, "GOOGLE_WIF_CREDENTIAL_FILE", str(_external_account_file(tmp_path)))
    genai_factory._credentials_cache.clear()
    try:
        genai_factory.build_vertex_genai_client_sync({"project_id": "p", "region": "asia-south1"})
    finally:
        genai_factory._credentials_cache.clear()
    assert captured["vertexai"] is True and captured["credentials"] is not None

    monkeypatch.setattr(settings, "GOOGLE_WIF_CREDENTIAL_FILE", "")
    captured.clear()
    genai_factory.build_vertex_genai_client_sync({"project_id": "p"})
    assert "credentials" not in captured  # Application Default Credentials, as before


def _external_account_file(tmp_path):
    token = tmp_path / "token"
    token.write_text("projected-service-account-token")
    path = tmp_path / "wif.json"
    path.write_text(json.dumps({
        "type": "external_account",
        "audience": "//iam.googleapis.com/projects/1/locations/global/workloadIdentityPools/aks/providers/hb-dev",
        "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
        "token_url": "https://sts.googleapis.com/v1/token",
        "credential_source": {"file": str(token)},
    }))
    return path


# ── Azure OpenAI ───────────────────────────────────────────────────────────


async def test_azure_openai_without_a_key_uses_the_managed_identity(tokens):
    adapter = AzureOpenAIAdapter(api_key="", model_name="gpt-4o", service_metadata={
        "azure_endpoint": "https://oai-hb-dev.openai.azure.com/", "auth": "managed_identity"})
    seen = {}

    def handler(request):
        seen["request"] = request
        return httpx.Response(200, json={"id": "c", "object": "chat.completion", "created": 0, "model": "gpt-4o",
                                         "choices": [{"index": 0, "finish_reason": "stop",
                                                      "message": {"role": "assistant", "content": "ok"}}]})

    client = adapter._build_client().with_options(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
    assert seen["request"].headers["authorization"] == "Bearer entra-token-1"
    assert "api-key" not in seen["request"].headers


def test_azure_openai_with_a_key_keeps_it(tokens):
    client = AzureOpenAIAdapter(api_key="k", model_name="gpt-4o", service_metadata={
        "azure_endpoint": "https://oai-hb-dev.openai.azure.com/"})._build_client()
    assert client.api_key == "k" and tokens.scopes == []


def test_a_managed_identity_integration_needs_no_stored_key():
    assert needs_api_key("azure_openai") is True
    assert needs_api_key("azure_openai", {"auth": "managed_identity"}) is False
    assert needs_api_key("azure_openai", {"auth": "Entra"}) is False
    assert needs_api_key("google") is False


async def test_no_workload_identity_says_what_to_do(monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_PROFILE", "local")
    monkeypatch.setattr(settings, "WORKLOAD_IDENTITY_BACKEND", "")
    identity.set_token_source(None)
    try:
        with pytest.raises(Exception, match="store an API key"):
            await identity.token_provider()()
    finally:
        identity.set_token_source(None)
