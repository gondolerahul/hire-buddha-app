"""
TerminalTool — Shell command execution for AI agents.

Executes shell commands in an isolated asyncio subprocess, reusing the
sandbox infrastructure patterns from SandboxCodeTool.

Safety features:
  - Hard timeout (default 30s, max 120s)
  - Stdout capped at 8192 characters
  - Stderr captured and returned alongside exit code
  - Minimal environment (no inherited secrets)
  - Command blocklist prevents destructive system commands

Input schema (JSON string):
    {
        "command":     "ls -la /tmp",
        "working_dir": "/tmp",          # optional, defaults to /tmp
        "timeout_s":   30               # optional, max 120
    }

Output (JSON string):
    {
        "exit_code":   0,
        "stdout":      "...",
        "stderr":      "",
        "timed_out":   false
    }
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, Optional

from src.ai.tools.base import Tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Safety: command blocklist patterns
# ---------------------------------------------------------------------------
_BLOCKED_PATTERNS: list[re.Pattern] = [
    re.compile(r"\brm\s+.*-\s*[^\s]*r[^\s]*f\s+/\s*$"),   # rm -rf /
    re.compile(r"\brm\s+.*-\s*[^\s]*f[^\s]*r\s+/\s*$"),   # rm -fr /
    re.compile(r"\bmkfs\b"),                                # mkfs
    re.compile(r"\bdd\s+.*of\s*=\s*/dev/"),                 # dd of=/dev/...
    re.compile(r":\(\)\s*\{"),                              # fork bomb
    re.compile(r"\bshutdown\b"),
    re.compile(r"\breboot\b"),
    re.compile(r"\bhalt\b"),
    re.compile(r"\bpoweroff\b"),
    re.compile(r"\binit\s+0\b"),
    re.compile(r"\binit\s+6\b"),
    re.compile(r">\s*/dev/sd[a-z]"),                        # overwrite disk
    re.compile(r"\bchmod\s+.*777\s+/\s*$"),                 # chmod 777 /
]

_MAX_OUTPUT_CHARS = 8192
_DEFAULT_TIMEOUT_S = 30
_MAX_TIMEOUT_S = 120


def _is_blocked(command: str) -> bool:
    """Check if a command matches any blocked pattern."""
    for pattern in _BLOCKED_PATTERNS:
        if pattern.search(command):
            return True
    return False


class TerminalTool(Tool):
    """
    Execute shell commands in a sandboxed subprocess.

    Unlike SandboxCodeTool (which writes code to a temp file and runs an
    interpreter), this tool passes the command string directly to
    ``/bin/bash -c "<command>"``, mirroring how a real terminal works.
    Output is returned as structured JSON with exit_code, stdout, and stderr.
    """
    timeout_seconds = 180  # per call (EP-08)

    name = "terminal"
    description = (
        "Execute a bash/shell command in an isolated subprocess. "
        "Input must be a JSON string with a 'command' field containing "
        "the shell command to run. Optional 'working_dir' sets the "
        "working directory (default /tmp). Optional 'timeout_s' "
        "overrides the 30-second default (max 120). "
        "Save a deliverable the user should get into the directory in $ARTIFACTS_DIR: it is "
        "kept as an artifact of the run (other files stay in the workspace). "
        "Returns JSON with exit_code, stdout, stderr, and timed_out fields."
    )

    async def run(self, input_data: str) -> str:
        """Execute command and return structured JSON result."""
        return await self._execute(input_data, context=None)

    async def run_with_context(
        self, input_data: str, context: Optional[Dict[str, Any]] = None
    ) -> str:
        return await self._execute(input_data, context=context)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _execute(self, input_data: str, context: Optional[Dict[str, Any]] = None) -> str:
        # 1. Parse input — supports JSON or raw command text as fallback
        args = None
        try:
            if isinstance(input_data, dict):
                args = input_data
            else:
                args = json.loads(input_data)
        except (json.JSONDecodeError, TypeError):
            pass  # Fall through to raw-text handling below

        if args and isinstance(args, dict):
            command = args.get("command", "").strip()
            working_dir = args.get("working_dir", "/tmp").strip() or "/tmp"
            timeout_s = min(
                int(args.get("timeout_s", _DEFAULT_TIMEOUT_S)),
                _MAX_TIMEOUT_S,
            )
        else:
            # Raw text fallback — treat the entire input as a bash command
            raw_text = input_data if isinstance(input_data, str) else str(input_data)
            raw_text = raw_text.strip()

            # Strip markdown code fences if present (```bash\n...\n```)
            import re
            fence_match = re.search(r'```(?:\w*)\s*\n(.*?)```', raw_text, re.DOTALL)
            if fence_match:
                command = fence_match.group(1).strip()
            else:
                command = raw_text

            working_dir = "/tmp"
            timeout_s = _DEFAULT_TIMEOUT_S
            logger.info(f"TerminalTool: raw text fallback — treating input as command ({len(command)} chars)")

        # P3 — Tenant-scoped working directory for filesystem isolation
        company_id = context.get("company_id") if context else None
        if company_id:
            import os
            from src.ai.tools.sandbox.workspace import tenant_workspace
            # The tenant workspace (TL-29) — where the run's skill files are
            # written; it was a hard-coded /tmp/sandbox/<company>.
            scoped_dir = tenant_workspace(company_id)
            os.makedirs(scoped_dir, exist_ok=True)
            # If caller didn't specify a custom working_dir, use the scoped one
            if working_dir == "/tmp":
                working_dir = scoped_dir
            logger.info(f"TerminalTool: executing command for company {company_id}")

        # 2. Validate
        if not command:
            return json.dumps({"error": "'command' field is empty or missing."})

        if _is_blocked(command):
            return json.dumps({
                "error": (
                    "Command blocked by safety filter. "
                    "Destructive system commands are not permitted."
                )
            })

        # 3. Execute. Deliverables go in $ARTIFACTS_DIR and are kept as the
        # run's artifacts when the command ends (TL-36): nothing is scanned.
        from src.ai.tools.sandbox.drop_box import drop_box, report
        try:
            async with drop_box(context, generated_by="terminal") as box:
                result = await self._run_subprocess(command, working_dir, timeout_s, context,
                                                    extra_env=box.env if box else None)
        except Exception as exc:
            logger.error(f"TerminalTool unexpected error: {exc}", exc_info=True)
            return json.dumps({
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Unexpected sandbox failure: {exc}",
                "timed_out": False,
            })

        kept = report(box)
        if kept:
            try:
                result_dict = json.loads(result)
                result_dict["artifacts"] = kept
                result = json.dumps(result_dict, default=str)
            except (json.JSONDecodeError, TypeError):
                result = result + "\n\n" + kept

        return result

    async def _run_subprocess(
        self,
        command: str,
        working_dir: str,
        timeout_s: int,
        context: Optional[Dict[str, Any]] = None,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> str:
        """Run ``bash -c command`` via the SandboxRuntime; shape the result
        into the tool's JSON contract (output cap + wording unchanged)."""
        from src.ai.tools.sandbox.runtime import run_sandbox_exec

        res = await run_sandbox_exec(
            context,
            ["/bin/bash", "-c", command],
            cwd=working_dir,
            timeout=float(timeout_s),
            # Sandbox env — LibreOffice needs SAL_USE_VCLPLUGIN for headless
            env={
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "HOME": "/tmp",
                "TMPDIR": "/tmp",
                "LANG": "C.UTF-8",
                "SAL_USE_VCLPLUGIN": "svp",  # LibreOffice headless rendering
                **(extra_env or {}),
            },
        )

        if res.timed_out:
            return json.dumps({
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Execution timed out after {timeout_s} seconds.",
                "timed_out": True,
            })
        if res.not_found:
            return json.dumps({
                "exit_code": -1,
                "stdout": "",
                "stderr": "/bin/bash not found on this system.",
                "timed_out": False,
            })
        if res.launch_error:
            return json.dumps({
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Subprocess launch failed: {res.launch_error}",
                "timed_out": False,
            })

        stdout = res.stdout
        stderr = res.stderr
        if len(stdout) > _MAX_OUTPUT_CHARS:
            stdout = (
                stdout[:_MAX_OUTPUT_CHARS]
                + f"\n... [truncated, {len(stdout)} total chars]"
            )
        if len(stderr) > _MAX_OUTPUT_CHARS:
            stderr = (
                stderr[:_MAX_OUTPUT_CHARS]
                + f"\n... [truncated, {len(stderr)} total chars]"
            )

        return json.dumps({
            "exit_code": res.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": False,
        })

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": (
                            "The shell command to execute, e.g. 'ls -la' or "
                            "'cat /etc/hostname'"
                        ),
                    },
                    "working_dir": {
                        "type": "string",
                        "description": (
                            "Working directory for the command (default: /tmp)"
                        ),
                        "default": "/tmp",
                    },
                    "timeout_s": {
                        "type": "integer",
                        "description": (
                            "Execution timeout in seconds (default 30, max 120)"
                        ),
                        "default": 30,
                    },
                },
                "required": ["command"],
            },
        }
