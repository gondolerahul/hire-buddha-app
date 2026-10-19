"""The sandbox agent (Phase 14 WS6 6.1, tech spec §11.1). Standard library only.

Runs in each sandbox pod on AKS (``python3 /opt/hb/agent.py``) and is how the
platform uses the pod: no host paths, no ``docker exec``. Every call but
``/healthz`` needs ``Authorization: Bearer $SANDBOX_AGENT_TOKEN`` (one per
pod, from its Secret). Paths are confined to ``$SANDBOX_ROOT`` (``/sandbox``).

    GET    /healthz
    POST   /exec                {argv, cwd, env, timeout, watch: [dirs]} → result, and files changed under watch
    GET    /files?path=…        a file's bytes
    PUT    /files?path=…        write a file (parents made)
    DELETE /files?path=…
    GET    /list?path=…         a directory's names
    GET    /archive?path=…      a directory as tar.gz (scratch persistence)
    POST   /restore?path=…      unpack a tar.gz into a directory
"""
from __future__ import annotations

import hmac
import io
import json
import os
import signal
import subprocess
import sys
import tarfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(os.environ.get("SANDBOX_ROOT", "/sandbox")).resolve()
TOKEN = os.environ.get("SANDBOX_AGENT_TOKEN", "")
PORT = int(os.environ.get("SANDBOX_AGENT_PORT", "7070"))
MAX_BODY = 200 * 1024 * 1024
MAX_OUTPUT = 4 * 1024 * 1024
MAX_CHANGED = 500
TIMEOUT_RC = 124


class Refused(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def confined(raw: str) -> Path:
    """``raw`` as a path inside ROOT (symlinks resolved), or 400."""
    if not raw:
        raise Refused(400, "path is required")
    path = Path(raw)
    path = (path if path.is_absolute() else ROOT / path).resolve()
    if path != ROOT and ROOT not in path.parents:
        raise Refused(400, f"{raw} is outside the sandbox")
    return path


def changed_since(dirs, since: float):
    out = []
    for raw in dirs or []:
        base = confined(raw)
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", "__pycache__")]
            for name in filenames:
                path = Path(dirpath) / name
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if stat.st_mtime >= since:
                    out.append({"path": path.as_posix(), "size": stat.st_size, "mtime": stat.st_mtime})
                    if len(out) >= MAX_CHANGED:
                        return out
    return out


def run(body: dict) -> dict:
    argv = [str(a) for a in body.get("argv") or []]
    if not argv:
        raise Refused(400, "argv is required")
    cwd = confined(body["cwd"]) if body.get("cwd") else ROOT
    cwd.mkdir(parents=True, exist_ok=True)   # a new pod's workspace exists once something runs in it
    timeout = float(body.get("timeout") or 30)
    env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "HOME": os.environ.get("HOME", "/tmp"),
           "LANG": "C.UTF-8", **{k: str(v) for k, v in (body.get("env") or {}).items()}}
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy"):
        if key in os.environ and key not in env:
            env[key] = os.environ[key]
    started = time.time()
    clock = time.monotonic()
    try:
        proc = subprocess.Popen(argv, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True)
    except FileNotFoundError as error:
        return {"returncode": 127, "not_found": True, "launch_error": str(error), "stdout": "", "stderr": "",
                "timed_out": False, "duration_ms": 0, "changed": []}
    except OSError as error:
        return {"returncode": -1, "launch_error": str(error), "stdout": "", "stderr": "", "timed_out": False,
                "duration_ms": 0, "changed": []}
    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)   # the whole group: children too
        except (AttributeError, ProcessLookupError, PermissionError):
            proc.kill()
        out, err = proc.communicate()
    return {"returncode": TIMEOUT_RC if timed_out else proc.returncode, "timed_out": timed_out,
            "stdout": out[:MAX_OUTPUT].decode("utf-8", "replace"), "stderr": err[:MAX_OUTPUT].decode("utf-8", "replace"),
            "duration_ms": int((time.monotonic() - clock) * 1000), "not_found": False, "launch_error": None,
            "changed": changed_since(body.get("watch"), started - 1)}


def archive(path: Path) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        if path.is_dir():
            for child in sorted(path.iterdir()):
                tar.add(str(child), arcname=child.name)
    return buffer.getvalue()


def restore(path: Path, data: bytes) -> int:
    path.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        members = tar.getmembers()
        tar.extractall(path, filter="data")
    return len(members)


class Handler(BaseHTTPRequestHandler):
    server_version = "hb-sandbox-agent/1"

    def log_message(self, fmt: str, *args) -> None:  # noqa: D401 - quieter than the default
        sys.stderr.write("agent: " + (fmt % args) + "\n")

    def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value) -> None:
        self._send(status, json.dumps(value).encode())

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        return bool(TOKEN) and header.startswith("Bearer ") and hmac.compare_digest(header[7:].encode(), TOKEN.encode())

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise Refused(413, "too large")
        return self.rfile.read(length) if length else b""

    def _route(self, method: str) -> None:
        parts = urlsplit(self.path)
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        if parts.path == "/healthz" and method == "GET":
            return self._json(200, {"status": "ok"})
        if not self._authorized():
            return self._json(401, {"error": "unauthorized"})
        try:
            if parts.path == "/exec" and method == "POST":
                return self._json(200, run(json.loads(self._body() or b"{}")))
            if parts.path == "/files":
                path = confined(query.get("path", ""))
                if method == "GET":
                    if not path.is_file():
                        raise Refused(404, "no such file")
                    return self._send(200, path.read_bytes(), "application/octet-stream")
                if method == "PUT":
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(self._body())
                    if query.get("mtime"):
                        mtime = float(query["mtime"])
                        os.utime(path, (mtime, mtime))
                    return self._json(200, {"written": str(path)})
                if method == "DELETE":
                    if path.is_file():
                        path.unlink()
                    return self._json(200, {"deleted": str(path)})
            if parts.path == "/list" and method == "GET":
                path = confined(query.get("path", ""))
                if not path.is_dir():
                    raise Refused(404, "no such directory")
                return self._json(200, sorted(os.listdir(path)))
            if parts.path == "/archive" and method == "GET":
                return self._send(200, archive(confined(query.get("path", ""))), "application/gzip")
            if parts.path == "/restore" and method == "POST":
                return self._json(200, {"restored": restore(confined(query.get("path", "")), self._body())})
            raise Refused(404, "no such endpoint")
        except Refused as error:
            return self._json(error.status, {"error": str(error)})
        except (ValueError, tarfile.TarError) as error:
            return self._json(400, {"error": str(error)})

    def do_GET(self) -> None:  # noqa: N802
        self._route("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._route("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._route("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self._route("DELETE")


def main() -> None:
    if not TOKEN:
        sys.exit("SANDBOX_AGENT_TOKEN is not set")
    ROOT.mkdir(parents=True, exist_ok=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
