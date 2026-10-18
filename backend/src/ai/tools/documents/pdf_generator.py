"""
PDF Generator Tool for HireBuddha AI Platform.

Generates professional PDF documents from markdown or HTML content using WeasyPrint.
Supports tables, lists, code blocks, and proper formatting with citations.
"""

import json
import os
import re as _re_module
import tempfile
import logging
from typing import Dict, Any
from datetime import datetime
from pathlib import Path
from src.ai.tools.base import NO_CONTEXT_ERROR, Tool, context_company_id


def _sanitize_filename(raw: str, max_length: int = 80) -> str:
    """Sanitize an LLM-generated filename into a filesystem-safe string.

    Handles common issues like colons, slashes, quotes, and Unicode.
    Returns a non-empty basename suitable for use in Path() / f"{name}.pdf".
    """
    # Strip leading/trailing whitespace
    name = raw.strip()
    # Remove .pdf extension if present (caller adds it back)
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    # Replace path separators and other dangerous chars with underscore
    name = _re_module.sub(r'[:/\\<>|"?*\x00-\x1f]', '_', name)
    # Replace spaces and multiple underscores with a single underscore
    name = _re_module.sub(r'[\s_]+', '_', name)
    # Strip leading/trailing underscores and dots
    name = name.strip('_.')
    # Truncate to max_length
    if len(name) > max_length:
        name = name[:max_length].rstrip('_')
    # Final fallback if empty
    return name or "document"

# WeasyPrint is declared (TL-66) but also needs Pango/GObject from the OS; a
# host without them raises OSError at import. Either way the tool says what is
# missing at call time instead of breaking the import of every tool.
_WEASYPRINT_ERROR = ""
try:
    from weasyprint import HTML, CSS, default_url_fetcher
    from weasyprint.text.fonts import FontConfiguration
except (ImportError, OSError) as _exc:
    _WEASYPRINT_ERROR = str(_exc).strip().splitlines()[0] if str(_exc).strip() else type(_exc).__name__
    HTML = None
    CSS = None
    FontConfiguration = None
    default_url_fetcher = None

try:
    import markdown
except ImportError:
    markdown = None


logger = logging.getLogger(__name__)


def _guarded_fetcher(company_id: str):
    """WeasyPrint's URL fetcher for one company (TL-55).

    The rendered HTML comes from the model, and markdown passes raw HTML
    through, so ``<img src="file:///etc/passwd">`` or a ``<link>`` to
    ``http://169.254.169.254/`` would be fetched at render time. Allowed:
    ``file:`` inside the company's own files, ``http(s)`` to public hosts, and
    ``data:``. Everything else is refused.
    """
    from urllib.parse import unquote, urlsplit
    from urllib.request import url2pathname

    from src.common.net_guard import check_url_sync
    from src.ai.tools.sandbox.workspace import confine_path

    def fetch(url: str, *args: Any, **kwargs: Any) -> Any:
        scheme = urlsplit(url).scheme.lower()
        if scheme == "file":
            confine_path(company_id, url2pathname(unquote(urlsplit(url).path)))
        elif scheme in ("http", "https"):
            check_url_sync(url)
        elif scheme != "data":
            raise ValueError(f"pdf_generator does not fetch {scheme or 'unknown'!r} URLs")
        return default_url_fetcher(url, *args, **kwargs)

    return fetch


