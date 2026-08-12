import json
import httpx
from typing import Any, Dict
from src.ai.tools.base import Tool, ToolParams, ToolResult as TypedToolResult


# ---------------------------------------------------------------------------
# Typed Tool Protocol — reference implementation
# ---------------------------------------------------------------------------

class ScraperParams(ToolParams):
    """Typed parameters for web scraper tool."""
    url: str
    purpose: str = ""

class ScraperTool(Tool):
    """Tool for scraping content from web pages using Firecrawl.
    
    Actions:
    1. scrape_url: Get text content from a URL via Firecrawl and save it as an artifact.
    """
    
    name = "scraper_tool"
    description = (
        "Extract text content from a web page URL using Firecrawl API. "
        "Input should be a JSON object with 'url'. "
        "Returns the scraped content and saves it as a document artifact."
    )

    async def run(self, input_data: str) -> str:
        return await self.run_with_context(input_data)

    async def run_with_context(self, input_data: str, context: dict = None) -> str:
        try:
            # Sanitize LLM-generated input: strip markdown fences, control chars
            cleaned = input_data.strip()
            if cleaned.startswith("```"):
                # Remove ```json ... ``` wrapper
                lines = cleaned.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                cleaned = "\n".join(lines).strip()

            # Try parsing as JSON first (strict=False to allow control chars)
            url = None
            urls_list = None
            try:
                params = json.loads(cleaned, strict=False)
                if isinstance(params, dict):
                    url = params.get("url")
                    urls_list = params.get("urls")  # Accept {"urls": [...]} format
                elif isinstance(params, list):
                    # LLM passed a JSON array of URLs (e.g. from a previous step)
                    urls_list = [u for u in params if isinstance(u, str) and u.startswith("http")]
                elif isinstance(params, str):
                    url = params  # LLM sometimes passes just a URL string
            except json.JSONDecodeError:
                # Fallback: treat the whole input as a raw URL or newline-separated URLs
                if cleaned.startswith("http://") or cleaned.startswith("https://"):
                    # Could be multiple URLs separated by newlines
                    found_urls = [l.strip() for l in cleaned.split("\n") if l.strip().startswith("http")]
                    if len(found_urls) > 1:
                        urls_list = found_urls
                    else:
                        url = found_urls[0] if found_urls else cleaned.split()[0]
                    params = {"url": url}
                else:
                    return json.dumps({"error": f"Could not parse scraper input as JSON or URL: {cleaned[:200]}"})

            # Handle multiple URLs: scrape each and return combined results
            if urls_list and len(urls_list) > 0:
                all_results = []
                for i, u in enumerate(urls_list[:10]):  # Cap at 10 URLs
                    single_input = json.dumps({"url": u.strip()})
                    result = await self.run_with_context(single_input, context)
                    try:
                        r = json.loads(result)
                        all_results.append({"url": u.strip(), **r})
                    except json.JSONDecodeError:
                        all_results.append({"url": u.strip(), "error": "Parse error"})
                return json.dumps({"results": all_results, "total_scraped": len(all_results)})
            
            if not url:
                return json.dumps({"error": "Missing 'url' in scraper input"})

            # Retrieve execution context info
            context = context or {}
            company_id = context.get("company_id")
            purpose = params.get("purpose", f"Scraped content from {url}")
            
            # Extract campaign/run IDs if provided
            campaign_id = context.get("campaign_id")
            agent_id = context.get("agent_id")
            run_id = context.get("run_id")

            # Need DB access for API key and to save artifact
            from src.common.database import AsyncSessionLocal
            from src.config.service import ConfigService
            from src.ai.artifact_service import ArtifactService, ORIGIN_SYSTEM
            
            async with AsyncSessionLocal() as db_session:
                config_svc = ConfigService(db_session)
                art_svc = ArtifactService(db_session)
                
                # Fetch API key
                # Per feedback: App Admin configures Firecrawl SKU system-wide.
                # config_svc auto-falls back to APP company if company-specific key is missing
                # get_api_key_by_provider already checks the app company ID as fallback
                key = None
                if company_id:
                    key = await config_svc.get_api_key_by_provider(company_id, "firecrawl")
                else:
                    app_company_id_val = await config_svc._get_app_company_id()
                    if app_company_id_val:
                        key = await config_svc.get_api_key_by_provider(app_company_id_val, "firecrawl")
                
                if not key:
                    return json.dumps({"error": "Firecrawl integration is not configured. Please add the 'firecrawl' provider key in the system settings."})
                
                # Call Firecrawl
                api_url = "https://api.firecrawl.dev/v1/scrape"
                headers = {
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "url": url,
                    "formats": ["markdown"]
                }
                
                # Increased timeout to handle large web pages
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(api_url, headers=headers, json=payload)
                    
                    if response.status_code != 200:
                        return json.dumps({"error": f"Firecrawl API error: {response.text}"})
                        
                    resp_data = response.json()
                    
                    if not resp_data.get("success"):
                        return json.dumps({"error": f"Scrape failed: {resp_data.get('error', 'Unknown error')}"})
                        
                    markdown_content = resp_data.get("data", {}).get("markdown", "")
                    
                    if not markdown_content:
                        return json.dumps({"error": "No markdown content extracted from URL"})
                    
                    # Create Artifact
                    # Generate a safe filename from the URL, max 50 chars
                    safe_url = url.split("://")[-1].replace("/", "_").replace("?", "_").replace("&", "_")
                    file_name = f"scraped_{safe_url[:50]}.md"
                    
                    # Store file path in DB, ArtifactService physically saves to @artifact base folder
                    # Uses company_id from context if available, otherwise app company id
                    target_company_id = company_id
                    if not target_company_id:
                        target_company_id = await config_svc._get_app_company_id()
                        
                    content_bytes = markdown_content.encode("utf-8")
                    
                    saved_artifact = await art_svc.save_artifact(
                        file_bytes=content_bytes,
                        file_name=file_name,
                        mime_type="text/markdown",
                        file_category="documents",
                        origin=ORIGIN_SYSTEM,
                        company_id=target_company_id,
                        purpose=purpose,
                        generated_by="scraper_tool",
                        campaign_id=campaign_id,
                        agent_id=agent_id,
                        run_id=run_id,
                        extra_metadata={"url": url, "char_count": len(markdown_content)}
                    )
                    
                    return json.dumps({
                        "status": "success",
                        "url": url,
                        "artifact_id": str(saved_artifact.id),
                        "file_path": saved_artifact.file_path,
                        "message": f"Successfully scraped {len(markdown_content)} characters and saved as document artifact.",
                        # Return content within LLM context budget (32K chars ≈ 8K tokens)
                        "content": markdown_content[:32000]
                    })
                    
        except Exception as e:
            return json.dumps({"error": f"Scraper Tool Error: {str(e)}"})

    # ---------------------------------------------------------------------------
    # Typed interface
    # ---------------------------------------------------------------------------

    async def run_typed(self, params: ScraperParams) -> TypedToolResult:
        """Typed tool execution — accepts ScraperParams, returns TypedToolResult."""
        try:
            result_str = await self.run_with_context(
                json.dumps({"url": params.url, "purpose": params.purpose})
            )
            return TypedToolResult(output=result_str)
        except Exception as e:
            return TypedToolResult(
                success=False, output="",
                error_code="SCRAPER_ERROR", error_message=str(e),
            )
    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL of the page to scrape"
                    },
                    "purpose": {
                        "type": "string",
                        "description": "Short description of why this url is being scraped. Defaults to 'Scraped content from {url}'."
                    }
                },
                "required": ["url"]
            }
        }
