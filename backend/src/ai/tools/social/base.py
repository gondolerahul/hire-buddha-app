"""
SocialMediaTool — Abstract base class for all social media AI tools.

Provides shared functionality:
- Credential resolution from social_connections table
- HTTP request helper with retry + error handling
- Standard JSON function schema pattern
"""
import asyncio
import contextvars
import json
import logging
import random
from abc import abstractmethod
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional

import httpx

from src.ai.tools.base import NO_CONTEXT_ERROR, Tool, ToolStatus, context_company_id

logger = logging.getLogger(__name__)

# Default timeout for all social API calls
DEFAULT_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
# What a platform says under load, and is worth waiting out (TL-37).
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_MAX_WAIT_S = 30.0
# A write is retried only when the platform cannot have acted on it: 429
# (refused before processing) and a connection that never opened. A 5xx or a
# timeout on a write may already have posted.
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# The next-page markers the responses of one operation carried (TL-38).
_PAGES: contextvars.ContextVar[Optional[List[str]]] = contextvars.ContextVar("social_pages", default=None)


def _backoff(attempt: int) -> float:
    return min(_MAX_WAIT_S, (2 ** attempt) + random.uniform(0, 0.5))


def _retry_after(resp: httpx.Response, attempt: int) -> float:
    """``Retry-After`` (seconds or an HTTP date), else exponential backoff; capped."""
    header = resp.headers.get("Retry-After")
    if header:
        try:
            return min(_MAX_WAIT_S, max(0.0, float(header)))
        except ValueError:
            try:
                from datetime import datetime, timezone
                when = parsedate_to_datetime(header)
                return min(_MAX_WAIT_S, max(0.0, (when - datetime.now(timezone.utc)).total_seconds()))
            except (TypeError, ValueError):
                pass
    return _backoff(attempt)


def next_page(body: Any) -> Optional[str]:
    """The cursor of the next page a list response points to, if any.

    Each platform says it its own way: Facebook and Instagram ``paging.next``
    (cursor ``paging.cursors.after``), LinkedIn ``paging`` start/count/total,
    X ``meta.next_token``, Google ``nextPageToken``, Reddit ``data.after``,
    TikTok ``has_more`` with ``cursor``.
    """
    if not isinstance(body, dict):
        return None
    paging = body.get("paging")
    if isinstance(paging, dict):
        if paging.get("next"):
            cursors = paging.get("cursors") if isinstance(paging.get("cursors"), dict) else {}
            return str(cursors.get("after") or paging["next"])
        start, count, total = paging.get("start"), paging.get("count"), paging.get("total")
        if all(isinstance(v, int) for v in (start, count, total)) and start + count < total:
            return str(start + count)
    for key in ("nextPageToken", "next_page_token"):
        if body.get(key):
            return str(body[key])
    meta = body.get("meta")
    if isinstance(meta, dict) and meta.get("next_token"):
        return str(meta["next_token"])
    data = body.get("data")
    for holder in (data, body):
        if isinstance(holder, dict):
            if holder is data and holder.get("after"):
                return str(holder["after"])
            if holder.get("has_more") and holder.get("cursor") is not None:
                return str(holder["cursor"])
    return None


