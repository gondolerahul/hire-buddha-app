"""tools.sandbox.synthesized_tool — runtime wrapper for a synthesized DRAFT tool.

A synthesized tool's source is **never** imported in-process (`06` §2.2). It is
written once per version — by content hash, like skill files — under the
company's read-only ``.skills/.synth/<name>/<hash>/`` root, beside a minimal
stub of the ``Tool`` base and a small driver. Each call writes its input and
the server-minted tool context to a request file and execs the driver in the
sandbox, under the tool's declared network policy; only the driver's one JSON
line crosses back (TL-02). It used to replay the whole test harness per call —
six files written and graded as if it were a test — and called ``run`` without
any context.

The wrapper carries ``status = DRAFT`` so the registry visibility gate keeps
it opt-in and tenant-only.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from typing import Any, Mapping, Optional

from src.ai.schemas.tools import NetworkPolicy, ToolSpec
from src.ai.tools.base import Tool, ToolStatus

__all__ = ["SandboxedSynthesizedTool", "sandbox_network", "tool_files", "sandbox_context"]

# A self-contained stub of the Tool base so synthesized code imports cleanly in
# the sandbox without the real platform package present.
BASE_STUB = '''
from abc import ABC, abstractmethod


class ToolStatus:
    ACTIVE = "ACTIVE"
    DRAFT = "DRAFT"


class Tool(ABC):
    name = ""
    description = ""
    status = "ACTIVE"

    @abstractmethod
    async def run(self, input_data):
        ...

    async def run_with_context(self, input_data, context=None):
        return await self.run(input_data)
'''

MARKER = "___TOOL___"

# One call: the request file is argv[1]; the tool's directory is this file's.
_DRIVER = '''
import asyncio, importlib.util, inspect, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _tool_class():
    spec = importlib.util.spec_from_file_location("synth_tool", os.path.join(HERE, "synth_tool.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import src.ai.tools.base as base
    for obj in vars(mod).values():
        if inspect.isclass(obj) and issubclass(obj, base.Tool) and obj is not base.Tool:
            return obj
    raise RuntimeError("no Tool subclass found")


def main():
    with open(sys.argv[1], encoding="utf-8") as fh:
        request = json.load(fh)
    try:
        out = asyncio.run(_tool_class()().run_with_context(request["input"], request.get("context") or {}))
        record = {"ok": True, "output": str(out)}
    except Exception as exc:  # noqa: BLE001
        record = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:500]}
    sys.stdout.write("''' + MARKER + '''" + json.dumps(record) + "\\n")


main()
'''


def tool_files(source: str) -> dict[str, str]:
    """The tool's source and the stub package it imports, by POSIX path."""
    return {
        "synth_tool.py": source,
        "src/__init__.py": "",
        "src/ai/__init__.py": "",
        "src/ai/tools/__init__.py": "",
        "src/ai/tools/base.py": BASE_STUB,
    }


def sandbox_network(policy: NetworkPolicy) -> str:
    """The sandbox network a declared policy runs under (TL-15). ``FULL`` is
    never granted to a synthesized tool: it runs with no network."""
    return "allowlist" if policy == NetworkPolicy.ALLOWLIST else "none"


def sandbox_context(context: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """What a synthesized tool sees of the call's context: the server-minted
    scalars (company, user, run, agent, …), never the loop's internal state."""
    return {k: v for k, v in (context or {}).items()
            if not k.startswith("__") and (v is None or isinstance(v, (str, int, float, bool)))}


class SandboxedSynthesizedTool(Tool):
    """Wraps synthesized source so every call runs in the sandbox, not in-process."""

    status = ToolStatus.DRAFT
    timeout_seconds = 60

    def __init__(self, spec: ToolSpec, source: str) -> None:
        self.name = spec.name
        self.description = spec.description
        self._spec = spec
        self._source = source

    async def run(self, input_data: str) -> str:
        return json.dumps({
            "error": "synthesized tools require execution context (sandbox). Use run_with_context().",
        })

    def _install(self, company_id: Any) -> str:
        """The tool's files under the read-only ``.skills/`` root, written once
        per version; returns the driver's host path."""
        from src.ai.tools.sandbox.skill_files import SKILLS_DIR, materialise

        files = {**tool_files(self._source), "_call.py": _DRIVER}
        digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode("utf-8")).hexdigest()
        root = materialise(company_id, f"{SKILLS_DIR}/.synth/{self.name}/{digest[:16]}", digest, files)
        return os.path.join(root, "_call.py")

    async def run_with_context(
        self, input_data: str, context: Optional[dict[str, Any]] = None,
    ) -> str:
        from src.ai.tools.sandbox.runtime import run_sandbox_exec
        from src.ai.tools.sandbox.workspace import tenant_workspace

        company_id = (context or {}).get("company_id")
        if not company_id:
            return json.dumps({"error": "no company: a synthesized tool has no workspace"})
        driver = self._install(company_id)
        call_dir = os.path.join(tenant_workspace(company_id), ".synth-calls", uuid.uuid4().hex[:12])
        os.makedirs(call_dir, exist_ok=True)
        request_path = os.path.join(call_dir, "request.json")
        with open(request_path, "w", encoding="utf-8") as fh:
            json.dump({"input": input_data, "context": sandbox_context(context)}, fh)
        try:
            res = await run_sandbox_exec(context, ["python", driver, request_path], cwd=call_dir,
                                         timeout=float(self.timeout_seconds - 5),
                                         network=sandbox_network(self._spec.network_policy))
        finally:
            shutil.rmtree(call_dir, ignore_errors=True)
        stdout = res.stdout or ""
        if MARKER not in stdout:
            reason = res.launch_error or ("timed out" if res.timed_out else (res.stderr or stdout)[-500:])
            return json.dumps({"error": f"sandbox execution failed: {reason}"})
        record = json.loads(stdout.split(MARKER, 1)[1].strip().splitlines()[0])
        if not record.get("ok"):
            return json.dumps({"error": record.get("error") or "the tool failed"})
        return str(record.get("output", ""))
