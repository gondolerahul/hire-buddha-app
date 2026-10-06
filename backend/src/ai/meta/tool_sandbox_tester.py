"""ai.meta.tool_sandbox_tester — run a synthesized tool against its examples.

The dynamic half of tool-synthesis safety (`06` §2.1, step 4). A synthesized
tool's source is **never** imported in-process; it is written to the tenant
workspace and executed through :func:`run_sandbox_exec` (container-when-enabled,
`02`). Each :class:`~src.ai.schemas.tools.ToolExample` is replayed and graded.

The harness deliberately ships a *minimal* ``src.ai.tools.base`` stub into the
workdir so the synthesized ``from src.ai.tools.base import Tool`` resolves
without exposing the real platform package to sandboxed code. It calls the
tool the way a run will — ``run_with_context`` with the call's server-minted
context — under the tool's declared network policy (TL-02, TL-15).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, List, Mapping, Optional, Sequence

from src.ai.schemas.tools import ToolSpec

logger = logging.getLogger(__name__)

__all__ = ["ExampleOutcome", "SandboxTestReport", "ToolSandboxTester", "build_harness_files"]


def _harness_main(examples: List[dict[str, Any]], context: Mapping[str, Any]) -> str:
    return f'''
import asyncio, importlib.util, inspect, json, sys, traceback

EXAMPLES = json.loads({json.dumps(json.dumps(examples))})
CONTEXT = json.loads({json.dumps(json.dumps(dict(context)))})


def _load_tool_class():
    spec = importlib.util.spec_from_file_location("synth_tool", "synth_tool.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import src.ai.tools.base as base
    for obj in vars(mod).values():
        if inspect.isclass(obj) and issubclass(obj, base.Tool) and obj is not base.Tool:
            return obj
    raise RuntimeError("no Tool subclass found")


async def _run():
    cls = _load_tool_class()
    inst = cls()
    results = []
    for ex in EXAMPLES:
        rec = {{"input": ex["input"], "ok": False}}
        try:
            out = await inst.run_with_context(ex["input"], CONTEXT)
            rec["output"] = str(out)[:2000]
            rec["errored"] = False
        except Exception as exc:  # noqa: BLE001
            rec["output"] = ""
            rec["errored"] = True
            rec["error"] = f"{{type(exc).__name__}}: {{exc}}"[:500]
        results.append(rec)
    return results


if __name__ == "__main__":
    try:
        res = asyncio.run(_run())
        print("___HARNESS___" + json.dumps(res))
    except Exception:
        traceback.print_exc()
        sys.exit(1)
'''


def build_harness_files(
    source: str, spec: ToolSpec, context: Optional[Mapping[str, Any]] = None,
) -> dict[str, str]:
    """Pure builder: POSIX path → content for the sandbox run."""
    from src.ai.tools.sandbox.synthesized_tool import sandbox_context, tool_files

    examples = [
        {"input": ex.input, "expected_contains": ex.expected_contains,
         "should_error": ex.should_error}
        for ex in spec.examples
    ]
    return {**tool_files(source), "_harness.py": _harness_main(examples, sandbox_context(context))}


@dataclass
class ExampleOutcome:
    input: str
    passed: bool
    output: str = ""
    detail: str = ""


@dataclass
class SandboxTestReport:
    ok: bool
    outcomes: List[ExampleOutcome] = field(default_factory=list)
    exit_code: int = 0
    error: str = ""

    def summary(self) -> str:
        if self.error:
            return f"sandbox error: {self.error}"
        passed = sum(1 for o in self.outcomes if o.passed)
        return f"{passed}/{len(self.outcomes)} examples passed (exit={self.exit_code})"


ExecFn = Callable[..., Awaitable[Any]]


def _grade(report_rows: list[dict[str, Any]], spec: ToolSpec) -> List[ExampleOutcome]:
    by_input = {r.get("input"): r for r in report_rows}
    outcomes: List[ExampleOutcome] = []
    for ex in spec.examples:
        row = by_input.get(ex.input, {})
        errored = bool(row.get("errored", True))
        output = str(row.get("output", ""))
        if ex.should_error:
            passed = errored
            detail = "expected error" + ("" if errored else " but ran clean")
        elif errored:
            passed = False
            detail = f"unexpected error: {row.get('error', '')}"
        elif ex.expected_contains:
            passed = ex.expected_contains in output
            detail = "" if passed else f"missing {ex.expected_contains!r}"
        else:
            passed = True
            detail = ""
        outcomes.append(ExampleOutcome(input=ex.input, passed=passed, output=output[:500], detail=detail))
    return outcomes


class ToolSandboxTester:
    """Replays a synthesized tool's examples inside the sandbox."""

    async def run_examples(
        self,
        source: str,
        spec: ToolSpec,
        context: Optional[Mapping[str, Any]] = None,
        *,
        exec_fn: Optional[ExecFn] = None,
        workdir: Optional[str] = None,
        timeout: float = 30.0,
    ) -> SandboxTestReport:
        if exec_fn is None:
            from src.ai.tools.sandbox.runtime import run_sandbox_exec
            exec_fn = run_sandbox_exec

        owns_dir = workdir is None
        if workdir is None:
            # Inside the company's workspace — the directory a tenant container
            # mounts — not bare /tmp, which only the host runtime can see: the
            # harness used to work only when the generated code ran unsandboxed
            # on the host (TL-02).
            company_id = (context or {}).get("company_id")
            if not company_id:
                return SandboxTestReport(ok=False, error="no company: the harness has no workspace")
            from src.ai.tools.sandbox.workspace import tenant_workspace
            base = tenant_workspace(company_id)
            os.makedirs(base, exist_ok=True)
            workdir = tempfile.mkdtemp(prefix="toolsynth_", dir=base)
        try:
            for rel, content in build_harness_files(source, spec, context).items():
                path = os.path.join(workdir, *rel.split("/"))
                os.makedirs(os.path.dirname(path) or workdir, exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(content)
            argv: Sequence[str] = ["python", "_harness.py"]
            # The tool's declared policy reaches the container (TL-15).
            from src.ai.tools.sandbox.synthesized_tool import sandbox_network
            try:
                res = await exec_fn(context, argv, cwd=workdir, timeout=timeout,
                                    network=sandbox_network(spec.network_policy))
            except Exception as exc:  # noqa: BLE001
                return SandboxTestReport(ok=False, error=f"exec failed: {type(exc).__name__}: {exc}")

            exit_code = int(getattr(res, "exit_code", getattr(res, "returncode", 1)) or 0)
            stdout = getattr(res, "stdout", "") or ""
            marker = "___HARNESS___"
            if marker not in stdout:
                stderr = (getattr(res, "stderr", "") or "")[:500]
                return SandboxTestReport(
                    ok=False, exit_code=exit_code,
                    error=f"harness produced no report (exit={exit_code}): {stderr}",
                )
            try:
                rows = json.loads(stdout.split(marker, 1)[1].strip())
            except Exception as exc:  # noqa: BLE001
                return SandboxTestReport(ok=False, exit_code=exit_code, error=f"bad report json: {exc}")

            outcomes = _grade(rows if isinstance(rows, list) else [], spec)
            ok = bool(outcomes) and all(o.passed for o in outcomes) and exit_code == 0
            return SandboxTestReport(ok=ok, outcomes=outcomes, exit_code=exit_code)
        finally:
            if owns_dir:
                import shutil
                shutil.rmtree(workdir, ignore_errors=True)
