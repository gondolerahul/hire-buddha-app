#!/usr/bin/env python3
"""
Create Deep Research entities from scratch on a clean DB.
Assumes all old entities have been deleted already.
"""

import json, os, sys, time, requests
from datetime import datetime, timedelta, timezone
from jose import jwt

BASE_URL = "http://localhost:8000/api/v1"
SECRET_KEY = "dev_secret_key_change_in_production"

token_data = {
    "sub": "admin@hirebuddha.com",
    "company_id": "699098ce-a31c-42ef-b13b-2780c7decb9d",
    "exp": datetime.now(timezone.utc) + timedelta(hours=24),
}
TOKEN = jwt.encode(token_data, SECRET_KEY, algorithm="HS256")

HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}
IDS = {}

def create(payload):
    r = requests.post(f"{BASE_URL}/ai/entities", json=payload, headers=HEADERS)
    if r.status_code not in (200, 201):
        print(f"  ❌ FAILED ({r.status_code}): {r.text[:500]}")
        r.raise_for_status()
    d = r.json()
    print(f"  ✅ {d['name']} → {d['id']}")
    return d

def update(eid, payload):
    r = requests.put(f"{BASE_URL}/ai/entities/{eid}", json=payload, headers=HEADERS)
    if r.status_code not in (200, 201):
        print(f"  ❌ UPDATE FAILED ({r.status_code}): {r.text[:500]}")
        r.raise_for_status()
    d = r.json()
    print(f"  ✅ Updated: {d['name']}")
    return d

# ===================== VERIFY AUTH =====================
print("Verifying auth...")
r = requests.get(f"{BASE_URL}/ai/entities", headers=HEADERS)
assert r.status_code == 200, f"Auth failed: {r.status_code}"
print(f"  OK ({len(r.json())} entities exist)")

# ===================== LAYER 1: ACTIONS (7) =====================
print("\n== Creating ACTIONs (7) ==")

d = create({"name":"deep-research-web-search","display_name":"Deep Research Web Search","description":"Executes a targeted web search query using SerpAPI/DuckDuckGo and returns structured results.","goal":"Find the most relevant, authoritative web results for a given search query.","type":"ACTION","version":"1.0.0","status":"ACTIVE","tags":["deep-research","search","web"],"identity":{"system_prompt":"You are a precision web search specialist. Always prioritize: (1) Primary sources, (2) Academic sources, (3) Authoritative journalism, (4) Expert analysis.","behavioral_constraints":["Never fabricate search results or URLs","Always preserve exact URLs","Flag outdated results","Include publication dates"]},"hierarchy":{"is_atomic":True,"composition_depth":0,"children":[]},"logic_gate":{"reasoning_config":{"task_type":"text_generation","temperature":0.2,"reasoning_mode":"REACT"},"retry_policy":{"max_retries":2,"backoff_strategy":"EXPONENTIAL","retry_on":["TOOL_FAILURE","TIMEOUT"]},"context_policy":{"type":"EXPLICIT","explicit_keys":["input","query"],"summarize_threshold":8000}},"planning":{"static_plan":{"enabled":True,"steps":[{"step_id":"step_1","order":1,"name":"Execute Web Search","description":"Run the web search query","type":"TOOL_CALL","target":{"tool_id":"web_search","prompt_template":"{{input}}","input_dependencies":[]},"required":True}]},"dynamic_planning":{"enabled":False}},"capabilities":{"tools":[{"tool_id":"web_search"}],"memory":{"enabled":True,"mode":"CORTEX"},"context_engineering":{"inject_cortex_viewport":True}},"governance":{"timeout_ms":30000,"max_cost_usd":0.10},"io_contract":{"input_schema":{"type":"object","properties":{"query":{"type":"string","description":"The search query"}},"required":["query"]},"output_schema":{"type":"object","properties":{"results":{"type":"array","description":"Search results"}}}}})
IDS["web_search_action"] = d["id"]; time.sleep(0.3)

d = create({"name":"deep-research-page-scrape","display_name":"Deep Research Page Scraper","description":"Scrapes a web page URL and returns clean markdown content.","goal":"Extract clean text content from a web page, preserving structure.","type":"ACTION","version":"1.0.0","status":"ACTIVE","tags":["deep-research","scraping"],"identity":{"system_prompt":"You are a web content extraction specialist. Extract the main content while preserving structure.","behavioral_constraints":["Never modify factual content","Preserve data tables","Note truncated content"]},"hierarchy":{"is_atomic":True,"composition_depth":0,"children":[]},"logic_gate":{"reasoning_config":{"task_type":"text_generation","temperature":0.1,"reasoning_mode":"REACT"},"retry_policy":{"max_retries":3,"backoff_strategy":"EXPONENTIAL","retry_on":["TOOL_FAILURE","TIMEOUT"]},"context_policy":{"type":"EXPLICIT","explicit_keys":["input","url"]}},"planning":{"static_plan":{"enabled":True,"steps":[{"step_id":"step_1","order":1,"name":"Scrape URL Content","description":"Scrape using the scraper tool","type":"TOOL_CALL","target":{"tool_id":"scraper_tool","prompt_template":"{{input}}"}}]}},"capabilities":{"tools":[{"tool_id":"scraper_tool"}],"memory":{"enabled":True,"mode":"CORTEX"}},"governance":{"timeout_ms":60000,"max_cost_usd":0.05}})
IDS["page_scrape_action"] = d["id"]; time.sleep(0.3)

