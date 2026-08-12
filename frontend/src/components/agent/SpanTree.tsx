/**
 * components/agent/SpanTree — Collapsible execution trace tree.
 *
 * Renders the nested span forest for one iteration:
 *   executor → step → { child, tool, llm }
 *
 * Each node shows kind, name, status, duration, cost, and token counts;
 * expanding a node reveals its full payload (tool input/output, LLM
 * prompt/response, errors). `child` nodes deep-link to the sub-run's own
 * execution detail page.
 *
 * Fed by IterationCard with the roots resolved (by parent_span_id) from the
 * merged live-SSE + REST-backfill span map.
 */
import React, { useState } from 'react';
import { Link } from 'react-router-dom';

import type { SpanKind, SpanNode, SpanStatus } from '@/types/agentKernel';

import './SpanTree.css';

const KIND_ICON: Record<SpanKind, string> = {
    iteration: '🔄',
    executor: '⚙️',
    step: '▸',
    child: '🧬',
    tool: '🔧',
    llm: '🧠',
    critic: '⚖️',
};

const STATUS_LABEL: Record<SpanStatus, string> = {
    running: 'running',
    success: 'ok',
    error: 'error',
};

function fmtDuration(ms?: number | null): string {
    if (ms == null) return '';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
}

function fmtPayloadValue(v: unknown): string {
    if (v == null) return '';
    if (typeof v === 'string') return v;
    try {
        return JSON.stringify(v, null, 2);
    } catch {
        return String(v);
    }
}

/** Payload keys worth surfacing first, in order. */
const PAYLOAD_ORDER = [
    'instruction',
    'description',
    'system_prompt',
    'user_prompt',
    'args',
    'input',
    'response',
    'output',
    'skip_reason',
];

const SpanRow: React.FC<{ node: SpanNode; depth: number }> = ({ node, depth }) => {
    const [open, setOpen] = useState(false);
    const hasChildren = node.children.length > 0;
    const payload = node.payload ?? {};
    const payloadKeys = Object.keys(payload).filter((k) => payload[k] != null && payload[k] !== '');
    const orderedKeys = [
        ...PAYLOAD_ORDER.filter((k) => payloadKeys.includes(k)),
        ...payloadKeys.filter((k) => !PAYLOAD_ORDER.includes(k)),
    ];
    const expandable = orderedKeys.length > 0 || !!node.error;

    return (
        <div className="agentk-span" style={{ ['--depth' as string]: depth }}>
            <div
                className={`agentk-span__row agentk-span__row--${node.status} ${expandable ? 'agentk-span__row--clickable' : ''}`}
                onClick={() => expandable && setOpen((o) => !o)}
            >
                <span className="agentk-span__caret">
                    {expandable ? (open ? '▾' : '▸') : ''}
                </span>
                <span className="agentk-span__icon">{KIND_ICON[node.kind] ?? '•'}</span>
                <span className={`agentk-span__kind agentk-span__kind--${node.kind}`}>
                    {node.kind}
                </span>
                <span className="agentk-span__name" title={node.name ?? ''}>
                    {node.name ?? '—'}
                </span>
                <span className={`agentk-span__status agentk-span__status--${node.status}`}>
                    {STATUS_LABEL[node.status]}
                </span>
                {node.duration_ms != null && (
                    <span className="agentk-span__metric">{fmtDuration(node.duration_ms)}</span>
                )}
                {node.cost_usd != null && node.cost_usd > 0 && (
                    <span className="agentk-span__metric" title="cost">
                        ${node.cost_usd.toFixed(4)}
                    </span>
                )}
                {(node.tokens_in != null || node.tokens_out != null) && (
                    <span className="agentk-span__metric" title="tokens in/out">
                        {node.tokens_in ?? 0}/{node.tokens_out ?? 0} tok
                    </span>
                )}
                {node.child_run_id && (
                    <Link
                        className="agentk-span__childlink"
                        to={`/ai/executions/${node.child_run_id}`}
                        onClick={(e) => e.stopPropagation()}
                    >
                        open sub-run ↗
                    </Link>
                )}
            </div>

            {open && (
                <div className="agentk-span__detail">
                    {node.error && (
                        <div className="agentk-span__field agentk-span__field--error">
                            <div className="agentk-span__field-key">error</div>
                            <pre className="agentk-span__field-val">{node.error}</pre>
                        </div>
                    )}
                    {orderedKeys.map((k) => (
                        <div className="agentk-span__field" key={k}>
                            <div className="agentk-span__field-key">
                                {k}
                                <button
                                    className="agentk-span__copy"
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        void navigator.clipboard?.writeText(
                                            fmtPayloadValue(payload[k]),
                                        );
                                    }}
                                >
                                    copy
                                </button>
                            </div>
                            <pre className="agentk-span__field-val">
                                {fmtPayloadValue(payload[k])}
                            </pre>
                        </div>
                    ))}
                </div>
            )}

            {hasChildren && (
                <div className="agentk-span__children">
                    {node.children.map((c) => (
                        <SpanRow key={c.span_id} node={c} depth={depth + 1} />
                    ))}
                </div>
            )}
        </div>
    );
};

export const SpanTree: React.FC<{ roots: SpanNode[] }> = ({ roots }) => {
    if (!roots.length) return null;
    return (
        <div className="agentk-span-tree">
            {roots.map((r) => (
                <SpanRow key={r.span_id} node={r} depth={0} />
            ))}
        </div>
    );
};
