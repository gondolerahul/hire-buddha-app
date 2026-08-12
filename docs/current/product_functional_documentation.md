# HireBuddha — Product Functional Documentation

> **Platform Version:** 2.0.0 (GA)  
> **Author:** Buddha Cognitive Lab  
> **Last Updated:** June 2026  
> **Status:** Release-Ready Reference Manual

---

## 1. Product Paradigm: The Autonomous Digital Workforce

### 1.1 The Business Thesis: "Stop Hiring, Start Deploying"
HireBuddha is built to solve the resource scaling limits of solopreneurs and Small & Medium Enterprises (SMEs). In a traditional organization, expanding operations (e.g., entering new sales territories, scaling customer service, launching multi-channel marketing campaigns) requires a linear increase in human headcount. Human hiring introduces significant frictions:
*   **Recruiting Overhead**: Sourcing, screening, and interviewing candidates.
*   **Training and Onboarding Delay**: A typical employee requires 30 to 90 days to achieve full productivity on company-specific context.
*   **Fixed Salary Commitments**: Payroll, payroll taxes, health insurance, PF contributions, paid leaves, and severance commitments.
*   **Attrition Risk**: Institutional knowledge leaves the company when the employee resigns.
*   **Performance Variance**: Human execution varies based on fatigue, mood, training, and individual capabilities.

HireBuddha replaces the human salary model with the **AI Employee Deployment Model**. Companies do not hire departments; they deploy pre-built, context-trained AI Employees in under 10 minutes.

| Dimension | Human Workforce | AI Workforce (HireBuddha) |
|---|---|---|
| **Compensation Model** | Fixed monthly salaries + benefits + overhead. | SKU-based, pay-for-performance cost models (tokens/minutes). |
| **Availability** | 8 hours/day, 5 days/week, excluding holidays. | 24/7/365 continuous operation with zero latency. |
| **Scaling Velocity** | 30 to 90 days of recruitment and onboarding. | Instantaneous duplication (cloning) in <10 seconds. |
| **Operational Consistency** | Subject to human error, cognitive fatigue, and churn. | Deterministic adherence to guidelines and prompt parameters. |
| **Context Retention** | Lost upon resignation or role transition. | Shared, permanent memory (CORTEX) saved in the tenant DB. |

### 1.2 The Core 3-Step Lifecycle: Design, Deploy, Employ

```mermaid
graph TD
    subgraph 1. DESIGN STAGE
        A[Define Persona Name & Role] --> B[Assign System Prompt Charter]
        B --> C[Configure Personality Sliders]
        C --> D[Bind Built-in/Custom Tools]
        D --> E[Upload Knowledge Base Docs]
    end

    subgraph 2. DEPLOY STAGE
        F[Assign Inbound/Outbound Phone Lines] --> G[Register WhatsApp Business API]
        G --> H[Authenticate SMTP/IMAP Email Accounts]
        H --> I[Link Social Accounts via OAuth 2.0]
    end

    subgraph 3. EMPLOY STAGE
        J[Trigger Outbound Campaigns] --> K[Auto-Answer Inbound Calls/Messages]
        K --> L[Run Background Processes]
        L --> M[Monitor real-time Cost/Run Traces]
    end

    1. DESIGN STAGE --> 2. DEPLOY STAGE
    2. DEPLOY STAGE --> 3. EMPLOY STAGE
```

#### Step 1: Design
Using the **No-Code AI Architect**, operators design their digital employee:
*   **Name & Title**: Define identities (e.g., "Sarah - Outbound BDR").
*   **System Prompt Charter**: The "job description" defining boundaries, guidelines, logic gates, and explicit behavior parameters.
*   **Personality Matrix**: Precision tuning sliders for Tone, Verbosity, Empathy, Humor, Formality, and Decision Confidence.
*   **Tool Bindings**: Activating tools from the registry (e.g., Web Search, PDF Generator, Sandbox Code Executor).
*   **Knowledge Base Injection**: Uploading business documents to populate semantic vector tables.

#### Step 2: Deploy
Connecting the virtual employee to communication networks:
*   **Voice Integration**: Purchasing Twilio, smartflo (Tata Tele), or Exotel lines.
*   **Messaging**: Authorizing Twilio WhatsApp Business APIs.
*   **Email**: Providing SMTP/IMAP credentials with secure app-specific passwords.
*   **Social & Ad Channels**: Authorizing OAuth connections to LinkedIn, Facebook, Google Ads, and YouTube.

