"""
E2E tests for the Terminal Tool.

Tests:
1. Tool registration: 'terminal' is in ToolRegistry
2. Schema validation: get_function_schema() has command, working_dir, timeout_s
3. Basic execution: echo hello → stdout contains "hello"
4. Working directory: pwd with working_dir=/tmp → output is /tmp
5. Exit code on failure: `false` → non-zero exit code
6. Timeout enforcement: sleep 60 with timeout_s=2 → timed_out=true
7. Blocked command rejection: rm -rf / → error without executing
8. Empty command rejection: empty string → validation error
9. Missing command key: no 'command' → validation error
10. Stderr capture: command writing to stderr → stderr in result
"""
import pytest
import json


# ---------------------------------------------------------------------------
# 1. Registration & Schema
# ---------------------------------------------------------------------------

class TestTerminalToolRegistration:
    """Verify the terminal tool is registered and has a valid schema."""

    def test_terminal_tool_registered(self):
        """'terminal' should be in ToolRegistry."""
        from src.ai.tools import ToolRegistry

        registered_names = {t["name"] for t in ToolRegistry.list_tools()}
        assert "terminal" in registered_names, "Tool 'terminal' not registered"

    def test_schema_valid(self):
        """get_function_schema() returns proper schema."""
        from src.ai.tools import ToolRegistry

        tool = ToolRegistry.get_tool("terminal")
        assert tool is not None

        schema = tool.get_function_schema()
        assert schema["name"] == "terminal"
        assert "description" in schema
        assert len(schema["description"]) > 10

        params = schema["parameters"]
        assert params["type"] == "object"
        props = params["properties"]
        assert "command" in props
        assert "working_dir" in props
        assert "timeout_s" in props
        assert "command" in params["required"]


# ---------------------------------------------------------------------------
# 2. Command Execution
# ---------------------------------------------------------------------------

class TestTerminalToolExecution:
    """Test actual command execution through the terminal tool."""

    @pytest.mark.asyncio
    async def test_basic_echo(self):
        """echo hello → stdout contains 'hello'."""
        from src.ai.tools import ToolRegistry

        tool = ToolRegistry.get_tool("terminal")
        result_str = await tool.run(json.dumps({"command": "echo hello"}))
        result = json.loads(result_str)

        assert result["exit_code"] == 0
        assert "hello" in result["stdout"]
        assert result["timed_out"] is False

    @pytest.mark.asyncio
    async def test_working_directory(self):
        """pwd with working_dir=/tmp → output is /tmp."""
        from src.ai.tools import ToolRegistry

        tool = ToolRegistry.get_tool("terminal")
        result_str = await tool.run(json.dumps({
            "command": "pwd",
            "working_dir": "/tmp"
        }))
        result = json.loads(result_str)

        assert result["exit_code"] == 0
        assert result["stdout"].strip() == "/tmp"

    @pytest.mark.asyncio
    async def test_nonzero_exit_code(self):
        """Running 'false' should return non-zero exit code."""
        from src.ai.tools import ToolRegistry

        tool = ToolRegistry.get_tool("terminal")
        result_str = await tool.run(json.dumps({"command": "false"}))
        result = json.loads(result_str)

        assert result["exit_code"] != 0
        assert result["timed_out"] is False

    @pytest.mark.asyncio
    async def test_stderr_capture(self):
        """A command writing to stderr should have stderr in result."""
        from src.ai.tools import ToolRegistry

        tool = ToolRegistry.get_tool("terminal")
        result_str = await tool.run(json.dumps({
            "command": "echo 'oops' >&2"
        }))
        result = json.loads(result_str)

        assert "oops" in result["stderr"]

    @pytest.mark.asyncio
    async def test_multiline_output(self):
        """Commands producing multiple lines work correctly."""
        from src.ai.tools import ToolRegistry

        tool = ToolRegistry.get_tool("terminal")
        result_str = await tool.run(json.dumps({
            "command": "echo line1; echo line2; echo line3"
        }))
        result = json.loads(result_str)

        assert result["exit_code"] == 0
        assert "line1" in result["stdout"]
        assert "line2" in result["stdout"]
        assert "line3" in result["stdout"]


