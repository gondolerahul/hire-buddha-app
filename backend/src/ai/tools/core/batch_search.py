"""
Batch Web Search Tool for Deep Research Pipeline.

Executes a list of search queries sequentially and returns aggregated,
deduplicated results. Designed for the source-discovery phase of deep research
where 10-25 queries need to be run together.

Unlike web_search (single query), batch_web_search accepts:
  - A JSON array of query strings: ["query1", "query2", ...]
  - A JSON array of query objects: [{"query": "...", "priority": 1}, ...]
  - A plain multi-line string (one query per line)

Returns: Aggregated, deduplicated results from all queries.
"""

import asyncio
import json
import logging
from typing import Dict, Any, List, Optional

from pydantic import Field, field_validator

from src.ai.tools.base import Tool, ToolOutput, ToolParams

logger = logging.getLogger(__name__)


class BatchWebSearchParams(ToolParams):
    """What ``batch_web_search`` takes."""
    queries: List[str] = Field(..., description="Search queries to run (at most 25)")
    max_per_query: int = Field(5, ge=1, le=20, description="Results kept per query (default 5)")

    @field_validator("queries", mode="before")
    @classmethod
    def _queries_from_text(cls, v: Any) -> Any:
        # A plan step hands over the previous step's text — often JSON in
        # markdown fences; the parser finds the list in it.
        if isinstance(v, str):
            v = BatchWebSearchTool()._parse_input(v)
        if isinstance(v, list):
            v = [str(q).strip()[:BatchWebSearchTool._MAX_QUERY_LEN] for q in v if str(q).strip()]
            v = v[:BatchWebSearchTool._MAX_QUERIES]
            if not v:
                raise ValueError("no search queries: give a JSON array of 1-25 search strings")
        return v