#### Step 3: Employ
Activating the AI:
*   Inbound channels answer automatically and process messages.
*   Outbound engines dial contact campaigns, run lead qualifiers, and draft proposals.
*   The system updates credit wallets and streams real-time execution logs (SSE traces).

---

## 2. The AI Workforce Hierarchy

HireBuddha structures autonomous agents into an organizational hierarchy. This hierarchy avoids monolithic prompt sprawl, separating macro strategy from micro tool invocation.

```
┌────────────────────────────────────────────────────────┐
│                        PROCESS                         │
│  - Goal: "Reactivate stale Q1 leads"                   │
│  - Executor: DAG / Parallel Steps / Debate             │
├────────────────────────────────────────────────────────┤
│                         AGENT                          │
│  - Role: Outbound Telephony SDR                        │
│  - Executor: Dialog / SingleStep                       │
├────────────────────────────────────────────────────────┤
│                         SKILL                          │
│  - Objective: Draft customized proposals              │
│  - Executor: ToolBurst / SingleStep                    │
├────────────────────────────────────────────────────────┤
│                         ACTION                         │
│  - Task: "Compute loan ROI case"                       │
│  - Executor: Built-in Tool Call                        │
└────────────────────────────────────────────────────────┘
```

### 2.1 The Four Organizational Tiers

#### 1. Process (C-Suite Orchestrator)
A **Process** represents a macro business workflow. It coordinates multiple departments (Agents) or operations (Skills).
*   *Example*: "Quarterly Lead Nurture and Activation Campaign".
*   *Behavior*: Receives target inputs (e.g., CSV lists), creates a dynamic dependency graph, schedules child runs, handles parallel branches, and summarizes final business outcomes.

#### 2. Agent (Manager / Department Head)
An **Agent** manages a specific communication channel or domain, maintaining conversational state and applying domain guidelines.
*   *Example*: "Sarah - Lead Qualification Phone Rep".
*   *Behavior*: Answers phone calls, maintains a running dialog, reads user intent, searches KB documents, and routes complex requests to specialists.

#### 3. Skill (Specialist / Task Executor)
A **Skill** is an optimized block of logic focused on a single technical task.
*   *Example*: "Contract Generation & E-Signature Routing".
*   *Behavior*: Takes raw customer variables, parses templates, runs math calculations, creates documents, and delivers them via email or API.

#### 4. Action (Individual Worker)
An **Action** is an atomic, tool-assisted execution. It represents the interface between the AI Engine and external systems.
*   *Example*: "Query Salesforce for Company ID".
*   *Behavior*: Calls a registered tool, validates formats, handles timeouts, and reports outputs.

### 2.2 Execution Reasoning Modes
The hierarchy matches reasoning strategies to step complexity:
*   **ReAct (Reason-then-Act)**: The engine decides which tool to call, runs the tool, observes the results, and loops until complete. Best for linear tasks and database operations.
*   **Chain-of-Thought (CoT)**: The model writes out its step-by-step logic explicitly before generating final outputs. Best for document drafting and legal review.

---

## 3. The Built-In Talent Stack (Tools)

HireBuddha provides virtual employees with **20+ built-in tools** out of the box, organized by capability.

### 3.1 Web Intelligence Suite

#### Web Search
*   *Functional Purpose*: Real-time internet search to fetch updated data (e.g., company news, market capitalization, competitor pricing).
*   *Providers*: DuckDuckGo API (default), Google Custom Search API.
*   *Inputs*: Raw text search query.
*   *Outputs*: Markdown-formatted search result snippets with titles and source URLs.

#### Web Scraper
*   *Functional Purpose*: Downloads the text contents of a target webpage.
*   *Backend*: Beautiful Soup and Firecrawl API.
*   *Inputs*: Target URL.
*   *Outputs*: Cleaned, markdown-rendered text of the webpage, filtering out headers, footers, and scripts.

#### Headless Browser
*   *Functional Purpose*: Interacts with dynamic, JavaScript-rendered websites.
*   *Backend*: Playwright.
*   *Capabilities*: Click elements, fill forms, scroll pages, wait for network idle, capture screenshots, and download files.
*   *Inputs*: JSON-structured action block (e.g., `{"actions": [{"type": "navigate", "url": "..."}, {"type": "click", "selector": "#submit-btn"}]}`).
*   *Outputs*: Target text, HTML source, or binary image of the page view.

