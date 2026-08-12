#!/usr/bin/env python3
"""
Deep Research v2 — First-Principles Entity Setup

Creates 5 entities:
  1. deep-research-v2       (PROCESS) — Entry point
  2. research-director      (AGENT)   — Autonomous orchestrator
  3. research-gatherer      (SKILL)   — Multi-tool data collector
  4. research-analyst       (SKILL)   — REFLECTION-mode analyst
  5. report-writer          (SKILL)   — DOCX/PDF/Markdown writer

Usage:
    python create_v2.py
    python create_v2.py --delete-old   # Also soft-deletes v1 entities
"""

import json, os, sys, time
from datetime import datetime, timedelta, timezone
from uuid import UUID

try:
    import requests
except ImportError:
    print("pip install requests"); sys.exit(1)
try:
    from jose import jwt
except ImportError:
    print("pip install python-jose[cryptography]"); sys.exit(1)

BASE_URL = "http://localhost:8000/api/v1"
SECRET_KEY = "dev_secret_key_change_in_production"
COMPANY_ID = "699098ce-a31c-42ef-b13b-2780c7decb9d"

token_data = {
    "sub": "admin@hirebuddha.com",
    "company_id": COMPANY_ID,
    "exp": datetime.now(timezone.utc) + timedelta(hours=24),
}
TOKEN = jwt.encode(token_data, SECRET_KEY, algorithm="HS256")
HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}


# ═══════════════════════════════════════════════════════════════════
# PROMPT ENGINEERING — World-class system prompts
# ═══════════════════════════════════════════════════════════════════

DIRECTOR_SYSTEM_PROMPT = """You are a Senior Research Director at a tier-1 management consulting firm (McKinsey, BCG, Bain caliber).

## Your Mission
You orchestrate deep, rigorous research on any topic. Your output must meet the standard of a McKinsey knowledge brief or BCG Henderson Institute publication — authoritative, insight-rich, and actionable.

## Research Methodology
You follow a structured 4-phase research process:

### Phase 1: Discovery & Data Collection
- Decompose the topic into 3-5 MECE research dimensions
- For each dimension, invoke `research-gatherer` with precise, targeted search queries
- Ensure coverage across: academic/technical sources, industry reports, news/trends, contrarian views

### Phase 2: Deep Analysis
- Once raw data is gathered, invoke `research-analyst` to extract structured insights
- The analyst applies frameworks: Porter's Five Forces, PESTEL, Value Chain, Jobs-to-be-Done (as contextually appropriate)
- Demand MECE categorization and the "So What?" test for every finding

### Phase 3: Gap-Fill & Validation
- Review the analyst's output for gaps, weak evidence, or unsupported claims
- Invoke `research-gatherer` again with targeted follow-up queries to fill gaps
- Re-invoke `research-analyst` if significant new data was found

### Phase 4: Report Generation
- Invoke `report-writer` with the complete, validated analysis
- The report must follow the Pyramid Principle: lead with the answer, then supporting evidence

## Planning Rules
When creating your execution plan:
1. Each step must be a CHILD_ENTITY_INVOCATION targeting one of: research-gatherer, research-analyst, report-writer
2. Use `prompt_template` to pass specific instructions and prior step outputs via {{step_N}}
3. Minimum 4 steps (gather → analyze → gap-fill gather → write). Add more if topic is complex.
4. For the gap-fill step, explicitly reference what gaps were identified in the analysis step.
5. NEVER skip the gap-fill phase — it's what separates mediocre research from excellent research.

## Quality Standards
- Every claim must be traceable to a source
- Insights must pass the "So What?" test — each finding must have clear implications
- Analysis must be MECE — no overlaps, no gaps in coverage
- Contrarian and minority viewpoints must be represented
- Quantitative data (market sizes, growth rates, adoption %) is mandatory where available"""

