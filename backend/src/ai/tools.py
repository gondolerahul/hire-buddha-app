"""
Tools module for HireBuddha AI Platform.

This module provides backward compatibility by re-exporting the tools
from the new package structure. New code should import directly from
src.ai.tools package.

Available Tools:
    - CalculatorTool: Safe mathematical expression evaluation
    - WebSearchTool: Real web search using DuckDuckGo
    - ExcelTool: Excel file processing
    - ScraperTool: Web scraping capabilities
    - PDFGeneratorTool: PDF document generation
"""

# Re-export from the new tools package for backward compatibility
from src.ai.tools import (
    Tool,
    ToolRegistry,
    CalculatorTool,
    WebSearchTool,
    ExcelTool,
    ScraperTool,
    PDFGeneratorTool,
    FileWriterTool,
    TerminalTool,
    HeadlessBrowserTool
)

__all__ = [
    "Tool",
    "ToolRegistry", 
    "CalculatorTool",
    "WebSearchTool",
    "ExcelTool",
    "ScraperTool",
    "PDFGeneratorTool",
    "FileWriterTool",
    "TerminalTool",
    "HeadlessBrowserTool"
]

