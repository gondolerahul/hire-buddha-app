export interface Company {
    id: string;
    name: string;
    type: 'APP' | 'PARTNER' | 'TENANT';
    parent_id?: string;
    logo_url?: string;
    status: 'active' | 'suspended';
    onboarding_status?: 'pending' | 'in_progress' | 'completed';
    // What the company may be billed in a calendar month; null = no cap (GH-18).
    monthly_spend_cap_usd?: number | null;
    // The business time zone schedules and reports use (Phase 14).
    timezone?: string;
    // How it is billed (Phase 15 T2-5).
    country_code?: string;
    billing_currency?: string;
    created_at: string;
    updated_at: string;
}

export interface User {
    id: string;
    email: string;
    full_name: string;
    role: UserRole;
    company_id: string;
    profile_picture_url?: string;
    /** How the company is billed (Phase 15 T2-5, GET /auth/me). */
    country_code?: string;
    billing_currency?: string;
    /** The workspace the screens show (Phase 15 T9-1): APP, PARTNER or TENANT, and a partner's type. */
    company_type?: 'APP' | 'PARTNER' | 'TENANT';
    partner_type?: 'SILVER' | 'GOLD' | null;
    /** An app_user's console functions (T9-12): support, sales, finance, ops. */
    staff_functions?: StaffFunction[];
    is_active: boolean;
    created_at: string;
}

export type StaffFunction = 'support' | 'sales' | 'finance' | 'ops';

export enum UserRole {
    APP_ADMIN = 'app_admin',
    PARTNER_ADMIN = 'partner_admin',
    TENANT_ADMIN = 'tenant_admin',
    APP_USER = 'app_user',
    PARTNER_USER = 'partner_user',
    TENANT_USER = 'tenant_user',
}

export interface LoginRequest {
    email: string;
    password: string;
}

export interface RegisterRequest {
    email: string;
    password: string;
    full_name: string;
    /** ISO 3166 code: the workspace is billed in its currency (Phase 15 T2-3). */
    country_code?: string;
}

export interface AuthResponse {
    access_token: string;
    refresh_token: string;
    token_type: string;
    user: User;
}

export interface ModelConfig {
    provider: string;
    model: string;
    temperature: number;
    max_tokens?: number;
    tools: string[];
}

// The six levels of the hierarchy, lowest first (R1). Every level runs the same
// way; a child sits at its parent's level or below.
export enum EntityType {
    ACTION = 'ACTION',    // 1 — a wrapper around a tool
    SKILL = 'SKILL',      // 2 — instructions, scripts and assets with a contract
    AGENT = 'AGENT',      // 3 — a role
    PROCESS = 'PROCESS',  // 4 — a business process
    LOOP = 'LOOP',        // 5 — a department or function
    GRAPH = 'GRAPH',      // 6 — the entire business
}

export enum EntityStatus {
    DRAFT = 'DRAFT',
    ACTIVE = 'ACTIVE',
    DEPRECATED = 'DEPRECATED',
    ARCHIVED = 'ARCHIVED',
}

export enum RunStatus {
    PENDING = 'PENDING',
    RUNNING = 'RUNNING',
    COMPLETED = 'COMPLETED',
    FAILED = 'FAILED',
    REFINING = 'REFINING',
}

// ---------------------------------------------------------------------------
// Standardized Persona Schema (matches backend schemas.py AgentPersona)
// ---------------------------------------------------------------------------

export interface PersonaExample {
    scenario: string;
    ideal_response: string;
}

/** Voice identity for Gemini Live API sessions. */
export interface VoiceConfig {
    /** Prebuilt Gemini voice. 18 options: Puck, Charon, Kore, Fenrir, Aoede, Orbit, Zephyr, Leda,
     *  Orus, Rigel, Schedar, Pulcherrima, Achird, Zubenelgenubi, Vindemiatrix, Sadachbia, Sadaltager, Sulafat */
    voice_name: string;
    language_code: string;      // BCP-47, e.g. "en-US"; native-audio models choose their own
    // No speaking rate or pitch: Gemini Live has neither (VT-11).
    custom_voice_id?: string;   // Future: custom voice clone reference
}