### 3.2 Email Operations Suite

```
  [ INCOMING EMAIL ] ──► IMAP Ingest ──► Classify ──► KB Lookup ──► Draft ──► SMTP Send
```

*   **Email Ingest**: Connects to the user's Gmail/Outlook via IMAP, fetching unread messages.
*   **Email Classify**: Analyzes incoming subject lines and body copy for:
    *   *Sentiment*: Positive, Neutral, Negative, Angry.
    *   *Urgency*: Low, Medium, High, Immediate.
    *   *Intent Category*: Support, Sales Pitch, Billing Query, Spam, General.
*   **Email Draft**: Generates contextual, brand-aligned email drafts based on semantic KB documentation.
*   **Email Send**: Transmits messages via SMTP.

### 3.3 Document & Data Factory

#### Excel Tool
*   *Functional Purpose*: Modifies, parses, and creates spreadsheet files.
*   *Backend*: `openpyxl`.
*   *Capabilities*: Auto-injects formulas, applies font weights, formats tables, and creates chart tabs.
*   *Inputs*: JSON matrix of rows and cell properties.

#### PDF Generator
*   *Functional Purpose*: Creates formatted corporate PDFs.
*   *Backend*: `WeasyPrint` (HTML-to-PDF rendering engine).
*   *Input*: HTML/CSS templates containing dynamic context variables (e.g., `{{client_name}}`).

#### Word (DOCX) Generator
*   *Functional Purpose*: Generates Microsoft Word document templates.
*   *Backend*: `python-docx`.
*   *Input*: JSON structure describing paragraphs, tables, lists, and formatting.

#### PowerPoint (PPTX) Generator
*   *Functional Purpose*: Compiles presentations.
*   *Backend*: `python-pptx` (Python) and `pptxgenjs` (Frontend export).
*   *Input*: Slide definitions, titles, body lists, and style properties (colors, fonts).

#### File Writer
*   *Functional Purpose*: Writes arbitrary text, CSV data, or code to local tenant workspaces.

### 3.4 Creative Studio
*   **Image Generation**: Leverages Google Gemini Image APIs to generate marketing banners, social media cards, and product mockups.
*   **Video Generation**: Connects to Google Veo 3.1 APIs to generate high-fidelity, short marketing videos and animations from prompt briefs.

### 3.5 Precision & Dev Tools
*   **Calculator**: Evaluates complex mathematical formulas safely (e.g., compound interest, ROI splits), avoiding model math errors.
*   **Sandbox Code Executor**: Runs arbitrary Python code inside a secure, isolated container/subprocess sandbox. Ideal for data scrubbing, complex calculations, or regex processing.
*   **Terminal Tool**: Runs shell commands inside a sandbox to run scripts, CLI commands, or interface with external servers.

---

## 4. The AI Agent Marketplace (42 RevOps Agents)

HireBuddha provides **42 pre-built, production-ready AI Agents** organized into **five core pillars** representing the complete Revenue Operations (RevOps) lifecycle.

```
                            ┌─────────────────────────┐
                            │    REVOPS ENGINE (42)   │
                            └────────────┬────────────┘
      ┌──────────────────────┬───────────┴───────────┬──────────────────────┐
      ▼                      ▼                       ▼                      ▼
Revenue Intel (7)      Demand Gen (10)      Revenue Acq (9)         Cust Success (10)
- Revenue Planner      - Campaign Planner   - Prospector            - Onboarding Orchestrator
- ICP Analyst          - Content Generator  - Outbound Sequencer    - Health Scorer
- Forecaster           - Lead Scorer        - MEDDPICC Scorer       - Churn Predictor
- CRM Governor         - Lead Router        - Demo Preparer         - Renewal Manager
- Attribution Engine   - Nurture Manager    - ROI & Proposal Writer - QBR Slide Builder
- Leak Finder          - ABM Director       - Risk Analyzer         - Support Ticket Triager
- Meeting intelligence - Paid Media Audits  - Closed-Won Handoff    - KB Article Writer
                       - Social Media Rep   - Win/Loss Analyst      - CSAT VOC Analyst
                       - Event Coordinator  - Battlecard Auditor    - Customer Advocate
                       - Website CRO                                - Meeting Prep (Ops)
                                                                    - Enablement Coach (Ops)
                                                                    - KPI Alerter (Ops)
                                                                    - Process Improver (Ops)
                                                                    - Tech Stack Monitor (Ops)
```

