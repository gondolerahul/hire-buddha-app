import { apiClient } from './api.client';

// ── Common Types ─────────────────────────────────────────────────────────────

export interface ExecutionHealthData {
    status_breakdown: { status: string; count: number; avg_execution_ms: number; avg_cost_usd: number }[];
    daily_trend: Record<string, any>[];
    summary: { total_runs: number; success_rate: number; failure_rate: number; paused_count: number };
}

export interface LLMPerformanceData {
    model_breakdown: { provider: string; model: string; calls: number; avg_latency_ms: number; total_prompt_tokens: number; total_completion_tokens: number; total_cost_usd: number }[];
    latency_percentiles: { p50?: number; p90?: number; p99?: number };
    total_calls: number;
    total_cost_usd: number;
}

export interface ToolEfficacyData {
    tools: { tool_name: string; provider: string; total_calls: number; success_count: number; failure_count: number; error_rate: number; avg_latency_ms: number }[];
}

export interface HitlData {
    approvals: { id: string; run_id: string; entity_name: string; entity_type: string; status: string; checkpoint_trigger: string; requested_at: string; responded_at?: string; age_hours: number; is_overdue: boolean }[];
    status_counts: Record<string, number>;
    overdue_count: number;
    total: number;
}

export interface WalletLiabilityData {
    wallets: { company_id: string; company_name: string; company_type: string; daily_credits: number; wallet_balance: number; subscription_credits: number; total_available: number; account_model: string }[];
    totals: { total_daily_credits: number; total_wallet_balance: number; total_subscription_credits: number; total_liability: number };
}

export interface UsageBreakdownData {
    channels: { service: string; category: string; calls: number; total_quantity: number; total_cost_usd: number }[];
    daily_trend: { date: string; cost: number }[];
    total_cost_usd: number;
}

export interface TenantHealthData {
    tenants: { company_id: string; company_name: string; status: string; total_runs_30d: number; completed_runs: number; failed_runs: number; wallet_balance: number; health_score: number; at_risk: boolean }[];
}

export interface CampaignAnalyticsData {
    status_breakdown: Record<string, { count: number; avg_ms: number; total_cost: number }>;
    telephony: { total_inbound_minutes: number; total_outbound_minutes: number; total_charge_usd: number };
    ai_usage: { total_image_generations: number; total_llm_charge_usd: number };
}

export interface PersonalTasksData {
    tasks: { id: string; entity_name: string; status: string; input_data?: any; total_cost_usd: number; billed_amount?: number; total_tokens: number; execution_time_ms?: number; started_at?: string; completed_at?: string; created_at: string; error_message?: string }[];
    summary: { total: number; completed: number; failed: number; success_rate: number; total_cost_usd: number; total_execution_ms: number; estimated_time_saved_hours: number };
}

export interface AgentErrorsData {
    agents: { entity_id: string; name: string; type: string; total: number; completed: number; failed: number; error_rate: number; avg_ms: number; total_cost: number }[];
}

export interface CreditForecastData {
    wallet: { daily_credits: number; wallet_balance: number; subscription_credits: number; total_available: number; account_model: string };
    burn_rate: { avg_daily_usd: number; daily_history: { date: string; cost: number }[] };
    forecast: { days_remaining: number; depletion_date?: string; projection: { date: string; projected_balance: number }[] };
}

export interface SubscriptionMRRData {
    subscriptions: { company_id: string; company_name: string; plan_tier: number; monthly_fee: number; status: string; next_billing_date?: string; cancelled_at?: string; created_at: string }[];
    summary: { total_active: number; total_cancelled: number; mrr_usd: number; churn_rate: number; tier_distribution: { tier: number; count: number }[] };
}

export interface PartnerPerformanceData {
    partners: { partner_id: string; partner_name: string; tenant_count: number; total_revenue_usd: number; status: string }[];
}

export interface DataGrowthData {
    row_counts: Record<string, number>;
    llm_log_growth: { month: string; count: number }[];
    recommendations: { table: string; count: number; needs_archival: boolean }[];
}

// ── Service ──────────────────────────────────────────────────────────────────

const BASE = '/reports/analytics';

export const reportsService = {
    getExecutionHealth: (days = 30, globalView = false) =>
        apiClient.get<ExecutionHealthData>(`${BASE}/execution-health?days=${days}&global_view=${globalView}`).then(r => r.data),

    getLLMPerformance: (days = 30, globalView = false) =>
        apiClient.get<LLMPerformanceData>(`${BASE}/llm-performance?days=${days}&global_view=${globalView}`).then(r => r.data),

    getToolEfficacy: (days = 30, globalView = false) =>
        apiClient.get<ToolEfficacyData>(`${BASE}/tool-efficacy?days=${days}&global_view=${globalView}`).then(r => r.data),

    getHitlOverview: (days = 30, globalView = false) =>
        apiClient.get<HitlData>(`${BASE}/hitl-overview?days=${days}&global_view=${globalView}`).then(r => r.data),

    getWalletLiability: () =>
        apiClient.get<WalletLiabilityData>(`${BASE}/wallet-liability`).then(r => r.data),

    getUsageBreakdown: (days = 30) =>
        apiClient.get<UsageBreakdownData>(`${BASE}/usage-breakdown?days=${days}`).then(r => r.data),

    getTenantHealth: () =>
        apiClient.get<TenantHealthData>(`${BASE}/tenant-health`).then(r => r.data),

    getCampaignAnalytics: (days = 30) =>
        apiClient.get<CampaignAnalyticsData>(`${BASE}/campaign-analytics?days=${days}`).then(r => r.data),

    getPersonalTasks: (limit = 50, status?: string) => {
        const qs = status ? `limit=${limit}&status=${status}` : `limit=${limit}`;
        return apiClient.get<PersonalTasksData>(`${BASE}/personal-tasks?${qs}`).then(r => r.data);
    },

    getAgentErrors: (days = 30) =>
        apiClient.get<AgentErrorsData>(`${BASE}/agent-errors?days=${days}`).then(r => r.data),

    getCreditForecast: () =>
        apiClient.get<CreditForecastData>(`${BASE}/credit-forecast`).then(r => r.data),

    getSubscriptionMRR: () =>
        apiClient.get<SubscriptionMRRData>(`${BASE}/subscription-mrr`).then(r => r.data),

    getPartnerPerformance: () =>
        apiClient.get<PartnerPerformanceData>(`${BASE}/partner-performance`).then(r => r.data),

    getDataGrowth: () =>
        apiClient.get<DataGrowthData>(`${BASE}/data-growth`).then(r => r.data),
};
