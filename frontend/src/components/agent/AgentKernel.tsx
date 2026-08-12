/**
 * components/agent/AgentKernel — Phase 11 building blocks.
 *
 * One file holds the small visual primitives:
 *   - BudgetBar           — multi-segment Budget pressure bar
 *   - ExecutorBadge       — colour-coded executor pill
 *   - ResumeIndicator     — "resumed from iter N" marker
 *   - CriticVerdictChip   — verdict chip (PASS / REVISE / REJECT / BLOCK)
 *   - FailureTagChip      — single FailureTag pill with hover-tooltip
 *   - RetryStrategyBadge  — retry-strategy badge
 *   - ProvenanceRibbon    — provenance + trust-score badge for CORTEX nodes
 *
 * Larger compositions live in sibling files (AgentStatePanel,
 * IterationCard, AgentLoopTimeline, ReflectionsList).
 */
import React from 'react';

import type {
    BudgetSnapshot,
    ExecutorName,
    FailureTag,
    PostCriticVerdictKind,
    PreCriticVerdictKind,
    ProvenanceBlock,
    RetryStrategy,
    SupervisorRecommendation,
} from '@/types/agentKernel';

import './AgentKernel.css';

// ---------------------------------------------------------------------------
// Budget bar
// ---------------------------------------------------------------------------

interface BudgetBarProps {
    budget: BudgetSnapshot;
    compact?: boolean;
}

function _pct(used: number, max: number): number {
    if (!max || max <= 0) return 0;
    return Math.max(0, Math.min(100, (used / max) * 100));
}

export const BudgetBar: React.FC<BudgetBarProps> = ({ budget, compact }) => {
    const usdUsed = Number(budget.usd_used ?? 0);
    const usdMax = Number(budget.usd_max ?? 0);
    const dims = [
        { label: '$', used: usdUsed, max: usdMax, fmt: (n: number) => `$${n.toFixed(4)}` },
        { label: 'tok', used: budget.tokens_used, max: budget.tokens_max, fmt: (n: number) => `${n}` },
        { label: 's', used: budget.wall_used_s, max: budget.wall_max_s, fmt: (n: number) => `${n}s` },
        { label: 'it', used: budget.iters, max: budget.iters_max, fmt: (n: number) => `${n}` },
    ];
    const pressure = Math.max(...dims.map((d) => _pct(d.used, d.max))) / 100;

    return (
        <div className={`agentk-budget-bar ${compact ? 'compact' : ''}`}>
            <div className="agentk-budget-bar__pressure" title={`pressure ${(pressure * 100).toFixed(0)}%`}>
                <div
                    className="agentk-budget-bar__fill"
                    style={{ width: `${pressure * 100}%`,
                              background: pressure > 0.85 ? 'var(--color-danger, #d33)' :
                                          pressure > 0.5 ? 'var(--color-warning, #d80)' :
                                                            'var(--color-success, #2a8)' }}
                />
            </div>
            <div className="agentk-budget-bar__dims">
                {dims.map((d) => (
                    <span key={d.label} className="agentk-budget-bar__dim">
                        <span className="agentk-budget-bar__dim-label">{d.label}</span>
                        <span className="agentk-budget-bar__dim-value">
                            {d.fmt(d.used)} / {d.fmt(d.max)}
                        </span>
                    </span>
                ))}
            </div>
        </div>
    );
};

// ---------------------------------------------------------------------------
// Executor badge
// ---------------------------------------------------------------------------

const _EXECUTOR_COLORS: Record<ExecutorName, string> = {
    DAG:         '#5b6fff',
    Recursive:   '#a06fff',
    SingleStep:  '#2a8',
    ChildEntity: '#d80',
    Dialog:      '#888',
    ToolBurst:   '#888',
    Skill:       '#0aa',
};

export const ExecutorBadge: React.FC<{ executor?: ExecutorName | string }> = ({
    executor,
}) => {
    if (!executor) return null;
    const color = (_EXECUTOR_COLORS as Record<string, string>)[executor] ?? '#888';
    return (
        <span className="agentk-exec-badge" style={{ borderColor: color, color }}>
            {executor}
        </span>
    );
};

// ---------------------------------------------------------------------------
// Resume indicator
// ---------------------------------------------------------------------------

export const ResumeIndicator: React.FC<{ fromIteration?: number }> = ({
    fromIteration,
}) => {
    if (typeof fromIteration !== 'number') return null;
    return (
        <span
            className="agentk-resume-indicator"
            title={`Worker resumed at iteration ${fromIteration}`}
        >
            ⟲ resumed
        </span>
    );
};