d = create({"name":"deep-research-content-extract","display_name":"Deep Research Content Extractor","description":"Analyzes scraped content and extracts key claims, statistics, quotes, entities, and credibility assessment.","goal":"Transform raw web content into structured, citation-ready research notes.","type":"ACTION","version":"1.0.0","status":"ACTIVE","tags":["deep-research","extraction","analysis"],"identity":{"system_prompt":"You are a research analyst. Extract: (1) KEY CLAIMS, (2) STATISTICS, (3) QUOTES, (4) ENTITIES, (5) CREDIBILITY. Output structured JSON.","behavioral_constraints":["Never infer unstated statistics","Always attribute claims","Distinguish facts/claims/opinions","Flag contradictions"]},"hierarchy":{"is_atomic":True,"composition_depth":0,"children":[]},"logic_gate":{"reasoning_config":{"task_type":"text_generation","temperature":0.2,"reasoning_mode":"CHAIN_OF_THOUGHT"},"context_policy":{"type":"FULL","summarize_threshold":15000}},"planning":{"static_plan":{"enabled":True,"steps":[{"step_id":"step_1","order":1,"name":"Extract Structured Information","description":"Analyze and extract structured info","type":"ACTION","target":{"prompt_template":"Analyze this content and extract structured research information:\n\n{{input}}"}}]}},"capabilities":{"tools":[],"memory":{"enabled":True,"mode":"CORTEX"}},"governance":{"timeout_ms":60000,"max_cost_usd":0.15}})
IDS["content_extract_action"] = d["id"]; time.sleep(0.3)

d = create({"name":"deep-research-fact-check","display_name":"Deep Research Fact Checker","description":"Verifies claims against multiple independent sources via web search.","goal":"Independently verify claims. Produce verdict: VERIFIED/PARTIALLY_VERIFIED/UNVERIFIED/CONTRADICTED.","type":"ACTION","version":"1.0.0","status":"ACTIVE","tags":["deep-research","fact-checking","verification"],"identity":{"system_prompt":"You are a rigorous fact-checker. For each claim: (1) Search for corroboration, (2) Identify contradictions, (3) Note recency/reliability, (4) Assign verdict. Show verification chain.","behavioral_constraints":["Need 2+ sources for VERIFIED","Primary > secondary sources","Note temporal limitations","Flag unfalsifiable claims"]},"hierarchy":{"is_atomic":True,"composition_depth":0,"children":[]},"logic_gate":{"reasoning_config":{"task_type":"text_generation","temperature":0.1,"reasoning_mode":"REFLECTION"},"retry_policy":{"max_retries":2,"backoff_strategy":"LINEAR"}},"planning":{"static_plan":{"enabled":True,"steps":[{"step_id":"step_1","order":1,"name":"Search for Verification","description":"Search for confirming/denying sources","type":"TOOL_CALL","target":{"tool_id":"web_search","prompt_template":"verify: {{input}}"}},{"step_id":"step_2","order":2,"name":"Assess Evidence","description":"Produce verification verdict","type":"ACTION","target":{"prompt_template":"Based on {{step_1}}, verify:\n\nCLAIM: {{input}}\n\nProduce verdict with supporting/contradicting sources, confidence, caveats.","input_dependencies":["step_1"]}}]}},"capabilities":{"tools":[{"tool_id":"web_search"}],"memory":{"enabled":True,"mode":"CORTEX"}},"governance":{"timeout_ms":90000,"max_cost_usd":0.20}})
IDS["fact_check_action"] = d["id"]; time.sleep(0.3)

d = create({"name":"deep-research-section-writer","display_name":"Deep Research Section Writer","description":"Writes publication-quality report sections from structured research findings.","goal":"Transform findings into compelling, well-structured, properly cited report sections.","type":"ACTION","version":"1.0.0","status":"ACTIVE","tags":["deep-research","writing","report"],"identity":{"system_prompt":"You are a senior research writer producing COMPREHENSIVE, PUBLICATION-QUALITY reports.\n\n## MANDATORY REQUIREMENTS:\n- Minimum 5,000 words, target 6,000-8,000 words\n- Every section MUST have 3+ paragraphs with specific data points\n- Every factual claim MUST have an inline citation [Source Name, Date]\n- Include: Executive Summary, Methodology, 5-8 major analytical sections, each with 2-4 subsections, Conclusions, References\n- ANALYZE don't just summarize — provide original insights, cross-references, implications\n- Include specific numbers, statistics, percentages, and comparisons\n- Each section ends with a KEY INSIGHT callout\n- Include a Sources/References section at the end listing all cited sources\n\n## QUALITY STANDARDS:\n- Academic/consulting report quality\n- No filler text or generic statements\n- Specific data over qualitative assessments\n- Consistent professional tone throughout\n- Logical flow between sections with transition paragraphs","behavioral_constraints":["Every claim must be cited with [Source, Date]","No filler text or generic padding","Specific numbers over qualifiers","Consistent professional tone","Minimum 5000 words","Include at least 5 major sections with subsections","End each section with KEY INSIGHT","Include References section"]},"hierarchy":{"is_atomic":True,"composition_depth":0,"children":[]},"logic_gate":{"reasoning_config":{"task_type":"text_generation","temperature":0.5,"reasoning_mode":"CHAIN_OF_THOUGHT"},"context_policy":{"type":"FULL","summarize_threshold":50000}},"planning":{"static_plan":{"enabled":True,"steps":[{"step_id":"step_1","order":1,"name":"Write Section","description":"Write publication-quality section","type":"ACTION","target":{"prompt_template":"{{input}}"}}]}},"capabilities":{"tools":[],"memory":{"enabled":True,"mode":"CORTEX"}},"governance":{"timeout_ms":300000,"max_cost_usd":0.50}})
IDS["section_writer_action"] = d["id"]; time.sleep(0.3)

d = create({"name":"deep-research-outline-generator","display_name":"Deep Research Outline Generator","description":"Generates detailed hierarchical report outlines based on research findings.","goal":"Create a comprehensive report outline ensuring complete topic coverage.","type":"ACTION","version":"1.0.0","status":"ACTIVE","tags":["deep-research","planning","outline"],"identity":{"system_prompt":"You are a research report architect. Design outlines: (1) Comprehensive, (2) Logical flow, (3) Proportional depth, (4) Content guidance. Output JSON array.","behavioral_constraints":["Include Executive Summary","Include Methodology section","3-7 subsections per major section"]},"hierarchy":{"is_atomic":True,"composition_depth":0,"children":[]},"logic_gate":{"reasoning_config":{"task_type":"thinking","temperature":0.4,"reasoning_mode":"TREE_OF_THOUGHTS"}},"capabilities":{"tools":[],"memory":{"enabled":True,"mode":"CORTEX"}},"governance":{"timeout_ms":90000,"max_cost_usd":0.20}})
IDS["outline_generator_action"] = d["id"]; time.sleep(0.3)

