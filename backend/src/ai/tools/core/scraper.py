import json
from typing import Any, Dict, List, Optional

import httpx
from pydantic import Field, model_validator

from src.ai.tools.base import NO_CONTEXT_ERROR, Tool, ToolOutput, ToolParams, context_company_id

_MAX_URLS = 10


class ScraperParams(ToolParams):
    """What ``scraper_tool`` takes: one URL, or several."""
    url: Optional[str] = Field(None, description="The URL of the page to scrape")
    urls: Optional[List[str]] = Field(None, max_length=_MAX_URLS,
                                      description=f"Several URLs to scrape (at most {_MAX_URLS}), instead of url")
    purpose: str = Field("", description="Short description of why the page is scraped "
                                         "(default 'Scraped content from <url>')")

    @model_validator(mode="after")
    def _one_or_several(self) -> "ScraperParams":
        # A plan step's text may hold several URLs, one per line.
        if self.url and not self.urls:
            found = [line.strip() for line in self.url.splitlines() if line.strip().startswith("http")]
            if len(found) > 1:
                self.url, self.urls = None, found[:_MAX_URLS]
            elif found:
                self.url = found[0].split()[0]
        if not self.url and not self.urls:
            raise ValueError("give url (or urls)")
        return self


class ScraperTool(Tool):
    """Scrape a web page's text with Firecrawl and keep it as a document artifact."""

    name = "scraper_tool"
    category = "browser"
    description = (
        "Extract text content from a web page URL using Firecrawl API. "
        "Returns the scraped content and saves it as a document artifact."
    )
    Params = ScraperParams
    string_field = "url"  # a plan step's text is the URL (or URLs, one per line)

    async def execute(self, params: ScraperParams, ctx: Dict[str, Any]) -> ToolOutput:
        if params.urls:
            results = []
            for u in params.urls:
                one = await self._scrape(u.strip(), params.purpose, ctx)
                results.append({"url": u.strip(), **one})
            return ToolOutput(output=json.dumps({"results": results, "total_scraped": len(results)}))
        assert params.url is not None
        one = await self._scrape(params.url, params.purpose, ctx)
        if "error" in one:
            return ToolOutput.failed(one["error"], code="scrape_failed")
        return ToolOutput(output=json.dumps(one))

    async def _scrape(self, url: str, purpose: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """One page: its markdown as an artifact of the run, or ``{"error": …}``."""
        try:
            from src.common.net_guard import BlockedURL, check_url
            try:
                await check_url(url)  # no internal hosts (TL-08)
            except BlockedURL as exc:
                return {"error": f"URL refused: {exc}"}

            # The company comes from the execution context only (TL-03, TL-05):
            # without one the scrape used to spend the platform's key and save
            # the page into the platform's artifact store.
            company_id = context_company_id(context)
            if not company_id:
                return {"error": NO_CONTEXT_ERROR}

            from src.ai.artifact_service import ORIGIN_SYSTEM, ArtifactService
            from src.common.database import AsyncSessionLocal
            from src.config.service import ConfigService

            async with AsyncSessionLocal() as db_session:
                # The Firecrawl key: the company's, else the platform's.
                key = await ConfigService(db_session).get_api_key_by_provider(company_id, "firecrawl")
                if not key:
                    return {"error": "Firecrawl integration is not configured. Please add the "
                                     "'firecrawl' provider key in the system settings."}

                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        "https://api.firecrawl.dev/v1/scrape",
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                        json={"url": url, "formats": ["markdown"]},
                    )
                if response.status_code != 200:
                    return {"error": f"Firecrawl API error: {response.text}"}
                resp_data = response.json()
                if not resp_data.get("success"):
                    return {"error": f"Scrape failed: {resp_data.get('error', 'Unknown error')}"}
                markdown_content = resp_data.get("data", {}).get("markdown", "")
                if not markdown_content:
                    return {"error": "No markdown content extracted from URL"}

                safe_url = url.split("://")[-1].replace("/", "_").replace("?", "_").replace("&", "_")
                saved = await ArtifactService(db_session).save_artifact(
                    file_bytes=markdown_content.encode("utf-8"),
                    file_name=f"scraped_{safe_url[:50]}.md",
                    mime_type="text/markdown",
                    file_category="documents",
                    origin=ORIGIN_SYSTEM,
                    company_id=company_id,
                    purpose=purpose or f"Scraped content from {url}",
                    generated_by="scraper_tool",
                    campaign_id=context.get("campaign_id"),
                    agent_id=context.get("agent_id"),
                    run_id=context.get("run_id"),
                    extra_metadata={"url": url, "char_count": len(markdown_content)},
                )
                return {
                    "status": "success",
                    "url": url,
                    "artifact_id": str(saved.id),
                    "file_path": saved.file_path,
                    "message": f"Successfully scraped {len(markdown_content)} characters and saved as document artifact.",
                    # Within the model's context budget (32K chars ≈ 8K tokens).
                    "content": markdown_content[:32000],
                }
        except Exception as e:
            return {"error": f"Scraper Tool Error: {str(e)}"}
