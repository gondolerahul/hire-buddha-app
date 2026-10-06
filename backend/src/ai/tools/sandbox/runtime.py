"""
ai.tools.sandbox.runtime — the SandboxRuntime boundary (Phase 12 `02` S1/S2).

The sandbox/terminal/browser tools used to each own their subprocess /
Playwright logic. This module introduces a single runtime abstraction they
delegate to, so the *execution substrate* can later be swapped (a persistent
per-tenant Docker `ContainerRuntime`, `02` S4) without touching the tools.

* ``SandboxRuntime`` — the Protocol (exec, file ops, browser session, lifecycle).
* ``ExecResult`` — the DTO the Protocol's ``exec`` returns. A browser session
  is a request the runtime runs (``run_browser``): the steps travel, not a
  page, so the browser can run inside the container (TL-18).
* ``SubprocessRuntime`` — the host runtime (asyncio subprocess; a browser
  session in-process behind the SSRF guard). Development's runtime.
* ``resolve_sandbox_runtime`` — what the tools call: ``ContainerRuntime`` when
  the one switch, ``sandbox.container_runtime_enabled``, is on for the company
  (its default is the deployment's ``SANDBOX_CONTAINER_RUNTIME_ENABLED``),
  else ``SubprocessRuntime``. A container runtime that cannot be built is an
  error, never a silent fallback to the host (TX-01, TL-01).

The tools keep their arg-parsing + output-shaping + artifact logic; they hand
the runtime a fully-built argv/env (or browser action) and shape the
``ExecResult`` / page back into their tool contract. Behaviour is unchanged.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    runtime_checkable,
)

logger = logging.getLogger(__name__)


@dataclass
class ExecResult:
    """Outcome of a single ``SandboxRuntime.exec`` call.

    The runtime captures the raw process result; truncation, JSON/string
    shaping, and error wording are the tool's concern.
    """

    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    duration_ms: int = 0
    # Set when the process could not be launched at all (e.g. interpreter
    # missing). ``not_found`` distinguishes FileNotFoundError from other launch
    # failures so the tool can reproduce its exact message.
    launch_error: Optional[str] = None
    not_found: bool = False

    @property
    def ok(self) -> bool:
        return (
            self.returncode == 0
            and not self.timed_out
            and self.launch_error is None
        )


@runtime_checkable
class SandboxRuntime(Protocol):
    """The execution substrate the sandbox tools delegate to.

    Two implementations: ``SubprocessRuntime`` (host, today's behavior) and —
    later — ``ContainerRuntime`` (persistent per-tenant Docker, `02` S4). Tool
    code never knows which it got.
    """

    async def exec(
        self,
        argv: Sequence[str],
        *,
        cwd: Optional[str] = None,
        timeout: float = 30.0,
        env: Optional[Mapping[str, str]] = None,
    ) -> ExecResult:
        """Run ``argv`` to completion (or ``timeout``), capturing stdout/stderr."""
        ...

    async def run_browser(self, request: Mapping[str, Any], *, timeout: float) -> Dict[str, Any]:
        """Run one browser session: ``request`` is a
        :mod:`~src.ai.tools.sandbox.browser_runner` request (``steps``,
        ``timeout_ms``, ``user_data_dir``, ``out_dir``); the result is its
        ``steps`` and ``blocked_requests``."""
        ...

    # --- file ops (host FS today; tenant volume under ContainerRuntime) ---
    async def write_file(self, path: str, content: bytes) -> None: ...
    async def read_file(self, path: str) -> bytes: ...
    async def list_dir(self, path: str) -> List[str]: ...

    # --- lifecycle (no-ops for SubprocessRuntime; real for ContainerRuntime) ---
    async def ensure(self) -> None: ...
    async def pause(self) -> None: ...
    async def resume(self) -> None: ...
    async def destroy(self) -> None: ...


async def guard_requests(page: Any) -> list[str]:
    """Check every request a host page makes against the SSRF guard (TL-08).

    Navigation, redirects, frames, subresources and script-driven requests all
    pass through Playwright's router, so ``evaluate`` cannot reach an internal
    host either. Returns the list the refused URLs are appended to. (In the
    container the egress proxy does this, for the address it connects to.)
    """
    from urllib.parse import urlsplit

    from src.common.net_guard import BlockedURL, check_url

    refused: list[str] = []
    verdicts: dict[str, bool] = {}  # per host, for the life of the session

    async def _route(route: Any) -> None:
        url = route.request.url
        if url.startswith(("data:", "blob:", "about:")):  # in-page, no network
            await route.continue_()
            return
        key = urlsplit(url).netloc.lower()
        if key not in verdicts:
            try:
                await check_url(url)
                verdicts[key] = True
            except BlockedURL:
                verdicts[key] = False
        if verdicts[key]:
            await route.continue_()
        else:
            refused.append(url)
            await route.abort("blockedbyclient")

    await page.route("**/*", _route)
    return refused


class SubprocessRuntime:
    """The host runtime: asyncio subprocesses as the backend's OS user, and a
    browser session in-process. Development's runtime; production runs the
    container runtime (TL-01)."""

    def __init__(self, company_id: Optional[str] = None) -> None:
        self.company_id = company_id

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
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=dict(env) if env is not None else None,
            )
        except FileNotFoundError:
            return ExecResult(
                returncode=-1,
                launch_error=f"{argv[0] if argv else ''} not found",
                not_found=True,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as a launch error
            return ExecResult(returncode=-1, launch_error=str(exc))

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=float(timeout)
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ExecResult(
                returncode=-1,
                timed_out=True,
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        return ExecResult(
            returncode=proc.returncode if proc.returncode is not None else -1,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    async def run_browser(self, request: Mapping[str, Any], *, timeout: float) -> Dict[str, Any]:
        """On the host, in-process: every navigation is checked against the
        SSRF guard first, and every request the page makes is routed through
        it (TL-08). Playwright is imported lazily; the tool reports its absence."""
        from src.ai.tools.sandbox import browser_runner
        from src.common.net_guard import check_url

        return await asyncio.wait_for(
            browser_runner.run_session(dict(request), check_url=check_url, guard=guard_requests),
            timeout=timeout,
        )

    # --- file ops (thin host-FS wrappers) ---
    async def write_file(self, path: str, content: bytes) -> None:
        with open(path, "wb") as fh:
            fh.write(content)

    async def read_file(self, path: str) -> bytes:
        with open(path, "rb") as fh:
            return fh.read()

    async def list_dir(self, path: str) -> List[str]:
        return os.listdir(path)

    # --- lifecycle: nothing to manage for a host subprocess runtime ---
    async def ensure(self) -> None:
        return None

    async def pause(self) -> None:
        return None

    async def resume(self) -> None:
        return None

    async def destroy(self) -> None:
        return None


def get_sandbox_runtime(
    context: Optional[Mapping[str, Any]] = None, *, container: bool = False, network: str = "none",
) -> SandboxRuntime:
    """The runtime for this call: ``ContainerRuntime`` when ``container``, else
    ``SubprocessRuntime``. Use :func:`resolve_sandbox_runtime`, which decides
    ``container`` from the one switch.

    A container runtime that cannot be built raises: it is never replaced by
    the host runtime, which runs the code as the backend's own OS user (TL-01).
    """
    company_id = None
    if context:
        cid = context.get("company_id")
        company_id = str(cid) if cid else None
    if container:
        from src.ai.tools.sandbox.container_runtime import ContainerRuntime

        return ContainerRuntime(company_id=company_id, network=network)
    return SubprocessRuntime(company_id=company_id)


# Feature-flag sources that represent an EXPLICIT per-scope decision (a DB row),
# as opposed to the env/default fall-through that the settings master covers.
_EXPLICIT_FLAG_SOURCES = {"entity", "entity_row", "company", "global"}


async def _resolve_company_flag(
    flag_key: str, company_id: Optional[str]
) -> Optional[bool]:
    """Resolve a per-company sandbox flag from the DB.

    Returns the value only when an explicit per-scope row exists (entity /
    company / global); otherwise ``None`` so the caller falls through to the
    process-wide setting. Any error (no DB, no migration) is swallowed → ``None``.
    """
    if not company_id:
        return None
    try:
        from uuid import UUID

        from src.ai.core.feature_flags import FeatureFlags
        from src.common.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            res = await FeatureFlags(db).resolve(
                flag_key, company_id=UUID(str(company_id))
            )
        if res.source in _EXPLICIT_FLAG_SOURCES:
            return bool(res.value)
        return None
    except Exception:  # noqa: BLE001 - flag resolution must never break a tool
        return None


async def container_runtime_enabled(company_id: Optional[str]) -> bool:
    """The one switch (TX-01): ``sandbox.container_runtime_enabled`` for this
    company — its row, the global row, ``AI_FLAG_SANDBOX_CONTAINER_RUNTIME_ENABLED``,
    then the deployment default (``SANDBOX_CONTAINER_RUNTIME_ENABLED``)."""
    from uuid import UUID

    from src.ai.core.feature_flags import DEFAULTS, FeatureFlags
    from src.common.database import AsyncSessionLocal

    key = "sandbox.container_runtime_enabled"
    try:
        async with AsyncSessionLocal() as db:
            return await FeatureFlags(db).is_on(
                key, company_id=UUID(str(company_id)) if company_id else None)
    except Exception as exc:  # noqa: BLE001 - no DB: the deployment default decides
        logger.warning("sandbox switch unresolved (%s); using the deployment default", exc)
        return bool(DEFAULTS.get(key, False))


async def resolve_sandbox_runtime(
    context: Optional[Mapping[str, Any]] = None, *, network: str = "none",
) -> "SandboxRuntime":
    """The runtime for a tool call, chosen by the one switch for its company.
    ``network`` is the call's policy — ``none``, ``allowlist`` (TL-15) or
    ``web`` (TL-18) — which only the container runtime can enforce."""
    company_id = (context or {}).get("company_id")
    return get_sandbox_runtime(context, container=await container_runtime_enabled(company_id), network=network)


async def resolve_persistent_browser_dir(
    context: Optional[Mapping[str, Any]] = None,
) -> Optional[str]:
    """Return the persistent Chromium profile dir for this call, or ``None``.

    Persistence (S5) is on when an explicit ``context["persistent_browser"]`` is
    truthy, or the per-company ``sandbox.persistent_browser_enabled`` flag is set,
    or the ``SANDBOX_PERSISTENT_BROWSER_ENABLED`` setting is on. Requires a
    ``company_id``; the profile lives under the tenant workspace (so it is the
    same dir the container sees via the bind-mount), namespaced by ``persona``.
    """
    if context is None:
        return None
    company_id = context.get("company_id")
    if not company_id:
        return None

    enabled: Optional[bool] = None
    if "persistent_browser" in context:
        enabled = bool(context["persistent_browser"])
    if enabled is None:
        flag = await _resolve_company_flag("sandbox.persistent_browser_enabled", company_id)
        if flag is not None:
            enabled = flag
    if enabled is None:
        try:
            from src.common.config import settings

            enabled = bool(settings.SANDBOX_PERSISTENT_BROWSER_ENABLED)
        except Exception:  # noqa: BLE001
            enabled = False
    if not enabled:
        return None

    persona = str(context.get("persona") or "default")
    base = os.path.join(_sandbox_base_dir(), str(company_id), ".browser", persona)
    return base


def _sandbox_base_dir() -> str:
    from src.ai.tools.sandbox.workspace import workspace_root

    return workspace_root()


async def run_sandbox_exec(
    context: Optional[Mapping[str, Any]],
    argv: Sequence[str],
    *,
    cwd: Optional[str] = None,
    timeout: float = 30.0,
    env: Optional[Mapping[str, str]] = None,
    network: str = "none",
) -> ExecResult:
    """Resolve the runtime (with per-company canary), run ``argv``, and meter the
    cost (Phase 12 `02` S6). The single entry point the exec-based sandbox tools
    use so runtime selection + cost attribution live in one place. ``network``
    is the call's policy (TL-15): it used to be dropped, so every container
    ran ``--network none`` and the egress proxy had no caller."""
    runtime = await resolve_sandbox_runtime(context, network=network)
    res = await runtime.exec(argv, cwd=cwd, timeout=timeout, env=env)
    try:
        from src.ai.tools.sandbox.metering import meter_sandbox_usage

        await meter_sandbox_usage(
            context,
            duration_ms=res.duration_ms,
            runtime_name=type(runtime).__name__,
            kind="exec",
        )
    except Exception:  # noqa: BLE001 - metering must never break a tool
        pass
    return res
