# Entity Relationship Diagram - Phase 3
## Hierarchical Autonomous AI Agentic Platform

This document describes the database schema and entity relationships for the HireBuddha Phase 3 platform.

## 1. ER Diagram

```mermaid
erDiagram
    COMPANIES ||--o{ COMPANIES : "parent_id"
    COMPANIES ||--o{ USERS : "company_id"
    COMPANIES ||--o{ INTEGRATION_REGISTRY : "company_id"
    COMPANIES ||--o{ HIERARCHICAL_ENTITIES : "company_id"
    COMPANIES ||--o{ EXECUTION_RUNS : "company_id"
    COMPANIES ||--o{ USAGE_LOGS : "company_id"
    COMPANIES ||--o{ DOCUMENTS : "company_id"

    USERS ||--o{ REFRESH_TOKENS : "user_id"
    USERS ||--o{ HUMAN_APPROVALS : "responded_by"

    HIERARCHICAL_ENTITIES ||--o{ HIERARCHICAL_ENTITIES : "parent_id"
    HIERARCHICAL_ENTITIES ||--o{ EXECUTION_RUNS : "entity_id"
    HIERARCHICAL_ENTITIES ||--o{ DOCUMENTS : "entity_id"

    INTEGRATION_REGISTRY ||--o{ USAGE_LOGS : "sku_id"

    EXECUTION_RUNS ||--o{ EXECUTION_RUNS : "parent_run_id"
    EXECUTION_RUNS ||--o{ LLM_INTERACTION_LOGS : "run_id"
    EXECUTION_RUNS ||--o{ TOOL_INTERACTION_LOGS : "run_id"
    EXECUTION_RUNS ||--o{ HUMAN_APPROVALS : "run_id"
    EXECUTION_RUNS ||--o{ USAGE_LOGS : "run_id"

    DOCUMENTS ||--o{ DOCUMENT_CHUNKS : "document_id"

    COMPANIES {
        uuid id PK
        string name
        string type "APP, PARTNER, TENANT"
        uuid parent_id FK
        string logo_url
        string status "active, suspended"
        datetime created_at
        datetime updated_at
    }

    USERS {
        uuid id PK
        string email UK
        string full_name
        string hashed_password
        uuid company_id FK
        string role "app_admin, partner_admin, etc"
        boolean is_active
        boolean is_verified
        string profile_picture_url
        datetime created_at
        datetime updated_at
    }

    REFRESH_TOKENS {
        uuid id PK
        uuid user_id FK
        string token UK
        datetime expires_at
        boolean revoked
        datetime created_at
    }

    INTEGRATION_REGISTRY {
        uuid id PK
        uuid company_id FK
        string provider_name
        string model_name
        string service_sku UK
        string component_type
        text encrypted_api_key
        numeric internal_cost
        string cost_unit
        string status
        datetime created_at
        datetime updated_at
    }

    HIERARCHICAL_ENTITIES {
        uuid id PK
        uuid company_id FK
        uuid parent_id FK
        string version
        string type "ACTION, SKILL, AGENT, PROCESS"
        string status
        string name
        string display_name
        text description
        json tags
        json identity
        json hierarchy
        json logic_gate
        json planning
        json capabilities
        json governance
        json io_contract
        json observability
        json metadata_extensions
        datetime created_at
        datetime updated_at
    }

    EXECUTION_RUNS {
        uuid id PK
        uuid entity_id FK
        uuid parent_run_id FK
        uuid company_id FK
        string status
        json input_data
        json dynamic_plan
        json result_data
        json context_state
        text error_message
        numeric total_cost_usd
        integer total_tokens
        integer execution_time_ms
        uuid trace_id
        string span_id
        datetime started_at
        datetime completed_at
        datetime created_at
    }

    LLM_INTERACTION_LOGS {
        uuid id PK
        uuid run_id FK
        string model_provider
        string model_name
        text input_prompt
        text output_response
        integer prompt_tokens
        integer completion_tokens
        integer latency_ms
        numeric cost_usd
        string reasoning_mode
        json log_metadata
        datetime created_at
    }

    TOOL_INTERACTION_LOGS {
        uuid id PK
        uuid run_id FK
        string tool_id
        string tool_name
        string provider
        json input_parameters
        json output_result
        boolean success
        text error_message
        integer latency_ms
        json log_metadata
        datetime created_at
    }

    HUMAN_APPROVALS {
        uuid id PK
        uuid run_id FK
        string checkpoint_trigger
        string status "PENDING, APPROVED, REJECTED"
        string requested_by
        uuid responded_by FK
        json context_snapshot
        text reviewer_notes
        json notification_channels
        integer timeout_ms
        datetime requested_at
        datetime responded_at
    }

    USAGE_LOGS {
        uuid id PK
        datetime timestamp
        uuid company_id FK
        uuid run_id FK
        uuid sku_id FK
        numeric raw_quantity
        numeric calculated_cost
        json log_metadata
    }

    DOCUMENTS {
        uuid id PK
        uuid company_id FK
        uuid entity_id FK
        string filename
        string file_type
        string file_size
        string upload_status
        datetime created_at
        datetime updated_at
    }

    DOCUMENT_CHUNKS {
        uuid id PK
        uuid document_id FK
        string chunk_index
        text content
        vector embedding
        datetime created_at
    }
```

## 2. Table Descriptions

### 2.1 Core Platform Tables
- **companies**: Manages the multi-tenant hierarchy (Partners, Tenants).
- **users**: System users with role-based access control.
- **refresh_tokens**: Manages secure persistent sessions.

### 2.2 AI Entity Schema
- **hierarchical_entities**: The primary repository for all intelligence units. Uses JSONB columns for modular configuration blocks (Identity, Logic, Planning, etc.).
- **documents**: Catalog of uploaded documents for RAG (Knowledge Base).
- **document_chunks**: Processed text fragments with vector embeddings for semantic search.

### 2.3 Execution & Logging
- **execution_runs**: Tracks every execution instance, including hierarchical relationships for nested sub-units.
- **llm_interaction_logs**: Atomic record of every LLM prompt and completion, including token usage and cost.
- **tool_interaction_logs**: Audits of external tool calls made during execution.
- **human_approvals**: Manages HITL (Human-In-The-Loop) checkpoints.

### 2.4 Integration & Billing
- **integration_registry**: Catalog of available service SKUs (Models, Tools) and their internal costs.
- **usage_logs**: The source of truth for all resource consumption across the platform.

---
**Version**: 0.2.0 (Phase 3)  
**Last Updated**: Dec 27, 2025