class PDFGeneratorTool(Tool):
    """Tool for generating professional PDF documents from markdown content.
    
    Features:
        - Converts markdown to PDF with proper formatting
        - Supports headers, lists, tables, code blocks
        - Includes table of contents
        - Professional styling with page numbers
        - Citation and reference formatting
    """
    timeout_seconds = 180  # per call (EP-08)
    
    name = "pdf_generator"
    description = (
        "Generate a professional PDF document from markdown content. "
        "Input should be a JSON object with 'content' (markdown text), "
        "'title', and 'filename'. Optional: 'author', 'subject', 'image_paths' (array of image filenames to append)."
    )
    
    # Base directory for artifacts — everything under system-generated

    def get_function_schema(self) -> Dict[str, Any]:
        """Return JSON schema for function calling with image parameter."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Markdown formatted text content for the PDF"
                    },
                    "title": {
                        "type": "string",
                        "description": "Document title"
                    },
                    "filename": {
                        "type": "string",
                        "description": "Output filename (without .pdf extension)"
                    },
                    "author": {
                        "type": "string",
                        "description": "Document author name"
                    },
                    "subject": {
                        "type": "string",
                        "description": "Document subject or category"
                    },
                    "image_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Array of image filenames or paths to automatically include at the end of the PDF (e.g., ['panel_1.png', 'panel_2.png'])"
                    }
                },
                "required": ["content", "title", "filename"]
            }
        }
    
    def __init__(self):
        """Initialize PDF generator."""
        # We'll create directories dynamically in run()
        pass
    
    async def run(self, input_data: str) -> str:
        """Generate a PDF document from markdown content."""
        return await self.run_with_context(input_data, context=None)

    async def run_with_context(self, input_data: str, context=None) -> str:
        """Generate a PDF document, enriching params with execution context (company_id/user_id).
        
        Args:
            input_data: JSON string with content, title, filename, etc.
            context: Execution context dict (may contain 'company_id', 'user_id')
            
        Returns:
            JSON string with pdf_path and metadata
        """
        try:
            # ── Sanitize LLM-generated JSON input ──────────────────────
            cleaned = input_data.strip()

            # Strip markdown code fences if present (```json ... ```)
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                cleaned = "\n".join(lines).strip()

            # Remove trailing commas before } or ] (common LLM JSON error)
            import re as _re
            cleaned = _re.sub(r',\s*([}\]])', r'\1', cleaned)

            # Try parsing with strict=False first (handles control chars)
            try:
                params = json.loads(cleaned, strict=False)
            except json.JSONDecodeError:
                # Last resort: escape all unescaped control characters inside
                # string values by replacing literal newlines/tabs with \\n/\\t
                # This handles the case where LLM puts raw multi-line markdown
                # inside a JSON string value without escaping newlines.
                sanitized = ""
                in_string = False
                escape_next = False
                for ch in cleaned:
                    if escape_next:
                        sanitized += ch
                        escape_next = False
                        continue
                    if ch == '\\':
                        escape_next = True
                        sanitized += ch
                        continue
                    if ch == '"' and not escape_next:
                        in_string = not in_string
                        sanitized += ch
                        continue
                    if in_string:
                        if ch == '\n':
                            sanitized += '\\n'
                            continue
                        elif ch == '\r':
                            sanitized += '\\r'
                            continue
                        elif ch == '\t':
                            sanitized += '\\t'
                            continue
                        elif ord(ch) < 32:
                            sanitized += f'\\u{ord(ch):04x}'
                            continue
                    sanitized += ch
                try:
                    params = json.loads(sanitized, strict=False)
                except json.JSONDecodeError:
                    # Final fallback: input is raw markdown/text, not JSON at all.
                    # Auto-wrap it as a document with generated title and filename.
                    # Extract a meaningful title from the first H1 heading,
                    # skipping step-metadata headings (e.g. "Analyze Research Topic",
                    # "Wave 1:", "Step 1:", "Scrape Source", etc.)
                    _SKIP_PREFIXES = (
                        "analyze research", "wave ", "step ", "scrape", "extract",
                        "generate", "synthesize", "decompose", "discover", "verify",
                        "fact", "outline", "write", "section",
                    )
                    _lines = cleaned.split('\n')
                    _title = None
                    for _l in _lines:
                        _stripped = _l.strip()
                        if _stripped.startswith('# '):
                            _candidate = _stripped.lstrip('# ').strip()
                            _lower = _candidate.lower()
                            if not any(_lower.startswith(p) for p in _SKIP_PREFIXES):
                                _title = _candidate
                                break
                    if not _title:
                        # Try first ## that looks like a report title
                        for _l in _lines:
                            _stripped = _l.strip()
                            if _stripped.startswith('## '):
                                _candidate = _stripped.lstrip('# ').strip()
                                _lower = _candidate.lower()
                                if not any(_lower.startswith(p) for p in _SKIP_PREFIXES):
                                    _title = _candidate
                                    break
                    if not _title:
                        from datetime import datetime as _dtnow
                        _title = f"Deep Research Report {_dtnow.utcnow().strftime('%Y-%m-%d')}"
                    _safe_filename = _sanitize_filename(_title)
                    params = {
                        "content": cleaned,
                        "title": _title,
                        "filename": _safe_filename,
                    }

            # The company and user come from the execution context only — a
            # model-supplied company_id used to win here (TL-03).
            company_id = context_company_id(context)
            if not company_id:
                return json.dumps({"error": NO_CONTEXT_ERROR})
            user_id = str((context or {}).get("user_id") or "default")
            
            # Validate required parameters
            content = params.get("content")
            title = params.get("title")
            filename = params.get("filename")
            
            if not content:
                return json.dumps({"error": "Missing 'content' parameter"})
            if not title:
                return json.dumps({"error": "Missing 'title' parameter"})
            if not filename:
                return json.dumps({"error": "Missing 'filename' parameter"})
            
            # Optional parameters
            author = params.get("author", "HireBuddha Research Agent")
            subject = params.get("subject", "Research Report")
            image_paths = params.get("image_paths", [])
            purpose = params.get("purpose", f"PDF document: {title}")
            generated_by = params.get("generated_by", "pdf_generator")
            
            # If image_paths were provided, append them to the content
            if image_paths and isinstance(image_paths, list):
                content += "\n\n## Generated Images\n\n"
                for img in image_paths:
                    content += f"![Generated Image]({img})\n\n"
            else:
                # Auto-append images from context if they exist and aren't referenced
                import re
                if not re.search(r'!\[.*?\]\(.*?\)', content) and context:
                    # Scan context values for image paths
                    found_images = []
                    for k, v in context.items():
                        if isinstance(v, str) and '"images"' in v:
                            try:
                                v_dict = json.loads(v)
                                if "images" in v_dict and isinstance(v_dict["images"], list):
                                    for img in v_dict["images"]:
                                        if "filename" in img:
                                            found_images.append(img["filename"])
                            except Exception:
                                pass
                    if found_images:
                        content += "\n\n## Related Images\n\n"
                        for img in found_images:
                            content += f"![Related Image]({img})\n\n"
            
            # Rendered in a scratch directory, then kept as an artifact of the
            # call's run — the one write path (TL-59).
            import tempfile
            from src.ai.artifact_service import save_tool_output
            with tempfile.TemporaryDirectory(prefix="pdf-") as scratch:
                pdf_path = await self._generate_pdf(
                    content=content,
                    title=title,
                    filename=filename,
                    author=author,
                    subject=subject,
                    output_dir=Path(scratch),
                    company_id=company_id,
                    user_id=user_id,
                )
                pdf_bytes = pdf_path.read_bytes()
            artifact = await save_tool_output(
                context, file_name=pdf_path.name, file_bytes=pdf_bytes, mime_type="application/pdf",
                file_category="documents", generated_by=generated_by, purpose=purpose,
                extra_metadata={"title": title, "author": author, "subject": subject},
            )

            return json.dumps({
                "status": "success",
                "artifact_id": str(artifact.id),
                "pdf_path": artifact.file_path,
                "filename": pdf_path.name,
                "size_bytes": len(pdf_bytes),
                "created_at": datetime.utcnow().isoformat()
            })

        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON input: {str(e)}"})
        except Exception as e:
            return json.dumps({"error": f"PDF generation failed: {str(e)}"})
    
    async def _generate_pdf(
        self,
        content: str,
        title: str,
        filename: str,
        author: str,
        subject: str,
        output_dir: Path,
        company_id: str = "default",
        user_id: str = "default",
    ) -> Path:
        """Generate PDF from markdown content using WeasyPrint.
        
        Args:
            content: Markdown formatted content
            title: Document title
            filename: Output filename (without extension)
            author: Document author
            subject: Document subject
            
        Returns:
            Path to generated PDF file
        """
        if not HTML or not markdown:
            raise ImportError(
                "PDF rendering is unavailable on this server: "
                + (f"WeasyPrint cannot load its system libraries (Pango) — {_WEASYPRINT_ERROR}"
                   if _WEASYPRINT_ERROR else "the 'markdown' package is not installed")
            )
        
        # Pre-process markdown: convert image paths to file:// URIs so WeasyPrint
        # can locate and embed them. Handles:
        #   - absolute paths: /home/rahul/.../panel_1.png  → file:///home/...
        #   - bare filenames: panel_XXX.png → searched under the company's roots
        import re as _re
        import glob as _glob

        # Every image resolves inside this company's own files (TL-55): the
        # bare-filename search used to glob every company's artifacts, and an
        # absolute path could embed any file the backend can read.
        from src.ai.tools.sandbox.workspace import (
            PathOutsideWorkspace, company_roots, confine_path,
        )

        def _confined(path: str) -> str:
            try:
                resolved = confine_path(company_id, path)
            except PathOutsideWorkspace:
                return ""
            return resolved if os.path.exists(resolved) else ""

        def _resolve_bare_filename(filename_only: str) -> str:
            """Search this company's workspace and artifacts for the file."""
            for root in company_roots(company_id):
                for candidate in (Path(root) / str(user_id) / "images" / filename_only,
                                  Path(root) / "images" / filename_only,
                                  Path(root) / filename_only):
                    if candidate.exists():
                        return str(candidate)
            for root in company_roots(company_id):
                matches = _glob.glob(str(Path(_glob.escape(root)) / "**" / _glob.escape(filename_only)),
                                     recursive=True)
                if matches:
                    return matches[0]
            return ""

        def _fix_img_path(m):
            alt = m.group(1)
            path = m.group(2)
            # A web image: WeasyPrint's guarded fetcher decides (TL-55).
            if path.startswith(('http://', 'https://')):
                return m.group(0)
            if path.startswith('file://'):
                path = path[len('file://'):]
            if os.path.isabs(path) or os.sep in path or '/' in path:
                resolved = _confined(path) or _confined(
                    str(Path(company_roots(company_id)[1]) / path))
            else:
                resolved = _resolve_bare_filename(path)
            if resolved:
                return f'![{alt}]({Path(resolved).as_uri()})'
            logger.warning("pdf_generator: image %r is not one of this company's files; left out", path)
            return f'*[{alt or "image"} unavailable]*'

        # An image named by the company's storage key (what an image tool returns
        # on Blob storage) is fetched to a local file first (Phase 14 WS1 1.2).
        from src.ai.tools.sandbox.workspace import company_storage_key, fetch_storage_keys
        keyed = {p: p for p in _re.findall(r'!\[[^\]]*\]\(([^)]+)\)', content)
                 if company_id and company_storage_key(company_id, p)}
        if keyed:
            await fetch_storage_keys(keyed, company_id, tuple(keyed))
            content = _re.sub(r'(!\[[^\]]*\]\()([^)]+)(\))',
                              lambda m: m.group(1) + keyed.get(m.group(2), m.group(2)) + m.group(3), content)

        processed_content = _re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', _fix_img_path, content)

        # Convert markdown to HTML
        html_content = markdown.markdown(
            processed_content,
            extensions=[
                'extra',  # Tables, fenced code blocks, etc.
                'codehilite',  # Code syntax highlighting
                'toc',  # Table of contents
                'nl2br',  # Newline to <br>
            ]
        )
        
        # Build complete HTML document with styling
        full_html = self._build_html_document(
            html_content=html_content,
            title=title,
            author=author,
            subject=subject
        )
        
        # Sanitize filename — LLM often produces path-unsafe names with
        # colons, slashes, etc. (e.g. "Strategic_Report:_The_2024/2025_...")
        clean_filename = _sanitize_filename(filename)
            
        # Generate PDF
        output_path = output_dir / f"{clean_filename}.pdf"
        
        # Create font configuration
        font_config = FontConfiguration()
        
        # Create CSS for styling
        css = CSS(string=self._get_pdf_styles(), font_config=font_config)
        
        # Generate PDF with WeasyPrint
        HTML(string=full_html, url_fetcher=_guarded_fetcher(company_id)).write_pdf(
            output_path,
            stylesheets=[css],
            font_config=font_config
        )
        
        print(f"Generated PDF: {output_path.absolute()}")
        return output_path
    
    def _build_html_document(
        self,
        html_content: str,
        title: str,
        author: str,
        subject: str
    ) -> str:
        """Build complete HTML document with metadata and structure.
        
        Args:
            html_content: Converted markdown HTML
            title: Document title
            author: Document author
            subject: Document subject
            
        Returns:
            Complete HTML document string
        """
        current_date = datetime.utcnow().strftime("%B %d, %Y")
        
        return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="author" content="{author}">
    <meta name="subject" content="{subject}">
    <title>{title}</title>
