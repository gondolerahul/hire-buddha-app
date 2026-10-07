# HireBuddha Platform v2.0 - Comprehensive Requirements Document

This document outlines the core features, functionalities, business rules, and technical constraints of the HireBuddha v2.0 platform. It serves as a comprehensive guide for the testing and validation team to develop test plans, test cases, and test data.

## 1. System Overview & Architecture
HireBuddha is a multi-tenant, AI-driven platform that supports complex multi-agent workflows, real-time voice/messaging (WhatsApp) streaming, document processing (RAG), and a comprehensive billing/costing engine.

### 1.1 Multi-Tenancy Hierarchy
*   **App Admin:** Global platform administrators.
*   **Partner:** Reseller or parent organization managing multiple tenants. Administered by `partner_admin`.
*   **Tenant:** The primary customer entity holding configurations, credits, and AI resources. Administered by `tenant_admin`.
*   **User:** End-users within a tenant. Role defaults to `user`.

## 2. Authentication & Authorization (RBAC)
*   **Registration:** Users can register standard flow (Email/Password) or via OAuth (Google, Microsoft).
*   **Authentication:** JWT-based stateless authentication with strict 15-minute access token expiry and 7-day refresh token bounds (HttpOnly cookies).
*   **Roles & Permissions:**
    *   `app_admin`: Full system access, can manage partners/tenants.
    *   `partner_admin`: Can manage their own partner settings and associated tenants.
    *   `tenant_admin`: Can manage users, billing, AI configurations, and campaigns for their specific tenant.
    *   `user`: Can access AI features and dashboards assigned to their tenant.
*   **Company State:** Tenants/Partners can be `suspended`. A custom middleware (`CompanySuspensionMiddleware`) blocks all non-public API access if the company is suspended.

## 3. AI Platform Engine
The core of the system is recursive, multi-agent AI processes, defined through `HierarchicalEntity` models.

### 3.1 Hierarchical Entities
*   **Types:** `Action`, `Skill`, `Agent`, `Process`.
*   **Hierarchical Execution:** A `Process` can execute an `Agent`, which executes a `Skill`, which executes an `Action`. 
*   **Configurations:** Entities have granular settings for:
    *   **Identity:** Name, description, instructions/prompt, model choice, provider.
    *   **Goveranance & HITL:** Strict human-in-the-loop (HITL) requirements (Require Approval, Max Auto Retries). If HITL is enabled, execution pauses waiting for a human response (`approve`, `reject`, `modify`).
    *   **Capabilities & Tools:** Associated tools (Web Search, File Writing, Calculator, PDF Generation, Email fetching, etc.).
    *   **Memory & RAG:** Vector search across uploaded `Documents` via Gemini text embeddings.

### 3.2 Execution Runs
*   **Asynchronous Processing:** Long-running executions are handled via `Arq` background tasks.
*   **Cost Tracking:** Every LLM interaction and tool usage logs cost in standard USD based on the `IntegrationRegistry` pricing.
*   **Real-time Observability:** SSE (Server-Sent Events) push execution logs to the frontend in real-time. Wait time constraints and token consumption are tracked granularly.

## 4. Voice & WhatsApp Streaming (Campaigns)
The platform integrates directly with Twilio and Tata Tele for real-time customer interactions.

### 4.1 Number Routing & Assignment
*   **DID Management:** 1:1 mapping of phone numbers to specific `Agents` via `CustomerPhoneNumber` assignments.
*   **Routing Logic:** Incoming calls/messages to a specific number automatically resume conversation history and trigger the assigned AI `Agent`.

### 4.2 Voice Campaigns (Auto-Dialer)
*   **Bulk Execution:** Users can upload CSVs of contacts. The system enforces strict CSV validation (handling headers and mandatory phone strings).
*   **Execution Strategy:** The `CampaignExecutor` handles concurrent calling (throttling max concurrent calls and max calls per hour limits).
*   **Webhooks:** Active WebSocket streams (`stream_sid`) are maintained linking the Twilio/Tata Tele connection directly to the AI text-to-speech/speech-to-text loop.

## 5. Billing & Subscription Engine
A highly granular, priority-based billing system controls consumption.

### 5.1 Billing Formula (Total Billing - TB)
Total Billing for any usage event is calculated dynamically:
`TB = (c * mf) + (c * mf * pf) + (c * mf * spf) - (c * mf * d)`
*   `c`: Base unit cost (from Integrations config)
*   `mf`: Multiplier Factor
*   `pf`: Platform Fee %
*   `spf`: Sales Partner Fee %
*   `d`: Discount %

### 5.2 Credit Wallets (Consumption Priority)
The system consumes credits in a strict priority order before allowing tasks to execute:
1.  **Daily Credits:** Refreshed to $5 daily at midnight. No carryover.
2.  **Wallet Balance (PAYG):** Top-ups processed via **Razorpay**. Valid for 365 days. (Used only if account model is `pay_as_you_go`).
3.  **Subscription Credits:** Awarded monthly via active subscriptions. (Used if account model is `subscription`). Includes a bonus % explicitly allocated during subscription creation.

*Constraint:* If all three buckets reach $0, `InsufficientCreditsError` exceptions block any further LLM or Telecom usage.

## 6. Config & Integrations
*   **Integration Registry:** External API keys (OpenAI, Twilio, Gemini, Razorpay, Tata Tele, Outlook/Gmail) are securely stored here.
*   **Encryption:** `encrypted_api_key` utilizes AES-256-GCM symmetric encryption using a master key from environment variables.
*   **Email Connections:** Dedicated IMAP/SMTP endpoints validate credentials via simple `NOOP` login sequences before storing encrypted App Passwords.

## 7. Media & Assets
*   **Call Content:** Audio recordings of calls and generated images/videos are stored locally (relative paths).
*   **Call Intelligence:** Post-call processing generates a `transcript`, `summary`, and `sentiment` mapping, linking the `voice_session` to the stored asset path.

## 8. Frontend Interface
Built with React, Vite, and React Router. Key accessible views:
*   `/dashboard`: High-level metrics.
*   `/ai/entities`: The Entity Builder canvas for complex multi-agent setup.
*   `/ai/executions` & `/ai/approvals`: Real-time monitoring of runs and manual human-in-the-loop intervention forms.
*   `/streaming/campaigns`: Setup auto-dialer campaigns with CSV upload widgets and real-time active call monitoring status.
*   `/integrations`: Form interfaces to input keys for various LLM, Storage, and Communication providers.

## 9. Testing & Validation Focus Areas
To ensure high quality, the QA team should focus on:
1.  **Billing Exits:** Validate that when credits exhaust, executions fail gracefully across all contexts (chat, voice campaign, standard agent run).
2.  **Concurrency:** Test the `CampaignExecutor` throttling mechanism for Twilio/Tata outbound calls to ensure rate limits aren't violated.
3.  **Entity DAG Traversal:** Validate recursive execution (Process -> Agent -> Skill -> Action), ensuring contexts pass up and down the chain correctly and fail exactly when a sub-item fails.
4.  **RBAC Fencing:** Validate partner_admin cannot see the integrations/users of a different partner; validate tenant_admin cannot modify billing formula parameters (app_admin only).
5.  **Multi-Modal Websockets:** Validate that network disconnections within active Webhook instances (voice and WhatsApp) clean up pending database state.
