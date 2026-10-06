"""
ai.tools.sandbox.container_runtime — the Docker-backed SandboxRuntime (Phase 12 `02` S4).

``ContainerRuntime`` implements the ``SandboxRuntime`` Protocol against a
persistent per-tenant container managed by ``TenantSandboxManager``. The sandbox
tools never know they got it instead of ``SubprocessRuntime`` — same ``exec`` /
file-op / browser / lifecycle surface.

* ``exec`` runs the argv via ``docker exec`` inside the tenant container, wrapped
  in coreutils ``timeout`` so the *in-container* process is killed on timeout
  (killing the ``docker exec`` client alone would orphan it). ``ExecResult`` is
  shaped to match ``SubprocessRuntime`` exactly (returncode / not_found /
  launch_error / timed_out), so the tools' output handling is unchanged.
* File ops act on the host side of the bind-mount — the container sees the same
  bytes at the same path, so a plain host read/write is correct and avoids a
  ``docker cp`` round-trip.
* ``run_browser`` runs a browser session's steps inside the company's ``web``
  container (TL-18): the platform writes the runner under the read-only
  ``.skills/`` root and the request into the workspace, and execs the runner
  with the image's Playwright. Chromium reaches the internet only through the
  egress proxy that refuses private addresses; screenshots land in the call's
  drop box. It used to open Chromium on the host.
* Lifecycle methods forward to the manager.

Selected by ``resolve_sandbox_runtime`` when the one switch is on for the
company; a Docker failure is an error, never a fallback to the host (TL-01).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import time
import uuid
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
)

from src.ai.tools.sandbox import browser_runner
from src.ai.tools.sandbox.runtime import ExecResult
from src.ai.tools.sandbox.container_paths import to_container_text, to_host_text
from src.ai.tools.sandbox.tenant_manager import (
    SandboxDockerError,
    TenantSandboxManager,
    mounted_roots,
)

# `timeout` exit codes (coreutils): 124 = TERM after duration, 137 = KILL after
# --kill-after. Both mean the command did not finish in time.
_TIMEOUT_RCS = {124, 137}
# A shell/`docker exec` reports 127 when the program itself is not found.
_NOT_FOUND_RC = 127


class ContainerRuntime:
    """``SandboxRuntime`` backed by a persistent per-tenant Docker container."""

    def __init__(
        self,
        company_id: Optional[str] = None,
        *,
        manager: Optional[TenantSandboxManager] = None,
        network: str = "none",
    ) -> None:
        self.company_id = str(company_id) if company_id else "_shared"
        self.manager = manager or TenantSandboxManager()
        # The call's network policy (TL-15): it picks the container.
        self.network = network

    async def exec(
        self,
        argv: Sequence[str],
        *,
        cwd: Optional[str] = None,
        timeout: float = 30.0,
        env: Optional[Mapping[str, str]] = None,
    ) -> ExecResult:
        start = time.monotonic()
        try:
            name = await self.manager.ensure(self.company_id, network=self.network)
        except SandboxDockerError as exc:
            return ExecResult(returncode=-1, launch_error=unavailable(exc))

        # Host paths in, container paths back out (identity on a Linux host).
        roots = mounted_roots(self.company_id)
        exec_args: List[str] = ["exec", "-u", "10001:10001"]
        if cwd:
            exec_args += ["-w", to_container_text(cwd, roots)]
        for key, val in (env or {}).items():
            exec_args += ["-e", f"{key}={to_container_text(str(val), roots)}"]
        # Enforce the timeout inside the container so the real process dies.
        wrapped = [
            "timeout",
            "--kill-after=2",
            f"{int(max(1, timeout))}",
            *(to_container_text(str(a), roots) for a in argv),
        ]
        exec_args += [name, *wrapped]

        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                *exec_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            return ExecResult(
                returncode=-1, launch_error=unavailable("docker CLI not found on PATH")
            )

        try:
            out_b, err_b = await asyncio.wait_for(
                proc.communicate(), timeout=float(timeout) + 10.0
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ExecResult(
                returncode=-1,
                timed_out=True,
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        rc = proc.returncode if proc.returncode is not None else -1
        stdout = to_host_text(out_b.decode("utf-8", errors="replace"), roots)
        stderr = to_host_text(err_b.decode("utf-8", errors="replace"), roots)
        duration_ms = int((time.monotonic() - start) * 1000)

        if rc in _TIMEOUT_RCS:
            return ExecResult(returncode=-1, timed_out=True, duration_ms=duration_ms)
        if rc == _NOT_FOUND_RC:
            return ExecResult(
                returncode=rc,
                stdout=stdout,
                stderr=stderr,
                not_found=True,
                duration_ms=duration_ms,
            )
        return ExecResult(
            returncode=rc,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
        )

    async def run_browser(self, request: Mapping[str, Any], *, timeout: float) -> Dict[str, Any]:
        """The session's steps, run by the runner in the company's ``web``
        container (TL-18). A runner that reports nothing is an error."""
        from src.ai.tools.sandbox.workspace import tenant_workspace

        runner = install_browser_runner(self.company_id)
        call_dir = os.path.join(tenant_workspace(self.company_id), ".browser-calls", uuid.uuid4().hex[:12])
        os.makedirs(call_dir, exist_ok=True)
        request_path = os.path.join(call_dir, "request.json")
        with open(request_path, "w", encoding="utf-8") as fh:
            json.dump({"steps": list(request.get("steps") or []),
                       "timeout_ms": int(request.get("timeout_ms") or 30000)}, fh)
        # Chromium writes its caches under HOME; the image's root is read-only.
        env = {"HOME": "/tmp"}
        if request.get("out_dir"):
            env["ARTIFACTS_DIR"] = str(request["out_dir"])
        if request.get("user_data_dir"):
            env[browser_runner.PROFILE_ENV] = str(request["user_data_dir"])
        web = self if self.network == "web" else ContainerRuntime(self.company_id, manager=self.manager, network="web")
        try:
            res = await web.exec(["python3", runner, request_path], cwd=call_dir, timeout=timeout, env=env)
        finally:
            shutil.rmtree(call_dir, ignore_errors=True)
        if browser_runner.MARKER not in res.stdout:
            reason = res.launch_error or ("timed out" if res.timed_out else (res.stderr or res.stdout)[-500:])
            raise RuntimeError(f"the browser runner failed in the container: {reason}")
        return json.loads(res.stdout.split(browser_runner.MARKER, 1)[1].strip().splitlines()[0])

    # --- file ops: host side of the bind-mount (container sees the same bytes) ---
    async def write_file(self, path: str, content: bytes) -> None:
        with open(path, "wb") as fh:
            fh.write(content)

    async def read_file(self, path: str) -> bytes:
        with open(path, "rb") as fh:
            return fh.read()

    async def list_dir(self, path: str) -> List[str]:
        return os.listdir(path)

    # --- lifecycle: forward to the manager ---
    async def ensure(self) -> None:
        await self.manager.ensure(self.company_id, network=self.network)

    async def pause(self) -> None:
        await self.manager.pause(self.company_id, network=self.network)

    async def resume(self) -> None:
        await self.manager.resume(self.company_id, network=self.network)

    async def destroy(self) -> None:
        await self.manager.destroy(self.company_id)


def unavailable(reason: Any) -> str:
    """Why a sandbox call was refused, and what decides it (TL-01, D29): the
    container is the default, and there is no fallback to the host."""
    return (f"the container sandbox is unavailable on this host: {reason}. Code runs only in the "
            "company's container (SANDBOX_CONTAINER_RUNTIME_ENABLED is on): start Docker and build "
            "hb-sandbox (backend/docker/sandbox/build.sh), or, on a development machine, set "
            "SANDBOX_CONTAINER_RUNTIME_ENABLED=false in .env")


def install_browser_runner(company_id: str) -> str:
    """Write the runner under the company's ``.skills/`` root, which the
    container mounts read-only, once per runner version; return its host path."""
    from src.ai.tools.sandbox.skill_files import SKILLS_DIR, materialise

    with open(browser_runner.__file__, encoding="utf-8") as fh:
        source = fh.read()
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    root = materialise(company_id, f"{SKILLS_DIR}/.platform/browser", digest, {"browser_runner.py": source})
    return os.path.join(root, "browser_runner.py")
