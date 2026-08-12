"""meta.tool_validator — static-analysis gate for synthesized tools (Phase 12 `06` §2).

Tool synthesis is the platform's most dangerous capability; this is the
"non-negotiable" static half of its safety posture (`06` §2.2). Before a
synthesized tool is ever executed (and only ever in the per-tenant container),
its source is parsed and walked here to enforce:

  * **import allow-list** — only a safe stdlib baseline ∪ the ToolSpec's
    ``allowed_imports``; network modules only when ``network_policy`` permits;
  * **no dynamic-code / escape primitives** — ``eval`` / ``exec`` / ``compile``
    / ``__import__`` / ``globals`` / dunder traversal
    (``__subclasses__`` / ``__globals__`` / ``__bases__`` / ``__mro__``);
  * **no process / shell access** — ``subprocess`` / ``os.system`` / ``os.popen`` /
    ``pty`` / ``commands``;
  * **no secret access** — ``os.environ`` / ``os.getenv`` / settings secrets;
  * **structure** — exactly one ``Tool`` subclass exposing an async ``run`` /
    ``run_with_context``.

The result is a structured verdict (never raises on bad input). This pairs with
the LLM red-team and the container sandbox-test; none of the three is sufficient
alone.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import List, Optional, Set

from src.ai.schemas.tools import NetworkPolicy, ToolSpec

__all__ = ["Violation", "ToolValidationResult", "ToolValidator"]


# A conservative safe-stdlib baseline every synthesized tool may import without
# declaring it. Deliberately excludes os, sys, subprocess, socket, importlib.
_SAFE_STDLIB: Set[str] = {
    "json", "math", "re", "datetime", "typing", "dataclasses", "decimal",
    "uuid", "base64", "hashlib", "hmac", "collections", "itertools",
    "functools", "statistics", "textwrap", "string", "random", "enum",
    "html", "csv", "io", "struct", "binascii", "unicodedata", "calendar",
}

# Full module paths a synthesized tool MUST be able to import (the base
# contract it subclasses) regardless of the allow-list.
_ALLOWED_FULL_IMPORTS: Set[str] = {"src.ai.tools.base"}

# Modules that grant network egress — only allowed when the policy permits.
_NETWORK_MODULES: Set[str] = {
    "socket", "ssl", "http", "urllib", "ftplib", "smtplib", "telnetlib",
    "requests", "httpx", "aiohttp", "websockets", "urllib3",
}

# Builtins that enable dynamic code execution or sandbox escape.
_FORBIDDEN_CALLS: Set[str] = {
    "eval", "exec", "compile", "__import__", "globals", "locals", "vars",
    "input", "breakpoint", "memoryview",
}

# Dunder attributes used in classic sandbox escapes.
_FORBIDDEN_ATTRS: Set[str] = {
    "__subclasses__", "__globals__", "__bases__", "__mro__", "__class__",
    "__dict__", "__builtins__", "__code__", "__closure__", "__reduce__",
    "__getattribute__", "__base__",
}

# Dotted accesses that touch the process / shell / secrets.
_FORBIDDEN_DOTTED: Set[str] = {
    "os.system", "os.popen", "os.environ", "os.getenv", "os.putenv",
    "os.fork", "os.exec", "os.spawn", "os.remove", "os.rmdir", "os.unlink",
    "subprocess.run", "subprocess.call", "subprocess.Popen",
    "subprocess.check_output", "subprocess.check_call",
    "sys.modules", "sys.exit", "importlib.import_module",
    "shutil.rmtree",
}


@dataclass
class Violation:
    code: str
    message: str
    lineno: int = 0


@dataclass
class ToolValidationResult:
    ok: bool
    violations: List[Violation] = field(default_factory=list)
    imported_modules: Set[str] = field(default_factory=set)

    def summary(self) -> str:
        if self.ok:
            return "ok"
        return "; ".join(f"{v.code}@{v.lineno}: {v.message}" for v in self.violations)


class _Scanner(ast.NodeVisitor):
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self.allowed = _SAFE_STDLIB | set(spec.allowed_imports)
        self.network_ok = spec.network_policy != NetworkPolicy.NONE
        self.violations: List[Violation] = []
        self.imported: Set[str] = set()
        self.tool_classes: List[str] = []
        self._has_run = False

    # -- imports -------------------------------------------------------------
    def _check_module(self, full: str, lineno: int) -> None:
        top = full.split(".")[0]
        self.imported.add(top)
        if full in _ALLOWED_FULL_IMPORTS:
            return
        if top in _NETWORK_MODULES and not self.network_ok:
            self.violations.append(
                Violation("network_denied",
                          f"import of network module '{top}' but network_policy=none",
                          lineno))
            return
        if top in _NETWORK_MODULES and self.network_ok:
            return  # policy permits; egress still enforced at runtime
        if top not in self.allowed:
            self.violations.append(
                Violation("import_not_allowed",
                          f"import '{top}' not in the allow-list",
                          lineno))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._check_module(alias.name, node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level and node.level > 0:
            self.violations.append(
                Violation("relative_import",
                          "relative imports are not allowed", node.lineno))
        elif node.module:
            self._check_module(node.module, node.lineno)
        self.generic_visit(node)

    # -- calls / names / attrs ----------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name) and func.id in _FORBIDDEN_CALLS:
            self.violations.append(
                Violation("forbidden_call",
                          f"call to '{func.id}' is not allowed", node.lineno))
        dotted = _dotted_name(func)
        if dotted and dotted in _FORBIDDEN_DOTTED:
            self.violations.append(
                Violation("forbidden_call",
                          f"call to '{dotted}' is not allowed", node.lineno))
        if dotted and dotted.startswith(("subprocess.", "os.exec", "os.spawn")):
            self.violations.append(
                Violation("forbidden_process",
                          f"process spawn via '{dotted}' is not allowed", node.lineno))
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in _FORBIDDEN_CALLS:
            # Bare reference (e.g. assigning eval to a variable) is also a leak.
            self.violations.append(
                Violation("forbidden_name",
                          f"reference to '{node.id}' is not allowed", node.lineno))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in _FORBIDDEN_ATTRS:
            self.violations.append(
                Violation("forbidden_attr",
                          f"access to '{node.attr}' is not allowed", node.lineno))
        dotted = _dotted_name(node)
        if dotted and dotted in _FORBIDDEN_DOTTED:
            self.violations.append(
                Violation("forbidden_attr",
                          f"access to '{dotted}' is not allowed", node.lineno))
        self.generic_visit(node)

    # -- structure -----------------------------------------------------------
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        base_names = {_dotted_name(b) or getattr(b, "id", "") for b in node.bases}
        if any(b and b.split(".")[-1] == "Tool" for b in base_names):
            self.tool_classes.append(node.name)
            for item in node.body:
                if isinstance(item, (ast.AsyncFunctionDef,)) and item.name in (
                    "run", "run_with_context",
                ):
                    self._has_run = True
        self.generic_visit(node)


def _dotted_name(node: ast.AST) -> Optional[str]:
    """Reconstruct a dotted name (``a.b.c``) from an Attribute/Name chain."""
    parts: List[str] = []
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return None


class ToolValidator:
    """Static-analysis gate; instantiate and call :meth:`validate`."""

    def validate(self, source: str, spec: ToolSpec) -> ToolValidationResult:
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return ToolValidationResult(
                ok=False,
                violations=[Violation("syntax_error", str(exc), exc.lineno or 0)],
            )

        scanner = _Scanner(spec)
        scanner.visit(tree)

        if not scanner.tool_classes:
            scanner.violations.append(
                Violation("no_tool_class",
                          "source defines no Tool subclass", 0))
        elif len(scanner.tool_classes) > 1:
            scanner.violations.append(
                Violation("multiple_tool_classes",
                          f"expected one Tool subclass, found {len(scanner.tool_classes)}", 0))
        elif not scanner._has_run:
            scanner.violations.append(
                Violation("no_run_method",
                          "Tool subclass must define async run/run_with_context", 0))

        return ToolValidationResult(
            ok=not scanner.violations,
            violations=scanner.violations,
            imported_modules=scanner.imported,
        )