d = create({"name":"deep-research-pdf-export","display_name":"Deep Research PDF Exporter","description":"Generates professionally formatted PDF documents from report content.","goal":"Produce a publication-ready PDF.","type":"ACTION","version":"1.0.0","status":"ACTIVE","tags":["deep-research","pdf","export"],"identity":{"system_prompt":"You are a document formatting specialist. Format reports into professional PDFs with headers, page numbers, TOC, citations.","behavioral_constraints":["Preserve citations","Maintain heading hierarchy","Include page numbers and TOC"]},"hierarchy":{"is_atomic":True,"composition_depth":0,"children":[]},"logic_gate":{"reasoning_config":{"task_type":"text_generation","temperature":0.1,"reasoning_mode":"REACT"}},"planning":{"static_plan":{"enabled":True,"steps":[{"step_id":"step_1","order":1,"name":"Generate PDF","description":"Generate PDF from report content","type":"TOOL_CALL","target":{"tool_id":"pdf_generator","prompt_template":"{{input}}"}}]}},"capabilities":{"tools":[{"tool_id":"pdf_generator"}],"memory":{"enabled":True,"mode":"CORTEX"}},"governance":{"timeout_ms":120000,"max_cost_usd":0.10}})
IDS["pdf_export_action"] = d["id"]; time.sleep(0.3)

# ===================== LAYER 2: SKILLS (5) =====================
print("\n== Creating SKILLs (5) ==")

d = create({"name":"deep-research-query-decomposer","display_name":"Research Query Decomposer","description":"Decomposes broad research topics into 5-15 targeted, non-overlapping search queries.","goal":"Generate comprehensive, multi-perspective search queries for the research topic.","type":"SKILL","version":"1.0.0","status":"ACTIVE","tags":["deep-research","query-planning"],"identity":{"system_prompt":"You are a research query strategist using: TAXONOMIC DECOMPOSITION, PERSPECTIVE TRIANGULATION, SPECIFICITY GRADIENT, TEMPORAL SPANNING, SOURCE TARGETING. Output JSON array of query objects.","behavioral_constraints":["5-15 queries","Non-overlapping","2+ opposing viewpoint queries","1+ quantitative data query"]},"hierarchy":{"is_atomic":False,"composition_depth":1,"children":[]},"logic_gate":{"reasoning_config":{"task_type":"thinking","temperature":0.5,"reasoning_mode":"TREE_OF_THOUGHTS"},"context_policy":{"type":"FULL","summarize_threshold":12000}},"planning":{"static_plan":{"enabled":True,"steps":[{"step_id":"step_1","order":1,"name":"Analyze Topic","description":"Identify key dimensions","type":"ACTION","target":{"prompt_template":"Analyze this research topic:\n\nTOPIC: {{input}}\n\nIdentify: core concepts, stakeholders, timeline, metrics, perspectives, adjacent topics"}},{"step_id":"step_2","order":2,"name":"Generate Queries","description":"Generate 5-15 search queries","type":"ACTION","target":{"prompt_template":"Based on:\n\n{{step_1}}\n\nGenerate 5-15 optimal search queries as JSON array.","input_dependencies":["step_1"]}}]},"dynamic_planning":{"enabled":False}},"capabilities":{"tools":[],"memory":{"enabled":True,"mode":"CORTEX"}},"governance":{"timeout_ms":120000,"max_cost_usd":0.30}})
IDS["query_decomposer_skill"] = d["id"]; time.sleep(0.3)

d = create({"name":"deep-research-source-discoverer","display_name":"Research Source Discoverer","description":"Executes search queries, deduplicates results, ranks sources by authority and relevance.","goal":"Discover and rank the most authoritative, relevant sources.","type":"SKILL","version":"1.0.0","status":"ACTIVE","tags":["deep-research","source-discovery"],"identity":{"system_prompt":"You are a research librarian. Evaluate sources by: authority, recency, depth, uniqueness, bias. Produce ranked deduplicated list.","behavioral_constraints":["Execute ALL queries","Deduplicate URLs","3+ source types","Flag biased sources"]},"hierarchy":{"is_atomic":False,"composition_depth":1,"children":[]},"logic_gate":{"reasoning_config":{"task_type":"text_generation","temperature":0.3,"reasoning_mode":"REACT"},"context_policy":{"type":"SLIDING_WINDOW","max_chars":20000},"retry_policy":{"max_retries":2,"backoff_strategy":"EXPONENTIAL"}},"planning":{"static_plan":{"enabled":True,"steps":[{"step_id":"step_1","order":1,"name":"Execute Searches","description":"Execute all search queries","type":"TOOL_CALL","target":{"tool_id":"web_search","prompt_template":"{{input}}"}},{"step_id":"step_2","order":2,"name":"Rank Sources","description":"Deduplicate, rank, select top 10-15","type":"ACTION","target":{"prompt_template":"Given results:\n\n{{step_1}}\n\nProduce ranked, deduplicated source list. Top 10-15 for scraping.","input_dependencies":["step_1"]}}]},"dynamic_planning":{"enabled":True,"planning_prompt":"If results insufficient, generate additional queries."}},"capabilities":{"tools":[{"tool_id":"web_search"}],"memory":{"enabled":True,"mode":"CORTEX"}},"governance":{"timeout_ms":300000,"max_cost_usd":1.00}})
IDS["source_discoverer_skill"] = d["id"]; time.sleep(0.3)