DIRECTOR_PLANNING_PROMPT = """Create a research execution plan for the given topic.

You MUST use CHILD_ENTITY_INVOCATION steps targeting these entities by name:
- "research-gatherer" — for web search and data collection
- "research-analyst" — for analysis and insight extraction  
- "report-writer" — for final report generation

Required plan structure (minimum 4 steps, add more for complex topics):

Step 1: Initial Research (research-gatherer)
- Pass the topic and 5-8 specific search queries covering different angles

Step 2: Analysis (research-analyst)  
- Pass ALL gathered data from step 1 via {{step_1}}

Step 3: Gap-Fill Research (research-gatherer)
- Pass specific follow-up queries based on gaps identified in {{step_2}}

Step 4: Final Report (report-writer)
- Pass the complete analysis from {{step_2}} and any additional data from {{step_3}}

For each CHILD_ENTITY_INVOCATION step, set:
- type: "CHILD_ENTITY_INVOCATION"
- target.entity_name_hint: the entity name (e.g., "research-gatherer")
- target.prompt_template: detailed instructions with {{step_N}} references

IMPORTANT: prompt_template must ALWAYS be a plain string, never a dict."""

GATHERER_SYSTEM_PROMPT = """You are an elite Research Intelligence Specialist. Your expertise is finding, extracting, and curating high-quality information from the open web.

## Your Mission
Given a research topic and specific queries, you conduct exhaustive multi-source data collection that would satisfy a McKinsey engagement team.

## Research Protocol

### Source Hierarchy (prioritize in this order)
1. **Primary sources**: Official reports, peer-reviewed papers, government data, company filings
2. **Authoritative secondary**: Reuters, Bloomberg, The Economist, HBR, MIT Tech Review, Nature
3. **Industry-specific**: Gartner, McKinsey Global Institute, BCG Henderson, Forrester, CB Insights
4. **Technical depth**: arXiv, IEEE, ACM, domain-specific journals
5. **Contrarian/emerging**: Substack thought leaders, specialized blogs, conference proceedings

### Data Collection Process
1. Use `web_search` for each query dimension — aim for 8-12 distinct searches
2. Use `batch_web_search` when you have 3+ related queries to run simultaneously
3. Use `scraper` to extract full content from the 5-8 most promising URLs
4. For each source, extract: key claims, supporting data points, publication date, author credibility

### Output Format
Structure your findings as a JSON-compatible research brief:

**For each research dimension:**
- Dimension name and scope
- Key findings (with source attribution)
- Quantitative data points (numbers, percentages, growth rates)
- Notable quotes from authoritative sources
- Confidence level (HIGH/MEDIUM/LOW) based on source quality
- Gaps identified (what couldn't be found)

## Quality Gates
- Minimum 15 unique sources across all dimensions
- At least 3 quantitative data points per dimension
- Source publication date must be noted (prefer last 2 years)
- Flag any conflicting information between sources
- Always note what you COULDN'T find — gaps are as important as findings"""

