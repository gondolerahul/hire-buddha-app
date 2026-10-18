# Tools package initialization
"""
HireBuddha AI Tools Package

This package contains production-ready tool implementations for:
- Calculator, Search, Excel, Scraper, PDF, File Writer
- Email (IMAP/SMTP), Image Gen, Video Gen, Sandbox
- Document CRUD (docx, pptx, xlsx)
- Social media tools (Phase 1, 2, 3)
"""

from src.ai.tools.base import Tool, ToolRegistry
from src.ai.tools.core.calculator import CalculatorTool
from src.ai.tools.core.search import WebSearchTool
from src.ai.tools.core.batch_search import BatchWebSearchTool
from src.ai.tools.documents.excel import ExcelTool
from src.ai.tools.core.scraper import ScraperTool
from src.ai.tools.documents.pdf_generator import PDFGeneratorTool
from src.ai.tools.core.file_writer import FileWriterTool
from src.ai.tools.email.email_tool import EmailIngestTool, EmailClassifyTool, EmailDraftTool, EmailSendTool
from src.ai.tools.media.image_generation import ImageGenerationTool
from src.ai.tools.media.video import (
    VideoGenerateTool,
    VideoEditTool,
    VideoAddSoundTool,
)
from src.ai.tools.sandbox.sandbox_executor import SandboxCodeTool
from src.ai.tools.sandbox.terminal_tool import TerminalTool
from src.ai.tools.sandbox.browser_tool import HeadlessBrowserTool
from src.ai.tools.documents.docx_tool import DocxTool
from src.ai.tools.documents.pptx_tool import PptxTool
from src.ai.tools.documents.document_save import DocumentSaveTool
from src.ai.tools.crm.crm_tools import (
    GetCurrentDateTimeTool,
    WhatsAppSendTenantTool,
    GoogleCalendarCreateEventTool,
    CRMUpdateLeadTool,
)

# Register all default tools
ToolRegistry.register(CalculatorTool())
ToolRegistry.register(WebSearchTool())
ToolRegistry.register(BatchWebSearchTool())
ToolRegistry.register(ExcelTool())
ToolRegistry.register(ScraperTool())
ToolRegistry.register(PDFGeneratorTool())
ToolRegistry.register(FileWriterTool())

# Email tools (IMAP/SMTP)
ToolRegistry.register(EmailIngestTool())
ToolRegistry.register(EmailClassifyTool())
ToolRegistry.register(EmailDraftTool())
ToolRegistry.register(EmailSendTool())

# Media generation tools
ToolRegistry.register(ImageGenerationTool())
# Composable video tools (Phase 12 `03`): generate / edit / add-sound.
ToolRegistry.register(VideoGenerateTool())
ToolRegistry.register(VideoEditTool())
ToolRegistry.register(VideoAddSoundTool())

# Sandbox execution tool (Ph-A: asyncio subprocess tier)
ToolRegistry.register(SandboxCodeTool())

# Terminal tool (shell command execution via sandbox)
ToolRegistry.register(TerminalTool())

# Headless browser tool (Playwright-based web interaction)
ToolRegistry.register(HeadlessBrowserTool())

# Document CRUD tools
ToolRegistry.register(DocxTool())
ToolRegistry.register(PptxTool())

# Document save utility (Phase 8: Document Generation Toolkit)
ToolRegistry.register(DocumentSaveTool())

# CRM integration tools (Real Estate tenant workflow)
ToolRegistry.register(GetCurrentDateTimeTool())
ToolRegistry.register(WhatsAppSendTenantTool())
ToolRegistry.register(GoogleCalendarCreateEventTool())
ToolRegistry.register(CRMUpdateLeadTool())

# Social platforms: one primitive; the per-verb classes are its operations (P6.2)
from src.ai.tools.social import SocialAPITool
ToolRegistry.register(SocialAPITool())

# Meta-Agent tools (context-aware — use run_with_context)
from src.ai.tools.meta import (
    MetaRegistrySearchTool, MetaSchemaValidatorTool,
    MetaEntityCreatorTool, MetaEntityExecutorTool,
    MetaPlatformIntrospectTool, MetaSpecCriticTool,
    AgentIntrospectTool, AgentReflectTool,
    ToolSynthesisTool,
)
ToolRegistry.register(MetaPlatformIntrospectTool())
ToolRegistry.register(MetaRegistrySearchTool())
ToolRegistry.register(MetaSchemaValidatorTool())
ToolRegistry.register(MetaEntityCreatorTool())
ToolRegistry.register(MetaEntityExecutorTool())
# Introspection meta-tools (Phase 12 `06` §3.1) — opt-in self-introspection +
# reflection, auto-injected per the meta-cognition matrix.
ToolRegistry.register(AgentIntrospectTool())
ToolRegistry.register(AgentReflectTool())
# Tool synthesis (Phase 12 `06` §2) — EXPERIMENTAL: needs the per-company
# tools.experimental.tool_synthesis opt-in to be visible, plus the in-tool
# is_meta_agent + meta_agent.tool_synthesis_enabled kill-switch gates.
ToolRegistry.register(ToolSynthesisTool())
# Spec critic (TX-04) — EXPERIMENTAL; the Board's critic calls it directly.
ToolRegistry.register(MetaSpecCriticTool())

# Automation (Phase 14 WS3, tech spec §7.10): an agent schedules work and sends
# signals; what it may is its tool grants, its Automation tab and the
# business's automation limits.
from src.ai.tools.automation import (CancelScheduleTool, EmitEventTool, ListSchedulesTool, ScheduleAgentTool,
                                    WaitForEventTool)
ToolRegistry.register(ScheduleAgentTool())
ToolRegistry.register(CancelScheduleTool())
ToolRegistry.register(ListSchedulesTool())
ToolRegistry.register(EmitEventTool())
ToolRegistry.register(WaitForEventTool())

__all__ = [
    "Tool", "ToolRegistry",
    "CalculatorTool", "WebSearchTool", "BatchWebSearchTool", "ExcelTool", "ScraperTool",
    "PDFGeneratorTool", "FileWriterTool",
    "EmailIngestTool", "EmailClassifyTool", "EmailDraftTool", "EmailSendTool",
    "ImageGenerationTool",
    "VideoGenerateTool", "VideoEditTool", "VideoAddSoundTool",
    "SandboxCodeTool", "TerminalTool",
    "HeadlessBrowserTool",
    "DocxTool", "PptxTool", "DocumentSaveTool",
    "SocialAPITool",
    "ScheduleAgentTool", "CancelScheduleTool", "ListSchedulesTool", "EmitEventTool", "WaitForEventTool",
    # CRM integration tools
    "GetCurrentDateTimeTool", "WhatsAppSendTenantTool",
    "GoogleCalendarCreateEventTool", "CRMUpdateLeadTool",
    # Meta-Agent tools
    "MetaPlatformIntrospectTool", "MetaRegistrySearchTool",
    "MetaSchemaValidatorTool", "MetaEntityCreatorTool",
    "MetaEntityExecutorTool", "ToolSynthesisTool", "MetaSpecCriticTool",
    "AgentIntrospectTool", "AgentReflectTool",
]

