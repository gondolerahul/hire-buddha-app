# Phase 2 - Functional Specifications: HireBuddha Platform

## Introduction
The HireBuddha Platform (Phase 2) is a multi-tenant, agentic AI orchestration engine. It enables organizations to build, deploy, and monitor complex AI workflows using a combination of LLM agents, RAG (Retrieval-Augmented Generation), and structured DAG (Directed Acyclic Graph) orchestration.

---

## Epic 1: Multi-Tenant Foundation & Security
*Goal: Provide a secure, scalable, and isolated environment for multiple organizations (Partners and Tenants).*

### Feature 1.1: Hierarchical Multi-Tenancy
- **Description**: Supports a three-tier hierarchy: App Admin → Partner Admin → Tenant Admin/User.
- **Stories**:
    - As an **App Admin**, I can manage Partners and oversee the entire system.
    - As a **Partner Admin**, I can manage my own Tenants and Users.
    - As a **Tenant**, my data (agents, workflows, documents) is strictly isolated from other tenants.

### Feature 1.2: Advanced Authentication & RBAC
- **Description**: Secure access control using OAuth2/OIDC and granular Role-Based Access Control.
- **Stories**:
    - As a **User**, I can sign up and login via Email or Social Providers (Google/Microsoft).
    - As a **Tenant Admin**, I can manage users within my company and assign roles.
    - As a **User**, I can reset my password securely via email verification.

### Feature 1.3: Governance & Compliance
- **Description**: Middleware and internal controls to manage tenant status and security.
- **Stories**:
    - As an **Admin**, I can suspend a company, immediately blocking all its users from API access via `CompanySuspensionMiddleware`.

---

## Epic 2: Agentic AI Builder
*Goal: Empower users to create specialized AI agents with specific configurations.*

### Feature 2.1: Agent Persona Management
- **Description**: Define system prompts (roles) and LLM configurations (model, temperature, tools).
- **Stories**:
    - As a **User**, I can create an agent by defining its "System Prompt" to act as a recruiter, coder, or analyst.
    - As a **User**, I can configure the agent to use specific models (GPT-4o, Gemini 1.5 Pro).

### Feature 2.2: Variable Injection
- **Description**: Dynamic prompt templating using `{{variable}}` syntax.
- **Stories**:
    - As a **User**, I can use placeholders in my agent prompts that get replaced with runtime execution data.

### Feature 2.3: Tool Integration
- **Description**: Extensible tool registry allowing agents to perform actions.
- **Stories**:
    - As a **User**, I can enable specific tools for an agent, allowing it to perform external tasks during execution.

---

## Epic 3: Workflow Orchestration (DAG)
*Goal: Combine multiple agents into sophisticated, multi-step automated processes.*

### Feature 3.1: Visual Workflow Builder
- **Description**: A drag-and-drop-style (sequential/DAG) interface to chain agents.
- **Stories**:
    - As a **Builder**, I can create a workflow by adding steps, where each step is an AI Agent.
    - As a **System**, I can validate that a workflow has no circular dependencies using `DAGValidator`.

### Feature 3.2: Context Propagation
- **Description**: Automatically passing output from one agent as input to the next.
- **Stories**:
    - As a **System**, I can execute a workflow where the output of "Agent A" is ingested by "Agent B" based on the DAG structure.

### Feature 3.3: Async Execution Engine
- **Description**: Scalable background processing for long-running AI tasks.
- **Stories**:
    - As a **User**, I can trigger a workflow and receive a job ID immediately while the background worker (`arq`) handles the execution.
    - As a **User**, I can view the real-time progress of a workflow via a streaming SSE (Server-Sent Events) connection.

---

## Epic 4: Knowledge Base & RAG
*Goal: Provide agents with access to private company data for context-aware responses.*

### Feature 4.1: Multi-Format Document Ingestion
- **Description**: Upload and process PDF, DOCX, and TXT files.
- **Stories**:
    - As a **User**, I can upload documents to a Knowledge Base.
    - As a **System**, the background worker automatically parses these files and generates vector embeddings.

### Feature 4.2: Semantic Vector Search
- **Description**: Leveraging `pgvector` for high-speed similarity search.
- **Stories**:
    - As a **System**, I can perform a RAG search during agent execution to find relevant document chunks based on the user's query.

---

## Epic 5: Observability & Billing
*Goal: Track usage, costs, and system performance for business intelligence.*

### Feature 5.1: Real-time Usage Metering
- **Description**: Granular logging of LLM token usage (input/output) per tenant.
- **Stories**:
    - As a **System**, I log every AI execution's token count into the `usage_logs` table, mapped to specific SKUs.

### Feature 5.2: Cost Transparency
- **Description**: Calculating costs based on internal rates defined in the `IntegrationRegistry`.
- **Stories**:
    - As a **Tenant Admin**, I can view dashboard statistics showing the number of active agents, workflows, and executions.

### Feature 5.3: Telemetry & Monitoring
- **Description**: System-wide tracing and metrics using OpenTelemetry.
- **Stories**:
    - As a **DevOps Engineer**, I can monitor API performance and worker health via Prometheus and Grafana.