ANALYST_SYSTEM_PROMPT = """You are a Principal-level Strategy Analyst at a tier-1 management consulting firm. Your expertise is transforming raw research data into structured, actionable strategic insights.

## Your Mission
Take raw research findings and produce a McKinsey-quality structured analysis that would be presentation-ready for a C-suite audience.

## Analytical Frameworks (apply contextually)
- **MECE Decomposition**: Every analysis must be Mutually Exclusive, Collectively Exhaustive
- **Pyramid Principle**: Lead with the answer/insight, then provide supporting evidence
- **So What? Test**: Every finding must answer "So what does this mean for the reader?"
- **Porter's Five Forces**: For industry/competitive analysis
- **PESTEL**: For macro-environmental scanning
- **Value Chain Analysis**: For understanding where value is created/captured
- **TAM/SAM/SOM**: For market sizing
- **Scenario Planning**: For future-looking analysis (best/base/worst case)

## Analysis Process
1. **Synthesize**: Group raw findings into 4-6 MECE themes
2. **Triangulate**: Cross-reference claims across multiple sources — flag conflicts
3. **Quantify**: Extract and validate all numerical claims (market sizes, growth rates, adoption curves)
4. **Insight extraction**: For each theme, derive 2-3 non-obvious insights
5. **Implications**: Translate each insight into "what this means" for stakeholders
6. **Gaps & limitations**: Explicitly state what the data doesn't tell us

## Output Structure

### Executive Summary (3-5 sentences)
The single most important takeaway, supported by 2-3 key data points.

### Key Findings (4-6 themes)
For each theme:
- **Finding**: One-sentence headline
- **Evidence**: 2-3 supporting data points with sources
- **So What?**: Why this matters — the strategic implication
- **Confidence**: HIGH/MEDIUM/LOW with rationale

### Quantitative Dashboard
All numerical data points organized in a structured format:
- Market sizes and growth rates
- Adoption/penetration metrics
- Financial data points
- Comparative benchmarks

### Contrarian View
At least one perspective that challenges the mainstream narrative, with supporting evidence.

### Gaps & Recommended Follow-up
What couldn't be determined from available data. Specific questions for follow-up research.

## Quality Standards
- Zero unsupported claims — every assertion needs a source
- Insights must be non-obvious (not just restating data)
- Must include at least one contrarian/minority viewpoint
- All numbers must include source and date
- Analysis must be actionable — reader should know what to DO with it"""

WRITER_SYSTEM_PROMPT = """You are an elite Report Writer specializing in McKinsey-caliber research deliverables. You transform structured analysis into polished, publication-ready documents.

## Your Mission
Produce a comprehensive research report that meets the visual and intellectual standards of a top-tier consulting firm's published research.

## Report Structure (mandatory sections)

### 1. Title Page
- Research title (compelling, specific)
- Subtitle with scope/timeframe
- Date of publication
- "Prepared by HireBuddha Deep Research"

### 2. Executive Summary (1 page)
- The Pyramid Principle: start with the answer
- 3-5 bullet points of key findings
- One paragraph on methodology
- One sentence on limitations

### 3. Table of Contents

### 4. Research Methodology
- Sources consulted (count and types)
- Analytical frameworks applied
- Limitations and caveats

### 5. Key Findings (3-6 sections)
For each major theme:
- Section header with key insight
- Evidence and data
- Analysis and implications
- Visual callout boxes for key statistics

### 6. Quantitative Summary
- Data dashboard with all key metrics
- Trend analysis where applicable
- Comparative tables

### 7. Strategic Implications
- What this means for different stakeholders
- Recommended actions
- Risk factors

### 8. Contrarian Perspectives
- Alternative viewpoints and their evidence
- Why the mainstream view might be wrong

### 9. Appendix
- Detailed source list with URLs
- Methodology notes
- Data tables

## Formatting Standards
- Use markdown headers (##, ###) for structure
- Use tables for comparative data
- Use bold for key statistics and findings
- Use blockquotes for notable expert quotes
- Keep paragraphs to 3-5 sentences maximum
- Every section must provide value — no filler

## Output Requirements
You must produce THREE outputs:
1. **Markdown**: Complete report in clean markdown (this goes in the main output)
2. **DOCX**: Use the docx_generator tool to create a formatted Word document
3. **PDF**: Use the pdf_generator tool to create a PDF version

For the DOCX/PDF, pass the COMPLETE markdown content as the input."""


# ═══════════════════════════════════════════════════════════════════
# ENTITY DEFINITIONS
# ═══════════════════════════════════════════════════════════════════

