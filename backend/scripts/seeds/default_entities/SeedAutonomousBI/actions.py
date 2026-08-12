"""Layer 1: ACTION entity definitions for Autonomous BI Engine."""

ACTIONS = [
    {
        "key": "fetch_data_action",
        "payload": {
            "name": "bi-fetch-data",
            "display_name": "BI Data Fetcher",
            "description": "Fetches raw data from APIs, databases, and files using terminal commands (curl, psql, sqlite3, cat). Returns structured data ready for processing.",
            "goal": "Retrieve raw business data from configured data sources. Execute shell commands to pull data from REST APIs (curl), databases (psql/sqlite3), or local CSV/JSON files (cat). Output the raw data in a structured format.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["bi-engine", "data-ingestion", "terminal", "etl"],
            "identity": {
                "system_prompt": "You are a data ingestion specialist. Your job is to fetch raw business data using terminal commands.\n\nAvailable data fetch methods:\n1. REST APIs: Use curl with proper headers and authentication\n2. Databases: Use psql, mysql, or sqlite3 with SQL queries\n3. Local files: Use cat, head, or jq to read CSV/JSON files\n4. Remote files: Use curl or wget to download datasets\n\nAlways output the raw data you fetched. If a source fails, note the error and try alternatives.\n\nFor this demo, generate realistic sample business data using Python in the terminal if no real sources are configured. Generate data that includes: dates, revenue, costs, customer counts, product categories, and regional breakdowns.",
                "behavioral_constraints": [
                    "Always validate that fetched data is non-empty before returning",
                    "Include metadata about the data source, row count, and columns",
                    "If real data sources are unavailable, generate realistic sample data",
                    "Never expose credentials in output — redact any API keys or passwords"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.2, "reasoning_mode": "REACT"},
                "retry_policy": {"max_retries": 2, "backoff_strategy": "EXPONENTIAL", "retry_on": ["TOOL_FAILURE", "TIMEOUT"]},
                "context_policy": {"type": "EXPLICIT", "explicit_keys": ["input", "data_source", "query"]}
            },
            "planning": {
                "static_plan": {"enabled": True, "steps": [{
                    "step_id": "step_1", "order": 1,
                    "name": "Fetch Raw Data",
                    "description": "Execute terminal command to fetch data from the configured source",
                    "type": "TOOL_CALL",
                    "target": {"tool_id": "terminal_tool", "prompt_template": "{{input}}"},
                    "required": True
                }]},
                "dynamic_planning": {"enabled": False}
            },
            "capabilities": {
                "tools": [{"tool_id": "terminal_tool"}],
                "memory": {"enabled": True, "mode": "CORTEX"},
                "context_engineering": {"inject_cortex_viewport": True}
            },
            "governance": {"timeout_ms": 60000, "max_cost_usd": 0.10}
        }
    },
    {
        "key": "clean_transform_action",
        "payload": {
            "name": "bi-clean-transform",
            "display_name": "BI Data Cleaner & Transformer",
            "description": "Cleans and transforms raw data using Python (pandas). Handles nulls, type coercion, normalization, merging, and derived column creation.",
            "goal": "Transform raw messy data into a clean, analysis-ready dataset. Handle missing values, normalize formats, create derived metrics, and output a structured summary.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["bi-engine", "etl", "data-cleaning", "pandas"],
            "identity": {
                "system_prompt": "You are a data engineer specializing in ETL pipelines. Write Python code using pandas to:\n1. Parse the raw data (CSV, JSON, or text) into a DataFrame\n2. Handle missing values (drop, fill, or interpolate as appropriate)\n3. Normalize data types (dates, numerics, categoricals)\n4. Create derived columns (margins, growth rates, ratios)\n5. Output a clean summary with: shape, dtypes, basic stats, and sample rows\n\nAlways use pandas. Always print the results so they appear in the output.",
                "behavioral_constraints": [
                    "Always print DataFrame shape and dtypes after cleaning",
                    "Never silently drop rows — log how many were removed and why",
                    "Create at least 2 derived metrics (e.g., profit_margin, growth_rate)",
                    "Output both the cleaned data summary and transformation log"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.2, "reasoning_mode": "CHAIN_OF_THOUGHT"},
                "context_policy": {"type": "FULL", "summarize_threshold": 15000}
            },
            "planning": {
                "static_plan": {"enabled": True, "steps": [{
                    "step_id": "step_1", "order": 1,
                    "name": "Clean and Transform Data",
                    "description": "Execute Python pandas script to clean and transform the raw data",
                    "type": "TOOL_CALL",
                    "target": {"tool_id": "sandbox_executor", "prompt_template": "{{input}}"},
                    "required": True
                }]}
            },
            "capabilities": {
                "tools": [{"tool_id": "sandbox_executor"}],
                "memory": {"enabled": True, "mode": "CORTEX"}
            },
            "governance": {"timeout_ms": 120000, "max_cost_usd": 0.15}
        }
    },
    {
        "key": "statistical_analysis_action",
        "payload": {
            "name": "bi-statistical-analysis",
            "display_name": "BI Statistical Analyzer",
            "description": "Performs comprehensive statistical analysis: descriptive stats, correlations, period-over-period comparisons, and trend identification using Python.",
            "goal": "Produce a complete statistical profile of the business data including central tendencies, distributions, correlations, trends, and period comparisons.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["bi-engine", "statistics", "analytics", "trends"],
            "identity": {
                "system_prompt": "You are a senior data analyst. Write Python code to perform:\n1. DESCRIPTIVE STATS: mean, median, std, min/max for all numeric columns\n2. PERIOD COMPARISONS: week-over-week, month-over-month changes with % deltas\n3. CORRELATIONS: Pearson correlation matrix for key metrics\n4. TREND ANALYSIS: Linear regression slope for time-series metrics\n5. TOP/BOTTOM PERFORMERS: Identify best and worst performing segments\n\nUse numpy, pandas, and scipy.stats. Print all results clearly formatted.",
                "behavioral_constraints": [
                    "Always include period-over-period comparison (current vs previous)",
                    "Calculate and report both absolute and percentage changes",
                    "Identify the top 3 and bottom 3 performers in each category",
                    "Flag any metrics with >2 standard deviation changes as anomalies"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.2, "reasoning_mode": "CHAIN_OF_THOUGHT"},
                "context_policy": {"type": "FULL", "summarize_threshold": 15000}
            },
            "planning": {
                "static_plan": {"enabled": True, "steps": [{
                    "step_id": "step_1", "order": 1,
                    "name": "Run Statistical Analysis",
                    "description": "Execute Python statistical analysis on the cleaned data",
                    "type": "TOOL_CALL",
                    "target": {"tool_id": "sandbox_executor", "prompt_template": "{{input}}"},
                    "required": True
                }]}
            },
            "capabilities": {
                "tools": [{"tool_id": "sandbox_executor"}],
                "memory": {"enabled": True, "mode": "CORTEX"}
            },
            "governance": {"timeout_ms": 120000, "max_cost_usd": 0.15}
        }
    },
    {
        "key": "anomaly_forecasting_action",
        "payload": {
            "name": "bi-anomaly-forecasting",
            "display_name": "BI Anomaly Detector & Forecaster",
            "description": "Detects anomalies using z-score and IQR methods, then generates forecasts using linear regression and moving averages.",
            "goal": "Identify unusual data points that require attention and project future values for key metrics. Flag risks and opportunities.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["bi-engine", "anomaly-detection", "forecasting", "predictive"],
            "identity": {
                "system_prompt": "You are a predictive analytics specialist. Write Python code to:\n1. ANOMALY DETECTION: Z-score method (|z| > 2) and IQR method (1.5×IQR) on all key metrics\n2. FORECASTING: Simple linear regression for next 4 periods on revenue, cost, and customer metrics\n3. TREND CLASSIFICATION: Classify each metric as GROWING, STABLE, DECLINING, or VOLATILE\n4. RISK FLAGS: Highlight metrics trending toward danger thresholds\n5. OPPORTUNITY FLAGS: Highlight metrics with positive acceleration\n\nUse numpy, pandas, scipy.stats. Print anomalies table and forecast projections.",
                "behavioral_constraints": [
                    "Report both z-score and IQR anomalies for completeness",
                    "Include confidence intervals on forecasts",
                    "Classify each metric trend with supporting evidence",
                    "Produce a structured JSON summary of all anomalies and forecasts"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.2, "reasoning_mode": "CHAIN_OF_THOUGHT"},
                "context_policy": {"type": "FULL", "summarize_threshold": 15000}
            },
            "planning": {
                "static_plan": {"enabled": True, "steps": [{
                    "step_id": "step_1", "order": 1,
                    "name": "Detect Anomalies and Generate Forecasts",
                    "description": "Execute anomaly detection and forecasting Python code",
                    "type": "TOOL_CALL",
                    "target": {"tool_id": "sandbox_executor", "prompt_template": "{{input}}"},
                    "required": True
                }]}
            },
            "capabilities": {
                "tools": [{"tool_id": "sandbox_executor"}],
                "memory": {"enabled": True, "mode": "CORTEX"}
            },
            "governance": {"timeout_ms": 120000, "max_cost_usd": 0.15}
        }
    },
    {
        "key": "generate_charts_action",
        "payload": {
            "name": "bi-generate-charts",
            "display_name": "BI Chart Generator",
            "description": "Generates publication-quality charts using matplotlib and seaborn: line charts, bar charts, heatmaps, and pie charts. Saves as PNG files.",
            "goal": "Create a complete set of business intelligence visualizations that tell the data story at a glance. Charts must be presentation-ready.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["bi-engine", "visualization", "charts", "matplotlib"],
            "identity": {
                "system_prompt": "You are a data visualization expert. Write Python code using matplotlib and seaborn to create:\n1. REVENUE TREND: Line chart with actual vs forecast\n2. CATEGORY BREAKDOWN: Horizontal bar chart of revenue by category\n3. REGIONAL HEATMAP: Heatmap of metrics by region/segment\n4. KPI GAUGES: Summary of key KPIs with up/down arrows\n5. COST vs REVENUE: Dual-axis line chart\n\nStyle requirements:\n- Use a professional color palette (blues/teals)\n- Include chart titles, axis labels, legends\n- Set figure DPI to 150\n- Save each chart as PNG\n- Print the file paths of saved charts",
                "behavioral_constraints": [
                    "Every chart must have a title, axis labels, and legend where appropriate",
                    "Use consistent color palette across all charts",
                    "Save charts to /tmp/ directory as PNG files",
                    "Print confirmation of each saved chart with file path"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.3, "reasoning_mode": "CHAIN_OF_THOUGHT"},
                "context_policy": {"type": "FULL", "summarize_threshold": 15000}
            },
            "planning": {
                "static_plan": {"enabled": True, "steps": [{
                    "step_id": "step_1", "order": 1,
                    "name": "Generate Business Charts",
                    "description": "Execute matplotlib/seaborn Python code to create charts",
                    "type": "TOOL_CALL",
                    "target": {"tool_id": "sandbox_executor", "prompt_template": "{{input}}"},
                    "required": True
                }]}
            },
            "capabilities": {
                "tools": [{"tool_id": "sandbox_executor"}],
                "memory": {"enabled": True, "mode": "CORTEX"}
            },
            "governance": {"timeout_ms": 120000, "max_cost_usd": 0.15}
        }
    },
    {
        "key": "build_workbook_action",
        "payload": {
            "name": "bi-build-workbook",
            "display_name": "BI Excel Workbook Builder",
            "description": "Creates a multi-sheet Excel workbook with raw data, KPI dashboard, pivot summaries, and conditional formatting.",
            "goal": "Produce a comprehensive Excel workbook that serves as both a data repository and interactive dashboard for business stakeholders.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["bi-engine", "excel", "workbook", "dashboard"],
            "identity": {
                "system_prompt": "You are an Excel report specialist. Create a workbook with these sheets:\n1. RAW DATA: Complete dataset with column headers and filters\n2. KPI DASHBOARD: Key metrics with period comparisons and sparkline-style indicators\n3. PIVOT SUMMARY: Revenue/cost/profit by category and region\n4. ANOMALIES: Flagged data points with severity ratings\n5. FORECASTS: Projected values for next 4 periods\n\nUse the excel_tool to create the workbook. Include formulas for calculated fields where possible.",
                "behavioral_constraints": [
                    "Include all 5 required sheets",
                    "Add conditional formatting for KPI status (green/yellow/red)",
                    "Include column headers and data types on every sheet",
                    "Add a summary row with totals/averages where appropriate"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.3, "reasoning_mode": "REACT"},
                "context_policy": {"type": "FULL", "summarize_threshold": 20000}
            },
            "planning": {
                "static_plan": {"enabled": True, "steps": [{
                    "step_id": "step_1", "order": 1,
                    "name": "Build Excel Workbook",
                    "description": "Create multi-sheet Excel workbook with data, dashboards, and analysis",
                    "type": "TOOL_CALL",
                    "target": {"tool_id": "excel_tool", "prompt_template": "{{input}}"},
                    "required": True
                }]}
            },
            "capabilities": {
                "tools": [{"tool_id": "excel_tool"}],
                "memory": {"enabled": True, "mode": "CORTEX"}
            },
            "governance": {"timeout_ms": 120000, "max_cost_usd": 0.10}
        }
    },
    {
        "key": "write_docx_report_action",
        "payload": {
            "name": "bi-write-docx-report",
            "display_name": "BI DOCX Report Writer",
            "description": "Writes a comprehensive narrative business report in DOCX format with executive summary, detailed analysis, and recommendations.",
            "goal": "Produce a professional narrative report that tells the story behind the numbers — what happened, why it matters, and what to do next.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["bi-engine", "docx", "narrative-report", "writing"],
            "identity": {
                "system_prompt": "You are a senior business analyst writing a weekly performance report. Structure:\n\n1. EXECUTIVE SUMMARY (1 page): Top 3 highlights, top 3 concerns, key recommendation\n2. PERFORMANCE OVERVIEW: Revenue, costs, margins with period comparisons\n3. SEGMENT ANALYSIS: Performance by product/region/customer segment\n4. ANOMALY REPORT: Unusual patterns detected and their likely causes\n5. FORECAST & OUTLOOK: Projected trajectory and confidence levels\n6. RECOMMENDATIONS: 3-5 specific, actionable recommendations with expected impact\n7. METHODOLOGY: Data sources, analysis methods, and limitations\n\nWrite in a professional but accessible tone. Use specific numbers, not vague language.",
                "behavioral_constraints": [
                    "Every claim must reference specific data points",
                    "Include period-over-period comparisons throughout",
                    "Recommendations must be specific and actionable, not generic",
                    "Executive Summary must fit in approximately 1 page"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.5, "reasoning_mode": "CHAIN_OF_THOUGHT"},
                "context_policy": {"type": "FULL", "summarize_threshold": 25000}
            },
            "planning": {
                "static_plan": {"enabled": True, "steps": [{
                    "step_id": "step_1", "order": 1,
                    "name": "Write Narrative Report",
                    "description": "Generate DOCX report with full narrative analysis",
                    "type": "TOOL_CALL",
                    "target": {"tool_id": "docx_tool", "prompt_template": "{{input}}"},
                    "required": True
                }]}
            },
            "capabilities": {
                "tools": [{"tool_id": "docx_tool"}],
                "memory": {"enabled": True, "mode": "CORTEX"}
            },
            "governance": {"timeout_ms": 180000, "max_cost_usd": 0.25}
        }
    },
    {
        "key": "build_exec_deck_action",
        "payload": {
            "name": "bi-build-exec-deck",
            "display_name": "BI Executive Deck Builder",
            "description": "Creates an executive presentation deck in PPTX format with KPI slides, analysis deep-dives, and recommendation slides.",
            "goal": "Build a board-ready presentation that communicates key business metrics, insights, and recommendations in a visually compelling format.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["bi-engine", "pptx", "presentation", "executive"],
            "identity": {
                "system_prompt": "You are a management consulting presentation specialist. Create a PPTX deck with:\n\nSlide 1: TITLE — Report title, date range, prepared by\nSlide 2: EXECUTIVE SUMMARY — 3 key takeaways, overall status (green/yellow/red)\nSlide 3: KPI SCORECARD — Key metrics with arrows (↑↓→) and RAG status\nSlide 4: REVENUE ANALYSIS — Revenue trends, breakdown by segment\nSlide 5: COST ANALYSIS — Cost trends, margin evolution\nSlide 6: ANOMALIES & RISKS — Flagged items requiring attention\nSlide 7: FORECAST — Projections for next quarter\nSlide 8: RECOMMENDATIONS — Top 3-5 action items with owners and deadlines\nSlide 9: APPENDIX — Data sources and methodology\n\nKeep text concise — bullet points, not paragraphs. Data-heavy, not text-heavy.",
                "behavioral_constraints": [
                    "Maximum 6 bullet points per slide",
                    "Include specific numbers on every data slide",
                    "Use RAG (Red/Amber/Green) status indicators",
                    "Each recommendation must have an owner and timeline"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.4, "reasoning_mode": "CHAIN_OF_THOUGHT"},
                "context_policy": {"type": "FULL", "summarize_threshold": 20000}
            },
            "planning": {
                "static_plan": {"enabled": True, "steps": [{
                    "step_id": "step_1", "order": 1,
                    "name": "Build Executive Deck",
                    "description": "Create PPTX presentation with KPI and analysis slides",
                    "type": "TOOL_CALL",
                    "target": {"tool_id": "pptx_tool", "prompt_template": "{{input}}"},
                    "required": True
                }]}
            },
            "capabilities": {
                "tools": [{"tool_id": "pptx_tool"}],
                "memory": {"enabled": True, "mode": "CORTEX"}
            },
            "governance": {"timeout_ms": 180000, "max_cost_usd": 0.20}
        }
    },
    {
        "key": "compile_pdf_action",
        "payload": {
            "name": "bi-compile-pdf",
            "display_name": "BI PDF Compiler",
            "description": "Compiles the final polished PDF report package from the narrative analysis content.",
            "goal": "Produce a publication-ready PDF that combines the executive summary, analysis, and recommendations into a single professional document.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["bi-engine", "pdf", "final-output", "compilation"],
            "identity": {
                "system_prompt": "You are a document publishing specialist. Take the narrative report content and compile it into a professionally formatted PDF with:\n- Table of contents\n- Page numbers\n- Professional headers/footers\n- Consistent typography\n- Section breaks between major sections",
                "behavioral_constraints": [
                    "Preserve all data points and citations from the source content",
                    "Maintain heading hierarchy from the narrative report",
                    "Include page numbers and table of contents"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "REACT"}
            },
            "planning": {
                "static_plan": {"enabled": True, "steps": [{
                    "step_id": "step_1", "order": 1,
                    "name": "Compile Final PDF",
                    "description": "Generate professionally formatted PDF from report content",
                    "type": "TOOL_CALL",
                    "target": {"tool_id": "pdf_generator", "prompt_template": "{{input}}"},
                    "required": True
                }]}
            },
            "capabilities": {
                "tools": [{"tool_id": "pdf_generator"}],
                "memory": {"enabled": True, "mode": "CORTEX"}
            },
            "governance": {"timeout_ms": 120000, "max_cost_usd": 0.10}
        }
    },
    {
        "key": "consistency_check_action",
        "payload": {
            "name": "bi-consistency-check",
            "display_name": "BI Cross-Document Validator",
            "description": "Validates that the same KPI numbers appear consistently across all generated documents (Excel, DOCX, PPTX, PDF).",
            "goal": "Ensure data integrity across all report artifacts. The revenue number in the Excel must match the DOCX narrative must match the PPTX slide.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["bi-engine", "qa", "validation", "consistency"],
            "identity": {
                "system_prompt": "You are a quality assurance analyst. Write Python code to:\n1. Extract key metrics from all generated document summaries\n2. Compare each metric across documents (Excel vs DOCX vs PPTX)\n3. Flag any discrepancies with severity (CRITICAL if >1% difference, WARNING if <1%)\n4. Produce a consistency matrix showing PASS/FAIL for each metric-document pair\n5. Output an overall QA verdict: PASS, PASS_WITH_WARNINGS, or FAIL\n\nIf the input contains document summaries rather than files, compare the numbers in the text.",
                "behavioral_constraints": [
                    "Check at minimum: total revenue, total cost, profit margin, customer count",
                    "Report exact values found in each document, not just pass/fail",
                    "A >1% discrepancy in any financial metric is CRITICAL",
                    "Output structured JSON with the consistency matrix"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "CHAIN_OF_THOUGHT"},
                "context_policy": {"type": "FULL", "summarize_threshold": 20000}
            },
            "planning": {
                "static_plan": {"enabled": True, "steps": [{
                    "step_id": "step_1", "order": 1,
                    "name": "Validate Cross-Document Consistency",
                    "description": "Run Python consistency checks across all documents",
                    "type": "TOOL_CALL",
                    "target": {"tool_id": "sandbox_executor", "prompt_template": "{{input}}"},
                    "required": True
                }]}
            },
            "capabilities": {
                "tools": [{"tool_id": "sandbox_executor"}],
                "memory": {"enabled": True, "mode": "CORTEX"}
            },
            "governance": {"timeout_ms": 60000, "max_cost_usd": 0.10}
        }
    },
    {
        "key": "archive_outputs_action",
        "payload": {
            "name": "bi-archive-outputs",
            "display_name": "BI Report Archiver",
            "description": "Organizes all generated report artifacts into a dated folder structure with a manifest file listing all deliverables.",
            "goal": "Create a clean, organized archive of all report artifacts with a manifest that lists every file, its type, size, and creation timestamp.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["bi-engine", "archive", "delivery", "organization"],
            "identity": {
                "system_prompt": "You are a report delivery specialist. Use terminal commands to:\n1. Create a dated output directory: /tmp/bi-reports/YYYY-MM-DD/\n2. Copy all generated files (Excel, DOCX, PPTX, PDF, PNGs) to the directory\n3. Create a manifest.json listing all files with: filename, type, size_bytes, created_at\n4. List the final directory contents with ls -la\n5. Print the full archive path for retrieval",
                "behavioral_constraints": [
                    "Always create the date-stamped directory structure",
                    "Include ALL generated artifacts in the manifest",
                    "Print the final ls -la output for verification",
                    "Never delete original files — only copy to archive"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "REACT"},
                "context_policy": {"type": "FULL", "summarize_threshold": 8000}
            },
            "planning": {
                "static_plan": {"enabled": True, "steps": [{
                    "step_id": "step_1", "order": 1,
                    "name": "Archive Report Files",
                    "description": "Organize and archive all report artifacts with manifest",
                    "type": "TOOL_CALL",
                    "target": {"tool_id": "terminal_tool", "prompt_template": "{{input}}"},
                    "required": True
                }]}
            },
            "capabilities": {
                "tools": [{"tool_id": "terminal_tool"}],
                "memory": {"enabled": True, "mode": "CORTEX"}
            },
            "governance": {"timeout_ms": 30000, "max_cost_usd": 0.05}
        }
    },
]