// ---------------------------------------------------------------------------
// Verdict chips
// ---------------------------------------------------------------------------

type AnyVerdict =
    | PreCriticVerdictKind
    | PostCriticVerdictKind
    | SupervisorRecommendation
    | 'PASS'
    | 'BLOCK'
    | 'REVISE'
    | 'REJECT';

const _VERDICT_COLORS: Record<string, string> = {
    PASS:     '#2a8',
    REVISE:   '#d80',
    REJECT:   '#d33',
    BLOCK:    '#d33',
    CONTINUE: '#2a8',
    REPLAN:   '#d80',
    ABORT:    '#d33',
    PAUSE:    '#888',
};

export interface VerdictChipProps {
    label: string;
    verdict?: AnyVerdict | null;
    title?: string;
}

export const CriticVerdictChip: React.FC<VerdictChipProps> = ({
    label,
    verdict,
    title,
}) => {
    if (!verdict) return null;
    const color = _VERDICT_COLORS[verdict] ?? '#888';
    return (
        <span
            className="agentk-verdict-chip"
            style={{ background: color }}
            title={title ?? `${label}: ${verdict}`}
        >
            {label}: <strong>{verdict}</strong>
        </span>
    );
};

// ---------------------------------------------------------------------------
// FailureTag chip
// ---------------------------------------------------------------------------

const _SEVERITY_BY_TAG: Record<FailureTag, 'low' | 'med' | 'high' | 'critical'> = {
    OFF_TOPIC: 'med',
    HALLUCINATION: 'high',
    INCOMPLETE: 'low',
    WRONG_FORMAT: 'low',
    TOOL_FAILURE: 'med',
    CONTRADICTION: 'med',
    UNVERIFIABLE: 'med',
    POLICY_VIOLATION: 'critical',
    UNDER_BUDGET: 'low',
    OVER_BUDGET: 'med',
    BLOCKED_DEPENDENCY: 'low',
    NEEDS_CLARIFICATION: 'low',
};

const _SEVERITY_COLORS: Record<'low' | 'med' | 'high' | 'critical', string> = {
    low:      '#888',
    med:      '#d80',
    high:     '#d33',
    critical: '#c00',
};

export const FailureTagChip: React.FC<{ tag: FailureTag }> = ({ tag }) => {
    const sev = _SEVERITY_BY_TAG[tag] ?? 'low';
    return (
        <span
            className="agentk-failure-chip"
            style={{ borderColor: _SEVERITY_COLORS[sev], color: _SEVERITY_COLORS[sev] }}
            title={`Failure tag ${tag} (severity: ${sev})`}
        >
            {tag.replace(/_/g, ' ').toLowerCase()}
        </span>
    );
};

// ---------------------------------------------------------------------------
// Retry strategy badge
// ---------------------------------------------------------------------------

export const RetryStrategyBadge: React.FC<{ strategy?: RetryStrategy | null }> = ({
    strategy,
}) => {
    if (!strategy || strategy === 'NONE') return null;
    return (
        <span className="agentk-retry-badge" title={`Strategist queued: ${strategy}`}>
            retry ▸ {strategy.replace(/^RETRY_/, '').replace(/_/g, ' ').toLowerCase()}
        </span>
    );
};

// ---------------------------------------------------------------------------
// Provenance ribbon (Track 6)
// ---------------------------------------------------------------------------

const _PROV_COLORS: Record<string, string> = {
    user_upload:    '#2a8',
    manual:         '#2a8',
    dreaming:       '#a06fff',
    tool:           '#5b6fff',
    reflection:     '#888',
    context_source: '#888',
    external_link:  '#d80',
};

export const ProvenanceRibbon: React.FC<{ provenance?: ProvenanceBlock | null }> = ({
    provenance,
}) => {
    if (!provenance) return null;
    const color = _PROV_COLORS[provenance.source_type] ?? '#888';
    const trustPct = Math.round((provenance.trust_score ?? 0) * 100);
    return (
        <span className="agentk-prov-ribbon" style={{ borderColor: color }}>
            <span className="agentk-prov-ribbon__source" style={{ color }}>
                {provenance.source_type.replace(/_/g, ' ')}
            </span>
            <span
                className="agentk-prov-ribbon__trust"
                title={`Trust score ${trustPct}%`}
                style={{ background: color }}
            >
                {trustPct}%
            </span>
            {provenance.url ? (
                <a
                    href={provenance.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="agentk-prov-ribbon__url"
                >
                    source ↗
                </a>
            ) : null}
        </span>
    );
};