### 4.1 Revenue Intelligence Pillar (7 Agents)
These agents provide strategic direction, forecasting, and data cleanliness.

*   **Revenue Planner**: Analyzes previous financial sheets, models market trends, identifies target pipelines, and drafts planning OKRs.
*   **ICP Intelligence**: Analyzes customer databases (closed-won vs. churned) to update Ideal Customer Profiles (ICP) and lead scoring logic.
*   **Forecaster**: Generates weekly AI forecasts (commit, best-case, closed-won probabilities) based on CRM updates and pipeline movement.
*   **CRM Data Governor**: Automatically audits CRM accounts, standardizes fields, deduplicates records, and extracts fields from call recordings.
*   **Attribution & Analytics**: Analyzes lead conversion events across channels to build multi-touch attribution reports.
*   **Revenue Leak Detector**: Scans conversion funnel drop-offs and flags billing anomalies or self-serve friction points.
*   **Meeting Intelligence**: Transcribes meetings, extracts MEDDPICC qualifiers, and drafts rep-specific coaching notes.

### 4.2 Demand Generation Pillar (10 Agents)
These agents act as a digital marketing department.

*   **Campaign Planner**: Evaluates pipeline gaps to generate campaign briefs and budget splits.
*   **Content Generator**: Identifies target keywords and generates SEO blogs, LinkedIn updates, and landing page copies.
*   **Lead Scorer**: Evaluates behavioral signals and company fit to promote leads to MQL status.
*   **Lead Router**: Routes MQLs to sales reps and monitors SLAs, escalating after 2 hours of inactivity.
*   **Nurture Orchestrator**: Runs personalized email drip sequences based on subscriber interaction.
*   **ABM Orchestrator**: Compiles target account research briefs and messaging advice for high-value prospects.
*   **Paid Media Optimizer**: Audits Google/Meta Ads daily to auto-adjust budgets and bids.
*   **Social Media Agent**: Schedules organic social posts, monitors mentions, and drafts comments.
*   **Event & Webinar Agent**: Manages invites, reminders, registrations, and post-event nurture workflows.
*   **Website CRO Optimizer**: Evaluates website behavior to recommend copy and layout improvements.

### 4.3 Revenue Acquisition Pillar (9 Agents)
These agents automate outbound sales workflows.

*   **Prospecting Researcher**: Generates enriched prospect lists (news, LinkedIn details) and drafts personalized pitches.
*   **Outbound Sequencer**: Runs multi-channel outbound outreach sequences (email, social, call scripts).
*   **MEDDPICC Scoring Agent**: Scores sales opportunities based on customer calls and emails, tracking deal qualification.
*   **Demo Prep Assistant**: Drafts demo talking points customized to discovery notes.
*   **ROI & Proposal Agent**: Runs financial calculations to build proposals and contracts.
*   **Deal Risk Agent**: Scans deals daily to flag risks (e.g., loss of champion, competitor activity).
*   **Closed-Won Handoff**: Auto-provisions customer folders, assigns CSMs, and schedules kickoff campaigns.
*   **Win/Loss Analyst**: Audits closed-lost deals to identify competitor trends or pricing issues.
*   **Competitive Battlecard Agent**: Monitors competitor updates to refresh objection-handling sheets.

### 4.4 Customer Expansion Pillar (10 Agents)
These agents manage customer success and expansions.

*   **Onboarding Orchestrator**: Guides new clients through setup guides and triggers survey links.
*   **Health Scoring Agent**: Builds customer health scores based on usage metrics and support tickets.
*   **Churn Predictor**: Flags accounts showing churn warning signs 60-90 days in advance.
*   **Expansion Opportunity Agent**: Flags accounts approaching usage limits to propose upgrades.
*   **Renewal Manager**: Automates renewal outreach, generates contracts, and follows up on signatures.
*   **QBR Deck Generator**: Autogenerates customer review decks with usage graphs.
*   **Support Ticket Triager**: Classifies support emails, auto-resolves FAQs, and routes P1 tickets.
*   **Knowledge Base Writer**: Reviews common ticket patterns and auto-drafts customer-facing articles.
*   **Voice of Customer Analyst**: Gathers reviews, CSAT, and NPS scores to generate feedback reports.
*   **Customer Advocate Coordinator**: Identifies promoters to coordinate reviews and case studies.