</head>
<body>
    <div class="cover-page">
        <h1 class="report-title">{title}</h1>
        <p class="report-meta">
            <strong>Author:</strong> {author}<br>
            <strong>Date:</strong> {current_date}<br>
            <strong>Subject:</strong> {subject}
        </p>
    </div>
    
    <div class="page-break"></div>
    
    <div class="content">
        {html_content}
    </div>
    
    <div class="footer">
        <span class="page-number"></span>
    </div>
</body>
</html>
"""
    
    def _get_pdf_styles(self) -> str:
        """Get CSS styles for PDF formatting.
        
        Returns:
            CSS string for professional PDF styling
        """
        return """
@page {
    size: A4;
    margin: 2.5cm 2cm 3cm 2cm;
    
    @bottom-center {
        content: "Page " counter(page) " of " counter(pages);
        font-size: 9pt;
        color: #666;
    }
}

body {
    font-family: 'DejaVu Sans', Arial, sans-serif;
    font-size: 11pt;
    line-height: 1.6;
    color: #333;
}

/* Cover Page */
.cover-page {
    text-align: center;
    padding-top: 8cm;
}

.report-title {
    font-size: 28pt;
    font-weight: bold;
    color: #2c3e50;
    margin-bottom: 2cm;
}

.report-meta {
    font-size: 12pt;
    color: #555;
    line-height: 1.8;
}