class SocialMediaTool(Tool):
    """
    Abstract base class for social media platform tools.

    Subclasses MUST set:
        - name: str
        - description: str
        - platform: str  (e.g. 'linkedin', 'twitter', 'facebook')

    Subclasses implement:
        - _execute(params, credentials, context) -> dict
        - get_function_schema() -> dict
    """

    platform: str = ""  # Override in subclass

    # C8 social audit (Phase 12): the 15 social/ads platform integrations are
    # not yet wired to any production entity and several are unfinished. They
    # are tagged EXPERIMENTAL so they require an explicit per-company opt-in
    # (``tools.experimental.{tool_id}=true``) before an agent can use them;
    # ``ai.governance.tool_access.ToolAccess`` enforces it on every call. Promote an individual platform to ``ToolStatus.ACTIVE`` on its
    # subclass once it is verified end-to-end. See tools/integrations README.
    status: ToolStatus = ToolStatus.EXPERIMENTAL

    async def run(self, input_data: str) -> str:
        """Delegate to run_with_context (credentials require context)."""
        return await self.run_with_context(input_data, None)

    async def run_with_context(
        self, input_data: str, context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Parse input, resolve credentials, and execute the platform-specific action.
        """
        try:
            params = json.loads(input_data) if isinstance(input_data, str) else input_data
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON input"})

        # Resolve credentials from social_connections table
        company_id = context_company_id(context)
        if not company_id:
            return json.dumps({"error": NO_CONTEXT_ERROR})

        from src.ai.social_connection_service import resolve_connection

        credentials = await resolve_connection(
            company_id=company_id,
            platform=self.platform,
            account_name=params.get("account_name"),
            platform_user_id=params.get("platform_user_id"),
        )

        if not credentials or not credentials.get("access_token"):
            return json.dumps({
                "error": (
                    f"No active {self.platform} connection found for this company. "
                    f"Please configure a social connection first via POST /api/social-connections."
                )
            })

        pages = _PAGES.set([])
        try:
            result = await self._execute(params, credentials, context)
            more = _PAGES.get() or []
            if more and isinstance(result, dict):
                # The platform has more than it returned: say so, and give the
                # cursor (TL-38). Results used to read as the complete set.
                result["truncated"] = True
                result["next_page"] = more[-1]
            return json.dumps(result)
        except httpx.HTTPStatusError as e:
            logger.error(f"[{self.name}] HTTP error: {e.response.status_code} {e.response.text}")
            return json.dumps({
                "error": f"API request failed: {e.response.status_code}",
                "detail": e.response.text[:500],
            })
        except httpx.TimeoutException:
            logger.error(f"[{self.name}] Request timed out")
            return json.dumps({"error": f"{self.platform} API request timed out"})
        except Exception as e:
            logger.error(f"[{self.name}] Execution error: {e}", exc_info=True)
            return json.dumps({"error": f"{self.name} failed: {str(e)}"})
        finally:
            _PAGES.reset(pages)

    @abstractmethod
    async def _execute(
        self,
        params: Dict[str, Any],
        credentials: Dict[str, Any],
        context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Platform-specific execution logic.

        Args:
            params: Parsed JSON input from the LLM
            credentials: Decrypted tokens from social_connection_service
            context: Extra execution context (company_id, user_id, etc.)

        Returns:
            Dict with the result to be JSON-serialized back to the LLM
        """
        ...

    # ------------------------------------------------------------------
    # Shared HTTP helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _api_request(
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        timeout: int = DEFAULT_TIMEOUT,
        content: Optional[bytes] = None,
    ) -> httpx.Response:
        """An HTTP request, retried when the platform says to wait (TL-37).

        A read is retried on 429, 5xx, a timeout or a refused connection; a
        write only on 429 and a refused connection. Waits honour
        ``Retry-After``, else back off exponentially with jitter, capped at
        30 s. Raises ``httpx.HTTPStatusError`` on the final 4xx/5xx.
        """
        write = method.upper() in _WRITE_METHODS
        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(MAX_RETRIES + 1):
                last = attempt == MAX_RETRIES
                try:
                    resp = await client.request(
                        method=method,
                        url=url,
                        headers=headers,
                        json=json_body,
                        params=params,
                        data=data,
                        content=content,
                    )
                except httpx.ConnectError as e:
                    if last:
                        raise
                    logger.warning(f"[SocialMediaTool] connect retry {attempt + 1}/{MAX_RETRIES}: {e}")
                    await asyncio.sleep(_backoff(attempt))
                    continue
                except httpx.TimeoutException as e:
                    if last or write:
                        raise
                    logger.warning(f"[SocialMediaTool] timeout retry {attempt + 1}/{MAX_RETRIES}: {e}")
                    await asyncio.sleep(_backoff(attempt))
                    continue
                retryable = resp.status_code == 429 or (resp.status_code in _RETRY_STATUSES and not write)
                if retryable and not last:
                    wait = _retry_after(resp, attempt)
                    logger.warning(f"[SocialMediaTool] {resp.status_code}; retry {attempt + 1}/{MAX_RETRIES} in {wait:.1f}s")
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                pages = _PAGES.get()
                if pages is not None:
                    try:
                        marker = next_page(resp.json())
                    except ValueError:
                        marker = None
                    if marker:
                        pages.append(marker)
                return resp
        raise RuntimeError("unreachable")  # pragma: no cover

    @staticmethod
    async def _download(url: str, max_bytes: int) -> tuple[bytes, str]:
        """A public file's bytes and content type, for an operation that uploads it.

        Only public hosts (the SSRF guard, TL-08); refused past ``max_bytes``.
        """
        from src.common.net_guard import check_url
        await check_url(url)
        chunks: list[bytes] = []
        size = 0
        async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError(f"{url} is larger than {max_bytes // (1024 * 1024)} MB")
                    chunks.append(chunk)
                content_type = resp.headers.get("content-type", "application/octet-stream").split(";")[0]
        return b"".join(chunks), content_type

    @staticmethod
    def _bearer_headers(access_token: str, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Build standard Bearer token authorization headers."""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        if extra:
            headers.update(extra)
        return headers