/** Behavioral fingerprint injected into system prompt at runtime. */
export interface PersonalityMatrix {
    tone: string;               // professional | friendly | formal | empathetic | assertive | casual
    verbosity: string;          // concise | moderate | verbose
    empathy_level: number;      // 0.0 – 1.0
    humor_level: number;        // 0.0 – 1.0
    formality: string;          // formal | semi-formal | casual
    decision_confidence: number; // 0.0 – 1.0 (confidence threshold before escalating)
}

/** Canonical, standardized persona for HierarchicalEntity.identity */
export interface AgentPersona {
    // Core identity
    name: string;
    role: string;
    bio?: string;

    // Visual identity
    profile_image_url?: string;
    profile_image_thumbnail_url?: string;

    // Behavioral fingerprint
    personality: PersonalityMatrix;

    // Voice identity (for Gemini Live sessions)
    voice: VoiceConfig;

    // Prompt engineering
    system_prompt: string;
    behavioral_constraints: string[];
    few_shot_examples?: { [key: string]: string }[];

    // Dynamic injection hooks
    greeting_template?: string;
    escalation_message?: string;
    closing_message?: string;
}

/** Legacy persona model — kept for backward compatibility. */
export interface Persona {
    system_prompt: string;
    examples: PersonaExample[];
    behavioral_constraints: string[];
    few_shot_examples?: { [key: string]: string }[];
}

export interface HierarchyChild {
    child_id: string;
    child_type: EntityType;
    relationship: 'SEQUENTIAL' | 'PARALLEL' | 'CONDITIONAL';
    condition?: {
        enabled: boolean;
        expression?: string;
        description?: string;
    };
}

export interface Hierarchy {
    parent_id?: string;
    children: HierarchyChild[];
    is_atomic: boolean;
    composition_depth: number;
}

export interface ContextPolicy {
    type: 'FULL' | 'LAST_N' | 'SLIDING_WINDOW' | 'EXPLICIT';
    n?: number;
    max_chars?: number;
    summarize_threshold?: number;
    explicit_keys?: string[];
    /** Domain-specific keys to always preserve verbatim during context summarization */
    preserve_keys?: string[];
}

export interface LogicGate {
    reasoning_config: {
        task_type?: string;
        model_provider?: string;
        model_name?: string;
        temperature: number;
        top_p?: number;
        max_tokens?: number;
        reasoning_mode: 'REACT' | 'CHAIN_OF_THOUGHT' | 'REFLECTION' | 'TREE_OF_THOUGHTS';
        // Declared by the backend's ReasoningConfig (ai/schemas/reasoning.py).
        execution_mode?: 'STANDARD' | 'AUTONOMOUS' | string;
        goal_validation_interval?: number;   // retired (P7.8): read from governance
        confidence_threshold?: number;
        max_replanning_attempts?: number;
        self_reflection_enabled?: boolean;
    };
    retry_policy: {
        max_retries: number;
        backoff_strategy: 'LINEAR' | 'EXPONENTIAL' | 'NONE';
        backoff_multiplier?: number;
    };
    review_mechanism: {
        enabled: boolean;
        review_prompt?: string;
        review_system_prompt?: string;  // Base review prompt (overridable)
        on_failure?: 'RETRY' | 'ESCALATE' | 'ABORT';
        success_criteria?: any[];
    };
    context_policy?: ContextPolicy;
}

export interface PlanStepTarget {
    entity_id?: string;
    tool_id?: string;
    prompt_template?: string;
    input_dependencies?: string[];
}

export interface PlanStep {
    step_id: string;
    order: number;
    name: string;
    description?: string;
    type: 'ACTION' | 'TOOL_CALL' | 'CHILD_ENTITY_INVOCATION' | 'THOUGHT';
    target?: PlanStepTarget;
    required: boolean;
    exit_conditions?: any[];
}