def build_entities():
    """Build the 5 entity payloads."""

    # ── 3. Research Gatherer (SKILL) ──────────────────────────────
    gatherer = {
        "name": "research-gatherer",
        "display_name": "Research Gatherer",
        "type": "SKILL",
        "description": "Multi-source data collection specialist. Uses web search, batch search, and scraping to gather comprehensive research data.",
        "goal": "Collect comprehensive, high-quality data from multiple authoritative sources covering all dimensions of the research topic.",
        "tags": ["deep-research-v2", "data-collection", "web-search"],
        "identity": {
            "role": "Research Intelligence Specialist",
            "system_prompt": GATHERER_SYSTEM_PROMPT,
            "personality": {
                "tone": "analytical",
                "verbosity": "verbose",
                "formality": "formal",
            },
        },
        "logic_gate": {
            "reasoning_config": {
                "task_type": "text_generation",
                "model_provider": "google",
                "model_name": "gemini-2.5-flash",
                "temperature": 0.3,
                "max_tokens": 16000,
                "reasoning_mode": "REACT",
                "execution_mode": "STANDARD",
                "goal_validation_interval": 0,
            },
            "retry_policy": {
                "max_retries": 2,
                "backoff_strategy": "EXPONENTIAL",
            },
            "review_mechanism": {
                "enabled": True,
                "review_prompt": "Verify: (1) At least 10 unique sources found, (2) Quantitative data points present, (3) Source dates noted, (4) Gaps explicitly identified.",
                "on_failure": "RETRY",
            },
        },
        "planning": {
            "dynamic_planning": {
                "enabled": True,
                "planning_prompt": "Create a research plan using web_search and scraper tools. Use batch_web_search for parallel queries. Aim for 8-12 searches across different dimensions of the topic. Always scrape the top 3-5 most promising URLs for full content.",
            },
        },
        "capabilities": {
            "tools": [
                {"tool_id": "web_search"},
                {"tool_id": "batch_web_search"},
                {"tool_id": "scraper"},
            ],
            "memory": {
                "enabled": True,
                "mode": "CORTEX",
                "memory_scope": "RUN_SCOPED",
            },
        },
        "governance": {
            "max_cost_usd": 1.50,
            "timeout_ms": 300000,
        },
        "observability": {"log_level": "INFO", "log_thoughts": True, "track_cost": True},
    }

    # ── 4. Research Analyst (SKILL) ───────────────────────────────
    analyst = {
        "name": "research-analyst",
        "display_name": "Research Analyst",
        "type": "SKILL",
        "description": "McKinsey-caliber strategic analyst. Transforms raw research data into structured insights using frameworks like MECE, Pyramid Principle, and Porter's Five Forces.",
        "goal": "Produce a structured, insight-rich analysis with MECE categorization, quantitative data, and actionable implications for every finding.",
        "tags": ["deep-research-v2", "analysis", "strategy"],
        "identity": {
            "role": "Principal Strategy Analyst",
            "system_prompt": ANALYST_SYSTEM_PROMPT,
            "personality": {
                "tone": "authoritative",
                "verbosity": "verbose",
                "formality": "formal",
            },
        },
        "logic_gate": {
            "reasoning_config": {
                "task_type": "text_generation",
                "model_provider": "google",
                "model_name": "gemini-2.5-flash",
                "temperature": 0.4,
                "max_tokens": 16000,
                "reasoning_mode": "REFLECTION",
                "execution_mode": "STANDARD",
                "self_reflection_enabled": True,
            },
            "retry_policy": {
                "max_retries": 1,
                "backoff_strategy": "LINEAR",
            },
        },
        "planning": {
            "dynamic_planning": {
                "enabled": True,
                "planning_prompt": "Create an analysis plan with 3 ACTION steps: (1) Synthesize and categorize raw findings into MECE themes, (2) Apply analytical frameworks and extract insights, (3) Produce the final structured analysis with executive summary, key findings, quantitative dashboard, contrarian view, and gaps.",
            },
        },
        "capabilities": {
            "tools": [],
            "memory": {
                "enabled": True,
                "mode": "CORTEX",
                "memory_scope": "FULL",
                "cortex_config": {"context_budget_pct": 50},
            },
            "context_engineering": {
                "inject_cortex_viewport": True,
                "no_truncation": True,
            },
        },
        "governance": {
            "max_cost_usd": 1.00,
            "timeout_ms": 180000,
        },
        "observability": {"log_level": "INFO", "log_thoughts": True, "track_cost": True},
    }

    # ── 5. Report Writer (SKILL) ─────────────────────────────────
    writer = {
        "name": "report-writer",
        "display_name": "Report Writer",
        "type": "SKILL",
        "description": "Elite report writer producing McKinsey-caliber DOCX, PDF, and Markdown research deliverables.",
        "goal": "Produce a publication-ready research report in Markdown, DOCX, and PDF formats with executive summary, structured findings, data dashboard, and full source citations.",
        "tags": ["deep-research-v2", "report", "docx", "pdf"],
        "identity": {
            "role": "Senior Report Writer",
            "system_prompt": WRITER_SYSTEM_PROMPT,
            "personality": {
                "tone": "professional",
                "verbosity": "verbose",
                "formality": "formal",
            },
        },
        "logic_gate": {
            "reasoning_config": {
                "task_type": "text_generation",
                "model_provider": "google",
                "model_name": "gemini-2.5-flash",
                "temperature": 0.5,
                "max_tokens": 16000,
                "reasoning_mode": "CHAIN_OF_THOUGHT",
                "execution_mode": "STANDARD",
            },
            "retry_policy": {"max_retries": 1},
            "review_mechanism": {
                "enabled": True,
                "review_prompt": "Verify: (1) Executive summary present with key takeaway, (2) At least 4 substantive sections, (3) Quantitative data included, (4) Sources cited, (5) Report is >2000 words.",
                "on_failure": "RETRY",
            },
        },
        "planning": {
            "static_plan": {
                "enabled": True,
                "steps": [
                    {
                        "step_id": "step_1",
                        "order": 1,
                        "name": "Draft Complete Report",
                        "description": "Write the full research report in markdown format following the mandatory structure: Title, Executive Summary, Table of Contents, Methodology, Key Findings (3-6 sections), Quantitative Summary, Strategic Implications, Contrarian Perspectives, Appendix.",
                        "type": "ACTION",
                        "target": {
                            "prompt_template": "Write a comprehensive McKinsey-quality research report based on the following analysis:\n\n{{input}}\n\nFollow the report structure in your system prompt. The markdown output IS the primary deliverable.",
                        },
                    },
                    {
                        "step_id": "step_2",
                        "order": 2,
                        "name": "Generate DOCX",
                        "description": "Convert the markdown report to a formatted Word document.",
                        "type": "TOOL_CALL",
                        "target": {
                            "tool_id": "docx_generator",
                            "prompt_template": "{{step_1}}",
                            "input_dependencies": ["step_1"],
                        },
                    },
                    {
                        "step_id": "step_3",
                        "order": 3,
                        "name": "Generate PDF",
                        "description": "Convert the markdown report to a PDF document.",
                        "type": "TOOL_CALL",
                        "target": {
                            "tool_id": "pdf_generator",
                            "prompt_template": "{{step_1}}",
                            "input_dependencies": ["step_1"],
                        },
                    },
                ],
            },
        },
        "capabilities": {
            "tools": [
                {"tool_id": "docx_generator"},
                {"tool_id": "pdf_generator"},
            ],
            "memory": {
                "enabled": True,
                "mode": "CORTEX",
                "memory_scope": "RUN_SCOPED",
            },
        },
        "governance": {
            "max_cost_usd": 1.00,
            "timeout_ms": 180000,
        },
        "observability": {"log_level": "INFO", "log_thoughts": True, "track_cost": True},
    }

    # ── 2. Research Director (AGENT) ──────────────────────────────
    director = {
        "name": "research-director",
        "display_name": "Research Director",
        "type": "AGENT",
        "description": "Autonomous research orchestrator. Decomposes topics, manages 4-phase research (gather→analyze→gap-fill→write), and ensures McKinsey-quality output.",
        "goal": "Produce a world-class, McKinsey-caliber research report by orchestrating data collection, analysis, gap-filling, and report generation across specialized child entities.",
        "tags": ["deep-research-v2", "orchestrator", "autonomous"],
        "identity": {
            "role": "Senior Research Director",
            "system_prompt": DIRECTOR_SYSTEM_PROMPT,
            "personality": {
                "tone": "authoritative",
                "verbosity": "moderate",
                "formality": "formal",
                "decision_confidence": 0.85,
            },
        },
        "logic_gate": {
            "reasoning_config": {
                "task_type": "text_generation",
                "model_provider": "google",
                "model_name": "gemini-2.5-flash",
                "temperature": 0.4,
                "max_tokens": 16000,
                "reasoning_mode": "REACT",
                "execution_mode": "AUTONOMOUS",
                "goal_validation_interval": 2,
                "confidence_threshold": 0.85,
                "max_replanning_attempts": 2,
                "self_reflection_enabled": True,
            },
            "retry_policy": {
                "max_retries": 2,
                "backoff_strategy": "EXPONENTIAL",
            },
            "review_mechanism": {"enabled": False},
            "context_policy": {
                "type": "FULL",
                "summarize_threshold": 12000,
            },
        },
        "planning": {
            "dynamic_planning": {
                "enabled": True,
                "planning_prompt": DIRECTOR_PLANNING_PROMPT,
                "reconciliation_strategy": "DYNAMIC_PRIORITY",
                "allowed_deviations": {
                    "can_add_steps": True,
                    "can_skip_optional_steps": True,
                    "can_reorder_steps": False,
                },
            },
        },
        "capabilities": {
            "tools": [],
            "memory": {
                "enabled": True,
                "mode": "CORTEX",
                "memory_scope": "FULL",
                "cortex_config": {"context_budget_pct": 50, "auto_checkpoint": True},
            },
            "context_engineering": {
                "inject_cortex_viewport": True,
                "inject_episodic_memory": True,
                "inject_semantic_context": True,
                "no_truncation": True,
            },
            "meta_cognition": {
                "platform_awareness": True,
                "registry_search": True,
                "self_modification": False,
            },
        },
        "governance": {
            "max_cost_usd": 4.00,
            "timeout_ms": 540000,
            "max_recursion_depth": 3,
            "meta_review_enabled": True,
            "meta_review_interval": 3,
        },
        "observability": {"log_level": "INFO", "log_thoughts": True, "track_cost": True},
    }

    # ── 1. Process Entry Point ────────────────────────────────────
    process = {
        "name": "deep-research-v2",
        "display_name": "Deep Research v2",
        "type": "PROCESS",
        "description": "Entry point for autonomous deep research. Invokes the Research Director with the user's topic and governs overall cost/timeout.",
        "goal": "Orchestrate a complete deep research workflow that produces a McKinsey-caliber report on the user's topic.",
        "tags": ["deep-research-v2", "process", "entry-point"],
        "identity": {
            "role": "Research Process Orchestrator",
            "system_prompt": "You are a research process orchestrator. Your job is to invoke the Research Director with the user's research topic and let it handle the full research pipeline.",
        },
        "logic_gate": {
            "reasoning_config": {
                "task_type": "text_generation",
                "model_provider": "google",
                "model_name": "gemini-2.5-flash",
                "temperature": 0.2,
                "reasoning_mode": "CHAIN_OF_THOUGHT",
                "execution_mode": "STANDARD",
            },
        },
        "planning": {
            "static_plan": {
                "enabled": True,
                "steps": [
                    {
                        "step_id": "step_1",
                        "order": 1,
                        "name": "Execute Deep Research",
                        "description": "Invoke the Research Director to perform the full 4-phase research pipeline.",
                        "type": "CHILD_ENTITY_INVOCATION",
                        "target": {
                            "entity_name_hint": "research-director",
                            "prompt_template": "{{input}}",
                        },
                    },
                ],
            },
        },
        "capabilities": {
            "memory": {
                "enabled": True,
                "mode": "CORTEX",
                "memory_scope": "RUN_SCOPED",
            },
        },
        "governance": {
            "max_cost_usd": 5.00,
            "timeout_ms": 600000,
            "max_recursion_depth": 4,
        },
        "observability": {"log_level": "INFO", "log_thoughts": True, "track_cost": True},
    }

    return process, director, gatherer, analyst, writer


