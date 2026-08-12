

# **Functional Specification: Hirebuddha Platform**

## **1\. Epic: Identity & Multi-Tenant Hierarchy**

**Goal:** Establish the strict three-tier hierarchy (Super Admin \> Sales Partner \> Tenant \> User) and secure authentication flows.

### **Feature 1.1: Authentication & Onboarding**

* **Story 1.1.1 (OAuth & Social Login):** As a **User**, I want to log in using Google or Microsoft so that I don't need to remember a new password.  
  * **AC 1:** Implement OAuth2 flow for Google and Microsoft Entra ID.  
  * **AC 2:** If the email does not exist in the system, automatically redirect to the "Registration" flow (Story 1.1.2).  
  * **AC 3:** Store the provider's sub (subject ID) to handle email changes on the provider side securely.  
* **Story 1.1.2 (Self-Registration & Auto-Tenancy):** As a **New User**, I want to register via Email/Password so that I can immediately start using the platform.  
  * **AC 1:** Registration form requires: Email, Password (min 12 chars), Full Name.  
  * **AC 2:** **System Logic:** Upon registration, the system must automatically:  
    1. Create a User record.  
    2. Create a Tenant record (Name \= "\[Name\]'s Workspace").  
    3. Link User to Tenant as TENANT\_ADMIN.  
    4. Set Tenant status to Active.  
  * **AC 3:** Trigger an async email verification task (SMTP). Account is locked if not verified in 24h.  
* **Story 1.1.3 (Session Persistence):** As a **User**, I want to remain logged in for 30 days.  
  * **AC 1:** Issue a short-lived access\_token (JWT, 15 min) and a long-lived refresh\_token (30 days).  
  * **AC 2:** Store refresh\_token hash in the database to allow for revocation (e.g., if a Partner suspends a Tenant).  
  * **AC 3:** refresh\_token must be sent as an HttpOnly; Secure; SameSite=Strict cookie.

### **Feature 1.2: Partner & Tenant Management**

* **Story 1.2.1 (Sales Partner Hierarchy):** As an **App Admin**, I want to create a "Sales Partner" entity so they can resell the platform.  
  * **AC 1:** Create partners table. Create users with role PARTNER\_ADMIN.  
  * **AC 2:** Partner Admins cannot see other Partners' data.  
* **Story 1.2.2 (Partner-Led Tenant Creation):** As a **Sales Partner**, I want to manually onboard a new Tenant so I can set up their account for them.  
  * **AC 1:** Form inputs: Tenant Name, Admin Email, Default Credit Balance (optional).  
  * **AC 2:** The created Tenant is linked via foreign key to the creating Partner.  
* **Story 1.2.3 (Tenant Suspension):** As a **Sales Partner**, I want to suspend a Tenant so they cannot access the system if they haven't paid.  
  * **AC 1:** UI Toggle: "Active/Suspended".  
  * **AC 2:** Middleware check: On every API request, check tenant.status. If Suspended, return 403 Forbidden.

---

## **2\. Epic: System Configuration & Integrations**

**Goal:** centralized management of high-value assets (API keys) and global defaults.

### **Feature 2.1: Global Model Configuration**

* **Story 2.1.1 (Model Registry):** As an **App Admin**, I want to register new AI models (Text, ASR, TTS, Image, Video) so they are available for use in the builder.  
  * **AC 1:** CRUD for ai\_models table.  
  * **AC 2:** Fields: model\_key (e.g., gpt-4), provider (e.g., openai), type (e.g., text, video), is\_active.  
* **Story 2.1.2 (Secure Key Vault):** As an **App Admin**, I want to input API keys for OpenAI, Twilio, and Tata so the system can function.  
  * **AC 1:** Input fields for:  
    * Text/Image/Video Model Keys (OpenAI/Anthropic).  
    * Twilio Account SID & Auth Token.  
    * Tata Communications API Key & Secret.  
  * **AC 2:** **Security:** Keys must be encrypted at rest using Fernet (symmetric encryption) before saving to Postgres.  
  * **AC 3:** Keys are never returned in API responses (write-only).

