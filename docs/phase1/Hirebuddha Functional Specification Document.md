

# **Technical Architecture and Functional Specification Report: The Hirebuddha Platform**

## **1\. Executive Strategic Overview**

The conceptualization and development of **Hirebuddha** represents a significant convergence of three distinct technological and commercial trends: the democratization of Generative AI via agentic workflows, the proliferation of verticalized B2B SaaS marketplaces, and the emergence of "Liquid" interface design paradigms inspired by spatial computing. This report serves as a definitive architectural blueprint and functional specification for the platform. It is intended to guide the engineering, product, and design teams through the implementation of a system that is not merely a tool for end-users but a robust commercial ecosystem for Sales Partners.

The core value proposition of Hirebuddha is twofold. Primarily, it creates a utility layer for **AI Agent Orchestration**, enabling tenants to define, execute, and manage complex, multi-step AI workflows using state-of-the-art Large Language Models (LLMs). Secondarily, and perhaps more critically for its business model, it establishes a **Multi-Tenant Reseller Hierarchy**. This structure empowers a "Sales Partner" persona to onboard, manage, and monetize their own distinct cohort of tenants, effectively functioning as a white-label distributor of the platform’s capabilities.

To support these requirements, the platform demands an architecture that balances extreme flexibility in AI orchestration with rigid, audit-grade precision in financial metering. The selected technology stack—**Python/FastAPI** for the backend, **PostgreSQL** for data persistence, and **React/TypeScript** for the frontend—provides the necessary performance characteristics. Specifically, FastAPI's asynchronous nature is uniquely suited to the I/O-bound workloads inherent in AI application development, where high concurrency is required to manage long-running LLM inference tasks without blocking server resources.1 Furthermore, the user interface requirement for an "Apple Liquid Glass" aesthetic dictates a frontend engineering strategy that goes beyond standard component libraries, requiring custom implementation of advanced CSS backdrop filters and physics-based animations to replicate the depth and translucency found in modern spatial operating systems.3

This document details the functional requirements, data structures, security protocols, and user experience specifications required to build Hirebuddha. It moves beyond high-level descriptions to provide actionable engineering guidance, ensuring that the complex interplay between multi-tenancy, billing, and AI execution is handled with architectural rigor.

## **2\. Backend Architecture: Microservices and FastAPI Implementation**

The backend architecture of Hirebuddha is designed around a modular microservices pattern, leveraging the **FastAPI** framework. This choice is driven by the specific performance profiles of modern AI applications. Unlike traditional CRUD applications, which are often CPU-bound or database-bound, AI applications are heavily I/O-bound, spending significant time waiting for responses from external inference APIs (such as OpenAI or Anthropic). FastAPI, built on the Starlette framework, utilizes the Asynchronous Server Gateway Interface (ASGI), allowing it to handle thousands of concurrent connections efficiently using Python’s async and await syntax.5

### **2.1 Service Decomposition and Boundaries**

While a monolithic architecture might suffice for early-stage prototypes, the distinct scaling requirements of Hirebuddha’s components necessitate a microservices approach. The system will be decomposed into four primary functional domains. This separation of concerns ensures that a heavy load on the AI execution engine does not degrade the performance of critical administrative functions like authentication or billing.

| Service Domain | Primary Responsibility | Tech Stack Highlights |
| :---- | :---- | :---- |
| **Identity & Access (IAM)** | Authentication, Registration, Session Management, RBAC enforcement. | FastAPI, Pydantic, JWT, Argon2 |
| **Tenant & Partner Core** | Organization hierarchy, Partner management, User profile management. | FastAPI, SQLAlchemy (Async), Postgres |
| **AI Orchestration Engine** | Agent configuration, Prompt management, Async Execution, LLM integration. | FastAPI, Arq, Redis, LangChain/PydanticAI |
| **Billing & Ledger** | Token metering, Cost calculation, Invoicing, Partner Commission tracking. | FastAPI, Stripe API, Ledger Tables |

#### **2.1.1 The API Gateway Strategy**

To maintain a coherent developer experience for the frontend team and secure the microservices mesh, a unified **API Gateway** will be implemented. This gateway serves as the single entry point for all client traffic, abstracting the complexity of the underlying service architecture.6 The gateway will handle "cross-cutting concerns" such as SSL termination, global rate limiting, and request routing.