d = create({"name":"deep-research-source-analyzer","display_name":"Research Source Analyzer","description":"Scrapes sources, extracts claims/statistics/quotes, assesses credibility, writes to CORTEX.","goal":"Transform raw web sources into structured, citation-ready research knowledge.","type":"SKILL","version":"1.0.0","status":"ACTIVE","tags":["deep-research","source-analysis"],"identity":{"system_prompt":"You are a deep research analyst. For each URL: (1) scrape, (2) extract claims/stats/quotes, (3) assess credibility, (4) cross-reference, (5) write to CORTEX.","behavioral_constraints":["Process one at a time","Write after each source","Track corroboration","Stop after 10 or diminishing returns"]},"hierarchy":{"is_atomic":False,"composition_depth":1,"children":[]},"logic_gate":{"reasoning_config":{"task_type":"text_generation","temperature":0.2,"reasoning_mode":"CHAIN_OF_THOUGHT"},"context_policy":{"type":"SLIDING_WINDOW","max_chars":25000,"summarize_threshold":20000}},"planning":{"static_plan":{"enabled":True,"steps":[{"step_id":"step_1","order":1,"name":"Scrape Source","description":"Scrape full content from priority source","type":"TOOL_CALL","target":{"tool_id":"scraper_tool","prompt_template":"{{input}}"}},{"step_id":"step_2","order":2,"name":"Extract Info","description":"Extract key claims, stats, quotes","type":"ACTION","target":{"prompt_template":"Analyze:\n\n{{step_1}}\n\nExtract: KEY_CLAIMS, STATISTICS, QUOTES, ENTITIES, CREDIBILITY (1-5)","input_dependencies":["step_1"]}}]},"dynamic_planning":{"enabled":True,"planning_prompt":"Iterate through URLs. For each: scrape, analyze, continue. Skip failures."},"loop_control":{"max_iterations":12,"iteration_context_mode":"SUMMARIZED","summary_every_n_iterations":3}},"capabilities":{"tools":[{"tool_id":"scraper_tool"},{"tool_id":"headless_browser"},{"tool_id":"web_search"}],"memory":{"enabled":True,"mode":"CORTEX","cortex_config":{"auto_checkpoint":True,"context_budget_pct":40}}},"governance":{"timeout_ms":600000,"max_cost_usd":3.00}})
IDS["source_analyzer_skill"] = d["id"]; time.sleep(0.3)

d = create({"name":"deep-research-fact-verifier","display_name":"Research Fact Verification Engine","description":"Systematically verifies critical claims against independent sources. Produces verification matrix.","goal":"Ensure factual accuracy by verifying every critical claim.","type":"SKILL","version":"1.0.0","status":"ACTIVE","tags":["deep-research","fact-checking","quality"],"identity":{"system_prompt":"You are a senior fact-checker. NO claim in the report without independent verification. 3-source verification protocol. Track in matrix.","behavioral_constraints":["Verify 10+ critical claims","2+ independent sources each","Flag single-source claims","Produce verification matrix"]},"hierarchy":{"is_atomic":False,"composition_depth":1,"children":[]},"logic_gate":{"reasoning_config":{"task_type":"text_generation","temperature":0.1,"reasoning_mode":"REFLECTION"},"context_policy":{"type":"SLIDING_WINDOW","max_chars":15000}},"planning":{"dynamic_planning":{"enabled":True,"planning_prompt":"For each claim: (1) formulate query, (2) search, (3) assess evidence, (4) record verdict."},"loop_control":{"max_iterations":15,"iteration_context_mode":"SUMMARIZED","summary_every_n_iterations":5}},"capabilities":{"tools":[{"tool_id":"web_search"}],"memory":{"enabled":True,"mode":"CORTEX","cortex_config":{"auto_checkpoint":True}}},"governance":{"timeout_ms":600000,"max_cost_usd":2.00}})
IDS["fact_verifier_skill"] = d["id"]; time.sleep(0.3)

d = create({"name":"deep-research-knowledge-synthesizer","display_name":"Research Knowledge Synthesizer","description":"Reads CORTEX knowledge tree and synthesizes into report with outline, sections, PDF export.","goal":"Transform CORTEX knowledge into a publication-quality research report.","type":"SKILL","version":"1.0.0","status":"ACTIVE","tags":["deep-research","synthesis","report-writing"],"identity":{"system_prompt":"You are a senior research writer. (1) Navigate CORTEX, (2) Identify threads, (3) Design outline, (4) Write sections with citations, (5) ANALYZE don't summarize.","behavioral_constraints":["Read ALL nodes first","Executive Summary LAST","Every claim cited","Include Key Findings section"]},"hierarchy":{"is_atomic":False,"composition_depth":1,"children":[]},"logic_gate":{"reasoning_config":{"task_type":"text_generation","temperature":0.5,"reasoning_mode":"CHAIN_OF_THOUGHT"},"context_policy":{"type":"FULL","summarize_threshold":30000},"review_mechanism":{"enabled":True,"review_prompt":"Review for accuracy, depth, coherence, completeness.","on_failure":"RETRY"}},"planning":{"static_plan":{"enabled":True,"steps":[{"step_id":"step_1","order":1,"name":"Synthesize Knowledge","description":"Read CORTEX and synthesize themes","type":"ACTION","target":{"prompt_template":"Review all findings and synthesize key themes:\n\n{{input}}"}},{"step_id":"step_2","order":2,"name":"Generate Outline","description":"Create report outline","type":"ACTION","target":{"prompt_template":"Based on themes:\n\n{{step_1}}\n\nGenerate report outline as JSON array.","input_dependencies":["step_1"]}},{"step_id":"step_3","order":3,"name":"Write Report","description":"Write full report with citations","type":"ACTION","target":{"prompt_template":"Using outline:\n\n{{step_2}}\n\nAnd findings:\n\n{{step_1}}\n\nWrite complete research report. Executive Summary LAST.","input_dependencies":["step_1","step_2"]}},{"step_id":"step_4","order":4,"name":"Generate PDF","description":"Export as PDF","type":"TOOL_CALL","target":{"tool_id":"pdf_generator","prompt_template":"{{step_3}}","input_dependencies":["step_3"]}}]},"dynamic_planning":{"enabled":True,"planning_prompt":"Break long sections into subsections."}},"capabilities":{"tools":[{"tool_id":"pdf_generator"}],"memory":{"enabled":True,"mode":"CORTEX","cortex_config":{"auto_checkpoint":True,"context_budget_pct":50}}},"governance":{"timeout_ms":900000,"max_cost_usd":5.00}})
IDS["knowledge_synthesizer_skill"] = d["id"]; time.sleep(0.3)