### 4.5 Cross-Pillar Operations Pillar (5 Agents)
These agents synchronize operations and technology.

*   **RevOps Meeting Prep**: Coordinates agenda documents, gathers performance metrics, and tracks action items.
*   **Enablement Coach**: Compiles training guidelines customized to rep skill gaps.
*   **KPI Monitor & Alerter**: Tracks KPIs and triggers alerts on Slack or email on threshold breaches.
*   **Process Improver**: Identifies team process bottlenecks and proposes SOP updates.
*   **Tech Stack Monitor**: Audits SaaS tools utilization to flag unused licenses and save costs.

---

## 5. Omnichannel Presence & Outbound Campaigns

HireBuddha integrates agents into standard communications systems, enabling outbound call routing and messaging.

### 5.1 Real-Time Voice Calls (Speech-to-Speech)
HireBuddha voice agents can communicate via telephone with low latency.

```
 [ Carrier / Twilio ] ◄── SIP / WS ──► [ Unified Gateway ] ◄── PCM Stream ──► [ Gemini Live ]
                                                                                   │
                                                                                   ▼
                                                                           [ Voice Persona ]
```

*   **Bidirectional PCM Streaming**: Audio streams over secure WebSockets in 20ms chunks, avoiding the delay of text-to-speech.
*   **Supported Engines**:
    1.  *Google Gemini Live (Vertex AI)*: Features low-latency voice calling across 18 unique voices.
    2.  *Azure OpenAI Realtime*: High-fidelity realtime voice engine using GPT-4o voice presets.
*   **Telephony Integrations**: Twilio, Smartflo (Tata Tele), and Exotel.
*   **Voice Personas**: Custom voice profiles allow operators to adjustspeaking rates (0.5x to 2.0x) and pitch shifts.
*   **Voice Activity Detection (VAD)**:
    *   *Start of Speech Sensitivity*: Set to `HIGH` for fast barge-in detection when a user interrupts.
    *   *End of Speech Sensitivity*: Set to `LOW` to prevent cutting off the speaker during natural pauses.
    *   *Silence Duration*: 1000ms threshold before the agent starts its response.

### 5.2 Outbound Campaigns
The Outbound Campaign Engine automates call outreach.
*   **CSV Import & Validation**: Automatically parses numbers, checks formatting, and matches country codes.
*   **Concurrency Throttling**: Limits concurrent dial channels (e.g., maximum 15 parallel calls) to stay within carrier limits.
*   **Real-time Campaign Dashboard**: Monitors contact list completion, conversion rates, cost-per-minute, and overall sentiment.

---

## 6. The AI Mind: Memory & Personality Design

### 6.1 The 4-Tier Memory System

```
  ┌────────────────────────────────────────────────────────┐
  │ 1. Working Memory (Temporary Run context)             │
  ├────────────────────────────────────────────────────────┤
  │ 2. Episodic Memory (10 latest user-agent conversations) │
  ├────────────────────────────────────────────────────────┤
  │ 3. Semantic Memory (Vector search over company files)  │
  ├────────────────────────────────────────────────────────┤
  │ 4. CORTEX Tree Memory (Hierarchical cognitive context) │
  └────────────────────────────────────────────────────────┘
```

#### 1. Working Memory
Temporary scratchpad context used during a single run iteration. Contains template inputs, loop iteration metrics, and current step calculations.

#### 2. Episodic Memory
Stores conversational history. The memory router pulls the last 10 interactions per contact/agent to maintain conversation continuity.

#### 3. Semantic Memory (Knowledge Base)
Supports PDF, DOCX, TXT, and CSV file uploads.
*   **Chunking & Embedding**: Documents are chunked into 500-character segments with 10% overlap, converted to 768-dimension vectors using Gemini's `text-embedding-004`, and stored in a PostgreSQL database via `pgvector`.
*   **Context Retrieval**: When a query occurs, the system runs a cosine similarity vector search, ranking relevant document chunks.

