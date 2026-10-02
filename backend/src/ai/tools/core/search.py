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
from pydantic import Field, field_validator

from src.ai.tools.base import Tool, ToolOutput, ToolParams

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------

class WebSearchParams(ToolParams):
    """What ``web_search`` takes."""
    query: str = Field(..., description="The search query to look up on the web")
    num_results: int = Field(8, ge=1, le=20, description="How many results to return (1-20, default 8)")

    @field_validator("query")
    @classmethod
    def _a_query_not_a_prompt(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("an empty search query")
        # Over 500 characters is a prompt pasted as a query, not a query.
        if len(v) > 500:
            logger.warning("[WebSearch] query of %d chars truncated to 500: %r", len(v), v[:100])
            v = v[:500]
        return v


class WebSearchTool(Tool):
    """Web search tool with multiple backend support.

    Priority order:
        1. SerpAPI / Google Search (SERP_API_KEY via Integration Registry)
        2. duckduckgo-search Python library (free, no key)
        3. DuckDuckGo Instant Answers API (very limited, no key)
    """

    name = "web_search"
    category = "search"
    description = (
        "Search the web for current information on any topic. "
        "Returns a list of relevant results including titles, URLs, and snippets."
    )
    Params = WebSearchParams
    string_field = "query"  # a plan step's text is the query

    _TIMEOUT = 15.0
    _DDG_API_URL = "https://api.duckduckgo.com/"
    _SERP_API_URL = "https://serpapi.com/search"

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
    # The call
    # ---------------------------------------------------------------------------

    async def execute(self, params: WebSearchParams, ctx: Dict[str, Any]) -> ToolOutput:
        results, backend = await self.search(params.query, ctx)
        units = 1 if backend == "serpapi" else 0
        if not results:
            return ToolOutput(output=(
                f"No results found for: '{params.query}'. "
                "For better results, configure SERP_API_KEY via Integration Registry."
            ), metadata={"backend": backend, "billable_units": units})
        return ToolOutput(output=self._format_results(params.query, results[: params.num_results]),
                          metadata={"backend": backend, "billable_units": units})

    async def search(self, query: str, ctx: Dict[str, Any]) -> tuple[List[Dict], str]:
        """Results for ``query`` and the backend that answered: SerpAPI (billed),
        then the duckduckgo library, then DDG Instant Answers (both free)."""
        logger.info(f"[WebSearch] Searching for: {query[:100]}")
        keys = await self._resolve_keys(ctx)
        # A SerpAPI request is charged whether or not it found anything.
        backend = "none"
        if keys.get("serp_api_key"):
            backend = "serpapi"
            results = await self._search_serpapi(query, keys["serp_api_key"])
            if results:
                return results, backend
        results = await self._search_ddg_library(query)
        if results:
            return results, "serpapi" if backend == "serpapi" else "ddg"
        results = await self._search_ddg_api(query)
        return results or [], "serpapi" if backend == "serpapi" else ("ddg" if results else "none")

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
