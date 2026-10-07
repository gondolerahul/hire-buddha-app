# HB-Proto-3 Analytics & Reports Requirements

**Document Purpose**: This document outlines a comprehensive set of reporting and analytics requirements tailored to the specific roles defined in the Hierarchical Role-Based Access Control (RBAC) model of the HireBuddha (HB-Proto-3) platform.

**Data Sources**: These reports rely heavily on the system's robust observability and tracking schema, specifically referencing:
* `execution_runs` & `episodic_memories` (Execution Health, Output Summaries)
* `llm_interaction_logs` & `tool_interaction_logs` (Latency, Errors, Traceability)
* `usage_logs`, `credit_wallets`, & `billing_events` (Cost, Consumption, Margins)
* `payment_transactions` & `subscriptions` (MRR, Top-ups, Churn)

---

## 1. App Admin (`app_admin`)
*Focus: Global Platform Health, overarching revenue generation, gross margin optimization, and total infrastructure utilization.*

**A. Financial & Revenue Analytics**
1. **Global Revenue & Margin Report**: Consolidated view of Total Billings minus Base Costs. Breakdown of Platform Fees collected vs. actual expenditure to vendors (OpenAI, Gemini, Twilio, Tata).
2. **Subscription MRR Forecasting & Churn Matrix**: Tracks monthly recurring revenue via Razorpay and highlights risk domains based on shrinking user activity before renewal periods.
3. **SKU Optimization & Cost-Arbitrage Report**: Aggregation of raw consumption metrics globally, contrasting retail prices charged against wholesale vendor rates to identify margin compression.
4. **Credit Liability & Outstanding Wallet Balance**: Tracks the total unspent credits sitting in customer wallets globally to project financial liabilities.

**B. Platform Health & Operations**
5. **Global System Execution & Flow Health**: Success/failure/pause rates of all `ExecutionRun` instances highlighting systemic bottlenecks in recursive AI processes.
6. **LLM Performance & Fallback Analytics**: Analyzes how often dynamic planning falls back to static planning due to LLM version deprecations or rate-limiting.
7. **Tool Efficacy & Integrations Audit**: Tracks the latency, uptime, and error rates of built-in tools (Web scrapers, calculators, PDF generators).
8. **Active Channels & Concurrency Dashboard**: Metrics on active WebSocket connections, active audio streaming threads, and live WhatsApp integrations for infrastructure provisioning.

**C. Cross-Partner & Tenant Growth**
9. **Partner Performance Dashboard**: Comparison of revenue generation, tenant acquisition, and margin contribution across different `PARTNER` companies.
10. **Global Feature Adoption Heatmap**: Visualization of which hierarchical entities (`AGENT`, `SKILL`, `ACTION`) are predominantly configured across the entire ecosystem.

---

## 2. App User (`app_user`)
*Focus: Internal platform operations, technical support, debugging, and maintaining underlying system integrations.*

**A. Technical Operations & Debugging**
1. **Global Incident & Traceability Report**: Granular logging of failed `ExecutionRuns`, tracing back to specific `LLMInteractionLog` timeouts or `ToolInteractionLog` extraction failures.
2. **Provider Integration Health**: Uptime tracking and error rate plotting for external platforms (Google Search API, Twilio Webhooks, Httpx Scraping instances).
3. **Execution Latency & Recursion Bottleneck Analysis**: Tracks the `execution_time_ms` across multi-level DAG (Directed Acyclic Graph) child executions to spot inefficient process designs.

**B. System Maintenance**
4. **Rate Limit & Vendor Quota Exhaustion Analytics**: Alerts on API thresholds nearing their maximum limits (e.g., Gemini RPM limits or Twilio concurrency bounds).
5. **Data Growth & Archival Readiness Report**: Tracks the explosive growth of `document_chunks` and `llm_interaction_logs` to advise when data purges or cold storage movements are necessary.
6. **Global HITL (Human-in-the-loop) SLA Report**: Identifies workflows hanging in a `PAUSED` state due to missing human approvals across the platform.

---

## 3. Partner Admin (`partner_admin`)
*Focus: Up-selling sub-tenants, monitoring aggregate sub-tenant margins, and managing the assigned tenant portfolio.*

**A. Portfolio Financials**
1. **Partner Commission & Accrued Fee Report**: Details the specific Sales Partner Fee (`spf`) revenue generated from their underlying tenants minus any applicable discounts (`d`) they provided.
2. **Aggregate Portfolio Billing & Top-Ups**: Total credit spend across all governed tenants, comparing Daily Credit utilization versus Wallet PAYG consumption.
3. **Tenant Subscription Downgrade/Upgrade Matrix**: Visibility into which tenants are upgrading their tiers versus churning out.