# ===================== LAYER 3: AGENTS (2) =====================
print("\n== Creating AGENTs (2) ==")

d = create({"name":"deep-research-director","display_name":"Research Director","description":"Autonomous research agent orchestrating multi-wave information gathering with fact verification.","goal":"Gather comprehensive, verified, multi-source research knowledge.","type":"AGENT","version":"1.0.0","status":"ACTIVE","tags":["deep-research","research-agent","director"],"identity":{"system_prompt":"You are the Research Director.\n\n## Wave 1: Broad Discovery\n- Decompose into 8-12 queries → search → rank sources → scrape top 8-10\n\n## Wave 2: Deep Dive\n- Identify gaps → follow-up queries → scrape 5-8 more\n\n## Wave 3: Verification\n- Extract 10-15 critical claims → verify each → build matrix\n\nCHECKPOINT after each wave.","behavioral_constraints":["2+ research waves","Multiple sources per claim","Include opposing viewpoints","Checkpoint after each wave","Note & work around scrape failures"]},"hierarchy":{"is_atomic":False,"composition_depth":2,"children":[]},"logic_gate":{"reasoning_config":{"task_type":"thinking","temperature":0.4,"reasoning_mode":"REFLECTION"},"retry_policy":{"max_retries":3,"backoff_strategy":"EXPONENTIAL"},"context_policy":{"type":"SLIDING_WINDOW","max_chars":30000,"summarize_threshold":25000,"preserve_keys":["research_topic","current_wave","verification_matrix"]},"review_mechanism":{"enabled":True,"review_prompt":"Evaluate: (1) All dimensions covered? (2) 3+ sources/claim? (3) Opposing viewpoints? (4) Verification complete?","on_failure":"RETRY"}},"planning":{"dynamic_planning":{"enabled":True,"planning_prompt":"Multi-wave research:\nWave 1: decompose → search → rank → scrape → extract\nWave 2: gaps → follow-up queries → scrape more → extract\nWave 3: critical claims → verify → matrix\nTools: web_search, scraper_tool, headless_browser. CHECKPOINT each wave.","allowed_deviations":{"can_add_steps":True,"can_skip_optional_steps":True,"can_reorder_steps":True,"can_change_tools":True},"reconciliation_strategy":"DYNAMIC_PRIORITY"},"loop_control":{"max_iterations":3,"iteration_context_mode":"SUMMARIZED","summary_every_n_iterations":1}},"capabilities":{"tools":[{"tool_id":"web_search"},{"tool_id":"scraper_tool"},{"tool_id":"headless_browser"}],"memory":{"enabled":True,"mode":"CORTEX","cortex_config":{"max_children":12,"page_size_tokens":8000,"context_budget_pct":40,"auto_checkpoint":True,"resume_enabled":True}},"context_engineering":{"inject_cortex_viewport":True,"inject_episodic_memory":True,"inject_semantic_context":True,"no_truncation":True}},"governance":{"timeout_ms":1200000,"max_cost_usd":8.00,"max_recursion_depth":4,"execution_limits":{"max_tool_calls":50}},"observability":{"log_level":"INFO","log_thoughts":True,"track_cost":True}})
IDS["research_director_agent"] = d["id"]; time.sleep(0.3)

d = create({"name":"deep-research-synthesizer","display_name":"Report Synthesizer","description":"Reads CORTEX knowledge tree, identifies narrative threads, writes each section, reviews, exports PDF.","goal":"Produce world-class research report with analytical narrative, citations, and original insights.","type":"AGENT","version":"1.0.0","status":"ACTIVE","tags":["deep-research","synthesis-agent","report-writer"],"identity":{"system_prompt":"You are the Report Synthesizer.\n\n1. READ entire CORTEX tree\n2. IDENTIFY narrative threads\n3. DESIGN outline\n4. WRITE each section, review after each\n5. Executive Summary LAST\n6. EXPORT PDF\n\nQuality: every paragraph has data/citations. Analysis > Description. Cross-reference. Include implications.","behavioral_constraints":["Read ALL CORTEX nodes first","Executive Summary LAST","Each section ends with insight","Include Sources/References","Self-review each section"]},"hierarchy":{"is_atomic":False,"composition_depth":2,"children":[]},"logic_gate":{"reasoning_config":{"task_type":"text_generation","temperature":0.5,"reasoning_mode":"REFLECTION","model_name":"gemini-3.1-pro-preview"},"context_policy":{"type":"FULL","summarize_threshold":30000,"preserve_keys":["report_outline","completed_sections"]},"review_mechanism":{"enabled":True,"review_prompt":"Review: (1) Claims cited? (2) Analytical insight? (3) Logical flow? (4) Gaps? (5) Professional?","success_criteria":[{"criterion":"All factual claims have inline citations","validation_type":"LLM_JUDGE","validator":"Check for [Source, Date] citation patterns"},{"criterion":"Contains analytical insight beyond summarization","validation_type":"LLM_JUDGE","validator":"Look for analytical language and original insights"}],"on_failure":"RETRY"}},"planning":{"dynamic_planning":{"enabled":True,"planning_prompt":"1. Read all CORTEX findings\n2. Synthesize themes\n3. Generate outline\n4. Write sections, review each\n5. Executive Summary last\n6. Generate PDF\n\nUse pdf_generator. Target: 3000-8000 words."}},"capabilities":{"tools":[{"tool_id":"pdf_generator"}],"memory":{"enabled":True,"mode":"CORTEX","cortex_config":{"auto_checkpoint":True,"context_budget_pct":50,"resume_enabled":True}},"context_engineering":{"inject_cortex_viewport":True,"no_truncation":True}},"governance":{"timeout_ms":900000,"max_cost_usd":6.00,"max_recursion_depth":3}})
IDS["report_synthesizer_agent"] = d["id"]; time.sleep(0.3)