Requests will be routed based on path prefixes. For example, traffic destined for authentication services will be routed via /api/v1/auth/\*, while AI execution requests are directed to /api/v1/agents/\*. This setup also facilitates the implementation of a "Backend for Frontend" (BFF) pattern if necessary, where the gateway aggregates data from multiple services (e.g., fetching user profile \+ tenant billing status) into a single response to reduce frontend network chatter.7

### **2.2 High-Performance FastAPI Implementation Patterns**

The success of the backend relies on adhering to strict development patterns that leverage FastAPI's strengths while mitigating common pitfalls in asynchronous Python development.

Project Structure and Modularity  
To ensure maintainability as the codebase grows, the project structure will follow a domain-driven design similar to the "Netflix Dispatch" pattern adapted for FastAPI.8 Instead of grouping files by type (e.g., all controllers in one folder), the codebase will be organized by module (e.g., src/auth, src/billing). Each module will contain its own router.py, schemas.py (Pydantic models), service.py (business logic), and dependencies.py. This encapsulation allows different teams to work on the "Billing" module and the "AI" module simultaneously with minimal merge conflicts.  
Asynchronous Database Drivers  
A critical technical requirement is the use of asynchronous database drivers. Using a synchronous driver (like psycopg2) in an async FastAPI application would block the main event loop, negating the performance benefits of ASGI. Therefore, Hirebuddha will utilize asyncpg for PostgreSQL interactions. This driver is highly performant and supports connection pooling, which is vital for maintaining throughput under heavy load.2 All database interactions will be mediated through an asynchronous ORM layer, specifically SQLAlchemy 2.0 (using AsyncSession) or SQLModel, ensuring that database queries do not become bottlenecks.9  
Dependency Injection for Context  
FastAPI’s dependency injection system will be the backbone of the application's request processing pipeline. Rather than relying on global variables or middleware for everything, dependencies will be used to inject context into route handlers. For example, a get\_current\_tenant dependency will extract the tenant ID from the authenticated user's session and verify the tenant's active status before the route handler is even executed. This ensures that multi-tenancy checks are consistently applied across all endpoints without repetitive code.10

### **2.3 Scalability and Concurrency Models**

The system must support scaling in two dimensions: the volume of HTTP requests (handled by the API Gateway and stateless service replicas) and the volume of background AI tasks.

Handling Blocking Code  
While the core stack is async, certain libraries (e.g., older PDF parsing tools or specific cryptographic functions) may be synchronous/blocking. To prevent these from freezing the application, the architecture mandates running such blocking code in a separate thread pool using run\_in\_threadpool or asyncio.to\_thread.8 This distinction is crucial for the "AI Orchestration" service, where preprocessing a large document upload for RAG (Retrieval-Augmented Generation) could otherwise stall the entire service.  
Containerization and Deployment  
Each microservice will be containerized using Docker, with uvicorn serving as the ASGI server. For production deployment, these containers will be orchestrated (e.g., via Kubernetes or AWS ECS), allowing independent scaling. If the Billing service experiences high load at the end of the month, it can be scaled up independently of the AI Orchestration service.11

## **3\. Multi-Tenancy and Data Strategy**

The requirement for "multi-tenancy" is central to Hirebuddha's architecture. The platform must serve multiple distinct organizations (Tenants) from a single deployment while ensuring strict data isolation. The complexity is compounded by the "Sales Partner" hierarchy, which requires aggregated visibility into the data of multiple tenants.

### **3.1 Database Schema Design: Shared Schema with Logical Isolation**

There are three primary approaches to multi-tenancy in PostgreSQL: Database per Tenant, Schema per Tenant, and Shared Schema.12 For Hirebuddha, the **Shared Database, Shared Schema** approach is the optimal architectural choice.

Rationale for Shared Schema  
While "Database per Tenant" offers the highest isolation, it creates significant operational overhead when managing thousands of tenants—running migrations across 5,000 databases is error-prone and slow. More importantly, the Sales Partner requirement necessitates cross-tenant reporting. A partner needs to see a dashboard showing "Total Earnings" calculated from all their managed tenants. In a "Database per Tenant" model, this would require querying hundreds of separate databases and aggregating the results in the application layer, which is highly inefficient. In a Shared Schema model, this is a simple, high-performance SQL query: SELECT sum(commission) FROM ledger WHERE partner\_id \= X.14  
To mitigate the security risks of a shared schema, strict logical isolation will be enforced. Every table containing tenant-specific data (users, agents, executions, invoices) must include a tenant\_id column (UUID), indexed for performance.16

