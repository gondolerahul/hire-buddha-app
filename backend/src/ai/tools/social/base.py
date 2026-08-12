"""
SocialMediaTool — Abstract base class for all social media AI tools.

Provides shared functionality:
- Credential resolution from social_connections table
- HTTP request helper with retry + error handling
- Standard JSON function schema pattern
"""
import json
import logging
from abc import abstractmethod
from typing import Any, Dict, Optional

import httpx

from src.ai.tools.base import Tool, ToolStatus

logger = logging.getLogger(__name__)

# Default timeout for all social API calls
DEFAULT_TIMEOUT = 30  # seconds
MAX_RETRIES = 2


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
    # (``tools.experimental.{tool_id}=true``) via
    # ``ToolRegistry.get_visible_tools_for_company`` before an agent can use
    # them. Promote an individual platform to ``ToolStatus.ACTIVE`` on its
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
        company_id = context.get("company_id") if context else params.get("company_id")
        if not company_id:
            return json.dumps({
                "error": "No company_id in context. Cannot resolve social media credentials."
            })

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

        try:
            result = await self._execute(params, credentials, context)
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
    ) -> httpx.Response:
        """
        Make an HTTP request with retry logic.

        Raises httpx.HTTPStatusError on 4xx/5xx responses.
        """
        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(MAX_RETRIES + 1):
                try:
                    resp = await client.request(
                        method=method,
                        url=url,
                        headers=headers,
                        json=json_body,
                        params=params,
                        data=data,
                    )
                    resp.raise_for_status()
                    return resp
                except httpx.HTTPStatusError:
                    raise  # Don't retry client errors
                except (httpx.TimeoutException, httpx.ConnectError) as e:
                    if attempt == MAX_RETRIES:
                        raise
                    logger.warning(f"[SocialMediaTool] Retry {attempt + 1}/{MAX_RETRIES}: {e}")

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