/* Page Break */
.page-break {
    page-break-after: always;
}

/* Content Styling */
.content {
    text-align: justify;
}

h1 {
    font-size: 20pt;
    color: #2c3e50;
    margin-top: 1.5em;
    margin-bottom: 0.5em;
    page-break-after: avoid;
}

h2 {
    font-size: 16pt;
    color: #34495e;
    margin-top: 1.2em;
    margin-bottom: 0.4em;
    page-break-after: avoid;
}

h3 {
    font-size: 13pt;
    color: #555;
    margin-top: 1em;
    margin-bottom: 0.3em;
    page-break-after: avoid;
}

p {
    margin-bottom: 0.8em;
    text-align: justify;
}

/* Lists */
ul, ol {
    margin-left: 1.5em;
    margin-bottom: 1em;
}

li {
    margin-bottom: 0.3em;
}

/* Tables */
table {
    width: 100%;
    border-collapse: collapse;
    margin: 1em 0;
    page-break-inside: avoid;
}

th {
    background-color: #3498db;
    color: white;
    padding: 8pt;
    text-align: left;
    font-weight: bold;
}

td {
    border: 1px solid #ddd;
    padding: 6pt;
}

tr:nth-child(even) {
    background-color: #f9f9f9;
}

/* Code Blocks */
code {
    background-color: #f4f4f4;
    padding: 2pt 4pt;
    border-radius: 3pt;
    font-family: 'DejaVu Sans Mono', monospace;
    font-size: 9pt;
}

