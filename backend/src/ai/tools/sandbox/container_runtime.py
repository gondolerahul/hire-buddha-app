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
* ``open_browser_session`` delegates to an embedded ``SubprocessRuntime`` (host,
  ephemeral) for now; moving Chromium into the container with a persistent
  profile is S5 (``sandbox.persistent_browser_enabled``).
* Lifecycle methods forward to the manager.

This is selected by ``get_sandbox_runtime`` only when the container runtime is
enabled (settings/flag, default OFF); on any Docker failure the tools' factory
falls back to ``SubprocessRuntime``.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import time
from typing import (
    Any,
    AsyncIterator,
    List,
    Mapping,
    Optional,
    Sequence,
)

from src.ai.tools.sandbox.runtime import (
    BrowserSession,
    ExecResult,
    SubprocessRuntime,
)
from src.ai.tools.sandbox.tenant_manager import (
    SandboxDockerError,
    TenantSandboxManager,
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
    ) -> None:
        self.company_id = str(company_id) if company_id else "_shared"
        self.manager = manager or TenantSandboxManager()
        # Host, ephemeral browser sessions until S5 moves Chromium in-container.
        self._browser_fallback = SubprocessRuntime(company_id=company_id)

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
            name = await self.manager.ensure(self.company_id)
        except SandboxDockerError as exc:
            return ExecResult(returncode=-1, launch_error=str(exc))

        exec_args: List[str] = ["exec", "-u", "10001:10001"]
        if cwd:
            exec_args += ["-w", cwd]
        for key, val in (env or {}).items():
            exec_args += ["-e", f"{key}={val}"]
        # Enforce the timeout inside the container so the real process dies.
        wrapped = [
            "timeout",
            "--kill-after=2",
            f"{int(max(1, timeout))}",
            *argv,
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
                returncode=-1, launch_error="docker CLI not found on PATH"
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
        stdout = out_b.decode("utf-8", errors="replace")
        stderr = err_b.decode("utf-8", errors="replace")
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

    @contextlib.asynccontextmanager
    async def open_browser_session(
        self,
        *,
        timeout_ms: int = 30000,
        viewport: Optional[Mapping[str, int]] = None,
        user_agent: Optional[str] = None,
        persona: Optional[str] = None,
        user_data_dir: Optional[str] = None,
    ) -> AsyncIterator[BrowserSession]:
        # The browser runs on the host for now (S5 persistence via the profile
        # dir, which lives on the bind-mounted tenant workspace so it is the same
        # bytes the container would see); running Chromium *inside* the container
        # over CDP is a later hardening.
        async with self._browser_fallback.open_browser_session(
            timeout_ms=timeout_ms,
            viewport=viewport,
            user_agent=user_agent,
            persona=persona,
            user_data_dir=user_data_dir,
        ) as session:
            yield session

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
        await self.manager.ensure(self.company_id)

    async def pause(self) -> None:
        await self.manager.pause(self.company_id)

    async def resume(self) -> None:
        await self.manager.resume(self.company_id)

    async def destroy(self) -> None:
        await self.manager.destroy(self.company_id)