### **3.2 Row-Level Security (RLS) Implementation**

To prevent data leaks—where a bug in a query allows User A to see User B's agents—the system will implement a comprehensive isolation strategy akin to Postgres Row-Level Security (RLS).

Application-Layer RLS  
We will implement "RLS" primarily at the application layer using FastAPI dependencies and SQLAlchemy filters. A global dependency get\_db\_session will be configured to automatically apply a filter to all queries based on the authenticated user's tenant\_id. This reduces the risk of a developer forgetting to add WHERE tenant\_id \=? to a manual SQL query. For high-security environments, this can be backed by actual Postgres RLS policies defined in the database migration scripts, ensuring that even a direct SQL injection attempt would struggle to access cross-tenant data.18

### **3.3 Data Model for the Reseller Hierarchy**

The data model must explicitly support the three-tier hierarchy: Super Admin → Sales Partner → Tenant.

| Entity | Description | Relationships |
| :---- | :---- | :---- |
| **Partner** | A reseller entity. | Has many Tenants. |
| **Tenant** | A customer organization. | Belongs to one Partner (optional, can be direct). Has many Users. |
| **User** | An individual account. | Belongs to one Tenant. |

The Self-Registration Flow  
The requirement "self-register \= new tenant" implies a frictionless onboarding process. When a user signs up without an invitation code or a recognized email domain, the system acts as an orchestration layer:

1. **User Creation:** A User record is created.  
2. **Tenant Creation:** A new Tenant record is automatically instantiated. The name defaults to the user's email domain or a generic "My Workspace".  
3. **Association:** The new User is assigned the role of Tenant Admin for this new Tenant.  
4. **Subdomain Routing (Optional):** If the architecture supports it, the system can provision a subdomain (e.g., tenant-name.hirebuddha.io). FastAPI middleware will then identify the tenant context by parsing the Host header of incoming requests.19

## **4\. Identity and Access Management (IAM)**

Security is paramount in a B2B SaaS application. The Authentication Service must handle diverse login methods and enforce a robust Role-Based Access Control (RBAC) system.

### **4.1 Authentication Protocols and Providers**

To maximize adoption and security, Hirebuddha will support OAuth2/OpenID Connect (OIDC) alongside traditional email/password authentication.

OIDC Integration (Google & Microsoft)  
For corporate users, "Login with Microsoft" or "Login with Google" is a requirement. This will be implemented using the standard Authorization Code flow. The backend will verify the identity token issued by the provider and map the provider's unique ID ( sub claim) to a local user record. This not only improves user experience but also offloads the security burden of credential storage to trusted providers.20  
Secure Session Management  
The requirement for a 30-day session dictates a dual-token strategy involving Access Tokens and Refresh Tokens.

* **Access Token (JWT):** A short-lived stateless token (e.g., 15 minutes) containing claims like user\_id, tenant\_id, and scopes. This is sent in the Authorization header.  
* **Refresh Token:** A long-lived opaque token (stored in the database) with a 30-day expiration. This token is sent to the client in an HttpOnly, Secure, SameSite cookie.  
* **Rotation & Revocation:** When the Access Token expires, the client uses the Refresh Token to request a new pair. Crucially, using the Refresh Token triggers **token rotation**—a new Refresh Token is issued, and the old one is invalidated. This mechanism allows for immediate session revocation (e.g., if a Sales Partner suspends a Tenant) by simply deleting the Refresh Token from the database, forcing the user to log out once their short-lived Access Token expires.21

### **4.2 Role-Based Access Control (RBAC)**

The permission system must distinguish between the platform's operational layers.

**Role Matrix**

* **App Admin (Superuser):** Has \* permissions. Can access the "System Config" to manage global API keys and "Cost Rates."  
* **Sales Partner:** Has permission to read and manage the Tenants linked to their partner\_id. Can view financial\_reports for their cohort. Critically, they generally do *not* have access to the internal data (Agents, Prompts) of their tenants unless explicitly granted "Support Access."  
* **Tenant Admin:** Has full control over a specific tenant\_id. Can create users, manage billing, and configure AI agents.  
* **Normal User:** Can execute agents and view their own history.

