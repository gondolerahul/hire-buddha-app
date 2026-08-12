"""
E2E tests for the Headless Browser Tool.

Tests:
1. Tool registration: 'headless_browser' is in ToolRegistry
2. Schema validation: get_function_schema() has correct parameters
3. Navigate action: navigate to a URL → returns page content
4. Get text action: extract text from page
5. Evaluate action: run JavaScript on page
6. Input validation: missing/invalid action → error
7. URL blocking: file:// and javascript: protocols blocked
8. Timeout enforcement
9. Screenshot action: captures page image
10. Dict input support
"""
import pytest
import json
import os


# ---------------------------------------------------------------------------
# 1. Registration & Schema
# ---------------------------------------------------------------------------

class TestBrowserToolRegistration:
    """Verify the browser tool is registered and has a valid schema."""

    def test_browser_tool_registered(self):
        """'headless_browser' should be in ToolRegistry."""
        from src.ai.tools import ToolRegistry
        tool = ToolRegistry.get_tool("headless_browser")
        assert tool is not None, "'headless_browser' not found in ToolRegistry"
        assert tool.name == "headless_browser"

    def test_schema_valid(self):
        """get_function_schema() returns proper schema."""
        from src.ai.tools import ToolRegistry
        tool = ToolRegistry.get_tool("headless_browser")
        schema = tool.get_function_schema()

        assert schema["name"] == "headless_browser"
        assert "description" in schema
        assert "parameters" in schema

        props = schema["parameters"]["properties"]
        assert "action" in props
        assert "url" in props
        assert "selector" in props
        assert "text" in props
        assert "javascript" in props
        assert "timeout_ms" in props
        assert "wait_for" in props

        # action should have enum
        assert "enum" in props["action"]
        expected_actions = {"click", "evaluate", "get_text", "navigate", "screenshot", "type"}
        assert set(props["action"]["enum"]) == expected_actions

        assert schema["parameters"]["required"] == ["action"]


# ---------------------------------------------------------------------------
# 2. Navigation & Text Extraction
# ---------------------------------------------------------------------------

class TestBrowserToolExecution:
    """Test actual browser execution through the tool."""

    @pytest.mark.asyncio
    async def test_navigate_to_url(self):
        """Navigate to example.com → content contains 'Example Domain'."""
        from src.ai.tools import ToolRegistry
        tool = ToolRegistry.get_tool("headless_browser")

        result_str = await tool.run(json.dumps({
            "action": "navigate",
            "url": "https://example.com",
            "timeout_ms": 30000,
        }))
        result = json.loads(result_str)

        assert result["status"] == "success"
        assert result["action"] == "navigate"
        assert "Example Domain" in result.get("title", "")
        assert "Example Domain" in result.get("content", "")

    @pytest.mark.asyncio
    async def test_get_text_from_page(self):
        """get_text on example.com → returns body text."""
        from src.ai.tools import ToolRegistry
        tool = ToolRegistry.get_tool("headless_browser")

        result_str = await tool.run(json.dumps({
            "action": "get_text",
            "url": "https://example.com",
        }))
        result = json.loads(result_str)

        assert result["status"] == "success"
        assert "Example Domain" in result.get("content", "")

    @pytest.mark.asyncio
    async def test_evaluate_javascript(self):
        """evaluate document.title on example.com → returns 'Example Domain'."""
        from src.ai.tools import ToolRegistry
        tool = ToolRegistry.get_tool("headless_browser")

        result_str = await tool.run(json.dumps({
            "action": "evaluate",
            "url": "https://example.com",
            "javascript": "document.title",
        }))
        result = json.loads(result_str)

        assert result["status"] == "success"
        assert "Example Domain" in result.get("result", "")

    @pytest.mark.asyncio
    async def test_screenshot_capture(self):
        """screenshot of example.com → creates a file."""
        from src.ai.tools import ToolRegistry
        tool = ToolRegistry.get_tool("headless_browser")

        result_str = await tool.run(json.dumps({
            "action": "screenshot",
            "url": "https://example.com",
        }))
        result = json.loads(result_str)

        assert result["status"] == "success"
        assert "screenshot_path" in result
        # Verify file exists
        assert os.path.exists(result["screenshot_path"])
        # Clean up
        try:
            os.remove(result["screenshot_path"])
        except OSError:
            pass


# ---------------------------------------------------------------------------
# 3. Input Validation
# ---------------------------------------------------------------------------