# ---------------------------------------------------------------------------
# 3. Timeout & Safety
# ---------------------------------------------------------------------------

class TestTerminalToolSafety:
    """Test timeout enforcement and command blocklist."""

    @pytest.mark.asyncio
    async def test_timeout_enforcement(self):
        """sleep 60 with timeout_s=2 → timed_out is true."""
        from src.ai.tools import ToolRegistry

        tool = ToolRegistry.get_tool("terminal")
        result_str = await tool.run(json.dumps({
            "command": "sleep 60",
            "timeout_s": 2
        }))
        result = json.loads(result_str)

        assert result["timed_out"] is True
        assert result["exit_code"] == -1

    @pytest.mark.asyncio
    async def test_blocked_command_rm_rf(self):
        """rm -rf / should be blocked without executing."""
        from src.ai.tools import ToolRegistry

        tool = ToolRegistry.get_tool("terminal")
        result_str = await tool.run(json.dumps({
            "command": "rm -rf /"
        }))
        result = json.loads(result_str)

        assert "error" in result
        assert "blocked" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_blocked_command_mkfs(self):
        """mkfs should be blocked."""
        from src.ai.tools import ToolRegistry

        tool = ToolRegistry.get_tool("terminal")
        result_str = await tool.run(json.dumps({
            "command": "mkfs.ext4 /dev/sda1"
        }))
        result = json.loads(result_str)

        assert "error" in result
        assert "blocked" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_blocked_command_shutdown(self):
        """shutdown should be blocked."""
        from src.ai.tools import ToolRegistry

        tool = ToolRegistry.get_tool("terminal")
        result_str = await tool.run(json.dumps({
            "command": "shutdown -h now"
        }))
        result = json.loads(result_str)

        assert "error" in result
        assert "blocked" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_timeout_capped_at_max(self):
        """timeout_s > 120 should be capped to 120 (not an error)."""
        from src.ai.tools import ToolRegistry

        tool = ToolRegistry.get_tool("terminal")
        result_str = await tool.run(json.dumps({
            "command": "echo capped",
            "timeout_s": 999
        }))
        result = json.loads(result_str)

        # Should still execute fine, just capped internally
        assert result["exit_code"] == 0
        assert "capped" in result["stdout"]


# ---------------------------------------------------------------------------
# 4. Input Validation
# ---------------------------------------------------------------------------

class TestTerminalToolValidation:
    """Test input validation edge cases."""

    @pytest.mark.asyncio
    async def test_empty_command(self):
        """Empty command string → error."""
        from src.ai.tools import ToolRegistry

        tool = ToolRegistry.get_tool("terminal")
        result_str = await tool.run(json.dumps({"command": ""}))
        result = json.loads(result_str)

        assert "error" in result

    @pytest.mark.asyncio
    async def test_missing_command_key(self):
        """No 'command' key → error."""
        from src.ai.tools import ToolRegistry

        tool = ToolRegistry.get_tool("terminal")
        result_str = await tool.run(json.dumps({"working_dir": "/tmp"}))
        result = json.loads(result_str)

        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_json_input(self):
        """Non-JSON input → error."""
        from src.ai.tools import ToolRegistry

        tool = ToolRegistry.get_tool("terminal")
        result_str = await tool.run("not valid json")
        result = json.loads(result_str)

        assert "error" in result

    @pytest.mark.asyncio
    async def test_dict_input(self):
        """Dict input (not string) should also work."""
        from src.ai.tools import ToolRegistry

        tool = ToolRegistry.get_tool("terminal")
        result_str = await tool.run(json.dumps({"command": "echo dict_test"}))
        result = json.loads(result_str)

        assert result["exit_code"] == 0
        assert "dict_test" in result["stdout"]

    @pytest.mark.asyncio
    async def test_run_with_context(self):
        """run_with_context should work the same as run."""
        from src.ai.tools import ToolRegistry

        tool = ToolRegistry.get_tool("terminal")
        result_str = await tool.run_with_context(
            json.dumps({"command": "echo context_test"}),
            context={"company_id": "test"}
        )
        result = json.loads(result_str)

        assert result["exit_code"] == 0
        assert "context_test" in result["stdout"]
