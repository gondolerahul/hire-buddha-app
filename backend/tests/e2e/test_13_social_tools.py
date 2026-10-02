"""
E2E tests for Social Media AI Agent Tools.

Tests:
1. Registration: social_api holds the 20 operations
2. Schema validation: each operation has a valid schema
3. Connection CRUD endpoints: social connection API routes
4. Webhook strategies: social media webhook detection
"""
import pytest
import json
from unittest.mock import AsyncMock, patch

# ---------------------------------------------------------------------------
# 1. Tool Registration & Schema Validation
# ---------------------------------------------------------------------------

class TestSocialToolRegistration:
    """Verify all 20 social media tools are registered and have valid schemas."""

    EXPECTED_TOOLS = [
        "linkedin_create_post",
        "linkedin_get_analytics",
        "linkedin_manage_comments",
        "linkedin_get_profile",
        "twitter_create_post",
        "twitter_search",
        "twitter_get_mentions",
        "twitter_get_analytics",
        "facebook_create_post",
        "facebook_get_insights",
        "facebook_manage_comments",
        "facebook_send_message",
        "instagram_publish_media",
        "instagram_get_insights",
        "instagram_manage_comments",
        "instagram_discover_hashtags",
        "google_ads_create_campaign",
        "google_ads_report",
        "google_ads_manage_keywords",
        "google_ads_get_ad_groups",
    ]

    def test_one_social_tool_holds_them_as_operations(self):
        """Since P6.2 the per-verb tools are operations of ``social_api``."""
        from src.ai.tools import ToolRegistry
        from src.ai.tools.social.social_api import operations

        names = set(ToolRegistry._tools)
        assert "social_api" in names
        ops = operations()
        for tool_name in self.EXPECTED_TOOLS:
            assert tool_name not in names, f"'{tool_name}' is registered on its own"
            platform = next(p for p in ops if tool_name.startswith(p + "_"))
            assert tool_name[len(platform) + 1:] in ops[platform], tool_name

    @pytest.mark.parametrize("tool_name", EXPECTED_TOOLS)
    def test_operation_schema_valid(self, tool_name):
        """Each operation's schema is what ``describe`` shows the model."""
        from src.ai.tools.social.social_api import operations

        ops = operations()
        platform = next(p for p in ops if tool_name.startswith(p + "_"))
        op = ops[platform][tool_name[len(platform) + 1:]]
        params = op.get_function_schema()["parameters"]
        assert params.get("type") == "object" and isinstance(params["properties"], dict)
        assert len(params["properties"]) > 0 and len(op.description) > 10


# ---------------------------------------------------------------------------
# 2. SocialMediaTool base class behavior
# ---------------------------------------------------------------------------

class TestSocialMediaToolBase:
    """Test the SocialMediaTool base class context handling."""

    @pytest.mark.asyncio
    async def test_no_company_id_returns_error(self):
        """Tool should return error JSON when no company_id in context."""
        from src.ai.tools.social.linkedin import LinkedInCreatePostTool

        tool = LinkedInCreatePostTool()
        result = await tool.run_with_context(
            json.dumps({"text": "hello"}),
            context={}
        )
        data = json.loads(result)
        assert "error" in data
        assert "company" in data["error"].lower()  # NO_CONTEXT_ERROR (P3.2)

    @pytest.mark.asyncio
    async def test_no_connection_returns_error(self):
        """Tool should return error when no social connection exists."""
        from src.ai.tools.social.linkedin import LinkedInCreatePostTool

        tool = LinkedInCreatePostTool()
        with patch("src.ai.social_connection_service.resolve_connection", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = {}
            result = await tool.run_with_context(
                json.dumps({"text": "hello"}),
                context={"company_id": "00000000-0000-0000-0000-000000000001"}
            )
            data = json.loads(result)
            assert "error" in data
            assert "connection" in data["error"].lower()


# ---------------------------------------------------------------------------
# 3. Webhook Strategy Detection
# ---------------------------------------------------------------------------

class TestSocialWebhookStrategies:
    """Test that new social webhook strategies detect events correctly."""

    def test_facebook_webhook_detection(self):
        """Facebook webhook strategy detects X-Hub-Signature-256."""
        from src.gateway.webhook_inbound import detect_strategy

        headers = {"X-Hub-Signature-256": "sha256=abc123"}
        payload = {"object": "page", "entry": []}
        strategy = detect_strategy(headers, payload)
        assert strategy.get_source() == "facebook"

    def test_instagram_webhook_detection(self):
        """Instagram webhook strategy detects object='instagram' payload."""
        from src.gateway.webhook_inbound import detect_strategy

        headers = {"X-Hub-Signature-256": "sha256=abc123"}
        payload = {"object": "instagram", "entry": []}
        strategy = detect_strategy(headers, payload)
        assert strategy.get_source() == "instagram"

    def test_twitter_webhook_detection(self):
        """Twitter webhook strategy detects for_user_id in payload."""
        from src.gateway.webhook_inbound import detect_strategy

        headers = {}
        payload = {"for_user_id": "12345", "tweet_create_events": []}
        strategy = detect_strategy(headers, payload)
        assert strategy.get_source() == "twitter"

    def test_tiktok_webhook_detection(self):
        """TikTok webhook strategy detects X-TikTok-Signature."""
        from src.gateway.webhook_inbound import detect_strategy

        headers = {"X-TikTok-Signature": "abc123"}
        payload = {"event": "video_publish"}
        strategy = detect_strategy(headers, payload)
        assert strategy.get_source() == "tiktok"

    def test_existing_linkedin_still_works(self):
        """Existing LinkedIn webhook strategy should still detect correctly."""
        from src.gateway.webhook_inbound import detect_strategy

        headers = {"X-Li-Signature": "sha256=xyz"}
        payload = {}
        strategy = detect_strategy(headers, payload)
        assert strategy.get_source() == "linkedin"

    def test_generic_fallback_still_works(self):
        """Unknown webhooks should still fall back to generic strategy."""
        from src.gateway.webhook_inbound import detect_strategy

        headers = {"X-Custom-Header": "val"}
        payload = {"random": "data"}
        strategy = detect_strategy(headers, payload)
        assert strategy.get_source() == "generic"


# ---------------------------------------------------------------------------
# 4. Social Connection Model
# ---------------------------------------------------------------------------

class TestSocialConnectionModel:
    """Test the SocialConnection model can be imported."""

    def test_model_import(self):
        """SocialConnection model imports without error."""
        from src.ai.social_models import SocialConnection
        assert SocialConnection.__tablename__ == "social_connections"

    def test_model_has_expected_columns(self):
        """SocialConnection model has all expected columns."""
        from src.ai.social_models import SocialConnection

        expected = [
            "id", "company_id", "platform", "account_name",
            "encrypted_access_token", "encrypted_refresh_token",
            "token_expires_at", "platform_user_id", "platform_page_id",
            "scopes", "oauth_metadata", "is_active", "status",
            "last_used_at", "created_at", "updated_at",
        ]
        columns = {c.name for c in SocialConnection.__table__.columns}
        for col in expected:
            assert col in columns, f"Missing column: {col}"