# ===================== LAYER 4: PROCESS (1) =====================
print("\n== Creating PROCESS (1) ==")

rd_id = IDS["research_director_agent"]
rs_id = IDS["report_synthesizer_agent"]

d = create({"name":"deep-research-process","display_name":"🔬 Deep Research","description":"World-class deep research process. Multi-wave research, fact verification, CORTEX memory, publication-quality synthesis.","goal":"Conduct thorough, accurate, insightful research and produce a publication-quality report.","type":"PROCESS","version":"1.0.0","status":"ACTIVE","tags":["deep-research","process","research","cortex-test"],"identity":{"system_prompt":"You are the Deep Research Orchestrator. You coordinate:\n1. Research Director — multi-wave information gathering + fact verification\n2. Report Synthesizer — publication-quality analysis\n\nProcess: receive topic → Research Director → quality gate → Report Synthesizer → return report+PDF","behavioral_constraints":["Research Director must complete before Synthesizer","Send back for more research if insufficient","Track cost, halt if approaching limits","Use CORTEX checkpointing"]},"hierarchy":{"is_atomic":False,"composition_depth":3,"children":[{"child_id":rd_id,"child_type":"AGENT","relationship":"SEQUENTIAL"},{"child_id":rs_id,"child_type":"AGENT","relationship":"SEQUENTIAL"}]},"logic_gate":{"reasoning_config":{"task_type":"thinking","temperature":0.3,"reasoning_mode":"REFLECTION"},"retry_policy":{"max_retries":2,"backoff_strategy":"EXPONENTIAL"},"context_policy":{"type":"FULL","summarize_threshold":30000,"preserve_keys":["research_topic","research_status","report_status"]}},"planning":{"static_plan":{"enabled":True,"steps":[{"step_id":"step_1","order":1,"name":"Research Phase","description":"Invoke Research Director for multi-wave research.","type":"CHILD_ENTITY_INVOCATION","target":{"entity_id":rd_id,"prompt_template":"{{input}}","input_dependencies":[]},"required":True},{"step_id":"step_2","order":2,"name":"Quality Gate","description":"Assess research completeness.","type":"ACTION","target":{"prompt_template":"Evaluate research completeness:\n\n{{step_1}}\n\nAssess: (1) Sources ≥8, (2) Verification status, (3) Multi-perspective, (4) Gaps. Output: PASS or NEEDS_MORE_RESEARCH.","input_dependencies":["step_1"]},"required":True},{"step_id":"step_3","order":3,"name":"Synthesis Phase","description":"Invoke Report Synthesizer for final report.","type":"CHILD_ENTITY_INVOCATION","target":{"entity_id":rs_id,"prompt_template":"Synthesize research into report. Summary:\n\n{{step_1}}\n\nQuality:\n\n{{step_2}}","input_dependencies":["step_1","step_2"]},"required":True}],"fallback_behavior":"ADAPTIVE"},"dynamic_planning":{"enabled":True,"planning_prompt":"If Quality Gate returns NEEDS_MORE_RESEARCH, re-invoke Research Director with specific gaps."}},"capabilities":{"tools":[],"memory":{"enabled":True,"mode":"CORTEX","cortex_config":{"max_children":12,"page_size_tokens":8000,"context_budget_pct":40,"auto_checkpoint":True,"resume_enabled":True}},"context_engineering":{"inject_cortex_viewport":True,"inject_episodic_memory":True,"no_truncation":True}},"governance":{"timeout_ms":1800000,"max_cost_usd":20.00,"max_recursion_depth":5,"execution_limits":{"max_tool_calls":100}},"observability":{"log_level":"INFO","log_thoughts":True,"track_cost":True}})
IDS["deep_research_process"] = d["id"]; time.sleep(0.3)

# ===================== LINK HIERARCHY =====================
print("\n== Linking Hierarchy ==")

# Skills → Actions
for skill_key, action_keys in [
    ("source_discoverer_skill", ["web_search_action"]),
    ("source_analyzer_skill", ["page_scrape_action", "content_extract_action"]),
    ("fact_verifier_skill", ["fact_check_action"]),
    ("knowledge_synthesizer_skill", ["outline_generator_action", "section_writer_action", "pdf_export_action"]),
]:
    update(IDS[skill_key], {"hierarchy": {"is_atomic": False, "composition_depth": 1, "children": [{"child_id": IDS[ak], "child_type": "ACTION", "relationship": "SEQUENTIAL"} for ak in action_keys]}})
    time.sleep(0.2)

# Agents → Skills
for agent_key, skill_keys in [
    ("research_director_agent", ["query_decomposer_skill", "source_discoverer_skill", "source_analyzer_skill", "fact_verifier_skill"]),
    ("report_synthesizer_agent", ["knowledge_synthesizer_skill"]),
]:
    update(IDS[agent_key], {"hierarchy": {"is_atomic": False, "composition_depth": 2, "children": [{"child_id": IDS[sk], "child_type": "SKILL", "relationship": "SEQUENTIAL"} for sk in skill_keys]}})
    time.sleep(0.2)

# ===================== LINK EXECUTION PLANS =====================
# The execution engine invokes child entities ONLY via CHILD_ENTITY_INVOCATION
# steps in planning.static_plan — NOT via hierarchy.children.
# Without these steps, only the PROCESS→AGENT links fire; SKILLs and ACTIONs
# are never executed as independent child runs.
print("\n== Linking Execution Plans (CHILD_ENTITY_INVOCATION) ==")

