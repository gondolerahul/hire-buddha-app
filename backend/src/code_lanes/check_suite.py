"""The checks a promotion runs (Phase 14 WS6 6.3, tech spec §11.2 step 2). Standard library only.

    python check_suite.py DIRECTORY [--tests] [--json]

This file is also the entrypoint of the checks image (``backend/docker/checks``),
which the Kubernetes Job of a promotion runs in the tenant's sandbox pool, so
it imports nothing from the platform. Each check returns
``{"name", "conclusion": success|failure|neutral|skipped, "summary", "tool"}``:

* **secrets** — ``gitleaks`` when installed; else a scan for the common key
  shapes (cloud keys, private keys, tokens, HireBuddha app keys). Any find fails.
* **code** — ``semgrep`` (``p/default``) when installed; else Python files are
  parsed (a syntax error fails) and dangerous calls are reported (neutral).
* **dependencies** — ``pip-audit`` for ``requirements.txt``, ``npm audit`` for
  ``package-lock.json`` when installed; skipped when there is nothing to audit
  or no tool.
* **tests** (``--tests``, only where the code may run: the sandbox) —
  ``pytest`` when there are ``test_*.py`` files, ``npm test`` when
  ``package.json`` has a test script; skipped otherwise.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

MAX_FILE_BYTES = 2 * 1024 * 1024
TOOL_TIMEOUT = 600

SECRET_PATTERNS = {
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    "Stripe live key": re.compile(r"\b(?:sk|rk)_live_[0-9a-zA-Z]{20,}\b"),
    "HireBuddha app key": re.compile(r"\bhbk_[a-z]+_[0-9a-z]+_[A-Za-z0-9_\-]{20,}\b"),
    "password or key in code": re.compile(
        r"""(?i)\b(?:password|passwd|secret|api_?key|access_?token)\s*[:=]\s*["'][^"'\s]{12,}["']"""),
}
_PLACEHOLDER = re.compile(r"(?i)(example|changeme|placeholder|your[_-]|xxxx|dummy|test|<.*>|\$\{)")
DANGEROUS_CALLS = {"eval", "exec", "os.system", "pickle.loads", "marshal.loads", "subprocess.getoutput"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}


def _files(root: Path) -> List[Path]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            try:
                if path.stat().st_size <= MAX_FILE_BYTES:
                    out.append(path)
            except OSError:
                continue
    return sorted(out)


def _result(name: str, conclusion: str, summary: str, tool: str) -> Dict[str, str]:
    return {"name": name, "conclusion": conclusion, "summary": summary.strip()[:4000], "tool": tool}


def _run(argv: List[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, timeout=TOOL_TIMEOUT)


def check_secrets(root: Path) -> Dict[str, str]:
    if shutil.which("gitleaks"):
        proc = _run(["gitleaks", "detect", "--no-git", "--source", ".", "--report-format", "json",
                     "--report-path", "/dev/stdout", "--exit-code", "3"], root)
        if proc.returncode == 3:
            try:
                finds = json.loads(proc.stdout or "[]")
            except ValueError:
                finds = []
            lines = [f"{f.get('File')}:{f.get('StartLine')} {f.get('Description')}" for f in finds[:20]]
            return _result("secrets", "failure", f"{len(finds)} secret(s) found\n" + "\n".join(lines), "gitleaks")
        if proc.returncode == 0:
            return _result("secrets", "success", "no secrets found", "gitleaks")
        return _result("secrets", "neutral", f"gitleaks failed: {proc.stderr[-500:]}", "gitleaks")
    finds = []
    for path in _files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for label, pattern in SECRET_PATTERNS.items():
                match = pattern.search(line)
                if match and not _PLACEHOLDER.search(match.group(0)):
                    finds.append(f"{path.relative_to(root).as_posix()}:{number} {label}")
    if finds:
        return _result("secrets", "failure", f"{len(finds)} possible secret(s)\n" + "\n".join(finds[:20]), "builtin")
    return _result("secrets", "success", "no secrets found (built-in scan; gitleaks not installed)", "builtin")


def _call_name(node: ast.Call) -> Optional[str]:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}"
    return None


def check_code(root: Path) -> Dict[str, str]:
    if shutil.which("semgrep"):
        proc = _run(["semgrep", "scan", "--config", "p/default", "--json", "--quiet", "--metrics", "off"], root)
        try:
            report = json.loads(proc.stdout or "{}")
        except ValueError:
            return _result("code", "neutral", f"semgrep failed: {proc.stderr[-500:]}", "semgrep")
        results = report.get("results") or []
        blocking = [r for r in results if (r.get("extra") or {}).get("severity") == "ERROR"]
        lines = [f"{r.get('path')}:{(r.get('start') or {}).get('line')} {r.get('check_id')}" for r in results[:20]]
        conclusion = "failure" if blocking else ("neutral" if results else "success")
        return _result("code", conclusion, f"{len(results)} finding(s), {len(blocking)} blocking\n" + "\n".join(lines),
                       "semgrep")
    errors, warnings = [], []
    for path in _files(root):
        if path.suffix != ".py":
            continue
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError as error:
            errors.append(f"{rel}:{error.lineno} syntax error: {error.msg}")
            continue
        except (UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _call_name(node)
                if name in DANGEROUS_CALLS:
                    warnings.append(f"{rel}:{node.lineno} calls {name}")
                if name and name.startswith("subprocess.") and any(
                        k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value is True
                        for k in node.keywords):
                    warnings.append(f"{rel}:{node.lineno} runs a shell (shell=True)")
    if errors:
        return _result("code", "failure", "\n".join(errors + warnings), "builtin")
    if warnings:
        return _result("code", "neutral", "review these:\n" + "\n".join(warnings), "builtin")
    return _result("code", "success", "Python parses; no dangerous calls (built-in; semgrep not installed)", "builtin")


def check_dependencies(root: Path) -> Dict[str, str]:
    summaries, failed, ran = [], False, False
    for requirements in root.rglob("requirements*.txt"):
        if any(part in SKIP_DIRS for part in requirements.parts):
            continue
        if not shutil.which("pip-audit"):
            summaries.append(f"{requirements.relative_to(root).as_posix()}: pip-audit not installed")
            continue
        ran = True
        proc = _run(["pip-audit", "-r", str(requirements), "--format", "json", "--progress-spinner", "off"], root)
        try:
            deps = json.loads(proc.stdout or "{}").get("dependencies") or []
        except ValueError:
            deps = []
        vulnerable = [d for d in deps if d.get("vulns")]
        failed = failed or bool(vulnerable)
        summaries.append(f"{requirements.name}: {len(vulnerable)} vulnerable package(s) " +
                         ", ".join(f"{d['name']} {d.get('version')}" for d in vulnerable[:10]))
    for lock in root.rglob("package-lock.json"):
        if any(part in SKIP_DIRS for part in lock.parts):
            continue
        if not shutil.which("npm"):
            summaries.append(f"{lock.relative_to(root).as_posix()}: npm not installed")
            continue
        ran = True
        proc = _run(["npm", "audit", "--json", "--audit-level=high", "--package-lock-only"], lock.parent)
        try:
            counts = (json.loads(proc.stdout or "{}").get("metadata") or {}).get("vulnerabilities") or {}
        except ValueError:
            counts = {}
        high = int(counts.get("high", 0)) + int(counts.get("critical", 0))
        failed = failed or high > 0
        summaries.append(f"{lock.parent.relative_to(root).as_posix() or '.'}: {high} high/critical")
    if not summaries:
        return _result("dependencies", "skipped", "no requirements.txt or package-lock.json", "none")
    if not ran:
        return _result("dependencies", "skipped", "\n".join(summaries), "none")
    return _result("dependencies", "failure" if failed else "success", "\n".join(summaries),
                   "pip-audit/npm audit")


def check_tests(root: Path) -> Dict[str, str]:
    python_tests = [p for p in _files(root) if p.name.startswith("test_") and p.suffix == ".py"]
    if python_tests:
        proc = _run([sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"], root)
        tail = (proc.stdout or proc.stderr)[-1500:]
        if proc.returncode == 5:
            return _result("tests", "skipped", "no tests collected", "pytest")
        return _result("tests", "success" if proc.returncode == 0 else "failure", tail, "pytest")
    package = root / "package.json"
    if package.exists():
        try:
            script = (json.loads(package.read_text(encoding="utf-8")).get("scripts") or {}).get("test")
        except ValueError:
            script = None
        if script and "no test specified" not in script and shutil.which("npm"):
            proc = _run(["npm", "test", "--silent"], root)
            return _result("tests", "success" if proc.returncode == 0 else "failure",
                           (proc.stdout + proc.stderr)[-1500:], "npm test")
    return _result("tests", "skipped", "no tests", "none")


def run_suite(root: Path, *, tests: bool = False) -> List[Dict[str, str]]:
    results = [check_secrets(root), check_code(root), check_dependencies(root)]
    if tests:
        results.append(check_tests(root))
    return results


def fetch(url: str, root: Path) -> None:
    """Unpack the gzipped tarball at ``url`` (a short-lived signed URL) into ``root``."""
    import tarfile
    import tempfile
    import urllib.request

    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile() as buffer:
        with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 - the platform's signed URL
            shutil.copyfileobj(response, buffer)
        buffer.seek(0)
        with tarfile.open(fileobj=buffer, mode="r:gz") as archive:
            archive.extractall(root, filter="data")


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    tests = "--tests" in args
    as_json = "--json" in args
    source = args[args.index("--fetch") + 1] if "--fetch" in args else None
    paths = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] != "--fetch")]
    root = Path(paths[0] if paths else ".").resolve()
    if source:
        fetch(source, root)
    results = run_suite(root, tests=tests)
    if as_json:
        print("HB-CHECKS " + json.dumps(results))
    else:
        for item in results:
            print(f"{item['name']}: {item['conclusion']} ({item['tool']})\n{item['summary']}\n")
    return 1 if any(r["conclusion"] == "failure" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