---

## **3\. Epic: The "No-Code" AI Agent Builder**

**Goal:** The core product. A visual or structured way to define complex agent behaviors.

### **Feature 3.1: Agent Definition**

* **Story 3.1.1 (Agent Configuration):** As a **Tenant Admin**, I want to create a basic Agent.  
  * **AC 1:** Inputs: Name, Role (System Prompt), Model Selection (dropdown of available models from Feature 2.1).  
  * **AC 2:** Temperature/Top-P sliders.  
* **Story 3.1.2 (Variable Support):** As a **Tenant Admin**, I want to define variables (e.g., {{candidate\_name}}) in my prompts.  
  * **AC 1:** Parser detects {{...}} syntax in the system prompt.  
  * **AC 2:** When executing, the API requires these variables to be passed in the JSON body.  
* **Story 3.1.3 (Multi-Agent Chaining):** As a **Tenant Admin**, I want to chain agents together (e.g., "Researcher" \-\> "Writer").  
  * **AC 1:** Create a "Workflow" entity.  
  * **AC 2:** Define a DAG (Directed Acyclic Graph) structure:  
    * Step 1: Agent A (Input: User Query).  
    * Step 2: Agent B (Input: Output of Agent A).  
  * **AC 3:** Validation: Ensure no circular dependencies.

### **Feature 3.2: Tooling & Skills**

* **Story 3.2.1 (Standard Tools):** As a **System**, I want to provide standard tools (Web Search, Calculator) that Agents can invoke.  
  * **AC 1:** Implement LangChain/PydanticAI tool interfaces.  
  * **AC 2:** Agents can be configured with a list of enabled tools.  
* **Story 3.2.2 (RAG/Knowledge Base):** As a **Tenant Admin**, I want to upload PDF documents so my agent knows about my company.  
  * **AC 1:** Upload endpoint accepts PDF/DOCX.  
  * **AC 2:** Background task: Chunk text \-\> Generate Embeddings (OpenAI text-embedding-3-small) \-\> Store in pgvector (Postgres vector extension).  
  * **AC 3:** Agent execution pipeline includes a "Retrieval" step before LLM inference.

---

## **4\. Epic: Execution Engine (Backend)**

**Goal:** High-concurrency execution of AI tasks using Python/FastAPI/Async.

### **Feature 4.1: Async Execution**

* **Story 4.1.1 (Job Queue):** As a **User**, I want to run a workflow without the browser timing out.  
  * **AC 1:** Endpoint POST /api/v1/execute pushes job to **Arq** (Redis-based queue).  
  * **AC 2:** Returns 202 Accepted with a job\_id.  
  * **AC 3:** Worker process picks up job, initializes LLM client, performs inference, and saves result to DB.  
* **Story 4.1.2 (Streaming Responses):** As a **User**, I want to see the text appear as it generates (Typewriter effect).  
  * **AC 1:** Implement Server-Sent Events (SSE) or WebSockets at /api/v1/stream/{job\_id}.  
  * **AC 2:** Forward chunks from OpenAI/Anthropic API to the frontend in real-time.

---

## **5\. Epic: Financial Engine (Billing & Rates)**

**Goal:** The complex calculation logic for the reseller model.

### **Feature 5.1: Rate Card Management (The 3-Layer Model)**

* **Story 5.1.1 (System Cost Rates):** As an **App Admin**, I want to define the *Cost* of every resource.  
  * **AC 1:** Table system\_rates:  
    * resource\_type: (text\_input, text\_output, image\_gen, voice\_min\_twilio, voice\_min\_tata).  
    * unit: (1k\_tokens, minute, request).  
    * rate: Decimal (e.g., 0.03).  