# SKILLs → Actions (add CHILD_ENTITY_INVOCATION steps to static_plan)
# source_discoverer_skill: invoke web_search_action, then rank inline
update(IDS["source_discoverer_skill"], {"planning": {
    "static_plan": {"enabled": True, "steps": [
        {"step_id": "step_1", "order": 1, "name": "Execute Web Search",
         "description": "Invoke the Web Search action to search for sources",
         "type": "CHILD_ENTITY_INVOCATION",
         "target": {"entity_id": IDS["web_search_action"], "prompt_template": "{{input}}"},
         "required": True},
        {"step_id": "step_2", "order": 2, "name": "Rank Sources",
         "description": "Deduplicate, rank, select top 10-15 sources for scraping",
         "type": "ACTION",
         "target": {"prompt_template": "Given results:\n\n{{Execute Web Search}}\n\nProduce ranked, deduplicated source list. Top 10-15 for scraping.",
                    "input_dependencies": ["step_1"]}}
    ]},
    "dynamic_planning": {"enabled": True, "planning_prompt": "If results insufficient, generate additional queries."}
}})
time.sleep(0.2)

# source_analyzer_skill: invoke page_scrape_action then content_extract_action
update(IDS["source_analyzer_skill"], {"planning": {
    "static_plan": {"enabled": True, "steps": [
        {"step_id": "step_1", "order": 1, "name": "Scrape Source Content",
         "description": "Invoke Page Scraper to scrape full content from source URL",
         "type": "CHILD_ENTITY_INVOCATION",
         "target": {"entity_id": IDS["page_scrape_action"], "prompt_template": "{{input}}"},
         "required": True},
        {"step_id": "step_2", "order": 2, "name": "Extract Structured Info",
         "description": "Invoke Content Extractor to extract claims, stats, quotes",
         "type": "CHILD_ENTITY_INVOCATION",
         "target": {"entity_id": IDS["content_extract_action"],
                    "prompt_template": "Analyze:\n\n{{Scrape Source Content}}\n\nExtract: KEY_CLAIMS, STATISTICS, QUOTES, ENTITIES, CREDIBILITY (1-5)",
                    "input_dependencies": ["step_1"]},
         "required": True}
    ]},
    "dynamic_planning": {"enabled": True, "planning_prompt": "Iterate through URLs. For each: scrape, analyze, continue. Skip failures."},
    "loop_control": {"max_iterations": 12, "iteration_context_mode": "SUMMARIZED", "summary_every_n_iterations": 3}
}})
time.sleep(0.2)

# fact_verifier_skill: invoke fact_check_action
update(IDS["fact_verifier_skill"], {"planning": {
    "static_plan": {"enabled": True, "steps": [
        {"step_id": "step_1", "order": 1, "name": "Verify Claims",
         "description": "Invoke Fact Checker to verify critical claims against independent sources",
         "type": "CHILD_ENTITY_INVOCATION",
         "target": {"entity_id": IDS["fact_check_action"], "prompt_template": "{{input}}"},
         "required": True}
    ]},
    "dynamic_planning": {"enabled": True, "planning_prompt": "For each claim: (1) formulate query, (2) search, (3) assess evidence, (4) record verdict."},
    "loop_control": {"max_iterations": 15, "iteration_context_mode": "SUMMARIZED", "summary_every_n_iterations": 5}
}})
time.sleep(0.2)

# knowledge_synthesizer_skill: inline synthesis step, then invoke outline, section writer, pdf
# CRITICAL: Pass the full raw research data ({{input}}) through to the section writer,
# not just the condensed synthesis. The section writer needs ALL details for a comprehensive report.
update(IDS["knowledge_synthesizer_skill"], {"planning": {
    "static_plan": {"enabled": True, "steps": [
        {"step_id": "step_1", "order": 1, "name": "Synthesize Knowledge",
         "description": "Read all research findings and identify key themes, narrative threads, and analytical framework",
         "type": "ACTION",
         "target": {"prompt_template": "You are synthesizing research findings into an analytical framework for a comprehensive report.\n\nINSTRUCTIONS:\n1. Read ALL the research data below carefully\n2. Identify 5-8 major themes/topics\n3. For each theme, list the specific data points, statistics, and sources\n4. Identify cross-cutting insights and contradictions\n5. Note the strongest and weakest evidence areas\n6. Preserve ALL specific numbers, statistics, URLs, and source names\n\nDo NOT condense or summarize — PRESERVE all details for the report writer.\n\nRESEARCH DATA:\n\n{{input}}"}},
        {"step_id": "step_2", "order": 2, "name": "Generate Outline",
         "description": "Invoke Outline Generator to create detailed report outline with 5-8 major sections",
         "type": "CHILD_ENTITY_INVOCATION",
         "target": {"entity_id": IDS["outline_generator_action"],
                    "prompt_template": "Based on these analytical themes:\n\n{{Synthesize Knowledge}}\n\nGenerate a DETAILED report outline as JSON array. Requirements:\n- Executive Summary (written last)\n- Methodology section\n- 5-8 major analytical sections, each with 2-4 subsections\n- Each section should specify key data points to include\n- Conclusions and Implications section\n- Sources/References section\n\nTarget: 20+ page report, 5000-8000 words.",
                    "input_dependencies": ["step_1"]},
         "required": True},
        {"step_id": "step_3", "order": 3, "name": "Write Report Sections",
         "description": "Invoke Section Writer with FULL research data + outline for comprehensive report",
         "type": "CHILD_ENTITY_INVOCATION",
         "target": {"entity_id": IDS["section_writer_action"],
                    "prompt_template": "Write a COMPREHENSIVE research report (minimum 5,000 words, target 6,000-8,000 words).\n\n## REPORT OUTLINE:\n{{Generate Outline}}\n\n## ANALYTICAL FRAMEWORK:\n{{Synthesize Knowledge}}\n\n## FULL RESEARCH DATA (use ALL details, statistics, and sources below):\n{{input}}\n\n## INSTRUCTIONS:\n- Write EVERY section from the outline above\n- Include specific statistics, numbers, and data points from the research data\n- Add inline citations [Source Name, Date] for every factual claim\n- Each section must have 3+ paragraphs of substantive analysis\n- Include cross-references between sections\n- End each major section with a KEY INSIGHT callout\n- Write Executive Summary LAST (as the final section)\n- Include a References section listing all sources cited\n- Target: 6,000-8,000 words minimum",
                    "input_dependencies": ["step_1", "step_2"]},
         "required": True},
        {"step_id": "step_4", "order": 4, "name": "Export PDF",
         "description": "Invoke PDF Exporter to generate final PDF",
         "type": "CHILD_ENTITY_INVOCATION",
         "target": {"entity_id": IDS["pdf_export_action"],
                    "prompt_template": "{{Write Report Sections}}",
                    "input_dependencies": ["step_3"]},
         "required": True}
    ]},
    "dynamic_planning": {"enabled": True, "planning_prompt": "Break long sections into subsections."}
}})
time.sleep(0.2)

