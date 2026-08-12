"""
Web Search Tool for HireBuddha AI Platform.

Provides real web search functionality using multiple backends:
1. SerpAPI — preferred (SERP_API_KEY via Integration Registry)
2. duckduckgo-search library — free robust fallback (no API key needed)
3. DuckDuckGo Instant Answers API — final minimal fallback

Configure via Integration Registry or env vars.
"""

import httpx
import json
import os
import re
import logging
from typing import Dict, Any, List, Optional
from src.ai.tools.base import Tool, ToolParams, ToolResult as TypedToolResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed Tool Protocol — reference implementation
# ---------------------------------------------------------------------------

class WebSearchParams(ToolParams):
    """Typed parameters for web search tool."""
    query: str
    num_results: int = 8


class WebSearchTool(Tool):
    """Web search tool with multiple backend support.

    Priority order:
        1. SerpAPI / Google Search (SERP_API_KEY via Integration Registry)
        2. duckduckgo-search Python library (free, no key)
        3. DuckDuckGo Instant Answers API (very limited, no key)
    """

    name = "web_search"
    description = (
        "Search the web for current information on any topic. "
        "Returns a list of relevant results including titles, URLs, and snippets. "
        "Input should be a plain-text search query or a JSON object with a 'query' key."
    )

    _TIMEOUT = 15.0
    _DDG_API_URL = "https://api.duckduckgo.com/"
    _SERP_API_URL = "https://serpapi.com/search"

    # ---------------------------------------------------------------------------
    # Input parsing
    # ---------------------------------------------------------------------------

    def _parse_query(self, input_data: str) -> str:
        """Extract search query from raw input string or JSON dict/list."""
        raw = (input_data or "").strip()
        if not raw:
            return ""

        # Try JSON parsing first
        if raw.startswith("{") or raw.startswith("["):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    # Source-discoverer passes a JSON array of query objects.
                    # Extract the first valid query string — the caller (REACT loop)
                    # is responsible for iterating through the array; this method
                    # only returns one query per call.
                    for item in parsed:
                        if isinstance(item, str) and item.strip():
                            return item.strip()[:500]
                        if isinstance(item, dict):
                            for key in ("query", "q", "search", "text"):
                                if key in item and isinstance(item[key], str):
                                    return item[key].strip()[:500]
                elif isinstance(parsed, dict):
                    for key in ("query", "q", "search", "input", "text"):
                        if key in parsed and isinstance(parsed[key], str):
                            return parsed[key].strip()[:500]
                    # Fallback: first string value
                    for v in parsed.values():
                        if isinstance(v, str) and v.strip():
                            return v.strip()[:500]
            except json.JSONDecodeError:
                pass  # Not JSON

        # Hard cap: queries >500 chars are always malformed (e.g. LLM passed full
        # research context instead of a search query). Truncate and warn.
        if len(raw) > 500:
            logger.warning(
                f"[WebSearch] Query too long ({len(raw)} chars) — likely a prompt injection. "
                f"Truncating to 500 chars. First 100: {raw[:100]!r}"
            )
            raw = raw[:500]

        return raw

    # ---------------------------------------------------------------------------
    # API key resolution
    # ---------------------------------------------------------------------------

    async def _resolve_keys(self, context: Optional[Dict] = None) -> Dict[str, Optional[str]]:
        """Look up available search API keys from the Integration Registry."""
        keys = {
            "serp_api_key": None,
        }

        # Integration registry lookup
        if context and context.get("company_id"):
            try:
                from uuid import UUID as _UUID
                from src.common.database import AsyncSessionLocal
                from src.config.service import ConfigService

                async with AsyncSessionLocal() as db:
                    config_service = ConfigService(db)
                    company_uuid = _UUID(str(context["company_id"]))
                    logger.info(f"[WebSearch] Resolving API keys for company {company_uuid}")

                    # SerpAPI Resolution
                    if not keys["serp_api_key"]:
                        keys["serp_api_key"] = await config_service.get_api_key_by_sku(company_uuid, "serp-api-key") or \
                                             await config_service.get_api_key_by_provider(company_uuid, "serpapi")

                    # Log resolution outcome
                    resolved = [k for k, v in keys.items() if v]
                    if resolved:
                        logger.info(f"[WebSearch] Resolved keys: {resolved}")
                    else:
                        logger.warning(f"[WebSearch] No search API keys found for company {company_uuid}. "
                                       f"Configure integration with provider_name='serpapi' or service_sku='serp-api-key'.")

            except Exception as e:
                logger.warning(f"[WebSearch] Registry lookup failed: {e}")
        else:
            logger.warning(f"[WebSearch] No company_id in context — cannot resolve API keys from registry")

        return keys



    # ---------------------------------------------------------------------------
    # Backend 1: SerpAPI
    # ---------------------------------------------------------------------------

    async def _search_serpapi(self, query: str, api_key: str) -> Optional[List[Dict]]:
        """Search using SerpAPI (Google results) with retry for rate limits."""
        import asyncio
        max_retries = 3
        base_delay = 2.0  # seconds

        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._TIMEOUT) as client:
                    response = await client.get(
                        self._SERP_API_URL,
                        params={
                            "q": query,
                            "api_key": api_key,
                            "engine": "google",
                            "num": 10,
                            "hl": "en",
                        }
                    )
                    # Retry on 429 Too Many Requests
                    if response.status_code == 429:
                        if attempt < max_retries:
                            delay = base_delay * (2 ** attempt)
                            logger.info(f"[WebSearch] SerpAPI 429 rate-limited, retry {attempt+1}/{max_retries} in {delay}s")
                            await asyncio.sleep(delay)
                            continue
                        else:
                            logger.warning(f"[WebSearch] SerpAPI 429 after {max_retries} retries for: {query[:60]}")
                            return None

                    response.raise_for_status()
                    data = response.json()

                results = []

                # Answer box
                answer_box = data.get("answer_box", {})
                if answer_box.get("answer") or answer_box.get("snippet"):
                    results.append({
                        "title": "Direct Answer",
                        "url": answer_box.get("link", ""),
                        "snippet": answer_box.get("answer") or answer_box.get("snippet", ""),
                    })

                for item in data.get("organic_results", [])[:8]:
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("link", ""),
                        "snippet": item.get("snippet", ""),
                    })

                logger.info(f"[WebSearch] SerpAPI returned {len(results)} results for: {query[:60]}")
                return results if results else None

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429 and attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    logger.info(f"[WebSearch] SerpAPI 429 rate-limited, retry {attempt+1}/{max_retries} in {delay}s")
                    await asyncio.sleep(delay)
                    continue
                logger.warning(f"[WebSearch] SerpAPI failed: {e}")
                return None
            except Exception as e:
                logger.warning(f"[WebSearch] SerpAPI failed: {e}")
                return None

        return None

    # ---------------------------------------------------------------------------
    # Backend 2: duckduckgo-search library (handles bot detection)
    # ---------------------------------------------------------------------------

    async def _search_ddg_library(self, query: str) -> Optional[List[Dict]]:
        """Search using the ddgs Python library (handles bot detection)."""
        try:
            # Try new ddgs package first, fall back to duckduckgo_search
            import warnings
            try:
                from ddgs import DDGS
            except ImportError:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", DeprecationWarning)
                    warnings.simplefilter("ignore", RuntimeWarning)
                    from duckduckgo_search import DDGS
            import asyncio

            def _sync_search():
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=8))

            # Run in threadpool since ddgs is sync
            loop = asyncio.get_running_loop()
            items = await loop.run_in_executor(None, _sync_search)

            results = []
            for item in items:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("href", item.get("url", "")),
                    "snippet": item.get("body", item.get("description", "")),
                })

            logger.info(f"[WebSearch] DDG library returned {len(results)} results for: {query[:60]}")
            return results if results else None

        except ImportError:
            logger.debug("[WebSearch] ddgs / duckduckgo-search not installed")
            return None
        except Exception as e:
            logger.warning(f"[WebSearch] DDG library failed: {e}")
            return None

    # ---------------------------------------------------------------------------
    # Backend 3: DuckDuckGo Instant Answers API (minimal fallback)
    # ---------------------------------------------------------------------------

    async def _search_ddg_api(self, query: str) -> List[Dict]:
        """Search using the DuckDuckGo Instant Answers API."""
        try:
            async with httpx.AsyncClient(timeout=self._TIMEOUT) as client:
                response = await client.get(
                    self._DDG_API_URL,
                    params={
                        "q": query,
                        "format": "json",
                        "no_html": "1",
                        "skip_disambig": "1",
                    },
                )
                response.raise_for_status()
                data = response.json()

            results = []
            if data.get("Abstract"):
                results.append({
                    "title": data.get("Heading", "Summary"),
                    "url": data.get("AbstractURL", ""),
                    "snippet": data["Abstract"],
                })
            if data.get("Answer"):
                results.append({
                    "title": "Instant Answer",
                    "url": "",
                    "snippet": data["Answer"],
                })
            for topic in data.get("RelatedTopics", [])[:5]:
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append({
                        "title": topic.get("Name", "Related"),
                        "url": topic.get("FirstURL", ""),
                        "snippet": topic["Text"][:400],
                    })

            logger.info(f"[WebSearch] DDG API returned {len(results)} results for: {query[:60]}")
            return results

        except Exception as e:
            logger.warning(f"[WebSearch] DDG API failed: {e}")
            return []

    # ---------------------------------------------------------------------------
    # Main entry points
    # ---------------------------------------------------------------------------

    async def run(self, input_data: str) -> str:
        """Execute a web search without extra context."""
        return await self.run_with_context(input_data, context=None)

    async def run_with_context(self, input_data: str, context: Optional[Dict] = None) -> str:
        """Execute a web search with optional execution context.

        Args:
            input_data: Search query string or JSON with 'query' key.
            context: Optional execution context (for API key lookup).

        Returns:
            Formatted string of search results.
        """
        query = self._parse_query(input_data)
        if not query:
            return "Error: Empty search query. Please provide a search term."

        logger.info(f"[WebSearch] Searching for: {query[:100]}")

        # Resolve available API keys
        keys = await self._resolve_keys(context)

        results: Optional[List[Dict]] = None

        # Backend 1: SerpAPI
        if keys.get("serp_api_key"):
            results = await self._search_serpapi(query, keys["serp_api_key"])

        # Backend 2: duckduckgo-search library
        if not results:
            results = await self._search_ddg_library(query)

        # Backend 3: DDG Instant Answers API
        if not results:
            results = await self._search_ddg_api(query)

        if not results:
            return (
                f"No results found for: '{query}'. "
                "For better results, configure SERP_API_KEY via Integration Registry."
            )

        return self._format_results(query, results)

    # ---------------------------------------------------------------------------
    # Typed interface
    # ---------------------------------------------------------------------------

    async def run_typed(self, params: WebSearchParams, context: Optional[Dict] = None) -> TypedToolResult:
        """Typed tool execution — accepts WebSearchParams, returns TypedToolResult."""
        try:
            result_str = await self.run_with_context(
                json.dumps({"query": params.query}), context=context
            )
            return TypedToolResult(output=result_str)
        except Exception as e:
            return TypedToolResult(
                success=False, output="",
                error_code="SEARCH_ERROR", error_message=str(e),
            )

    # ---------------------------------------------------------------------------
    # Output formatting
    # ---------------------------------------------------------------------------

    def _format_results(self, query: str, results: List[Dict]) -> str:
        """Format a list of result dicts into a readable string."""
        lines = [f"Search results for: {query}\n"]
        for i, r in enumerate(results, 1):
            title = (r.get("title") or "").strip()
            url = (r.get("url") or "").strip()
            snippet = (r.get("snippet") or "").strip()
            if len(snippet) > 400:
                snippet = snippet[:400] + "..."
            lines.append(f"{i}. {title}")
            if url:
                lines.append(f"   URL: {url}")
            if snippet:
                lines.append(f"   {snippet}")
            lines.append("")
        return "\n".join(lines)

    def get_function_schema(self) -> Dict[str, Any]:
        """Return JSON schema for Gemini function calling."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to look up on the web"
                    }
                },
                "required": ["query"]
            }
        }