* **Story 5.1.2 (Sales Partner Selling Rates):** As a **Sales Partner**, I want to define the *Price* I charge my tenants.  
  * **AC 1:** Table partner\_rates: Linked to partner\_id and system\_rate\_id.  
  * **AC 2:** Input: New Rate (must be \>= System Rate).  
  * **AC 3:** Validation: Partner cannot set a rate lower than the System Cost.

### **Feature 5.2: The Ledger & Metering**

* **Story 5.2.1 (Usage Metering):** As a **System**, I must record every API call's usage.  
  * **AC 1:** **Text:** Count tokens (Prompt \+ Completion).  
  * **AC 2:** **Voice:** Calculate duration (End Time \- Start Time).  
  * **AC 3:** **Video:** Count seconds generated.  
* **Story 5.2.2 (Transaction Recording):** As a **System**, I want to calculate the financial spread instantly.  
  * **AC 1:** On job completion, create a ledger\_entry:  
    * tenant\_cost: (Usage \* Partner\_Rate). **(Amount Tenant Pays)**  
    * platform\_cost: (Usage \* System\_Rate). **(Amount Platform Pays Provider)**  
    * partner\_commission: (tenant\_cost \- platform\_cost). **(Profit)**  
  * **AC 2:** All values stored in USD (decimal(18,6)).

### **Feature 5.3: Reporting**

* **Story 5.3.1 (Partner Earnings):** As a **Sales Partner**, I want to see my commissions.  
  * **AC 1:** Query sum(partner\_commission) from ledger\_entries where partner\_id \= X.  
  * **AC 2:** Group by Month and Tenant.

---

## **6\. Epic: "Liquid Glass" Frontend UX**

**Goal:** Visual implementation of the specific aesthetic requirements.

### **Feature 6.1: Design System Implementation**

* **Story 6.1.1 (Glass Container Component):** As a **Developer**, I want a reusable GlassCard component.  
  * **AC 1:** CSS: backdrop-filter: blur(20px).  
  * **AC 2:** Background: rgba(25, 25, 25, 0.6) (Dark Grey transparent).  
  * **AC 3:** Border: 1px solid rgba(255, 255, 255, 0.1).  
  * **AC 4:** Shadow: Soft diffused shadow.  
* **Story 6.1.2 (Rose Gold Typography):** As a **Developer**, I want a standard class for the Rose Gold metallic text.  
  * **AC 1:** CSS background-image: linear-gradient(to right, \#D4938B, \#F6DCD4, \#97534C).  
  * **AC 2:** background-clip: text, text-fill-color: transparent.  
* **Story 6.1.3 (Jelly Button):** As a **User**, I want buttons to feel organic.  
  * **AC 1:** Implement a React component using framer-motion.  
  * **AC 2:** whileHover: scale(1.05).  
  * **AC 3:** whileTap: scale(0.95) with a "spring" bounce transition (damping: 10, stiffness: 100).

### **Feature 6.2: Layouts**

* **Story 6.2.1 (Login Screen):** As a **User**, I want a visually immersive login page.  
  * **AC 1:** Background: Animated "smoke/liquid" video or WebGL canvas (Dark Grey).  
  * **AC 2:** Centered GlassCard containing the login form.  
  * **AC 3:** Inputs must be transparent with only a bottom border (Rose Gold on focus).

---

## **7\. Epic: Technical Non-Functional Requirements**

**Goal:** Performance and Architecture standards.

* **Story 7.1 (Microservices):** The backend must be split into modular services (Auth, Billing, AI).  
* **Story 7.2 (API Gateway):** All traffic must pass through a single entry point (e.g., Nginx or a FastAPI Gateway) for rate limiting and routing.  
* **Story 7.3 (Postgres Schema):** All tables must have created\_at, updated\_at, and tenant\_id (where applicable).  
* **Story 7.4 (Encryption):** Sensitive columns (API Keys, User PII) must be encrypted at rest.