"""
ai.tools.sandbox.runtime — the SandboxRuntime boundary (Phase 12 `02` S1/S2).

The sandbox/terminal/browser tools used to each own their subprocess /
Playwright logic. This module introduces a single runtime abstraction they
delegate to, so the *execution substrate* can later be swapped (a persistent
per-tenant Docker `ContainerRuntime`, `02` S4) without touching the tools.

* ``SandboxRuntime`` — the Protocol (exec, file ops, browser session, lifecycle).
* ``ExecResult`` / ``BrowserSession`` — the DTOs the Protocol traffics in.
* ``SubprocessRuntime`` — today's behavior (host asyncio subprocess + a fresh
  Playwright Chromium per session). The default in dev/CI and the production
  rollback path.
* ``get_sandbox_runtime`` — the factory the tools call. Returns
  ``SubprocessRuntime`` until the (S4) ``ContainerRuntime`` lands behind
  ``sandbox.container_runtime_enabled``.

The tools keep their arg-parsing + output-shaping + artifact logic; they hand
the runtime a fully-built argv/env (or browser action) and shape the
``ExecResult`` / page back into their tool contract. Behaviour is unchanged.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import time
from dataclasses import dataclass
from typing import (
    Any,
    AsyncIterator,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    runtime_checkable,
)

# Default Chromium context settings — preserved verbatim from the legacy
# HeadlessBrowserTool so SubprocessRuntime is byte-for-byte today's behavior.
_DEFAULT_VIEWPORT = {"width": 1280, "height": 720}
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 "
    "HireBuddha-AI-Agent/1.0"
)


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


class BrowserSession:
    """A live browser page plus the Playwright objects backing it.

    Yielded by ``SandboxRuntime.open_browser_session``. The tool's action
    methods operate on ``.page``; the runtime owns teardown.
    """

    def __init__(
        self,
        page: Any,
        *,
        _playwright: Any = None,
        _browser: Any = None,
        _context: Any = None,
    ) -> None:
        self.page = page
        self._playwright = _playwright
        self._browser = _browser
        self._context = _context

    async def aclose(self) -> None:
        for closer in (
            getattr(self._context, "close", None),
            getattr(self._browser, "close", None),
            getattr(self._playwright, "stop", None),
        ):
            if closer is None:
                continue
            try:
                await closer()
            except Exception:  # pragma: no cover - best-effort teardown
                pass


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

    def open_browser_session(
        self,
        *,
        timeout_ms: int = 30000,
        viewport: Optional[Mapping[str, int]] = None,
        user_agent: Optional[str] = None,
        persona: Optional[str] = None,
        user_data_dir: Optional[str] = None,
    ) -> "contextlib.AbstractAsyncContextManager[BrowserSession]":
        """Async context manager yielding a ``BrowserSession``.

        ``user_data_dir`` (S5): when set, a persistent Chromium profile rooted
        there is reused, so cookies/logins survive across sessions.
        """
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


class SubprocessRuntime:
    """Today's behavior behind the Protocol: host asyncio subprocesses + a
    fresh ephemeral Playwright Chromium per browser session. No persistence,
    no container — the dev/CI default and the production rollback path."""

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

    @contextlib.asynccontextmanager
    async def open_browser_session(
        self,
        *,
        timeout_ms: int = 30000,
        viewport: Optional[Mapping[str, int]] = None,
        user_agent: Optional[str] = None,
        persona: Optional[str] = None,  # noqa: ARG002 - reserved for callers
        user_data_dir: Optional[str] = None,
    ) -> AsyncIterator[BrowserSession]:
        # Imported lazily so the module loads without Playwright; the caller
        # catches ImportError to reproduce the tool's "not installed" message.
        from playwright.async_api import async_playwright

        pw = await async_playwright().start()
        if user_data_dir:
            # S5 persistent profile: launch_persistent_context owns the browser,
            # so there is no separate browser handle; closing the context tears
            # everything down. The profile dir persists cookies/logins on close.
            os.makedirs(user_data_dir, exist_ok=True)
            ctx = await pw.chromium.launch_persistent_context(
                user_data_dir,
                headless=True,
                viewport=dict(viewport) if viewport else dict(_DEFAULT_VIEWPORT),
                user_agent=user_agent or _DEFAULT_USER_AGENT,
            )
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            page.set_default_timeout(timeout_ms)
            session = BrowserSession(page, _playwright=pw, _browser=None, _context=ctx)
        else:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                viewport=dict(viewport) if viewport else dict(_DEFAULT_VIEWPORT),
                user_agent=user_agent or _DEFAULT_USER_AGENT,
            )
            page = await ctx.new_page()
            page.set_default_timeout(timeout_ms)
            session = BrowserSession(
                page, _playwright=pw, _browser=browser, _context=ctx
            )
        try:
            yield session
        finally:
            await session.aclose()

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


def _container_runtime_selected(context: Optional[Mapping[str, Any]]) -> bool:
    """Whether the per-tenant ``ContainerRuntime`` should be used.

    An explicit ``context["container_runtime"]`` wins (this is where a caller
    threads a resolved per-company ``sandbox.container_runtime_enabled`` feature
    flag); otherwise the process-wide ``SANDBOX_CONTAINER_RUNTIME_ENABLED``
    setting decides. Default OFF.
    """
    if context is not None and "container_runtime" in context:
        return bool(context["container_runtime"])
    try:
        from src.common.config import settings

        return bool(settings.SANDBOX_CONTAINER_RUNTIME_ENABLED)
    except Exception:  # noqa: BLE001 - config import must never break tools
        return False


def get_sandbox_runtime(context: Optional[Mapping[str, Any]] = None) -> SandboxRuntime:
    """Return the runtime the sandbox tools should use.

    Defaults to ``SubprocessRuntime`` (today's behavior, the dev/CI default and
    the production rollback path). When the per-tenant container runtime is
    enabled (settings/flag, default OFF) this returns a ``ContainerRuntime``;
    importing it is deferred so a host without Docker support never pays for it,
    and any import failure falls back to ``SubprocessRuntime``. The tools never
    change.
    """
    company_id = None
    if context:
        cid = context.get("company_id")
        company_id = str(cid) if cid else None

    if _container_runtime_selected(context):
        try:
            from src.ai.tools.sandbox.container_runtime import ContainerRuntime

            return ContainerRuntime(company_id=company_id)
        except Exception:  # noqa: BLE001 - never let container selection break a tool
            return SubprocessRuntime(company_id=company_id)

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


async def _resolve_company_container_flag(company_id: Optional[str]) -> Optional[bool]:
    """Per-company ``sandbox.container_runtime_enabled`` (see _resolve_company_flag)."""
    return await _resolve_company_flag("sandbox.container_runtime_enabled", company_id)


async def resolve_sandbox_runtime(
    context: Optional[Mapping[str, Any]] = None,
) -> "SandboxRuntime":
    """Async runtime selection that honors the per-company canary flag.

    The sync :func:`get_sandbox_runtime` can't await DB flag resolution, so tools
    call this instead: it resolves the per-company
    ``sandbox.container_runtime_enabled`` flag and threads the result into the
    context as ``container_runtime`` (an explicit override the sync factory then
    respects), with the process-wide setting as the fallback when no explicit
    flag row exists.
    """
    ctx: dict[str, Any] = dict(context or {})
    if "container_runtime" not in ctx:
        flag = await _resolve_company_container_flag(ctx.get("company_id"))
        if flag is not None:
            ctx["container_runtime"] = flag
    return get_sandbox_runtime(ctx)


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
    import tempfile

    return os.path.join(tempfile.gettempdir(), "sandbox")


async def run_sandbox_exec(
    context: Optional[Mapping[str, Any]],
    argv: Sequence[str],
    *,
    cwd: Optional[str] = None,
    timeout: float = 30.0,
    env: Optional[Mapping[str, str]] = None,
) -> ExecResult:
    """Resolve the runtime (with per-company canary), run ``argv``, and meter the
    cost (Phase 12 `02` S6). The single entry point the exec-based sandbox tools
    use so runtime selection + cost attribution live in one place."""
    runtime = await resolve_sandbox_runtime(context)
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