Implementation  
Permissions will be enforced using FastAPI dependencies (e.g., Depends(RoleChecker(\["tenant\_admin"\]))). These dependencies inspect the JWT scopes or query the database to validate that the requesting user holds the necessary role for the target resource.23

### **4.3 API Key Security**

A critical system configuration task for the App Admin is managing API keys for AI providers (e.g., OpenAI, Anthropic). These keys are high-value targets and must never be stored in plain text.

* **Encryption at Rest:** The database column for these keys will be encrypted using **Fernet** (symmetric encryption). The application will hold the encryption key in an environment variable or secrets manager (like AWS Secrets Manager).  
* **Just-in-Time Decryption:** The keys are only decrypted within the memory of the AI Orchestration Service immediately prior to making an API call, and are never logged or returned in API responses.25

## **5\. AI Agent Orchestration Engine**

The core utility of Hirebuddha is the ability to define and execute AI Agents. This service requires a flexible yet structured approach to defining logic.

### **5.1 Agent Definition and Schema**

Agents will be defined as Directed Acyclic Graphs (DAGs) serialized into JSON. This allows for complex, multi-step workflows (e.g., "Step 1: Search Web", "Step 2: Summarize", "Step 3: Email Result").27

JSON Configuration Schema  
The configuration column in the agents table will store a JSON object adhering to a strict schema. This schema defines the model to be used (e.g., GPT-4), the system prompt, and the parameters (temperature, max tokens).

JSON

{  
  "model\_config": {  
    "provider": "openai",  
    "model": "gpt-4-turbo",  
    "temperature": 0.7  
  },  
  "workflow": {  
    "nodes": \[  
      {"id": "input", "type": "user\_input"},  
      {"id": "llm\_process", "type": "llm", "prompt\_template": "Analyze this: {input}"}  
    \],  
    "edges": \[  
      {"source": "input", "target": "llm\_process"}  
    \]  
  }  
}

This structure allows the frontend to render a visual node-based editor or a simple form, while the backend treats the execution logic uniformly.29

### **5.2 Asynchronous Execution Pipeline**

Executing an AI agent is a long-running operation that can take anywhere from seconds to minutes. Handling this synchronously in a web request would exhaust server connections and lead to timeouts.

The Arq & Redis Solution  
Hirebuddha will utilize Arq, a lightweight asynchronous job queue built on Redis, rather than the more heavyweight Celery. Arq is designed specifically for Python's asyncio and integrates seamlessly with FastAPI.

1. **Enqueue:** When a user triggers an agent, the API endpoint validates the request and pushes a job payload to Redis. It immediately returns a job\_id to the frontend.  
2. **Processing:** A separate worker process (running Arq) picks up the job. This worker is responsible for the heavy lifting: communicating with the OpenAI API, handling retries, and processing the response.  
3. **Result Storage:** Upon completion, the worker writes the result (and usage metrics) to the database.  
4. **Frontend Updates:** The frontend polls the status endpoint using the job\_id or listens for a WebSocket event to display the result.30

### **5.3 Observability and Monitoring**

For AI workflows, standard logging is insufficient. The system needs to track token usage, latency, and error rates per model and per tenant. **OpenTelemetry** will be integrated into the AI Service to trace requests from the API Gateway through to the external LLM providers. This data will be exported to a monitoring stack (e.g., Prometheus \+ Grafana), giving the App Admin visibility into system health and the Sales Partners confidence in the platform's reliability.32

## **6\. Commercial Engine: Billing, Ledger, and Commissions**

The billing engine is the financial heart of the platform. It must translate abstract "token usage" into concrete invoices and partner commissions.

### **6.1 The Three-Layer Rate Model**

To support the reseller model, the system must track three distinct financial values for every transaction:

1. **Cost Rate:** The baseline cost incurred by the platform (e.g., paying OpenAI $0.03 per 1k tokens). This is configured by the App Admin.  
2. **Billing Rate:** The price charged to the Tenant. This is determined by a markup factor (e.g., 2x Cost) configured by the Sales Partner or App Admin.  
3. **Commission:** The profit share allocated to the Sales Partner. This is calculated as a percentage of the *Net Margin* (Billing Rate \- Cost Rate) or the *Gross Revenue*, depending on the business model configuration.34