**B. Tenant Health & Sales Metrics**
4. **At-Risk Tenant Alerts (Wallet Depletion)**: Ranks tenants based on rapid credit consumption rates, showing which are running out of wallet balances and are prime targets for sales outreach.
5. **Top Performing Tenants by AI Yield**: Highlights "Power Users" who have successfully integrated complex recursive workflows.
6. **Feature Upsell Opportunities Heatmap**: Identifies tenants using basic chat features who have not yet configured Voice telephony or WhatsApp messaging.
7. **White-label Configuration Audit**: Ensures all sub-tenants are properly utilizing the partner's custom branding properties and mapped domain records.

---

## 4. Partner User (`partner_user`)
*Focus: First-line tenant success, onboarding, account management, and minor technical interventions.*

**A. Tenant Support & Success**
1. **Individual Tenant Health Scorecard**: A per-tenant view combining their recent activity logs, billing standing, and active integrations status.
2. **Tenant Onboarding Progression Tracking**: Tracks the milestones of new tenants (e.g., First Team Member added -> First API Key Configured -> First Agent Deployed).
3. **Tenant Configuration Error Logs**: Walled-off error reporting that just highlights setup mistakes made by their specific tenants (e.g., malformed prompt templates, invalid Twilio keys).

**B. Engagement Tracking**
4. **Tenant Support Ticket/Query Trends**: Categorizes the types of issues sub-tenants are hitting (e.g., billing confusion vs. API errors) to inform partner documentation.
5. **Custom Workflow Adoption Metrics**: Tracks when a tenant successfully moves from using standardized templates to deploying custom `hierarchical_entities`.
6. **Proactive Credit Top-up Alerts Report**: Flags tenants whose scheduled campaigns might fail due to insufficient funds occurring mid-run.

---

## 5. Tenant Admin (`tenant_admin`)
*Focus: Cost control, internal budget attribution, team productivity, and operational oversight of the AI deployments.*

**A. Internal Cost Allocation & Billing**
1. **Credit Consumption & Departmental Breakdown**: Daily burn rate of the Wallet. Clear visualizations outlining costs separated by channels: LLM vs. Voice vs. SMS vs. WhatsApp vs. APIs.
2. **User-level Cost Attribution & Activity Report**: Tracks internal spending and execution volumes broken down by individual `tenant_users`. Identifies which employee is triggering the most expensive tasks.
3. **Credit Depletion Forecasting**: Predictive model defining when the company's PAYG wallet will hit \$0 based on current recursive agent configurations.

**B. Workflow & Campaign Analytics**
4. **Campaign & ROI Analysis (Outbound Metrics)**: Deep dive into bulk execution runs. Tracks Total Inbound/Outbound minutes, average call duration, WhatsApp delivery rates, and conversion success.
5. **Agent Efficacy & Sentiment Trends**: Derived from `EpisodicMemory`, tracks the historically summarized interactions with external clients to determine positive vs negative operational outcomes.
6. **Automated vs. Manual Intervention Mix (HITL)**: Plots the percentage of tasks resolved entirely by AI versus tasks that required fallback Human-In-The-Loop approvals.
7. **Agent Error Rates & Remediation Matrix**: Shows which of their internally configured `AGENTS` or `SKILLS` fail most frequently so the Admin can refine the prompts or configurations.
8. **Channel Delivery Efficacy**: Compares the response rates across Text, Voice, and WhatsApp execution handlers.

---

## 6. Tenant User (`tenant_user`)
*Focus: Personal efficiency, individual task status checking, and day-to-day workflow management.*

**A. Task Execution & History**
1. **My Personal Task Backlog & History**: A historical report of all `ExecutionRuns` they specifically triggered. Includes inputs, dynamic plans generated, output summaries (from `EpisodicMemory`), and success/fail statuses.
2. **Execution Trace Debug View**: A simplistic UI report allowing them to click into a failed task and see exactly which nested `ACTION` or `TOOL` stumbled (e.g., "Web search returned zero results").
3. **Specific Campaign Conversion / Success Report**: If they own a specific workflow (like a customer outreach batch), this shows just the outcomes of that specific batch.

**B. Action Items & Productivity**
4. **Overdue HITL (Pending Approvals) Dashboard**: A focused, prioritized report highlighting workflows that are currently paused and awaiting their specific manual review/notes before continuing.
5. **Workflow Execution Timing & Time Saved**: Approximates the manual hours saved by tracking the total `execution_time_ms` vs the estimated time it would take a human to do it.
6. **Agent "Hallucination" or Feedback Flags Report**: Tracks items where the Tenant User had to downvote or correct an AI's output, helping them build a repository of refinement notes for the Tenant Admin.
7. **Personal Usage & Resource Limit Warning**: Shows their individualized token consumption and a warning if they are nearing daily limits imposed by their Tenant Admin.