class TestBrowserToolValidation:
    """Test input validation edge cases."""

    @pytest.mark.asyncio
    async def test_missing_action(self):
        """No 'action' key → error."""
        from src.ai.tools import ToolRegistry
        tool = ToolRegistry.get_tool("headless_browser")

        result_str = await tool.run(json.dumps({"url": "https://example.com"}))
        result = json.loads(result_str)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_action(self):
        """Unknown action → error."""
        from src.ai.tools import ToolRegistry
        tool = ToolRegistry.get_tool("headless_browser")

        result_str = await tool.run(json.dumps({"action": "destroy"}))
        result = json.loads(result_str)
        assert "error" in result
        assert "Invalid action" in result["error"]

    @pytest.mark.asyncio
    async def test_navigate_missing_url(self):
        """Navigate without URL → error."""
        from src.ai.tools import ToolRegistry
        tool = ToolRegistry.get_tool("headless_browser")

        result_str = await tool.run(json.dumps({"action": "navigate"}))
        result = json.loads(result_str)
        assert result["status"] == "error"
        assert "url" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_click_missing_selector(self):
        """Click without selector → error."""
        from src.ai.tools import ToolRegistry
        tool = ToolRegistry.get_tool("headless_browser")

        result_str = await tool.run(json.dumps({"action": "click"}))
        result = json.loads(result_str)
        assert result["status"] == "error"
        assert "selector" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_evaluate_missing_javascript(self):
        """Evaluate without javascript → error."""
        from src.ai.tools import ToolRegistry
        tool = ToolRegistry.get_tool("headless_browser")

        result_str = await tool.run(json.dumps({"action": "evaluate"}))
        result = json.loads(result_str)
        assert result["status"] == "error"
        assert "javascript" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_invalid_json_input(self):
        """Non-JSON input → error."""
        from src.ai.tools import ToolRegistry
        tool = ToolRegistry.get_tool("headless_browser")

        result_str = await tool.run("not json at all")
        result = json.loads(result_str)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_dict_input(self):
        """Dict input (not string) should also work."""
        from src.ai.tools import ToolRegistry
        tool = ToolRegistry.get_tool("headless_browser")

        result_str = await tool.run({"action": "navigate", "url": "https://example.com"})
        result = json.loads(result_str)
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_run_with_context(self):
        """run_with_context should work the same as run."""
        from src.ai.tools import ToolRegistry
        tool = ToolRegistry.get_tool("headless_browser")

        result_str = await tool.run_with_context(
            json.dumps({"action": "navigate", "url": "https://example.com"}),
            context={"company_id": None}
        )
        result = json.loads(result_str)
        assert result["status"] == "success"


# ---------------------------------------------------------------------------
# 4. URL Safety
# ---------------------------------------------------------------------------

class TestBrowserToolSafety:
    """Test URL blocking and timeout enforcement."""

    @pytest.mark.asyncio
    async def test_blocked_file_url(self):
        """file:// URL should be blocked."""
        from src.ai.tools import ToolRegistry
        tool = ToolRegistry.get_tool("headless_browser")

        result_str = await tool.run(json.dumps({
            "action": "navigate",
            "url": "file:///etc/passwd",
        }))
        result = json.loads(result_str)
        assert result["status"] == "error"
        assert "blocked" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_blocked_javascript_url(self):
        """javascript: URL should be blocked."""
        from src.ai.tools import ToolRegistry
        tool = ToolRegistry.get_tool("headless_browser")

        result_str = await tool.run(json.dumps({
            "action": "navigate",
            "url": "javascript:alert(1)",
        }))
        result = json.loads(result_str)
        assert result["status"] == "error"
        assert "blocked" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_blocked_data_url(self):
        """data: URL should be blocked."""
        from src.ai.tools import ToolRegistry
        tool = ToolRegistry.get_tool("headless_browser")

        result_str = await tool.run(json.dumps({
            "action": "navigate",
            "url": "data:text/html,<h1>test</h1>",
        }))
        result = json.loads(result_str)
        assert result["status"] == "error"
        assert "blocked" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_timeout_capped_at_max(self):
        """timeout_ms > 120000 should be capped to 120000."""
        from src.ai.tools import ToolRegistry
        tool = ToolRegistry.get_tool("headless_browser")

        # This should succeed (timeout capped, not error)
        result_str = await tool.run(json.dumps({
            "action": "navigate",
            "url": "https://example.com",
            "timeout_ms": 999999,
        }))
        result = json.loads(result_str)
        assert result["status"] == "success"