pre {
    background-color: #f4f4f4;
    padding: 10pt;
    border-left: 3pt solid #3498db;
    overflow-x: auto;
    page-break-inside: avoid;
}

pre code {
    background-color: transparent;
    padding: 0;
}

/* Blockquotes */
blockquote {
    border-left: 3pt solid #3498db;
    padding-left: 1em;
    margin-left: 0;
    font-style: italic;
    color: #555;
}

/* Links */
a {
    color: #3498db;
    text-decoration: none;
}

/* Horizontal Rules */
hr {
    border: none;
    border-top: 1pt solid #ddd;
    margin: 1.5em 0;
}

/* Avoid orphans and widows */
p, li {
    orphans: 3;
    widows: 3;
}

/* Keep headings with following content */
h1, h2, h3, h4, h5, h6 {
    page-break-after: avoid;
}

/* Images — ensure comic panel images render large and centred */
img {
    display: block;
    max-width: 16cm;
    width: 100%;
    height: auto;
    margin: 0.8em auto;
    border: 2pt solid #e0e0e0;
    border-radius: 4pt;
    page-break-inside: avoid;
}

/* Comic panel section styling */
h3 {
    background-color: #f0f7ff;
    padding: 6pt 10pt;
    border-left: 4pt solid #3498db;
    border-radius: 0 4pt 4pt 0;
}
"""
