#!/usr/bin/env python3
"""
Deep Research Entity Setup Script
==================================

Creates all 15 hierarchical entities for the Deep Research process via the API.
Entities are created bottom-up: ACTIONs → SKILLs → AGENTs → PROCESS.

After creation, parent entities are updated to reference child UUIDs in their
hierarchy.children arrays.

Usage:
    # Set environment variables:
    export API_BASE_URL="https://gateway.hirebuddha.com/api/v1"
    export AUTH_TOKEN="your_jwt_token"

    python create_entities.py

    # Or pass as arguments:
    python create_entities.py --base-url http://localhost:8000/api/v1 --token "your_jwt_token"
"""

import argparse
import json
import os
import sys
import time
from typing import Dict, Any, Optional
from uuid import UUID

try:
    import requests
except ImportError:
    print("Error: 'requests' library is required. Install with: pip install requests")
    sys.exit(1)


# ============================================================================
# Configuration
# ============================================================================

DEFAULT_BASE_URL = os.environ.get(
    "API_BASE_URL", "https://gateway.hirebuddha.com/api/v1"
)
AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "")

# Created entity IDs — populated during execution
ENTITY_IDS: Dict[str, str] = {}


# ============================================================================
# API Client
# ============================================================================

class APIClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        })

    def create_entity(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a hierarchical entity via POST /ai/entities."""
        url = f"{self.base_url}/ai/entities"
        resp = self.session.post(url, json=payload)
        if resp.status_code not in (200, 201):
            print(f"  ❌ FAILED: {resp.status_code} — {resp.text[:500]}")
            resp.raise_for_status()
        data = resp.json()
        print(f"  ✅ Created: {data['name']} → {data['id']}")
        return data

    def update_entity(self, entity_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Update a hierarchy entity via PUT /ai/entities/{id}."""
        url = f"{self.base_url}/ai/entities/{entity_id}"
        resp = self.session.put(url, json=payload)
        if resp.status_code not in (200, 201):
            print(f"  ❌ UPDATE FAILED: {resp.status_code} — {resp.text[:500]}")
            resp.raise_for_status()
        data = resp.json()
        print(f"  ✅ Updated: {data['name']} — hierarchy linked")
        return data

    def trigger_execution(self, entity_id: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Trigger an execution run via POST /ai/execute."""
        url = f"{self.base_url}/ai/execute"
        payload = {"entity_id": entity_id, "input_data": input_data}
        resp = self.session.post(url, json=payload)
        if resp.status_code not in (200, 201):
            print(f"  ❌ EXEC FAILED: {resp.status_code} — {resp.text[:500]}")
            resp.raise_for_status()
        data = resp.json()
        print(f"  🚀 Execution started: {data['id']}")
        return data


# ============================================================================
# Entity Definitions — Layer 1: ACTIONs (7 entities)
# ============================================================================

ACTIONS = [
    {
        "key": "web_search_action",
        "payload": {
            "name": "deep-research-web-search",
            "display_name": "Deep Research Web Search",
            "description": "Executes a targeted web search query using SerpAPI/DuckDuckGo and returns structured results with titles, URLs, and snippets. Designed for precision recall on academic, technical, and current-affairs queries.",
            "goal": "Find the most relevant, authoritative web results for a given search query. Prioritize primary sources, academic publications, official documentation, and authoritative news sources over blog posts and opinion pieces.",
            "type": "ACTION",
            "version": "1.0.0",
            "status": "ACTIVE",
            "tags": ["deep-research", "search", "web", "information-retrieval"],
            "identity": {
                "system_prompt": "You are a precision web search specialist. Your job is to formulate the optimal search query and extract the most relevant results. Always prioritize: (1) Primary sources and official documentation, (2) Peer-reviewed or academic sources, (3) Authoritative journalism from established outlets, (4) Expert analysis from recognized domain specialists. Deprioritize: opinion blogs, social media posts, aggregator sites.",
                "behavioral_constraints": [
                    "Never fabricate search results or URLs",
                    "Always preserve exact URLs from search results",
                    "Flag when results seem outdated or potentially unreliable",
                    "Include publication dates when available"
                ]
            },
            "hierarchy": {
                "is_atomic": True,
                "composition_depth": 0,
                "children": []
            },
            "logic_gate": {
                "reasoning_config": {
                    "task_type": "text_generation",
                    "temperature": 0.2,
                    "reasoning_mode": "REACT"
                },
                "retry_policy": {
                    "max_retries": 2,
                    "backoff_strategy": "EXPONENTIAL",
                    "retry_on": ["TOOL_FAILURE", "TIMEOUT"]
                },
                "context_policy": {
                    "type": "EXPLICIT",
                    "explicit_keys": ["input", "query"],
                    "summarize_threshold": 8000
                }
            },
            "planning": {
                "static_plan": {
                    "enabled": True,
                    "steps": [
                        {
                            "step_id": "step_1",
                            "order": 1,
                            "name": "Execute Web Search",
                            "description": "Run the web search query using the web_search tool",
                            "type": "TOOL_CALL",
                            "target": {
                                "tool_id": "web_search",
                                "prompt_template": "{{input}}",
                                "input_dependencies": []
                            },
                            "required": True
                        }
                    ]
                },
                "dynamic_planning": {"enabled": False}
            },
            "capabilities": {
                "tools": [{"tool_id": "web_search"}],
                "memory": {"enabled": True, "mode": "CORTEX"},
                "context_engineering": {"inject_cortex_viewport": True}
            },
            "governance": {
                "timeout_ms": 30000,
                "max_cost_usd": 0.10
            },
            "io_contract": {
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "The search query to execute"}},
                    "required": ["query"]
                },
                "output_schema": {
                    "type": "object",
                    "properties": {"results": {"type": "array", "description": "List of search result objects"}}
                }
            }
        }
    },
    {
        "key": "page_scrape_action",
        "payload": {
            "name": "deep-research-page-scrape",
            "display_name": "Deep Research Page Scraper",
            "description": "Scrapes a web page URL using Firecrawl and returns clean markdown content. Handles JavaScript-rendered pages, paywalls (where possible), and multi-page articles.",
            "goal": "Extract the complete, clean text content from a web page, preserving structure (headings, lists, tables) while removing navigation, ads, and boilerplate.",
            "type": "ACTION",
            "version": "1.0.0",
            "status": "ACTIVE",
            "tags": ["deep-research", "scraping", "content-extraction"],
            "identity": {
                "system_prompt": "You are a web content extraction specialist. Extract the main content from web pages while preserving document structure. Focus on the article body, data tables, and key figures. Ignore navigation, ads, sidebars, and cookie banners.",
                "behavioral_constraints": [
                    "Never modify the factual content of scraped text",
                    "Preserve all data tables and structured information",
                    "Note when content appears truncated or behind a paywall"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "REACT"},
                "retry_policy": {"max_retries": 3, "backoff_strategy": "EXPONENTIAL", "retry_on": ["TOOL_FAILURE", "TIMEOUT"]},
                "context_policy": {"type": "EXPLICIT", "explicit_keys": ["input", "url"]}
            },
            "planning": {
                "static_plan": {
                    "enabled": True,
                    "steps": [
                        {
                            "step_id": "step_1",
                            "order": 1,
                            "name": "Scrape URL Content",
                            "description": "Scrape the target URL using the scraper tool",
                            "type": "TOOL_CALL",
                            "target": {"tool_id": "scraper_tool", "prompt_template": "{{input}}"}
                        }
                    ]
                }
            },
            "capabilities": {
                "tools": [{"tool_id": "scraper_tool"}],
                "memory": {"enabled": True, "mode": "CORTEX"}
            },
            "governance": {"timeout_ms": 60000, "max_cost_usd": 0.05}
        }
    },
    {
        "key": "content_extract_action",
        "payload": {
            "name": "deep-research-content-extract",
            "display_name": "Deep Research Content Extractor",
            "description": "Analyzes scraped web content and extracts structured information: key claims, statistics, direct quotes, named entities, dates, and source credibility assessment.",
            "goal": "Transform raw web content into structured, citation-ready research notes with explicit source attribution for every extracted fact.",
            "type": "ACTION",
            "version": "1.0.0",
            "status": "ACTIVE",
            "tags": ["deep-research", "extraction", "analysis", "NLP"],
            "identity": {
                "system_prompt": "You are a research analyst specializing in information extraction. From the given content, extract: (1) KEY CLAIMS — main assertions made with their evidence basis, (2) STATISTICS — specific numbers, percentages, metrics with exact source attribution, (3) QUOTES — notable direct quotes from named individuals, (4) ENTITIES — companies, people, products, organizations mentioned, (5) CREDIBILITY — your assessment of source reliability (1-5 scale) with reasoning. Output as structured JSON.",
                "behavioral_constraints": [
                    "Never infer statistics that aren't explicitly stated in the source",
                    "Always attribute claims to their original source",
                    "Distinguish between facts, claims, and opinions",
                    "Flag contradictions with previously extracted information"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.2, "reasoning_mode": "CHAIN_OF_THOUGHT"},
                "context_policy": {"type": "FULL", "summarize_threshold": 15000}
            },
            "planning": {
                "static_plan": {
                    "enabled": True,
                    "steps": [
                        {
                            "step_id": "step_1",
                            "order": 1,
                            "name": "Extract Structured Information",
                            "description": "Analyze the provided content and extract key claims, statistics, quotes, entities, and credibility assessment into structured JSON format",
                            "type": "ACTION",
                            "target": {"prompt_template": "Analyze this content and extract structured research information:\n\n{{input}}"}
                        }
                    ]
                }
            },
            "capabilities": {
                "tools": [],
                "memory": {"enabled": True, "mode": "CORTEX"}
            },
            "governance": {"timeout_ms": 60000, "max_cost_usd": 0.15}
        }
    },
    {
        "key": "fact_check_action",
        "payload": {
            "name": "deep-research-fact-check",
            "display_name": "Deep Research Fact Checker",
            "description": "Takes a specific claim or statistic and verifies it against multiple independent sources via web search. Returns a verification verdict with supporting/contradicting evidence.",
            "goal": "Independently verify claims by cross-referencing against at least 2-3 independent authoritative sources. Produce a clear verdict: VERIFIED, PARTIALLY_VERIFIED, UNVERIFIED, or CONTRADICTED.",
            "type": "ACTION",
            "version": "1.0.0",
            "status": "ACTIVE",
            "tags": ["deep-research", "fact-checking", "verification"],
            "identity": {
                "system_prompt": "You are a rigorous fact-checker. For each claim presented, you must: (1) Search for independent corroboration from authoritative sources, (2) Identify any contradicting evidence, (3) Note the recency and reliability of corroborating sources, (4) Assign a verdict: VERIFIED (3+ independent sources agree), PARTIALLY_VERIFIED (some support, some gaps), UNVERIFIED (insufficient evidence), CONTRADICTED (reliable sources disagree). Always show your verification chain.",
                "behavioral_constraints": [
                    "Never mark a claim as VERIFIED without at least 2 independent sources",
                    "Primary sources always outweigh secondary sources",
                    "Note any temporal limitations (claim may have been true at time X but not now)",
                    "Flag when a claim is unfalsifiable"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "REFLECTION"},
                "retry_policy": {"max_retries": 2, "backoff_strategy": "LINEAR"}
            },
            "planning": {
                "static_plan": {
                    "enabled": True,
                    "steps": [
                        {
                            "step_id": "step_1",
                            "order": 1,
                            "name": "Search for Verification",
                            "description": "Search the web for independent sources that confirm or deny the claim",
                            "type": "TOOL_CALL",
                            "target": {"tool_id": "web_search", "prompt_template": "verify: {{input}}"}
                        },
                        {
                            "step_id": "step_2",
                            "order": 2,
                            "name": "Assess Verification Evidence",
                            "description": "Analyze search results and produce a verification verdict with supporting evidence chain",
                            "type": "ACTION",
                            "target": {
                                "prompt_template": "Based on the search results in {{step_1}}, verify the original claim:\n\nCLAIM: {{input}}\n\nProduce a verification verdict (VERIFIED/PARTIALLY_VERIFIED/UNVERIFIED/CONTRADICTED) with:\n1. Supporting sources (URL + key quote)\n2. Contradicting sources (if any)\n3. Confidence level (0-100%)\n4. Caveats or limitations",
                                "input_dependencies": ["step_1"]
                            }
                        }
                    ]
                }
            },
            "capabilities": {
                "tools": [{"tool_id": "web_search"}],
                "memory": {"enabled": True, "mode": "CORTEX"}
            },
            "governance": {"timeout_ms": 90000, "max_cost_usd": 0.20}
        }
    },
    {
        "key": "section_writer_action",
        "payload": {
            "name": "deep-research-section-writer",
            "display_name": "Deep Research Section Writer",
            "description": "Writes a single, publication-quality section of a research report from structured research findings. Produces properly cited, well-argued prose with clear topic sentences, evidence integration, and analytical depth.",
            "goal": "Transform research findings into a compelling, well-structured report section that reads like it was written by a senior research analyst. Every claim must be cited. Every paragraph must advance the argument.",
            "type": "ACTION",
            "version": "1.0.0",
            "status": "ACTIVE",
            "tags": ["deep-research", "writing", "report-generation"],
            "identity": {
                "system_prompt": "You are a senior research writer producing publication-quality analysis. Your writing style is: authoritative but accessible, data-driven, precisely cited, and analytically rigorous. Every section you write must have: (1) A clear topic sentence stating the section's thesis, (2) Evidence paragraphs integrating facts with analysis, (3) Proper inline citations [Source Name, Date], (4) A concluding insight that connects to the broader research question. Use active voice. Avoid hedging language unless genuinely uncertain. Present data in context (comparisons, trends, benchmarks).",
                "behavioral_constraints": [
                    "Every factual claim must have an inline citation",
                    "Never pad with generic filler text",
                    "Use specific numbers over vague qualifiers",
                    "Maintain consistent tone with other report sections"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.5, "reasoning_mode": "CHAIN_OF_THOUGHT"}
            },
            "planning": {
                "static_plan": {
                    "enabled": True,
                    "steps": [
                        {
                            "step_id": "step_1",
                            "order": 1,
                            "name": "Write Report Section",
                            "description": "Write a publication-quality section based on the provided research findings and outline",
                            "type": "ACTION",
                            "target": {"prompt_template": "{{input}}"}
                        }
                    ]
                }
            },
            "capabilities": {
                "tools": [],
                "memory": {"enabled": True, "mode": "CORTEX"}
            },
            "governance": {"timeout_ms": 120000, "max_cost_usd": 0.25}
        }
    },
    {
        "key": "outline_generator_action",
        "payload": {
            "name": "deep-research-outline-generator",
            "display_name": "Deep Research Outline Generator",
            "description": "Generates a detailed, hierarchical report outline based on the research topic, discovered information, and target audience. Produces section titles, sub-section structure, and per-section content guidance.",
            "goal": "Create a comprehensive report outline that ensures complete coverage of the topic, logical flow between sections, and appropriate depth allocation based on information density.",
            "type": "ACTION",
            "version": "1.0.0",
            "status": "ACTIVE",
            "tags": ["deep-research", "planning", "outline", "structure"],
            "identity": {
                "system_prompt": "You are a research report architect. Design outlines that: (1) Cover the topic comprehensively with no significant gaps, (2) Flow logically from context → analysis → implications, (3) Allocate depth proportional to information importance, (4) Include specific content guidance for each section (what data, what analysis, what sources). Output as a structured JSON array of sections with title, subsections, content_guidance, and estimated_word_count fields.",
                "behavioral_constraints": [
                    "Every outline must include an Executive Summary section",
                    "Every outline must include a Methodology/Sources section",
                    "Subsections should be 3-7 per major section",
                    "Total word count target should be proportional to topic complexity"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "thinking", "temperature": 0.4, "reasoning_mode": "TREE_OF_THOUGHTS"}
            },
            "capabilities": {
                "tools": [],
                "memory": {"enabled": True, "mode": "CORTEX"}
            },
            "governance": {"timeout_ms": 90000, "max_cost_usd": 0.20}
        }
    },
    {
        "key": "pdf_export_action",
        "payload": {
            "name": "deep-research-pdf-export",
            "display_name": "Deep Research PDF Exporter",
            "description": "Takes the fully assembled research report content and generates a professionally formatted PDF document with table of contents, headers, citations, and consistent styling.",
            "goal": "Produce a publication-ready PDF that looks like it came from a professional research firm.",
            "type": "ACTION",
            "version": "1.0.0",
            "status": "ACTIVE",
            "tags": ["deep-research", "pdf", "export", "document-generation"],
            "identity": {
                "system_prompt": "You are a document formatting specialist. Take the provided report content and format it into a professional PDF with proper headers, page numbers, table of contents, citations, and consistent typography.",
                "behavioral_constraints": [
                    "Preserve all citations and source references",
                    "Maintain heading hierarchy from the outline",
                    "Include page numbers and table of contents"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "REACT"}
            },
            "planning": {
                "static_plan": {
                    "enabled": True,
                    "steps": [
                        {
                            "step_id": "step_1",
                            "order": 1,
                            "name": "Generate PDF Report",
                            "description": "Generate a professionally formatted PDF from the report content",
                            "type": "TOOL_CALL",
                            "target": {"tool_id": "pdf_generator", "prompt_template": "{{input}}"}
                        }
                    ]
                }
            },
            "capabilities": {
                "tools": [{"tool_id": "pdf_generator"}],
                "memory": {"enabled": True, "mode": "CORTEX"}
            },
            "governance": {"timeout_ms": 120000, "max_cost_usd": 0.10}
        }
    },
]


# ============================================================================
# Entity Definitions — Layer 2: SKILLs (5 entities)
# ============================================================================

SKILLS = [
    {
        "key": "query_decomposer_skill",
        "payload": {
            "name": "deep-research-query-decomposer",
            "display_name": "Research Query Decomposer",
            "description": "Takes a broad research topic and systematically decomposes it into 5-15 targeted, non-overlapping search queries that together provide comprehensive coverage. Uses taxonomic decomposition (what, who, when, where, how, why) and perspective triangulation (proponent, critic, neutral).",
            "goal": "Generate a set of search queries that, when executed, will retrieve comprehensive, multi-perspective information on the research topic. Queries should cover: (1) Core facts and current state, (2) Historical context and evolution, (3) Key players and stakeholders, (4) Competing viewpoints and criticisms, (5) Quantitative data and metrics, (6) Future outlook and implications.",
            "type": "SKILL",
            "version": "1.0.0",
            "status": "ACTIVE",
            "tags": ["deep-research", "query-planning", "decomposition"],
            "identity": {
                "system_prompt": "You are a research query strategist. Your expertise is decomposing complex topics into optimal search queries. You use these strategies:\n\n1. TAXONOMIC DECOMPOSITION: Break the topic along who/what/when/where/how/why axes\n2. PERSPECTIVE TRIANGULATION: Generate queries from proponent, critic, and neutral perspectives\n3. SPECIFICITY GRADIENT: Mix broad context queries with narrow, specific data queries\n4. TEMPORAL SPANNING: Include queries for historical context, current state, and future outlook\n5. SOURCE TARGETING: Craft queries likely to surface academic, official, and expert sources\n\nOutput a JSON array of query objects with: query, rationale, expected_source_type, priority (1-5).",
                "behavioral_constraints": [
                    "Generate minimum 5, maximum 15 queries",
                    "Queries must be non-overlapping in expected results",
                    "At least 2 queries must target opposing viewpoints",
                    "At least 1 query must target quantitative data specifically"
                ]
            },
            "hierarchy": {"is_atomic": False, "composition_depth": 1, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "thinking", "temperature": 0.5, "reasoning_mode": "TREE_OF_THOUGHTS"},
                "context_policy": {"type": "FULL", "summarize_threshold": 12000}
            },
            "planning": {
                "static_plan": {
                    "enabled": True,
                    "steps": [
                        {
                            "step_id": "step_1",
                            "order": 1,
                            "name": "Analyze Research Topic",
                            "description": "Analyze the research topic to identify key dimensions, stakeholders, and information gaps that need to be covered",
                            "type": "ACTION",
                            "target": {"prompt_template": "Analyze this research topic and identify all key dimensions that need investigation:\n\nTOPIC: {{input}}\n\nIdentify: (1) Core concepts to define, (2) Key stakeholders/entities, (3) Historical timeline, (4) Quantitative metrics to find, (5) Competing perspectives, (6) Related adjacent topics"}
                        },
                        {
                            "step_id": "step_2",
                            "order": 2,
                            "name": "Generate Search Queries",
                            "description": "Generate 5-15 targeted, non-overlapping search queries covering all identified dimensions",
                            "type": "ACTION",
                            "target": {
                                "prompt_template": "Based on this topic analysis:\n\n{{step_1}}\n\nGenerate 5-15 optimal search queries. Output ONLY a raw JSON array of query strings, nothing else. No markdown, no explanations, no source lists. Example format:\n[\"query 1\", \"query 2\", \"query 3\"]\n\nThe queries should be actual Google search queries, NOT source titles, URLs, or descriptions.",
                                "input_dependencies": ["step_1"]
                            }
                        }
                    ]
                },
                "dynamic_planning": {"enabled": False}
            },
            "capabilities": {
                "tools": [],
                "memory": {"enabled": True, "mode": "CORTEX"}
            },
            "governance": {"timeout_ms": 120000, "max_cost_usd": 0.30}
        }
    },
    {
        "key": "source_discoverer_skill",
        "payload": {
            "name": "deep-research-source-discoverer",
            "display_name": "Research Source Discoverer",
            "description": "Executes a batch of search queries, deduplicates results, ranks sources by authority and relevance, and produces a prioritized source list for deep analysis.",
            "goal": "Discover and rank the most authoritative, relevant sources for the research topic. Ensure diversity of source types (academic, journalistic, official, expert blogs) and perspectives.",
            "type": "SKILL",
            "version": "1.0.0",
            "status": "ACTIVE",
            "tags": ["deep-research", "source-discovery", "search-execution"],
            "identity": {
                "system_prompt": "You are a research librarian specializing in source discovery and evaluation. Execute searches, then evaluate and rank sources by: (1) Authority — is this from a recognized expert, institution, or publication? (2) Recency — how current is this information? (3) Depth — does this source provide substantive analysis or just surface-level coverage? (4) Uniqueness — does this source offer information not available elsewhere? (5) Bias — is this source known for any particular bias?\n\nProduce a ranked source list with URL, title, source_type, authority_score (1-10), and scrape_priority.",
                "behavioral_constraints": [
                    "Execute ALL provided search queries — do not skip any",
                    "Deduplicate URLs across query results",
                    "Include at least 3 different source types in final ranking",
                    "Flag any sources with known bias"
                ]
            },
            "hierarchy": {"is_atomic": False, "composition_depth": 1, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.3, "reasoning_mode": "REACT"},
                "context_policy": {"type": "SLIDING_WINDOW", "max_chars": 20000},
                "retry_policy": {"max_retries": 2, "backoff_strategy": "EXPONENTIAL"}
            },
            "planning": {
                "static_plan": {
                    "enabled": True,
                    "steps": [
                        {
                            "step_id": "step_1",
                            "order": 1,
                            "name": "Execute All Search Queries",
                            "description": "Execute all search queries from the input using batch search and collect all results",
                            "type": "TOOL_CALL",
                            # batch_web_search accepts a JSON array of queries — it executes each
                            # one individually with SerpAPI and returns aggregated results.
                            # This prevents the 'URL too long' error from passing the full array
                            # as a single query to web_search.
                            "target": {"tool_id": "batch_web_search", "prompt_template": "{{input}}"}
                        },
                        {
                            "step_id": "step_2",
                            "order": 2,
                            "name": "Rank and Deduplicate Sources",
                            "description": "Analyze all search results, deduplicate URLs, and rank sources by authority, recency, depth, and uniqueness",
                            "type": "ACTION",
                            "target": {
                                "prompt_template": "Given these search results:\n\n{{step_1}}\n\nProduce a ranked, deduplicated source list. For each source provide: url, title, source_type (academic/news/official/expert/data), authority_score (1-10), scrape_priority (1=scrape first). Select the top 10-15 most valuable sources for scraping.",
                                "input_dependencies": ["step_1"]
                            }
                        }
                    ]
                },
                "dynamic_planning": {
                    "enabled": False
                }
            },
            "capabilities": {
                "tools": [{"tool_id": "batch_web_search"}, {"tool_id": "web_search"}],
                "memory": {"enabled": True, "mode": "CORTEX"}
            },
            "governance": {"timeout_ms": 300000, "max_cost_usd": 1.00}
        }
    },
    {
        "key": "source_analyzer_skill",
        "payload": {
            "name": "deep-research-source-analyzer",
            "display_name": "Research Source Analyzer",
            "description": "For each high-priority source: scrapes the full content, extracts key claims/statistics/quotes, assesses credibility, and writes structured research findings to the CORTEX knowledge tree.",
            "goal": "Transform raw web sources into structured, citation-ready research knowledge. Every fact extracted must be traceable to its original source URL.",
            "type": "SKILL",
            "version": "1.0.0",
            "status": "ACTIVE",
            "tags": ["deep-research", "source-analysis", "extraction"],
            "identity": {
                "system_prompt": "You are a deep research analyst. For each source URL: (1) Scrape the full content, (2) Extract all key claims, statistics, and notable quotes, (3) Assess source credibility (1-5), (4) Identify how this source relates to other sources already analyzed (corroboration, contradiction, new angle), (5) Write structured findings to the CORTEX tree. Be exhaustive — capture every relevant data point.",
                "behavioral_constraints": [
                    "Process sources one at a time in priority order",
                    "Write findings to CORTEX after each source (not at the end)",
                    "Track cross-source corroboration as you go",
                    "Stop after 10 sources or when diminishing returns are detected"
                ]
            },
            "hierarchy": {"is_atomic": False, "composition_depth": 1, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.2, "reasoning_mode": "CHAIN_OF_THOUGHT"},
                "context_policy": {"type": "SLIDING_WINDOW", "max_chars": 25000, "summarize_threshold": 20000}
            },
            "planning": {
                "static_plan": {
                    "enabled": True,
                    "steps": [
                        {
                            "step_id": "step_1",
                            "order": 1,
                            "name": "Scrape Source Content",
                            "description": "Scrape the full content from the next priority source URL",
                            "type": "TOOL_CALL",
                            "target": {"tool_id": "scraper_tool", "prompt_template": "{{input}}"}
                        },
                        {
                            "step_id": "step_2",
                            "order": 2,
                            "name": "Extract Structured Information",
                            "description": "Analyze the scraped content and extract key claims, statistics, quotes, entities, and credibility assessment",
                            "type": "ACTION",
                            "target": {
                                "prompt_template": "Analyze this scraped content and extract structured research information:\n\n{{step_1}}\n\nExtract: KEY_CLAIMS, STATISTICS, QUOTES, ENTITIES, CREDIBILITY_SCORE (1-5), RELATIONSHIP_TO_PRIOR_FINDINGS",
                                "input_dependencies": ["step_1"]
                            }
                        }
                    ]
                },
                "dynamic_planning": {
                    "enabled": True,
                    "planning_prompt": "Iterate through all source URLs provided in the input. For each URL: scrape it, analyze it, then move to the next. If a scrape fails, skip that source and continue. Use the headless_browser tool as fallback for JavaScript-heavy pages."
                },
                "loop_control": {
                    "max_iterations": 12,
                    "iteration_context_mode": "SUMMARIZED",
                    "summary_every_n_iterations": 3
                }
            },
            "capabilities": {
                "tools": [{"tool_id": "scraper_tool"}, {"tool_id": "headless_browser"}, {"tool_id": "web_search"}],
                "memory": {"enabled": True, "mode": "CORTEX", "cortex_config": {"auto_checkpoint": True, "context_budget_pct": 40}}
            },
            "governance": {"timeout_ms": 600000, "max_cost_usd": 3.00}
        }
    },
    {
        "key": "fact_verifier_skill",
        "payload": {
            "name": "deep-research-fact-verifier",
            "display_name": "Research Fact Verification Engine",
            "description": "Takes all critical claims extracted from sources and systematically verifies each against independent sources. Produces a verification matrix showing which claims are verified, partially verified, unverified, or contradicted.",
            "goal": "Ensure factual accuracy of the research by independently verifying every critical claim. This is what separates world-class research from surface-level aggregation.",
            "type": "SKILL",
            "version": "1.0.0",
            "status": "ACTIVE",
            "tags": ["deep-research", "fact-checking", "verification", "quality"],
            "identity": {
                "system_prompt": "You are a senior fact-checker for a Tier-1 research firm. Your standard: NO claim appears in the final report without independent verification. Process each claim through a 3-source verification protocol. Track verification status in a matrix. Flag any claim where sources disagree — these require special handling in the report (presented as 'contested' with both sides cited).",
                "behavioral_constraints": [
                    "Verify the 10 most critical claims at minimum",
                    "Each verification must cite at least 2 independent sources",
                    "Flag any verified claim where the original source was the ONLY source",
                    "Produce a verification matrix at the end"
                ]
            },
            "hierarchy": {"is_atomic": False, "composition_depth": 1, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "REFLECTION"},
                "context_policy": {"type": "SLIDING_WINDOW", "max_chars": 15000}
            },
            "planning": {
                "dynamic_planning": {
                    "enabled": True,
                    "planning_prompt": "For each critical claim in the input: (1) formulate a verification search query, (2) execute the search, (3) assess the verification evidence, (4) record verdict. Use web_search for verification queries. Process claims in order of importance to the research conclusion."
                },
                "loop_control": {"max_iterations": 15, "iteration_context_mode": "SUMMARIZED", "summary_every_n_iterations": 5}
            },
            "capabilities": {
                "tools": [{"tool_id": "web_search"}],
                "memory": {"enabled": True, "mode": "CORTEX", "cortex_config": {"auto_checkpoint": True}}
            },
            "governance": {"timeout_ms": 600000, "max_cost_usd": 2.00}
        }
    },
    {
        "key": "knowledge_synthesizer_skill",
        "payload": {
            "name": "deep-research-knowledge-synthesizer",
            "display_name": "Research Knowledge Synthesizer",
            "description": "Reads the complete CORTEX knowledge tree (all findings, verification results, source analyses) and synthesizes them into a coherent report. Generates the outline, writes each section, assembles the full document, and exports as PDF.",
            "goal": "Transform the accumulated CORTEX knowledge tree into a publication-quality research report. The report must tell a coherent story, not just list facts. Every section must build on previous ones.",
            "type": "SKILL",
            "version": "1.0.0",
            "status": "ACTIVE",
            "tags": ["deep-research", "synthesis", "report-writing", "output"],
            "identity": {
                "system_prompt": "You are a senior research writer and knowledge synthesizer. Your job: (1) Navigate the CORTEX knowledge tree to understand ALL accumulated findings, (2) Identify the key narrative threads and analytical insights, (3) Design a report outline that tells a coherent story, (4) Write each section with proper citations, (5) Ensure analytical depth — don't just summarize, ANALYZE. Your reports should contain original insights drawn from the intersection of multiple sources, not just a summary of each source.",
                "behavioral_constraints": [
                    "Read ALL nodes in the CORTEX knowledge tree before writing",
                    "The Executive Summary must be written LAST (after all sections)",
                    "Every factual claim must be cited with [Source, Date]",
                    "Include a 'Key Findings' section with 5-10 bullet points"
                ]
            },
            "hierarchy": {"is_atomic": False, "composition_depth": 1, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.5, "reasoning_mode": "CHAIN_OF_THOUGHT"},
                "context_policy": {"type": "FULL", "summarize_threshold": 30000},
                "review_mechanism": {
                    "enabled": True,
                    "review_prompt": "Review the report section for: (1) Factual accuracy — are all claims cited? (2) Analytical depth — does the section go beyond summarization? (3) Coherence — does it flow from the previous section? (4) Completeness — are there obvious gaps?",
                    "on_failure": "RETRY"
                }
            },
            "planning": {
                "static_plan": {
                    "enabled": True,
                    "steps": [
                        {
                            "step_id": "step_1",
                            "order": 1,
                            "name": "Synthesize Knowledge Tree",
                            "description": "Read all findings from the CORTEX working memory and synthesize key themes, narrative threads, and analytical insights",
                            "type": "ACTION",
                            "target": {"prompt_template": "Review all research findings and synthesize key themes:\n\n{{input}}"}
                        },
                        {
                            "step_id": "step_2",
                            "order": 2,
                            "name": "Generate Report Outline",
                            "description": "Create a detailed, hierarchical report outline with section titles, content guidance, and estimated word counts",
                            "type": "ACTION",
                            "target": {
                                "prompt_template": "Based on these synthesized themes:\n\n{{step_1}}\n\nGenerate a comprehensive report outline as a JSON array of sections with: title, subsections[], content_guidance, estimated_word_count",
                                "input_dependencies": ["step_1"]
                            }
                        },
                        {
                            "step_id": "step_3",
                            "order": 3,
                            "name": "Write Full Report",
                            "description": "Write each section of the report following the outline, with proper citations and analytical depth",
                            "type": "ACTION",
                            "target": {
                                "prompt_template": "Using this outline:\n\n{{step_2}}\n\nAnd these research findings:\n\n{{step_1}}\n\nWrite the complete research report. For each section, include:\n- Clear topic sentence stating the section thesis\n- Evidence paragraphs with inline citations [Source, Date]\n- Data integration (statistics, metrics, comparisons)\n- Analytical insight connecting to the broader research question\n\nWrite the Executive Summary LAST, after all other sections.",
                                "input_dependencies": ["step_1", "step_2"]
                            }
                        },
                        {
                            "step_id": "step_4",
                            "order": 4,
                            "name": "Generate PDF",
                            "description": "Export the final report as a professionally formatted PDF",
                            "type": "TOOL_CALL",
                            "target": {
                                "tool_id": "pdf_generator",
                                "prompt_template": "{{step_3}}",
                                "input_dependencies": ["step_3"]
                            }
                        }
                    ]
                },
                "dynamic_planning": {
                    "enabled": True,
                    "planning_prompt": "If sections are too long for a single LLM call, break them into subsections and write separately. If the report outline has more than 8 sections, write in batches of 3-4 sections."
                }
            },
            "capabilities": {
                "tools": [{"tool_id": "pdf_generator"}],
                "memory": {"enabled": True, "mode": "CORTEX", "cortex_config": {"auto_checkpoint": True, "context_budget_pct": 50}}
            },
            "governance": {"timeout_ms": 900000, "max_cost_usd": 5.00}
        }
    },
]


# ============================================================================
# Entity Definitions — Layer 3: AGENTs (2 entities)
# ============================================================================

AGENTS = [
    {
        "key": "research_director_agent",
        "payload": {
            "name": "deep-research-director",
            "display_name": "Research Director",
            "description": "Autonomous research agent that orchestrates the complete information gathering pipeline. Decomposes the research topic into queries, discovers sources, scrapes and analyzes them, verifies critical claims, and writes all findings to the CORTEX knowledge tree. Operates iteratively — performs multiple research waves with increasing depth.",
            "goal": "Gather the most comprehensive, verified, multi-source body of research knowledge possible on the given topic. Leave no stone unturned. Prioritize depth over breadth. Your output is a fully populated CORTEX knowledge tree — not a report (that's the Synthesizer's job).",
            "type": "AGENT",
            "version": "1.0.0",
            "status": "ACTIVE",
            "tags": ["deep-research", "research-agent", "director", "orchestrator"],
            "identity": {
                "system_prompt": "You are the Research Director — a relentless, thorough research investigator. Your methodology:\n\n## Wave 1: Broad Discovery\n- Decompose the topic into 8-12 search queries covering all dimensions\n- Execute searches and rank discovered sources\n- Scrape and analyze the top 8-10 sources\n\n## Wave 2: Deep Dive\n- Identify gaps in Wave 1 coverage\n- Generate targeted follow-up queries for underexplored areas\n- Scrape and analyze 5-8 additional sources\n\n## Wave 3: Verification & Synthesis\n- Extract the 10-15 most critical claims from all findings\n- Independently verify each claim via separate searches\n- Flag contradictions, contested claims, and data discrepancies\n- Write a comprehensive verification matrix\n\nAfter each wave, CHECKPOINT your progress to the CORTEX tree.\nYou are DONE when: (1) All major dimensions are covered, (2) Critical claims are verified, (3) Multiple perspectives are represented.",
                "behavioral_constraints": [
                    "Always perform at least 2 research waves before declaring completion",
                    "Never rely on a single source for any critical claim",
                    "Always include opposing viewpoints",
                    "Checkpoint after each wave to preserve progress",
                    "If a source scrape fails, note it and find alternatives"
                ]
            },
            "hierarchy": {"is_atomic": False, "composition_depth": 2, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "thinking", "temperature": 0.4, "reasoning_mode": "REFLECTION"},
                "retry_policy": {"max_retries": 3, "backoff_strategy": "EXPONENTIAL"},
                "context_policy": {
                    "type": "SLIDING_WINDOW",
                    "max_chars": 30000,
                    "summarize_threshold": 25000,
                    "preserve_keys": ["research_topic", "current_wave", "verification_matrix"]
                },
                "review_mechanism": {
                    "enabled": True,
                    "review_prompt": "Evaluate research completeness: (1) Are all topic dimensions covered? (2) Are there at least 3 sources per major claim? (3) Have opposing viewpoints been explored? (4) Is the verification matrix complete?",
                    "on_failure": "RETRY"
                }
            },
            "planning": {
                "dynamic_planning": {
                    "enabled": True,
                    "planning_prompt": "Plan a multi-wave research process:\n\nWave 1 — Broad Discovery: Decompose the topic into search queries → execute searches → discover and rank sources → scrape top sources → extract findings\n\nWave 2 — Deep Dive: Identify gaps → generate follow-up queries → search → scrape additional sources → extract findings\n\nWave 3 — Verification: Extract critical claims → verify each independently → build verification matrix\n\nUse these tools: web_search (search), scraper_tool (scrape URLs), headless_browser (JS-heavy pages).\nEvery wave must end with writing findings to the CORTEX tree.\nThe final step should produce a comprehensive summary of all findings, verified claims, and remaining gaps.",
                    "allowed_deviations": {
                        "can_add_steps": True,
                        "can_skip_optional_steps": True,
                        "can_reorder_steps": True,
                        "can_change_tools": True
                    },
                    "reconciliation_strategy": "DYNAMIC_PRIORITY"
                },
                "loop_control": {
                    "max_iterations": 3,
                    "iteration_context_mode": "SUMMARIZED",
                    "summary_every_n_iterations": 1
                }
            },
            "capabilities": {
                "tools": [
                    {"tool_id": "web_search"},
                    {"tool_id": "scraper_tool"},
                    {"tool_id": "headless_browser"}
                ],
                "memory": {
                    "enabled": True,
                    "mode": "CORTEX",
                    "cortex_config": {
                        "max_children": 12,
                        "page_size_tokens": 8000,
                        "context_budget_pct": 40,
                        "auto_checkpoint": True,
                        "resume_enabled": True
                    }
                },
                "context_engineering": {
                    "inject_cortex_viewport": True,
                    "inject_episodic_memory": True,
                    "inject_semantic_context": True,
                    "no_truncation": True
                }
            },
            "governance": {
                "timeout_ms": 1200000,
                "max_cost_usd": 8.00,
                "max_recursion_depth": 4,
                "execution_limits": {"max_tool_calls": 50}
            },
            "observability": {"log_level": "INFO", "log_thoughts": True, "track_cost": True}
        }
    },
    {
        "key": "report_synthesizer_agent",
        "payload": {
            "name": "deep-research-synthesizer",
            "display_name": "Report Synthesizer",
            "description": "Autonomous report synthesis agent. Reads the complete CORTEX knowledge tree populated by the Research Director, identifies narrative threads, generates a report outline, writes each section with proper citations, performs self-critique review, and exports the final PDF.",
            "goal": "Produce a world-class research report that: (1) Tells a coherent analytical narrative, not just a fact dump, (2) Cites every claim with source references, (3) Contains original analytical insights from cross-source synthesis, (4) Is formatted and structured for professional consumption.",
            "type": "AGENT",
            "version": "1.0.0",
            "status": "ACTIVE",
            "tags": ["deep-research", "synthesis-agent", "report-writer"],
            "identity": {
                "system_prompt": "You are the Report Synthesizer — a world-class research writer who transforms raw knowledge into compelling analysis.\n\n## Your Process:\n1. READ the entire CORTEX knowledge tree to understand all findings\n2. IDENTIFY narrative threads — what connects these findings?\n3. DESIGN the report outline — logical flow, proportional depth allocation\n4. WRITE each section — analytical, cited, insightful prose\n5. SELF-REVIEW each section against quality criteria\n6. WRITE the Executive Summary last (it must reflect the full report)\n7. EXPORT as PDF\n\n## Quality Standards:\n- Every paragraph must contain at least one specific data point or cited fact\n- Analysis > Description: Don't just state what happened — explain WHY it matters\n- Cross-reference findings: \"This aligns with [Source A] but contradicts [Source B]\"\n- Include implications: \"This suggests that...\", \"The key implication is...\"\n- Present contested claims fairly: \"[Source A] argues X, while [Source B] contends Y\"",
                "behavioral_constraints": [
                    "Read ALL CORTEX nodes before writing anything",
                    "Executive Summary written LAST",
                    "Every section ends with an analytical insight",
                    "Include a Sources/References section at the end",
                    "Self-review each major section before moving to the next"
                ]
            },
            "hierarchy": {"is_atomic": False, "composition_depth": 2, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.5, "reasoning_mode": "REFLECTION"},
                "context_policy": {"type": "FULL", "summarize_threshold": 30000, "preserve_keys": ["report_outline", "completed_sections"]},
                "review_mechanism": {
                    "enabled": True,
                    "review_prompt": "Review this report section critically: (1) Are all claims properly cited? (2) Does it contain analytical insight beyond summarization? (3) Does it flow logically? (4) Are there gaps in coverage? (5) Is the writing professional and precise?",
                    "success_criteria": [
                        {"criterion": "All factual claims have inline citations", "validation_type": "LLM_JUDGE", "validator": "Check for [Source, Date] patterns"},
                        {"criterion": "Section contains analytical insight, not just description", "validation_type": "LLM_JUDGE", "validator": "Look for analytical language"}
                    ],
                    "on_failure": "RETRY"
                }
            },
            "planning": {
                "dynamic_planning": {
                    "enabled": True,
                    "planning_prompt": "Plan the report synthesis process:\n1. Read all findings from the CORTEX knowledge tree (use previous step contexts)\n2. Synthesize key themes and narrative threads\n3. Generate a detailed report outline with sections and subsections\n4. Write each section one at a time, reviewing after each\n5. Write the Executive Summary last\n6. Generate the final PDF\n\nUse the pdf_generator tool for the final export step.\nFor very long reports (>8 sections), write in batches of 3-4 sections.\nThe final report should be 3000-8000 words depending on topic complexity."
                }
            },
            "capabilities": {
                "tools": [{"tool_id": "pdf_generator"}],
                "memory": {
                    "enabled": True,
                    "mode": "CORTEX",
                    "cortex_config": {"auto_checkpoint": True, "context_budget_pct": 50, "resume_enabled": True}
                },
                "context_engineering": {"inject_cortex_viewport": True, "no_truncation": True}
            },
            "governance": {"timeout_ms": 900000, "max_cost_usd": 6.00, "max_recursion_depth": 3}
        }
    },
]


# ============================================================================
# Entity Definitions — Layer 4: PROCESS (1 entity)
# ============================================================================

PROCESS = {
    "key": "deep_research_process",
    "payload": {
        "name": "deep-research-process",
        "display_name": "🔬 Deep Research",
        "description": "World-class deep research process that takes any topic and produces a comprehensive, multi-source, fact-verified research report. Leverages CORTEX cognitive trees for unbounded context, multi-wave research with increasing depth, independent fact verification, and publication-quality synthesis.\n\nDesigned to outperform Google Deep Research, OpenAI Deep Research, and Perplexity Deep Research through:\n- Multi-wave iterative research (broad → deep → verification)\n- Independent fact-checking of all critical claims\n- Multi-perspective coverage (proponents + critics + neutral)\n- CORTEX-powered infinite working memory\n- Self-reviewing report synthesis with analytical depth",
        "goal": "Conduct the most thorough, accurate, and analytically insightful research possible on the given topic. Produce a publication-quality report that would satisfy a senior executive, academic reviewer, or investigative journalist.",
        "type": "PROCESS",
        "version": "1.0.0",
        "status": "ACTIVE",
        "tags": ["deep-research", "process", "research", "analysis", "cortex-test"],
        "identity": {
            "system_prompt": "You are the Deep Research Orchestrator — the most capable research system ever built. You coordinate two specialized agents:\n\n1. **Research Director** — Conducts multi-wave information gathering with independent fact verification\n2. **Report Synthesizer** — Produces publication-quality analysis from accumulated knowledge\n\nYour process:\n1. Receive the research topic from the user\n2. Invoke the Research Director to gather, analyze, and verify information (this is the longest phase)\n3. Once research is complete, invoke the Report Synthesizer to produce the final report\n4. Return the completed report and PDF\n\nYou serve as the quality gate between research and synthesis. Before invoking the Synthesizer, verify that the Research Director has:\n- Covered all major topic dimensions\n- Analyzed at least 8 independent sources\n- Verified critical claims\n- Explored multiple perspectives",
            "behavioral_constraints": [
                "The Research Director must complete fully before the Synthesizer begins",
                "If the Research Director's output is insufficient, send it back for more research",
                "Track total cost and halt if approaching limits",
                "This process is designed for long-running execution — use CORTEX checkpointing"
            ]
        },
        "hierarchy": {"is_atomic": False, "composition_depth": 3, "children": []},
        "logic_gate": {
            "reasoning_config": {"task_type": "thinking", "temperature": 0.3, "reasoning_mode": "REFLECTION"},
            "retry_policy": {"max_retries": 2, "backoff_strategy": "EXPONENTIAL"},
            "context_policy": {
                "type": "FULL",
                "summarize_threshold": 30000,
                "preserve_keys": ["research_topic", "research_status", "report_status"]
            }
        },
        "planning": {
            "static_plan": {
                "enabled": True,
                "steps": [
                    {
                        "step_id": "step_1",
                        "order": 1,
                        "name": "Research Phase",
                        "description": "Invoke the Research Director agent to conduct multi-wave research: topic decomposition → source discovery → source analysis → fact verification. The Research Director will populate the CORTEX knowledge tree with all findings.",
                        "type": "CHILD_ENTITY_INVOCATION",
                        "target": {
                            "prompt_template": "{{input}}",
                            "input_dependencies": []
                        },
                        "required": True
                    },
                    {
                        "step_id": "step_2",
                        "order": 2,
                        "name": "Quality Gate",
                        "description": "Assess the completeness of the research phase. Verify that sufficient sources were analyzed, critical claims were verified, and multiple perspectives are represented. If insufficient, flag for additional research.",
                        "type": "ACTION",
                        "target": {
                            "prompt_template": "Evaluate the research completeness from the Research Director:\n\n{{step_1}}\n\nAssess: (1) Number of sources analyzed (need ≥8), (2) Verification status of critical claims, (3) Multi-perspective coverage, (4) Any major gaps. Output: PASS or NEEDS_MORE_RESEARCH with specific gaps.",
                            "input_dependencies": ["step_1"]
                        },
                        "required": True
                    },
                    {
                        "step_id": "step_3",
                        "order": 3,
                        "name": "Synthesis Phase",
                        "description": "Invoke the Report Synthesizer agent to transform accumulated CORTEX knowledge into a publication-quality research report with PDF export.",
                        "type": "CHILD_ENTITY_INVOCATION",
                        "target": {
                            "prompt_template": "Synthesize the research from the CORTEX knowledge tree into a comprehensive report. Research summary:\n\n{{step_1}}\n\nQuality assessment:\n\n{{step_2}}",
                            "input_dependencies": ["step_1", "step_2"]
                        },
                        "required": True
                    }
                ],
                "fallback_behavior": "ADAPTIVE"
            },
            "dynamic_planning": {
                "enabled": True,
                "planning_prompt": "If the Quality Gate returns NEEDS_MORE_RESEARCH, add additional research steps before synthesis. The Research Director should be re-invoked with the specific gaps identified."
            }
        },
        "capabilities": {
            "tools": [],
            "memory": {
                "enabled": True,
                "mode": "CORTEX",
                "cortex_config": {
                    "max_children": 12,
                    "page_size_tokens": 8000,
                    "context_budget_pct": 40,
                    "auto_checkpoint": True,
                    "resume_enabled": True
                }
            },
            "context_engineering": {
                "inject_cortex_viewport": True,
                "inject_episodic_memory": True,
                "no_truncation": True
            }
        },
        "governance": {
            "timeout_ms": 1800000,
            "max_cost_usd": 20.00,
            "max_recursion_depth": 5,
            "execution_limits": {"max_tool_calls": 100}
        },
        "observability": {"log_level": "INFO", "log_thoughts": True, "track_cost": True}
    }
}


# ============================================================================
# Hierarchy Linking — Update parents with child UUIDs
# ============================================================================

def link_hierarchy(client: APIClient):
    """Update parent entities to reference child UUIDs in hierarchy.children."""

    print("\n" + "=" * 60)
    print("Phase 3: Linking Entity Hierarchy")
    print("=" * 60)

    # Skills → link to Actions
    skill_action_map = {
        "query_decomposer_skill": [],  # Pure LLM, no child actions
        "source_discoverer_skill": ["web_search_action"],
        "source_analyzer_skill": ["page_scrape_action", "content_extract_action"],
        "fact_verifier_skill": ["fact_check_action"],
        "knowledge_synthesizer_skill": ["outline_generator_action", "section_writer_action", "pdf_export_action"],
    }

    for skill_key, action_keys in skill_action_map.items():
        if not action_keys:
            continue
        skill_id = ENTITY_IDS[skill_key]
        children = [
            {
                "child_id": ENTITY_IDS[ak],
                "child_type": "ACTION",
                "relationship": "SEQUENTIAL"
            }
            for ak in action_keys
        ]
        client.update_entity(skill_id, {
            "hierarchy": {
                "is_atomic": False,
                "composition_depth": 1,
                "children": children
            }
        })

    # Agents → link to Skills
    agent_skill_map = {
        "research_director_agent": [
            "query_decomposer_skill",
            "source_discoverer_skill",
            "source_analyzer_skill",
            "fact_verifier_skill",
        ],
        "report_synthesizer_agent": [
            "knowledge_synthesizer_skill",
        ],
    }

    for agent_key, skill_keys in agent_skill_map.items():
        agent_id = ENTITY_IDS[agent_key]
        children = [
            {
                "child_id": ENTITY_IDS[sk],
                "child_type": "SKILL",
                "relationship": "SEQUENTIAL"
            }
            for sk in skill_keys
        ]
        client.update_entity(agent_id, {
            "hierarchy": {
                "is_atomic": False,
                "composition_depth": 2,
                "children": children
            }
        })

    # Process → link to Agents + update CHILD_ENTITY_INVOCATION steps with entity_ids
    process_id = ENTITY_IDS["deep_research_process"]
    research_director_id = ENTITY_IDS["research_director_agent"]
    report_synthesizer_id = ENTITY_IDS["report_synthesizer_agent"]

    children = [
        {"child_id": research_director_id, "child_type": "AGENT", "relationship": "SEQUENTIAL"},
        {"child_id": report_synthesizer_id, "child_type": "AGENT", "relationship": "SEQUENTIAL"},
    ]

    # Update hierarchy AND planning steps to include entity_id references
    client.update_entity(process_id, {
        "hierarchy": {
            "is_atomic": False,
            "composition_depth": 3,
            "children": children
        },
        "planning": {
            "static_plan": {
                "enabled": True,
                "steps": [
                    {
                        "step_id": "step_1",
                        "order": 1,
                        "name": "Research Phase",
                        "description": "Invoke the Research Director agent to conduct multi-wave research.",
                        "type": "CHILD_ENTITY_INVOCATION",
                        "target": {
                            "entity_id": research_director_id,
                            "prompt_template": "{{input}}",
                            "input_dependencies": []
                        },
                        "required": True
                    },
                    {
                        "step_id": "step_2",
                        "order": 2,
                        "name": "Quality Gate",
                        "description": "Assess the completeness of the research phase.",
                        "type": "ACTION",
                        "target": {
                            "prompt_template": "Evaluate the research completeness from the Research Director:\n\n{{step_1}}\n\nAssess: (1) Number of sources analyzed (need ≥8), (2) Verification status of critical claims, (3) Multi-perspective coverage, (4) Any major gaps. Output: PASS or NEEDS_MORE_RESEARCH with specific gaps.",
                            "input_dependencies": ["step_1"]
                        },
                        "required": True
                    },
                    {
                        "step_id": "step_3",
                        "order": 3,
                        "name": "Synthesis Phase",
                        "description": "Invoke the Report Synthesizer agent to produce the final report.",
                        "type": "CHILD_ENTITY_INVOCATION",
                        "target": {
                            "entity_id": report_synthesizer_id,
                            "prompt_template": "Synthesize the research from the CORTEX knowledge tree into a comprehensive report. Research summary:\n\n{{step_1}}\n\nQuality assessment:\n\n{{step_2}}",
                            "input_dependencies": ["step_1", "step_2"]
                        },
                        "required": True
                    }
                ],
                "fallback_behavior": "ADAPTIVE"
            },
            "dynamic_planning": {
                "enabled": True,
                "planning_prompt": "If the Quality Gate returns NEEDS_MORE_RESEARCH, add additional research steps before synthesis. The Research Director should be re-invoked with the specific gaps identified."
            }
        }
    })


# ============================================================================
# Main — Create all entities and link hierarchy
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Create Deep Research entities via API")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API base URL")
    parser.add_argument("--token", default=AUTH_TOKEN, help="JWT auth token")
    parser.add_argument("--dry-run", action="store_true", help="Print payloads without creating")
    parser.add_argument("--execute", action="store_true", help="Also trigger a test execution")
    parser.add_argument("--topic", default="Impact of generative AI on the creative industries: economics, employment, and intellectual property", help="Research topic for test execution")
    args = parser.parse_args()

    if not args.token:
        print("❌ Error: Auth token is required.")
        print("   Set AUTH_TOKEN env var or pass --token")
        sys.exit(1)

    client = APIClient(args.base_url, args.token)

    # --- Phase 1: Create ACTIONs ---
    print("\n" + "=" * 60)
    print("Phase 1: Creating ACTIONs (Layer 1 — Atomic Operations)")
    print("=" * 60)
    for action_def in ACTIONS:
        key = action_def["key"]
        payload = action_def["payload"]
        if args.dry_run:
            print(f"  [DRY RUN] Would create: {payload['name']}")
            ENTITY_IDS[key] = f"dry-run-{key}"
            continue
        try:
            result = client.create_entity(payload)
            ENTITY_IDS[key] = result["id"]
            time.sleep(0.3)  # Rate limiting
        except Exception as e:
            print(f"  ❌ Failed to create {payload['name']}: {e}")
            sys.exit(1)

    # --- Phase 2: Create SKILLs ---
    print("\n" + "=" * 60)
    print("Phase 2: Creating SKILLs (Layer 2 — Composed Capabilities)")
    print("=" * 60)
    for skill_def in SKILLS:
        key = skill_def["key"]
        payload = skill_def["payload"]
        if args.dry_run:
            print(f"  [DRY RUN] Would create: {payload['name']}")
            ENTITY_IDS[key] = f"dry-run-{key}"
            continue
        try:
            result = client.create_entity(payload)
            ENTITY_IDS[key] = result["id"]
            time.sleep(0.3)
        except Exception as e:
            print(f"  ❌ Failed to create {payload['name']}: {e}")
            sys.exit(1)

    # --- Phase 3: Create AGENTs ---
    print("\n" + "=" * 60)
    print("Phase 3: Creating AGENTs (Layer 3 — Autonomous Specialists)")
    print("=" * 60)
    for agent_def in AGENTS:
        key = agent_def["key"]
        payload = agent_def["payload"]
        if args.dry_run:
            print(f"  [DRY RUN] Would create: {payload['name']}")
            ENTITY_IDS[key] = f"dry-run-{key}"
            continue
        try:
            result = client.create_entity(payload)
            ENTITY_IDS[key] = result["id"]
            time.sleep(0.3)
        except Exception as e:
            print(f"  ❌ Failed to create {payload['name']}: {e}")
            sys.exit(1)

    # --- Phase 4: Create PROCESS ---
    print("\n" + "=" * 60)
    print("Phase 4: Creating PROCESS (Layer 4 — Top-Level Orchestrator)")
    print("=" * 60)
    key = PROCESS["key"]
    payload = PROCESS["payload"]
    if args.dry_run:
        print(f"  [DRY RUN] Would create: {payload['name']}")
        ENTITY_IDS[key] = f"dry-run-{key}"
    else:
        try:
            result = client.create_entity(payload)
            ENTITY_IDS[key] = result["id"]
        except Exception as e:
            print(f"  ❌ Failed to create {payload['name']}: {e}")
            sys.exit(1)

    # --- Phase 5: Link Hierarchy ---
    if not args.dry_run:
        link_hierarchy(client)

    # --- Summary ---
    print("\n" + "=" * 60)
    print("✅ Deep Research Setup Complete!")
    print("=" * 60)
    print(f"\nTotal entities created: {len(ENTITY_IDS)}")
    print("\nEntity IDs:")
    for key, entity_id in ENTITY_IDS.items():
        print(f"  {key}: {entity_id}")

    # Save entity IDs for reference
    output_path = os.path.join(os.path.dirname(__file__), "entity_ids.json")
    with open(output_path, "w") as f:
        json.dump(ENTITY_IDS, f, indent=2)
    print(f"\nEntity IDs saved to: {output_path}")

    # --- Optional: Trigger test execution ---
    if args.execute and not args.dry_run:
        print("\n" + "=" * 60)
        print("Phase 5: Triggering Test Execution")
        print("=" * 60)
        process_id = ENTITY_IDS["deep_research_process"]
        input_data = {"input": args.topic}
        print(f"  Topic: {args.topic}")
        print(f"  Process ID: {process_id}")
        try:
            execution = client.trigger_execution(process_id, input_data)
            print(f"\n  🎯 Execution ID: {execution['id']}")
            print(f"  Status: {execution['status']}")
            print(f"\n  Monitor at: {args.base_url}/ai/executions/{execution['id']}")
        except Exception as e:
            print(f"  ❌ Execution failed: {e}")


if __name__ == "__main__":
    main()