export interface Planning {
    static_plan: {
        enabled: boolean;
        steps: PlanStep[];
        fallback_behavior?: 'STRICT' | 'ADAPTIVE' | 'DYNAMIC_ONLY';
    };
    dynamic_planning: {
        enabled: boolean;
        planning_prompt?: string;
        planning_system_prompt?: string;  // Base planning prompt (overridable)
        constraints?: string[];
        reconciliation_strategy?: 'STATIC_PRIORITY' | 'DYNAMIC_PRIORITY' | 'HYBRID';
        allowed_deviations?: {
            can_add_steps: boolean;
            can_skip_optional_steps: boolean;
            can_reorder_steps: boolean;
            can_change_tools: boolean;
        };
    };
}

export type ToolUsage = 'AUTONOMOUS' | 'PLANNED' | 'BOTH';

export interface ToolDefinition {
    tool_id: string;
    name?: string;
    description?: string;
    provider?: string;
    /** How the tool is used: AUTONOMOUS (LLM decides), PLANNED (deterministic step), BOTH */
    usage?: ToolUsage;
    /** Permission declarations: read | write | execute | network | storage */
    permissions?: string[];
    sandbox_mode?: boolean;
    max_execution_seconds?: number;
    rate_limit_per_run?: number;
    access_level?: 'READ' | 'WRITE' | 'EXECUTE';
}

export interface CortexMemoryConfig {
    max_children?: number;
    page_size_tokens?: number;
    context_budget_pct?: number;
    auto_checkpoint?: boolean;
    resume_enabled?: boolean;
}

export interface ContextSource {
    source_type: 'DOCUMENT' | 'KNOWLEDGE_BASE' | 'CORTEX_TREE' | 'DB_RECORDS';
    reference_id: string;
    description?: string;
    // Display metadata for UI
    file_name?: string;
    file_type?: string;
    file_size?: number;
    tree_status?: string;
    tree_node_count?: number;
}

export interface Capabilities {
    tools: ToolDefinition[];
    memory: {
        enabled: boolean;
        mode: 'STANDARD' | 'CORTEX';
        episodic_memory_count?: number;
        semantic_search_enabled?: boolean;
        semantic_top_k?: number;
        cortex_config?: CortexMemoryConfig;
    };
    context_engineering: {
        context_sources?: ContextSource[];
        inject_episodic_memory?: boolean;
        inject_semantic_context?: boolean;
        inject_cortex_viewport?: boolean;
        no_truncation?: boolean;
    };
    /** The agent's Automation tab (Phase 14 WS3): may triggers run it; whom it may schedule. */
    automation?: {
        triggerable?: boolean;
        can_schedule?: string[];
    };
}

export type HITLTriggerType = 'BEFORE_STEP' | 'AFTER_STEP' | 'COST_THRESHOLD' | 'TOOL_CALL' | 'CUSTOM';

export interface HITLCheckpoint {
    trigger_type: HITLTriggerType;
    step_ref?: string;              // For BEFORE_STEP/AFTER_STEP: step name or step_id
    tool_ref?: string;              // For TOOL_CALL: tool_id to gate
    threshold?: number;             // For COST_THRESHOLD: USD amount
    expression?: string;            // For CUSTOM: boolean expression
    timeout_ms: number;             // How long to wait for approval (default 5 min)
    notification_channels: string[];// e.g. ["email", "slack", "dashboard"]
    message?: string;               // Custom message shown to the reviewer
    auto_approve_on_timeout: boolean;
}

/** What one run of an agent may be billed, in the company's currency (Phase 15 T5-7). */
export interface MaxBill {
    amount: string | number;
    currency?: string | null;
}