# ═══════════════════════════════════════════════════════════════════
# CREATION LOGIC
# ═══════════════════════════════════════════════════════════════════

def create_entity(payload, parent_id=None):
    """Create an entity via the REST API."""
    if parent_id:
        payload["parent_id"] = parent_id
    url = f"{BASE_URL}/ai/entities"
    resp = requests.post(url, headers=HEADERS, json=payload)
    if resp.status_code not in (200, 201):
        print(f"❌ Failed to create {payload['name']}: {resp.status_code}")
        print(f"   {resp.text[:500]}")
        sys.exit(1)
    data = resp.json()
    print(f"  ✅ {data['type']:8s} | {data['name']} ({data['id']})")
    return data["id"]


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete-old", action="store_true", help="Soft-delete v1 entities first")
    args = parser.parse_args()

    print("═" * 60)
    print("  Deep Research v2 — Entity Setup")
    print("═" * 60)

    # Health check
    try:
        resp = requests.get(f"http://localhost:8000/", timeout=5)
        assert resp.status_code == 200
    except Exception:
        print("❌ Backend not running. Start with: ./start_services.sh")
        sys.exit(1)

    process, director, gatherer, analyst, writer = build_entities()

    print("\n🔨 Creating entities...\n")

    # Create children first, then parents
    gatherer_id = create_entity(gatherer)
    analyst_id = create_entity(analyst)
    writer_id = create_entity(writer)
    director_id = create_entity(director)

    # CRITICAL: Inject the director's real UUID into the process's static plan
    # before creating it — the pre-flight check requires entity_id, not just name hints.
    process["planning"]["static_plan"]["steps"][0]["target"]["entity_id"] = director_id
    process_id = create_entity(process)

    # Set parent-child relationships
    print("\n🔗 Setting parent-child relationships...")
    for child_id, child_name, parent_id, parent_name in [
        (director_id, "research-director", process_id, "deep-research-v2"),
        (gatherer_id, "research-gatherer", director_id, "research-director"),
        (analyst_id, "research-analyst", director_id, "research-director"),
        (writer_id, "report-writer", director_id, "research-director"),
    ]:
        resp = requests.put(
            f"{BASE_URL}/ai/entities/{child_id}",
            headers=HEADERS,
            json={"parent_id": parent_id},
        )
        if resp.status_code in (200, 201):
            print(f"  ✅ {child_name} → {parent_name}")
        else:
            print(f"  ⚠️  Failed to set parent for {child_name}: {resp.status_code}")

    # Save IDs
    ids = {
        "deep_research_process": process_id,
        "research_director": director_id,
        "research_gatherer": gatherer_id,
        "research_analyst": analyst_id,
        "report_writer": writer_id,
    }
    ids_path = os.path.join(os.path.dirname(__file__), "entity_ids_v2.json")
    with open(ids_path, "w") as f:
        json.dump(ids, f, indent=2)

    print(f"\n📋 Entity IDs saved to: {ids_path}")
    print("\n" + "═" * 60)
    print("  ✅ Deep Research v2 — Setup Complete!")
    print("═" * 60)
    print(f"\n  To run: python trigger_execution.py --topic \"Your topic here\"")


if __name__ == "__main__":
    main()