# AGENTs → Skills (add static_plan with CHILD_ENTITY_INVOCATION for each child SKILL)
# research_director_agent: sequentially invoke 4 skills
update(IDS["research_director_agent"], {"planning": {
    "static_plan": {"enabled": True, "steps": [
        {"step_id": "step_1", "order": 1, "name": "Query Decomposition",
         "description": "Invoke Query Decomposer to break topic into targeted search queries",
         "type": "CHILD_ENTITY_INVOCATION",
         "target": {"entity_id": IDS["query_decomposer_skill"], "prompt_template": "{{input}}"},
         "required": True},
        {"step_id": "step_2", "order": 2, "name": "Source Discovery",
         "description": "Invoke Source Discoverer to execute queries and rank sources",
         "type": "CHILD_ENTITY_INVOCATION",
         "target": {"entity_id": IDS["source_discoverer_skill"],
                    "prompt_template": "Search for sources using these queries:\n\n{{Query Decomposition}}",
                    "input_dependencies": ["step_1"]},
         "required": True},
        {"step_id": "step_3", "order": 3, "name": "Source Analysis",
         "description": "Invoke Source Analyzer to scrape and analyze top sources",
         "type": "CHILD_ENTITY_INVOCATION",
         "target": {"entity_id": IDS["source_analyzer_skill"],
                    "prompt_template": "Scrape and analyze these sources:\n\n{{Source Discovery}}",
                    "input_dependencies": ["step_2"]},
         "required": True},
        {"step_id": "step_4", "order": 4, "name": "Fact Verification",
         "description": "Invoke Fact Verifier to verify critical claims",
         "type": "CHILD_ENTITY_INVOCATION",
         "target": {"entity_id": IDS["fact_verifier_skill"],
                    "prompt_template": "Verify critical claims from:\n\n{{Source Analysis}}",
                    "input_dependencies": ["step_3"]},
         "required": True}
    ]},
    "dynamic_planning": {"enabled": True,
        "planning_prompt": "Multi-wave research:\nWave 1: decompose → search → rank → scrape → extract\nWave 2: gaps → follow-up queries → scrape more → extract\nWave 3: critical claims → verify → matrix\nTools: web_search, scraper_tool, headless_browser. CHECKPOINT each wave.",
        "allowed_deviations": {"can_add_steps": True, "can_skip_optional_steps": True, "can_reorder_steps": True, "can_change_tools": True},
        "reconciliation_strategy": "DYNAMIC_PRIORITY"},
    "loop_control": {"max_iterations": 3, "iteration_context_mode": "SUMMARIZED", "summary_every_n_iterations": 1}
}})
time.sleep(0.2)

# report_synthesizer_agent: invoke knowledge_synthesizer_skill
update(IDS["report_synthesizer_agent"], {"planning": {
    "static_plan": {"enabled": True, "steps": [
        {"step_id": "step_1", "order": 1, "name": "Knowledge Synthesis",
         "description": "Invoke Knowledge Synthesizer to read CORTEX, generate outline, write report, and export PDF",
         "type": "CHILD_ENTITY_INVOCATION",
         "target": {"entity_id": IDS["knowledge_synthesizer_skill"], "prompt_template": "{{input}}"},
         "required": True}
    ]},
    "dynamic_planning": {"enabled": True,
        "planning_prompt": "1. Read all CORTEX findings\n2. Synthesize themes\n3. Generate outline\n4. Write sections, review each\n5. Executive Summary last\n6. Generate PDF\n\nUse pdf_generator. Target: 3000-8000 words."}
}})
time.sleep(0.2)

# ===================== DONE =====================
print("\n" + "=" * 60)
print("✅ Deep Research Setup Complete! (15 entities)")
print("=" * 60)
print(f"\n📊 Hierarchy:")
print(f"  PROCESS: 🔬 Deep Research → {IDS['deep_research_process']}")
print(f"  ├── AGENT: Research Director → {IDS['research_director_agent']}")
print(f"  │   ├── SKILL: Query Decomposer → {IDS['query_decomposer_skill']}")
print(f"  │   ├── SKILL: Source Discoverer → {IDS['source_discoverer_skill']}")
print(f"  │   │   └── ACTION: Web Search → {IDS['web_search_action']}")
print(f"  │   ├── SKILL: Source Analyzer → {IDS['source_analyzer_skill']}")
print(f"  │   │   ├── ACTION: Page Scraper → {IDS['page_scrape_action']}")
print(f"  │   │   └── ACTION: Content Extractor → {IDS['content_extract_action']}")
print(f"  │   └── SKILL: Fact Verifier → {IDS['fact_verifier_skill']}")
print(f"  │       └── ACTION: Fact Checker → {IDS['fact_check_action']}")
print(f"  └── AGENT: Report Synthesizer → {IDS['report_synthesizer_agent']}")
print(f"      └── SKILL: Knowledge Synthesizer → {IDS['knowledge_synthesizer_skill']}")
print(f"          ├── ACTION: Outline Generator → {IDS['outline_generator_action']}")
print(f"          ├── ACTION: Section Writer → {IDS['section_writer_action']}")
print(f"          └── ACTION: PDF Exporter → {IDS['pdf_export_action']}")

output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "entity_ids.json")
with open(output_path, "w") as f:
    json.dump(IDS, f, indent=2)
print(f"\nEntity IDs saved to: {output_path}")