export interface Governance {
    /** The budget's raw-cost equivalent, derived from `max_bill` on save; staff only. */
    max_cost_usd?: number;
    max_bill?: MaxBill | null;
    timeout_ms: number;
    max_recursion_depth?: number;   // how deep the tree below this entity may go (enforced)
    checkpoint_every_n_steps?: number;
    goal_validation_interval?: number;   // alignment critic every N iterations (the one setting, PC-17)
    execution_limits?: {
        max_recursion_depth?: number;   // old spelling, folded into max_recursion_depth
        max_tool_calls?: number;
    };
    hitl_checkpoints: HITLCheckpoint[];
}

export interface IOContract {
    input_schema: any;
    output_schema: any;
}

export interface Observability {
    log_level: string;
    log_thoughts: boolean;
    track_cost: boolean;
}

export interface HierarchicalEntity {
    id: string;
    company_id: string;
    parent_id?: string;
    name: string;
    display_name?: string;
    description?: string;
    goal?: string;
    type: EntityType;
    version: string;
    status: EntityStatus;
    tags: string[];
    is_template?: boolean;
    template_source_id?: string;
    created_by?: string;

    /** AgentPersona (new standardized) or legacy Persona */
    identity?: AgentPersona | Persona | any;
    hierarchy?: Hierarchy;
    logic_gate?: LogicGate;
    planning?: Planning;
    capabilities?: Capabilities;
    governance?: Governance;
    io_contract?: IOContract;
    observability?: Observability;
    metadata_extensions?: any;

    created_at: string;
    updated_at: string;
}

export interface LLMInteractionLog {
    id: string;
    run_id: string;
    model_provider: string;
    model_name: string;
    input_prompt: string;
    output_response: string;
    prompt_tokens: number;
    completion_tokens: number;
    latency_ms?: number;
    /** Staff only: absent for tenants and partners (Phase 15 T9-3). */
    cost_usd?: number;
    reasoning_mode?: string;
    step_name?: string;
    created_at: string;
}

export interface ToolInteractionLog {
    id: string;
    run_id: string;
    tool_id: string;
    tool_name: string;
    /** The plan step that made the call (FE-10); null on calls logged before it existed. */
    step_name?: string | null;
    input_parameters?: Record<string, any> | null;
    error_message?: string | null;
    output_result?: any;
    success: boolean;
    latency_ms?: number;
    created_at: string;
}

/** What the reviewer is approving — built by backend governance/hitl_snapshot.py. */
export interface HITLContextSnapshot {
    message?: string;
    trigger_type?: string;
    phase?: 'BEFORE' | 'AFTER';
    entity_name?: string;
    step_name?: string;
    step_type?: string;
    step_description?: string;
    tool_id?: string;
    step_prompt?: string;
    run_input?: string;
    step_output?: string;
    run_cost_usd?: number;
}

export interface HumanApproval {
    id: string;
    run_id: string;
    checkpoint_trigger: string;
    status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'TIMEOUT';
    requested_at: string;
    responded_at?: string;
    timeout_ms?: number;
    context_snapshot?: HITLContextSnapshot;
}

export interface ExecutionRun {
    id: string;
    entity_id: string;
    parent_run_id?: string;   // structure: the run that dispatched this one as a child
    retry_of_run_id?: string; // the run this one retries or refines
    depth?: number;           // how many parents this run has; 0 for a top-level run
    max_depth?: number;       // the deepest a descendant of this run may go
    company_id: string;
    status: RunStatus;
    input_data?: any;
    dynamic_plan?: any;
    result_data?: any;
    context_state?: any;
    error_message?: string;

    /** Raw provider cost: staff only — absent for tenants and partners (Phase 15 T9-3). */
    total_cost_usd?: number;
    billed_amount?: number;  // TB formula result — the user-facing charge
    /** The currency of `billed_amount` for a tenant's or partner's people (USD for staff). */
    billed_currency?: string;
    total_tokens: number;
    execution_time_ms?: number;
    trace_id?: string;

    started_at?: string;
    completed_at?: string;
    created_at: string;

    llm_logs?: LLMInteractionLog[];
    tool_logs?: ToolInteractionLog[];
    human_approvals?: HumanApproval[];
    child_runs?: ExecutionRun[];
    entity?: HierarchicalEntity;
}