#### 4. CORTEX Memory (Cognitive Tree)
A hierarchical tree memory structure that manages context windows for long-running workflows.
*   **Nodes Hierarchy**: Organizes information into nodes: `root`, `knowledge`, `finding`, `task`, `output`, and `checkpoint`.
*   **Viewport Slicing**: The perceiver selects relevant path segments from the tree, avoiding LLM context limit issues.
*   **Auto-Checkpointing**: Generates summary nodes when the context reaches the threshold (default: 8,000 tokens), preserving historical progress.

### 6.2 Personality Design Matrix
Every virtual employee is configured via a sliding-scale Personality Matrix:
*   **Tone**: Slider ranges between Professional, Friendly, Empathetic, and Assertive.
*   **Verbosity**: Controls response brevity (Concise, Moderate, or Verbose).
*   **Empathy**: Scales emotional response matching (0.0 to 1.0).
*   **Humor**: Scales wit and playfulness (0.0 to 1.0).
*   **Formality**: Configures casual vs. formal language styles.
*   **Custom Rules**: Specific behavioral parameters (e.g., "Never discuss competitor pricing; always direct to support").

---

## 7. Economics & Cost Attribution

### 7.1 Wallet Pools
HireBuddha uses a 3-tier wallet priority system:
1.  **Daily Credits**: Every tenant gets $5.00 of free daily credits. These expire at midnight and do not roll over.
2.  **PAYG Wallet Balance**: Pay-as-you-go funds topped up via Razorpay, valid for 365 days.
3.  **Subscription Credits**: Monthly recurring credits issued under active plans (Starter, Growth, Enterprise) with up to 40% bonus credits.

### 7.2 The Billing Cost Formula
Every run, tool call, voice minute, and token consumption is recorded in a centralized ledger. The billable amount is computed using:

$$\text{Billed Amount} = (\text{Base Cost} \times \text{Multiplier}) \times (1 + \text{Platform Fee \%} + \text{Partner Fee \%} - \text{Discount \%})$$

This enables:
*   **Partners** to white-label the platform and add their own service markup margins.
*   **Tenants** to track costs down to the micro-cent for every single task execution.
*   **Users** to see direct ROI (e.g., comparing the cost of an AI call to a human call center rep).

### 7.3 Minimum Wallet Balance Thresholds
To prevent overspend, the credit service enforces minimum thresholds before execution runs start:

*   **Process Execution**: Requires minimum wallet balance of **$0.50** (covers plan generation and agent spawns).
*   **Agent Run**: Requires minimum wallet balance of **$0.05** (covers initial conversational turns).
*   **Skill Run**: Requires minimum wallet balance of **$0.02** (covers single template rendering).
*   **Action Run**: Requires minimum wallet balance of **$0.01** (covers single tool call).

Runs are blocked with an `InsufficientCreditsError` if the wallet balance falls below the target threshold.

---

## 8. Enterprise Governance & Security

### 8.1 Multi-Tenant Hierarchy
The platform isolation model utilizes a 4-level structure:

*   **App Admins (Buddha Cognitive Lab)**: View platform dashboards, modify integration settings, set baseline SKU costs, manage the global tool registry, and handle partner commissions.
*   **Partners**: Manage portfolios of Tenants, configure pricing multipliers, track earnings and commissions.
*   **Tenants**: Manage their specific workspace, users, AI employees, integrations, and wallets.
*   **Users**: Access designated AI features, monitor execution histories, and interact with the workspace.

### 8.2 Security Gates
*   **Key Vault**: External API keys and OAuth tokens are stored in the database encrypted via AES-256-GCM using a master key stored outside the database.
*   **Access Handshake**: Stateless JWT authentication handles API calls, using short-lived tokens (15 minutes) and HTTP-only cookie-refresh tokens (7 days).
*   **Company Suspension Middleware**: Instantly blocks API access for any Tenant marked as suspended in the DB, immediately terminating running campaigns and phone lines.
*   **Human-in-the-Loop (HITL) Checkpoints**: Pauses execution runs at designated checkpoints (e.g., before sending high-value emails or executing tools), alerting administrators for verification before resuming.
*   **Credit Circuit Breaker**: Evaluates accumulated run cost against the tenant's wallet balance after every step execution, raising an `InsufficientCreditsError` if the balance is depleted.