### **6.2 Metering Middleware and The Ledger**

Accurate billing requires precise metering of every API call.  
Middleware Implementation  
A custom FastAPI middleware or decorator will wrap the AI execution functions. This middleware performs two critical actions:

* **Pre-Flight Check:** It verifies that the Tenant has a valid payment method or sufficient credits.  
* **Post-Flight Recording:** After the AI response is generated, it extracts the usage statistics (prompt tokens \+ completion tokens) provided by the LLM API response.

The Ledger  
These statistics are written to an immutable ledger\_entries table. This table acts as the single source of truth for all financial reporting. It records the tenant\_id, partner\_id, tokens\_used, model\_id, and the calculated financial values (Cost, Price, Commission) at the moment of execution. This ensures that future price changes do not retroactively alter historical billing records.35

### **6.3 Dunning and Revenue Recovery**

In a B2B SaaS, failed payments are inevitable. The system must implement a robust **Dunning Management** process.

* **Retry Logic:** If a monthly invoice payment fails, the system should automatically retry the payment method on a schedule (e.g., Day 1, Day 3, Day 7).  
* **Communication:** Automated emails must be triggered at each failure, escalating in urgency. These emails should be branded (Tenant-specific or White-label) to maintain trust.  
* **Service Degradation:** After a configurable period of non-payment (e.g., 14 days), the system should automatically transition the Tenant to a "Suspended" state, blocking access to the AI Execution endpoints while preserving data.36

## **7\. Frontend Engineering: The "Liquid Glass" Experience**

The user requirement for an "Apple Liquid Glass / Rose Gold" theme demands a high-fidelity frontend implementation that mimics the aesthetics of visionOS. This is not merely a color scheme but a physics-based interface design.

### **7.1 The Liquid Glass Design System**

The "Liquid Glass" effect is achieved through a combination of translucency, blurring, and lighting simulation.

* **Backdrop Filters:** The core CSS property is backdrop-filter: blur(20px) saturate(180%). This creates the signature "frosted" look where background colors bleed through the interface elements, anchoring them in the environment.38  
* **Material Simulation:** Interface cards will use a background of rgba(255, 255, 255, 0.4) to create a semi-transparent "platter." A subtle white border (1px solid rgba(255, 255, 255, 0.3)) creates the physical edge of the glass, while a soft, diffused shadow lifts the element off the page.40  
* **Rose Gold Palette:** The "Rose Gold" theme is not a flat color but a metallic gradient. Text and icons will utilize background-clip: text with a linear gradient spanning from a warm copper (\#D4938B) to a pale pink highlight (\#F6DCD4) and back to a deep bronze (\#97534C). This simulates light reflecting off a metallic surface.41

### **7.2 Physics-Based Animation**

Static interfaces feel dead. The Liquid Glass design requires motion that mimics real-world physics.

* **Spring Animations:** We will use libraries like **Framer Motion** or **React Spring** to handle interactions. Hover states should not just toggle colors but physically lift the element (scale up \+ shadow expansion) using a spring curve rather than a linear transition.  
* **Jelly Effects:** For primary actions (like the "Execute Agent" button), a "Jelly" animation (scaling X up and Y down, then oscillating) will provide tactile feedback, making the button feel like a deformable physical object.43  
* **Specular Highlights:** To fully sell the glass effect, a pseudo-element overlay with a linear gradient can be animated across the surface of cards on hover, simulating a light source moving across the glass.3

## **8\. Infrastructure and DevOps**

### **8.1 CI/CD and Containerization**

The entire platform will be containerized using **Docker**. A multi-stage build process will be used to keep images small and secure.

* **CI Pipeline:** A GitHub Actions or GitLab CI pipeline will run on every commit. It will execute the test suite (Pytest for backend, Jest/Vitest for frontend), run linting (Ruff/Black), and build the Docker images.1  
* **CD Pipeline:** Upon merging to the main branch, the images will be pushed to a container registry and deployed to the staging environment.

### **8.2 Deployment Strategy**

The recommended production deployment utilizes a managed container orchestration service (like AWS ECS or Google Cloud Run) and a managed PostgreSQL instance (RDS or Cloud SQL). This offloads the complexity of database backups and server patching. The Redis instance (for Arq) should also be a managed service (e.g., ElastiCache) to ensure high availability.