class BatchWebSearchTool(Tool):
    """Batch web search tool — executes multiple queries and aggregates results.

    Designed for research workflows that generate a list of search queries
    (e.g. from a query decomposer) and need to execute all of them efficiently.

    Priority order (same as WebSearchTool):
        1. SerpAPI / Google Search (SERP_API_KEY via Integration Registry)
        2. duckduckgo-search Python library (free, no key)
        3. DuckDuckGo Instant Answers API (very limited)
    """

    name = "batch_web_search"
    description = (
        "Execute multiple web search queries and return aggregated results, without a URL "
        "an earlier query already returned. Give 'queries' (an array of search strings) and "
        "optionally 'max_per_query'."
    )
    Params = BatchWebSearchParams
    string_field = "queries"  # a plan step's text: the parser finds the list in it

    _MAX_QUERIES = 25  # Hard cap to prevent runaway API costs
    _MAX_QUERY_LEN = 500
    _BATCH_SIZE = 3    # Max concurrent queries per batch (SerpAPI rate limit)
    _INTER_QUERY_DELAY = 1.5  # Seconds between queries within a batch
    _INTER_BATCH_DELAY = 3.0  # Seconds between batches

    def _strip_markdown(self, text: str) -> str:
        """Strip markdown formatting from LLM output to extract raw JSON.

        LLM entities (e.g. query-decomposer) commonly wrap their JSON output in:
        - Markdown headers: ``## Step Title``
        - Code fences: `` ```json ... ``` ``
        This method strips those wrappers so JSON parsing can succeed.
        """
        import re
        s = text.strip()

        # Strip leading markdown headers (## Title, ### Title, etc.)
        s = re.sub(r'^#{1,4}\s+[^\n]*\n', '', s, flags=re.MULTILINE).strip()

        # Extract content from ```json ... ``` or ``` ... ``` fences
        fence_match = re.search(r'```(?:json)?\s*\n(.*?)```', s, re.DOTALL)
        if fence_match:
            s = fence_match.group(1).strip()

        return s

    def _extract_json_from_text(self, text: str) -> str | None:
        """Find the first JSON array or object embedded in arbitrary text."""
        import re
        # Look for a JSON array [...] or object {...} anywhere in the text
        for pattern in [r'(\[[\s\S]*\])', r'(\{[\s\S]*\})']:
            match = re.search(pattern, text)
            if match:
                candidate = match.group(1)
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    continue
        return None

    def _parse_json_queries(self, raw: str) -> List[str]:
        """Parse a JSON string into a list of query strings."""
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []

        if isinstance(parsed, list):
            queries = []
            for item in parsed:
                if isinstance(item, str) and item.strip():
                    queries.append(item.strip()[:self._MAX_QUERY_LEN])
                elif isinstance(item, dict):
                    for key in ("query", "q", "search", "text"):
                        if key in item and isinstance(item[key], str):
                            queries.append(item[key].strip()[:self._MAX_QUERY_LEN])
                            break
            return queries[:self._MAX_QUERIES]

        if isinstance(parsed, dict):
            qs = parsed.get("queries", parsed.get("query", []))
            if isinstance(qs, str):
                return [qs.strip()[:self._MAX_QUERY_LEN]]
            if isinstance(qs, list):
                result = []
                for q in qs:
                    if isinstance(q, str):
                        result.append(q.strip()[:self._MAX_QUERY_LEN])
                    elif isinstance(q, dict):
                        for key in ("query", "q", "search", "text"):
                            if key in q and isinstance(q[key], str):
                                result.append(q[key].strip()[:self._MAX_QUERY_LEN])
                                break
                return result[:self._MAX_QUERIES]

        return []

    def _parse_input(self, input_data: str) -> List[str]:
        """Extract list of queries from various input formats.

        Handles:
        - Raw JSON arrays: ["query1", "query2"]
        - JSON objects: {"queries": ["q1", "q2"]}
        - Markdown-wrapped JSON (from LLM entities like query-decomposer):
              ## Step Title
              ```json
              ["query1", "query2"]
              ```
        - Short bare query strings
        """
        raw = (input_data or "").strip()
        if not raw:
            return []

        # ── Step 1: Try direct JSON parsing ──────────────────────────────
        if raw.startswith("{") or raw.startswith("["):
            queries = self._parse_json_queries(raw)
            if queries:
                return queries

        # ── Step 2: Strip markdown formatting and retry ──────────────────
        # LLMs (especially query-decomposer) wrap JSON in ```json fences
        # with markdown headers. Strip those and try JSON parsing again.
        cleaned = self._strip_markdown(raw)
        if cleaned and cleaned != raw:
            if cleaned.startswith("{") or cleaned.startswith("["):
                queries = self._parse_json_queries(cleaned)
                if queries:
                    logger.info(f"[BatchWebSearch] Parsed {len(queries)} queries after stripping markdown")
                    return queries

        # ── Step 3: Extract embedded JSON from arbitrary text ────────────
        # Last-resort: find a JSON array/object anywhere in the raw text.
        extracted = self._extract_json_from_text(raw)
        if extracted:
            queries = self._parse_json_queries(extracted)
            if queries:
                logger.info(f"[BatchWebSearch] Extracted {len(queries)} queries from embedded JSON")
                return queries

        # ── Step 4: Narrative text guard ─────────────────────────────────
        # Only reject as narrative AFTER all JSON extraction attempts failed.
        _NARRATIVE_SIGNALS = [
            "**Authority", "**Recency", "**Depth", "**Uniqueness",
            "Based on your request", "I have conducted", "I have evaluated",
            "The following is", "curated list", "comprehensive search",
            "market research", "### **", "I will now", "Here are the",
            "source list", "search results", "source discovery",
        ]
        if len(raw) > 300 or any(sig in raw for sig in _NARRATIVE_SIGNALS):
            logger.error(
                f"[BatchWebSearch] REJECTED: No JSON queries found in input. "
                f"Expected a JSON array like: "
                f'["query 1", "query 2", ...]. '
                f"Got ({len(raw)} chars): {raw[:120]!r}"
            )
            return []

        # ── Step 5: Short single-line fallback ───────────────────────────
        if "\n" not in raw and len(raw) <= self._MAX_QUERY_LEN:
            return [raw]

        logger.error(
            f"[BatchWebSearch] REJECTED: Could not parse input as query list. "
            f"Got ({len(raw)} chars): {raw[:120]!r}"
        )
        return []

    async def execute(self, params: BatchWebSearchParams, ctx: Dict[str, Any]) -> ToolOutput:
        """Run each query, keep ``max_per_query`` results each, drop URLs an
        earlier query already returned, and report the paid sub-queries (TL-60)."""
        from src.ai.tools.core.search import WebSearchTool
        search_tool = WebSearchTool()
        queries = params.queries
        logger.info(f"[BatchWebSearch] Executing {len(queries)} queries")

        seen_urls: set[str] = set()
        sections: List[str] = []
        failed: List[str] = []
        paid = duplicates = 0
        for i, query in enumerate(queries):
            try:
                results, backend = await search_tool.search(query, ctx)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[BatchWebSearch] Query failed: {query[:60]} - {e}")
                results, backend = [], "none"
            if backend == "serpapi":
                paid += 1
            fresh = []
            for r in results:
                url = (r.get("url") or "").strip()
                if url and url in seen_urls:
                    duplicates += 1
                    continue
                if url:
                    seen_urls.add(url)
                fresh.append(r)
                if len(fresh) >= params.max_per_query:
                    break
            if fresh:
                sections.append(f"### Query: {query}\n{search_tool._format_results(query, fresh)}")
            else:
                failed.append(query)

            # Rate-limit pauses, so SerpAPI does not answer 429.
            if i < len(queries) - 1:
                await asyncio.sleep(self._INTER_BATCH_DELAY if (i + 1) % self._BATCH_SIZE == 0
                                    else self._INTER_QUERY_DELAY)

        metadata = {"billable_units": paid, "queries": len(queries), "duplicates_dropped": duplicates}
        if not sections:
            return ToolOutput(output=(
                f"No results found for any of the {len(queries)} queries. "
                f"Failed queries: {failed[:5]}. Check SerpAPI key configuration in Integration Registry."
            ), metadata=metadata)
        lines = [
            "## Batch Search Results",
            f"**Executed:** {len(queries)} queries | **With results:** {len(sections)} | "
            f"**Without:** {len(failed)} | **Duplicate URLs dropped:** {duplicates}",
            "",
            *sections,
        ]
        if failed:
            lines.append(f"### Queries without new results ({len(failed)})")
            lines.extend(f"- {q}" for q in failed)
        return ToolOutput(output="\n".join(lines), metadata=metadata)
