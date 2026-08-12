"""
SandboxCodeTool — Sb-A

Executes arbitrary code snippets in an isolated asyncio subprocess.

Safety features:
  - Hard 30-second timeout (configurable per entity via max_execution_seconds)
  - Stdout capped at 4096 characters
  - Stderr captured and returned on non-zero exit
  - Supports Python 3 and Bash (extensible via EXECUTORS map)
  - No network access flag (best-effort, does NOT guarantee security)

Input schema (JSON string):
    {
        "language":  "python" | "bash",
        "code":      "<source code string>",
        "timeout_s": 30           # optional, overrides default
    }

Output:
    stdout text (truncated to 4096 chars) on success
    Error message with stderr on failure
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from typing import Any, Dict, Optional

from src.ai.tools.base import Tool, ToolRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Executor command map — maps language → (interpreter, source-file-extension)
# ---------------------------------------------------------------------------
_EXECUTORS: Dict[str, tuple[str, str]] = {
    "python":  (sys.executable, ".py"),
    "python3": (sys.executable, ".py"),
    "bash":    ("/bin/bash",     ".sh"),
    "sh":      ("/bin/sh",       ".sh"),
}

_MAX_OUTPUT_CHARS = 4096


class SandboxCodeTool(Tool):
    """
    Execute code safely in a subprocess sandbox.

    The tool writes the code to a temp file, spawns a subprocess with
    asyncio, and captures stdout/stderr. A configurable timeout (default
    30 s) ensures runaway processes are killed.
    """
    name = "sandbox_code"
    description = (
        "Execute a Python or Bash code snippet in an isolated subprocess sandbox. "
        "Input must be a JSON string with 'language' ('python' or 'bash') "
        "and 'code' fields. Optional 'timeout_s' overrides the 30-second default. "
        "Returns stdout on success, or an error message with stderr on failure."
    )

    # Per-call default timeout — may be overridden by the entity's
    # ToolDefinition.max_execution_seconds via the args dict.
    DEFAULT_TIMEOUT_S: int = 30

    async def run(self, input_data: str) -> str:
        """Execute code and return stdout or error string."""
        return await self._execute(input_data, context=None)

    async def run_with_context(self, input_data: str, context: Optional[Dict[str, Any]] = None) -> str:
        return await self._execute(input_data, context=context)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _execute(self, input_data: str, context: Optional[Dict[str, Any]]) -> str:
        # 1. Parse input — supports JSON or raw code text as fallback
        args = None
        try:
            if isinstance(input_data, dict):
                args = input_data
            else:
                args = json.loads(input_data)
        except (json.JSONDecodeError, TypeError):
            pass  # Fall through to raw-text handling below

        if args and isinstance(args, dict) and args.get("code"):
            # Structured JSON input — use as-is
            language = str(args.get("language", "python")).lower()
            code = args.get("code", "")
            timeout_s = int(args.get("timeout_s", self.DEFAULT_TIMEOUT_S))
        elif args and isinstance(args, dict) and not args.get("code"):
            # JSON dict but no 'code' key — maybe the whole thing is code?
            return "Error: input must be a JSON string with 'language' and 'code' keys."
        else:
            # Raw text fallback — auto-detect language and treat input as code
            raw_text = input_data if isinstance(input_data, str) else str(input_data)
            raw_text = raw_text.strip()
            if not raw_text:
                return "Error: 'code' field is empty."

            # Strip common markdown code fences the LLM may wrap code in
            code, language = self._extract_code_from_text(raw_text)
            timeout_s = self.DEFAULT_TIMEOUT_S
            logger.info(f"SandboxCodeTool: raw text fallback — auto-detected language '{language}' ({len(code)} chars)")

        if not code.strip():
            return "Error: 'code' field is empty."

        executor = _EXECUTORS.get(language)
        if not executor:
            supported = ", ".join(_EXECUTORS.keys())
            return f"Error: unsupported language '{language}'. Supported: {supported}"

        interpreter, ext = executor

        # P3 — Tenant-scoped temp directory for filesystem isolation
        company_id = context.get("company_id") if context else None
        if company_id:
            sandbox_dir = os.path.join(tempfile.gettempdir(), "sandbox", str(company_id))
            os.makedirs(sandbox_dir, exist_ok=True)
            # Create a stable /tmp/sandbox/output symlink so LLM-generated code
            # using the generic path "/tmp/sandbox/output/" resolves correctly.
            output_link = os.path.join(tempfile.gettempdir(), "sandbox", "output")
            try:
                if os.path.islink(output_link):
                    os.unlink(output_link)
                elif os.path.isdir(output_link):
                    pass  # real dir already — leave it
                if not os.path.exists(output_link):
                    os.symlink(sandbox_dir, output_link)
            except OSError:
                pass  # Non-fatal — code can still use the real company path
            # Provision shared resources (e.g. Document Factory scripts)
            from src.ai.tools.sandbox.sandbox_provision import provision_sandbox
            provision_sandbox(sandbox_dir)
            logger.info(f"SandboxCodeTool: executing {language} for company {company_id}")
        else:
            sandbox_dir = None

        # 2. Snapshot existing files before execution (for artifact detection)
        pre_existing_files = set()
        if sandbox_dir:
            try:
                for root, _, files in os.walk(sandbox_dir):
                    for fn in files:
                        pre_existing_files.add(os.path.join(root, fn))
            except OSError:
                pass

        # 3. Write code to temp file and execute
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=ext,
                delete=False,
                encoding="utf-8",
                dir=sandbox_dir,
            ) as f:
                f.write(code)
                tmp_path = f.name

            try:
                result = await self._run_subprocess(
                    interpreter=interpreter,
                    script_path=tmp_path,
                    timeout_s=timeout_s,
                    working_dir=sandbox_dir,
                    context=context,
                )
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

            # 4. Post-execution: detect new document files and register as artifacts
            if sandbox_dir and company_id:
                artifact_report = await self._register_new_artifacts(
                    sandbox_dir, pre_existing_files, company_id, context
                )
                if artifact_report:
                    result = result + "\n\n" + artifact_report

            return result

        except Exception as exc:
            logger.error(f"SandboxCodeTool unexpected error: {exc}", exc_info=True)
            return f"Error: unexpected sandbox failure — {exc}"

    # ------------------------------------------------------------------
    # Document file extensions that should be auto-registered as artifacts
    # ------------------------------------------------------------------
    _ARTIFACT_EXTENSIONS: Dict[str, tuple[str, str]] = {
        # ext → (mime_type, file_category)
        ".pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "documents"),
        ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "documents"),
        ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "documents"),
        ".pdf":  ("application/pdf", "documents"),
        ".csv":  ("text/csv", "documents"),
        ".json": ("application/json", "documents"),
        ".html": ("text/html", "documents"),
        ".htm":  ("text/html", "documents"),
        ".png":  ("image/png", "images"),
        ".jpg":  ("image/jpeg", "images"),
        ".jpeg": ("image/jpeg", "images"),
        ".svg":  ("image/svg+xml", "images"),
        ".txt":  ("text/plain", "text"),
        ".md":   ("text/markdown", "text"),
    }

    async def _register_new_artifacts(
        self,
        sandbox_dir: str,
        pre_existing_files: set,
        company_id: str,
        context: Optional[Dict[str, Any]],
    ) -> str:
        """Detect new document files created during execution and register as artifacts.

        Returns a human-readable report string, or empty string if nothing found.
        """
        from uuid import UUID as _UUID

        # 1. Discover new files
        new_files = []
        try:
            for root, _, files in os.walk(sandbox_dir):
                # Skip venv, __pycache__, node_modules, scripts directories.
                # ``scratch`` is a reserved working area: agents (e.g.
                # doc-factory-lite) write intermediate/probe files there and then
                # register exactly ONE final output explicitly via the
                # ``document_save`` tool. Auto-registering scratch files is what
                # produced ~15 artifacts (incl. throwaway test.xlsx) for a single
                # request — see the document-factory redesign notes §4.5.
                rel_root = os.path.relpath(root, sandbox_dir)
                if any(skip in rel_root
                       for skip in ("venv", "__pycache__", "node_modules", "scripts", ".git", "scratch")):
                    continue
                for fn in files:
                    full_path = os.path.join(root, fn)
                    if full_path in pre_existing_files:
                        continue
                    ext = os.path.splitext(fn)[1].lower()
                    if ext in self._ARTIFACT_EXTENSIONS:
                        file_size = os.path.getsize(full_path)
                        # Skip trivially small files (< 100 bytes — likely empty/errored)
                        if file_size >= 100:
                            new_files.append((full_path, fn, ext, file_size))
        except OSError as e:
            logger.warning(f"SandboxCodeTool: artifact scan failed: {e}")
            return ""

        if not new_files:
            return ""

        # 2. Register each file as an artifact
        registered = []
        try:
            from src.common.database import AsyncSessionLocal
            from src.ai.artifact_service import ArtifactService, ORIGIN_SYSTEM

            async with AsyncSessionLocal() as db:
                art_svc = ArtifactService(db)
                _company_uuid = _UUID(str(company_id))
                _run_id = None
                if context and context.get("run_id"):
                    try:
                        _run_id = _UUID(str(context["run_id"]))
                    except (ValueError, TypeError):
                        pass

                for full_path, fn, ext, file_size in new_files:
                    mime_type, file_category = self._ARTIFACT_EXTENSIONS[ext]
                    try:
                        with open(full_path, "rb") as f:
                            file_bytes = f.read()

                        artifact = await art_svc.save_artifact(
                            file_bytes=file_bytes,
                            file_name=fn,
                            mime_type=mime_type,
                            file_category=file_category,
                            origin=ORIGIN_SYSTEM,
                            company_id=_company_uuid,
                            purpose=f"Auto-generated by sandbox execution",
                            generated_by="sandbox_code",
                            run_id=_run_id,
                        )
                        registered.append({
                            "file": fn,
                            "size": file_size,
                            "artifact_id": str(artifact.id),
                            "download_url": f"/api/v1/artifacts/{artifact.id}/download",
                        })
                        logger.info(
                            f"SandboxCodeTool: auto-registered artifact '{fn}' "
                            f"({file_size} bytes, {mime_type}) → {artifact.id}"
                        )
                    except Exception as e:
                        logger.warning(f"SandboxCodeTool: failed to register artifact '{fn}': {e}")

        except Exception as e:
            logger.warning(f"SandboxCodeTool: artifact registration failed: {e}")
            return ""

        if not registered:
            return ""

        # 3. Build report
        lines = ["📎 **Generated Artifacts:**"]
        for r in registered:
            lines.append(f"  • {r['file']} ({r['size']:,} bytes) — [Download](/api/v1/artifacts/{r['artifact_id']}/download)")
        return "\n".join(lines)

    @staticmethod
    def _extract_code_from_text(raw_text: str) -> tuple[str, str]:
        """Extract code and auto-detect language from raw LLM text.

        Handles:
        - Markdown fenced code blocks (```python ... ```)
        - Shebang lines (#!/usr/bin/env python3)
        - Language detection by syntax heuristics
        - Plain code without any markers

        Returns:
            (code, language) tuple
        """
        import re

        text = raw_text.strip()

        # 1. Try to extract from markdown code fences: ```lang\n...\n```
        fence_pattern = re.compile(
            r'```(\w*)\s*\n(.*?)```',
            re.DOTALL
        )
        match = fence_pattern.search(text)
        if match:
            fence_lang = match.group(1).lower().strip()
            code = match.group(2).strip()

            # Map common fence language labels
            lang_map = {
                "python": "python", "python3": "python", "py": "python",
                "javascript": "bash", "js": "bash",  # JS runs via node in bash
                "bash": "bash", "sh": "bash", "shell": "bash", "zsh": "bash",
                "": None,  # No language specified
            }
            language = lang_map.get(fence_lang, fence_lang) if fence_lang else None

            if language and language in _EXECUTORS:
                return code, language
            # If fence lang is unrecognized, fall through to heuristics with extracted code
            if code:
                text = code

        # 2. Check for shebang
        if text.startswith("#!/"):
            first_line = text.split("\n", 1)[0].lower()
            if "python" in first_line:
                return text, "python"
            elif "bash" in first_line or "sh" in first_line:
                return text, "bash"

        # 3. Heuristic language detection
        _python_signals = [
            "import ", "from ", "def ", "class ", "print(", "if __name__",
            "async def ", "await ", "with open(", ".append(", "lambda ",
        ]
        _bash_signals = [
            "#!/", "echo ", "mkdir ", "cd ", "ls ", "grep ", "sed ",
            "awk ", "chmod ", "curl ", "wget ", "apt ", "pip ",
            "export ", "source ", "&&", "||", "| ", " > ", " >> ",
        ]
        _js_signals = [
            "const ", "let ", "var ", "require(", "module.exports",
            "function ", "=> {", "async function", "console.log(",
            "new ", ".then(", ".catch(",
        ]

        py_score = sum(1 for sig in _python_signals if sig in text)
        bash_score = sum(1 for sig in _bash_signals if sig in text)
        js_score = sum(1 for sig in _js_signals if sig in text)

        # JS gets executed as bash via: node -e "..." or node script.js
        # So if it looks like JS, wrap it as a bash command
        if js_score > py_score and js_score > bash_score:
            # Wrap JS code as a bash script that writes to temp file and runs with node
            escaped = text.replace("'", "'\\''")
            bash_code = (
                "cat > /tmp/_sandbox_js.js << 'JSEOF'\n"
                f"{text}\n"
                "JSEOF\n"
                "node /tmp/_sandbox_js.js"
            )
            return bash_code, "bash"

        if py_score >= bash_score:
            return text, "python"
        else:
            return text, "bash"

    async def _run_subprocess(self, interpreter: str, script_path: str, timeout_s: int, working_dir: str = None, context: Optional[Dict[str, Any]] = None) -> str:
        """Run the script via the SandboxRuntime; shape the result into the
        tool's string contract (output cap + error wording unchanged)."""
        from src.ai.tools.sandbox.runtime import run_sandbox_exec

        # Build env — include node_modules/.bin for npm tools (e.g. pptxgenjs)
        node_bin = os.path.join(working_dir, "node_modules", ".bin") if working_dir else ""
        sandbox_path = f"{node_bin}:/usr/local/bin:/usr/bin:/bin" if node_bin else "/usr/local/bin:/usr/bin:/bin"
        env = {
            "PATH": sandbox_path,
            "HOME": "/tmp",
            "TMPDIR": working_dir or "/tmp",
            "LANG": "C.UTF-8",
            "SAL_USE_VCLPLUGIN": "svp",  # LibreOffice headless rendering
        }

        res = await run_sandbox_exec(
            context,
            [interpreter, script_path],
            cwd=working_dir,
            timeout=float(timeout_s),
            env=env,
        )

        if res.timed_out:
            return f"Error: execution timed out after {timeout_s} seconds."
        if res.not_found:
            return f"Error: interpreter '{interpreter}' not found on this system."
        if res.launch_error:
            return f"Error: subprocess launch failed — {res.launch_error}"

        if res.returncode != 0:
            msg = f"Error: process exited with code {res.returncode}."
            if res.stderr.strip():
                msg += f"\nStderr:\n{res.stderr[:2048]}"
            return msg

        stdout = res.stdout
        if len(stdout) > _MAX_OUTPUT_CHARS:
            stdout = stdout[:_MAX_OUTPUT_CHARS] + f"\n... [truncated, {len(stdout)} total chars]"

        return stdout if stdout else "(no output)"

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "enum": ["python", "python3", "bash", "sh"],
                        "description": "Programming language to execute",
                    },
                    "code": {
                        "type": "string",
                        "description": "Source code to execute",
                    },
                    "timeout_s": {
                        "type": "integer",
                        "description": "Execution timeout in seconds (default 30)",
                        "default": 30,
                    },
                },
                "required": ["language", "code"],
            },
        }
