"""ai.tools.sandbox.egress_proxy — the sandbox network gate (Phase 12 `02`/`06`).

When a tool's ``NetworkPolicy`` is ``ALLOWLIST`` (synthesized / network-using
tools), the sandbox container must reach a *few* approved hosts without getting
the open internet. ``EgressProxyManager`` stands up the mechanism that makes
that safe:

  * an ``--internal`` docker network (``SANDBOX_EGRESS_NETWORK``) with **no**
    route to the internet — the sandbox joins only this;
  * a normal "uplink" bridge network (``SANDBOX_EGRESS_UPLINK_NETWORK``) that
    does have internet;
  * one **dual-homed** ``hb-egress-proxy`` container attached to *both*, running
    tinyproxy with ``FilterDefaultDeny`` over ``SANDBOX_EGRESS_ALLOWLIST``.

So the sandbox's only route out is the proxy, and the proxy only permits the
allow-list. Even if tool code ignores the ``HTTP(S)_PROXY`` env, the internal
network gives it nowhere to connect. Verified end-to-end:
allow-listed host reachable, others refused, no-proxy egress has no route.

Idempotent + docker-CLI-only, mirroring ``TenantSandboxManager``.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional, Tuple

from src.ai.tools.sandbox.tenant_manager import SandboxDockerError
from src.common.config import settings

logger = logging.getLogger(__name__)

_PROXY_NAME = "hb-egress-proxy"
_LABEL = "hb-egress"


class EgressProxyManager:
    """Ensure the egress networks + the dual-homed allow-list proxy exist."""

    _lock = asyncio.Lock()

    def __init__(
        self,
        *,
        proxy_image: Optional[str] = None,
        internal_network: Optional[str] = None,
        uplink_network: Optional[str] = None,
        proxy_port: Optional[int] = None,
        allowlist: Optional[str] = None,
    ) -> None:
        self.proxy_image = proxy_image or settings.SANDBOX_EGRESS_IMAGE
        self.internal_network = internal_network or settings.SANDBOX_EGRESS_NETWORK
        self.uplink_network = uplink_network or settings.SANDBOX_EGRESS_UPLINK_NETWORK
        self.proxy_port = proxy_port or settings.SANDBOX_EGRESS_PROXY_PORT
        self.allowlist = allowlist or settings.SANDBOX_EGRESS_ALLOWLIST

    @property
    def proxy_url(self) -> str:
        """The HTTP(S)_PROXY value a sandbox container on the internal net uses."""
        return f"http://{_PROXY_NAME}:{self.proxy_port}"

    # ------------------------------------------------------------------
    # docker CLI helper (same shape as TenantSandboxManager._docker)
    # ------------------------------------------------------------------

    async def _docker(
        self, *args: str, timeout: float = 60.0, check: bool = True
    ) -> Tuple[int, str, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise SandboxDockerError("docker CLI not found on PATH") from exc
        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise SandboxDockerError(f"docker {args[0]} timed out") from exc
        out = out_b.decode("utf-8", errors="replace")
        err = err_b.decode("utf-8", errors="replace")
        rc = proc.returncode if proc.returncode is not None else -1
        if check and rc != 0:
            raise SandboxDockerError(f"docker {args[0]} failed (rc={rc}): {err.strip()}")
        return rc, out, err

    async def _network_exists(self, name: str) -> bool:
        rc, _, _ = await self._docker("network", "inspect", name, check=False)
        return rc == 0

    async def _ensure_network(self, name: str, *, internal: bool) -> None:
        if await self._network_exists(name):
            return
        args = ["network", "create"]
        if internal:
            args.append("--internal")
        args += ["--label", f"{_LABEL}=1", name]
        await self._docker(*args)
        logger.info("created egress network %s (internal=%s)", name, internal)

    async def _proxy_status(self) -> Optional[str]:
        rc, out, _ = await self._docker(
            "inspect", "-f", "{{.State.Status}}", _PROXY_NAME, check=False
        )
        if rc != 0:
            return None
        return out.strip() or None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def ensure(self) -> str:
        """Ensure both networks + a running proxy; return the proxy URL.

        Serialised by a process lock so concurrent first-time callers don't race
        on create. Safe to call before every egress-mode sandbox launch.
        """
        async with self._lock:
            await self._ensure_network(self.uplink_network, internal=False)
            await self._ensure_network(self.internal_network, internal=True)

            status = await self._proxy_status()
            if status == "running":
                return self.proxy_url
            if status == "paused":
                await self._docker("unpause", _PROXY_NAME)
                return self.proxy_url
            # Any other state (exited/created/dead/restarting/None-but-present)
            # → remove and recreate clean. rm is a no-op if it's truly absent.
            await self._docker("rm", "-f", _PROXY_NAME, check=False)

            # Create on the uplink network, then attach the internal one so the
            # proxy is dual-homed. cap-drop ALL but keep SETUID/SETGID so
            # tinyproxy can drop from root to its own user (the conf's User/Group).
            await self._docker(
                "run", "-d",
                "--name", _PROXY_NAME,
                "--label", f"{_LABEL}=1",
                "--restart", "unless-stopped",
                "--network", self.uplink_network,
                "--cap-drop", "ALL",
                "--cap-add", "SETUID",
                "--cap-add", "SETGID",
                "--security-opt", "no-new-privileges",
                "-e", f"ALLOWLIST={self.allowlist}",
                self.proxy_image,
                timeout=120.0,
            )
            await self._docker("network", "connect", self.internal_network, _PROXY_NAME)
            logger.info("started egress proxy %s (allowlist=%s)", _PROXY_NAME, self.allowlist)
            return self.proxy_url

    async def destroy(self) -> None:
        await self._docker("rm", "-f", _PROXY_NAME, check=False)
        await self._docker("network", "rm", self.internal_network, check=False)
        await self._docker("network", "rm", self.uplink_network, check=False)
