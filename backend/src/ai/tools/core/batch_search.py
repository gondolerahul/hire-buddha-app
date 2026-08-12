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

from src.ai.tools.base import Tool, ToolParams, ToolResult as TypedToolResult

logger = logging.getLogger(__name__)


class BatchWebSearchParams(ToolParams):
    """Typed parameters for batch web search tool."""
    queries: List[str]
    max_per_query: int = 5
    deduplicate: bool = True


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
        "Execute multiple web search queries and return aggregated, deduplicated results. "
        "Input should be a JSON object with a 'queries' key containing an array of search strings. "
        "Example: {\"queries\": [\"AI agent startups 2024\", \"autonomous AI market size\"], \"max_per_query\": 5}. "
        "Also accepts a plain JSON array of query strings directly."
    )

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

    async def run(self, input_data: str) -> str:
        return await self.run_with_context(input_data, context=None)

    async def run_with_context(self, input_data: str, context: Optional[Dict] = None) -> str:
        """Execute all queries and return aggregated results."""
        queries = self._parse_input(input_data)
        if not queries:
            return (
                "ERROR: batch_web_search requires a JSON array of search query strings. "
                "The input you provided could not be parsed as a query list. "
                "Required format: [\"search query 1\", \"search query 2\", ...] "
                "or {\"queries\": [\"query 1\", \"query 2\"]}. "
                "Do NOT pass narrative text, source lists, or synthesized content as input. "
                "INSTRUCTION: Generate a JSON array of 5-15 targeted search queries based on "
                "the research topic from your context, then call this tool again with that JSON array."
            )

        logger.info(f"[BatchWebSearch] Executing {len(queries)} queries")

        # Import the underlying WebSearchTool to reuse its backends
        from src.ai.tools.core.search import WebSearchTool
        search_tool = WebSearchTool()

        all_results = []
        seen_urls = set()
        failed_queries = []
        successful_queries = 0

        for i, query in enumerate(queries):
            try:
                logger.info(f"[BatchWebSearch] Query {i+1}/{len(queries)}: {query[:80]}")
                result_str = await search_tool.run_with_context(
                    json.dumps({"query": query}),
                    context=context,
                )
                # Parse results back from formatted string
                if "No results found" not in result_str and "Error:" not in result_str:
                    all_results.append({
                        "query": query,
                        "results": result_str,
                    })
                    successful_queries += 1
                else:
                    failed_queries.append(query)
                    logger.warning(f"[BatchWebSearch] No results for: {query[:60]}")
            except Exception as e:
                failed_queries.append(query)
                logger.warning(f"[BatchWebSearch] Query failed: {query[:60]} — {e}")

            # Rate-limit delay to avoid 429 from SerpAPI
            if i < len(queries) - 1:
                # Longer delay between batches (every _BATCH_SIZE queries)
                if (i + 1) % self._BATCH_SIZE == 0:
                    logger.info(f"[BatchWebSearch] Rate-limit pause ({self._INTER_BATCH_DELAY}s between batches)")
                    await asyncio.sleep(self._INTER_BATCH_DELAY)
                else:
                    await asyncio.sleep(self._INTER_QUERY_DELAY)

        if not all_results:
            return (
                f"No results found for any of the {len(queries)} queries. "
                f"Failed queries: {failed_queries[:5]}. "
                "Check SerpAPI key configuration in Integration Registry."
            )

        # Format aggregated output
        output_lines = [
            f"## Batch Search Results",
            f"**Executed:** {len(queries)} queries | **Successful:** {successful_queries} | **Failed:** {len(failed_queries)}",
            "",
        ]
        for item in all_results:
            output_lines.append(f"### Query: {item['query']}")
            output_lines.append(item["results"])
            output_lines.append("")

        if failed_queries:
            output_lines.append(f"### Failed Queries ({len(failed_queries)})")
            for fq in failed_queries:
                output_lines.append(f"- {fq}")

        logger.info(f"[BatchWebSearch] Complete: {successful_queries}/{len(queries)} queries returned results")
        return "\n".join(output_lines)

    def get_function_schema(self) -> Dict[str, Any]:
        """Return JSON schema for function calling."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "queries": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of search query strings to execute (max 25)"
                    },
                    "max_per_query": {
                        "type": "integer",
                        "description": "Maximum results to return per query (default: 5)",
                        "default": 5,
                    }
                },
                "required": ["queries"]
            }
        }
