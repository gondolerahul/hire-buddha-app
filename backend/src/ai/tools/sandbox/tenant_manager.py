"""
ai.tools.sandbox.tenant_manager — the per-tenant container lifecycle (Phase 12 `02` S4).

``TenantSandboxManager`` owns one long-lived Docker container per company: it
creates it from the pinned ``hb-sandbox`` image with kernel-level isolation,
reuses/resumes it on subsequent calls, and pauses/stops/destroys it on its TTLs.
``ContainerRuntime`` (the ``SandboxRuntime`` implementation) talks to it.

It shells out to the ``docker`` CLI via asyncio subprocesses rather than taking
a ``docker`` SDK dependency — the CLI is what production hosts already trust, and
it keeps the package free of a new runtime dependency.

The workspace model (S4): the host directory ``/tmp/sandbox/<company_id>`` is
bind-mounted into the container at the *identical absolute path*, so the existing
tools — which write a script to that host path and then ``exec`` it — work
unchanged and the workspace persists across container recreation. The shared
Document Factory dirs are bind-mounted read-only at their host paths too, so the
host-created symlinks resolve inside the container. (The plan's eventual private
named ``/workspace`` volume is an S5 follow-up that requires routing tool file IO
through the runtime.)

Isolation applied at ``docker run`` time: non-root user, read-only root FS,
tmpfs ``/tmp``, ``--cap-drop ALL``, ``no-new-privileges``, default-deny network
(``--network none``), and cpu/memory/pids limits. The image carries none of this
itself.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from src.common.config import settings

logger = logging.getLogger(__name__)

_LABEL = "hb-sandbox"


class SandboxDockerError(RuntimeError):
    """A ``docker`` CLI invocation failed (non-zero exit or missing binary)."""


@dataclass
class TenantSandboxConfig:
    """Resource + isolation policy for a tenant container. Defaults come from
    ``settings`` (env-overridable); a tier system can supply per-company values."""

    image: str = field(default_factory=lambda: settings.SANDBOX_IMAGE)
    network: str = field(default_factory=lambda: settings.SANDBOX_NETWORK)
    memory: str = field(default_factory=lambda: settings.SANDBOX_MEMORY)
    cpus: str = field(default_factory=lambda: settings.SANDBOX_CPUS)
    pids_limit: int = field(default_factory=lambda: settings.SANDBOX_PIDS_LIMIT)


def _sandbox_base_dir() -> str:
    return os.path.join(tempfile.gettempdir(), "sandbox")


class TenantSandboxManager:
    """Create/reuse/pause/reap one ``hb-sandbox`` container per company.

    Stateless across instances — all state lives in Docker — so it is safe to
    construct one per call. Concurrent ``ensure`` calls for the same company are
    serialized by a per-company asyncio lock to avoid a create race.
    """

    _locks: dict[str, asyncio.Lock] = {}

    def __init__(self, config: Optional[TenantSandboxConfig] = None) -> None:
        self.config = config or TenantSandboxConfig()

    @staticmethod
    def container_name(company_id: str, *, egress: bool = False) -> str:
        # Egress and no-network containers are kept separate (a running
        # container's network is fixed) so switching a company's NetworkPolicy
        # never has to mutate a live container's network.
        suffix = "-egress" if egress else ""
        return f"{_LABEL}-{company_id}{suffix}"

    @classmethod
    def _lock_for(cls, company_id: str) -> asyncio.Lock:
        lock = cls._locks.get(company_id)
        if lock is None:
            lock = asyncio.Lock()
            cls._locks[company_id] = lock
        return lock

    # ------------------------------------------------------------------
    # docker CLI helper
    # ------------------------------------------------------------------

    async def _docker(
        self, *args: str, timeout: float = 60.0, check: bool = True
    ) -> Tuple[int, str, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                *args,
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

    async def _status(self, name: str) -> Optional[str]:
        """Container state ('running'/'paused'/'exited'/...) or None if absent."""
        rc, out, _ = await self._docker(
            "inspect", "-f", "{{.State.Status}}", name, check=False
        )
        if rc != 0:
            return None
        return out.strip() or None

    # ------------------------------------------------------------------
    # mounts
    # ------------------------------------------------------------------

    def _mounts(self, company_id: str) -> List[str]:
        host_dir = os.path.join(_sandbox_base_dir(), company_id)
        os.makedirs(host_dir, exist_ok=True)
        try:
            from src.ai.tools.sandbox.sandbox_provision import (
                _resolve_shared_dirs,
                provision_sandbox,
            )

            provision_sandbox(host_dir)
            shared = _resolve_shared_dirs()
        except Exception as exc:  # noqa: BLE001 - provisioning is best-effort
            logger.warning("sandbox provisioning failed for %s: %s", company_id, exc)
            shared = []

        args: List[str] = ["-v", f"{host_dir}:{host_dir}"]
        for src, _name in shared:
            args += ["-v", f"{src}:{src}:ro"]
        return args

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def ensure(self, company_id: str, *, egress: bool = False) -> str:
        """Return the name of a running container for ``company_id``, creating,
        starting, or unpausing it as needed.

        When ``egress`` is set the container joins the allow-list egress network
        (`02`/`06` ``NetworkPolicy.ALLOWLIST``) instead of ``--network none``;
        the :class:`EgressProxyManager` is ensured first and its proxy is
        injected as ``HTTP(S)_PROXY``.
        """
        name = self.container_name(company_id, egress=egress)
        network = self.config.network
        proxy_env: List[str] = []
        if egress:
            from src.ai.tools.sandbox.egress_proxy import EgressProxyManager

            proxy = EgressProxyManager()
            proxy_url = await proxy.ensure()
            network = proxy.internal_network
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                proxy_env += ["-e", f"{key}={proxy_url}"]

        async with self._lock_for(name):
            status = await self._status(name)
            if status == "running":
                return name
            if status == "paused":
                await self._docker("unpause", name)
                return name
            if status in {"exited", "created", "dead"}:
                # A stopped container can't take new run-flags; recreate clean.
                await self._docker("rm", "-f", name, check=False)
            await self._create(company_id, name, network=network, extra_env=proxy_env)
            return name

    async def _create(
        self,
        company_id: str,
        name: str,
        *,
        network: Optional[str] = None,
        extra_env: Optional[List[str]] = None,
    ) -> None:
        cfg = self.config
        args = [
            "run",
            "-d",
            "--name",
            name,
            "--label",
            f"{_LABEL}=1",
            "--label",
            f"{_LABEL}-company={company_id}",
            "--user",
            "10001:10001",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,exec,size=512m",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--network",
            network or cfg.network,
            "--memory",
            cfg.memory,
            "--cpus",
            cfg.cpus,
            "--pids-limit",
            str(cfg.pids_limit),
        ]
        args += extra_env or []
        args += self._mounts(company_id)
        args += [cfg.image]
        await self._docker(*args, timeout=120.0)
        logger.info("created sandbox container %s (network=%s)", name, network or cfg.network)

    async def pause(self, company_id: str) -> None:
        name = self.container_name(company_id)
        if await self._status(name) == "running":
            await self._docker("pause", name, check=False)

    async def resume(self, company_id: str) -> None:
        await self.ensure(company_id)

    async def destroy(self, company_id: str) -> None:
        name = self.container_name(company_id)
        await self._docker("rm", "-f", name, check=False)

    # ------------------------------------------------------------------
    # reaper (operational; call from a cron/worker)
    # ------------------------------------------------------------------

    async def list_containers(self) -> List[Tuple[str, str]]:
        """All managed containers as (id, status) pairs."""
        rc, out, _ = await self._docker(
            "ps",
            "-a",
            "--filter",
            f"label={_LABEL}=1",
            "--format",
            "{{.ID}} {{.State}}",
            check=False,
        )
        if rc != 0:
            return []
        result: List[Tuple[str, str]] = []
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                result.append((parts[0], parts[1]))
        return result

    async def reap_exited(self) -> int:
        """Remove stopped managed containers (their bind-mounted workspace
        persists on the host). Returns the count removed. Idle-pause of *running*
        containers is the caller's policy via :meth:`pause`."""
        removed = 0
        for cid, state in await self.list_containers():
            if state in {"exited", "dead", "created"}:
                rc, _, _ = await self._docker("rm", "-f", cid, check=False)
                if rc == 0:
                    removed += 1
        return removed
